from __future__ import annotations

"""Plan lifecycle and resident planning state."""

import hashlib

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

from .schema import build_plan_record, plan_identity


ACTIVE_PLAN_LIMIT = 3
REASONING_REVIEW_MIN_SECONDS = 20
REASONING_REVIEW_MAX_SECONDS = 45


def _stable_seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _reasoning_interval_ticks(resident: dict, tick: int) -> int:
    personality = resident.get("personality", {})
    traits = personality.get("traits", {})
    curiosity = float(traits.get("curiosity", 0.5))
    ambition = float(traits.get("ambition", 0.5))
    caution = float(traits.get("caution", 0.5))
    base_seconds = 32.0 - curiosity * 5.0 - ambition * 3.0 + caution * 4.0
    base_seconds = max(REASONING_REVIEW_MIN_SECONDS, min(REASONING_REVIEW_MAX_SECONDS, base_seconds))
    jitter = (_stable_seed(f"{resident.get('id', 'resident')}:{tick}:plan-review") % 101) - 50
    return max(1, int(round(base_seconds * float(cfg.TICK_RATE_HZ))) + jitter)


def ensure_planning_state(resident: dict, tick: int) -> dict:
    resident.setdefault("plans", [])
    state = resident.setdefault("planning_state", {})
    state.setdefault("schema_version", 1)
    state.setdefault("plan_counter", len(resident.get("plans", [])))
    state.setdefault("review_needed", False)
    state.setdefault("review_reason", "")
    state.setdefault("last_review_tick", int(tick))
    state.setdefault("last_review_source", "seed")
    state.setdefault("next_review_tick", int(tick) + _reasoning_interval_ticks(resident, tick))
    return state


def next_plan_id(resident: dict) -> str:
    tick = int(resident.get("snapshot", {}).get("tick", 0))
    state = ensure_planning_state(resident, tick)
    state["plan_counter"] = int(state.get("plan_counter", 0)) + 1
    return f"p_{int(state['plan_counter']):04d}"


def _plan_sort_key(plan: dict) -> tuple[float, int, int]:
    status_bonus = 1.0 if str(plan.get("status", "queued")) in {"active", "queued"} else 0.0
    return (
        status_bonus,
        float(plan.get("priority", 0.0)),
        int(plan.get("last_review_tick", plan.get("created_tick", 0))),
    )


def prune_plans(resident: dict, tick: int, *, limit: int = ACTIVE_PLAN_LIMIT) -> list[dict]:
    ensure_planning_state(resident, tick)
    active = []
    for plan in list(resident.get("plans", [])):
        if plan.get("expires_tick") is not None and int(plan["expires_tick"]) < int(tick):
            continue
        if str(plan.get("status", "queued")) not in {"queued", "active"}:
            continue
        if float(plan.get("priority", 0.0)) <= 0.05:
            continue
        active.append(plan)
    active.sort(key=_plan_sort_key, reverse=True)
    trimmed = active[: max(limit, 0)]
    trimmed.sort(key=lambda plan: (-float(plan.get("priority", 0.0)), int(plan.get("created_tick", 0))))
    resident["plans"] = trimmed
    return trimmed


def upsert_plan(resident: dict, plan: dict, tick: int) -> dict:
    ensure_planning_state(resident, tick)
    resident.setdefault("plans", [])
    identity = plan_identity(plan)
    existing = next((item for item in resident["plans"] if plan_identity(item) == identity), None)
    if existing is None:
        created = build_plan_record(
            next_plan_id(resident),
            str(plan.get("plan_kind", "")),
            tick=tick,
            goal_id=plan.get("goal_id"),
            priority=float(plan.get("priority", 0.5)),
            confidence=plan.get("confidence"),
            status=str(plan.get("status", "queued")),
            origin=str(plan.get("origin", "reasoning")),
            steps=list(plan.get("steps", [])),
            expires_tick=plan.get("expires_tick"),
            summary=str(plan.get("summary", "")),
            metadata=dict(plan.get("metadata", {})),
        )
        resident["plans"].append(created)
        prune_plans(resident, tick)
        return created

    existing["priority"] = round(max(float(existing.get("priority", 0.0)), float(plan.get("priority", 0.0))), 3)
    existing["confidence"] = round(max(float(existing.get("confidence", 0.0)), float(plan.get("confidence", 0.0))), 3)
    existing["last_review_tick"] = int(tick)
    existing["last_update_tick"] = int(tick)
    existing["status"] = str(plan.get("status", existing.get("status", "queued")))
    if plan.get("summary"):
        existing["summary"] = str(plan["summary"])
    if plan.get("steps"):
        existing["steps"] = [dict(step) for step in list(plan["steps"])]
        existing["current_step_index"] = min(
            int(existing.get("current_step_index", 0)),
            max(len(existing["steps"]) - 1, 0),
        )
    metadata = dict(existing.get("metadata", {}))
    metadata.update(dict(plan.get("metadata", {})))
    existing["metadata"] = metadata
    if plan.get("expires_tick") is not None:
        existing["expires_tick"] = int(plan["expires_tick"])
    prune_plans(resident, tick)
    return existing


def mark_reasoning_review_needed(resident: dict, tick: int, reason: str) -> None:
    state = ensure_planning_state(resident, tick)
    state["review_needed"] = True
    state["review_reason"] = str(reason)


def reasoning_review_due(resident: dict, tick: int) -> bool:
    state = ensure_planning_state(resident, tick)
    return bool(state.get("review_needed", False)) or int(state.get("next_review_tick", tick)) <= int(tick)


def clear_reasoning_review(resident: dict, tick: int, source: str) -> None:
    state = ensure_planning_state(resident, tick)
    state["review_needed"] = False
    state["review_reason"] = ""
    state["last_review_tick"] = int(tick)
    state["last_review_source"] = str(source)
    state["next_review_tick"] = int(tick) + _reasoning_interval_ticks(resident, tick)


def active_plan(resident: dict) -> dict | None:
    plans = list(resident.get("plans", []))
    if not plans:
        return None
    plans.sort(key=_plan_sort_key, reverse=True)
    return plans[0]
