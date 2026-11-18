"""Wire contract v1: the one envelope every model call uses, shared by the game client and the model server.

Stdlib only. The game never imports a model library; it speaks this contract over HTTP. Anything that can accept an
``Envelope`` and return a ``ResponseEnvelope`` (a mock, a rules server, a hosted model behind an adapter) can be plugged in.
JSON Schema and OpenAPI are generated from these dataclasses (``model_server/schema.py``), so the documents cannot drift.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from typing import Any, Optional

SCHEMA_VERSION = 1
ROLES = ("decide", "resident", "dialogue", "world")
PRIORITIES = ("critical", "active", "background")
PROVIDER_MODES = ("rules", "mock", "recorded", "live", "fallback")
QUESTION_KINDS = ("choice", "yes_no")
# Modes of the batch roles. They are the legacy hook modes (implement_llm.md); ``resident_reasoning`` arrives through
# the legacy *world* handler but is a resident-role call (plans and goals for one resident).
# ``plan_ops`` (resident) and ``director`` (world) are the async-native Tier 3 modes of round 2 (1008_tier3.md): typed context in, a plan of
# verb steps / a list of power intents out, both validated again by the game before anything runs. They do not exist in the legacy hooks.
ROLE_MODES = {
    "resident": ("urgent_react", "normal_live", "resident_reasoning", "plan_ops"),
    "dialogue": ("talk_reply", "ambient_npc_talk"),
    "world": ("decree", "director"),
}
LEGACY_MODE_ROLE = {mode: role for role, modes in ROLE_MODES.items() for mode in modes}
ROLE_ROUTES = {"decide": "/v1/decide", "resident": "/v1/resident", "dialogue": "/v1/dialogue", "world": "/v1/world"}
ROLE_TIER = {"decide": 2, "resident": 3, "dialogue": 3, "world": 3}  # Tier 1 (matrix) is local and has no wire role
MAX_CASES = 32
MAX_SPEECH_CHARS = 500
MAX_OPTIONS = 64
MAX_PLAN_STEPS = 8
MAX_INTENTS = 6
ERROR_CODES = ("malformed_request", "schema_version_unsupported", "unknown_role", "invalid_payload", "deadline_exceeded",
               "backend_unavailable", "backend_error", "backend_not_implemented", "cancelled", "internal_error")


class ContractError(ValueError):
    """A request or reply that breaks the contract. ``code`` is one of ERROR_CODES (or a client-side reason)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ClefMappingHeld(NotImplementedError):
    """Raised by the Clef adapters: the request/response mapping is held until the real Clef API is supplied."""


def _meta(**kw):
    """A dataclass field whose JSON Schema keywords live in its metadata; ``default`` is a real default too."""
    if "default" in kw:
        return field(default=kw["default"], metadata=kw)
    return field(metadata=kw)


@dataclass
class ErrorBody:
    code: str
    message: str = ""
    retryable: bool = False


@dataclass
class Envelope:
    """Request envelope. ``payload`` depends on ``role`` (DecidePayload, ResidentPayload, DialoguePayload, WorldPayload)."""
    job_id: str = _meta(minLength=1)
    role: str = _meta(enum=list(ROLES))
    world_epoch: str = _meta(description="Game world epoch; echoed back unchanged. A reply that disagrees is stale.")
    state_revision: int = _meta(minimum=0, description="Revision of the state the request was built from; echoed back.")
    payload: dict = _meta(description="Role specific body, see the *Payload schemas.")
    priority: str = _meta(enum=list(PRIORITIES), default="active")
    deadline_ms: int = _meta(minimum=1, maximum=60000, default=1000,
                             description="The caller stops waiting after this; a late answer is discarded.")
    cancel_token: str = _meta(default="", description="Opaque group id; POST /v1/cancel {cancel_token} abandons the work.")
    schema_version: int = _meta(default=SCHEMA_VERSION)

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "role": self.role, "world_epoch": self.world_epoch,
                "state_revision": self.state_revision, "priority": self.priority, "deadline_ms": self.deadline_ms,
                "cancel_token": self.cancel_token, "schema_version": self.schema_version, "payload": self.payload}


@dataclass
class ResponseEnvelope:
    """Reply envelope. On failure ``ok`` is false, ``error`` is set and ``result`` is empty."""
    job_id: str
    role: str
    world_epoch: str
    state_revision: int
    provider_mode: str = _meta(enum=list(PROVIDER_MODES))
    latency_ms: float = _meta(minimum=0)
    model_id: str = ""
    result: dict = field(default_factory=dict)
    ok: bool = True
    error: Optional[ErrorBody] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        body = {"job_id": self.job_id, "role": self.role, "world_epoch": self.world_epoch,
                "state_revision": self.state_revision, "schema_version": self.schema_version, "ok": self.ok,
                "provider_mode": self.provider_mode, "latency_ms": self.latency_ms, "model_id": self.model_id,
                "result": self.result}
        if self.error is not None:
            body["error"] = {"code": self.error.code, "message": self.error.message, "retryable": self.error.retryable}
        return body


# ---- role payloads and results (typed halves of the envelope) -------------------------------------------------------

@dataclass
class DecideOption:
    id: str = _meta(minLength=1)
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class DecidePayload:
    """Tier 2 (Clef-style) typed choice: options are already legal; the model returns one probability per option."""
    resident_id: str
    trigger: str = _meta(description="Event type plus causal event id, e.g. commission_request:o_000001.")
    question_kind: str = _meta(enum=list(QUESTION_KINDS))
    options: list[DecideOption] = _meta(minItems=1, maxItems=MAX_OPTIONS)
    tick: int = 0
    topic: str = "generic"
    state: dict = field(default_factory=dict)


@dataclass
class DecideResult:
    probabilities: dict[str, float] = _meta(description="Exactly the offered option ids; finite, >= 0, sum 1 (+-1e-3).")


@dataclass
class PacketResponse:
    """One answer per case, in the same order. ``packet`` keeps the legacy structured contract (implement_llm.md)."""
    packet: dict
    source: str = ""


@dataclass
class ResidentPayload:
    """Tier 3 ``resident``: urgent_react / normal_live (tiny reactions) and resident_reasoning (goals and plans)."""
    mode: str = _meta(enum=list(ROLE_MODES["resident"]))
    cases: list[dict] = _meta(minItems=1, maxItems=MAX_CASES)


@dataclass
class ResidentResult:
    mode: str = _meta(enum=list(ROLE_MODES["resident"]))
    responses: list[PacketResponse] = _meta(minItems=1, maxItems=MAX_CASES)


@dataclass
class DialoguePayload:
    """Tier 3 ``dialogue``: wording from an already decided outcome (talk_reply, ambient_npc_talk)."""
    mode: str = _meta(enum=list(ROLE_MODES["dialogue"]))
    cases: list[dict] = _meta(minItems=1, maxItems=MAX_CASES)


@dataclass
class DialogueResult:
    mode: str = _meta(enum=list(ROLE_MODES["dialogue"]))
    responses: list[PacketResponse] = _meta(minItems=1, maxItems=MAX_CASES)


@dataclass
class WorldPayload:
    """Tier 3 ``world``: god decrees and world operations. The reply is a packet; Python validates and executes it."""
    mode: str = _meta(enum=list(ROLE_MODES["world"]))
    cases: list[dict] = _meta(minItems=1, maxItems=MAX_CASES)


@dataclass
class WorldResult:
    mode: str = _meta(enum=list(ROLE_MODES["world"]))
    responses: list[PacketResponse] = _meta(minItems=1, maxItems=MAX_CASES)


PAYLOAD_TYPES = {"decide": DecidePayload, "resident": ResidentPayload, "dialogue": DialoguePayload, "world": WorldPayload}
RESULT_TYPES = {"decide": DecideResult, "resident": ResidentResult, "dialogue": DialogueResult, "world": WorldResult}
ALL_TYPES = (Envelope, ResponseEnvelope, ErrorBody, DecideOption, DecidePayload, DecideResult, PacketResponse, ResidentPayload,
             ResidentResult, DialoguePayload, DialogueResult, WorldPayload, WorldResult)


# ---- validation -----------------------------------------------------------------------------------------------------

def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse_envelope(data: Any) -> Envelope:
    """Strictly parse a request body. Raises ContractError (malformed_request / schema_version_unsupported / unknown_role)."""
    if not isinstance(data, dict):
        raise ContractError("malformed_request", "body must be a JSON object")
    version = data.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION or not _is_int(version):
        raise ContractError("schema_version_unsupported", f"this server speaks schema_version {SCHEMA_VERSION}, got {version!r}")
    role = data.get("role")
    if role not in ROLES:
        raise ContractError("unknown_role", f"role must be one of {list(ROLES)}, got {role!r}")
    for key in ("job_id", "world_epoch"):
        if not _nonempty_str(data.get(key)):
            raise ContractError("malformed_request", f"{key} must be a non-empty string")
    if not _is_int(data.get("state_revision")) or data["state_revision"] < 0:
        raise ContractError("malformed_request", "state_revision must be an integer >= 0")
    priority = data.get("priority", "active")
    if priority not in PRIORITIES:
        raise ContractError("malformed_request", f"priority must be one of {list(PRIORITIES)}")
    deadline = data.get("deadline_ms", 1000)
    if not _is_int(deadline) or not 1 <= deadline <= 60000:
        raise ContractError("malformed_request", "deadline_ms must be an integer in 1..60000")
    token = data.get("cancel_token", "")
    if not isinstance(token, str):
        raise ContractError("malformed_request", "cancel_token must be a string")
    if not isinstance(data.get("payload"), dict):
        raise ContractError("malformed_request", "payload must be an object")
    envelope = Envelope(job_id=data["job_id"], role=role, world_epoch=data["world_epoch"], state_revision=data["state_revision"],
                        payload=data["payload"], priority=priority, deadline_ms=deadline, cancel_token=token,
                        schema_version=version)
    validate_payload(role, envelope.payload)
    return envelope


def validate_payload(role: str, payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ContractError("invalid_payload", "payload must be an object")
    if role == "decide":
        if not _nonempty_str(payload.get("resident_id")) or not _nonempty_str(payload.get("trigger")):
            raise ContractError("invalid_payload", "decide payload needs resident_id and trigger")
        if payload.get("question_kind") not in QUESTION_KINDS:
            raise ContractError("invalid_payload", f"question_kind must be one of {list(QUESTION_KINDS)}")
        options = payload.get("options")
        if not isinstance(options, list) or not 1 <= len(options) <= MAX_OPTIONS:
            raise ContractError("invalid_payload", f"options must be a list of 1..{MAX_OPTIONS} items")
        ids = []
        for option in options:
            if not isinstance(option, dict) or not _nonempty_str(option.get("id")):
                raise ContractError("invalid_payload", "every option needs a non-empty string id")
            ids.append(option["id"])
        if len(set(ids)) != len(ids):
            raise ContractError("invalid_payload", "option ids must be unique")
        if "state" in payload and not isinstance(payload["state"], dict):
            raise ContractError("invalid_payload", "state must be an object")
        return
    modes = ROLE_MODES[role]
    if payload.get("mode") not in modes:
        raise ContractError("invalid_payload", f"{role} mode must be one of {list(modes)}, got {payload.get('mode')!r}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES or not all(isinstance(c, dict) for c in cases):
        raise ContractError("invalid_payload", f"cases must be a list of 1..{MAX_CASES} objects")


def validate_probabilities(option_ids: list[str], probabilities: Any, tolerance: float = 1e-3) -> dict[str, float]:
    """Return a clean distribution over exactly ``option_ids`` or raise ContractError (option set, finiteness, sum)."""
    if not isinstance(probabilities, dict):
        raise ContractError("backend_error", "probabilities must be an object")
    if set(probabilities) != set(option_ids):
        raise ContractError("backend_error", f"probabilities must cover exactly the offered options {sorted(option_ids)}, "
                                              f"got {sorted(map(str, probabilities))}")
    clean = {}
    for key in option_ids:
        value = probabilities[key]
        if not _is_num(value) or value < 0:
            raise ContractError("backend_error", f"probability for {key!r} must be a finite number >= 0, got {value!r}")
        clean[key] = float(value)
    total = sum(clean.values())
    if abs(total - 1.0) > tolerance:
        raise ContractError("backend_error", f"probabilities must sum to 1, got {total}")
    return {key: value / total for key, value in clean.items()}


def _validate_packet(role: str, mode: str, packet: Any, case: dict) -> dict:
    """Light structural check of one legacy packet; the game's own normalisers and executors stay authoritative."""
    if not isinstance(packet, dict):
        raise ContractError("backend_error", "packet must be an object")
    if mode in ("urgent_react", "normal_live"):
        if not _nonempty_str(packet.get("intent")):
            raise ContractError("backend_error", f"{mode} packet needs a non-empty intent")
        action = packet.get("action")
        if action is not None and (not isinstance(action, dict) or not _nonempty_str(action.get("type"))):
            raise ContractError("backend_error", "action must be an object with a type")
        confidence = packet.get("confidence")
        if confidence is not None and (not _is_num(confidence) or not 0.0 <= confidence <= 1.0):
            raise ContractError("backend_error", "confidence must be a number in [0, 1]")
    elif mode == "resident_reasoning":
        if not _nonempty_str(packet.get("resident_id")):
            raise ContractError("backend_error", "resident_reasoning packet needs resident_id")
        for key in ("goal_updates", "plans"):
            if not isinstance(packet.get(key, []), list):
                raise ContractError("backend_error", f"{key} must be a list")
    elif mode in ("talk_reply", "ambient_npc_talk"):
        text = packet.get("speech_text")
        if not _nonempty_str(text) or len(text) > MAX_SPEECH_CHARS:
            raise ContractError("backend_error", f"speech_text must be a non-empty string of at most {MAX_SPEECH_CHARS} characters")
        allowed = (case.get("prompt_case") or {}).get("allowed_physical_intents")
        intent = packet.get("physical_intent", "")
        if not isinstance(intent, str) or (intent and isinstance(allowed, list) and intent not in allowed):
            raise ContractError("backend_error", f"physical_intent {intent!r} is not one of the allowed intents")
    elif mode == "plan_ops":
        if not _nonempty_str(packet.get("resident_id")):
            raise ContractError("backend_error", "plan_ops packet needs resident_id")
        confidence = packet.get("confidence")
        if not _is_num(confidence) or not 0.0 <= confidence <= 1.0:
            raise ContractError("backend_error", "plan_ops confidence must be a number in [0, 1]")
        steps = packet.get("steps")
        if not isinstance(steps, list) or len(steps) > MAX_PLAN_STEPS:
            raise ContractError("backend_error", f"steps must be a list of at most {MAX_PLAN_STEPS} items")
        for step in steps:
            if not isinstance(step, dict) or not _nonempty_str(step.get("op")) or not isinstance(step.get("args", {}), dict):
                raise ContractError("backend_error", "each step needs a non-empty op and an object args")
        if not isinstance(packet.get("summary", ""), str):
            raise ContractError("backend_error", "summary must be a string")
    elif mode == "director":
        intents = packet.get("intents")
        if not isinstance(intents, list) or len(intents) > MAX_INTENTS:
            raise ContractError("backend_error", f"intents must be a list of at most {MAX_INTENTS} items")
        for intent in intents:
            if not isinstance(intent, dict) or not _nonempty_str(intent.get("power")) or not isinstance(intent.get("args", {}), dict):
                raise ContractError("backend_error", "each intent needs a non-empty power and an object args")
        if not isinstance(packet.get("thought", ""), str):
            raise ContractError("backend_error", "thought must be a string")
    elif mode == "decree":
        for key in ("map_actions", "human_actions", "new_entities", "new_instincts"):
            if not isinstance(packet.get(key, []), list):
                raise ContractError("backend_error", f"{key} must be a list")
    return packet


def validate_result(role: str, payload: dict, result: Any) -> dict:
    """Check a backend's ``result`` against the request ``payload`` and return a clean copy, or raise ContractError."""
    if not isinstance(result, dict):
        raise ContractError("backend_error", "result must be an object")
    if role == "decide":
        ids = [option["id"] for option in payload["options"]]
        return {"probabilities": validate_probabilities(ids, result.get("probabilities"))}
    mode = payload["mode"]
    if result.get("mode", mode) != mode:
        raise ContractError("backend_error", f"result mode {result.get('mode')!r} does not match request mode {mode!r}")
    responses = result.get("responses")
    cases = payload["cases"]
    if not isinstance(responses, list) or len(responses) != len(cases):
        raise ContractError("backend_error", f"responses must be a list with one entry per case ({len(cases)})")
    clean = []
    for case, response in zip(cases, responses):
        if not isinstance(response, dict):
            raise ContractError("backend_error", "each response must be an object with a packet")
        packet = _validate_packet(role, mode, response.get("packet"), case)
        clean.append({"packet": packet, "source": str(response.get("source", ""))})
    return {"mode": mode, "responses": clean}


def parse_response(data: Any, request: Envelope) -> ResponseEnvelope:
    """Client side: parse and verify a reply to ``request``. Echo mismatches raise ContractError('stale_reply')."""
    if not isinstance(data, dict):
        raise ContractError("bad_reply", "reply must be a JSON object")
    if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ContractError("bad_reply", f"reply schema_version {data.get('schema_version')!r} unsupported")
    if data.get("ok") is not True:
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        raise ContractError(str(error.get("code", "backend_error")), str(error.get("message", "server reported failure")))
    if data.get("job_id") != request.job_id or data.get("role") != request.role:
        raise ContractError("stale_reply", "reply job_id/role does not match the request")
    if data.get("world_epoch") != request.world_epoch or data.get("state_revision") != request.state_revision:
        raise ContractError("stale_reply", "reply world_epoch/state_revision does not match the request")
    mode = data.get("provider_mode")
    if mode not in PROVIDER_MODES:
        raise ContractError("bad_reply", f"provider_mode {mode!r} unknown")
    latency = data.get("latency_ms", 0.0)
    if not _is_num(latency) or latency < 0:
        raise ContractError("bad_reply", "latency_ms must be a number >= 0")
    result = validate_result(request.role, request.payload, data.get("result"))
    return ResponseEnvelope(job_id=request.job_id, role=request.role, world_epoch=request.world_epoch,
                            state_revision=request.state_revision, provider_mode=mode, latency_ms=float(latency),
                            model_id=str(data.get("model_id", "")), result=result)


def field_names(cls) -> list[str]:
    return [f.name for f in fields(cls)]
