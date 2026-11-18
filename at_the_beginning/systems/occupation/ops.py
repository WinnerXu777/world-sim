from __future__ import annotations

"""Stable occupation ops for resident-side integration and schedule shaping."""

from .assign import assign_occupation
from .prompt_view import build_occupation_prompt_payload, summarize_occupation
from .resolver import (
    get_occupation,
    occupation_block_preferences,
    occupation_optional_tools,
    occupation_required_tools,
    occupation_routine_biases,
)


def ensure_resident_occupation(
    resident: dict,
    *,
    human_id: str,
    personality: dict | None = None,
    parent_occupations: list[str] | tuple[str, ...] | None = None,
    preferred_kind: str | None = None,
) -> dict:
    occupation = get_occupation(resident)
    if not occupation:
        occupation = assign_occupation(
            human_id,
            personality=personality or resident.get("personality"),
            parent_occupations=parent_occupations,
            preferred_kind=preferred_kind,
        )
        resident["occupation"] = occupation
    return dict(resident.get("occupation", {}))


def occupation_schedule_block_preferences(resident: dict, *, time_block: str) -> list[str]:
    return list(occupation_block_preferences(resident, time_block=time_block))


def occupation_routine_score_adjustment(resident: dict, kind: str, *, time_block: str) -> float:
    biases = occupation_routine_biases(resident)
    block_preferences = occupation_schedule_block_preferences(resident, time_block=time_block)
    score = float(biases.get(str(kind), 0.0))
    if block_preferences:
        try:
            index = block_preferences.index(str(kind))
        except ValueError:
            index = -1
        if index == 0:
            score += 0.14
        elif index == 1:
            score += 0.08
        elif index == 2:
            score += 0.04
    return round(score, 4)


def occupation_prompt_payload(resident: dict) -> dict:
    return build_occupation_prompt_payload(resident)


def occupation_prompt_summary(resident: dict) -> str:
    return summarize_occupation(resident)


def occupation_core_tools(resident: dict) -> list[str]:
    return occupation_required_tools(resident)


def occupation_upgrade_tools(resident: dict) -> list[str]:
    return occupation_optional_tools(resident)


__all__ = [
    "ensure_resident_occupation",
    "occupation_core_tools",
    "occupation_prompt_payload",
    "occupation_prompt_summary",
    "occupation_routine_score_adjustment",
    "occupation_schedule_block_preferences",
    "occupation_upgrade_tools",
]
