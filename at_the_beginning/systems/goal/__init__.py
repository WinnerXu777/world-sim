"""Structured resident goals and review lifecycle helpers."""

from .catalog import GOAL_DEFS
from .generators import apply_event_goal_updates, initialize_starter_goals, run_periodic_goal_review
from .lifecycle import (
    ACTIVE_GOAL_LIMIT,
    clear_goal_review,
    ensure_goal_state,
    goal_review_due,
    mark_goal_review_needed,
    primary_goal,
    prune_goals,
    upsert_goal,
)
from .ops import (
    ensure_resident_goals,
    goal_prompt_payload,
    goal_prompt_summary,
    primary_goal_payload,
    refresh_goals_for_event,
    request_goal_review,
    review_resident_goals,
)
from .prompt_view import build_goal_prompt_payload, summarize_goals
from .review import maybe_review_goals
from .schema import GOAL_SCHEMA_VERSION, build_goal_record, goal_identity

__all__ = [
    "ACTIVE_GOAL_LIMIT",
    "GOAL_DEFS",
    "GOAL_SCHEMA_VERSION",
    "apply_event_goal_updates",
    "build_goal_prompt_payload",
    "build_goal_record",
    "clear_goal_review",
    "ensure_goal_state",
    "ensure_resident_goals",
    "goal_identity",
    "goal_prompt_payload",
    "goal_prompt_summary",
    "goal_review_due",
    "initialize_starter_goals",
    "mark_goal_review_needed",
    "maybe_review_goals",
    "primary_goal",
    "primary_goal_payload",
    "prune_goals",
    "refresh_goals_for_event",
    "request_goal_review",
    "review_resident_goals",
    "run_periodic_goal_review",
    "summarize_goals",
    "upsert_goal",
]
