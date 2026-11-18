"""pairwise_distances must stay exact at large offsets where torch.cdist's matmul path is not (G-D0-1)."""
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness.numerics import pairwise_distances  # noqa: E402


def reference(a, b):
    return torch.cdist(a.double(), b.double(), compute_mode="donot_use_mm_for_euclid_dist")


class PairwiseDistanceTests(unittest.TestCase):
    def test_error_is_below_1e4_at_every_offset_and_shape(self):
        torch.manual_seed(7)
        for offset in (0.0, 1e3, 1e5):
            for rows_a, rows_b in ((100, 100), (1024, 1), (26, 25), (25, 26), (1024, 100)):
                a = (torch.rand(rows_a, 2, dtype=torch.float64) * 40 + offset).float()
                b = (torch.rand(rows_b, 2, dtype=torch.float64) * 40 + offset).float()
                error = (pairwise_distances(a, b).double() - reference(a, b)).abs().max().item()
                self.assertLess(error, 1e-4, f"offset {offset} shape {rows_a}x{rows_b}: {error}")

    def test_plain_cdist_is_not_good_enough_at_offset_1e3(self):
        torch.manual_seed(7)
        a, b = torch.rand(100, 2) * 40 + 1000, torch.rand(100, 2) * 40 + 1000
        self.assertGreater((torch.cdist(a, b).double() - reference(a, b)).abs().max().item(), 1e-3)

    def test_matches_cdist_for_small_inputs_and_keeps_shape_dtype(self):
        a, b = torch.rand(5, 2), torch.rand(3, 2)
        out = pairwise_distances(a, b)
        self.assertEqual((out.shape, out.dtype), ((5, 3), torch.float32))
        self.assertTrue(torch.allclose(out, torch.cdist(a, b), atol=1e-6))

    def test_empty_operands(self):
        self.assertEqual(tuple(pairwise_distances(torch.zeros(0, 2), torch.zeros(4, 2)).shape), (0, 4))


if __name__ == "__main__":
    unittest.main()
