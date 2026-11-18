from __future__ import annotations

"""Resolve occupation-driven schedule preferences and prompt views."""

from typing import Any

from .catalog import OCCUPATION_DEFS


def get_occupation(resident: dict[str, Any]) -> dict[str, Any]:
    occupation = resident.get("occupation")
    return dict(occupation or {})


def occupation_kind(resident: dict[str, Any]) -> str:
    return str(get_occupation(resident).get("kind", ""))


def occupation_def(resident_or_kind: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(resident_or_kind, dict):
        kind = str(get_occupation(resident_or_kind).get("kind", ""))
    else:
        kind = str(resident_or_kind or "")
    return dict(OCCUPATION_DEFS.get(kind, {}))


def occupation_block_preferences(resident: dict[str, Any], *, time_block: str | None = None) -> dict[str, list[str]] | list[str]:
    blueprint = occupation_def(resident)
    block_routines = {key: list(value) for key, value in dict(blueprint.get("block_routines", {})).items()}
    if time_block is None:
        return block_routines
    return list(block_routines.get(str(time_block), []))


def occupation_routine_biases(resident: dict[str, Any]) -> dict[str, float]:
    blueprint = occupation_def(resident)
    return {str(key): float(value) for key, value in dict(blueprint.get("routine_biases", {})).items()}


def occupation_preferred_place_tags(resident: dict[str, Any]) -> list[str]:
    blueprint = occupation_def(resident)
    return [str(item) for item in list(blueprint.get("place_tags", ()))]


def occupation_preferred_tool_tags(resident: dict[str, Any]) -> list[str]:
    blueprint = occupation_def(resident)
    return [str(item) for item in list(blueprint.get("tool_tags", ()))]


def occupation_required_tools(resident: dict[str, Any]) -> list[str]:
    blueprint = occupation_def(resident)
    return [str(item) for item in list(blueprint.get("required_tools", ()))]


def occupation_optional_tools(resident: dict[str, Any]) -> list[str]:
    blueprint = occupation_def(resident)
    return [str(item) for item in list(blueprint.get("optional_tools", ()))]
