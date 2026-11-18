from __future__ import annotations

"""Task record builders for resident activity queues."""

from typing import Any

from .catalog import TASK_KIND_DEFS


TASK_SCHEMA_VERSION = 1


def build_task_record(
    task_id: str,
    task_kind: str,
    *,
    tick: int,
    status: str = "queued",
    priority: float | None = None,
    source: str = "runtime",
    summary: str = "",
    target_kind: str = "",
    target_id: str | None = None,
    target_place: dict[str, Any] | None = None,
    required_item: str = "",
    requested_quantity: int | None = None,
    goal_id: str | None = None,
    plan_id: str | None = None,
    expires_tick: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind_def = TASK_KIND_DEFS.get(str(task_kind), {})
    resolved_priority = float(kind_def.get("default_priority", 0.5) if priority is None else priority)
    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "id": str(task_id),
        "task_kind": str(task_kind),
        "status": str(status or "queued"),
        "priority": round(max(0.0, min(1.0, resolved_priority)), 3),
        "source": str(source or "runtime"),
        "summary": str(summary or kind_def.get("label", task_kind)),
        "target_kind": str(target_kind or ""),
        "target_id": target_id,
        "target_place": dict(target_place or {}),
        "required_item": str(required_item or ""),
        "requested_quantity": None if requested_quantity is None else max(1, int(requested_quantity)),
        "goal_id": goal_id,
        "plan_id": plan_id,
        "created_tick": int(tick),
        "last_update_tick": int(tick),
        "expires_tick": None if expires_tick is None else int(expires_tick),
        "metadata": dict(metadata or {}),
    }


def build_task_state(
    *,
    tick: int,
    current_task_id: str | None = None,
    current_task: dict[str, Any] | None = None,
    last_transition_tick: int | None = None,
    blocked_reason: str = "",
    last_completed_task_kind: str = "",
    last_source: str = "",
    last_task_action: str = "",
    last_interrupt_reason: str = "",
    last_completed_task: dict[str, Any] | None = None,
    paused_tasks: list[dict[str, Any]] | None = None,
    resume_candidate: dict[str, Any] | None = None,
    cargo_cache: dict[str, int] | None = None,
    carry_manifest: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "current_task_id": current_task_id,
        "current_task": dict(current_task or {}),
        "last_transition_tick": int(tick if last_transition_tick is None else last_transition_tick),
        "blocked_reason": str(blocked_reason or ""),
        "last_completed_task_kind": str(last_completed_task_kind or ""),
        "last_source": str(last_source or ""),
        "last_task_action": str(last_task_action or ""),
        "last_interrupt_reason": str(last_interrupt_reason or ""),
        "last_completed_task": dict(last_completed_task or {}),
        "paused_tasks": [dict(task) for task in list(paused_tasks or []) if isinstance(task, dict)],
        "resume_candidate": dict(resume_candidate or {}),
        "cargo_cache": {
            str(item_kind): max(int(quantity), 0)
            for item_kind, quantity in dict(cargo_cache or {}).items()
            if str(item_kind).strip() and max(int(quantity), 0) > 0
        },
        "carry_manifest": {
            str(item_kind): max(int(quantity), 0)
            for item_kind, quantity in dict(carry_manifest or {}).items()
            if str(item_kind).strip() and max(int(quantity), 0) > 0
        },
    }
