"""Adapters that route the legacy model hooks through the model plane, keeping their structured output contracts.

The engine already calls ``handler(mode=..., cases=[...], engine=engine)`` for the tiny resident modes (urgent_react, normal_live,
talk_reply, ambient_npc_talk) and for the world modes (decree, resident_reasoning), and expects ``[{"packet": {...}, "source": ...}]``
(or None entries, which means "use the built-in packet"). ``LegacyModelHandler`` is that handler. There is no second NPC stack: the
packets go through the same normalisers and executors as before; only the source of the answer changes.

Because the legacy call is synchronous and the tick must not wait, the handler is pull based: the first call for a case queues a
job and returns None for it (the stand-in packet is used); a later call with the same case finds the validated answer in the
cache. In ``shadow`` mode answers are logged and never returned; with the role ``off`` the handler returns None at once.

Role mapping: urgent_react/normal_live -> resident, resident_reasoning -> resident (even though it arrives through the world
handler), talk_reply/ambient_npc_talk -> dialogue, decree -> world.
"""
from __future__ import annotations

import hashlib
import json
import time

from ..client import Job
from ..wire import LEGACY_MODE_ROLE

LANE = {"urgent_react": ("critical", 400), "talk_reply": ("active", 1500), "normal_live": ("background", 2500),
        "ambient_npc_talk": ("background", 3000), "resident_reasoning": ("background", 8000), "decree": ("active", 8000)}
# How long a finished answer may still be applied (wall seconds). An urgent reaction goes stale in seconds, a plan in a minute.
ANSWER_TTL_S = {"urgent_react": 2.0, "talk_reply": 10.0, "normal_live": 10.0, "ambient_npc_talk": 10.0, "resident_reasoning": 60.0,
                "decree": 60.0}


def identity(mode: str, case: dict) -> tuple:
    """(cache key, resident id) naming WHAT a case asks, not the volatile numbers in it, so an answer can be found again on a later
    call for the same question. Urgent/normal: the resident. Talk: speaker, listener and the utterance. Reasoning: resident and reason.
    Decree: the query text."""
    prompt = case.get("prompt_case") or {}
    if mode in ("urgent_react", "normal_live"):
        who, parts = str(case.get("human_id", "")), [case.get("human_id")]
    elif mode == "talk_reply":
        who, parts = str(case.get("listener_id", "")), [case.get("speaker_id"), case.get("listener_id"), prompt.get("utterance")]
    elif mode == "ambient_npc_talk":
        who, parts = str(case.get("speaker_id", "")), [case.get("speaker_id"), case.get("listener_id"), prompt.get("speech_act"), prompt.get("topic")]
    elif mode == "resident_reasoning":
        who, parts = str(case.get("resident_id", "")), [case.get("resident_id"), case.get("reason")]
    else:
        who, parts = "", [case.get("query") or case.get("raw_payload")]
    blob = json.dumps([mode, parts], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24], who


class LegacyModelHandler:
    """Callable installed as ``engine.tiny_model_handler`` / ``engine.world_model_handler``."""

    def __init__(self, plane):
        self.plane = plane
        self._pending: dict = {}   # key -> wall time it may be asked again

    def __call__(self, mode=None, cases=None, engine=None, **_):
        role = LEGACY_MODE_ROLE.get(str(mode or "").strip().lower())
        cases = list(cases or [])
        if role is None or not cases or self.plane.mode(role) == "off":
            return None
        self.plane.pump()
        state = self.plane.mode(role)
        epoch = str(getattr(engine, "world_epoch", "") or "none")
        now = time.monotonic()
        idents = [identity(mode, case) for case in cases]
        answers = [None] * len(cases)
        missing = []
        for index, (key, _) in enumerate(idents):
            hit = self.plane.answers.take(key, epoch, ANSWER_TTL_S[mode]) if state == "on" else None
            if hit is not None:
                answers[index] = dict(hit.value)
                self._pending.pop(key, None)
            elif self._pending.get(key, 0.0) <= now:
                missing.append(index)
        if missing and state in ("on", "shadow"):
            self._submit(role, mode, [cases[i] for i in missing], [idents[i] for i in missing], epoch, engine, now)
        return answers if state == "on" else None

    def _submit(self, role, mode, cases, idents, epoch, engine, now):
        priority, deadline_ms = LANE[mode]
        keys = [key for key, _ in idents]
        for key in keys:
            self._pending[key] = now + deadline_ms / 1000.0 + 0.5
        if len(self._pending) > 4096:
            self._pending = {k: v for k, v in self._pending.items() if v > now}
        resident = next((who for _, who in idents if who), "")
        job = Job(role=role, payload={"mode": mode, "cases": cases}, world_epoch=epoch, state_revision=int(getattr(engine, "tick", 0) or 0),
                  priority=priority, deadline_ms=deadline_ms, resident_id=resident, meta={"case_keys": keys})
        self.plane.client.submit(job)


def install(engine, plane):
    """Point the engine's legacy hooks at the plane. Returns an ``uninstall()`` that restores the previous handlers."""
    previous = (getattr(engine, "tiny_model_handler", None), getattr(engine, "resident_model_handler", None),
                getattr(engine, "world_model_handler", None))
    handler = LegacyModelHandler(plane)
    engine.tiny_model_handler = handler
    engine.resident_model_handler = handler
    engine.world_model_handler = handler

    def uninstall():
        engine.tiny_model_handler, engine.resident_model_handler, engine.world_model_handler = previous

    return uninstall


def sync_installation(engine, plane, state: dict):
    """Install while any role is enabled, restore the original handlers when everything is off. ``state`` holds the uninstall."""
    if plane.switch.any_enabled() and state.get("uninstall") is None:
        state["uninstall"] = install(engine, plane)
    elif not plane.switch.any_enabled() and state.get("uninstall") is not None:
        state["uninstall"]()
        state["uninstall"] = None
