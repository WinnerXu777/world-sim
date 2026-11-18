from __future__ import annotations

"""Data containers for escalation routing."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EscalationCandidate:
    slot: int
    human_id: str
    resident: dict[str, Any]
    escalated_flag: bool
    pending_since_tick: int
    last_decision_tick: int
    signals: dict[str, Any]


@dataclass
class EscalationDecision:
    slot: int
    human_id: str
    lane: str
    priority: float
    should_consider: bool
    urgent_score: float
    urgent_reason: str
    normal_score: float
    normal_reason: str
    goal_review_score: float
    goal_review_reason: str
    goal_review_requested: bool
    reaction_ticket_requested: bool
    reaction_ticket_reason: str
    consequence_ticket_requested: bool
    consequence_ticket_reason: str
    consequence_ticket_source_key: str
    consequence_due_tick: int | None
    requires_reflex: bool
    route_tags: list[str] = field(default_factory=list)
