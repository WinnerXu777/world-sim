from __future__ import annotations

"""Prompt-friendly payloads and summaries for crafting recipes."""

from .resolver import (
    crafting_output_kind,
    crafting_recipe_def,
    crafting_recipe_ingredients,
    crafting_recipe_occupation_tags,
    crafting_recipe_required_tool_tags,
    crafting_recipe_station_kind,
)


def _ingredient_summary(ingredients: list[dict[str, object]]) -> str:
    if not ingredients:
        return "none"
    parts: list[str] = []
    for entry in ingredients:
        parts.append(f'{int(entry.get("quantity", 1))}x {entry.get("item_kind", "")}')
    return ", ".join(parts)


def summarize_crafting_recipe(recipe_id: str) -> str:
    recipe_def = crafting_recipe_def(recipe_id)
    if not recipe_def:
        return ""
    label = str(recipe_def.get("label", recipe_id))
    ingredients = _ingredient_summary(crafting_recipe_ingredients(recipe_id))
    tool_tags = crafting_recipe_required_tool_tags(recipe_id)
    station_kind = crafting_recipe_station_kind(recipe_id) or "none"
    tool_summary = ", ".join(tool_tags) if tool_tags else "none"
    return (
        f"{label}: {ingredients}; tools={tool_summary}; station={station_kind}"
    )


def build_crafting_recipe_prompt_payload(recipe_id: str) -> dict[str, object]:
    recipe_def = crafting_recipe_def(recipe_id)
    if not recipe_def:
        return {}
    return {
        "recipe_id": str(recipe_id),
        "label": str(recipe_def.get("label", recipe_id)),
        "output_kind": crafting_output_kind(recipe_id),
        "output_quantity": int(recipe_def.get("output_quantity", 1)),
        "ingredients": crafting_recipe_ingredients(recipe_id),
        "required_tool_tags": list(crafting_recipe_required_tool_tags(recipe_id)),
        "station_kind": crafting_recipe_station_kind(recipe_id),
        "occupation_tags": list(crafting_recipe_occupation_tags(recipe_id)),
        "difficulty": float(recipe_def.get("difficulty", 0.0)),
        "time_cost": float(recipe_def.get("time_cost", 1.0)),
        "notes": str(recipe_def.get("notes", "")),
        "summary": summarize_crafting_recipe(recipe_id),
    }


def build_crafting_state_prompt_payload(resident: dict) -> dict[str, object]:
    state = dict(resident.get("crafting_state", {}) or {})
    needs = [dict(item) for item in list(state.get("baseline_needs", []))[:4]]
    active_need = state.get("active_need")
    return {
        "baseline_ready": bool(state.get("baseline_ready", False)),
        "maturity_ready": bool(state.get("maturity_ready", False)),
        "survival_clear": bool(state.get("survival_clear", False)),
        "auto_allowed": bool(state.get("auto_allowed", False)),
        "required_tools": [str(item) for item in list(state.get("required_tools", [])) if str(item).strip()],
        "optional_tools": [str(item) for item in list(state.get("optional_tools", [])) if str(item).strip()],
        "material_cache": {
            str(item_kind): int(quantity)
            for item_kind, quantity in dict(state.get("material_cache", {})).items()
            if str(item_kind).strip() and int(quantity) > 0
        },
        "accessible_storage_count": int(state.get("accessible_storage_count", 0)),
        "active_need": dict(active_need) if isinstance(active_need, dict) else None,
        "baseline_needs": needs,
        "summary": str(state.get("summary", "")),
        "review_reason": str(state.get("review_reason", "")),
    }


def summarize_crafting_state(resident: dict) -> str:
    payload = build_crafting_state_prompt_payload(resident)
    summary = str(payload.get("summary", "")).strip()
    if summary:
        return summary
    if not bool(payload.get("baseline_ready", False)):
        return "baseline crafting not ready"
    return "crafting state unknown"
