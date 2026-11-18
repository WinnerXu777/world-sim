"""Reply parsers and the confidence gate. A packet that comes back from a model is untrusted: it is turned into a typed proposal here or it
is rejected with a stable code, and a proposal still has to pass the gate before anything acts on it. Nothing in this module changes the
world (the plan gate asks the runner for a dry run, the world vetting asks the powers for a plan)."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Optional

from .types import DialogueLine, GateResult, PacketError, PlanProposal, WorldIntent

MAX_SPEECH_CHARS = 500
MAX_SUMMARY_CHARS = 200
TONES = ("neutral", "warm", "cold", "tense", "angry", "afraid", "kind", "playful", "sad")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass
class GateConfig:
    min_confidence: float = 0.6          # placeholder: tuned from shadow data
    max_steps: int = 6
    allow_destructive_powers: bool = False
    allow_destructive_ops: bool = False      # plan ops with risk destructive / irreversible (attack): refused at the gate unless set
    max_intents: int = 3


def _json_safe(value, depth: int = 0):
    """Round-trip through JSON so a step or intent cannot smuggle a non-data object into the runner."""
    if depth > 6:
        raise PacketError("args_too_deep")
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError):
        raise PacketError("args_not_json")


# -- resident ----------------------------------------------------------------------------------------------------------------------

def parse_plan(packet, resident_id: str, source: str = "") -> PlanProposal:
    if not isinstance(packet, dict):
        raise PacketError("not_an_object")
    if str(packet.get("resident_id", "")) != str(resident_id):
        raise PacketError("wrong_resident", f"{packet.get('resident_id')!r} != {resident_id!r}")
    confidence = packet.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise PacketError("bad_confidence")
    steps = packet.get("steps")
    if not isinstance(steps, list):
        raise PacketError("steps_not_a_list")
    clean = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("op"), str) or not step["op"].strip():
            raise PacketError("bad_step", f"step {index}")
        args = step.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise PacketError("bad_step_args", f"step {index}")
        clean.append({"op": step["op"].strip(), "args": _json_safe(args)})
    summary = packet.get("summary", "")
    return PlanProposal(str(resident_id), tuple(clean), float(confidence), CONTROL.sub("", str(summary))[:MAX_SUMMARY_CHARS], str(source))


def gate_plan(proposal: PlanProposal, runner, actor: str, config: Optional[GateConfig] = None) -> GateResult:
    """Accept only a non-empty, confident, known-op plan whose first step is legal right now (the runner's own dry run). Later steps are
    checked for schema only: whether they are legal depends on what the earlier ones change, and the runner judges each step when it runs."""
    config = config or GateConfig()
    if not proposal.steps:
        return GateResult(False, "empty_plan")
    if len(proposal.steps) > config.max_steps:
        return GateResult(False, "too_many_steps", {"steps": len(proposal.steps), "max": config.max_steps})
    if proposal.confidence < config.min_confidence:
        return GateResult(False, "low_confidence", {"confidence": proposal.confidence, "needed": config.min_confidence})
    from systems.actions.plan_ops import PLAN_OPS
    from systems.actions.catalog import FROZEN_LEGACY
    for index, step in enumerate(proposal.steps):
        if step["op"] in FROZEN_LEGACY:
            return GateResult(False, f"legacy_frozen:{step['op']}", {"step": index})
        if step["op"] not in PLAN_OPS:
            return GateResult(False, f"unknown_op:{step['op']}", {"step": index})
        if not config.allow_destructive_ops and runner.registry.actions[step["op"]].extra.get("risk", "reversible") != "reversible":
            return GateResult(False, f"destructive_op:{step['op']}", {"step": index})
        problems = runner.registry.validate_call(step["op"], step["args"], kind="action")
        if problems:
            return GateResult(False, f"invalid_step:{index}:invalid_arguments", {"errors": list(problems)[:3]})
    first = runner.run(actor, proposal.steps[0]["op"], proposal.steps[0]["args"], proposer="tier3", confidence=proposal.confidence, dry_run=True)
    if not first.ok:
        return GateResult(False, f"illegal_step:0:{first.code}", {"detail": first.detail and {k: v for k, v in first.detail.items() if k != "verdict"}})
    return GateResult(True)


# -- dialogue ----------------------------------------------------------------------------------------------------------------------

RELATIONSHIP_DELTAS = ("neutral", "warmer", "colder")


def parse_line(packet, speaker: str, listener: str, allowed_intents=(), source: str = "") -> DialogueLine:
    """Keep only wording: text, act, tone and one allowed physical intent. Anything else a model adds (obligations, items, trades, deltas)
    is ignored, so a line can colour an outcome Python already decided but never change it."""
    if not isinstance(packet, dict):
        raise PacketError("not_an_object")
    text = packet.get("speech_text")
    if not isinstance(text, str):
        raise PacketError("no_speech_text")
    text = CONTROL.sub("", text).strip()
    if not text:
        raise PacketError("empty_speech_text")
    if len(text) > MAX_SPEECH_CHARS:
        raise PacketError("speech_too_long", str(len(text)))
    intent = packet.get("physical_intent", "") or ""
    if not isinstance(intent, str) or (intent and list(allowed_intents) and intent not in allowed_intents) or (intent and not allowed_intents):
        raise PacketError("intent_not_allowed", str(intent))
    tone = packet.get("tone", "neutral")
    tone = tone if isinstance(tone, str) and tone in TONES else "neutral"
    return DialogueLine(str(speaker), str(listener), text, str(packet.get("speech_act", ""))[:40], tone, intent, source or "model")


FALLBACK_LINES = {"threat_response": "Stay away from me!", "alarm_response": "I will raise the alarm.", "trade_response": "Let us talk terms.",
                  "apology_response": "Fine. Let it go.", "warn": "Careful, danger is near!", "greet": "Good day to you.",
                  "comfort": "It will be alright.", "gossip": "Have you heard the news?", "accept": "Agreed.", "refuse": "No. I cannot do that.",
                  "thank": "Thank you."}


def fallback_line(speaker: str, listener: str, act: str = "greet", tone: str = "neutral") -> DialogueLine:
    """The rules line: a short canned sentence per speech act (what the game says with every role off)."""
    return DialogueLine(str(speaker), str(listener), FALLBACK_LINES.get(act, "..."), act, tone if tone in TONES else "neutral", "", "fallback")


# -- world -------------------------------------------------------------------------------------------------------------------------

def parse_intents(packet, max_intents: int = 3) -> list:
    if not isinstance(packet, dict):
        raise PacketError("not_an_object")
    raw = packet.get("intents")
    if not isinstance(raw, list):
        raise PacketError("intents_not_a_list")
    out = []
    for index, intent in enumerate(raw[:max_intents]):
        if not isinstance(intent, dict) or not isinstance(intent.get("power"), str) or not intent["power"].strip():
            raise PacketError("bad_intent", f"intent {index}")
        args = intent.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise PacketError("bad_intent_args", f"intent {index}")
        out.append(WorldIntent(intent["power"].strip(), _json_safe(args), CONTROL.sub("", str(intent.get("reason", "")))[:200]))
    return out


def vet_intents(world, intents: list, config: Optional[GateConfig] = None, registry=None) -> tuple:
    """(accepted, rejected): every intent is planned (never applied) by the powers; a refused plan, an unknown power or a destructive
    power without ``allow_destructive_powers`` lands in ``rejected`` as ``(intent, reason)``."""
    from harness import powers
    config = config or GateConfig()
    registry = registry or powers.REGISTRY
    accepted, rejected = [], []
    for intent in intents:
        if intent.power not in registry.powers:
            rejected.append((intent, f"unknown_power:{intent.power}"))
            continue
        risk = registry.powers[intent.power].extra.get("risk", "reversible")
        if risk == "destructive" and not config.allow_destructive_powers:
            rejected.append((intent, "risk_gated"))
            continue
        try:
            plan = powers.plan(world, intent.power, intent.args, registry)
        except Exception as exc:  # noqa: BLE001 - a power that cannot even plan this world is a rejection, not a crash
            rejected.append((intent, f"plan_error:{type(exc).__name__}"))
            continue
        if not plan.ok:
            rejected.append((intent, f"{plan.reason}" + (f":{plan.errors[0]}" if plan.errors else "")))
            continue
        accepted.append((intent, plan))
    return accepted, rejected
