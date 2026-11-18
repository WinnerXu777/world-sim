"""Crafting recipes for tools, components, and future player or resident work."""

from .catalog import CRAFTING_RECIPE_DEFS, CRAFTING_RECIPE_IDS
from .lifecycle import (
    BASELINE_PROVISION_REVIEW_TICKS,
    CRAFTING_STATE_SCHEMA_VERSION,
    baseline_provisioning_due,
    ensure_crafting_state,
    sync_baseline_provisioning,
)
from .ops import (
    build_crafting_job,
    crafting_prompt_payload,
    crafting_prompt_summary,
    crafting_missing_ingredients,
    crafting_occupation_recipe_ids,
    crafting_recipe_prompt_payload,
    crafting_recipe_prompt_summary,
    ensure_resident_crafting_state,
    recipe_can_be_satisfied,
    review_resident_baseline_provisioning,
)
from .prompt_view import (
    build_crafting_recipe_prompt_payload,
    build_crafting_state_prompt_payload,
    summarize_crafting_state,
    summarize_crafting_recipe,
)
from .resolver import (
    crafting_output_kind,
    crafting_recipe_def,
    crafting_recipe_ids,
    crafting_recipe_ingredients,
    crafting_recipe_occupation_tags,
    crafting_recipe_required_tool_tags,
    crafting_recipe_station_kind,
    crafting_recipes_for_occupation,
)
from .schema import CRAFTING_SCHEMA_VERSION, build_crafting_job_record
from .stations import CRAFTING_STATION_DEFS, crafting_station_def

__all__ = [
    "CRAFTING_RECIPE_DEFS",
    "CRAFTING_RECIPE_IDS",
    "CRAFTING_SCHEMA_VERSION",
    "CRAFTING_STATION_DEFS",
    "CRAFTING_STATE_SCHEMA_VERSION",
    "BASELINE_PROVISION_REVIEW_TICKS",
    "baseline_provisioning_due",
    "build_crafting_job",
    "build_crafting_job_record",
    "build_crafting_recipe_prompt_payload",
    "build_crafting_state_prompt_payload",
    "crafting_prompt_payload",
    "crafting_prompt_summary",
    "crafting_missing_ingredients",
    "crafting_occupation_recipe_ids",
    "crafting_output_kind",
    "crafting_recipe_def",
    "crafting_recipe_ids",
    "crafting_recipe_ingredients",
    "crafting_recipe_occupation_tags",
    "crafting_recipe_prompt_payload",
    "crafting_recipe_prompt_summary",
    "crafting_recipe_required_tool_tags",
    "crafting_recipe_station_kind",
    "crafting_recipes_for_occupation",
    "crafting_station_def",
    "ensure_crafting_state",
    "ensure_resident_crafting_state",
    "recipe_can_be_satisfied",
    "review_resident_baseline_provisioning",
    "summarize_crafting_state",
    "summarize_crafting_recipe",
    "sync_baseline_provisioning",
]
