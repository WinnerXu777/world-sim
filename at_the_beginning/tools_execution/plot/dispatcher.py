from __future__ import annotations

"""Dispatcher object for plot / resident reasoning execution."""

from typing import Any

from .executors import execute_plot_packet


class PlotExecutionDispatcher:
    def execute_packet(
        self,
        engine: Any,
        packet: dict[str, Any],
        *,
        reasoning_id: int | None = None,
        reason_text: str = "",
    ) -> dict[str, Any]:
        return execute_plot_packet(
            engine,
            packet,
            reasoning_id=reasoning_id,
            reason_text=reason_text,
        )
