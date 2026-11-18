"""Connected-component labels of the walkable space, per movement-contract revision.

``Components`` rasterises the same lattice ``systems.movement.pathing`` plans on (cell = actor_radius / 2, wall boxes inflated by the actor
radius plus the planner's tight safety margin, open interiors blocked), labels every free run of every lattice row, and joins runs of
adjacent rows that overlap (4-connectivity: a diagonal step that does not cut a corner needs both orthogonal neighbours free, so the
components are the same as the planner's 8-connected no-corner-cutting ones). The labelling is done with union-find over runs, not
over cells, so a 1056 x 480 map costs a few thousand unions.

``label(point)`` is the component id of the nearest free lattice node (within ``ATTACH_RING`` rings, and only a node the point can see
without crossing an inflated wall), or None when the point has no such node. Two points with the same label are connected: ``Reach`` uses
that as a positive shortcut for the legality mask, where only "can they get there" matters and not "how far". A different label is
never trusted as a negative (the planner retries with a finer lattice and finds doors this one can miss): it falls back to the search.

Reads the private helpers ``_contract``, ``_inflate`` and ``_segment_hits`` of ``systems.movement.pathing``; if they change shape the
import fails, ``available()`` is False, and ``Reach`` simply does not use components.
"""
from __future__ import annotations

import math
import re
from bisect import bisect_right
from typing import Optional

try:
    from systems.movement.pathing import ATTACH_RING, TIGHT_MARGIN, _contract, _inflate, _segment_hits
except Exception:  # noqa: BLE001 - the planner's internals moved: components are simply unavailable
    ATTACH_RING = 4
    _contract = None

_FREE = re.compile(rb"\x00+")


def available() -> bool:
    return _contract is not None


class Components:
    def __init__(self, contract: dict):
        radius, bounds, boxes = _contract(contract)
        self.radius = radius
        self.cell = max(radius / 2.0, max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 800.0)
        self.x0, self.y0 = bounds[0] + radius, bounds[1] + radius
        span_x, span_y = bounds[2] - radius - self.x0, bounds[3] - radius - self.y0
        self.w = int(span_x / self.cell + 1e-9) + 1
        self.h = int(span_y / self.cell + 1e-9) + 1
        self.inflated = _inflate(boxes, radius)                      # exact inflated walls (the standable test of the planner)
        tight = _inflate(boxes, radius + TIGHT_MARGIN)
        rows = [bytearray(self.w) for _ in range(self.h)]
        tol = 1e-9
        for a, b, c, d in tight:
            i_lo = max(0, math.floor((a + tol - self.x0) / self.cell) + 1)
            i_hi = min(self.w - 1, math.ceil((c - tol - self.x0) / self.cell) - 1)
            j_lo = max(0, math.floor((b + tol - self.y0) / self.cell) + 1)
            j_hi = min(self.h - 1, math.ceil((d - tol - self.y0) / self.cell) - 1)
            if i_lo > i_hi or j_lo > j_hi:
                continue
            run = b"\x01" * (i_hi - i_lo + 1)
            for j in range(j_lo, j_hi + 1):
                rows[j][i_lo:i_hi + 1] = run
        self.rows = rows
        self._label_runs()

    # labelling -----------------------------------------------------------------------
    def _label_runs(self) -> None:
        parent: list = []

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        self.runs = []                       # per row: (starts, ends, ids)
        previous = None
        for j, row in enumerate(self.rows):
            starts, ends, ids = [], [], []
            for m in _FREE.finditer(bytes(row)):
                starts.append(m.start())
                ends.append(m.end() - 1)
                ids.append(len(parent))
                parent.append(len(parent))
            if previous is not None:
                ps, pe, pi = previous
                a = b = 0
                while a < len(starts) and b < len(ps):                # two-pointer overlap of the sorted runs
                    if starts[a] <= pe[b] and ps[b] <= ends[a]:
                        ra, rb = find(ids[a]), find(pi[b])
                        if ra != rb:
                            parent[max(ra, rb)] = min(ra, rb)
                    if ends[a] < pe[b]:
                        a += 1
                    else:
                        b += 1
            self.runs.append((starts, ends, ids))
            previous = (starts, ends, ids)
        self._parent = parent
        self._find = find
        self.count = len({find(i) for i in range(len(parent))})

    # queries -------------------------------------------------------------------------
    def _node_label(self, i: int, j: int) -> Optional[int]:
        if not (0 <= i < self.w and 0 <= j < self.h):
            return None
        starts, ends, ids = self.runs[j]
        k = bisect_right(starts, i) - 1
        if k >= 0 and i <= ends[k]:
            return self._find(ids[k])
        return None

    def label(self, point: tuple) -> Optional[int]:
        x, y = float(point[0]), float(point[1])
        ci, cj = round((x - self.x0) / self.cell), round((y - self.y0) / self.cell)
        best = None
        for j in range(cj - ATTACH_RING, cj + ATTACH_RING + 1):
            for i in range(ci - ATTACH_RING, ci + ATTACH_RING + 1):
                label = self._node_label(i, j)
                if label is None:
                    continue
                node = (self.x0 + i * self.cell, self.y0 + j * self.cell)
                d = math.hypot(node[0] - x, node[1] - y)
                if best is None or d < best[0]:
                    if not _segment_hits((x, y), node, self.inflated):          # the point must see the node
                        best = (d, label)
        return None if best is None else best[1]

    def connected(self, start: tuple, goal: tuple) -> bool:
        a = self.label(start)
        return a is not None and a == self.label(goal)
