from __future__ import annotations

"""Stable planning ops for resident-side integration."""

from .compiler import compile_plan, compile_plan_bundle
from .executor import compile_active_plan, execute_compiled_plan_step, tick_resident_plans
from .lifecycle import (
    active_plan,
    clear_reasoning_review,
    ensure_planning_state,
    mark_reasoning_review_needed,
    prune_plans,
    reasoning_review_due,
    upsert_plan,
)
from .prompt_view import build_plan_catalog_payload, build_plan_prompt_payload, summarize_plans
from .validator import plan_is_valid, validate_plan


def ensure_resident_plans(resident: dict, tick: int) -> list[dict]:
    ensure_planning_state(resident, tick)
    return prune_plans(resident, tick)


def queue_reasoning_review(resident: dict, tick: int, reason: str) -> None:
    mark_reasoning_review_needed(resident, tick, reason)


def store_resident_plan(resident: dict, plan: dict, tick: int) -> dict:
    ensure_planning_state(resident, tick)
    return upsert_plan(resident, plan, tick)


def active_plan_payload(resident: dict) -> dict | None:
    return active_plan(resident)


def plan_prompt_payload(resident: dict, *, limit: int = 2) -> list[dict]:
    return build_plan_prompt_payload(resident, limit=limit)


def plan_prompt_summary(resident: dict, *, limit: int = 2) -> str:
    return summarize_plans(resident, limit=limit)


def plan_catalog_payload() -> dict[str, list[dict[str, object]]]:
    return build_plan_catalog_payload()


__all__ = [
    "active_plan_payload",
    "clear_reasoning_review",
    "compile_active_plan",
    "compile_plan",
    "compile_plan_bundle",
    "ensure_resident_plans",
    "execute_compiled_plan_step",
    "plan_catalog_payload",
    "plan_is_valid",
    "plan_prompt_payload",
    "plan_prompt_summary",
    "prune_plans",
    "queue_reasoning_review",
    "reasoning_review_due",
    "store_resident_plan",
    "tick_resident_plans",
    "validate_plan",
]
