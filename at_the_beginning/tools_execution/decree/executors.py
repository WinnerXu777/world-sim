from __future__ import annotations

"""Hardcoded decree execution bridge."""

from typing import Any

from .schema import decree_packet_errors, normalize_decree_packet


def execute_decree_packet(
    engine: Any,
    execution_agent: Any,
    packet: dict[str, Any],
    *,
    decree_id: int | None = None,
    decree_text: str = "",
) -> dict[str, Any]:
    normalized = normalize_decree_packet(packet)
    errors = decree_packet_errors(normalized)
    if errors:
        return {
            "ok": False,
            "frame_dirty": False,
            "map_dirty": False,
            "results": [],
            "errors": [{"reason": error} for error in errors],
            "warnings": [],
        }
    return execution_agent.execute_packet(
        engine,
        normalized,
        decree_id=decree_id,
        decree_text=decree_text,
    )
