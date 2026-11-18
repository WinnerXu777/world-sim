"""Personality blueprints, trait assignment, and appraisal helpers."""

from .appraisal import compute_pressures
from .assign import (
    PERSONALITY_SCHEMA_VERSION,
    assign_personality,
    get_personality,
    get_personality_traits,
    legacy_decision_traits,
    personality_profile_view,
)
from .catalog import ARCHETYPE_NAMES, ARCHETYPE_PRESETS, LEGACY_TRAIT_NAMES, TRAIT_NAMES
from .ops import (
    ensure_resident_personality,
    personality_prompt_payload,
    personality_prompt_summary,
    refresh_resident_pressures,
)
from .prompt_view import build_personality_prompt_payload, summarize_personality

__all__ = [
    "ARCHETYPE_NAMES",
    "ARCHETYPE_PRESETS",
    "LEGACY_TRAIT_NAMES",
    "PERSONALITY_SCHEMA_VERSION",
    "TRAIT_NAMES",
    "assign_personality",
    "build_personality_prompt_payload",
    "compute_pressures",
    "ensure_resident_personality",
    "get_personality",
    "get_personality_traits",
    "legacy_decision_traits",
    "personality_profile_view",
    "personality_prompt_payload",
    "personality_prompt_summary",
    "refresh_resident_pressures",
    "summarize_personality",
]
