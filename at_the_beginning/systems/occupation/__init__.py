"""Occupation blueprints for ordinary resident life and schedule shaping."""

from .assign import assign_occupation
from .catalog import OCCUPATION_DEFS, OCCUPATION_NAMES
from .inheritance import derive_occupation_weights, sample_occupation_kind
from .ops import (
    ensure_resident_occupation,
    occupation_core_tools,
    occupation_prompt_payload,
    occupation_prompt_summary,
    occupation_routine_score_adjustment,
    occupation_schedule_block_preferences,
    occupation_upgrade_tools,
)
from .prompt_view import build_occupation_prompt_payload, summarize_occupation
from .resolver import (
    get_occupation,
    occupation_block_preferences,
    occupation_def,
    occupation_kind,
    occupation_optional_tools,
    occupation_preferred_place_tags,
    occupation_preferred_tool_tags,
    occupation_required_tools,
    occupation_routine_biases,
)
from .schema import OCCUPATION_SCHEMA_VERSION, build_occupation_record

__all__ = [
    "OCCUPATION_DEFS",
    "OCCUPATION_NAMES",
    "OCCUPATION_SCHEMA_VERSION",
    "assign_occupation",
    "build_occupation_prompt_payload",
    "build_occupation_record",
    "derive_occupation_weights",
    "ensure_resident_occupation",
    "get_occupation",
    "occupation_block_preferences",
    "occupation_core_tools",
    "occupation_def",
    "occupation_kind",
    "occupation_optional_tools",
    "occupation_preferred_place_tags",
    "occupation_preferred_tool_tags",
    "occupation_prompt_payload",
    "occupation_prompt_summary",
    "occupation_required_tools",
    "occupation_routine_biases",
    "occupation_routine_score_adjustment",
    "occupation_schedule_block_preferences",
    "occupation_upgrade_tools",
    "sample_occupation_kind",
    "summarize_occupation",
]
