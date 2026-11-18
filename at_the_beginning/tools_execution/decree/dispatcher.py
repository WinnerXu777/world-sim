from __future__ import annotations

"""Dispatcher object for decree-mode execution."""

from typing import Any

from .executors import execute_decree_packet


class DecreeExecutionDispatcher:
    def __init__(self, execution_agent: Any):
        self.execution_agent = execution_agent

    def execute_packet(
        self,
        engine: Any,
        packet: dict[str, Any],
        *,
        decree_id: int | None = None,
        decree_text: str = "",
    ) -> dict[str, Any]:
        return execute_decree_packet(
            engine,
            self.execution_agent,
            packet,
            decree_id=decree_id,
            decree_text=decree_text,
        )
