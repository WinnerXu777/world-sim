from __future__ import annotations

"""Stable schedule ops for resident-side integration."""

from .lifecycle import ensure_schedule_state, schedule_refresh_due, set_current_routine
from .prompt_view import build_schedule_prompt_payload, summarize_schedule
from .resolver import choose_schedule_routine


def ensure_resident_schedule(resident: dict, tick: int) -> dict:
    return ensure_schedule_state(resident, tick)


def choose_resident_schedule_routine(resident: dict, tick: int, *, context: dict | None = None) -> dict:
    decision = choose_schedule_routine(resident, tick, context=context)
    if decision.get("ok") and decision.get("routine") is not None:
        routine = dict(decision["routine"])
        set_current_routine(
            resident,
            routine,
            tick,
            reason=str(routine.get("reason", "schedule_default")),
            time_block=str(routine.get("time_block", "")),
        )
    return decision


def schedule_prompt_payload(resident: dict) -> dict:
    return build_schedule_prompt_payload(resident)


def schedule_prompt_summary(resident: dict) -> str:
    return summarize_schedule(resident)


__all__ = [
    "choose_resident_schedule_routine",
    "ensure_resident_schedule",
    "schedule_prompt_payload",
    "schedule_prompt_summary",
    "schedule_refresh_due",
]
