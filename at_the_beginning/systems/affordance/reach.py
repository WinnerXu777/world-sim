"""Pluggable reachability: straight line first, then ``systems.movement.pathing.plan_path`` with a small expansion cap.

``Reach.check(start, goal)`` answers "can an actor walk from here to there?" for the few candidate options the engine actually surfaces:

1. no movement contract (a map without walls) -> reachable, ``mode="exact"``;
2. the goal is on another placed map -> walk to the portal, then from the portal exit to the goal (one hop per call, up to 3);
3. an entity goal sits inside its own footprint wall: the goal becomes the nearest standable point (``snap_to_standable``);
4. a clear straight segment (the same wall-box test commission uses) -> reachable, ``exact``;
5. when only "can it get there" is needed (``need_length=False``, the legality mask), two points in the same connected component of the
   walkable lattice (``components.py``, labelled once per contract revision) are reachable without any search: ``mode="component"``, length =
   the straight-line distance (a lower bound). A different label is not trusted as a negative; it falls through to the search below;
6. otherwise ``plan_path`` with ``max_expansions``; a path -> reachable with its polyline length, ``exact``; ``no_path`` -> not
   reachable, ``exact``; budget exhausted (``search_limit``) -> the search is repeated once from the goal (a sealed pocket floods
   quickly from inside); if that also runs out, the straight-line answer (blocked) is used and marked ``approx``.

Results are cached on ``(contract revision, start cell, goal cell, goal entity)``; cells are ``REACH_CELL_QUANT`` wide, so two queries
inside one cell share an answer (a start within ~1 unit of a wall edge can be mislabelled by the quantisation; a measured
simplification, see ``1008_actions.md``). The class is replaceable: anything with ``check`` and ``stats`` works.
"""
from __future__ import annotations

import math
import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from . import components as comp
from . import config


@dataclass(frozen=True)
class ReachResult:
    ok: bool
    mode: str            # "exact" | "approx" | "component" (connected, length is a straight-line lower bound)
    reason: str = ""     # "" | "unreachable" | "blocked"
    length: float = 0.0
    hops: int = 0        # portals taken


def _polyline(start, waypoints) -> float:
    total, prev = 0.0, start
    for point in waypoints:
        total += math.hypot(point[0] - prev[0], point[1] - prev[1])
        prev = point
    return total


class Reach:
    def __init__(self, services, *, max_expansions: int = config.REACH_MAX_EXPANSIONS, quant: float = config.REACH_CELL_QUANT,
                 cache_size: int = config.REACH_CACHE_SIZE):
        self.services = services
        self.max_expansions, self.quant, self.cache_size = int(max_expansions), float(quant), int(cache_size)
        self._cache: OrderedDict = OrderedDict()
        self.stats = {"calls": 0, "hits": 0, "misses": 0, "straight": 0, "path_searches": 0, "reverse_searches": 0, "no_path": 0, "capped": 0,
                      "portal_hops": 0, "search_ms": 0.0, "component_hits": 0, "components_built": 0, "component_build_ms": 0.0, "too_far": 0}
        self._components = None            # (contract revision, Components)

    # public -------------------------------------------------------------------
    def check(self, start: tuple, goal: tuple, *, goal_entity: Optional[str] = None, depth: int = 0, need_length: bool = True) -> ReachResult:
        self.stats["calls"] += 1
        contract = self.services.contract()
        start, goal = (float(start[0]), float(start[1])), (float(goal[0]), float(goal[1]))
        if contract is None:
            return ReachResult(True, "exact", "", math.hypot(goal[0] - start[0], goal[1] - start[1]))
        key = (self.services.contract_revision(), round(start[0] / self.quant), round(start[1] / self.quant),
               round(goal[0] / self.quant), round(goal[1] / self.quant), goal_entity or "")
        found = self._cache.get(key)                       # an exact answer serves both kinds of question
        if found is None and not need_length:
            found = self._cache.get(key + ("q",))
        if found is not None:
            self._cache.move_to_end(key if key in self._cache else key + ("q",))
            self.stats["hits"] += 1
            return found
        self.stats["misses"] += 1
        result = self._compute(contract, start, goal, goal_entity, depth, need_length)
        self._cache[key if need_length or result.mode != "component" else key + ("q",)] = result
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return result

    def clear(self) -> None:
        self._cache.clear()

    # internals ----------------------------------------------------------------
    @staticmethod
    def max_distance() -> float:
        """``EDEN_REACH_MAX_DISTANCE`` in world units (read at call time; unset, empty or not a positive number: no cap)."""
        raw = os.environ.get(config.REACH_MAX_DISTANCE_ENV, "")
        try:
            return max(0.0, float(raw)) if raw else 0.0
        except ValueError:
            return 0.0

    def components_for(self, contract) -> Optional["comp.Components"]:
        """The connected-component labelling of the current contract revision (built on first use, None if unavailable)."""
        if not comp.available():
            return None
        revision = self.services.contract_revision()
        if self._components is None or self._components[0] != revision:
            import time
            began = time.perf_counter()
            self._components = (revision, comp.Components(contract))
            self.stats["components_built"] += 1
            self.stats["component_build_ms"] += (time.perf_counter() - began) * 1000.0
        return self._components[1]

    def _compute(self, contract, start, goal, goal_entity, depth, need_length=True) -> ReachResult:
        portal = self.services.portal_toward(start, goal) if depth < 3 else None
        if portal is not None:
            self.stats["portal_hops"] += 1
            first = self.check(start, tuple(portal[0]), depth=depth + 1, need_length=need_length)
            second = self.check(tuple(portal[1]), goal, goal_entity=goal_entity, depth=depth + 1, need_length=need_length)
            ok = first.ok and second.ok
            mode = "approx" if "approx" in (first.mode, second.mode) else "component" if "component" in (first.mode, second.mode) else "exact"
            return ReachResult(ok, mode,
                               "" if ok else (first.reason or second.reason or "unreachable"),
                               first.length + second.length, first.hops + second.hops + 1)
        from systems.movement.pathing import plan_path
        from systems.movement.spatial import segment_blocked, snap_to_standable
        target = goal
        if goal_entity:
            snapped = snap_to_standable(goal, contract)
            if snapped is None:
                return ReachResult(False, "exact", "blocked")
            target = (float(snapped[0]), float(snapped[1]))
        if not segment_blocked(start, target, contract["boxes"]):
            self.stats["straight"] += 1
            return ReachResult(True, "exact", "", math.hypot(target[0] - start[0], target[1] - start[1]))
        if not need_length:
            labels = self.components_for(contract)
            if labels is not None and labels.connected(start, target):
                self.stats["component_hits"] += 1
                return ReachResult(True, "component", "", math.hypot(target[0] - start[0], target[1] - start[1]))
        limit = self.max_distance()
        if limit > 0.0 and math.hypot(target[0] - start[0], target[1] - start[1]) > limit:     # the search area grows with the request: a far goal is not searched (approx, like a capped search)
            self.stats["too_far"] += 1
            return ReachResult(False, "approx", "unreachable")
        import time
        began = time.perf_counter()
        self.stats["path_searches"] += 1
        result = plan_path(start, target, contract, max_expansions=self.max_expansions)
        self.stats["search_ms"] += (time.perf_counter() - began) * 1000.0
        if result.waypoints is not None:
            return ReachResult(True, "exact", "", _polyline(start, result.waypoints))
        if result.reason == "search_limit":
            # a sealed goal inside a big open map exhausts a search that starts in the open; the same question asked from the goal
            # floods only the small pocket and finishes (the grid is undirected, so a path exists in one direction iff in the other)
            began = time.perf_counter()
            self.stats["reverse_searches"] += 1
            back = plan_path(target, start, contract, max_expansions=self.max_expansions)
            self.stats["search_ms"] += (time.perf_counter() - began) * 1000.0
            if back.waypoints is not None:
                return ReachResult(True, "exact", "", _polyline(target, back.waypoints))
            if back.reason == "no_path":
                self.stats["no_path"] += 1
                return ReachResult(False, "exact", "unreachable")
            self.stats["capped"] += 1
            return ReachResult(False, "approx", "unreachable")        # straight line is blocked: the fallback answer
        if result.reason == "no_path":
            self.stats["no_path"] += 1
            return ReachResult(False, "exact", "unreachable")
        return ReachResult(False, "exact", "blocked")                 # start or goal not standable
