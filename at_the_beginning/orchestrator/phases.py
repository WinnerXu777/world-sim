from __future__ import annotations

from copy import deepcopy
from typing import Any

from .intake import packet_from_reasoning_output
from .schema import ORCHESTRATION_PHASES


def _orchestrator_cache(packet: dict[str, Any]) -> dict[str, Any]:
    return packet.setdefault("_orchestrator_cache", {})


def _resolve_packet_human_target(packet: dict[str, Any]) -> str:
    if str(packet.get("target_kind", "")).strip().lower() == "human":
        return str(packet.get("target_id", "")).strip()
    if str(packet.get("actor_kind", "")).strip().lower() == "human":
        return str(packet.get("actor_id", "")).strip()
    return ""


def _resolve_reasoning_resident_id(packet: dict[str, Any]) -> str:
    payload = dict(packet.get("payload") or {})
    for key in ("resident_id", "human_id"):
        value = str(payload.get(key, "")).strip()
        if value:
            return value
    target_human_id = _resolve_packet_human_target(packet)
    if target_human_id:
        return target_human_id
    if str(packet.get("actor_kind", "")).strip().lower() == "human":
        return str(packet.get("actor_id", "")).strip()
    return ""


def _resolve_reasoning_counterparty_id(packet: dict[str, Any], resident_id: str) -> str:
    payload = dict(packet.get("payload") or {})
    for key in ("counterparty_id", "other_human_id", "target_human_id"):
        value = str(payload.get(key, "")).strip()
        if value and value != resident_id:
            return value
    actor_id = str(packet.get("actor_id", "")).strip()
    if str(packet.get("actor_kind", "")).strip().lower() == "human" and actor_id and actor_id != resident_id:
        return actor_id
    target_id = str(packet.get("target_id", "")).strip()
    if str(packet.get("target_kind", "")).strip().lower() == "human" and target_id and target_id != resident_id:
        return target_id
    return ""


def _mock_reasoning_strategy(packet: dict[str, Any], resident_id: str, counterparty_id: str) -> str:
    payload = dict(packet.get("payload") or {})
    explicit = str(
        payload.get("mock_strategy")
        or payload.get("plan_kind_hint")
        or payload.get("mock_plan_kind")
        or ""
    ).strip().lower()
    if explicit:
        return explicit
    semantic_action = str(
        packet.get("semantic_action", "")
        or dict(packet.get("metadata", {})).get("source_semantic_action", "")
    ).strip().lower()
    if semantic_action == "reasoning_output":
        semantic_action = str(dict(packet.get("metadata", {})).get("source_semantic_action", "")).strip().lower()
    physical_intent = str(payload.get("physical_intent", "")).strip().lower()
    reason_text = str(payload.get("reason", "") or packet.get("metadata", {}).get("reason", "") or "").strip().lower()
    if semantic_action == "attack_target" and counterparty_id:
        return "retaliate"
    if semantic_action == "talk_command" and counterparty_id:
        if physical_intent in {"counterattack", "scan_and_prepare"}:
            return "retaliate"
        if "threat" in reason_text or bool(payload.get("danger_upgrade", False)):
            return "avoid_target"
        if physical_intent == "call_help":
            return "recruit_support"
    if "protect" in reason_text or "guard" in reason_text:
        return "guard_home"
    if semantic_action == "interact_target" and str(packet.get("target_kind", "")).strip().lower() == "entity":
        return "scout_region"
    return "scout_region"


def _build_mock_plot_packet(packet: dict[str, Any], engine: Any = None) -> dict[str, Any] | None:
    resident_id = _resolve_reasoning_resident_id(packet)
    if not resident_id:
        return None
    resident = None if engine is None else getattr(engine, "resident_store", None).get(resident_id)
    counterparty_id = _resolve_reasoning_counterparty_id(packet, resident_id)
    strategy = _mock_reasoning_strategy(packet, resident_id, counterparty_id)
    payload = dict(packet.get("payload") or {})
    reason_text = str(
        payload.get("reason")
        or dict(packet.get("metadata", {})).get("reason")
        or f"mock reasoning from {packet.get('semantic_action', packet.get('trigger_kind', 'event'))}"
    ).strip()
    plan_metadata = {
        "mock_reasoning": True,
        "source_packet_id": str(packet.get("packet_id", "")),
        "source_trigger_kind": str(packet.get("trigger_kind", "")),
        "source_semantic_action": str(packet.get("semantic_action", "")),
    }
    if counterparty_id:
        plan_metadata["counterparty_id"] = counterparty_id

    goal_updates: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    auto_plan = False

    if strategy in {"retaliate", "revenge"} and counterparty_id:
        goal_updates.append(
            {
                "kind": "retaliate",
                "priority": 0.92,
                "target_id": counterparty_id,
                "origin": "mock_reasoning",
                "plan_hint": "revenge",
                "confidence": 0.82,
                "metadata": dict(plan_metadata),
            }
        )
        plans.append(
            {
                "plan_kind": "revenge",
                "priority": 0.88,
                "origin": "mock_reasoning",
                "summary": "mock revenge response",
                "steps": [
                    {"op": "recover_until_hp", "threshold": 70.0},
                    {"op": "move_to_target", "target_id": counterparty_id},
                    {"op": "attack_target_when_close", "target_id": counterparty_id},
                ],
                "metadata": dict(plan_metadata),
            }
        )
    elif strategy in {"avoid_target", "escape_and_hide"} and counterparty_id:
        goal_updates.append(
            {
                "kind": "avoid_target",
                "priority": 0.84,
                "target_id": counterparty_id,
                "origin": "mock_reasoning",
                "plan_hint": "escape_and_hide",
                "confidence": 0.8,
                "metadata": dict(plan_metadata),
            }
        )
        plans.append(
            {
                "plan_kind": "escape_and_hide",
                "priority": 0.82,
                "origin": "mock_reasoning",
                "summary": "mock evasive response",
                "steps": [
                    {"op": "avoid_target", "target_id": counterparty_id},
                    {"op": "rest_until_safe"},
                    {"op": "return_home"},
                ],
                "metadata": dict(plan_metadata),
            }
        )
    elif strategy == "recruit_support":
        goal_updates.append(
            {
                "kind": "recruit_allies",
                "priority": 0.78,
                "target_id": counterparty_id or None,
                "origin": "mock_reasoning",
                "plan_hint": "recruit_support",
                "confidence": 0.76,
                "metadata": dict(plan_metadata),
            }
        )
        plans.append(
            {
                "plan_kind": "recruit_support",
                "priority": 0.76,
                "origin": "mock_reasoning",
                "summary": "mock recruit support response",
                "steps": [
                    {"op": "recruit_allies", "count": 1},
                    *([{"op": "move_to_target", "target_id": counterparty_id}] if counterparty_id else []),
                ],
                "metadata": dict(plan_metadata),
            }
        )
    elif strategy == "guard_home":
        goal_updates.append(
            {
                "kind": "guard_home",
                "priority": 0.74,
                "origin": "mock_reasoning",
                "plan_hint": "fortify_home",
                "confidence": 0.74,
                "metadata": dict(plan_metadata),
            }
        )
        plans.append(
            {
                "plan_kind": "fortify_home",
                "priority": 0.72,
                "origin": "mock_reasoning",
                "summary": "mock guard home response",
                "steps": [
                    {"op": "return_home"},
                    {"op": "guard_place", "place_hint": "home"},
                ],
                "metadata": dict(plan_metadata),
            }
        )
    else:
        goal_updates.append(
            {
                "kind": "explore_region",
                "priority": 0.52,
                "origin": "mock_reasoning",
                "plan_hint": "scout_region",
                "confidence": 0.62,
                "metadata": dict(plan_metadata),
            }
        )
        plans.append(
            {
                "plan_kind": "scout_region",
                "priority": 0.54,
                "origin": "mock_reasoning",
                "summary": "mock scout response",
                "steps": [
                    {"op": "move_to_place", "place_hint": "frontier"},
                    {"op": "observe_target", "target_id": counterparty_id or resident_id},
                ],
                "metadata": dict(plan_metadata),
            }
        )

    if resident is None:
        auto_plan = False

    return {
        "resident_id": resident_id,
        "reasoning_mode": "resident_reasoning",
        "reason": reason_text or "mock resident reasoning",
        "notes": f"Mock reasoning output for {resident_id}",
        "goal_review": {
            "requested": True,
            "reason": reason_text or "mock resident reasoning",
            "force": True,
        },
        "goal_updates": goal_updates,
        "plans": plans,
        "auto_plan": auto_plan,
    }


def _extract_reasoning_packet(packet: dict[str, Any], engine: Any = None) -> dict[str, Any] | None:
    payload = dict(packet.get("payload") or {})
    for key in ("reasoning_packet", "packet", "prebuilt_packet"):
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            return dict(candidate)
    if bool(payload.get("mock_output", False)) or bool(dict(packet.get("metadata", {})).get("mock_output", False)):
        return _build_mock_plot_packet(packet, engine=engine)
    if bool(getattr(engine, "mock_reasoning_enabled", False)):
        return _build_mock_plot_packet(packet, engine=engine)
    return None


def _probe_human_escalation(
    packet: dict[str, Any],
    engine: Any = None,
    *,
    force_immediate_urgent: bool,
) -> dict[str, Any] | None:
    if engine is None:
        return None
    human_agent = getattr(engine, "human_agent", None)
    if human_agent is None or not hasattr(human_agent, "ingest_external_trigger"):
        return None
    target_human_id = _resolve_packet_human_target(packet)
    if not target_human_id:
        return None
    cache = _orchestrator_cache(packet)
    if "escalation_probe" in cache:
        return cache["escalation_probe"]
    result = human_agent.ingest_external_trigger(
        engine,
        target_human_id,
        force_immediate_urgent=bool(force_immediate_urgent),
        force_process=bool(force_immediate_urgent),
        source_tag=f"orchestrator:{packet.get('semantic_action', '')}",
    )
    cache["escalation_probe"] = result
    return result


def run_normalize_phase(packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    packet["status"] = "normalized"
    packet["outputs"].setdefault("normalized", True)
    return packet


def run_immediate_effects_phase(packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    packet["outputs"].setdefault("immediate_effects", {})
    return packet


def run_reflex_handoff_phase(packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    if bool(packet.get("facts", {}).get("requires_reflex", False)):
        packet["outputs"]["reflex_handoff"] = {
            "requested": True,
            "target_human_id": _resolve_packet_human_target(packet),
        }
    return packet


def run_urgent_signal_phase(packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    if bool(packet.get("facts", {}).get("emit_urgent_ticket", False)):
        escalation = _probe_human_escalation(packet, engine=engine, force_immediate_urgent=True)
        packet["outputs"]["urgent_signal"] = {
            "requested": True,
            "target_human_id": _resolve_packet_human_target(packet),
            "result": deepcopy(escalation) if isinstance(escalation, dict) else None,
        }
    return packet


def run_consequence_signal_phase(packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    if bool(packet.get("facts", {}).get("emit_consequence_ticket", False)):
        escalation = _probe_human_escalation(packet, engine=engine, force_immediate_urgent=False)
        packet["outputs"]["consequence_signal"] = {
            "requested": True,
            "target_human_id": _resolve_packet_human_target(packet),
            "result": deepcopy(escalation) if isinstance(escalation, dict) else None,
        }
    return packet


def run_reasoning_ticket_phase(packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    if bool(packet.get("facts", {}).get("emit_reasoning_ticket", False)):
        consequence_result = dict((packet.get("outputs", {}).get("consequence_signal") or {}).get("result") or {})
        target_human_id = _resolve_packet_human_target(packet)
        packet["outputs"]["reasoning_ticket"] = {
            "requested": True,
            "actor_id": str(packet.get("actor_id", "")),
            "target_id": str(packet.get("target_id", "")),
            "semantic_action": str(packet.get("semantic_action", "")),
            "delegated": True,
            "delegated_to": "human_agent_deferred_escalation",
            "resident_id": target_human_id,
            "consequence_due_tick": consequence_result.get("consequence_due_tick"),
            "goal_review_requested": bool(consequence_result.get("goal_review_requested", False)),
        }
        if engine is not None and bool(getattr(engine, "mock_reasoning_enabled", False)) and target_human_id:
            orchestrator = getattr(engine, "orchestrator", None)
            if orchestrator is not None:
                mock_reasoning_packet = packet_from_reasoning_output(
                    packet_id=orchestrator.next_packet_id(),
                    tick=int(packet.get("tick", 0)),
                    actor_kind="human",
                    actor_id=target_human_id,
                    target_kind="human" if str(packet.get("actor_kind", "")).strip().lower() == "human" else "",
                    target_id=str(packet.get("actor_id", "")).strip()
                    if str(packet.get("actor_kind", "")).strip().lower() == "human" and str(packet.get("actor_id", "")).strip() != target_human_id
                    else "",
                    semantic_action=str(packet.get("semantic_action", "")).strip().lower() or "reasoning_output",
                    action_family="reasoning",
                    payload={
                        "resident_id": target_human_id,
                        "counterparty_id": _resolve_reasoning_counterparty_id(packet, target_human_id),
                        "reason": str(consequence_result.get("consequence_ticket_reason") or packet.get("semantic_action") or "mock_reasoning"),
                        "mock_output": True,
                    },
                    metadata={
                        "origin": "mock_reasoning_ticket",
                        "source_packet_id": str(packet.get("packet_id", "")),
                        "source_semantic_action": str(packet.get("semantic_action", "")).strip().lower(),
                        "consequence_source_key": str(consequence_result.get("consequence_ticket_source_key", "")),
                        "mock_output": True,
                    },
                )
                mock_result = orchestrator.run_packet(mock_reasoning_packet, engine=engine)
                packet["outputs"]["reasoning_output"] = {
                    "requested": True,
                    "mock": True,
                    "packet_id": str(mock_reasoning_packet.get("packet_id", "")),
                    "result": deepcopy(mock_result),
                }
    return packet


def run_task_materialization_phase(packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    if bool(packet.get("facts", {}).get("emit_task_materialization", False)):
        output = {"requested": True}
        reasoning_packet = _extract_reasoning_packet(packet, engine=engine)
        if reasoning_packet is not None:
            output["reasoning_packet"] = deepcopy(reasoning_packet)
            plot_execution = None if engine is None else getattr(engine, "plot_execution", None)
            if plot_execution is not None and hasattr(plot_execution, "execute_packet"):
                reason_text = str(
                    reasoning_packet.get("reason")
                    or dict(packet.get("payload", {})).get("reason")
                    or "mock resident reasoning"
                ).strip()
                reasoning_id = dict(packet.get("metadata", {})).get("reasoning_id")
                outcome = plot_execution.execute_packet(
                    engine,
                    reasoning_packet,
                    reasoning_id=reasoning_id,
                    reason_text=reason_text,
                )
                output["execution"] = deepcopy(outcome)
                if engine is not None and bool(outcome.get("ok")):
                    if int(outcome.get("goal_updates_applied", 0)) > 0 or int(outcome.get("plans_applied", 0)) > 0:
                        engine._force_frame_refresh = True
                    resident_id = str(reasoning_packet.get("resident_id", "")).strip()
                    source_key = str(dict(packet.get("metadata", {})).get("consequence_source_key", "")).strip()
                    human_agent = getattr(engine, "human_agent", None)
                    if resident_id and human_agent is not None and hasattr(human_agent, "acknowledge_reasoning_handoff"):
                        output["acknowledged"] = human_agent.acknowledge_reasoning_handoff(
                            resident_id,
                            source_key=source_key,
                        )
            else:
                output["execution"] = {"ok": False, "reason": "plot_execution_unavailable"}
        packet["outputs"]["task_materialization"] = output
    return packet


def run_finalize_phase(packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    packet["status"] = "completed"
    packet["outputs"].setdefault("finalized", True)
    return packet


DEFAULT_PHASE_HANDLERS = {
    "normalize": run_normalize_phase,
    "immediate_effects": run_immediate_effects_phase,
    "reflex_handoff": run_reflex_handoff_phase,
    "urgent_signal": run_urgent_signal_phase,
    "consequence_signal": run_consequence_signal_phase,
    "reasoning_ticket": run_reasoning_ticket_phase,
    "task_materialization": run_task_materialization_phase,
    "finalize": run_finalize_phase,
}


def apply_phase(packet: dict[str, Any], phase_name: str, engine: Any = None) -> dict[str, Any]:
    handler = DEFAULT_PHASE_HANDLERS.get(str(phase_name or "").strip().lower())
    phase_record = {
        "phase": str(phase_name or "").strip().lower(),
        "status": "skipped" if handler is None else "applied",
    }
    if handler is not None:
        packet = handler(packet, engine=engine)
    packet.setdefault("phase_history", []).append(deepcopy(phase_record))
    return packet


__all__ = [
    "DEFAULT_PHASE_HANDLERS",
    "ORCHESTRATION_PHASES",
    "apply_phase",
]
