from __future__ import annotations

"""Prompt-facing occupation summaries."""

from .resolver import (
    get_occupation,
    occupation_kind,
    occupation_optional_tools,
    occupation_preferred_place_tags,
    occupation_preferred_tool_tags,
    occupation_required_tools,
)


def build_occupation_prompt_payload(resident: dict) -> dict:
    occupation = get_occupation(resident)
    return {
        "kind": occupation_kind(resident),
        "origin": str(occupation.get("origin", "")),
        "parent_bias": str(occupation.get("parent_bias", "")),
        "skill": float(occupation.get("skill", 0.0)),
        "stability": float(occupation.get("stability", 0.0)),
        "mutation": bool(occupation.get("mutation", False)),
        "place_tags": occupation_preferred_place_tags(resident),
        "tool_tags": occupation_preferred_tool_tags(resident),
        "required_tools": occupation_required_tools(resident),
        "optional_tools": occupation_optional_tools(resident),
    }


def summarize_occupation(resident: dict) -> str:
    payload = build_occupation_prompt_payload(resident)
    kind = str(payload.get("kind", "")).strip()
    if not kind:
        return "no occupation"
    origin = str(payload.get("origin", "")).strip()
    if origin:
        return f"{kind} ({origin})"
    return kind
