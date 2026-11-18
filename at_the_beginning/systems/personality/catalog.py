from __future__ import annotations

"""Personality archetype presets and trait vocabulary."""

from typing import Final


TRAIT_NAMES: Final[tuple[str, ...]] = (
    "aggression",
    "caution",
    "vengefulness",
    "greed",
    "loyalty",
    "mercy",
    "pride",
    "fearfulness",
    "curiosity",
    "ambition",
    "deceitfulness",
    "protectiveness",
    "sociability",
    "discipline",
    "resourcefulness",
    "resolve",
)

LEGACY_TRAIT_NAMES: Final[tuple[str, ...]] = (
    "caution",
    "sociability",
    "resourcefulness",
    "resolve",
)

BALANCED_BASE: Final[dict[str, float]] = {
    "aggression": 0.48,
    "caution": 0.52,
    "vengefulness": 0.42,
    "greed": 0.45,
    "loyalty": 0.52,
    "mercy": 0.5,
    "pride": 0.48,
    "fearfulness": 0.44,
    "curiosity": 0.5,
    "ambition": 0.46,
    "deceitfulness": 0.32,
    "protectiveness": 0.5,
    "sociability": 0.5,
    "discipline": 0.5,
    "resourcefulness": 0.52,
    "resolve": 0.52,
}


def _preset(**overrides: float) -> dict[str, float]:
    preset = dict(BALANCED_BASE)
    preset.update(overrides)
    return preset


ARCHETYPE_PRESETS: Final[dict[str, dict[str, float]]] = {
    "balanced_survivor": _preset(),
    "avenger": _preset(
        aggression=0.7,
        vengefulness=0.88,
        pride=0.72,
        mercy=0.22,
        fearfulness=0.28,
        resolve=0.76,
    ),
    "guardian": _preset(
        aggression=0.56,
        loyalty=0.82,
        mercy=0.66,
        protectiveness=0.88,
        discipline=0.7,
        resolve=0.7,
    ),
    "greedy_scavenger": _preset(
        greed=0.9,
        deceitfulness=0.62,
        ambition=0.6,
        loyalty=0.32,
        mercy=0.28,
        resourcefulness=0.7,
    ),
    "opportunist": _preset(
        aggression=0.54,
        greed=0.68,
        ambition=0.66,
        deceitfulness=0.66,
        resourcefulness=0.76,
        sociability=0.44,
    ),
    "schemer": _preset(
        aggression=0.34,
        caution=0.68,
        greed=0.62,
        pride=0.64,
        ambition=0.8,
        deceitfulness=0.86,
        resolve=0.58,
    ),
    "tribalist": _preset(
        aggression=0.58,
        loyalty=0.86,
        protectiveness=0.76,
        sociability=0.72,
        mercy=0.42,
        resolve=0.68,
    ),
    "coward": _preset(
        aggression=0.18,
        caution=0.82,
        vengefulness=0.24,
        fearfulness=0.86,
        ambition=0.22,
        resolve=0.3,
    ),
    "bully": _preset(
        aggression=0.86,
        vengefulness=0.62,
        greed=0.58,
        loyalty=0.22,
        mercy=0.12,
        pride=0.72,
        fearfulness=0.2,
    ),
    "caretaker": _preset(
        aggression=0.24,
        loyalty=0.76,
        mercy=0.82,
        fearfulness=0.5,
        protectiveness=0.9,
        sociability=0.7,
    ),
    "stoic_survivor": _preset(
        aggression=0.42,
        caution=0.64,
        mercy=0.4,
        fearfulness=0.24,
        discipline=0.78,
        resourcefulness=0.72,
        resolve=0.88,
    ),
    "wanderer": _preset(
        caution=0.34,
        greed=0.34,
        curiosity=0.9,
        loyalty=0.32,
        ambition=0.52,
        sociability=0.36,
    ),
    "social_climber": _preset(
        aggression=0.42,
        greed=0.56,
        pride=0.68,
        ambition=0.88,
        deceitfulness=0.56,
        sociability=0.78,
    ),
    "hoarder": _preset(
        aggression=0.28,
        caution=0.68,
        greed=0.84,
        curiosity=0.26,
        discipline=0.74,
        resourcefulness=0.66,
    ),
    "raider": _preset(
        aggression=0.88,
        greed=0.74,
        loyalty=0.44,
        mercy=0.12,
        pride=0.74,
        fearfulness=0.18,
        resolve=0.78,
    ),
    "hermit": _preset(
        aggression=0.26,
        caution=0.72,
        loyalty=0.34,
        mercy=0.54,
        curiosity=0.58,
        sociability=0.12,
        discipline=0.68,
    ),
}


ARCHETYPE_NAMES: Final[tuple[str, ...]] = tuple(sorted(ARCHETYPE_PRESETS.keys()))
