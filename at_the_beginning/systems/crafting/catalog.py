from __future__ import annotations

"""Declarative crafting recipes for medieval tools and components."""

from typing import Final


def _requirement(item_kind: str, quantity: int) -> dict[str, object]:
    return {
        "item_kind": str(item_kind),
        "quantity": max(int(quantity), 1),
    }


def _recipe(
    label: str,
    *,
    output_kind: str,
    output_quantity: int = 1,
    ingredient_requirements: tuple[tuple[str, int], ...],
    required_tool_tags: tuple[str, ...] = (),
    station_kind: str | None = None,
    occupation_tags: tuple[str, ...] = (),
    time_cost: float = 1.0,
    difficulty: float = 0.1,
    notes: str = "",
) -> dict[str, object]:
    return {
        "label": label,
        "output_kind": str(output_kind),
        "output_quantity": max(int(output_quantity), 1),
        "ingredient_requirements": tuple(
            _requirement(item_kind, quantity)
            for item_kind, quantity in ingredient_requirements
        ),
        "required_tool_tags": tuple(str(tag) for tag in required_tool_tags),
        "station_kind": str(station_kind or ""),
        "occupation_tags": tuple(str(tag) for tag in occupation_tags),
        "time_cost": max(float(time_cost), 0.1),
        "difficulty": round(max(0.0, min(1.0, float(difficulty))), 3),
        "notes": str(notes or ""),
    }


CRAFTING_RECIPE_DEFS: Final[dict[str, dict[str, object]]] = {
    "stone_blade": _recipe(
        "Stone Blade",
        output_kind="stone_blade",
        ingredient_requirements=(("stone_chunk", 1), ("fiber_bundle", 1)),
        required_tool_tags=("knife",),
        occupation_tags=("hunter", "builder", "healer"),
        time_cost=0.5,
        difficulty=0.2,
        notes="A crude cut edge used as a simple component or improvised tool.",
    ),
    "rope": _recipe(
        "Rope",
        output_kind="rope",
        ingredient_requirements=(("fiber_bundle", 3),),
        occupation_tags=("builder", "woodcutter", "trader", "fisherman"),
        time_cost=0.8,
        difficulty=0.18,
        notes="Simple fiber rope used in many later recipes.",
    ),
    "plank_bundle": _recipe(
        "Plank Bundle",
        output_kind="plank_bundle",
        ingredient_requirements=(("wood_log", 1),),
        required_tool_tags=("axe", "knife"),
        occupation_tags=("builder", "woodcutter"),
        time_cost=1.1,
        difficulty=0.25,
        notes="Prepared wood components for later building and tool making.",
    ),
    "club": _recipe(
        "Club",
        output_kind="club",
        ingredient_requirements=(("wood_bundle", 2),),
        required_tool_tags=("knife",),
        occupation_tags=("guard", "hunter"),
        time_cost=0.7,
        difficulty=0.1,
        notes="Basic blunt weapon from shaped wood.",
    ),
    "axe": _recipe(
        "Axe",
        output_kind="axe",
        ingredient_requirements=(
            ("wood_bundle", 2),
            ("stone_blade", 1),
            ("fiber_bundle", 1),
        ),
        required_tool_tags=("knife",),
        occupation_tags=("woodcutter", "builder"),
        time_cost=1.1,
        difficulty=0.26,
        notes="Core cutting tool for wood work and basic labor.",
    ),
    "spear": _recipe(
        "Spear",
        output_kind="spear",
        ingredient_requirements=(
            ("wood_bundle", 2),
            ("stone_blade", 1),
            ("fiber_bundle", 1),
        ),
        required_tool_tags=("knife",),
        occupation_tags=("guard", "hunter"),
        time_cost=1.2,
        difficulty=0.28,
        notes="A simple pole weapon for hunting or defense.",
    ),
    "hoe": _recipe(
        "Hoe",
        output_kind="hoe",
        ingredient_requirements=(
            ("wood_bundle", 2),
            ("stone_blade", 1),
            ("fiber_bundle", 1),
        ),
        required_tool_tags=("knife",),
        occupation_tags=("farmer",),
        time_cost=1.0,
        difficulty=0.22,
        notes="Basic farming tool for ordinary field work.",
    ),
    "hammer": _recipe(
        "Hammer",
        output_kind="hammer",
        ingredient_requirements=(
            ("wood_bundle", 1),
            ("stone_chunk", 1),
            ("fiber_bundle", 1),
        ),
        required_tool_tags=("knife",),
        occupation_tags=("builder",),
        time_cost=1.0,
        difficulty=0.24,
        notes="Basic builder tool for simple construction and repair.",
    ),
    "basket": _recipe(
        "Basket",
        output_kind="basket",
        ingredient_requirements=(("fiber_bundle", 3),),
        occupation_tags=("gatherer", "farmer"),
        time_cost=0.8,
        difficulty=0.12,
        notes="Simple carrying tool for gathering and farm work.",
    ),
    "pack": _recipe(
        "Pack",
        output_kind="pack",
        ingredient_requirements=(("fiber_bundle", 4), ("rope", 1)),
        occupation_tags=("trader",),
        time_cost=1.0,
        difficulty=0.2,
        notes="Light trade pack for carrying ordinary goods.",
    ),
    "fishing_rod": _recipe(
        "Fishing Rod",
        output_kind="fishing_rod",
        ingredient_requirements=(("wood_bundle", 2), ("fiber_bundle", 2)),
        required_tool_tags=("knife",),
        occupation_tags=("fisherman",),
        time_cost=1.0,
        difficulty=0.18,
        notes="Light fishing tool for shoreline work.",
    ),
    "simple_net": _recipe(
        "Simple Net",
        output_kind="simple_net",
        ingredient_requirements=(("fiber_bundle", 4), ("rope", 1)),
        occupation_tags=("fisherman", "gatherer"),
        time_cost=1.4,
        difficulty=0.3,
        notes="Early netting gear for fishing or trapping small catches.",
    ),
    "bandage": _recipe(
        "Bandage",
        output_kind="bandage",
        output_quantity=2,
        ingredient_requirements=(("fiber_bundle", 2), ("herb_bundle", 1)),
        occupation_tags=("healer",),
        time_cost=0.6,
        difficulty=0.12,
        notes="Simple medical wrapping from fiber and herbs.",
    ),
    "torch": _recipe(
        "Torch",
        output_kind="torch",
        ingredient_requirements=(("wood_bundle", 1), ("fiber_bundle", 1)),
        required_tool_tags=("knife",),
        occupation_tags=("guard", "builder", "hunter"),
        time_cost=0.5,
        difficulty=0.1,
        notes="Basic carried light for night travel and guard duty.",
    ),
    "sword": _recipe(
        "Sword",
        output_kind="sword",
        ingredient_requirements=(("iron_ingot", 2), ("wood_bundle", 1)),
        required_tool_tags=("hammer",),
        station_kind="forge",
        occupation_tags=("smith",),
        time_cost=1.5,
        difficulty=0.35,
        notes="Forged at a smithy on commission; never provisioned automatically (see systems/commission).",
    ),
}


CRAFTING_RECIPE_IDS: Final[tuple[str, ...]] = tuple(sorted(CRAFTING_RECIPE_DEFS.keys()))
