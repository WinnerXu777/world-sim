from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schema import packet_summary


def next_packet_id(state: dict[str, Any]) -> str:
    current = int(state.get("next_packet_id", 1))
    state["next_packet_id"] = current + 1
    return f"orch_{current:06d}"


def normalize_packet(packet: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(packet or {})
    normalized.setdefault("packet_id", "")
    normalized.setdefault("tick", 0)
    normalized.setdefault("trigger_kind", "world_event")
    normalized.setdefault("actor_kind", "")
    normalized.setdefault("actor_id", "")
    normalized.setdefault("target_kind", "")
    normalized.setdefault("target_id", "")
    normalized.setdefault("semantic_action", "")
    normalized.setdefault("action_family", "")
    normalized.setdefault("world_refs", {})
    normalized.setdefault("facts", {})
    normalized.setdefault("payload", {})
    normalized.setdefault("metadata", {})
    normalized.setdefault("phase_history", [])
    normalized.setdefault("outputs", {})
    normalized.setdefault("status", "queued")
    return normalized


def packet_debug_summary(packet: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_packet(packet)
    return {
        "packet_id": str(normalized.get("packet_id", "")),
        "summary": packet_summary(normalized),
        "trigger_kind": str(normalized.get("trigger_kind", "")),
        "semantic_action": str(normalized.get("semantic_action", "")),
        "status": str(normalized.get("status", "")),
        "phase_count": len(normalized.get("phase_history", [])),
    }


__all__ = [
    "next_packet_id",
    "normalize_packet",
    "packet_debug_summary",
]
