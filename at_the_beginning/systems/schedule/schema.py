from __future__ import annotations

"""Builders for resident schedule profiles and current routine records."""

from typing import Any

from .catalog import DEFAULT_BLOCK_ROUTINES, TIME_BLOCKS


SCHEDULE_SCHEMA_VERSION = 1


def default_block_preferences() -> dict[str, list[str]]:
    return {block: list(DEFAULT_BLOCK_ROUTINES.get(block, ())) for block in TIME_BLOCKS}


def build_schedule_profile(
    *,
    home_anchor_kind: str = "resident_home",
    home_anchor_id: str | None = None,
    block_preferences: dict[str, list[str]] | None = None,
    stability: float = 0.82,
    novelty_bias: float = 0.1,
    commitment_window_ticks: int = 240,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "home_anchor_kind": str(home_anchor_kind or "resident_home"),
        "home_anchor_id": home_anchor_id,
        "block_preferences": dict(block_preferences or default_block_preferences()),
        "stability": round(max(0.0, min(1.0, float(stability))), 3),
        "novelty_bias": round(max(0.0, min(1.0, float(novelty_bias))), 3),
        "commitment_window_ticks": max(30, int(commitment_window_ticks)),
        "notes": str(notes or ""),
    }


def build_routine_record(
    kind: str,
    *,
    tick: int,
    time_block: str,
    reason: str = "schedule_default",
    priority: float = 0.5,
    target_place: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": str(kind),
        "status": "active",
        "priority": round(max(0.0, min(1.0, float(priority))), 3),
        "time_block": str(time_block),
        "reason": str(reason or "schedule_default"),
        "created_tick": int(tick),
        "last_update_tick": int(tick),
        "target_place": dict(target_place or {}),
        "metadata": dict(metadata or {}),
    }
