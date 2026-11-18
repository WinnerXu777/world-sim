from __future__ import annotations

"""Resident task queue lifecycle helpers."""

from copy import deepcopy
from typing import Any

from .schema import TASK_SCHEMA_VERSION, build_task_state


TASK_STATE_SCHEMA_VERSION = 1


def _default_task_state(tick: int) -> dict[str, Any]:
    state = build_task_state(tick=tick)
    state["schema_version"] = TASK_STATE_SCHEMA_VERSION
    state.setdefault("queue_revision", 0)
    return state


def ensure_task_state(resident: dict[str, Any], tick: int) -> dict[str, Any]:
    tasks = resident.get("tasks")
    if not isinstance(tasks, list):
        resident["tasks"] = []
    else:
        resident["tasks"] = [dict(task) for task in tasks if isinstance(task, dict)]

    state = resident.get("task_state")
    if not isinstance(state, dict) or not state:
        resident["task_state"] = _default_task_state(tick)
    else:
        defaults = _default_task_state(tick)
        for key, value in defaults.items():
            if key not in resident["task_state"]:  # setdefault(key, deepcopy(value)) copied the default on every call
                resident["task_state"][key] = deepcopy(value)
        paused_tasks = resident["task_state"].get("paused_tasks")
        if not isinstance(paused_tasks, list):
            resident["task_state"]["paused_tasks"] = []
        else:
            resident["task_state"]["paused_tasks"] = [dict(task) for task in paused_tasks if isinstance(task, dict)]
        if not isinstance(resident["task_state"].get("last_completed_task"), dict):
            resident["task_state"]["last_completed_task"] = {}
        if not isinstance(resident["task_state"].get("resume_candidate"), dict):
            resident["task_state"]["resume_candidate"] = {}

    current_task = resident["task_state"].get("current_task")
    current_task_id = str(resident["task_state"].get("current_task_id") or "")
    if not isinstance(current_task, dict):
        resident["task_state"]["current_task"] = {}
    elif current_task and not current_task_id:
        resident["task_state"]["current_task_id"] = str(current_task.get("id", ""))

    queued = resident.get("tasks", [])
    if queued and not resident["task_state"].get("current_task"):
        resident["task_state"]["current_task"] = dict(queued[0])
        resident["task_state"]["current_task_id"] = str(queued[0].get("id", ""))

    return resident["task_state"]
