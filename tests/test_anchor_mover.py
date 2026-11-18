"""AnchorMover (P3.2) with the real spatial.slide and pathing.plan_path."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from systems.movement.anchor_mover import ANCHOR_TOLERANCE, MAX_REPLANS, NO_PATH_TTL_TICKS, STALL_TICKS, AnchorMover
from systems.movement.pathing import PathResult, plan_path
from systems.movement.spatial import is_standable_point

R = 2.4


def box(i, x0, y0, x1, y1):
    return {"id": f"b{i}", "min": [x0, y0], "max": [x1, y1]}


def room(gap, bounds=(0.0, 0.0, 120.0, 80.0), extra=()):
    """A vertical wall at x 58..62 with a centred door of ``gap`` units; west and east halves."""
    mid = 40.0
    boxes = [box(0, 58, 0, 62, mid - gap / 2), box(1, 58, mid + gap / 2, 62, 80), *extra]
    return {"version": 1, "revision": f"r{len(boxes)}", "actor_radius": R, "bounds": list(bounds), "boxes": boxes}


def walk(mover, contract, start, goal, max_ticks=600, key="npc"):
    """Run the mover until it arrives; return (trail, ticks). Asserts the per-tick invariants on the way."""
    position, trail = start, [start]
    for tick in range(max_ticks):
        result = mover.step(key, position, goal, contract, tick)
        assert result.moved <= mover.step_len + 1e-9, f"moved {result.moved} > step {mover.step_len}"
        assert is_standable_point(result.position, contract), f"embedded at {result.position}"
        assert math.hypot(result.position[0] - position[0], result.position[1] - position[1]) <= mover.step_len + 1e-9
        position = result.position
        trail.append(position)
        if result.arrived:
            return trail, tick + 1
        if result.blocked:
            return trail, -1
    return trail, -2


class WalkTests(unittest.TestCase):
    def test_straight_walk_arrives_within_tolerance_one_unit_per_tick(self):
        trail, ticks = walk(AnchorMover(), room(8.0), (10.0, 10.0), (40.0, 10.0))
        self.assertGreater(ticks, 0)
        self.assertLessEqual(math.hypot(trail[-1][0] - 40.0, trail[-1][1] - 10.0), ANCHOR_TOLERANCE)
        self.assertAlmostEqual(ticks, 30 - ANCHOR_TOLERANCE, delta=2)

    def test_walks_through_one_tile_and_ten_unit_doors_without_a_teleport(self):
        for gap in (8.0, 10.0, 16.0):
            with self.subTest(gap=gap):
                contract = room(gap)
                trail, ticks = walk(AnchorMover(), contract, (20.0, 12.0), (100.0, 70.0))
                self.assertGreater(ticks, 0, f"did not arrive through a {gap}-unit door")
                self.assertTrue(any(p[0] > 62 for p in trail))
                self.assertTrue(all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1.0 + 1e-9 for a, b in zip(trail, trail[1:])))
                crossing = [p for p in trail if 56 < p[0] < 64]
                self.assertTrue(all(40 - gap / 2 + R - 0.01 <= p[1] <= 40 + gap / 2 - R + 0.01 for p in crossing))  # inside the door band

    def test_sprint_step_length_and_a_custom_step(self):
        mover = AnchorMover(step_len=1.5)
        trail, ticks = walk(mover, room(10.0), (20.0, 12.0), (100.0, 70.0))
        self.assertGreater(ticks, 0)
        self.assertTrue(all(math.hypot(a[0] - b[0], a[1] - b[1]) <= 1.5 + 1e-9 for a, b in zip(trail, trail[1:])))
        with self.assertRaises(ValueError):
            AnchorMover(step_len=0)

    def test_already_there_is_arrival_without_planning(self):
        mover = AnchorMover()
        result = mover.step("npc", (10.0, 10.0), (11.0, 10.5), room(8.0))
        self.assertTrue(result.arrived)
        self.assertEqual((result.position, mover.plan_calls), ((10.0, 10.0), 0))

    def test_a_goal_inside_a_wall_is_reported_not_walked_into(self):
        mover = AnchorMover()
        result = mover.step("npc", (10.0, 10.0), (60.0, 20.0), room(8.0))  # inside the wall box
        self.assertEqual((result.blocked, result.position), ("goal_not_standable", (10.0, 10.0)))


class PlanningTests(unittest.TestCase):
    def test_no_path_is_cached_until_the_ttl_or_the_contract_changes(self):
        sealed = room(2.0)  # a 2-unit door is narrower than the actor: no route
        mover = AnchorMover()
        first = mover.step("npc", (10.0, 10.0), (100.0, 10.0), sealed, tick=0)
        self.assertEqual((first.blocked, mover.plan_calls), ("no_path", 1))
        for tick in range(1, 20):
            self.assertEqual(mover.step("npc", (10.0, 10.0), (100.0, 10.0), sealed, tick=tick).blocked, "no_path")
        self.assertEqual(mover.plan_calls, 1)  # cached
        mover.step("npc", (10.0, 10.0), (100.0, 10.0), sealed, tick=NO_PATH_TTL_TICKS + 1)
        self.assertEqual(mover.plan_calls, 2)  # expired
        opened = room(10.0)
        opened["revision"] = "opened"
        self.assertEqual(mover.step("npc", (10.0, 10.0), (100.0, 10.0), opened, tick=NO_PATH_TTL_TICKS + 2).blocked, "")
        self.assertEqual(mover.plan_calls, 3)  # the contract revision changed: asked again immediately

    def test_replans_when_the_contract_revision_changes_mid_walk(self):
        contract = room(10.0)
        mover = AnchorMover()
        position, replans, blocked = (20.0, 12.0), 0, ""
        for tick in range(400):
            if tick == 20:  # a new wall appears across the door
                contract = {**contract, "revision": "walled", "boxes": contract["boxes"] + [box(9, 58, 35, 62, 45)]}
            result = mover.step("npc", position, (100.0, 70.0), contract, tick)
            replans += result.replanned
            position, blocked = result.position, result.blocked
            self.assertTrue(is_standable_point(position, contract))
            if result.arrived or result.blocked:
                break
        self.assertGreaterEqual(replans, 2)  # the first plan plus the one after the revision changed
        self.assertEqual(blocked, "no_path")  # the door is now closed: reported, not walked into the wall
        self.assertLess(position[0], 58 - R + 0.01)

    def test_a_new_goal_replans(self):
        contract = room(10.0)
        mover = AnchorMover()
        position = (10.0, 10.0)
        for tick in range(10):
            position = mover.step("npc", position, (100.0, 10.0), contract, tick).position
        calls = mover.plan_calls
        mover.step("npc", position, (10.0, 70.0), contract, 11)
        self.assertEqual(mover.plan_calls, calls + 1)

    def test_a_stale_plan_with_the_same_revision_stalls_then_replans(self):
        contract = room(10.0)
        mover = AnchorMover()
        position = (20.0, 38.0)
        mover.step("npc", position, (100.0, 40.0), contract, 0)
        # An invisible obstacle the revision does not reflect: the walker stops making progress
        blocked = {**contract, "boxes": contract["boxes"] + [box(9, 40, 20, 44, 60)]}
        blocked["revision"] = contract["revision"]  # same revision string: the mover cannot know
        calls = mover.plan_calls
        results = [mover.step("npc", position, (100.0, 40.0), blocked, tick) for tick in range(1, 80)]
        position = results[-1].position
        self.assertGreater(mover.plan_calls, calls)  # stalled long enough to re-plan on its own
        self.assertTrue(is_standable_point(position, blocked))

    def test_stuck_is_reported_after_repeated_replans_without_progress(self):
        contract = room(10.0)

        def liar(start, goal, contract_):
            return PathResult([goal])  # claims a straight line through the wall every time
        mover = AnchorMover(planner=liar)
        position, blocked = (20.0, 12.0), ""
        for tick in range(STALL_TICKS * (MAX_REPLANS + 3) + 50):
            result = mover.step("npc", position, (100.0, 12.0), contract, tick)
            position, blocked = result.position, result.blocked
            if blocked:
                break
        self.assertEqual(blocked, "stuck")
        self.assertTrue(is_standable_point(position, contract))

    def test_an_embedded_start_is_stood_up_first(self):
        contract = room(10.0)
        mover = AnchorMover()
        embedded = (60.0, 20.0)  # inside the wall box
        result = mover.step("npc", embedded, (100.0, 20.0), contract, 0)
        self.assertTrue(is_standable_point(result.position, contract))
        self.assertNotEqual(result.position, embedded)
        self.assertTrue(result.replanned)
        trail, ticks = walk(mover, contract, result.position, (100.0, 20.0))
        self.assertGreater(ticks, 0)

    def test_keys_are_independent_and_forget_clears_them(self):
        contract = room(10.0)
        mover = AnchorMover()
        a = mover.step("a", (10.0, 10.0), (100.0, 10.0), contract, 0)
        b = mover.step("b", (10.0, 70.0), (100.0, 70.0), contract, 0)
        self.assertEqual(sorted(mover.plans), ["a", "b"])
        mover.forget("a")
        self.assertEqual(sorted(mover.plans), ["b"])
        self.assertIsNotNone(a.position)
        self.assertIsNotNone(b.position)

    def test_per_tick_displacement_never_exceeds_the_step_over_a_long_route(self):
        contract = room(8.0, extra=(box(5, 20, 20, 40, 30), box(6, 80, 50, 100, 60)))
        trail, ticks = walk(AnchorMover(), contract, (8.0, 8.0), (110.0, 72.0), max_ticks=800)
        self.assertGreater(ticks, 0)


if __name__ == "__main__":
    unittest.main()
