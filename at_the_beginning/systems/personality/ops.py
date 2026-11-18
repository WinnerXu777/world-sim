from __future__ import annotations

"""Stable personality ops for resident-side integration."""

from typing import Any

from .appraisal import compute_pressures
from .assign import assign_personality, get_personality, personality_profile_view
from .prompt_view import build_personality_prompt_payload, summarize_personality


def ensure_resident_personality(
    resident: dict[str, Any],
    *,
    human_id: str,
    sex: int,
    preferred_archetype: str | None = None,
) -> dict[str, Any]:
    personality = get_personality(resident)
    if not resident.get("personality"):
        personality = assign_personality(human_id, sex, preferred_archetype=preferred_archetype)
        resident["personality"] = personality
    else:
        resident["personality"] = personality
    resident.setdefault("profile", {})
    resident["profile"]["personality"] = personality_profile_view(resident["personality"])
    return resident["personality"]


def refresh_resident_pressures(resident: dict[str, Any], tick: int) -> dict[str, float]:
    pressures = compute_pressures(resident, tick)
    resident["pressures"] = pressures
    return pressures


def personality_prompt_payload(resident: dict[str, Any]) -> dict[str, Any]:
    return build_personality_prompt_payload(resident)


def personality_prompt_summary(resident: dict[str, Any]) -> str:
    return summarize_personality(resident)
