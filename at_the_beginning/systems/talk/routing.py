from __future__ import annotations

"""Route local speech into tiny-model talk lanes and follow-up tickets."""

from typing import Any

from .schema import MODE_AMBIENT_NPC_TALK, MODE_AMBIENT_TALK, MODE_DIRECT_TALK


def tiny_talk_priority(mode: str) -> float:
    normalized = str(mode or "").strip().lower()
    if normalized == MODE_DIRECT_TALK:
        return 0.93
    if normalized == MODE_AMBIENT_TALK:
        return 0.72
    if normalized == MODE_AMBIENT_NPC_TALK:
        return 0.24
    return 0.0


def build_talk_ticket(
    event: dict[str, Any],
    *,
    tick: int,
    direct_click: bool = False,
    listener_count: int = 0,
) -> dict[str, Any]:
    event = dict(event or {})
    mode = str(event.get("mode", "")).strip().lower()
    if direct_click or mode == MODE_DIRECT_TALK:
        mode = MODE_DIRECT_TALK
        queue = "direct_talk"
    elif mode == MODE_AMBIENT_NPC_TALK:
        queue = "ambient_npc_talk"
    else:
        mode = MODE_AMBIENT_TALK
        queue = "ambient_talk"
    priority = tiny_talk_priority(mode)
    if mode == MODE_AMBIENT_TALK and int(listener_count) > 3:
        priority = min(0.84, priority + 0.05)
    return {
        "queue": queue,
        "mode": mode,
        "event_id": str(event.get("event_id", "")),
        "speaker_id": event.get("speaker_id"),
        "listener_id": event.get("listener_id"),
        "priority": round(priority, 3),
        "queued_tick": int(tick),
    }


def derive_followup_tickets(result: dict[str, Any], *, tick: int) -> dict[str, Any]:
    result = dict(result or {})
    tickets: dict[str, Any] = {
        "urgent": None,
        "reasoning": None,
    }
    target_id = result.get("target_id") or result.get("listener_id") or result.get("primary_listener_id")
    if bool(result.get("danger_upgrade")) and target_id:
        tickets["urgent"] = {
            "queue": "urgent",
            "human_id": str(target_id),
            "reason": "talk_escalation",
            "priority": 0.88,
            "queued_tick": int(tick),
        }
    if bool(result.get("reasoning_followup")) and target_id:
        tickets["reasoning"] = {
            "queue": "reasoning",
            "human_id": str(target_id),
            "reason": "talk_consequence",
            "due_tick": int(tick) + 120,
            "priority": 0.68,
        }
    return tickets


def ambient_npc_budget_sort_key(item: dict[str, Any]) -> tuple[float, float]:
    item = dict(item or {})
    salience = float(item.get("memory_salience", 0.0))
    distance = max(0.0, float(item.get("distance_to_player", 9999.0)))
    return (-salience, distance)
