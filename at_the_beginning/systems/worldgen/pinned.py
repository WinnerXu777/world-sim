"""Pinned (authored) areas: tile rectangles that generation never touches and blends into.

D3 of the plan: `starter_village` (48 x 36 tiles at the world origin) is pinned; it always loads from its map file. The generator
only needs to know which tiles are inside and how far every other tile is from the nearest pinned tile.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np

from .spec import CHUNK_TILES

DEFAULT_BLEND_TILES = 8


@dataclass(frozen=True)
class PinnedArea:
    """Tile rectangle `[x0, x0 + w) x [y0, y0 + h)` in world tile coordinates, owned by an authored map file."""

    id: str
    x0: int
    y0: int
    w: int
    h: int

    def contains_rect(self, tx0: int, ty0: int, tw: int, th: int) -> bool:
        return self.x0 <= tx0 and self.y0 <= ty0 and tx0 + tw <= self.x0 + self.w and ty0 + th <= self.y0 + self.h


class PinnedSet:
    """A fixed collection of pinned areas plus the blend width. Immutable; `fingerprint` is part of every cache key."""

    def __init__(self, areas: Iterable[PinnedArea] = (), blend: int = DEFAULT_BLEND_TILES):
        self.areas = tuple(sorted(areas, key=lambda a: (a.id, a.x0, a.y0, a.w, a.h)))
        self.blend = int(blend)
        if self.blend < 1:
            raise ValueError("blend must be >= 1")
        payload = json.dumps([[a.id, a.x0, a.y0, a.w, a.h] for a in self.areas] + [self.blend], separators=(",", ":"))
        self.fingerprint = hashlib.sha256(payload.encode("ascii")).hexdigest()[:16] if self.areas else ""

    def __bool__(self) -> bool:
        return bool(self.areas)

    def distance(self, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
        """Chebyshev tile distance to the nearest pinned tile; 0 inside a pinned area. int32, same shape as the inputs."""
        best = np.full(gx.shape, 1 << 30, dtype=np.int64)
        for a in self.areas:
            dx = np.maximum(np.maximum(a.x0 - gx, gx - (a.x0 + a.w - 1)), 0)
            dy = np.maximum(np.maximum(a.y0 - gy, gy - (a.y0 + a.h - 1)), 0)
            best = np.minimum(best, np.maximum(dx, dy))
        return best.astype(np.int32)

    def fully_pinned_by(self, cx: int, cy: int) -> Optional[PinnedArea]:
        for a in self.areas:
            if a.contains_rect(cx * CHUNK_TILES, cy * CHUNK_TILES, CHUNK_TILES, CHUNK_TILES):
                return a
        return None

    def min_distance_rect(self, tx0: int, ty0: int, tw: int, th: int) -> int:
        """Smallest tile distance from a rectangle to any pinned area (0 if they overlap)."""
        best = 1 << 30
        for a in self.areas:
            dx = max(a.x0 - (tx0 + tw - 1), tx0 - (a.x0 + a.w - 1), 0)
            dy = max(a.y0 - (ty0 + th - 1), ty0 - (a.y0 + a.h - 1), 0)
            best = min(best, max(dx, dy))
        return best


NO_PINS = PinnedSet(())


def as_pinned(value) -> PinnedSet:
    if value is None:
        return NO_PINS
    if isinstance(value, PinnedSet):
        return value
    if isinstance(value, PinnedArea):
        return PinnedSet((value,))
    if isinstance(value, (list, tuple)):
        return PinnedSet(tuple(value))
    raise TypeError(f"cannot use {type(value).__name__} as pinned areas")


def starter_village_area(map_file: Optional[Path] = None) -> PinnedArea:
    """The authored village at the world origin. Reads `size_tiles` from the map file when given (read-only), else 48 x 36."""
    w, h = 48, 36
    if map_file is not None:
        size = json.loads(Path(map_file).read_text(encoding="utf-8"))["size_tiles"]
        w, h = int(size[0]), int(size[1])
    return PinnedArea("starter_village", 0, 0, w, h)
