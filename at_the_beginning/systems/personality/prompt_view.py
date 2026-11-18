from __future__ import annotations

"""Prompt-facing personality summaries."""

from typing import Any

from .assign import get_personality, get_personality_traits
from .traits import top_traits


def build_personality_prompt_payload(resident: dict[str, Any]) -> dict[str, Any]:
    personality = get_personality(resident)
    traits = get_personality_traits(personality)
    return {
        "archetype": str(personality.get("archetype", "balanced_survivor")),
        "top_traits": list(personality.get("top_traits", top_traits(traits))),
        "traits": {name: round(float(value), 3) for name, value in traits.items()},
    }


def summarize_personality(resident_or_personality: dict[str, Any]) -> str:
    if "profile" in resident_or_personality or "snapshot" in resident_or_personality:
        personality = get_personality(resident_or_personality)
    else:
        personality = resident_or_personality
    traits = get_personality_traits(personality)
    dominant = ", ".join(personality.get("top_traits", top_traits(traits))[:3])
    return f"{personality.get('archetype', 'balanced_survivor')} [{dominant}]"
