"""SpaceFrame: window-local float32 positions over an int64 chunk origin (1008 D0 finding G-D0-2, decision 3).

Tensors keep positions as float32 *relative to a window origin* that is an integer chunk coordinate, so the stored numbers
stay within a few thousand units no matter how far the player has travelled. Absolute positions exist only as a pair
``(chunk_x, chunk_y, x, y)`` (integer chunk, float64 offset inside that chunk) at the persistence and wire boundaries.

Nothing here converts live engine tensors yet; it is the interface and the arithmetic, unit-tested on synthetic data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

DEFAULT_CHUNK_UNITS = 256.0   # plan D2: 32 tiles x 8 units


@dataclass(frozen=True, order=True)
class AbsPos:
    """Absolute position: integer chunk coordinates plus a float64 offset in ``[0, chunk_units)`` inside the chunk."""
    chunk_x: int
    chunk_y: int
    x: float
    y: float

    def chunk(self) -> tuple[int, int]:
        return (self.chunk_x, self.chunk_y)


class SpaceFrame:
    """Maps window-local coordinates to absolute ``AbsPos`` and back.

    ``origin`` is the integer chunk whose lower-left corner is local ``(0, 0)``. ``space`` is the space id (0 = overworld;
    interiors get their own ids under decision D-001). ``bounds`` is the finite local rectangle ``(x0, y0, x1, y1)`` of a
    finite world (the legacy 1200 x 900 frame) or ``None`` for an unbounded one.
    """

    def __init__(self, chunk_units: float = DEFAULT_CHUNK_UNITS, origin: tuple[int, int] = (0, 0), space: int = 0,
                 bounds: Optional[tuple[float, float, float, float]] = None):
        if not (chunk_units > 0 and math.isfinite(chunk_units)):
            raise ValueError("chunk_units must be a finite number > 0")
        self.chunk_units = float(chunk_units)
        self.origin = (int(origin[0]), int(origin[1]))
        self.space = int(space)
        self.bounds = None if bounds is None else tuple(float(v) for v in bounds)
        if self.bounds is not None and not (self.bounds[0] < self.bounds[2] and self.bounds[1] < self.bounds[3]):
            raise ValueError("bounds must be (x0, y0, x1, y1) with x0 < x1 and y0 < y1")

    # conversions -------------------------------------------------------------
    def to_absolute(self, x: float, y: float) -> AbsPos:
        """Local window coordinates -> absolute. Exact in float64 for any float32 input."""
        size = self.chunk_units
        cx, cy = math.floor(x / size), math.floor(y / size)
        return AbsPos(self.origin[0] + cx, self.origin[1] + cy, float(x) - cx * size, float(y) - cy * size)

    def to_local(self, pos: AbsPos) -> tuple[float, float]:
        """Absolute -> local window coordinates (float64; the caller rounds to float32 when storing)."""
        size = self.chunk_units
        return ((pos.chunk_x - self.origin[0]) * size + pos.x, (pos.chunk_y - self.origin[1]) * size + pos.y)

    def chunk_of(self, x: float, y: float) -> tuple[int, int]:
        """Absolute chunk coordinate containing the local point."""
        return (self.origin[0] + math.floor(x / self.chunk_units), self.origin[1] + math.floor(y / self.chunk_units))

    def chunk_rect(self, chunk: tuple[int, int]) -> tuple[float, float, float, float]:
        """Local rectangle ``(x0, y0, x1, y1)`` of an absolute chunk."""
        x0, y0 = (chunk[0] - self.origin[0]) * self.chunk_units, (chunk[1] - self.origin[1]) * self.chunk_units
        return (x0, y0, x0 + self.chunk_units, y0 + self.chunk_units)

    # rebasing ----------------------------------------------------------------
    def rebase_shift(self, new_origin: tuple[int, int]) -> tuple[float, float]:
        """Local-coordinate shift to add to stored positions when the window origin moves to ``new_origin``."""
        return ((self.origin[0] - int(new_origin[0])) * self.chunk_units, (self.origin[1] - int(new_origin[1])) * self.chunk_units)

    def rebase(self, new_origin: tuple[int, int], *position_arrays) -> tuple[float, float]:
        """Move the origin and shift each position tensor/array (last axis = x, y) in place.

        Returns the shift applied. Shifts are whole multiples of ``chunk_units`` so the only error is float32 rounding at the
        new (small) magnitude. Bounds are shifted with the origin.
        """
        shift = self.rebase_shift(new_origin)
        for array in position_arrays:
            array[..., 0] += shift[0]
            array[..., 1] += shift[1]
        if self.bounds is not None:
            b = self.bounds
            self.bounds = (b[0] + shift[0], b[1] + shift[1], b[2] + shift[0], b[3] + shift[1])
        self.origin = (int(new_origin[0]), int(new_origin[1]))
        return shift

    # bounds ------------------------------------------------------------------
    def clamp(self, x: float, y: float) -> tuple[float, float]:
        """Clamp to the finite bounds; the identity for an unbounded frame."""
        if self.bounds is None:
            return (x, y)
        return (min(max(x, self.bounds[0]), self.bounds[2]), min(max(y, self.bounds[1]), self.bounds[3]))

    def centre(self) -> Optional[tuple[float, float]]:
        """Centre of the finite bounds, or ``None`` for an unbounded frame."""
        if self.bounds is None:
            return None
        return ((self.bounds[0] + self.bounds[2]) / 2.0, (self.bounds[1] + self.bounds[3]) / 2.0)

    def __repr__(self) -> str:
        return f"SpaceFrame(space={self.space}, origin={self.origin}, chunk_units={self.chunk_units}, bounds={self.bounds})"
