"""Standalone grid A* pathing for actors that move with ``spatial.slide``.

Nothing here touches the engine; it only reads a movement contract
(``actor_radius``, ``bounds``, ``boxes``), the same dict ``spatial.slide`` takes.

Collision model (identical to ``slide``): the actor is a point whose standable
region is the bounds shrunk by ``actor_radius`` minus every wall box inflated by
``actor_radius`` on all sides (open interiors; boundaries are standable).

Result convention
-----------------
``plan_path`` returns a ``PathResult``. ``find_path`` is a thin wrapper that
returns just ``result.waypoints``.

* ``waypoints`` excludes ``start`` and ends with ``goal`` exactly as given;
  walk them in order with straight-line ``slide`` steps. ``[]`` means
  ``start == goal``. ``None`` means no path; ``reason`` says why:
  ``start_not_standable``, ``goal_not_standable``, ``no_path``,
  ``search_limit`` (expansion budget exhausted, the route may still exist).
* Invalid input (non-finite numbers, non-positive radius) raises ``ValueError``.

Method
------
1. Reject non-standable start/goal (same tolerance as ``slide``'s "embedded" rule).
2. If the straight segment is clear, return ``[goal]`` (no grid is built).
3. Rasterise the inflated boxes onto a lattice whose origin is the minimum
   standable point; 8-connected A* (no diagonal corner cutting, octile heuristic,
   deterministic tie-breaking by index). Start and goal attach to nearby lattice
   nodes they can see.
4. Remove collinear points, then greedy line-of-sight string pulling.

Why ``cell = actor_radius / 2``: a passage of width ``g`` leaves a centre band of
``g - 2r``; for an 8-unit door at r = 2.4 that is 3.2 units, which holds at least
two lattice nodes at 1.2-unit spacing, so the door is never missed. Smoothing
then removes the staircase, so a finer cell only buys narrower doors, not
better paths. If no path is found the search is retried with a smaller safety
margin and then a half-size cell, so doors with a centre band down to about
0.6 units are still found (bands of 0.6 or less may be missed and reported as
``no_path``; the map validator should keep gaps at 2r + 1 or more).

Safety margin: the lattice and the line-of-sight tests treat boxes as inflated
by ``actor_radius + margin`` (default 0.15), so waypoints and segments keep a
little clearance from the exact inflated edge. ``slide`` resolves X then Y per
step, which can graze a corner by up to about half a step; grazing only slides,
it does not stall (verified in tests with 1.0 and 1.5-unit steps).

Limits: lattice size is capped (``MAX_CELLS``) by coarsening the cell, and
``max_expansions`` bounds the search, so huge maps with a tiny radius (the
legacy 0.35) trade precision for time. This module is meant for 2D maps with
radius around 2.4 and bounds in the hundreds of units.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, replace

EMBED_TOL = 1e-4        # slide treats a start inside an inflated box by more than this as embedded
DEFAULT_MARGIN = 0.15
TIGHT_MARGIN = 0.02
MAX_CELLS = 1_500_000
DEFAULT_MAX_EXPANSIONS = 250_000
ATTACH_RING = 4         # lattice rings searched around start/goal for a visible node
_SQRT2 = math.sqrt(2.0)


@dataclass(frozen=True)
class PathResult:
    """Result of a path search: the waypoints (None when there is no path) and the reason."""
    waypoints: list | None
    reason: str | None = None
    cell: float = 0.0
    margin: float = 0.0
    expansions: int = 0
    spent: int = 0          # expansions over every attempt of plan_path (``expansions`` is the last attempt's), a deterministic work measure


def _contract(contract):
    radius = float(contract["actor_radius"])
    bounds = [float(v) for v in contract["bounds"]]
    boxes = [(float(b["min"][0]), float(b["min"][1]), float(b["max"][0]), float(b["max"][1]))
             for b in contract["boxes"]]
    values = [radius, *bounds, *(v for box in boxes for v in box)]
    if not all(math.isfinite(v) for v in values) or radius <= 0:
        raise ValueError("contract needs a finite positive actor_radius, finite bounds and boxes")
    return radius, bounds, boxes


def _inflate(boxes, amount):
    return [(a - amount, b - amount, c + amount, d + amount) for a, b, c, d in boxes]


def _inside(point, boxes, tol):
    x, y = point
    return any(a + tol < x < c - tol and b + tol < y < d - tol for a, b, c, d in boxes)


def is_standable(point, contract):
    """True when ``slide`` would let an actor stand at ``point`` (not embedded, within bounds)."""
    radius, bounds, boxes = _contract(contract)
    return _standable(point, radius, bounds, _inflate(boxes, radius))


def _standable(point, radius, bounds, inflated):
    x, y = point
    if not (math.isfinite(x) and math.isfinite(y)):
        return False
    eps = 1e-9
    if not (bounds[0] + radius - eps <= x <= bounds[2] - radius + eps
            and bounds[1] + radius - eps <= y <= bounds[3] - radius + eps):
        return False
    return not _inside(point, inflated, EMBED_TOL)


def _segment_hits(p, q, boxes):
    """True when the closed segment p-q passes through the open interior of any box."""
    px, py = p
    qx, qy = q
    lo_x, hi_x = (px, qx) if px <= qx else (qx, px)
    lo_y, hi_y = (py, qy) if py <= qy else (qy, py)
    dx, dy = qx - px, qy - py
    for a, b, c, d in boxes:
        if hi_x <= a or lo_x >= c or hi_y <= b or lo_y >= d:
            continue
        enter, leave = 0.0, 1.0
        blocked = True
        for start, delta, lo, hi in ((px, dx, a, c), (py, dy, b, d)):
            if abs(delta) < 1e-12:
                if not lo < start < hi:
                    blocked = False
                    break
                continue
            t1, t2 = (lo - start) / delta, (hi - start) / delta
            if t1 > t2:
                t1, t2 = t2, t1
            enter, leave = max(enter, t1), min(leave, t2)
            if enter >= leave - 1e-12:
                blocked = False
                break
        if blocked:
            return True
    return False


class _Grid:
    def __init__(self, radius, bounds, margin, cell, expand_boxes, max_cells):
        self.x0, self.y0 = bounds[0] + radius, bounds[1] + radius
        span_x, span_y = bounds[2] - radius - self.x0, bounds[3] - radius - self.y0
        cell = max(cell, 1e-6)
        while (span_x / cell + 1) * (span_y / cell + 1) > max_cells:
            cell *= 1.25
        self.cell = cell
        self.w = int(span_x / cell + 1e-9) + 1
        self.h = int(span_y / cell + 1e-9) + 1
        blocked = bytearray(self.w * self.h)
        tol = 1e-9
        for a, b, c, d in expand_boxes:
            i_lo = max(0, math.floor((a + tol - self.x0) / cell) + 1)
            i_hi = min(self.w - 1, math.ceil((c - tol - self.x0) / cell) - 1)
            j_lo = max(0, math.floor((b + tol - self.y0) / cell) + 1)
            j_hi = min(self.h - 1, math.ceil((d - tol - self.y0) / cell) - 1)
            if i_lo > i_hi or j_lo > j_hi:
                continue
            run = b"\x01" * (i_hi - i_lo + 1)
            for j in range(j_lo, j_hi + 1):
                base = j * self.w
                blocked[base + i_lo:base + i_hi + 1] = run
        self.blocked = blocked

    def point(self, index):
        j, i = divmod(index, self.w)
        return (self.x0 + i * self.cell, self.y0 + j * self.cell)

    def nearby(self, point, rings):
        """Free lattice indices around ``point``, nearest first (deterministic)."""
        ci = round((point[0] - self.x0) / self.cell)
        cj = round((point[1] - self.y0) / self.cell)
        found = []
        for j in range(max(0, cj - rings), min(self.h - 1, cj + rings) + 1):
            for i in range(max(0, ci - rings), min(self.w - 1, ci + rings) + 1):
                index = j * self.w + i
                if not self.blocked[index]:
                    found.append((math.hypot(self.x0 + i * self.cell - point[0], self.y0 + j * self.cell - point[1]), index))
        found.sort()
        return found


def _plan(start, goal, radius, bounds, boxes, cell, margin, max_expansions):
    inflated_true = _inflate(boxes, radius)
    inflated_safe = _inflate(boxes, radius + margin)

    def margin_zone(point):
        return _inside(point, inflated_safe, 0.0)

    def clear(p, q):
        if not _segment_hits(p, q, inflated_safe):
            return True
        # An endpoint already inside the safety margin (start/goal hugging a wall)
        # is only held to the exact inflated boxes.
        return (margin_zone(p) or margin_zone(q)) and not _segment_hits(p, q, inflated_true)

    if clear(start, goal):
        return PathResult([goal], None, cell, margin, 0)

    grid = _Grid(radius, bounds, margin, cell, inflated_safe, MAX_CELLS)
    w, cell = grid.w, grid.cell
    sources = [(d, i) for d, i in grid.nearby(start, ATTACH_RING) if clear(start, grid.point(i))]
    goals = {i: d for d, i in grid.nearby(goal, ATTACH_RING) if clear(grid.point(i), goal)}
    if not sources or not goals:
        return PathResult(None, "no_path", cell, margin, 0)

    blocked = grid.blocked
    height = grid.h
    size = w * height
    gscore = [math.inf] * size
    parent = [-1] * size
    done = bytearray(size)
    gx, gy = goal
    x0, y0 = grid.x0, grid.y0
    diag = cell * _SQRT2
    octile = _SQRT2 - 2.0

    def heuristic(i, j):
        dx, dy = abs(x0 + i * cell - gx), abs(y0 + j * cell - gy)
        return dx + dy + octile * (dx if dx < dy else dy)

    heap = []
    for d, index in sources:
        if d < gscore[index]:
            gscore[index] = d
            hs = heuristic(index % w, index // w)
            heap.append((d + hs, hs, index))
    heapq.heapify(heap)
    steps = ((-1, 0, cell), (1, 0, cell), (0, -1, cell), (0, 1, cell),
             (-1, -1, diag), (1, -1, diag), (-1, 1, diag), (1, 1, diag))
    expansions = 0
    end = -1
    best_total = math.inf
    push, pop = heapq.heappush, heapq.heappop
    while heap:
        f, h, index = pop(heap)
        if index == -2:               # virtual goal node: the best attachment has been reached
            break
        if done[index]:
            continue
        done[index] = 1
        expansions += 1
        if expansions > max_expansions:
            return PathResult(None, "search_limit", cell, margin, expansions)
        g = gscore[index]
        if index in goals:
            total = g + goals[index]
            if total < best_total:
                best_total, end = total, index
                push(heap, (total, 0.0, -2))
        j, i = divmod(index, w)
        for di, dj, step in steps:
            ni, nj = i + di, j + dj
            if ni < 0 or nj < 0 or ni >= w or nj >= height:
                continue
            neighbor = nj * w + ni
            if blocked[neighbor] or done[neighbor]:
                continue
            if di and dj and (blocked[j * w + ni] or blocked[nj * w + i]):
                continue
            ng = g + step
            if ng < gscore[neighbor]:
                gscore[neighbor] = ng
                parent[neighbor] = index
                hn = heuristic(ni, nj)
                push(heap, (ng + hn, hn, neighbor))
    else:
        return PathResult(None, "no_path", cell, margin, expansions)

    chain = []
    index = end
    while index != -1:
        chain.append(grid.point(index))
        index = parent[index]
    chain.reverse()
    points = [start, *chain, goal]
    return PathResult(_smooth(points, clear)[1:], None, cell, margin, expansions)


def _smooth(points, clear):
    """Drop collinear runs, then greedy farthest-visible string pulling."""
    kept = [points[0]]
    for k in range(1, len(points) - 1):
        ax, ay = kept[-1]
        bx, by = points[k]
        cx, cy = points[k + 1]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        dot = (bx - ax) * (cx - bx) + (by - ay) * (cy - by)
        if abs(cross) > 1e-9 or dot < 0:
            kept.append(points[k])
    kept.append(points[-1])
    result = [kept[0]]
    i = 0
    while i < len(kept) - 1:
        j = len(kept) - 1
        while j > i + 1 and not clear(kept[i], kept[j]):
            j -= 1
        result.append(kept[j])
        i = j
    return result


def plan_path(start, goal, contract, cell=None, margin=DEFAULT_MARGIN, max_expansions=DEFAULT_MAX_EXPANSIONS):
    """Plan a route; see the module docstring for the result convention."""
    radius, bounds, boxes = _contract(contract)
    start, goal = (float(start[0]), float(start[1])), (float(goal[0]), float(goal[1]))
    if not all(math.isfinite(v) for v in (*start, *goal)) or margin < 0:
        raise ValueError("start, goal and margin must be finite and margin non-negative")
    if cell is not None and not (math.isfinite(cell) and cell > 0):
        raise ValueError("cell must be a positive finite number")
    inflated = _inflate(boxes, radius)
    if not _standable(start, radius, bounds, inflated):
        return PathResult(None, "start_not_standable")
    if not _standable(goal, radius, bounds, inflated):
        return PathResult(None, "goal_not_standable")
    if math.hypot(goal[0] - start[0], goal[1] - start[1]) <= 1e-9:
        return PathResult([])
    base = float(cell) if cell is not None else max(radius / 2.0, max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 800.0)
    attempts = [(base, float(margin)), (base, min(float(margin), TIGHT_MARGIN)), (base / 2.0, min(float(margin), TIGHT_MARGIN))]
    result = None
    spent = 0
    for attempt_cell, attempt_margin in dict.fromkeys(attempts):
        result = _plan(start, goal, radius, bounds, boxes, attempt_cell, attempt_margin, max_expansions)
        spent += result.expansions
        if result.waypoints is not None or result.reason != "no_path":
            break
    return replace(result, spent=spent)


def find_path(start, goal, contract, cell=None):
    """Waypoints from ``start`` (excluded) to ``goal`` (included), or ``None``. See ``plan_path`` for the reason."""
    return plan_path(start, goal, contract, cell).waypoints
