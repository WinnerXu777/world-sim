from __future__ import annotations

"""Prompt-facing escalation summaries."""

from typing import Any

from .queue_state import EscalationDecision


def build_escalation_prompt_payload(decision: EscalationDecision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "lane": decision.lane,
        "priority": round(float(decision.priority), 3),
        "urgent_score": round(float(decision.urgent_score), 3),
        "urgent_reason": decision.urgent_reason,
        "normal_score": round(float(decision.normal_score), 3),
        "normal_reason": decision.normal_reason,
        "goal_review_score": round(float(decision.goal_review_score), 3),
        "goal_review_reason": decision.goal_review_reason,
        "goal_review_requested": bool(decision.goal_review_requested),
        "reaction_ticket_requested": bool(decision.reaction_ticket_requested),
        "reaction_ticket_reason": decision.reaction_ticket_reason,
        "consequence_ticket_requested": bool(decision.consequence_ticket_requested),
        "consequence_ticket_reason": decision.consequence_ticket_reason,
        "consequence_ticket_source_key": decision.consequence_ticket_source_key,
        "consequence_due_tick": None if decision.consequence_due_tick is None else int(decision.consequence_due_tick),
        "requires_reflex": bool(decision.requires_reflex),
        "tags": list(decision.route_tags),
    }


def summarize_escalation(decision: EscalationDecision | None) -> str:
    if decision is None:
        return "no escalation"
    pieces = [decision.lane, f"p={decision.priority:.2f}"]
    if decision.urgent_reason:
        pieces.append(f"u:{decision.urgent_reason}")
    if decision.goal_review_requested:
        pieces.append("goal_review")
    if decision.consequence_ticket_requested:
        pieces.append("deferred")
    return " | ".join(pieces)
