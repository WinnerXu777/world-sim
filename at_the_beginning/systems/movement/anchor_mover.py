"""AnchorMover: walk a resident to an anchor along an A* path, one bounded step per tick, sliding every step.

Engine-agnostic: the caller passes the current position and the movement contract (the dict ``spatial.slide`` takes).
Each call moves AT MOST ``step_len`` and finishes with ``spatial.slide`` itself, so the resident never ends embedded
in a wall and never crosses one, whatever the task phase or other movement did earlier in the tick (finding 5 of
1006_smith_loop_design.md). Plans live in this object (not saved): after a restore a plan is simply rebuilt.
"""
import math
from dataclasses import dataclass

from .pathing import plan_path
from .spatial import is_standable_point, slide, snap_to_standable

ANCHOR_TOLERANCE = 2.0     # arrival radius in units (12 px at 6 px/unit)
WAYPOINT_REACHED = 0.75    # a waypoint counts as reached inside this distance
STALL_TICKS = 12           # ticks without real progress before the plan is rebuilt
NO_PATH_TTL_TICKS = 100    # a "no path" answer is remembered this long
MAX_REPLANS = 6            # consecutive replans without arriving before the mover reports "stuck"
# EDEN_WINDOW contracts (they carry ``static_revision``): every chunk integration changes ``revision``, so a "no path" memo keyed on it
# never survives and each integration re-ran the full 3-attempt search that exhausts the reachable area (~100 ms per resident, 250 ms
# in the first ticks). In window mode the memo is keyed on the walls' own revision and lives WINDOW_NO_PATH_TTL_TICKS: a goal that a newly
# integrated chunk makes reachable is planned at most that many ticks later (max staleness 20 ticks = 1 s). A change to the static walls
# still drops the memo at once. And at most PLAN_EXPANSION_BUDGET A* expansions (summed over attempts, a count, never a clock) are spent
# per tick: a plan that starts after the budget is used up is deferred to the next tick and the resident stands still for it.
WINDOW_NO_PATH_TTL_TICKS = 20
PLAN_EXPANSION_BUDGET = 12_000


@dataclass
class StepResult:
    """Outcome of one walking tick: where the resident stands, whether he arrived, why he is blocked, how far he moved."""
    position: tuple
    arrived: bool = False
    blocked: str = ""       # "", "no_path", "goal_not_standable", "stuck"
    moved: float = 0.0
    replanned: bool = False


class AnchorMover:
    """Walks one resident per key along an A* route, one step of ``step_len`` per tick and always sliding along walls; caches plans and unreachable goals."""
    def __init__(self, step_len=1.0, tolerance=ANCHOR_TOLERANCE, planner=plan_path):
        if not (step_len > 0 and math.isfinite(step_len)):
            raise ValueError("step_len must be finite and > 0")
        self.step_len = float(step_len)
        self.tolerance = float(tolerance)
        self.planner = planner  # injectable for tests
        self.plans = {}
        self.no_path = {}       # key -> (goal, revision, expires_tick); window mode: revision = the walls' static_revision
        self.plan_calls = 0
        self.deferred = 0       # window mode: plans pushed to a later tick by PLAN_EXPANSION_BUDGET (diagnostic)
        self._budget_tick = None
        self._budget_used = 0

    def forget(self, key):
        self.plans.pop(key, None)
        self.no_path.pop(key, None)

    def _revision(self, contract):
        return contract.get("revision") or (len(contract["boxes"]), tuple(contract["bounds"]))

    def _plan(self, key, position, goal, contract, tick):
        static = contract.get("static_revision")
        windowed = static is not None
        revision = static if windowed else self._revision(contract)
        cached = self.no_path.get(key)
        if cached and cached[0] == goal and cached[1] == revision and tick < cached[2]:
            return None, "no_path"
        if windowed:
            if self._budget_tick != tick:
                self._budget_tick, self._budget_used = tick, 0
            elif self._budget_used >= PLAN_EXPANSION_BUDGET:
                self.deferred += 1
                return None, "deferred"
        self.plan_calls += 1
        result = self.planner(position, goal, contract)
        if windowed:
            self._budget_used += max(getattr(result, "spent", 0), getattr(result, "expansions", 0))
        if result.waypoints is None:
            if result.reason == "goal_not_standable":
                return None, "goal_not_standable"
            if result.reason == "start_not_standable":
                snapped = snap_to_standable(position, contract)
                if snapped is None:
                    return None, "no_path"
                return {"snap": snapped}, ""
            self.no_path[key] = (goal, revision, tick + (WINDOW_NO_PATH_TTL_TICKS if windowed else NO_PATH_TTL_TICKS))
            return None, "no_path"
        self.no_path.pop(key, None)
        previous = self.plans.get(key)
        plan = {"goal": goal, "waypoints": list(result.waypoints) or [goal], "index": 0, "revision": self._revision(contract),
                "best": math.inf, "stalled": 0, "replans": (previous["replans"] + 1) if previous and previous["goal"] == goal else 0}
        return plan, ""

    def step(self, key, position, goal, contract, tick=0):
        """Advance one tick toward ``goal``. Returns a StepResult whose position is where the resident now stands."""
        position = (float(position[0]), float(position[1]))
        goal = (float(goal[0]), float(goal[1]))
        if math.hypot(goal[0] - position[0], goal[1] - position[1]) <= self.tolerance:
            self.plans.pop(key, None)
            return StepResult(position, arrived=True)
        plan = self.plans.get(key)
        replanned = False
        revision = self._revision(contract)
        if plan is None or plan["goal"] != goal or plan["revision"] != revision or plan["stalled"] >= STALL_TICKS:
            if plan is not None and plan["stalled"] >= STALL_TICKS and plan["replans"] >= MAX_REPLANS:
                self.plans.pop(key, None)
                return StepResult(position, blocked="stuck")
            plan, reason = self._plan(key, position, goal, contract, tick)
            replanned = True
            if plan is None:
                if reason == "deferred":                      # not blocked, not walked: the plan is made on a later tick
                    return StepResult(position)
                return StepResult(position, blocked=reason, replanned=True)
            if "snap" in plan:  # the resident started embedded: stand it up and plan next tick
                self.plans.pop(key, None)
                return StepResult(plan["snap"], moved=math.hypot(plan["snap"][0] - position[0], plan["snap"][1] - position[1]), replanned=True)
            self.plans[key] = plan
        waypoints = plan["waypoints"]
        while plan["index"] < len(waypoints) - 1 and math.hypot(waypoints[plan["index"]][0] - position[0],
                                                                waypoints[plan["index"]][1] - position[1]) <= WAYPOINT_REACHED:
            plan["index"] += 1
        target = waypoints[plan["index"]]
        dx, dy = target[0] - position[0], target[1] - position[1]
        distance = math.hypot(dx, dy)
        if distance < 1e-9:
            return StepResult(position, replanned=replanned)
        move = min(self.step_len, distance)
        desired = (position[0] + dx / distance * move, position[1] + dy / distance * move)
        new_position = slide(position, desired, contract)
        moved = math.hypot(new_position[0] - position[0], new_position[1] - position[1])
        remaining = math.hypot(goal[0] - new_position[0], goal[1] - new_position[1])
        path_left = math.hypot(target[0] - new_position[0], target[1] - new_position[1]) + sum(
            math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(waypoints[plan["index"]:], waypoints[plan["index"] + 1:]))
        if path_left < plan["best"] - 0.05 * self.step_len:  # progress is measured along the route, not as the crow flies
            plan["best"], plan["stalled"] = path_left, 0
        else:
            plan["stalled"] += 1
        arrived = remaining <= self.tolerance
        if arrived:
            self.plans.pop(key, None)
        return StepResult(new_position, arrived=arrived, moved=moved, replanned=replanned)


__all__ = ["ANCHOR_TOLERANCE", "AnchorMover", "StepResult", "is_standable_point"]
