from __future__ import annotations

"""Goal record builders."""

from typing import Any

from .catalog import GOAL_DEFS


GOAL_SCHEMA_VERSION = 1


def build_goal_record(
    goal_id: str,
    kind: str,
    *,
    tick: int,
    priority: float,
    target_id: str | None = None,
    target_place: dict[str, Any] | None = None,
    horizon: str | None = None,
    status: str = "active",
    origin: str = "review",
    plan_hint: str = "",
    confidence: float = 0.5,
    expires_tick: int | None = None,
    success_condition: str = "",
    failure_condition: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    goal_def = GOAL_DEFS.get(kind, {})
    return {
        "schema_version": GOAL_SCHEMA_VERSION,
        "id": goal_id,
        "kind": kind,
        "priority": round(max(0.0, min(1.0, float(priority))), 3),
        "target_id": target_id,
        "target_place": dict(target_place or {}),
        "horizon": str(horizon or goal_def.get("horizon", "medium")),
        "status": status,
        "origin": origin,
        "plan_hint": plan_hint,
        "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
        "created_tick": int(tick),
        "last_review_tick": int(tick),
        "expires_tick": None if expires_tick is None else int(expires_tick),
        "success_condition": success_condition,
        "failure_condition": failure_condition,
        "metadata": dict(metadata or {}),
    }


def goal_identity(goal: dict[str, Any]) -> tuple[str, str | None, str | None]:
    target_place = goal.get("target_place") or {}
    place_key = None
    if target_place:
        place_key = f"{target_place.get('kind', '')}:{target_place.get('entity_id', '')}:{target_place.get('x', '')}:{target_place.get('y', '')}"
    return (str(goal.get("kind", "")), goal.get("target_id"), place_key)
