"""World facade, SpaceFrame and the World-owned spatial index, on tiny synthetic worlds (no legacy engine)."""
import math
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness.frame import AbsPos, SpaceFrame  # noqa: E402
from harness.spatial_index import SpatialIndex  # noqa: E402
from harness.world import World  # noqa: E402


class SpaceFrameTests(unittest.TestCase):
    def test_round_trip_is_exact_for_float32_values_far_from_origin(self):
        frame = SpaceFrame(256.0, origin=(1000, -2000))
        for x, y in ((0.0, 0.0), (255.99, 0.01), (-0.5, -300.25), (123456.0, -98765.5), (3.0e7, 1.0e-3)):
            x32, y32 = float(torch.tensor(x, dtype=torch.float32)), float(torch.tensor(y, dtype=torch.float32))
            back = frame.to_local(frame.to_absolute(x32, y32))
            self.assertEqual(back, (x32, y32))

    def test_absolute_has_offset_inside_chunk(self):
        frame = SpaceFrame(256.0)
        p = frame.to_absolute(-1.0, 513.0)
        self.assertEqual((p.chunk_x, p.chunk_y), (-1, 2))
        self.assertTrue(0 <= p.x < 256 and 0 <= p.y < 256)
        self.assertEqual(frame.chunk_of(-1.0, 513.0), (-1, 2))

    def test_rebase_keeps_absolute_positions_and_small_numbers(self):
        frame = SpaceFrame(256.0)
        pos = torch.tensor([[2_000_000.5, 3_000_000.25], [2_000_100.0, 3_000_050.0]], dtype=torch.float32)
        before = [frame.to_absolute(*map(float, row)) for row in pos]
        new_origin = frame.chunk_of(2_000_000.5, 3_000_000.25)
        shift = frame.rebase(new_origin, pos)
        self.assertEqual(shift, (-new_origin[0] * 256.0, -new_origin[1] * 256.0))
        self.assertLess(float(pos.abs().max()), 1000.0)  # numbers are small again
        after = [frame.to_absolute(*map(float, row)) for row in pos]
        for b, a in zip(before, after):
            self.assertEqual(b.chunk(), a.chunk())
            self.assertAlmostEqual(b.x, a.x, places=3)
            self.assertAlmostEqual(b.y, a.y, places=3)

    def test_bounds_clamp_centre_and_unbounded(self):
        finite = SpaceFrame(bounds=(0, 0, 1200, 900))
        self.assertEqual(finite.clamp(-5, 2000), (0, 900))
        self.assertEqual(finite.centre(), (600.0, 450.0))
        open_world = SpaceFrame()
        self.assertEqual(open_world.clamp(-5e6, 5e6), (-5e6, 5e6))
        self.assertIsNone(open_world.centre())
        with self.assertRaises(ValueError):
            SpaceFrame(bounds=(10, 0, 5, 9))
        with self.assertRaises(ValueError):
            SpaceFrame(0)

    def test_rebase_moves_finite_bounds_with_the_origin(self):
        frame = SpaceFrame(256.0, bounds=(0, 0, 1200, 900))
        frame.rebase((1, 1))
        self.assertEqual(frame.bounds, (-256.0, -256.0, 944.0, 644.0))


class SpatialIndexTests(unittest.TestCase):
    def test_radius_queries_are_exact_and_ordered(self):
        frame, index = SpaceFrame(256.0), SpatialIndex(256.0)
        for name, x, y in (("b", 10, 10), ("a", 13, 14), ("c", 300, 10), ("d", 10, 16.01)):
            index.insert_local(frame, name, x, y)
        centre = frame.to_absolute(10, 10)
        self.assertEqual(index.query_radius(0, centre, 5.0), ["a", "b"])  # a is exactly 5.0 away (inclusive); d is 6.01
        self.assertEqual(index.query_radius(0, centre, 5.0, exclude=["b"]), ["a"])
        self.assertEqual(index.query_radius(0, centre, 400.0), ["a", "b", "c", "d"])  # spans chunks
        self.assertEqual(index.nearest(0, centre, 100.0, exclude=["b"]), "a")

    def test_exact_at_a_huge_offset_where_float32_cdist_is_not(self):
        index = SpatialIndex(256.0)
        base = 5_000_000
        index.insert("p", 0, AbsPos(base // 256, 0, 10.0, 10.0))
        index.insert("q", 0, AbsPos(base // 256, 0, 14.0, 13.0))  # 5.0 away
        index.insert("r", 0, AbsPos(base // 256, 0, 15.0, 13.0))  # 5.83 away
        self.assertEqual(index.query_radius(0, AbsPos(base // 256, 0, 10.0, 10.0), 5.0), ["p", "q"])

    def test_spaces_are_separate_and_chunk_removal(self):
        index = SpatialIndex(256.0)
        index.insert("x", 0, AbsPos(0, 0, 1.0, 1.0))
        index.insert("y", 1, AbsPos(0, 0, 1.0, 1.0))
        self.assertEqual(index.query_radius(0, AbsPos(0, 0, 1.0, 1.0), 10), ["x"])
        self.assertEqual(index.query_radius(1, AbsPos(0, 0, 1.0, 1.0), 10), ["y"])
        self.assertEqual(index.remove_chunk(0, (0, 0)), ["x"])
        self.assertNotIn("x", index)
        self.assertIn("y", index)
        self.assertFalse(index.remove("x"))

    def test_move_updates_buckets(self):
        index = SpatialIndex(256.0)
        index.insert("m", 0, AbsPos(0, 0, 1.0, 1.0))
        index.move("m", AbsPos(5, 5, 1.0, 1.0))
        self.assertEqual(index.ids_in_chunk(0, (0, 0)), [])
        self.assertEqual(index.ids_in_chunk(0, (5, 5)), ["m"])
        self.assertEqual(index.chunks(0), [(0, 5, 5)])


class WorldTests(unittest.TestCase):
    def test_two_worlds_in_one_process_are_independent(self):
        a, b = World.synthetic(seed=1), World.synthetic(seed=1)
        a.add_row("humans", x=1, y=1, hp=50)
        self.assertEqual(a.observe_counts()["humans"], 1)
        self.assertEqual(b.observe_counts()["humans"], 0)
        self.assertEqual(a.rng("s", "h_000001").random(), b.rng("s", "h_000001").random())  # same seed, same stream
        self.assertNotEqual(World.synthetic(seed=2).rng("s", "h_000001").random(), a.rng("s", "h_000001").random())

    def test_bounds_centre_clamp_follow_the_frame(self):
        from harness.frame import SpaceFrame
        finite = World.synthetic(frame=SpaceFrame(bounds=(0, 0, 1200, 900)))
        self.assertEqual((finite.bounds(), finite.centre(), finite.clamp(-3, 5000)), ((0.0, 0.0, 1200.0, 900.0), (600.0, 450.0), (0.0, 900.0)))
        open_world = World.synthetic(view_centre=(5000.0, -20.0))
        self.assertIsNone(open_world.bounds())
        self.assertEqual((open_world.centre(), open_world.clamp(-9e9, 9e9)), ((5000.0, -20.0), (-9e9, 9e9)))

    def test_clock_rng_ties_to_tick(self):
        w = World.synthetic(seed=3)
        first = w.rng("sys", 1).random()
        w.clock.advance()
        self.assertNotEqual(first, w.rng("sys", 1).random())
        self.assertEqual(w.tick, 1)

    def test_within_uses_the_index_and_ids(self):
        w = World.synthetic()
        near = w.add_row("humans", x=10, y=10)
        far = w.add_row("humans", x=900, y=10)
        w.add_row("entities", x=11, y=10)
        self.assertEqual(w.within("humans", 10, 10, 20), [near])
        self.assertEqual(w.within("humans", 900, 10, 20), [far])

    def test_unknown_table_and_field_are_reported(self):
        w = World.synthetic()
        with self.assertRaises(KeyError):
            w.table("nope")
        with self.assertRaises(KeyError):
            w.table("humans").col("nope")

    def test_revision_listener(self):
        w = World.synthetic()
        seen = []
        w.on_revision(seen.append)
        w.bump_revision()
        w.bump_revision()
        self.assertEqual((seen, w.revision), ([1, 2], 2))


if __name__ == "__main__":
    unittest.main()
