from __future__ import annotations

"""Stable escalation ops used by the human runtime."""

from typing import Any

from .prompt_view import build_escalation_prompt_payload, summarize_escalation
from .queue_state import EscalationCandidate, EscalationDecision
from .routing import build_escalation_decision, select_processing_batch
from .signals import build_escalation_signals, distress_proxy_from_row


def build_candidate(
    engine: Any,
    slot: int,
    human_id: str,
    resident: dict[str, Any],
    *,
    escalated_flag: bool,
    pending_since_tick: int,
    last_decision_tick: int,
) -> EscalationCandidate:
    signals = build_escalation_signals(
        engine,
        slot,
        human_id,
        resident,
        escalated_flag=escalated_flag,
    )
    return EscalationCandidate(
        slot=slot,
        human_id=human_id,
        resident=resident,
        escalated_flag=bool(escalated_flag),
        pending_since_tick=int(pending_since_tick),
        last_decision_tick=int(last_decision_tick),
        signals=signals,
    )


__all__ = [
    "EscalationCandidate",
    "EscalationDecision",
    "build_candidate",
    "build_escalation_decision",
    "build_escalation_prompt_payload",
    "build_escalation_signals",
    "distress_proxy_from_row",
    "select_processing_batch",
    "summarize_escalation",
]
