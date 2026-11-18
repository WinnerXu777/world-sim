from __future__ import annotations

"""Prompt-facing summaries for resident tasks."""

from typing import Any

from .resolver import active_task, queued_tasks


def build_task_prompt_payload(resident: dict[str, Any]) -> dict[str, Any]:
    tasks = queued_tasks(resident)
    state = dict(resident.get("task_state", {}))
    return {
        "current_task": active_task(resident) or {},
        "queued_tasks": tasks[:4],
        "queued_count": len(tasks),
        "task_state": state,
        "cargo_cache": dict(state.get("cargo_cache", {})),
    }


def summarize_tasks(resident: dict[str, Any]) -> str:
    payload = build_task_prompt_payload(resident)
    current = dict(payload.get("current_task") or {})
    if current:
        task_kind = str(current.get("task_kind", "unknown"))
        status = str(current.get("status", "queued"))
        source = str(current.get("source", "runtime"))
        return f"{task_kind} ({status}, {source})"
    cargo_cache = dict(payload.get("cargo_cache", {}))
    if cargo_cache:
        cargo_summary = ", ".join(f"{kind}:{qty}" for kind, qty in sorted(cargo_cache.items()))
        return f"carrying task cargo {cargo_summary}"
    queued_count = int(payload.get("queued_count", 0))
    if queued_count > 0:
        return f"{queued_count} queued task(s)"
    return "no active tasks"
