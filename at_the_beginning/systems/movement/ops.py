from __future__ import annotations

"""
Stable, generation-friendly movement ops.

These wrappers keep target stepping, navigation bias, and manual-control
movement on one predictable import surface for future generated tools.
"""

from typing import Any

import torch

try:
    from systems.movement.manual import apply_manual_control_movement, build_manual_control_context
    from systems.movement.resolver import clamp_world_position, resolve_target_step
    from systems.movement.sim import apply_navigation_bias
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.movement.manual import apply_manual_control_movement, build_manual_control_context
    from at_the_beginning.systems.movement.resolver import clamp_world_position, resolve_target_step
    from at_the_beginning.systems.movement.sim import apply_navigation_bias


def build_manual_context(
    h_tensor: torch.Tensor,
    *,
    player_control_runtime: Any = None,
    engine: Any = None,
) -> dict[str, Any]:
    return build_manual_control_context(
        h_tensor,
        player_control_runtime=player_control_runtime,
        engine=engine,
    )


def apply_controlled_movement(
    noise: torch.Tensor,
    h_tensor: torch.Tensor,
    h_indices: torch.Tensor,
    *,
    manual_control: dict[str, Any] | None,
    move_step: float,
    sprint_multiplier: float = 1.5,
    m_tensor: torch.Tensor | None = None,
) -> torch.Tensor:
    return apply_manual_control_movement(
        noise,
        h_tensor,
        h_indices,
        manual_control,
        move_step,
        sprint_multiplier=sprint_multiplier,
        m_tensor=m_tensor,
    )


def apply_navigation_biases(
    noise: torch.Tensor,
    h_indices: torch.Tensor,
    *,
    nav_survival: torch.Tensor | None = None,
    nav_social: torch.Tensor | None = None,
) -> torch.Tensor:
    return apply_navigation_bias(
        noise,
        h_indices,
        nav_survival=nav_survival,
        nav_social=nav_social,
    )


def step_toward_point(
    current_x: float,
    current_y: float,
    *,
    target_x: float,
    target_y: float,
    max_step: float,
) -> tuple[float, float]:
    return resolve_target_step(
        current_x,
        current_y,
        target_x,
        target_y,
        max_step,
    )


def clamp_position(x: float, y: float, *, map_width: float, map_height: float) -> tuple[float, float]:
    return clamp_world_position(x, y, map_width, map_height)


__all__ = [
    "apply_controlled_movement",
    "apply_navigation_biases",
    "build_manual_context",
    "clamp_position",
    "step_toward_point",
]
