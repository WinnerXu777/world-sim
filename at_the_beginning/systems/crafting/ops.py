from __future__ import annotations

"""Stable integration helpers for recipe prompts and requirement checks."""

from collections import defaultdict
from itertools import count
from typing import Iterable

from .lifecycle import ensure_crafting_state, sync_baseline_provisioning
from .prompt_view import (
    build_crafting_recipe_prompt_payload,
    build_crafting_state_prompt_payload,
    summarize_crafting_recipe,
    summarize_crafting_state,
)
from .resolver import crafting_recipe_ingredients, crafting_recipes_for_occupation
from .schema import build_crafting_job_record


_JOB_COUNTER = count(1)


def build_crafting_job(
    recipe_id: str,
    *,
    owner_id: str,
    owner_kind: str = "resident",
    source: str = "manual",
    requested_quantity: int = 1,
    priority: float = 0.5,
    metadata: dict | None = None,
) -> dict:
    job_id = f"craft_{next(_JOB_COUNTER):06d}"
    return build_crafting_job_record(
        recipe_id,
        job_id=job_id,
        owner_id=owner_id,
        owner_kind=owner_kind,
        requested_quantity=requested_quantity,
        priority=priority,
        source=source,
        metadata=metadata,
    )


def crafting_recipe_prompt_payload(recipe_id: str) -> dict[str, object]:
    return build_crafting_recipe_prompt_payload(recipe_id)


def crafting_recipe_prompt_summary(recipe_id: str) -> str:
    return summarize_crafting_recipe(recipe_id)


def crafting_occupation_recipe_ids(occupation_kind: str) -> tuple[str, ...]:
    return crafting_recipes_for_occupation(occupation_kind)


def ensure_resident_crafting_state(resident: dict, tick: int) -> dict:
    return ensure_crafting_state(resident, tick)


def review_resident_baseline_provisioning(
    resident: dict,
    tick: int,
    *,
    personal_inventory: dict | None = None,
    accessible_inventories: Iterable[dict] | None = None,
    allow_auto: bool = True,
    force: bool = False,
) -> bool:
    return sync_baseline_provisioning(
        resident,
        tick,
        personal_inventory=personal_inventory,
        accessible_inventories=accessible_inventories,
        allow_auto=allow_auto,
        force=force,
        build_job=build_crafting_job,
        missing_ingredients_fn=crafting_missing_ingredients,
    )


def crafting_prompt_payload(resident: dict) -> dict[str, object]:
    return build_crafting_state_prompt_payload(resident)


def crafting_prompt_summary(resident: dict) -> str:
    return summarize_crafting_state(resident)


def _counts_from_stacks(item_stacks: Iterable[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for stack in item_stacks:
        item_kind = str(stack.get("kind", "")).strip()
        if not item_kind:
            continue
        counts[item_kind] += max(int(stack.get("quantity", 0)), 0)
    return dict(counts)


def crafting_missing_ingredients(
    recipe_id: str,
    available_item_stacks: Iterable[dict],
) -> list[dict[str, object]]:
    counts = _counts_from_stacks(available_item_stacks)
    missing: list[dict[str, object]] = []
    for entry in crafting_recipe_ingredients(recipe_id):
        item_kind = str(entry.get("item_kind", "")).strip()
        quantity = max(int(entry.get("quantity", 1)), 1)
        have = max(int(counts.get(item_kind, 0)), 0)
        if have >= quantity:
            continue
        missing.append(
            {
                "item_kind": item_kind,
                "required_quantity": quantity,
                "available_quantity": have,
                "missing_quantity": quantity - have,
            }
        )
    return missing


def recipe_can_be_satisfied(recipe_id: str, available_item_stacks: Iterable[dict]) -> bool:
    return not crafting_missing_ingredients(recipe_id, available_item_stacks)


__all__ = [
    "build_crafting_job",
    "crafting_missing_ingredients",
    "crafting_occupation_recipe_ids",
    "crafting_prompt_payload",
    "crafting_prompt_summary",
    "crafting_recipe_prompt_payload",
    "crafting_recipe_prompt_summary",
    "ensure_resident_crafting_state",
    "recipe_can_be_satisfied",
    "review_resident_baseline_provisioning",
]
