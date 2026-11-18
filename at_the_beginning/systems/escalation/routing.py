from __future__ import annotations

"""Route escalation candidates into urgent and normal lanes."""

from typing import Any

from .queue_state import EscalationCandidate, EscalationDecision
from .scoring import score_escalation


def build_escalation_decision(candidate: EscalationCandidate, *, tick: int, urgent_cooldown_ticks: int) -> EscalationDecision:
    scores = score_escalation(candidate.signals)
    route_tags: list[str] = []
    lane = "skip"
    priority = 0.0

    if not scores["should_consider"]:
        return EscalationDecision(
            slot=candidate.slot,
            human_id=candidate.human_id,
            lane=lane,
            priority=priority,
            should_consider=False,
            urgent_score=float(scores["urgent_score"]),
            urgent_reason=str(scores["urgent_reason"]),
            normal_score=float(scores["normal_score"]),
            normal_reason=str(scores["normal_reason"]),
            goal_review_score=float(scores["goal_review_score"]),
            goal_review_reason=str(scores["goal_review_reason"]),
            goal_review_requested=bool(scores["goal_review_requested"]),
            reaction_ticket_requested=bool(scores["reaction_ticket_requested"]),
            reaction_ticket_reason=str(scores["reaction_ticket_reason"]),
            consequence_ticket_requested=bool(scores["consequence_ticket_requested"]),
            consequence_ticket_reason=str(scores["consequence_ticket_reason"]),
            consequence_ticket_source_key=str(scores["consequence_ticket_source_key"]),
            consequence_due_tick=scores["consequence_due_tick"],
            requires_reflex=bool(scores["requires_reflex"]),
            route_tags=route_tags,
        )

    if bool(candidate.escalated_flag):
        route_tags.append("legacy_flag")
    if bool(scores["reaction_ticket_requested"]):
        route_tags.append("reaction_ticket")
    if bool(scores["consequence_ticket_requested"]):
        route_tags.append("consequence_ticket")
    if bool(scores["goal_review_requested"]):
        route_tags.append("goal_review")
    if str(scores.get("reaction_ticket_reason", "")).startswith("manual_") or str(scores.get("consequence_ticket_reason", "")).startswith("manual_"):
        route_tags.append("manual")

    cooldown_ready = (int(tick) - int(candidate.last_decision_tick)) >= int(urgent_cooldown_ticks)
    if bool(scores["reaction_ticket_requested"]) and float(scores["urgent_score"]) >= 0.75 and cooldown_ready:
        lane = "urgent"
        priority = float(scores["urgent_score"])
        route_tags.append("urgent")
    elif float(scores["normal_score"]) >= 0.72 or bool(candidate.escalated_flag):
        lane = "normal_candidate"
        age_bonus = min(0.18, max(0, int(tick) - int(candidate.pending_since_tick)) / 600.0)
        priority = float(scores["normal_score"]) + age_bonus
        route_tags.append("normal")
    elif bool(scores["consequence_ticket_requested"]):
        lane = "defer"
        priority = float(scores["goal_review_score"])
        route_tags.append("deferred")

    return EscalationDecision(
        slot=candidate.slot,
        human_id=candidate.human_id,
        lane=lane,
        priority=round(priority, 3),
        should_consider=True,
        urgent_score=float(scores["urgent_score"]),
        urgent_reason=str(scores["urgent_reason"]),
        normal_score=float(scores["normal_score"]),
        normal_reason=str(scores["normal_reason"]),
        goal_review_score=float(scores["goal_review_score"]),
        goal_review_reason=str(scores["goal_review_reason"]),
        goal_review_requested=bool(scores["goal_review_requested"]),
        reaction_ticket_requested=bool(scores["reaction_ticket_requested"]),
        reaction_ticket_reason=str(scores["reaction_ticket_reason"]),
        consequence_ticket_requested=bool(scores["consequence_ticket_requested"]),
        consequence_ticket_reason=str(scores["consequence_ticket_reason"]),
        consequence_ticket_source_key=str(scores["consequence_ticket_source_key"]),
        consequence_due_tick=scores["consequence_due_tick"],
        requires_reflex=bool(scores["requires_reflex"]),
        route_tags=route_tags,
    )


def select_processing_batch(
    candidates: list[EscalationCandidate],
    *,
    tick: int,
    batch_interval_ticks: int,
    max_batch_size: int,
    last_batch_tick: int,
    urgent_cooldown_ticks: int,
) -> dict[str, Any]:
    decisions = [
        build_escalation_decision(candidate, tick=tick, urgent_cooldown_ticks=urgent_cooldown_ticks)
        for candidate in candidates
    ]
    decision_by_human = {decision.human_id: decision for decision in decisions}
    urgent = [decision for decision in decisions if decision.lane == "urgent"]
    normals = [decision for decision in decisions if decision.lane == "normal_candidate"]

    scheduled_normals: list[EscalationDecision] = []
    batch_tick = last_batch_tick
    if normals and (int(tick) - int(last_batch_tick)) >= int(batch_interval_ticks):
        normals.sort(key=lambda decision: (-decision.priority, decision.human_id))
        scheduled_normals = normals[: max(max_batch_size, 0)]
        batch_tick = int(tick)

    process: list[EscalationDecision] = []
    seen_humans: set[str] = set()
    for decision in [*urgent, *scheduled_normals]:
        if decision.human_id in seen_humans:
            continue
        seen_humans.add(decision.human_id)
        process.append(decision)
    return {
        "decisions": decisions,
        "decision_by_human": decision_by_human,
        "urgent": urgent,
        "scheduled_normals": scheduled_normals,
        "process": process,
        "batch_tick": batch_tick,
    }
