"""Deterministic ordinary-life scheduling helpers for residents."""

from .catalog import DEFAULT_BLOCK_ROUTINES, ROUTINE_DEFS, ROUTINE_KINDS, TIME_BLOCKS
from .lifecycle import (
    clear_current_routine,
    ensure_schedule_state,
    schedule_refresh_due,
    set_current_routine,
)
from .navigation import build_schedule_navigation_bias
from .ops import (
    choose_resident_schedule_routine,
    ensure_resident_schedule,
    schedule_prompt_payload,
    schedule_prompt_summary,
)
from .prompt_view import build_schedule_prompt_payload, summarize_schedule
from .resolver import choose_schedule_routine, routine_candidates_for_tick, tick_to_time_block
from .schema import (
    SCHEDULE_SCHEMA_VERSION,
    build_routine_record,
    build_schedule_profile,
    default_block_preferences,
)

__all__ = [
    "DEFAULT_BLOCK_ROUTINES",
    "ROUTINE_DEFS",
    "ROUTINE_KINDS",
    "SCHEDULE_SCHEMA_VERSION",
    "TIME_BLOCKS",
    "build_routine_record",
    "build_schedule_profile",
    "build_schedule_prompt_payload",
    "build_schedule_navigation_bias",
    "choose_resident_schedule_routine",
    "choose_schedule_routine",
    "clear_current_routine",
    "default_block_preferences",
    "ensure_resident_schedule",
    "ensure_schedule_state",
    "routine_candidates_for_tick",
    "schedule_prompt_payload",
    "schedule_prompt_summary",
    "schedule_refresh_due",
    "set_current_routine",
    "summarize_schedule",
    "tick_to_time_block",
]
