"""Reusable cross-module orchestration pipeline."""

from .intake import (
    packet_from_manual_action,
    packet_from_reasoning_output,
    packet_from_task_outcome,
    packet_from_world_event,
)
from .ops import (
    next_packet_id,
    normalize_packet,
    packet_debug_summary,
)
from .router import select_phase_order
from .runtime import OrchestratorRuntime
from .schema import (
    DEFAULT_PHASE_ORDER,
    ORCHESTRATION_PHASES,
    ORCHESTRATION_TRIGGER_KINDS,
    build_orchestration_packet,
    build_orchestration_result,
)

__all__ = [
    "DEFAULT_PHASE_ORDER",
    "ORCHESTRATION_PHASES",
    "ORCHESTRATION_TRIGGER_KINDS",
    "OrchestratorRuntime",
    "build_orchestration_packet",
    "build_orchestration_result",
    "next_packet_id",
    "normalize_packet",
    "packet_debug_summary",
    "packet_from_manual_action",
    "packet_from_reasoning_output",
    "packet_from_task_outcome",
    "packet_from_world_event",
    "select_phase_order",
]
