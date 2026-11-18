"""Grid A* pathing verified against the real ``spatial.slide`` (actor radius 2.4, 2D-map scale)."""
import math
import random
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from systems.movement.pathing import find_path, is_standable, plan_path  # noqa: E402
from systems.movement.spatial import slide  # noqa: E402

R = 2.4
FIXTURES = ROOT / "tests" / "fixtures" / "maps"


def contract(boxes, width=200, height=200, radius=R):
    return {"actor_radius": radius, "bounds": [0, 0, width, height],
            "boxes": [{"min": list(lo), "max": list(hi)} for lo, hi in boxes]}


def wall_with_door(gap, y=100.0, thickness=1.2, width=200):
    left = ([0, y - thickness / 2], [width / 2 - gap / 2, y + thickness / 2])
    right = ([width / 2 + gap / 2, y - thickness / 2], [width, y + thickness / 2])
    return [left, right]


def walk(c, start, waypoints, step, tol=0.05):
    """Walk waypoints with real slide steps; returns (position, steps, ok). ok is False if stuck or embedded."""
    p, steps = tuple(start), 0
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip([start, *waypoints], waypoints))
    limit = int(length / step * 1.5) + 5 * len(waypoints) + 10
    for target in waypoints:
        while True:
            d = math.hypot(target[0] - p[0], target[1] - p[1])
            if d <= tol:
                break
            s = min(step, d)
            nxt = slide(p, (p[0] + (target[0] - p[0]) / d * s, p[1] + (target[1] - p[1]) / d * s), c)
            steps += 1
            if nxt == p or steps > limit or not is_standable(nxt, c):
                return nxt, steps, False
            p = nxt
    return p, steps, True


class PathingTestCase(unittest.TestCase):
    def assertWalks(self, c, start, goal, tol=0.1, steps=(1.0, 1.5)):
        result = plan_path(start, goal, c)
        self.assertIsNotNone(result.waypoints, result.reason)
        self.assertEqual(result.waypoints[-1], tuple(float(v) for v in goal))
        for step in steps:
            position, count, ok = walk(c, start, result.waypoints, step)
            self.assertTrue(ok, f"step {step}: stuck/embedded at {position} after {count} steps; path {result.waypoints}")
            self.assertLessEqual(math.hypot(position[0] - goal[0], position[1] - goal[1]), tol)
        return result


class LayoutTests(PathingTestCase):
    def test_open_field_is_one_straight_segment_and_needs_no_grid(self):
        c = contract([([90, 90], [110, 91])])
        result = self.assertWalks(c, (20, 20), (60, 150))
        self.assertEqual(result.waypoints, [(60.0, 150.0)])
        self.assertEqual(result.expansions, 0)

    def test_start_equals_goal_is_an_empty_path(self):
        self.assertEqual(find_path((50, 50), (50, 50), contract([])), [])

    def test_eight_and_ten_unit_doors_at_radius_2_4(self):
        for gap in (8.0, 10.0):
            c = contract(wall_with_door(gap))
            for start, goal in (((30, 150), (170, 40)), ((170, 30), (20, 180)), ((100, 140), (100, 60))):
                with self.subTest(gap=gap, start=start, goal=goal):
                    result = self.assertWalks(c, start, goal)
                    # the route must actually cross the wall line inside the door band
                    crossing = [p for p in result.waypoints if abs(p[1] - 100) < 8]
                    self.assertTrue(all(abs(p[0] - 100) <= (gap - 2 * R) / 2 + 1e-6 for p in crossing), crossing)

    def test_thick_walls_and_a_door_deep_in_a_wall(self):
        c = contract(wall_with_door(8.0, thickness=8.0))
        self.assertWalks(c, (20, 190), (180, 10))

    def test_narrow_doors_are_found_down_to_the_retry_resolution_and_impassable_ones_are_not(self):
        # Centre bands of 1.0 and 0.7 units (the validator's 2r + 1 u recommendation and below) need the
        # tight-margin / finer-cell retries; bands under half the default cell (0.6) may be missed.
        for band in (1.0, 0.7):
            with self.subTest(band=band):
                self.assertWalks(contract(wall_with_door(2 * R + band)), (30, 150), (170, 40), tol=0.2)
        sealed = contract(wall_with_door(2 * R - 0.01))        # slide cannot pass this
        result = plan_path((30, 150), (170, 40), sealed)
        self.assertIsNone(result.waypoints)
        self.assertEqual(result.reason, "no_path")

    def test_l_shaped_corridor(self):
        # Free area: [20,120]x[20,30] plus [110,120]x[20,120] (10 units wide, centre band 5.2).
        c = contract([([0, 0], [140, 20]), ([0, 20], [20, 140]), ([20, 30], [110, 140]),
                      ([120, 20], [140, 140]), ([0, 120], [140, 140])], 140, 140)
        result = self.assertWalks(c, (25, 25), (115, 115))
        self.assertGreaterEqual(len(result.waypoints), 2)
        self.assertWalks(c, (115, 115), (25, 25))

    def test_room_with_a_door_and_the_goal_inside(self):
        t = 2.0
        room = [([70, 70], [130, 70 + t]), ([70, 130 - t], [130, 130]), ([70, 70], [70 + t, 130]),
                ([130 - t, 70], [130, 130])]
        # Door: remove the middle 10 units of the south wall by splitting it.
        room[1:2] = [([70, 130 - t], [95, 130]), ([105, 130 - t], [130, 130])]
        c = contract(room)
        self.assertWalks(c, (20, 20), (100, 100))
        self.assertWalks(c, (100, 100), (180, 30))
        self.assertWalks(c, (60, 190), (80, 90))

    def test_no_route_when_the_room_is_sealed(self):
        t = 2.0
        c = contract([([70, 70], [130, 70 + t]), ([70, 130 - t], [130, 130]), ([70, 70], [70 + t, 130]),
                      ([130 - t, 70], [130, 130])])
        result = plan_path((20, 20), (100, 100), c)
        self.assertIsNone(result.waypoints)
        self.assertEqual(result.reason, "no_path")
        self.assertIsNone(find_path((20, 20), (100, 100), c))

    def test_goal_or_start_embedded_in_a_wall_is_rejected_with_a_reason(self):
        c = contract([([90, 90], [110, 110])])
        self.assertEqual(plan_path((20, 20), (100, 100), c).reason, "goal_not_standable")
        self.assertEqual(plan_path((100, 100), (20, 20), c).reason, "start_not_standable")
        # inside the inflated box (not inside the wall itself) is also embedded for slide
        self.assertEqual(plan_path((20, 20), (88.5, 100), c).reason, "goal_not_standable")
        # exactly on the inflated boundary is standable
        self.assertIsNotNone(find_path((20, 20), (90 - R, 100), c))
        # outside the bounds clamp
        self.assertEqual(plan_path((20, 20), (1, 1), c).reason, "goal_not_standable")

    def test_endpoints_hugging_a_wall_still_route(self):
        c = contract(wall_with_door(10.0))
        near = 100 + 0.6 + R + 0.05   # 5 hundredths outside the inflated edge (inside the safety margin)
        self.assertWalks(c, (60, near), (60, 100 - 0.6 - R - 0.05))
        self.assertWalks(c, (60, near), (100, 60))

    def test_invalid_contract_raises(self):
        with self.assertRaises(ValueError):
            plan_path((20, 20), (30, 30), contract([], radius=0))
        with self.assertRaises(ValueError):
            plan_path((20, 20), (30, 30), contract([([float("nan"), 0], [1, 1])]))

    def test_waypoints_keep_a_clearance_from_inflated_edges(self):
        c = contract(wall_with_door(8.0))
        for p in find_path((30, 150), (170, 40), c):
            for box in c["boxes"]:
                lo = (box["min"][0] - R, box["min"][1] - R)
                hi = (box["max"][0] + R, box["max"][1] + R)
                inside = lo[0] < p[0] < hi[0] and lo[1] < p[1] < hi[1]
                self.assertFalse(inside)
                gap_x = max(lo[0] - p[0], p[0] - hi[0], 0)
                gap_y = max(lo[1] - p[1], p[1] - hi[1], 0)
                if p != (170.0, 40.0):
                    self.assertGreaterEqual(math.hypot(gap_x, gap_y), 0.1 - 1e-9)


class RandomisedTests(PathingTestCase):
    def test_random_fields_walk_to_the_goal_with_real_slide(self):
        reached = unreachable = 0
        for seed in range(60):
            rng = random.Random(seed)
            size = rng.choice([120, 200, 300])
            boxes = []
            for _ in range(rng.randint(3, 25)):
                x, y = rng.uniform(0, size - 10), rng.uniform(0, size - 10)
                w, h = rng.choice([(rng.uniform(5, 80), rng.uniform(1, 12)), (rng.uniform(1, 12), rng.uniform(5, 80))])
                boxes.append(([x, y], [min(size, x + w), min(size, y + h)]))
            c = contract(boxes, size, size)
            points = []
            while len(points) < 2:
                p = (rng.uniform(R, size - R), rng.uniform(R, size - R))
                if is_standable(p, c):
                    points.append(p)
            result = plan_path(points[0], points[1], c)
            if result.waypoints is None:
                self.assertEqual(result.reason, "no_path")
                unreachable += 1
                continue
            for step in (1.0, 1.5):
                position, count, ok = walk(c, points[0], result.waypoints, step)
                self.assertTrue(ok, f"seed {seed} step {step} stuck at {position}")
                self.assertLessEqual(math.hypot(position[0] - points[1][0], position[1] - points[1][1]), 0.1)
            reached += 1
        self.assertGreater(reached, 40)   # most random fields are connected; guards against a degenerate planner


class DeterminismAndPerformanceTests(PathingTestCase):
    @staticmethod
    def big_map(seed=1, count=40):
        rng = random.Random(seed)
        boxes = []
        while len(boxes) < count:
            x, y = rng.uniform(20, 1080), rng.uniform(20, 780)
            w, h = rng.choice([(rng.uniform(8, 60), rng.uniform(4, 10)), (rng.uniform(4, 10), rng.uniform(8, 60))])
            boxes.append(([x, y], [x + w, y + h]))
        return contract(boxes, 1200, 900)

    def test_same_input_gives_the_same_path(self):
        c = contract(wall_with_door(8.0))
        first = plan_path((30, 150), (170, 40), c)
        second = plan_path((30, 150), (170, 40), contract(wall_with_door(8.0)))
        self.assertEqual(first.waypoints, second.waypoints)
        self.assertEqual(first.expansions, second.expansions)

    def test_input_contract_is_not_modified(self):
        c = contract(wall_with_door(8.0))
        before = repr(c)
        plan_path((30, 150), (170, 40), c)
        self.assertEqual(repr(c), before)

    def test_cross_map_path_with_a_few_dozen_boxes_is_fast(self):
        c = self.big_map()
        # A long wall with a door forces a real detour on top of the 40 random boxes.
        c["boxes"] += [{"min": [0, 440], "max": [560, 452]}, {"min": [640, 440], "max": [1200, 452]}]
        pairs = []
        rng = random.Random(7)
        while len(pairs) < 2:
            a, b = (rng.uniform(10, 1190), rng.uniform(10, 440 if len(pairs) == 0 else 880)), (rng.uniform(10, 1190), rng.uniform(460, 890))
            if is_standable(a, c) and is_standable(b, c):
                pairs.append((a, b))
        for a, b in pairs:
            started = time.perf_counter()
            result = plan_path(a, b, c)
            elapsed = time.perf_counter() - started
            self.assertIsNotNone(result.waypoints, result.reason)
            self.assertLess(elapsed, 1.0, f"{elapsed:.2f}s for {result.expansions} expansions")
            position, count, ok = walk(c, a, result.waypoints, 1.5)
            self.assertTrue(ok)
            self.assertLessEqual(math.hypot(position[0] - b[0], position[1] - b[1]), 0.1)

    def test_search_limit_is_reported_not_raised(self):
        c = contract([([500, 0], [512, 900])], 1200, 900)   # sealed: forces an exhaustive search
        result = plan_path((20, 20), (1180, 880), c, max_expansions=2000)
        self.assertIsNone(result.waypoints)
        self.assertEqual(result.reason, "search_limit")


class AuthoredMapTests(PathingTestCase):
    def test_example_smith_anchors_are_mutually_reachable(self):
        try:
            from world_map import load_map, to_movement_contract
        except ImportError:                               # sibling package not present
            self.skipTest("world_map is not available")
        world_map = load_map(FIXTURES / "example_smith.json")
        c = to_movement_contract(world_map, world_map.actor_radius if world_map.actor_radius is not None else R)
        anchors = [a.position for a in world_map.anchors]
        self.assertGreaterEqual(len(anchors), 2)
        for start in anchors:
            for goal in anchors:
                if start != goal:
                    with self.subTest(start=start, goal=goal):
                        self.assertWalks(c, start, goal)


if __name__ == "__main__":
    unittest.main()
