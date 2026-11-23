"""Executors of ``RecordOp`` kinds: the writes an Action makes to resident records and legacy systems (not tensor/item effects).

``EngineRecordOps`` talks to the live legacy engine through the same public calls the engine itself uses (``queue_resident_task``,
``set_current_routine``, ``resident_store.update_relationship``, the commission ``submit_request`` path). ``StaticRecordOps`` does the
same on plain dict records for synthetic worlds. ``NullRecordOps`` refuses every op (reported in the audit as ``skipped``).
Each ``execute`` returns ``{"ok": bool, ...}`` and never raises for a normal failure.
"""
from __future__ import annotations

import copy
from typing import Optional


class RecordOps:
    def cancel_invitation_travel(self, actor, invitation, tick):
        record = self._rec(actor) if hasattr(self, "_rec") else self._record(actor) if hasattr(self, "_record") else None
        if record is None:
            return
        matches = [t for t in record.get("tasks", []) if t.get("metadata", {}).get("invitation") == invitation]
        state = record.get("task_state") or {}
        if any(t.get("id") == state.get("current_task_id") for t in matches):
            from systems.tasks.ops import complete_current_task
            complete_current_task(record, tick, outcome="cancelled", reason="invitation_expired")
        record["tasks"] = [t for t in record.get("tasks", []) if t.get("metadata", {}).get("invitation") != invitation]
        if hasattr(self, "engine"):
            self.engine.resident_store.touch_resident(actor)

    def execute(self, op, actor: str, tick: int) -> dict:
        handler = getattr(self, f"op_{op.kind}", None)
        if handler is None:
            return {"ok": False, "reason": "unsupported_op", "kind": op.kind}
        try:
            return handler(actor, tick, **op.args)
        except TypeError as exc:
            return {"ok": False, "reason": "bad_op_args", "detail": str(exc)}


class NullRecordOps(RecordOps):
    def execute(self, op, actor, tick):
        return {"ok": False, "reason": "skipped_no_record_ops", "kind": op.kind}


class StaticRecordOps(RecordOps):
    """Dict records: ``tasks`` appended to ``record["tasks"]``, routine stored in ``schedule_state``, closeness in ``relationships``."""

    def __init__(self, records: dict):
        self.records = records
        self._task_seq = 0

    def finish_task(self, actor, task_id, outcome="completed", tick=0) -> bool:
        """Test/sim helper with the engine's shape: the task leaves ``tasks`` and ``task_state.last_completed_task`` records how it ended."""
        record = self._rec(actor) or {}
        left = [t for t in record.get("tasks", []) if t.get("id") != task_id]
        if len(left) == len(record.get("tasks", [])):
            return False
        done = next(t for t in record["tasks"] if t.get("id") == task_id)
        record["tasks"] = left
        record.setdefault("task_state", {})["last_completed_task"] = {**done, "status": outcome, "last_update_tick": tick}
        return True

    def _rec(self, actor) -> Optional[dict]:
        return self.records.get(actor)

    def op_queue_task(self, actor, tick, task_kind, **kwargs):
        record = self._rec(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        self._task_seq += 1
        task = {"id": f"task_s{self._task_seq:04d}", "task_kind": task_kind, "created_tick": tick, **copy.deepcopy(kwargs)}
        record.setdefault("tasks", []).append(task)
        return {"ok": True, "task": task, "task_id": task["id"]}

    def op_set_routine(self, actor, tick, kind, reason="action"):
        record = self._rec(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        record.setdefault("schedule_state", {})["current_routine"] = {"kind": kind, "reason": reason, "set_tick": tick}
        return {"ok": True}

    def op_site_trip(self, actor, tick, kind, reason="action"):
        record = self._rec(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        record.setdefault("site_trips", []).append({"kind": kind, "tick": tick})
        return {"ok": True, "trip": kind}

    def op_memory_note(self, actor, tick, owner, kind, other="", event="", about="", event_kind=""):
        record = self._rec(owner)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        record.setdefault("memory", {}).setdefault("recent_events", []).append(
            {"tick": tick, "kind": kind, "other_human_id": other, "about_event": event, "about": about, "event_kind": event_kind})
        return {"ok": True}

    def op_relationship(self, actor, tick, other, kind, delta, owner=None):
        record = self._rec(owner or actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        relation = record.setdefault("relationships", {}).setdefault(other, {"kind": kind, "closeness": 0.0, "tags": [kind]})
        relation["closeness"] = round(max(-1.0, min(1.0, float(relation.get("closeness", 0.0)) + float(delta))), 3)
        relation["last_seen_tick"] = tick
        return {"ok": True, "closeness": relation["closeness"]}

    def op_r61_clear_goal(self, actor, tick, target):
        record = self._rec(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        goals = record.get("goals", [])
        record["goals"] = [g for g in goals if not (g.get("kind") == "retaliate" and g.get("target_id") == target)]
        return {"ok": True, "cleared": len(goals) - len(record["goals"])}

    def op_place_mark(self, actor, tick, name, x, y, space=0.0, source="mark"):
        record = self._rec(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        from systems.places import remember
        remember(record, name, x, y, space, tick, source)
        return {"ok": True, "place": name}

    def op_place_ask(self, actor, tick, target, name, closeness=0.0):
        """The asked resident answers by rules (``systems.places.answer_directions``); a yes copies the place to the asker and nudges both closeness values."""
        asker, teller = self._rec(actor), self._rec(target)
        if asker is None or teller is None:
            return {"ok": False, "reason": "no_record"}
        from systems.places import answer_directions
        answer = answer_directions(asker, teller, actor, name, tick)
        if answer["ok"]:
            self.op_relationship(actor, tick, target, "known", closeness)
            self.op_relationship(actor, tick, actor, "known", closeness, owner=target)
        return answer


class EngineRecordOps(RecordOps):
    def __init__(self, engine):
        self.engine = engine

    def _record(self, actor):
        return self.engine.resident_store.get(actor)

    def op_queue_task(self, actor, tick, task_kind, **kwargs):
        from systems.tasks.ops import queue_resident_task
        record = self._record(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        kwargs.setdefault("source", "action")
        task = queue_resident_task(record, task_kind, tick=tick, **kwargs)
        self.engine.resident_store.touch_resident(actor)
        return {"ok": True, "task_id": task["id"], "task_kind": task_kind}

    def op_set_routine(self, actor, tick, kind, reason="action"):
        from systems.schedule.lifecycle import set_current_routine
        from systems.schedule.ops import ensure_resident_schedule
        from systems.schedule.resolver import tick_to_time_block
        record = self._record(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        ensure_resident_schedule(record, tick)
        block = tick_to_time_block(tick)
        set_current_routine(record, {"kind": kind, "time_block": block, "source": "action", "reason": reason}, tick, reason=reason, time_block=block)
        self.engine.resident_store.touch_resident(actor)
        return {"ok": True, "routine": kind, "time_block": block}

    def op_site_trip(self, actor, tick, kind, reason="action"):
        """Start the roster needs loop's trip to the food / water site now. Refused without a roster binding, without a site, or with a trip running."""
        from systems.roster.driver import roster_of, runtime
        from systems.roster.needs import settings, site_position
        roster, _ = roster_of(self.engine, actor)
        if not roster or kind not in ("food", "water"):
            return {"ok": False, "reason": "no_roster" if not roster else "bad_kind"}
        needs, has_sites = settings(roster)
        if site_position(self.engine, needs, kind, has_sites) is None:
            return {"ok": False, "reason": "no_site"}
        state = runtime(self.engine)
        if actor in state.trips:
            return {"ok": False, "reason": "trip_active", "kind": state.trips[actor]["kind"]}
        state.trips[actor] = {"kind": kind, "phase": "walk", "started": int(tick), "stood": 0}
        return {"ok": True, "trip": kind}

    def op_memory_note(self, actor, tick, owner, kind, other="", event="", about="", event_kind=""):
        """A resident's memory entry (``resident_store.record_event``): what the listener of a piece of news was told, and by whom."""
        if self._record(owner) is None:
            return {"ok": False, "reason": "no_record"}
        note = f"{other} told me about {event_kind}" + (f" involving {about}" if about else "")
        extra = {"about_event": event, **({"about": about} if about else {})}
        self.engine.resident_store.record_event(owner, tick, kind, note=note, other_human_id=other or None, extra=extra)
        return {"ok": True}

    def op_relationship(self, actor, tick, other, kind, delta, owner=None):
        owner = owner or actor
        # ``update_relationship`` overwrites the relation kind, so an existing kind (family, friend, rival...) is passed back in unchanged
        existing = ((self._record(owner) or {}).get("relationships") or {}).get(other) or {}
        self.engine.resident_store.update_relationship(owner, other, str(existing.get("kind") or kind), float(delta), tick)
        return {"ok": True}

    def op_r61_clear_goal(self, actor, tick, target):
        record = self._record(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        goals = record.get("goals", [])
        record["goals"] = [g for g in goals if not (g.get("kind") == "retaliate" and g.get("target_id") == target)]
        self.engine.resident_store.touch_resident(actor)
        return {"ok": True, "cleared": len(goals) - len(record["goals"])}

    def op_place_mark(self, actor, tick, name, x, y, space=0.0, source="mark"):
        record = self._record(actor)
        if record is None:
            return {"ok": False, "reason": "no_record"}
        from systems.places import remember
        remember(record, name, x, y, space, tick, source)
        self.engine.resident_store.touch_resident(actor)
        return {"ok": True, "place": name}

    def op_place_ask(self, actor, tick, target, name, closeness=0.0):
        asker, teller = self._record(actor), self._record(target)
        if asker is None or teller is None:
            return {"ok": False, "reason": "no_record"}
        from systems.places import answer_directions
        answer = answer_directions(asker, teller, actor, name, tick)
        if answer["ok"]:
            self.engine.resident_store.touch_resident(actor)
            self.op_relationship(actor, tick, target, "known", closeness)
            self.op_relationship(target, tick, actor, "known", closeness)
        return answer

    def op_commission_request(self, actor, tick, smith, recipe):
        """The Stage 1 customer path: create the order and let the smith decide with the rules provider (what a /commission/request does at drain time)."""
        from systems.commission.access import DEFAULT_INTERACT_RADIUS, engine_interaction_ok, human_position
        from systems.commission.decide import submit_request
        from systems.commission.engine import _slot, context, decision_service, env_for
        customer_slot, smith_slot = _slot(self.engine, actor), _slot(self.engine, smith)
        if customer_slot is None or smith_slot is None:
            return {"ok": False, "reason": "unknown_resident"}
        interaction = engine_interaction_ok(self.engine, customer_slot, human_position(self.engine, smith_slot), DEFAULT_INTERACT_RADIUS)
        if not interaction["ok"]:
            return {"ok": False, "reason": interaction["reason"]}
        result = submit_request(context(self.engine), actor, smith, recipe, decision_service(self.engine), None,
                                env_for(self.engine, smith, actor, interaction=interaction))
        self.engine._force_frame_refresh = True
        return {"ok": bool(result.get("ok", False)), "order_id": result.get("order_id"), "state": result.get("state"), "code": result.get("code", ""),
                "reason": result.get("reason", "")}
