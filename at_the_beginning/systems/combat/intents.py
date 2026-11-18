from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CombatIntent:
    """Shared combat intent shape for autonomous and manual sources."""

    source: str
    action: str
    attacker_kind: str
    attacker_slot: int
    target_kind: str
    target_slot: int
    target_id: str | None = None
    world_x: float | None = None
    world_y: float | None = None

