from __future__ import annotations

"""Lifecycle helpers for resident scheduling state."""

from typing import Any

from .schema import SCHEDULE_SCHEMA_VERSION, build_schedule_profile


DEFAULT_REFRESH_TICKS = 120


def ensure_schedule_state(resident: dict[str, Any], tick: int) -> dict[str, Any]:
    profile = resident.get("schedule_profile")
    if not isinstance(profile, dict) or not profile:
        resident["schedule_profile"] = build_schedule_profile()
    else:
        defaults = build_schedule_profile()
        for key, value in defaults.items():
            resident["schedule_profile"].setdefault(key, value)
    resident.setdefault("schedule_state", {})
    state = resident["schedule_state"]
    state.setdefault("schema_version", SCHEDULE_SCHEMA_VERSION)
    state.setdefault("current_routine", None)
    state.setdefault("last_refresh_tick", max(0, int(tick) - DEFAULT_REFRESH_TICKS))
    state.setdefault("last_time_block", "")
    state.setdefault("last_reason", "")
    return state


def schedule_refresh_due(resident: dict[str, Any], tick: int, *, refresh_ticks: int = DEFAULT_REFRESH_TICKS) -> bool:
    state = ensure_schedule_state(resident, tick)
    last_refresh = int(state.get("last_refresh_tick", 0))
    return int(tick) - last_refresh >= int(refresh_ticks)


def set_current_routine(
    resident: dict[str, Any],
    routine: dict[str, Any] | None,
    tick: int,
    *,
    reason: str = "",
    time_block: str = "",
) -> dict[str, Any]:
    state = ensure_schedule_state(resident, tick)
    state["current_routine"] = None if routine is None else dict(routine)
    state["last_refresh_tick"] = int(tick)
    state["last_reason"] = str(reason or state.get("last_reason", ""))
    if time_block:
        state["last_time_block"] = str(time_block)
    return state


def clear_current_routine(resident: dict[str, Any], tick: int, *, reason: str = "") -> dict[str, Any]:
    state = ensure_schedule_state(resident, tick)
    state["current_routine"] = None
    state["last_refresh_tick"] = int(tick)
    if reason:
        state["last_reason"] = str(reason)
    return state
