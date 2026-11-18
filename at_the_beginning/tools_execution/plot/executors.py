from __future__ import annotations

"""Hardcoded resident reasoning / plot execution helpers."""

from typing import Any

try:
    from systems.goal import primary_goal, review_resident_goals, upsert_goal
    from systems.planning import (
        active_plan_payload,
        clear_reasoning_review,
        compile_plan,
        store_resident_plan,
        validate_plan,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.goal import primary_goal, review_resident_goals, upsert_goal
    from at_the_beginning.systems.planning import (
        active_plan_payload,
        clear_reasoning_review,
        compile_plan,
        store_resident_plan,
        validate_plan,
    )

from .schema import normalize_plot_packet, plot_packet_errors


def _default_plan_for_goal(resident: dict[str, Any], tick: int, reason: str) -> dict[str, Any] | None:
    goal = primary_goal(resident)
    if goal is None:
        return None
    kind = str(goal.get("kind", ""))
    target_id = goal.get("target_id")
    base = {
        "goal_id": goal.get("id"),
        "priority": float(goal.get("priority", 0.5)),
        "origin": "reasoning",
        "summary": f"auto plan for {kind}",
    }
    if kind == "retaliate":
        plan_kind = "revenge"
        steps = [
            {"op": "recover_until_hp", "threshold": 70.0},
            {"op": "move_to_target", "target_id": target_id},
            {"op": "attack_target_when_close", "target_id": target_id},
        ]
    elif kind == "avoid_target":
        plan_kind = "escape_and_hide"
        steps = [
            {"op": "avoid_target", "target_id": target_id},
            {"op": "rest_until_safe"},
            {"op": "return_home"},
        ]
    elif kind == "recruit_allies":
        plan_kind = "recruit_support"
        steps = [
            {"op": "recruit_allies", "count": 1},
            {"op": "move_to_target", "target_id": target_id},
        ]
    elif kind == "accumulate_wealth":
        plan_kind = "theft"
        steps = [
            {"op": "observe_target", "target_id": target_id or "wealth_opportunity"},
            {"op": "steal_from_target_when_safe", "target_id": target_id or "wealth_opportunity"},
        ]
    elif kind == "guard_home":
        plan_kind = "fortify_home"
        steps = [
            {"op": "return_home"},
            {"op": "guard_place", "place_hint": "home"},
        ]
    else:
        plan_kind = "scout_region"
        steps = [
            {"op": "move_to_place", "place_hint": "frontier"},
            {"op": "observe_target", "target_id": target_id or "region_interest"},
        ]
    return {
        **base,
        "plan_kind": plan_kind,
        "steps": steps,
        "metadata": {"reason": reason, "goal_kind": kind},
    }


def execute_plot_packet(
    engine: Any,
    packet: dict[str, Any],
    *,
    reasoning_id: int | None = None,
    reason_text: str = "",
) -> dict[str, Any]:
    normalized = normalize_plot_packet(packet)
    errors = plot_packet_errors(normalized)
    if errors:
        return {
            "ok": False,
            "errors": [{"reason": error} for error in errors],
            "goal_updates_applied": 0,
            "plans_applied": 0,
            "resident_id": normalized.get("resident_id"),
        }

    resident_id = normalized["resident_id"]
    resident = engine.resident_store.get(resident_id)
    if resident is None:
        return {
            "ok": False,
            "errors": [{"reason": "resident_not_found", "resident_id": resident_id}],
            "goal_updates_applied": 0,
            "plans_applied": 0,
            "resident_id": resident_id,
        }

    goal_updates_applied = 0
    plans_applied = 0
    plan_errors: list[dict[str, Any]] = []
    review_info = dict(normalized.get("goal_review") or {})
    review_reason = str(review_info.get("reason") or normalized.get("reason") or reason_text or "reasoning")
    if bool(review_info.get("requested", False)):
        review_resident_goals(
            resident,
            int(engine.tick),
            reason=review_reason,
            force=bool(review_info.get("force", False)),
        )

    for goal in list(normalized.get("goal_updates", [])):
        upsert_goal(resident, dict(goal), int(engine.tick))
        goal_updates_applied += 1

    plans = list(normalized.get("plans", []))
    if not plans and bool(normalized.get("auto_plan", False)):
        default_plan = _default_plan_for_goal(resident, int(engine.tick), review_reason)
        if default_plan is not None:
            plans.append(default_plan)

    for plan in plans:
        validation_errors = validate_plan(dict(plan))
        if validation_errors:
            plan_errors.append(
                {
                    "reason": "invalid_plan",
                    "plan_kind": plan.get("plan_kind"),
                    "errors": validation_errors,
                }
            )
            continue
        compiled = compile_plan(dict(plan))
        if not compiled.get("ok", False):
            plan_errors.append(
                {
                    "reason": "compile_failed",
                    "plan_kind": plan.get("plan_kind"),
                    "errors": compiled.get("errors", []),
                }
            )
            continue
        stored = store_resident_plan(resident, dict(plan), int(engine.tick))
        stored_metadata = dict(stored.get("metadata", {}))
        stored_metadata["compiled_steps"] = list(compiled.get("compiled_steps", []))
        stored_metadata["reasoning_id"] = reasoning_id
        stored["metadata"] = stored_metadata
        plans_applied += 1

    clear_reasoning_review(resident, int(engine.tick), review_reason or "reasoning")
    engine.resident_store.touch_resident(resident_id)
    active_plan = active_plan_payload(resident)
    return {
        "ok": len(plan_errors) == 0,
        "resident_id": resident_id,
        "goal_updates_applied": goal_updates_applied,
        "plans_applied": plans_applied,
        "active_plan": None if active_plan is None else {
            "id": active_plan.get("id"),
            "plan_kind": active_plan.get("plan_kind"),
            "priority": active_plan.get("priority"),
        },
        "errors": plan_errors,
        "frame_dirty": False,
        "map_dirty": False,
    }
