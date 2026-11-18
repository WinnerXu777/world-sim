"""1008 window: where a position may be. The legacy engine clamps every moving thing into ``0..MAP_WIDTH x 0..MAP_HEIGHT`` (1200 x 900). Under
``EDEN_WINDOW=1`` that rectangle is wrong twice over: the world has no edge, and window-local coordinates are negative on the far side of the
origin (and a re-base shifts residents left outside the window by whole chunks). So with the flag on the legacy clamp sites read ``world_limits()``
and get no limit at all; the wall boxes, the void boxes and the space masks are the real boundaries. Flag off it is exactly the legacy rectangle.

Light on purpose (no torch, no engine): the clamp sites import it from files that load before the harness does.
"""
from __future__ import annotations

import math
import os

WINDOW_FLAG = "EDEN_WINDOW"
UNBOUNDED = (-math.inf, -math.inf, math.inf, math.inf)


def world_limits() -> tuple:
    """``(x0, y0, x1, y1)``: the legacy map rectangle, or no limit under EDEN_WINDOW=1 (read at call time)."""
    if os.environ.get(WINDOW_FLAG, "") == "1":
        return UNBOUNDED
    try:
        import genesis_config as cfg
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import genesis_config as cfg
    return (0.0, 0.0, float(cfg.MAP_WIDTH), float(cfg.MAP_HEIGHT))
