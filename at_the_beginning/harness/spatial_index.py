"""World-owned spatial index: per space, per chunk buckets keyed by stable ids (replaces the ``map_geo`` module globals for
new code; the legacy index is untouched).

Positions are stored as ``AbsPos`` (integer chunk + float64 offset), so a window rebase never invalidates the index. Queries
use exact float64 arithmetic (``math.hypot`` on offsets relative to the query point), not ``torch.cdist``, so they are exact at
any distance from the origin. Results are ordered by id for determinism.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Optional

from .frame import AbsPos, SpaceFrame


def _order_key(entity_id):
    return (0, entity_id) if isinstance(entity_id, int) else (1, str(entity_id))


class SpatialIndex:
    def __init__(self, chunk_units: float = 256.0):
        self.chunk_units = float(chunk_units)
        self._pos: dict = {}                       # id -> (space, AbsPos)
        self._cells: dict = defaultdict(set)       # (space, cx, cy) -> {id}

    # mutation ----------------------------------------------------------------
    def insert(self, entity_id, space: int, pos: AbsPos) -> None:
        if entity_id in self._pos:
            self.remove(entity_id)
        self._pos[entity_id] = (int(space), pos)
        self._cells[(int(space), pos.chunk_x, pos.chunk_y)].add(entity_id)

    def move(self, entity_id, pos: AbsPos, space: Optional[int] = None) -> None:
        old_space, _ = self._pos[entity_id]
        self.insert(entity_id, old_space if space is None else space, pos)

    def remove(self, entity_id) -> bool:
        entry = self._pos.pop(entity_id, None)
        if entry is None:
            return False
        space, pos = entry
        key = (space, pos.chunk_x, pos.chunk_y)
        bucket = self._cells.get(key)
        if bucket is not None:
            bucket.discard(entity_id)
            if not bucket:
                del self._cells[key]
        return True

    def remove_chunk(self, space: int, chunk: tuple[int, int]) -> list:
        """Drop every entity in a chunk (unload); returns their ids in id order."""
        ids = sorted(self._cells.get((int(space), chunk[0], chunk[1]), ()), key=_order_key)
        for entity_id in ids:
            self.remove(entity_id)
        return ids

    def insert_local(self, frame: SpaceFrame, entity_id, x: float, y: float) -> None:
        self.insert(entity_id, frame.space, frame.to_absolute(x, y))

    # queries -----------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._pos)

    def __contains__(self, entity_id) -> bool:
        return entity_id in self._pos

    def position_of(self, entity_id) -> Optional[tuple[int, AbsPos]]:
        return self._pos.get(entity_id)

    def ids_in_chunk(self, space: int, chunk: tuple[int, int]) -> list:
        return sorted(self._cells.get((int(space), chunk[0], chunk[1]), ()), key=_order_key)

    def chunks(self, space: Optional[int] = None) -> list:
        return sorted(k for k in self._cells if space is None or k[0] == space)

    def query_radius(self, space: int, centre: AbsPos, radius: float, exclude: Iterable = ()) -> list:
        """Ids in ``space`` within ``radius`` of ``centre`` (inclusive), ordered by id."""
        if radius < 0:
            return []
        size, skip = self.chunk_units, set(exclude)
        span = int(math.ceil(radius / size)) + 1
        out = []
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                for entity_id in self._cells.get((int(space), centre.chunk_x + dx, centre.chunk_y + dy), ()):
                    if entity_id in skip:
                        continue
                    _, p = self._pos[entity_id]
                    ox = (p.chunk_x - centre.chunk_x) * size + (p.x - centre.x)
                    oy = (p.chunk_y - centre.chunk_y) * size + (p.y - centre.y)
                    if math.hypot(ox, oy) <= radius:
                        out.append(entity_id)
        return sorted(out, key=_order_key)

    def nearest(self, space: int, centre: AbsPos, max_radius: float, exclude: Iterable = ()):
        """Closest id within ``max_radius`` (ties broken by id order), or ``None``."""
        size, best, best_d = self.chunk_units, None, None
        for entity_id in self.query_radius(space, centre, max_radius, exclude):
            _, p = self._pos[entity_id]
            d = math.hypot((p.chunk_x - centre.chunk_x) * size + (p.x - centre.x), (p.chunk_y - centre.chunk_y) * size + (p.y - centre.y))
            if best_d is None or d < best_d:
                best, best_d = entity_id, d
        return best
