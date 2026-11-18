from __future__ import annotations

"""Deterministic personality assignment and compatibility helpers."""

import hashlib
import random
from typing import Any

from .catalog import ARCHETYPE_NAMES, ARCHETYPE_PRESETS, BALANCED_BASE, LEGACY_TRAIT_NAMES
from .traits import jitter_traits, normalize_traits, top_traits


PERSONALITY_SCHEMA_VERSION = 1


def _stable_seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _pick_archetype(human_id: str, sex: int, preferred_archetype: str | None = None) -> str:
    if preferred_archetype and preferred_archetype in ARCHETYPE_PRESETS:
        return preferred_archetype
    rng = random.Random(_stable_seed(f"{human_id}:{sex}:archetype"))
    return ARCHETYPE_NAMES[rng.randrange(len(ARCHETYPE_NAMES))]


def assign_personality(
    human_id: str,
    sex: int,
    *,
    preferred_archetype: str | None = None,
) -> dict[str, Any]:
    archetype = _pick_archetype(human_id, sex, preferred_archetype=preferred_archetype)
    seed = _stable_seed(f"{human_id}:{sex}:{archetype}:traits")
    rng = random.Random(seed)
    traits = jitter_traits(ARCHETYPE_PRESETS[archetype], rng)
    return {
        "schema_version": PERSONALITY_SCHEMA_VERSION,
        "archetype": archetype,
        "birth_seed": seed,
        "traits": traits,
        "top_traits": top_traits(traits),
    }


def personality_profile_view(personality: dict[str, Any]) -> dict[str, Any]:
    normalized = get_personality_traits(personality)
    view: dict[str, Any] = {
        "archetype": str(personality.get("archetype", "balanced_survivor")),
        "top_traits": list(personality.get("top_traits", top_traits(normalized))),
    }
    for key, value in normalized.items():
        view[key] = value
    return view


def get_personality_traits(personality: dict[str, Any] | None) -> dict[str, float]:
    if not personality:
        return dict(BALANCED_BASE)
    traits = personality.get("traits")
    if isinstance(traits, dict):
        return normalize_traits(traits)
    legacy = {name: personality.get(name, BALANCED_BASE[name]) for name in BALANCED_BASE}
    return normalize_traits(legacy)


def get_personality(resident: dict[str, Any]) -> dict[str, Any]:
    top_level = resident.get("personality")
    if isinstance(top_level, dict) and top_level:
        personality = dict(top_level)
        personality["traits"] = get_personality_traits(personality)
        personality["top_traits"] = list(personality.get("top_traits", top_traits(personality["traits"])))
        personality.setdefault("schema_version", PERSONALITY_SCHEMA_VERSION)
        personality.setdefault("archetype", "balanced_survivor")
        return personality

    profile = resident.get("profile", {})
    legacy = profile.get("personality", {})
    personality = {
        "schema_version": PERSONALITY_SCHEMA_VERSION,
        "archetype": str(legacy.get("archetype", "balanced_survivor")),
        "birth_seed": None,
        "traits": get_personality_traits(legacy),
    }
    personality["top_traits"] = list(top_traits(personality["traits"]))
    return personality


def legacy_decision_traits(personality: dict[str, Any]) -> dict[str, float]:
    traits = get_personality_traits(personality)
    return {name: float(traits.get(name, BALANCED_BASE[name])) for name in LEGACY_TRAIT_NAMES}
