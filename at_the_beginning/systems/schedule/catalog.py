from __future__ import annotations

"""Routine ontology and deterministic defaults for resident schedules."""

from typing import Final


TIME_BLOCKS: Final[tuple[str, ...]] = ("dawn", "day", "dusk", "night")


ROUTINE_DEFS: Final[dict[str, dict[str, object]]] = {
    "sleep": {
        "label": "Sleep",
        "default_priority": 0.95,
        "tags": ("rest", "home", "night"),
    },
    "stay_home": {
        "label": "Stay Home",
        "default_priority": 0.74,
        "tags": ("home", "safe"),
    },
    "return_home": {
        "label": "Return Home",
        "default_priority": 0.78,
        "tags": ("home", "travel"),
    },
    "wander_local": {
        "label": "Wander Local",
        "default_priority": 0.46,
        "tags": ("explore", "local"),
    },
    "gather": {
        "label": "Gather",
        "default_priority": 0.66,
        "tags": ("work", "resource"),
    },
    "work_site": {
        "label": "Work Site",
        "default_priority": 0.7,
        "tags": ("work", "settlement"),
    },
    "patrol": {
        "label": "Patrol",
        "default_priority": 0.61,
        "tags": ("guard", "movement"),
    },
    "guard": {
        "label": "Guard",
        "default_priority": 0.72,
        "tags": ("guard", "home"),
    },
    "socialize": {
        "label": "Socialize",
        "default_priority": 0.52,
        "tags": ("social",),
    },
    "rest": {
        "label": "Rest",
        "default_priority": 0.49,
        "tags": ("rest",),
    },
    "visit_water": {
        "label": "Visit Water",
        "default_priority": 0.55,
        "tags": ("water", "travel"),
    },
}


ROUTINE_KINDS: Final[tuple[str, ...]] = tuple(ROUTINE_DEFS.keys())


DEFAULT_BLOCK_ROUTINES: Final[dict[str, tuple[str, ...]]] = {
    "dawn": ("visit_water", "gather", "wander_local"),
    "day": ("work_site", "gather", "patrol", "wander_local"),
    "dusk": ("socialize", "return_home", "rest"),
    "night": ("sleep", "stay_home", "guard"),
}


TRAIT_ROUTINE_WEIGHTS: Final[dict[str, dict[str, float]]] = {
    "aggression": {"patrol": 0.16, "guard": 0.1, "socialize": -0.04},
    "caution": {"return_home": 0.18, "stay_home": 0.16, "wander_local": -0.14},
    "fearfulness": {"stay_home": 0.2, "sleep": 0.08, "patrol": -0.08},
    "sociability": {"socialize": 0.24, "stay_home": -0.06},
    "discipline": {"work_site": 0.2, "rest": -0.05},
    "resourcefulness": {"gather": 0.18, "visit_water": 0.05},
    "curiosity": {"wander_local": 0.24, "stay_home": -0.1},
    "protectiveness": {"guard": 0.22, "patrol": 0.08},
    "loyalty": {"guard": 0.12, "socialize": 0.05},
}
