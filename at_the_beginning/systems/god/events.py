"""Intervention events: one causal id per event, perceived only by witnesses, remembered once per witness."""
from .state import new_event_id, store

KINDS = {"divine_gift": "A gift appeared from nowhere", "divine_heal": "Wounds closed by themselves",
         "weather_changed": "The weather changed"}


def commit_event(engine, kind, *, point, target_id=None, note="", extra=None, witnesses=()):
    """Record the event in the ledger and in each witness's memory exactly once. Returns the event record.

    ``witnesses`` are human ids already filtered by the caller. A witness already in the ledger entry (same event id)
    is skipped, so replaying the commit (or restoring and re-running it) never affects a resident twice.
    """
    data = store(engine)
    event_id = (extra or {}).get("event_id") or new_event_id(engine)
    entry = data["events"].setdefault(event_id, {"id": event_id, "kind": kind, "tick": engine.tick, "target_id": target_id,
                                                  "point": [round(point[0], 2), round(point[1], 2)], "witnesses": []})
    fresh = [w for w in witnesses if w not in entry["witnesses"]]
    for human_id in fresh:
        engine.resident_store.record_event(human_id, engine.tick, kind, note=note or KINDS.get(kind, kind),
                                           other_human_id=target_id if target_id and target_id != human_id else None,
                                           extra={"event_id": event_id, "god": True, **{k: v for k, v in (extra or {}).items() if k != "event_id"}})
        entry["witnesses"].append(human_id)
    if fresh:
        engine._queue_event(kind, event_id, -1, target_id=target_id, witnesses=len(entry["witnesses"]))
        engine._force_frame_refresh = True
    return entry


def remembers(engine, human_id, kind):
    """The events of ``kind`` in a resident's recent memory."""
    resident = engine.resident_store.get(human_id) or {}
    return [e for e in resident.get("memory", {}).get("recent_events", []) if e.get("kind") == kind]
