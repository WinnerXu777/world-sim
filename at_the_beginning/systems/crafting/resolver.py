from __future__ import annotations

"""Lightweight query helpers for crafting recipes."""

from .catalog import CRAFTING_RECIPE_DEFS, CRAFTING_RECIPE_IDS


def crafting_recipe_ids() -> tuple[str, ...]:
    return CRAFTING_RECIPE_IDS


def crafting_recipe_def(recipe_id: str) -> dict[str, object]:
    return dict(CRAFTING_RECIPE_DEFS.get(str(recipe_id), {}))


def crafting_output_kind(recipe_id: str) -> str:
    return str(crafting_recipe_def(recipe_id).get("output_kind", ""))


def crafting_recipe_ingredients(recipe_id: str) -> list[dict[str, object]]:
    recipe_def = crafting_recipe_def(recipe_id)
    return [dict(entry) for entry in recipe_def.get("ingredient_requirements", ())]


def crafting_recipe_required_tool_tags(recipe_id: str) -> tuple[str, ...]:
    recipe_def = crafting_recipe_def(recipe_id)
    return tuple(str(tag) for tag in recipe_def.get("required_tool_tags", ()))


def crafting_recipe_station_kind(recipe_id: str) -> str:
    recipe_def = crafting_recipe_def(recipe_id)
    return str(recipe_def.get("station_kind", ""))


def crafting_recipe_occupation_tags(recipe_id: str) -> tuple[str, ...]:
    recipe_def = crafting_recipe_def(recipe_id)
    return tuple(str(tag) for tag in recipe_def.get("occupation_tags", ()))


def crafting_recipes_for_occupation(occupation_kind: str) -> tuple[str, ...]:
    needle = str(occupation_kind or "").strip()
    if not needle:
        return ()
    matches: list[str] = []
    for recipe_id in CRAFTING_RECIPE_IDS:
        if needle in crafting_recipe_occupation_tags(recipe_id):
            matches.append(recipe_id)
    return tuple(matches)
