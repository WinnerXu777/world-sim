from __future__ import annotations

"""Prompt-facing schedule summaries."""

from typing import Any


def build_schedule_prompt_payload(resident: dict[str, Any]) -> dict[str, Any]:
    profile = dict(resident.get("schedule_profile", {}))
    state = dict(resident.get("schedule_state", {}))
    return {
        "home_anchor_kind": str(profile.get("home_anchor_kind", "resident_home")),
        "home_anchor_id": profile.get("home_anchor_id"),
        "block_preferences": dict(profile.get("block_preferences", {})),
        "current_routine": dict(state.get("current_routine") or {}),
        "last_time_block": str(state.get("last_time_block", "")),
        "last_reason": str(state.get("last_reason", "")),
    }


def summarize_schedule(resident: dict[str, Any]) -> str:
    payload = build_schedule_prompt_payload(resident)
    current = dict(payload.get("current_routine") or {})
    if current:
        return f"{current.get('kind', 'unknown')} during {current.get('time_block', payload.get('last_time_block', 'unknown'))}"
    last_block = str(payload.get("last_time_block", "")).strip()
    if last_block:
        return f"no active routine; last block {last_block}"
    return "schedule not yet assigned"
