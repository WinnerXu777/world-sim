"""ModelPlane: the one object the game holds. Owns the switch, the client, caches and the status view.

Pull model: the tick thread calls ``pump()`` (or any API that pumps first); finished model answers land in caches keyed by what
asked for them, and game code reads the cache. Nothing here blocks the tick, and with every role ``off`` nothing here does I/O.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from systems.decision.contract import DecisionResult, summarize
from systems.decision.providers import ModelPending

from .client import Job, ModelClient, Outcome
from .config import ModelPlaneConfig
from .switch import ModelSwitch, SwitchError
from .transport import Transport
from .wire import LEGACY_MODE_ROLE

DECISION_TTL_S = 30.0


@dataclass
class CachedAnswer:
    value: object
    provider_mode: str
    model_id: str
    latency_ms: float
    at: float
    world_epoch: str = ""


class AnswerCache:
    """Bounded TTL cache of finished model answers."""

    def __init__(self, ttl_s: float, size: int = 512, clock=time.monotonic):
        self.ttl_s, self.size, self.clock = ttl_s, size, clock
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def put(self, key, value, provider_mode, model_id="", latency_ms=0.0, world_epoch=""):
        with self._lock:
            self._items[key] = CachedAnswer(value, provider_mode, model_id, latency_ms, self.clock(), world_epoch)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def get(self, key, world_epoch=None):
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            if self.clock() - item.at > self.ttl_s or (world_epoch is not None and item.world_epoch != world_epoch):
                del self._items[key]
                return None
            return item

    def take(self, key, world_epoch=None, ttl_s=None):
        """Like ``get`` but removes the entry (an answer is applied once) and may use a tighter TTL."""
        with self._lock:
            item = self._items.pop(key, None)
        if item is None:
            return None
        if self.clock() - item.at > (self.ttl_s if ttl_s is None else min(ttl_s, self.ttl_s)) or (
                world_epoch is not None and item.world_epoch != world_epoch):
            return None
        return item

    def clear(self):
        with self._lock:
            self._items.clear()

    def __len__(self):
        return len(self._items)


@dataclass
class Completed:
    """One finished job as seen by ``pump()``. ``applicable`` means a validated model answer the caller may apply (mode on)."""
    job: Job
    outcome: Outcome
    kind: str
    result: object = None
    applicable: bool = False
    note: str = ""


def case_key(mode: str, case: dict) -> str:
    blob = json.dumps({"mode": mode, "case": case}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


class ModelPlane:
    def __init__(self, config: ModelPlaneConfig | None = None, switch: ModelSwitch | None = None, transport: Transport | None = None,
                 log=None, clock=time.monotonic, env=None, game_clock=None):
        import os
        env = os.environ if env is None else env
        self.config = config or ModelPlaneConfig.from_env(env)
        self.config_error = ""
        if switch is None:
            try:
                switch = ModelSwitch.from_env(env)
            except SwitchError as exc:   # a typo in the environment must not stop the game: everything stays off, and it is reported
                switch, self.config_error = ModelSwitch(), str(exc)
        self.switch = switch
        self.clock = clock
        self.log = log
        self.client = ModelClient(self.config, self.switch, transport, clock=clock, game_clock=game_clock)
        self.metrics = self.client.metrics
        self.decisions = AnswerCache(DECISION_TTL_S, clock=clock)
        self.answers = AnswerCache(120.0, clock=clock)           # legacy batch answers by case key
        self._listeners: list = []
        self._pump_lock = threading.Lock()
        self.tier3 = None                                        # set by tier3.Tier3Router
        self.escalator = None                                    # set by tier3.escalation.install

    # ---- switch ---------------------------------------------------------------------------------------------------

    def mode(self, role: str) -> str:
        return self.switch.mode(role)

    def on_switch(self, listener) -> None:
        """``listener(status)`` runs after every effective toggle (the legacy-hook installer subscribes)."""
        self._listeners.append(listener)

    def set_modes(self, tier1: str | None = None, **slot_modes) -> dict:
        result = self.switch.set(tier1, **slot_modes)
        if result["changed"]:
            self.decisions.clear()
            self.answers.clear()
            self._log({"type": "model_switch", "changed": result["changed"], "model_epoch": result["epoch"]})
            for listener in list(self._listeners):
                listener(self.switch.snapshot())
        return result

    # ---- decisions (Tier 2) ---------------------------------------------------------------------------------------

    @staticmethod
    def decision_key(request) -> tuple:
        return (request.resident_id, request.trigger, request.state_revision, request.world_epoch)

    def submit_decision(self, request, standin: dict | None = None, depth: int = 0, parent_tier: int = 0):
        """Queue a /v1/decide job for ``request`` (a DecisionRequest). ``standin`` = the probabilities the game applies meanwhile."""
        payload = {"resident_id": request.resident_id, "trigger": request.trigger, "question_kind": request.question_kind,
                   "topic": request.topic, "tick": request.tick, "state": request.state,
                   "options": [{"id": o.id, "description": o.description, "tags": list(o.tags)} for o in request.options]}
        job = Job(role="decide", payload=payload, world_epoch=request.world_epoch, state_revision=request.state_revision,
                  job_id=request.job_id, priority=request.priority, deadline_ms=request.deadline_ms,
                  resident_id=request.resident_id, causal_id=request.trigger, depth=depth, parent_tier=parent_tier,
                  meta={"request": request, "standin": standin})
        return self.client.submit(job)

    def decide_for_provider(self, request, rules_provider, blocking: bool = False):
        """(probabilities, provider_mode) for a ClefDecisionProvider. Raises ModelPending when the model answer is not ready."""
        mode = self.mode("decide")
        if mode == "off":
            return rules_provider.decide(request), "rules"
        self.pump()
        if mode == "shadow":
            probabilities = rules_provider.decide(request)
            if self.decisions.get(self.decision_key(request)) is None:
                self.submit_decision(request, standin=probabilities)
            return probabilities, "rules"
        hit = self.decisions.get(self.decision_key(request), request.world_epoch)
        if hit is not None:
            return dict(hit.value), hit.provider_mode
        if blocking:
            outcome = self._decide_blocking(request)
            if outcome.status == "ok":
                return dict(outcome.response.result["probabilities"]), outcome.response.provider_mode
            raise ModelPending(f"model unavailable: {outcome.reason}")
        refused = self.submit_decision(request)
        if refused is not None:
            raise ModelPending(f"model not used: {refused.reason}")
        raise ModelPending("model answer pending")

    def _decide_blocking(self, request) -> Outcome:
        payload = {"resident_id": request.resident_id, "trigger": request.trigger, "question_kind": request.question_kind,
                   "topic": request.topic, "tick": request.tick, "state": request.state,
                   "options": [{"id": o.id, "description": o.description, "tags": list(o.tags)} for o in request.options]}
        job = Job(role="decide", payload=payload, world_epoch=request.world_epoch, state_revision=request.state_revision,
                  job_id=request.job_id, priority=request.priority, deadline_ms=request.deadline_ms,
                  resident_id=request.resident_id, causal_id=request.trigger, meta={"request": request})
        return self.client.call_sync(job)

    # ---- pumping --------------------------------------------------------------------------------------------------

    def pump(self, max_n: int | None = None) -> list:
        """Drain finished jobs: fill caches, log shadow comparisons, count agreement. Tick-thread safe (no I/O but logging)."""
        done = []
        with self._pump_lock:
            for outcome in self.client.drain(max_n):
                try:
                    completed = self._complete(outcome)
                    done.append(completed)
                except Exception as exc:  # noqa: BLE001 - bookkeeping must not reach the tick
                    self.metrics.reason(outcome.job.role, f"pump_error:{type(exc).__name__}")
                    continue
                callback = outcome.job.meta.get("on_complete")      # Tier 3 router: parse, gate and store the result (never raises into the tick)
                if callback is not None:
                    try:
                        callback(completed)
                    except Exception as exc:  # noqa: BLE001
                        self.metrics.reason(outcome.job.role, f"on_complete_error:{type(exc).__name__}")
        return done

    def _complete(self, outcome: Outcome) -> Completed:
        job = outcome.job
        if outcome.status != "ok":
            if job.mode == "shadow":
                self._log({"type": "shadow_failed", "role": job.role, "job_id": job.job_id, "reason": outcome.reason,
                           "resident_id": job.resident_id})
            return Completed(job, outcome, job.role, note=outcome.reason)
        response = outcome.response
        shadow = job.mode == "shadow"
        if job.role == "decide":
            request = job.meta["request"]
            probabilities = response.result["probabilities"]
            top, top_p, margin = summarize(request.options, probabilities)
            result = DecisionResult(job_id=job.job_id, resident_id=job.resident_id, world_epoch=job.world_epoch,
                                    state_revision=job.state_revision, probabilities=probabilities, top_option=top, top_p=top_p,
                                    margin=margin, provider_mode=response.provider_mode, latency_ms=outcome.latency_ms)
            if shadow:
                standin = job.meta.get("standin")
                standin_top = None if not standin else max(request.options, key=lambda o: standin[o.id]).id
                agree = None if standin_top is None else standin_top == top
                self.metrics.count("decide", job.priority, "shadow_ok")
                if agree is not None:
                    self.metrics.count("decide", job.priority, "agreed" if agree else "disagreed")
                self._log({"type": "shadow", "role": "decide", "job_id": job.job_id, "resident_id": job.resident_id,
                           "trigger": request.trigger, "model_probabilities": probabilities, "standin_probabilities": standin,
                           "model_top": top, "standin_top": standin_top, "agree": agree, "provider_mode": response.provider_mode,
                           "model_id": response.model_id, "latency_ms": round(outcome.latency_ms, 2)})
                return Completed(job, outcome, "decision", result, applicable=False)
            self.decisions.put(self.decision_key(request), dict(probabilities), response.provider_mode, response.model_id,
                               outcome.latency_ms, job.world_epoch)
            return Completed(job, outcome, "decision", result, applicable=True)
        # batch roles
        keys = job.meta.get("case_keys", [])
        responses = response.result["responses"]
        if shadow:
            self.metrics.count(job.role, job.priority, "shadow_ok")
            self._log({"type": "shadow", "role": job.role, "mode": job.payload["mode"], "job_id": job.job_id,
                       "packets": [r["packet"] for r in responses], "provider_mode": response.provider_mode,
                       "model_id": response.model_id, "latency_ms": round(outcome.latency_ms, 2)})
            return Completed(job, outcome, "batch", responses, applicable=False)
        for key, item in zip(keys, responses):
            self.answers.put(key, item, response.provider_mode, response.model_id, outcome.latency_ms, job.world_epoch)
        return Completed(job, outcome, "batch", responses, applicable=True)

    # ---- status ---------------------------------------------------------------------------------------------------

    def status(self) -> dict:
        return {"switch": self.switch.snapshot(), "model_epoch": self.switch.epoch,
                "endpoints": {role: self.config.endpoint(role).public(role) for role in self.config.limits},
                "metrics": self.metrics.snapshot(), "client": self.client.status(),
                "caches": {"decisions": len(self.decisions), "answers": len(self.answers)},
                "tier3": None if self.tier3 is None else {**self.tier3.status(),
                                                          "escalation": None if self.escalator is None else self.escalator.status()},
                "network_enabled": self.switch.any_enabled(), "saved_in_worlds": False, "config_error": self.config_error}

    def brief(self) -> dict:
        """Small view for the existing /status ``decision`` field."""
        snap = self.switch.snapshot()
        return {**snap, "network_calls": self.client.network_calls, "fallbacks": sum(
            c["fallbacks"] for lanes in self.metrics.snapshot().values() for lane, c in lanes.items() if lane != "reasons")}

    def close(self) -> None:
        self.client.close()

    def _log(self, record: dict) -> None:
        if self.log is not None:
            try:
                self.log.append(record)
            except Exception:  # noqa: BLE001 - logging never breaks play
                pass


def role_for_mode(mode: str):
    return LEGACY_MODE_ROLE.get(str(mode or "").strip().lower())
