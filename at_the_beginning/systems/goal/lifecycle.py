from __future__ import annotations

"""Goal persistence, review cadence, and deduplicated updates."""

import hashlib

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

from .schema import build_goal_record, goal_identity


ACTIVE_GOAL_LIMIT = 3
REVIEW_MIN_SECONDS = 15
REVIEW_MAX_SECONDS = 30


def _stable_seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _review_interval_ticks(resident: dict, tick: int) -> int:
    personality = resident.get("personality", {})
    traits = personality.get("traits", {})
    curiosity = float(traits.get("curiosity", 0.5))
    ambition = float(traits.get("ambition", 0.5))
    caution = float(traits.get("caution", 0.5))
    midpoint = (REVIEW_MIN_SECONDS + REVIEW_MAX_SECONDS) * 0.5
    base_seconds = midpoint - curiosity * 4.0 - ambition * 2.5 + caution * 3.0
    base_seconds = max(REVIEW_MIN_SECONDS, min(REVIEW_MAX_SECONDS, base_seconds))
    jitter = (_stable_seed(f"{resident.get('id', 'resident')}:{tick}:goal-review") % 81) - 40
    return max(1, int(round(base_seconds * float(cfg.TICK_RATE_HZ))) + jitter)


def ensure_goal_state(resident: dict, tick: int) -> dict:
    resident.setdefault("goals", [])
    state = resident.setdefault("goal_state", {})
    state.setdefault("schema_version", 1)
    state.setdefault("goal_counter", len(resident.get("goals", [])))
    state.setdefault("last_review_tick", int(tick))
    state.setdefault("last_review_source", "seed")
    state.setdefault("review_needed", False)
    state.setdefault("review_reason", "")
    state.setdefault("next_review_tick", int(tick) + _review_interval_ticks(resident, tick))
    return state


def next_goal_id(resident: dict) -> str:
    state = ensure_goal_state(resident, int(resident.get("snapshot", {}).get("tick", 0)))
    state["goal_counter"] = int(state.get("goal_counter", 0)) + 1
    return f"g_{int(state['goal_counter']):04d}"


def _goal_sort_key(goal: dict) -> tuple[float, int, int]:
    status_bonus = 1.0 if str(goal.get("status", "active")) == "active" else 0.0
    return (
        status_bonus,
        float(goal.get("priority", 0.0)),
        int(goal.get("last_review_tick", goal.get("created_tick", 0))),
    )


def prune_goals(resident: dict, tick: int, *, limit: int = ACTIVE_GOAL_LIMIT) -> list[dict]:
    ensure_goal_state(resident, tick)
    active = []
    for goal in list(resident.get("goals", [])):
        if goal.get("expires_tick") is not None and int(goal["expires_tick"]) < int(tick):
            continue
        if str(goal.get("status", "active")) not in {"active", "queued"}:
            continue
        if float(goal.get("priority", 0.0)) <= 0.05:
            continue
        active.append(goal)
    active.sort(key=_goal_sort_key, reverse=True)
    trimmed = active[: max(limit, 0)]
    trimmed.sort(key=lambda goal: (-float(goal.get("priority", 0.0)), int(goal.get("created_tick", 0))))
    resident["goals"] = trimmed
    return trimmed


def upsert_goal(resident: dict, goal: dict, tick: int) -> dict:
    ensure_goal_state(resident, tick)
    resident.setdefault("goals", [])
    identity = goal_identity(goal)
    existing = next((item for item in resident["goals"] if goal_identity(item) == identity), None)
    if existing is None:
        new_goal = build_goal_record(
            next_goal_id(resident),
            str(goal["kind"]),
            tick=tick,
            priority=float(goal.get("priority", 0.5)),
            target_id=goal.get("target_id"),
            target_place=goal.get("target_place"),
            horizon=goal.get("horizon"),
            status=str(goal.get("status", "active")),
            origin=str(goal.get("origin", "review")),
            plan_hint=str(goal.get("plan_hint", "")),
            confidence=float(goal.get("confidence", 0.5)),
            expires_tick=goal.get("expires_tick"),
            success_condition=str(goal.get("success_condition", "")),
            failure_condition=str(goal.get("failure_condition", "")),
            metadata=dict(goal.get("metadata", {})),
        )
        resident["goals"].append(new_goal)
        prune_goals(resident, tick)
        return new_goal

    existing["priority"] = round(max(float(existing.get("priority", 0.0)), float(goal.get("priority", 0.0))), 3)
    existing["last_review_tick"] = int(tick)
    existing["status"] = str(goal.get("status", existing.get("status", "active")))
    if goal.get("target_id") is not None:
        existing["target_id"] = goal.get("target_id")
    if goal.get("target_place"):
        existing["target_place"] = dict(goal["target_place"])
    if goal.get("plan_hint"):
        existing["plan_hint"] = str(goal["plan_hint"])
    if goal.get("origin"):
        existing["origin"] = str(goal["origin"])
    existing["confidence"] = round(max(float(existing.get("confidence", 0.0)), float(goal.get("confidence", 0.5))), 3)
    metadata = dict(existing.get("metadata", {}))
    metadata.update(dict(goal.get("metadata", {})))
    existing["metadata"] = metadata
    if goal.get("expires_tick") is not None:
        current_expiry = existing.get("expires_tick")
        goal_expiry = int(goal["expires_tick"])
        existing["expires_tick"] = max(int(current_expiry), goal_expiry) if current_expiry is not None else goal_expiry
    prune_goals(resident, tick)
    return existing


def mark_goal_review_needed(resident: dict, tick: int, reason: str) -> None:
    state = ensure_goal_state(resident, tick)
    state["review_needed"] = True
    state["review_reason"] = reason


def goal_review_due(resident: dict, tick: int) -> bool:
    state = ensure_goal_state(resident, tick)
    return bool(state.get("review_needed", False)) or int(state.get("next_review_tick", tick)) <= int(tick)


def clear_goal_review(resident: dict, tick: int, source: str) -> None:
    state = ensure_goal_state(resident, tick)
    state["review_needed"] = False
    state["review_reason"] = ""
    state["last_review_tick"] = int(tick)
    state["last_review_source"] = source
    state["next_review_tick"] = int(tick) + _review_interval_ticks(resident, tick)


def primary_goal(resident: dict) -> dict | None:
    goals = list(resident.get("goals", []))
    if not goals:
        return None
    goals.sort(key=_goal_sort_key, reverse=True)
    return goals[0]
