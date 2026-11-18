from __future__ import annotations

"""Goal review entry points."""

from .generators import run_periodic_goal_review
from .lifecycle import goal_review_due


def maybe_review_goals(
    resident: dict,
    tick: int,
    *,
    reason: str = "periodic",
    force: bool = False,
) -> list[dict]:
    if force or goal_review_due(resident, tick):
        return run_periodic_goal_review(resident, tick, reason=reason)
    return list(resident.get("goals", []))
