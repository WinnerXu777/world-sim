from __future__ import annotations

"""Stable resident task ops and queue helpers."""

import json
from itertools import count

from .lifecycle import ensure_task_state
from .prompt_view import build_task_prompt_payload, summarize_tasks
from .resolver import active_task, queued_tasks, task_kind_def
from .schema import build_task_record


_TASK_COUNTER = count(1)


def _next_task_id() -> str:
    return f"task_{next(_TASK_COUNTER):06d}"


def ensure_resident_tasks(resident: dict, tick: int) -> dict:
    return ensure_task_state(resident, tick)


def _task_signature(task: dict) -> tuple:
    return (
        str(task.get("task_kind", "")),
        str(task.get("source", "")),
        str(task.get("summary", "")),
        str(task.get("target_kind", "")),
        str(task.get("target_id", "")),
        str(task.get("required_item", "")),
        int(task.get("requested_quantity") or 0),
        json.dumps(task.get("target_place", {}), sort_keys=True),
        json.dumps(task.get("metadata", {}), sort_keys=True),
    )


def queue_resident_task(
    resident: dict,
    task_kind: str,
    *,
    tick: int,
    priority: float | None = None,
    source: str = "runtime",
    summary: str = "",
    target_kind: str = "",
    target_id: str | None = None,
    target_place: dict | None = None,
    required_item: str = "",
    requested_quantity: int | None = None,
    goal_id: str | None = None,
    plan_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    ensure_task_state(resident, tick)
    task = build_task_record(
        _next_task_id(),
        task_kind,
        tick=tick,
        priority=priority,
        source=source,
        summary=summary,
        target_kind=target_kind,
        target_id=target_id,
        target_place=target_place,
        required_item=required_item,
        requested_quantity=requested_quantity,
        goal_id=goal_id,
        plan_id=plan_id,
        metadata=metadata,
    )
    resident.setdefault("tasks", []).append(task)
    resident.setdefault("task_state", {})["queue_revision"] = int(resident.get("task_state", {}).get("queue_revision", 0)) + 1
    if not resident.get("task_state", {}).get("current_task"):
        start_next_resident_task(resident, tick, reason="queue_bootstrap")
    return task


def _sort_task_records(tasks: list[dict], tick: int) -> list[dict]:
    return sorted(
        [dict(task) for task in tasks if isinstance(task, dict)],
        key=lambda entry: (-float(entry.get("priority", 0.0)), int(entry.get("created_tick", tick))),
    )


def _current_task_interruptible(resident: dict) -> bool:
    current = active_task(resident)
    if not current:
        return False
    kind_def = task_kind_def(str(current.get("task_kind", "")))
    return bool(kind_def.get("interruptible", True))


def _current_task_priority(resident: dict) -> float:
    current = active_task(resident)
    if not current:
        return 0.0
    return float(current.get("priority", 0.0))


def _should_force_clear(reason: str) -> bool:
    return str(reason or "").strip().lower() in {"manual_control", "manual_control_override", "controlled"}


def interrupt_current_task(
    resident: dict,
    tick: int,
    *,
    reason: str = "interrupt",
) -> bool:
    ensure_task_state(resident, tick)
    current = active_task(resident)
    if not current or not _current_task_interruptible(resident):
        return False
    current_id = str(current.get("id", ""))
    paused = resident["task_state"].setdefault("paused_tasks", [])
    for task in list(resident.get("tasks", [])):
        record = dict(task)
        if str(record.get("id", "")) == current_id:
            record["status"] = "paused"
            record["last_update_tick"] = int(tick)
            record.setdefault("metadata", {})["paused_reason"] = str(reason or "")
            paused.append(record)
        elif str(record.get("status", "queued")) in {"queued", "active", "paused"}:
            paused.append(record)
    resident["tasks"] = []
    resident["task_state"]["current_task"] = {}
    resident["task_state"]["current_task_id"] = None
    resident["task_state"]["last_interrupt_reason"] = str(reason or "")
    resident["task_state"]["last_transition_tick"] = int(tick)
    resident["task_state"]["queue_revision"] = int(resident["task_state"].get("queue_revision", 0)) + 1
    resident["task_state"]["paused_tasks"] = _sort_task_records(paused, tick)
    resident["task_state"]["resume_candidate"] = dict(resident["task_state"]["paused_tasks"][0]) if resident["task_state"]["paused_tasks"] else {}
    return True


def resume_paused_tasks(
    resident: dict,
    tick: int,
    *,
    reason: str = "resume",
) -> bool:
    ensure_task_state(resident, tick)
    if resident.get("tasks"):
        return False
    paused = _sort_task_records(list(resident.get("task_state", {}).get("paused_tasks", [])), tick)
    if not paused:
        resident["task_state"]["resume_candidate"] = {}
        return False
    resident["tasks"] = []
    for task in paused:
        record = dict(task)
        record["status"] = "queued"
        record["last_update_tick"] = int(tick)
        record.setdefault("metadata", {})["resumed_reason"] = str(reason or "")
        resident["tasks"].append(record)
    resident["task_state"]["paused_tasks"] = []
    resident["task_state"]["resume_candidate"] = dict(resident["tasks"][0]) if resident["tasks"] else {}
    resident["task_state"]["last_interrupt_reason"] = ""
    resident["task_state"]["queue_revision"] = int(resident["task_state"].get("queue_revision", 0)) + 1
    start_next_resident_task(resident, tick, reason=reason)
    return bool(resident.get("tasks"))


def clear_resident_tasks(resident: dict, tick: int, *, reason: str = "cleared") -> bool:
    ensure_task_state(resident, tick)
    had_tasks = bool(resident.get("tasks")) or bool(resident.get("task_state", {}).get("current_task"))
    resident["tasks"] = []
    resident["task_state"]["current_task"] = {}
    resident["task_state"]["current_task_id"] = None
    resident["task_state"]["blocked_reason"] = str(reason or "")
    resident["task_state"]["last_transition_tick"] = int(tick)
    resident["task_state"]["queue_revision"] = int(resident["task_state"].get("queue_revision", 0)) + 1
    return had_tasks


def replace_resident_tasks(
    resident: dict,
    task_specs: list[dict],
    *,
    tick: int,
    reason: str = "replace_queue",
) -> bool:
    ensure_task_state(resident, tick)
    desired_signatures = [_task_signature(spec) for spec in task_specs]
    current_signatures = [_task_signature(task) for task in list(resident.get("tasks", []))]
    if desired_signatures == current_signatures:
        if task_specs and not resident.get("task_state", {}).get("current_task"):
            start_next_resident_task(resident, tick, reason=reason)
            return True
        if not task_specs and resident.get("tasks"):
            return clear_resident_tasks(resident, tick, reason=reason)
        if not task_specs and resume_paused_tasks(resident, tick, reason=f"resume_after_{reason}"):
            return True
        return False

    current = active_task(resident)
    highest_new_priority = max((float(spec.get("priority", 0.0)) for spec in task_specs), default=0.0)
    current_priority = _current_task_priority(resident)
    current_kind = str(current.get("task_kind", "")) if current else ""
    current_source = str(current.get("source", "")) if current else ""
    desired_kinds = [str(spec.get("task_kind", "")) for spec in task_specs]
    desired_sources = {
        str(spec.get("source", "")).strip()
        for spec in task_specs
        if str(spec.get("source", "")).strip()
    }

    if current and not task_specs:
        if _should_force_clear(reason):
            return clear_resident_tasks(resident, tick, reason=reason)
        return False

    if current and task_specs:
        if current_source in desired_sources and current_kind in desired_kinds:
            pass
        elif highest_new_priority < current_priority:
            return False
        elif not _current_task_interruptible(resident):
            return False
        elif not interrupt_current_task(resident, tick, reason=reason):
            return False

    resident["tasks"] = []
    resident["task_state"]["current_task"] = {}
    resident["task_state"]["current_task_id"] = None
    resident["task_state"]["blocked_reason"] = str(reason or "")
    resident["task_state"]["last_transition_tick"] = int(tick)
    resident["task_state"]["queue_revision"] = int(resident["task_state"].get("queue_revision", 0)) + 1
    for spec in task_specs:
        queue_resident_task(
            resident,
            str(spec.get("task_kind", "")),
            tick=tick,
            priority=spec.get("priority"),
            source=str(spec.get("source", "runtime")),
            summary=str(spec.get("summary", "")),
            target_kind=str(spec.get("target_kind", "")),
            target_id=spec.get("target_id"),
            target_place=dict(spec.get("target_place", {})),
            required_item=str(spec.get("required_item", "")),
            requested_quantity=spec.get("requested_quantity"),
            goal_id=spec.get("goal_id"),
            plan_id=spec.get("plan_id"),
            metadata=dict(spec.get("metadata", {})),
        )
    if not task_specs:
        resident["task_state"]["last_source"] = ""
        return resume_paused_tasks(resident, tick, reason=f"resume_after_{reason}")
    return True


def start_next_resident_task(resident: dict, tick: int, *, reason: str = "queue_start") -> dict | None:
    ensure_task_state(resident, tick)
    tasks = resident.setdefault("tasks", [])
    if not tasks:
        paused = _sort_task_records(list(resident.get("task_state", {}).get("paused_tasks", [])), tick)
        if paused:
            resume_paused_tasks(resident, tick, reason=f"auto_{reason}")
            tasks = resident.setdefault("tasks", [])
            if not tasks:
                resident["task_state"]["current_task"] = {}
                resident["task_state"]["current_task_id"] = None
                resident["task_state"]["blocked_reason"] = str(reason or "")
                resident["task_state"]["last_transition_tick"] = int(tick)
                return None
        else:
            resident["task_state"]["current_task"] = {}
            resident["task_state"]["current_task_id"] = None
            resident["task_state"]["blocked_reason"] = str(reason or "")
            resident["task_state"]["last_transition_tick"] = int(tick)
            return None
    tasks.sort(key=lambda entry: (-float(entry.get("priority", 0.0)), int(entry.get("created_tick", tick))))
    current = dict(tasks[0])
    current["status"] = "active"
    current["last_update_tick"] = int(tick)
    tasks[0] = current
    resident["task_state"]["current_task"] = current
    resident["task_state"]["current_task_id"] = str(current.get("id", ""))
    resident["task_state"]["blocked_reason"] = ""
    resident["task_state"]["last_source"] = str(current.get("source", ""))
    resident["task_state"]["last_transition_tick"] = int(tick)
    resident["task_state"]["resume_candidate"] = {}
    return current


def complete_current_task(resident: dict, tick: int, *, outcome: str = "completed", reason: str = "") -> dict | None:
    ensure_task_state(resident, tick)
    current = active_task(resident)
    if not current:
        return None
    current_id = str(current.get("id", ""))
    remaining: list[dict] = []
    completed: dict | None = None
    for task in list(resident.get("tasks", [])):
        if str(task.get("id", "")) == current_id and completed is None:
            task = dict(task)
            task["status"] = str(outcome or "completed")
            task["last_update_tick"] = int(tick)
            if reason:
                task.setdefault("metadata", {})["completion_reason"] = str(reason)
            completed = task
            continue
        remaining.append(dict(task))
    resident["tasks"] = remaining
    resident["task_state"]["current_task"] = {}
    resident["task_state"]["current_task_id"] = None
    resident["task_state"]["last_completed_task_kind"] = str((completed or {}).get("task_kind", ""))
    resident["task_state"]["last_completed_task"] = dict(completed or {})
    resident["task_state"]["blocked_reason"] = str(reason or "")
    resident["task_state"]["last_transition_tick"] = int(tick)
    start_next_resident_task(resident, tick, reason="post_complete")
    return completed


def task_prompt_payload(resident: dict) -> dict:
    return build_task_prompt_payload(resident)


def task_prompt_summary(resident: dict) -> str:
    return summarize_tasks(resident)


def active_task_payload(resident: dict) -> dict:
    return active_task(resident) or {}


__all__ = [
    "active_task_payload",
    "clear_resident_tasks",
    "complete_current_task",
    "ensure_resident_tasks",
    "interrupt_current_task",
    "queue_resident_task",
    "replace_resident_tasks",
    "resume_paused_tasks",
    "start_next_resident_task",
    "task_prompt_payload",
    "task_prompt_summary",
]
