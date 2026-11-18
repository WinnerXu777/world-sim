from __future__ import annotations

"""Plan record builders."""

from typing import Any

from .catalog import PLAN_KIND_DEFS


PLAN_SCHEMA_VERSION = 1


def build_plan_step(
    op: str,
    *,
    target_id: str | None = None,
    place_hint: str = "",
    threshold: float | None = None,
    target_tick: int | None = None,
    count: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "op": str(op),
        "target_id": target_id,
        "place_hint": str(place_hint or ""),
        "threshold": None if threshold is None else round(float(threshold), 3),
        "target_tick": None if target_tick is None else int(target_tick),
        "count": None if count is None else int(count),
        "metadata": dict(metadata or {}),
    }


def build_plan_record(
    plan_id: str,
    plan_kind: str,
    *,
    tick: int,
    goal_id: str | None = None,
    priority: float = 0.5,
    confidence: float | None = None,
    status: str = "queued",
    origin: str = "reasoning",
    steps: list[dict[str, Any]] | None = None,
    expires_tick: int | None = None,
    summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan_def = PLAN_KIND_DEFS.get(plan_kind, {})
    default_confidence = float(plan_def.get("default_confidence", 0.5))
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "id": str(plan_id),
        "goal_id": goal_id,
        "plan_kind": str(plan_kind),
        "priority": round(max(0.0, min(1.0, float(priority))), 3),
        "confidence": round(
            max(0.0, min(1.0, float(default_confidence if confidence is None else confidence))),
            3,
        ),
        "status": str(status),
        "origin": str(origin),
        "summary": str(summary or ""),
        "steps": [dict(step) for step in list(steps or [])],
        "current_step_index": 0,
        "created_tick": int(tick),
        "last_review_tick": int(tick),
        "last_update_tick": int(tick),
        "expires_tick": None if expires_tick is None else int(expires_tick),
        "metadata": dict(metadata or {}),
    }


def plan_identity(plan: dict[str, Any]) -> tuple[str, str | None]:
    return (str(plan.get("plan_kind", "")), plan.get("goal_id"))
