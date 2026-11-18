from __future__ import annotations

from copy import deepcopy
from typing import Any

from .ops import next_packet_id, normalize_packet
from .phases import apply_phase
from .router import select_phase_order
from .schema import build_orchestration_result


class OrchestratorRuntime:
    def __init__(self):
        self.state: dict[str, Any] = {"next_packet_id": 1}
        self.queue: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []

    def next_packet_id(self) -> str:
        return next_packet_id(self.state)

    def enqueue(self, packet: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_packet(packet)
        self.queue.append(normalized)
        self.queue = self.queue[-64:]
        return {
            "ok": True,
            "packet_id": str(normalized.get("packet_id", "")),
            "pending": len(self.queue),
        }

    def run_packet(self, packet: dict[str, Any], engine: Any = None) -> dict[str, Any]:
        working = normalize_packet(packet)
        phase_order = select_phase_order(working)
        for phase_name in phase_order:
            working = apply_phase(working, phase_name, engine=engine)
        result = build_orchestration_result(packet=working, outputs=working.get("outputs", {}))
        self.history.append(
            {
                "packet_id": str(working.get("packet_id", "")),
                "tick": int(working.get("tick", 0)),
                "trigger_kind": str(working.get("trigger_kind", "")),
                "semantic_action": str(working.get("semantic_action", "")),
                "status": str(working.get("status", "")),
                "phase_history": deepcopy(working.get("phase_history", [])),
            }
        )
        self.history = self.history[-64:]
        return result

    def drain_queue(self, engine: Any = None, *, limit: int = 8) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        max_count = max(int(limit), 0)
        for packet in self.queue:
            if max_count > 0 and len(completed) < max_count:
                completed.append(self.run_packet(packet, engine=engine))
            else:
                remaining.append(packet)
        self.queue = remaining
        return completed

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "pending_packets": len(self.queue),
            "history": deepcopy(self.history[-12:]),
            "next_packet_id": int(self.state.get("next_packet_id", 1)),
        }


__all__ = ["OrchestratorRuntime"]
