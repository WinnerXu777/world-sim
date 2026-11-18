from __future__ import annotations

"""Schema helpers for decree-mode execution packets."""

from typing import Any


def normalize_decree_packet(packet: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(packet or {})
    return {
        "thought": str(payload.get("thought", "")),
        "map_actions": list(payload.get("map_actions") or []),
        "human_actions": list(payload.get("human_actions") or []),
        "new_entities": list(payload.get("new_entities") or []),
        "new_instincts": list(payload.get("new_instincts") or []),
    }


def decree_packet_errors(packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("map_actions", "human_actions", "new_entities", "new_instincts"):
        if not isinstance(packet.get(key), list):
            errors.append(f"invalid_packet_field:{key}")
    return errors
