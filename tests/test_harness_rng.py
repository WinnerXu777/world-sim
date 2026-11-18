"""Counter-based RNG streams: pure functions of (seed, tick, system, entity), independent of call order and population."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from harness.rng import hash_for_ids, normal_for_ids, rng, uniform_for_ids  # noqa: E402


class StreamTests(unittest.TestCase):
    def test_same_coordinates_same_numbers(self):
        a, b = rng(7, 100, "hunger", "h_000001"), rng(7, 100, "hunger", "h_000001")
        self.assertEqual([a.random() for _ in range(5)], [b.random() for _ in range(5)])

    def test_each_coordinate_changes_the_stream(self):
        base = rng(7, 100, "hunger", "h_000001").random()
        for other in (rng(8, 100, "hunger", "h_000001"), rng(7, 101, "hunger", "h_000001"), rng(7, 100, "thirst", "h_000001"),
                      rng(7, 100, "hunger", "h_000002")):
            self.assertNotEqual(base, other.random())

    def test_call_order_and_population_do_not_matter(self):
        alone = rng(1, 5, "move", "h_000003").uniform(0, 1)
        for other in ("h_000001", "h_000002", "h_000009"):  # drawing for other entities first changes nothing
            rng(1, 5, "move", other).random()
        self.assertEqual(alone, rng(1, 5, "move", "h_000003").uniform(0, 1))

    def test_distribution_helpers(self):
        s = rng(3, 0, "t", 0)
        values = [s.uniform(10, 20) for _ in range(500)]
        self.assertTrue(all(10 <= v < 20 for v in values))
        ints = {rng(3, i, "t", 0).randint(1, 3) for i in range(60)}
        self.assertEqual(ints, {1, 2, 3})  # inclusive on both ends
        self.assertEqual(sorted(rng(3, 0, "t", 1).shuffle(list(range(10)))), list(range(10)))
        self.assertIn(rng(3, 0, "t", 2).choice(["a", "b", "c"]), "abc")
        with self.assertRaises(IndexError):
            rng(3, 0, "t", 2).choice([])

    def test_stable_across_processes(self):
        """blake2b keys, not Python's randomised hash(): a fresh interpreter must give the same first number."""
        code = ("import sys; sys.path.insert(0, r'%s'); from harness.rng import rng; print(repr(rng(7, 100, 'hunger', 'h_000001').random()))"
                % (ROOT / "at_the_beginning"))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env={**os.environ, "PYTHONHASHSEED": "random"})
        self.assertEqual(float(out.stdout.strip()), rng(7, 100, "hunger", "h_000001").random(), out.stderr)


class VectorisedTests(unittest.TestCase):
    def test_element_depends_only_on_its_own_id(self):
        ids = list(range(100))
        full = uniform_for_ids(9, 50, "heal", ids)
        sub = uniform_for_ids(9, 50, "heal", [3, 77])
        self.assertEqual(sub[0], full[3])
        self.assertEqual(sub[1], full[77])
        reordered = uniform_for_ids(9, 50, "heal", ids[::-1])
        self.assertTrue(np.array_equal(reordered[::-1], full))

    def test_uniform_range_and_rough_uniformity(self):
        u = uniform_for_ids(1, 1, "s", np.arange(20000, dtype=np.uint64))
        self.assertTrue(((u >= 0) & (u < 1)).all())
        self.assertAlmostEqual(float(u.mean()), 0.5, delta=0.01)
        hist, _ = np.histogram(u, bins=10, range=(0, 1))
        self.assertTrue((hist > 1700).all() and (hist < 2300).all(), hist)

    def test_tick_system_and_salt_decorrelate(self):
        ids = np.arange(2000, dtype=np.uint64)
        a = uniform_for_ids(1, 1, "s", ids)
        for b in (uniform_for_ids(1, 2, "s", ids), uniform_for_ids(1, 1, "t", ids), uniform_for_ids(1, 1, "s", ids, salt=1)):
            self.assertLess(abs(float(np.corrcoef(a, b)[0, 1])), 0.1)

    def test_normals_and_string_ids(self):
        z = normal_for_ids(2, 3, "n", np.arange(20000, dtype=np.uint64))
        self.assertAlmostEqual(float(z.mean()), 0.0, delta=0.03)
        self.assertAlmostEqual(float(z.std()), 1.0, delta=0.03)
        a = hash_for_ids(2, 3, "n", ["h_000001", "h_000002"])
        self.assertNotEqual(int(a[0]), int(a[1]))
        self.assertEqual(int(hash_for_ids(2, 3, "n", ["h_000002"])[0]), int(a[1]))


if __name__ == "__main__":
    unittest.main()
