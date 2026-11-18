from __future__ import annotations

"""Stable goal ops for resident-side integration."""

from .generators import apply_event_goal_updates, initialize_starter_goals
from .lifecycle import ensure_goal_state, mark_goal_review_needed, primary_goal
from .prompt_view import build_goal_prompt_payload, summarize_goals
from .review import maybe_review_goals


def ensure_resident_goals(resident: dict, tick: int) -> list[dict]:
    ensure_goal_state(resident, tick)
    return initialize_starter_goals(resident, tick)


def refresh_goals_for_event(
    resident: dict,
    tick: int,
    event_kind: str,
    event_payload: dict | None = None,
    *,
    force_review: bool = False,
) -> list[dict]:
    updated = apply_event_goal_updates(resident, tick, event_kind, event_payload)
    if force_review:
        return maybe_review_goals(resident, tick, reason=f"event:{event_kind}", force=True)
    return updated


def request_goal_review(resident: dict, tick: int, reason: str) -> None:
    mark_goal_review_needed(resident, tick, reason)


def review_resident_goals(
    resident: dict,
    tick: int,
    *,
    reason: str = "periodic",
    force: bool = False,
) -> list[dict]:
    return maybe_review_goals(resident, tick, reason=reason, force=force)


def primary_goal_payload(resident: dict) -> dict | None:
    return primary_goal(resident)


def goal_prompt_payload(resident: dict, *, limit: int = 3) -> list[dict]:
    return build_goal_prompt_payload(resident, limit=limit)


def goal_prompt_summary(resident: dict, *, limit: int = 2) -> str:
    return summarize_goals(resident, limit=limit)
