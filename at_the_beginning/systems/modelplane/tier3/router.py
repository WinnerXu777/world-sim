"""``Tier3Router``: the one object the game asks for model plans, dialogue lines and world intents.

Pull model, like the rest of the plane. ``request_*`` builds nothing heavy and never blocks: with the role ``off`` it returns a ``Ticket``
("off") before any job, queue or socket exists. Otherwise it queues one job whose ``on_complete`` callback (run by ``ModelPlane.pump``)
parses the reply, runs the confidence gate and stores a ``Tier3Result``:

* mode ``shadow``: the result is *recorded* (``status="shadow"``, ``would_apply`` = what the gate said) and never offered to a caller;
* mode ``on``: the result is offered once through ``poll_*``: ``accepted`` (use it) or ``rejected``/``fallback`` (use Tier 1 / the rules;
  ``reason`` is logged and counted in ``/model_status``).

Nothing here executes a plan: the consumer runs an accepted plan through ``ActionRunner`` / ``run_plan``; world intents are applied by
``apply_intents`` only when the caller asks. A line proposal is always usable: a rejected or failed request carries the rules' fallback line.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter, deque
from typing import Optional

from ..client import Job
from . import context as ctx
from . import parsers
from .parsers import GateConfig
from .types import (DialogueLine, GateResult, PacketError, Tier3Result, Ticket)

LANES = {"plan": ("background", 8000), "line": ("active", 1500), "intents": ("active", 8000)}
KIND_ROLE = {"plan": "resident", "line": "dialogue", "intents": "world"}
KIND_MODE = {"plan": "plan_ops", "line": None, "intents": "director"}      # line: the case names talk_reply / ambient_npc_talk itself
READY_TTL_S = {"plan": 60.0, "line": 10.0, "intents": 60.0}


def _digest(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


class Tier3Router:
    def __init__(self, plane, *, runner=None, world=None, aff=None, gate: Optional[GateConfig] = None, clock=time.monotonic, history: int = 200):
        self.plane = plane
        self.runner = runner
        self.world = world if world is not None else getattr(runner, "world", None)
        self.aff = aff if aff is not None else getattr(runner, "aff", None)
        self.gate = gate or GateConfig()
        self.clock = clock
        self._lock = threading.Lock()
        self._pending: dict = {}          # key -> wall time after which it may be asked again
        self._ready: dict = {}            # key -> (expires, Tier3Result) for results a caller may take (mode on)
        self.history: deque = deque(maxlen=history)
        self.counts: dict = {kind: Counter() for kind in LANES}
        self.reasons: Counter = Counter()
        plane.tier3 = self

    # -- public requests ----------------------------------------------------------------------------------------------------------
    def request_plan(self, actor: str, reason: str, *, case: Optional[dict] = None, depth: int = 0, parent_tier: int = 0,
                     tick: Optional[int] = None) -> Ticket:
        if self.plane.mode("resident") == "off":
            return Ticket("off")
        case = case or ctx.resident_case(self.world, self.runner.services, self.aff, actor, reason, max_steps=self.gate.max_steps,
                                         min_confidence=self.gate.min_confidence,
                                         destructive_ops=self.gate.allow_destructive_ops)
        tick = int(case.get("tick", 0) if tick is None else tick)
        return self._request("plan", f"plan:{actor}", case, resident=actor, reason=reason, tick=tick, depth=depth, parent_tier=parent_tier,
                             meta={"resident_id": actor})

    def request_line(self, decided: "ctx.DecidedOutcome", *, tick: int = 0, depth: int = 0, parent_tier: int = 0) -> Ticket:
        if self.plane.mode("dialogue") == "off":
            return Ticket("off")
        case = ctx.dialogue_case(decided)
        key = f"line:{decided.speaker}:{decided.listener}:{decided.act}:{_digest(decided.topic, decided.utterance, decided.outcome)}"
        return self._request("line", key, case, resident=decided.listener, reason=decided.act, tick=tick, depth=depth, parent_tier=parent_tier,
                             meta={"decided": decided}, payload_mode=decided.mode)

    def request_intents(self, query: str, reason: str = "decree", *, tick: int = 0, residents: int = 0, extra: Optional[dict] = None,
                        sample_ids=(), only=None, depth: int = 0, parent_tier: int = 0) -> Ticket:
        if self.plane.mode("world") == "off":
            return Ticket("off")
        case = ctx.world_case(query, reason, tick=tick, residents=residents,
                              powers=[p for p in ctx.power_catalog(sample_ids=sample_ids) if only is None or p["name"] in only], max_intents=self.gate.max_intents, extra=extra)
        return self._request("intents", f"intents:{_digest(query, reason)}", case, resident="", reason=reason, tick=tick, depth=depth,
                             parent_tier=parent_tier, meta={"query": query})

    def forget_pending(self) -> None:
        """Drop the "already asked" keys and ready results (after a switch change: their jobs are stale, a new ask must not be refused as pending)."""
        with self._lock:
            self._pending.clear()
            self._ready.clear()

    # -- polling (mode on) ---------------------------------------------------------------------------------------------------------
    def poll(self, key: str) -> Optional[Tier3Result]:
        """Pump, then take the result stored under ``key`` once (None while pending, in shadow mode, or already taken)."""
        self.plane.pump()
        with self._lock:
            item = self._ready.pop(key, None)
        if item is None or item[0] < self.clock():
            return None
        return item[1]

    def poll_plan(self, actor: str) -> Optional[Tier3Result]:
        return self.poll(f"plan:{actor}")

    def poll_line(self, decided: "ctx.DecidedOutcome") -> Optional[Tier3Result]:
        return self.poll(f"line:{decided.speaker}:{decided.listener}:{decided.act}:{_digest(decided.topic, decided.utterance, decided.outcome)}")

    def poll_intents(self, query: str, reason: str = "decree") -> Optional[Tier3Result]:
        return self.poll(f"intents:{_digest(query, reason)}")

    def line_or_fallback(self, decided: "ctx.DecidedOutcome", *, tick: int = 0) -> DialogueLine:
        """One call for a speaker: the model's line once it is ready and passed the check, else the rules' line (and a request is queued)."""
        polled = self.poll_line(decided)
        if polled is not None and isinstance(polled.proposal, DialogueLine):
            return polled.proposal
        if polled is None:
            self.request_line(decided, tick=tick)
        return parsers.fallback_line(decided.speaker, decided.listener, decided.act, decided.tone)

    def apply_intents(self, result: Tier3Result) -> list:
        """Apply the accepted intents of an ``accepted`` result through the harness powers (atomic each); returns the PowerResults."""
        from harness import powers
        if result.status != "accepted":
            return []
        return [powers.apply(self.world, plan) for _intent, plan in result.proposal]

    # -- internals -----------------------------------------------------------------------------------------------------------------
    def _request(self, kind: str, key: str, case: dict, *, resident: str, reason: str, tick: int, depth: int, parent_tier: int, meta: dict,
                 payload_mode: Optional[str] = None) -> Ticket:
        now = self.clock()
        with self._lock:
            if self._pending.get(key, 0.0) > now:
                return Ticket("pending", "already_pending", key)
        role = KIND_ROLE[kind]
        priority, deadline_ms = LANES[kind]
        mode = payload_mode or KIND_MODE[kind]
        epoch = self._epoch()
        job = Job(role=role, payload={"mode": mode, "cases": [case]}, world_epoch=epoch, state_revision=int(tick), priority=priority,
                  deadline_ms=deadline_ms, resident_id=resident, causal_id=f"{kind}:{reason}:{key}:{int(tick) // 200}:m{self.plane.switch.epoch}", depth=depth,
                  parent_tier=parent_tier, meta={"tier3": kind, "key": key, "on_complete": self._on_complete, "tick": int(tick), **meta})
        with self._lock:
            self._pending[key] = now + deadline_ms / 1000.0 + 1.0
            if len(self._pending) > 2048:
                self._pending = {k: v for k, v in self._pending.items() if v > now}
        refused = self.plane.client.submit(job)
        if refused is not None:
            with self._lock:
                self._pending.pop(key, None)
            self._store(Tier3Result(kind, role, "fallback", refused.reason, resident, self.plane.mode(role), job_id=job.job_id, tick=int(tick)),
                        key, job)
            return Ticket("refused", refused.reason, key)
        return Ticket("pending", "", key)

    def _epoch(self) -> str:
        engine = getattr(self.world, "engine", None)
        return str(getattr(engine, "world_epoch", "") or getattr(self.world, "epoch", "") or "none")

    def _on_complete(self, completed) -> None:
        job = completed.job
        kind, key, tick = job.meta["tier3"], job.meta["key"], job.meta.get("tick", 0)
        role, mode = job.role, job.mode
        with self._lock:
            self._pending.pop(key, None)
        if completed.outcome.status != "ok":
            self._store(Tier3Result(kind, role, "fallback", completed.note or completed.outcome.reason, job.resident_id, mode, job_id=job.job_id,
                                    tick=tick), key, job)
            return
        packet = completed.result[0]["packet"]
        source = completed.outcome.response.model_id or completed.outcome.response.provider_mode
        try:
            result = getattr(self, f"_finish_{kind}")(job, packet, source, mode, tick)
        except PacketError as exc:
            result = Tier3Result(kind, role, "shadow" if mode == "shadow" else "rejected", f"invalid_packet:{exc.code}", job.resident_id, mode,
                                 would_apply=False if mode == "shadow" else None, job_id=job.job_id, tick=tick, detail={"detail": exc.detail})
            if kind == "line":
                d = job.meta["decided"]
                result.proposal = parsers.fallback_line(d.speaker, d.listener, d.act, d.tone)
        self._store(result, key, job)

    def _finish_plan(self, job, packet, source, mode, tick) -> Tier3Result:
        actor = job.meta["resident_id"]
        proposal = parsers.parse_plan(packet, actor, source)
        gate = parsers.gate_plan(proposal, self.runner, actor, self.gate)
        return self._gated("plan", job, proposal, gate, mode, tick, extra={"confidence": proposal.confidence, "steps": proposal.steps_list(),
                                                                          "summary": proposal.summary})

    def _finish_line(self, job, packet, source, mode, tick) -> Tier3Result:
        d = job.meta["decided"]
        line = parsers.parse_line(packet, d.speaker, d.listener, d.allowed_intents, source)
        return self._gated("line", job, line, GateResult(True), mode, tick, extra={"text": line.text, "intent": line.intent})

    def _finish_intents(self, job, packet, source, mode, tick) -> Tier3Result:
        intents = parsers.parse_intents(packet, self.gate.max_intents)
        accepted, rejected = parsers.vet_intents(self.world, intents, self.gate)
        gate = GateResult(bool(accepted), "" if accepted else ("no_intent" if not intents else "no_valid_intent"),
                          {"rejected": [(i.power, why) for i, why in rejected]})
        return self._gated("intents", job, accepted, gate, mode, tick,
                           extra={"accepted": [i.power for i, _ in accepted], "rejected": [(i.power, why) for i, why in rejected]})

    def _gated(self, kind, job, proposal, gate: GateResult, mode, tick, extra) -> Tier3Result:
        role = job.role
        if mode == "shadow":
            return Tier3Result(kind, role, "shadow", gate.reason, job.resident_id, mode, proposal, would_apply=gate.ok, job_id=job.job_id, tick=tick,
                               detail={**extra, **gate.detail})
        return Tier3Result(kind, role, "accepted" if gate.ok else "rejected", gate.reason, job.resident_id, mode, proposal if gate.ok else None,
                           job_id=job.job_id, tick=tick, detail={**extra, **gate.detail})

    def _store(self, result: Tier3Result, key: str, job) -> None:
        kind = result.kind
        take = result.mode == "on"             # shadow results are recorded, never offered to a caller
        if kind == "line" and result.proposal is None and job.meta.get("decided") is not None:     # every non-accepted line request carries the rules line
            d = job.meta["decided"]
            result.proposal = parsers.fallback_line(d.speaker, d.listener, d.act, d.tone)
        with self._lock:
            self.counts[kind][result.status] += 1
            if result.reason:
                self.reasons[f"{kind}:{result.reason.split(':')[0] if result.status != 'fallback' else result.reason}"] += 1
            self.history.append(result.summary())
            if take:
                self._ready[key] = (self.clock() + READY_TTL_S[kind], result)
                if len(self._ready) > 512:
                    for old in sorted(self._ready, key=lambda k: self._ready[k][0])[:128]:
                        del self._ready[old]
        counter = {"accepted": "gate_accepted", "rejected": "gate_rejected"}.get(result.status)
        if counter:
            self.plane.metrics.count(result.role, job.priority, counter)
        if result.reason:
            self.plane.metrics.reason(result.role, f"gate:{result.reason.split(':')[0]}")
        self.plane._log({"type": "tier3", **result.summary(), "confidence": result.detail.get("confidence"), "steps": result.detail.get("steps"),
                         "text": result.detail.get("text"), "intents": result.detail.get("accepted"), "rejected_intents": result.detail.get("rejected")})

    # -- status --------------------------------------------------------------------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            return {"gate": {"min_confidence": self.gate.min_confidence, "max_steps": self.gate.max_steps,
                             "allow_destructive_powers": self.gate.allow_destructive_powers},
                    "pending": len(self._pending), "ready": len(self._ready),
                    "results": {kind: dict(counter) for kind, counter in self.counts.items()},
                    "reasons": dict(self.reasons), "recent": list(self.history)[-10:]}
