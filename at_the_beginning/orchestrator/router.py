from __future__ import annotations

from .schema import DEFAULT_PHASE_ORDER


def select_phase_order(packet: dict) -> list[str]:
    facts = dict(packet.get("facts", {}))
    phases: list[str] = ["normalize", "immediate_effects"]

    if bool(facts.get("requires_reflex", False)):
        phases.append("reflex_handoff")
    if bool(facts.get("emit_urgent_ticket", False)):
        phases.append("urgent_signal")
    if bool(facts.get("emit_consequence_ticket", False)):
        phases.append("consequence_signal")
    if bool(facts.get("emit_reasoning_ticket", False)):
        phases.append("reasoning_ticket")
    if bool(facts.get("emit_task_materialization", False)):
        phases.append("task_materialization")

    phases.append("finalize")
    ordered = [phase for phase in DEFAULT_PHASE_ORDER if phase in phases]
    return ordered or list(DEFAULT_PHASE_ORDER)


__all__ = ["select_phase_order"]
