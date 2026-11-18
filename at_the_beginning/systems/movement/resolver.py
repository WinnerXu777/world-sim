from __future__ import annotations

import math


def clamp_world_position(x: float, y: float, map_width: float, map_height: float) -> tuple[float, float]:
    """Clamp a world-space position to the playable bounds."""
    return (max(0.0, min(float(x), float(map_width))), max(0.0, min(float(y), float(map_height))))


def resolve_target_step(
    current_x: float,
    current_y: float,
    target_x: float,
    target_y: float,
    max_step: float,
) -> tuple[float, float]:
    """Return a bounded delta that moves toward a target point."""
    delta_x = float(target_x) - float(current_x)
    delta_y = float(target_y) - float(current_y)
    dist = math.hypot(delta_x, delta_y)
    if dist <= 1e-6:
        return (0.0, 0.0)
    scaled_step = min(float(max_step), dist)
    return ((delta_x / dist) * scaled_step, (delta_y / dist) * scaled_step)

