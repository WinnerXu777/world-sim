from __future__ import annotations

"""Score escalation candidates into urgent, normal, and review lanes."""

from typing import Any

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

try:
    from systems.goal import goal_review_due
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.goal import goal_review_due


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _top_reason(values: dict[str, float]) -> tuple[float, str]:
    if not values:
        return 0.0, ""
    reason, score = max(values.items(), key=lambda item: item[1])
    return round(float(score), 3), reason


def _consequence_delay_ticks(signals: dict[str, Any], manual_interaction: dict[str, Any]) -> int:
    action = str(
        manual_interaction.get("semantic_action")
        or manual_interaction.get("action")
        or ""
    ).strip().lower()
    delay_seconds = {
        "attack": 6.0,
        "attack_target": 6.0,
        "interact": 4.0,
        "interact_target": 4.0,
        "talk": 4.5,
        "talk_command": 4.5,
        "select": 8.0,
        "select_target": 8.0,
    }.get(action, 5.0)
    recent_attack = float(signals.get("recent_attack_signal", 0.0))
    if recent_attack >= 0.75 and action in {"attack", "attack_target"}:
        delay_seconds = max(3.0, delay_seconds - 2.0)
    return max(1, int(round(delay_seconds * float(cfg.TICK_RATE_HZ))))


def score_escalation(signals: dict[str, Any]) -> dict[str, Any]:
    tick = int(signals["tick"])
    pressures = dict(signals.get("pressures", {}))
    goal_state = dict(signals.get("goal_state", {}))
    primary_goal = dict(signals.get("primary_goal", {}))
    manual_interaction = dict(signals.get("manual_interaction") or {})
    manual_reaction_score = float(manual_interaction.get("reaction_score", 0.0))
    manual_consequence_score = float(manual_interaction.get("consequence_score", 0.0))

    distress_norm = _clamp01(float(signals.get("distress_proxy", 0.0)) / 2.5)
    predator_close = 0.0
    if int(signals.get("predator_eid", -1)) != -1:
        predator_close = _clamp01(
            1.0 - (float(signals.get("predator_dist", float("inf"))) / float(max(cfg.PREDATOR_ALERT_RADIUS, 1.0)))
        )
    hazard_close = 0.0
    if int(signals.get("hazard_eid", -1)) != -1:
        hazard_close = _clamp01(
            1.0 - (float(signals.get("hazard_dist", float("inf"))) / float(max(cfg.HAZARD_AVOID_RADIUS, 1.0)))
        )

    urgent_factors = {
        "critical_health": _clamp01(float(signals.get("critical_health", 0.0))),
        "hp_crisis": _clamp01((25.0 - float(signals.get("hp", 100.0))) / 25.0),
        "panic_threat": _clamp01((float(signals.get("threat", 0.0)) - 75.0) / 25.0),
        "starvation": max(
            _clamp01((float(signals.get("hunger", 0.0)) - 96.0) / 4.0),
            _clamp01((float(signals.get("thirst", 0.0)) - 96.0) / 4.0),
        ),
        "predator_close": predator_close,
        "hazard_close": hazard_close,
        "recent_attack": float(signals.get("recent_attack_signal", 0.0)) * 0.9,
        "manual_reaction": manual_reaction_score,
    }
    urgent_score, urgent_reason = _top_reason(urgent_factors)

    normal_factors = {
        "legacy_escalation": 0.62 if bool(signals.get("escalated_flag", False)) else 0.0,
        "distress": distress_norm,
        "security_pressure": float(pressures.get("security_pressure", 0.0)),
        "resource_pressure": float(pressures.get("resource_pressure", 0.0)),
        "loyalty_pressure": float(pressures.get("loyalty_pressure", 0.0)) * 0.9,
        "status_pressure": float(pressures.get("status_pressure", 0.0)) * 0.85,
        "curiosity_pressure": float(pressures.get("curiosity_pressure", 0.0)) * 0.8,
        "vengeance_pressure": float(pressures.get("vengeance_pressure", 0.0)) * 0.9,
        "greed_pressure": float(pressures.get("greed_pressure", 0.0)) * 0.85,
        "recent_world": float(signals.get("recent_world_signal", 0.0)) * 0.7,
    }
    normal_score, normal_reason = _top_reason(normal_factors)

    review_due = goal_review_due(
        {
            "goals": [primary_goal] if primary_goal else [],
            "goal_state": goal_state,
            "personality": {},
        },
        tick,
    )
    goal_factors = {
        "review_needed": 1.0 if bool(goal_state.get("review_needed", False)) else 0.0,
        "periodic_review_due": 0.82 if review_due else 0.0,
        "goal_gap": 0.72 if int(signals.get("goal_count", 0)) <= 0 else 0.0,
        "goal_pressure_mismatch": 0.68
        if (
            primary_goal.get("kind") not in {"retaliate", "avoid_target"}
            and float(pressures.get("vengeance_pressure", 0.0)) >= 0.72
        )
        else 0.0,
    }
    goal_review_score, goal_review_reason = _top_reason(goal_factors)
    goal_review_requested = goal_review_score >= 0.78

    consequence_factors = {
        "manual_consequence": manual_consequence_score,
        "goal_review": goal_review_score if goal_review_requested else 0.0,
    }
    consequence_score, consequence_reason = _top_reason(consequence_factors)
    consequence_ticket_requested = consequence_score >= 0.24
    consequence_due_tick: int | None = None
    if consequence_ticket_requested:
        if manual_consequence_score > 0.0:
            consequence_due_tick = tick + _consequence_delay_ticks(signals, manual_interaction)
        else:
            consequence_due_tick = tick

    reaction_ticket_requested = urgent_score >= 0.72 or manual_reaction_score >= 0.28
    reaction_ticket_reason = str(
        manual_interaction.get("reaction_reason")
        if manual_reaction_score >= max(urgent_score - 0.05, 0.28)
        else urgent_reason
    )

    should_consider = bool(
        bool(signals.get("escalated_flag", False))
        or urgent_score >= 0.7
        or normal_score >= 0.72
        or consequence_ticket_requested
    )

    return {
        "urgent_score": urgent_score,
        "urgent_reason": urgent_reason,
        "normal_score": normal_score,
        "normal_reason": normal_reason,
        "goal_review_score": goal_review_score,
        "goal_review_reason": goal_review_reason,
        "goal_review_requested": goal_review_requested,
        "reaction_ticket_requested": reaction_ticket_requested,
        "reaction_ticket_reason": reaction_ticket_reason,
        "consequence_ticket_requested": consequence_ticket_requested,
        "consequence_ticket_reason": consequence_reason,
        "consequence_ticket_source_key": str(manual_interaction.get("source_key", "")),
        "consequence_due_tick": consequence_due_tick,
        "requires_reflex": urgent_score >= 0.75,
        "should_consider": should_consider,
    }
