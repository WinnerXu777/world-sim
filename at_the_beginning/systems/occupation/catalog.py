from __future__ import annotations

"""Occupation blueprints for a medieval ordinary-life simulation."""

from typing import Final


def _blueprint(
    label: str,
    *,
    block_routines: dict[str, tuple[str, ...]],
    routine_biases: dict[str, float],
    place_tags: tuple[str, ...],
    tool_tags: tuple[str, ...],
    required_tools: tuple[str, ...] = (),
    optional_tools: tuple[str, ...] = (),
    notes: str,
    sampled: bool = True,
) -> dict[str, object]:
    return {
        "sampled": bool(sampled),
        "label": label,
        "block_routines": {key: tuple(value) for key, value in block_routines.items()},
        "routine_biases": dict(routine_biases),
        "place_tags": tuple(place_tags),
        "tool_tags": tuple(tool_tags),
        "required_tools": tuple(required_tools),
        "optional_tools": tuple(optional_tools),
        "notes": notes,
    }


OCCUPATION_DEFS: Final[dict[str, dict[str, object]]] = {
    "farmer": _blueprint(
        "Farmer",
        block_routines={
            "dawn": ("visit_water", "work_site", "gather"),
            "day": ("work_site", "gather", "wander_local"),
            "dusk": ("return_home", "socialize", "rest"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"work_site": 0.22, "gather": 0.1, "return_home": 0.06},
        place_tags=("field", "farm", "settlement"),
        tool_tags=("hoe", "basket", "grain"),
        required_tools=("hoe",),
        optional_tools=("basket",),
        notes="Ordinary field labor and food production.",
    ),
    "fisherman": _blueprint(
        "Fisherman",
        block_routines={
            "dawn": ("visit_water", "gather", "work_site"),
            "day": ("visit_water", "work_site", "rest"),
            "dusk": ("return_home", "socialize", "rest"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"visit_water": 0.26, "work_site": 0.08, "socialize": 0.04},
        place_tags=("water", "shore", "dock"),
        tool_tags=("net", "rod", "knife"),
        required_tools=("fishing_rod",),
        optional_tools=("simple_net", "knife"),
        notes="Lives around water and fishing labor.",
    ),
    "hunter": _blueprint(
        "Hunter",
        block_routines={
            "dawn": ("wander_local", "gather", "visit_water"),
            "day": ("wander_local", "gather", "patrol"),
            "dusk": ("return_home", "rest", "socialize"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"wander_local": 0.24, "gather": 0.1, "patrol": 0.06},
        place_tags=("forest", "wild", "trail"),
        tool_tags=("bow", "spear", "knife"),
        required_tools=("spear",),
        optional_tools=("knife", "torch"),
        notes="Ranges farther from home and works the wild edge.",
    ),
    "guard": _blueprint(
        "Guard",
        block_routines={
            "dawn": ("guard", "patrol", "visit_water"),
            "day": ("guard", "patrol", "socialize"),
            "dusk": ("patrol", "return_home", "guard"),
            "night": ("guard", "sleep"),
        },
        routine_biases={"guard": 0.26, "patrol": 0.18, "return_home": -0.02},
        place_tags=("gate", "wall", "settlement"),
        tool_tags=("spear", "shield", "torch"),
        required_tools=("spear",),
        optional_tools=("torch",),
        notes="Keeps watch, patrols, and responds to threat.",
    ),
    "builder": _blueprint(
        "Builder",
        block_routines={
            "dawn": ("work_site", "gather", "visit_water"),
            "day": ("work_site", "gather", "rest"),
            "dusk": ("return_home", "socialize", "rest"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"work_site": 0.24, "gather": 0.08},
        place_tags=("worksite", "settlement", "quarry"),
        tool_tags=("hammer", "axe", "rope"),
        required_tools=("hammer",),
        optional_tools=("rope", "plank_bundle"),
        notes="Builds and repairs structures.",
    ),
    "woodcutter": _blueprint(
        "Woodcutter",
        block_routines={
            "dawn": ("wander_local", "gather", "visit_water"),
            "day": ("gather", "wander_local", "rest"),
            "dusk": ("return_home", "rest", "socialize"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"gather": 0.22, "wander_local": 0.12},
        place_tags=("forest", "grove", "settlement"),
        tool_tags=("axe", "rope"),
        required_tools=("axe",),
        optional_tools=("rope",),
        notes="Works wooded areas and resource gathering.",
    ),
    "gatherer": _blueprint(
        "Gatherer",
        block_routines={
            "dawn": ("gather", "wander_local", "visit_water"),
            "day": ("gather", "wander_local", "rest"),
            "dusk": ("return_home", "socialize", "rest"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"gather": 0.24, "wander_local": 0.08},
        place_tags=("wild", "grove", "shore"),
        tool_tags=("basket", "knife"),
        required_tools=("basket",),
        optional_tools=("knife",),
        notes="Collects scattered resources and edible goods.",
    ),
    "trader": _blueprint(
        "Trader",
        block_routines={
            "dawn": ("visit_water", "wander_local", "socialize"),
            "day": ("socialize", "work_site", "wander_local"),
            "dusk": ("socialize", "return_home", "rest"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"socialize": 0.26, "wander_local": 0.1, "work_site": 0.04},
        place_tags=("market", "road", "settlement"),
        tool_tags=("coin", "pack", "cart"),
        required_tools=("coin", "pack"),
        optional_tools=("cart",),
        notes="Moves value and spends more time around people.",
    ),
    "smith": _blueprint(
        "Smith",
        block_routines={
            "dawn": ("work_site", "stay_home"),
            "day": ("work_site",),
            "dusk": ("socialize", "return_home"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"work_site": 0.3, "socialize": 0.08, "sleep": 0.06},
        place_tags=("smithy", "worksite", "settlement"),
        tool_tags=("hammer", "iron"),
        required_tools=("hammer",),
        optional_tools=(),
        notes="Works metal at the forge on commission. Assigned by roster only, never drawn at random.",
        sampled=False,
    ),
    "healer": _blueprint(
        "Healer",
        block_routines={
            "dawn": ("visit_water", "work_site", "stay_home"),
            "day": ("work_site", "socialize", "rest"),
            "dusk": ("return_home", "socialize", "rest"),
            "night": ("sleep", "stay_home"),
        },
        routine_biases={"work_site": 0.18, "stay_home": 0.08, "socialize": 0.08},
        place_tags=("home", "hearth", "settlement"),
        tool_tags=("herbs", "bandage", "knife"),
        required_tools=("bandage",),
        optional_tools=("knife",),
        notes="Supports recovery, herbs, and care work.",
    ),
}


# Occupations drawn at random for new residents. Roster-assigned ones (smith) are excluded so legacy sampling
# is unchanged; ALL_OCCUPATION_NAMES is what a preferred (explicitly assigned) kind may be.
OCCUPATION_NAMES: Final[tuple[str, ...]] = tuple(sorted(k for k, v in OCCUPATION_DEFS.items() if v.get("sampled", True)))
ALL_OCCUPATION_NAMES: Final[tuple[str, ...]] = tuple(sorted(OCCUPATION_DEFS.keys()))
