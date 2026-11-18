from __future__ import annotations

from typing import Any

from .schema import build_orchestration_packet


def _base_facts_from_semantic_action(semantic_action: str) -> dict[str, Any]:
    normalized = str(semantic_action or "").strip().lower()
    if normalized == "attack_target":
        return {
            "requires_reflex": True,
            "emit_urgent_ticket": True,
            "emit_consequence_ticket": True,
            "emit_reasoning_ticket": True,
        }
    if normalized == "talk_command":
        return {
            "emit_consequence_ticket": True,
            "emit_reasoning_ticket": True,
        }
    if normalized in {"interact_target", "work_on_target"}:
        return {
            "emit_consequence_ticket": True,
        }
    return {}


def _merged_semantic_facts(semantic_action: str, facts: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _base_facts_from_semantic_action(semantic_action)
    merged.update(dict(facts or {}))
    return merged


def packet_from_manual_action(
    *,
    packet_id: str,
    tick: int,
    actor_kind: str,
    actor_id: str,
    semantic_action: str,
    action_family: str = "",
    target_kind: str = "",
    target_id: str = "",
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_orchestration_packet(
        packet_id=packet_id,
        tick=tick,
        trigger_kind="manual_action",
        actor_kind=actor_kind,
        actor_id=actor_id,
        target_kind=target_kind,
        target_id=target_id,
        semantic_action=semantic_action,
        action_family=action_family,
        payload=payload,
        metadata=metadata,
        facts=_merged_semantic_facts(semantic_action, facts),
    )


def packet_from_world_event(
    *,
    packet_id: str,
    tick: int,
    event_kind: str,
    actor_kind: str = "",
    actor_id: str = "",
    target_kind: str = "",
    target_id: str = "",
    semantic_action: str = "",
    action_family: str = "",
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_payload = dict(payload or {})
    merged_payload["event_kind"] = str(event_kind or "").strip().lower()
    return build_orchestration_packet(
        packet_id=packet_id,
        tick=tick,
        trigger_kind="world_event",
        actor_kind=actor_kind,
        actor_id=actor_id,
        target_kind=target_kind,
        target_id=target_id,
        semantic_action=semantic_action,
        action_family=action_family,
        payload=merged_payload,
        metadata=metadata,
        facts=_merged_semantic_facts(semantic_action, facts),
    )


def packet_from_task_outcome(
    *,
    packet_id: str,
    tick: int,
    actor_kind: str,
    actor_id: str,
    task_kind: str,
    semantic_action: str = "",
    action_family: str = "",
    target_kind: str = "",
    target_id: str = "",
    outcome: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(outcome or {})
    payload["task_kind"] = str(task_kind or "").strip().lower()
    return build_orchestration_packet(
        packet_id=packet_id,
        tick=tick,
        trigger_kind="task_outcome",
        actor_kind=actor_kind,
        actor_id=actor_id,
        target_kind=target_kind,
        target_id=target_id,
        semantic_action=semantic_action,
        action_family=action_family,
        payload=payload,
        metadata=metadata,
        facts=_merged_semantic_facts(semantic_action, facts),
    )


def packet_from_reasoning_output(
    *,
    packet_id: str,
    tick: int,
    actor_kind: str,
    actor_id: str,
    target_kind: str = "",
    target_id: str = "",
    semantic_action: str = "",
    action_family: str = "",
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_orchestration_packet(
        packet_id=packet_id,
        tick=tick,
        trigger_kind="reasoning_output",
        actor_kind=actor_kind,
        actor_id=actor_id,
        target_kind=target_kind,
        target_id=target_id,
        semantic_action=semantic_action,
        action_family=action_family,
        payload=payload,
        metadata=metadata,
        facts={"emit_task_materialization": True, **dict(facts or {})},
    )


__all__ = [
    "packet_from_manual_action",
    "packet_from_reasoning_output",
    "packet_from_task_outcome",
    "packet_from_world_event",
]
