from __future__ import annotations

from copy import deepcopy
from typing import Any


ORCHESTRATION_TRIGGER_KINDS: set[str] = {
    "manual_action",
    "spontaneous_interaction",
    "world_event",
    "task_outcome",
    "reasoning_output",
}

ORCHESTRATION_PHASES: tuple[str, ...] = (
    "normalize",
    "immediate_effects",
    "reflex_handoff",
    "urgent_signal",
    "consequence_signal",
    "reasoning_ticket",
    "task_materialization",
    "finalize",
)

DEFAULT_PHASE_ORDER: tuple[str, ...] = ORCHESTRATION_PHASES


def normalize_trigger_kind(trigger_kind: str | None, *, fallback: str = "world_event") -> str:
    normalized = str(trigger_kind or fallback).strip().lower()
    if normalized in ORCHESTRATION_TRIGGER_KINDS:
        return normalized
    return fallback


def build_orchestration_packet(
    *,
    packet_id: str,
    tick: int,
    trigger_kind: str,
    actor_kind: str = "",
    actor_id: str = "",
    target_kind: str = "",
    target_id: str = "",
    semantic_action: str = "",
    action_family: str = "",
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    facts: dict[str, Any] | None = None,
    world_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet_facts = {
        "immediate_effect_applied": False,
        "requires_reflex": False,
        "emit_urgent_ticket": False,
        "emit_consequence_ticket": False,
        "emit_reasoning_ticket": False,
        "emit_task_materialization": False,
    }
    packet_facts.update(dict(facts or {}))
    return {
        "packet_id": str(packet_id),
        "tick": int(tick),
        "trigger_kind": normalize_trigger_kind(trigger_kind),
        "actor_kind": str(actor_kind or "").strip().lower(),
        "actor_id": str(actor_id or "").strip(),
        "target_kind": str(target_kind or "").strip().lower(),
        "target_id": str(target_id or "").strip(),
        "semantic_action": str(semantic_action or "").strip().lower(),
        "action_family": str(action_family or "").strip().lower(),
        "world_refs": deepcopy(world_refs or {}),
        "facts": packet_facts,
        "payload": deepcopy(payload or {}),
        "metadata": deepcopy(metadata or {}),
        "phase_history": [],
        "outputs": {},
        "status": "queued",
    }


def build_orchestration_result(
    *,
    packet: dict[str, Any],
    completed: bool = True,
    outputs: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": bool(completed and not errors),
        "packet_id": str(packet.get("packet_id", "")),
        "trigger_kind": str(packet.get("trigger_kind", "")),
        "semantic_action": str(packet.get("semantic_action", "")),
        "outputs": deepcopy(outputs or packet.get("outputs", {})),
        "errors": [str(item) for item in list(errors or []) if str(item).strip()],
        "phase_history": [dict(item) for item in list(packet.get("phase_history", []))],
    }


def packet_summary(packet: dict[str, Any]) -> str:
    trigger_kind = str(packet.get("trigger_kind", "")).strip()
    semantic_action = str(packet.get("semantic_action", "")).strip()
    actor_id = str(packet.get("actor_id", "")).strip()
    target_id = str(packet.get("target_id", "")).strip()
    parts = [part for part in (trigger_kind, semantic_action, actor_id, target_id) if part]
    return " / ".join(parts) if parts else "orchestration_packet"


__all__ = [
    "DEFAULT_PHASE_ORDER",
    "ORCHESTRATION_PHASES",
    "ORCHESTRATION_TRIGGER_KINDS",
    "build_orchestration_packet",
    "build_orchestration_result",
    "normalize_trigger_kind",
    "packet_summary",
]
