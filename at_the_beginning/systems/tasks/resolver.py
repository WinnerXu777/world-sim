from __future__ import annotations

"""Query helpers for resident task queues."""

from .catalog import TASK_KIND_DEFS


def task_kind_def(task_kind: str) -> dict[str, object]:
    return dict(TASK_KIND_DEFS.get(str(task_kind), {}))


def queued_tasks(resident: dict) -> list[dict]:
    return [dict(task) for task in list(resident.get("tasks", [])) if isinstance(task, dict)]


def paused_tasks(resident: dict) -> list[dict]:
    state = dict(resident.get("task_state", {}))
    return [dict(task) for task in list(state.get("paused_tasks", [])) if isinstance(task, dict)]


def active_task(resident: dict) -> dict | None:
    state = dict(resident.get("task_state", {}))
    current = state.get("current_task")
    if isinstance(current, dict) and current:
        return dict(current)
    tasks = queued_tasks(resident)
    return dict(tasks[0]) if tasks else None
