"""clamp_rows_ clamps what ``t[mask, col].clamp_`` silently does not (KNOWN_BUG_G_D0_3 / audit G-D0-4)."""
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness.clamp import clamp_rows_  # noqa: E402


def sample():
    t = torch.tensor([[1.0, 150.0], [2.0, -20.0], [3.0, 50.0], [4.0, 130.0]])
    return t


class ClampRowsTests(unittest.TestCase):
    def test_bool_mask_clamps_only_selected_rows(self):
        t = sample()
        clamp_rows_(t, torch.tensor([True, True, False, False]), 1, 0.0, 100.0)
        self.assertEqual(t[:, 1].tolist(), [100.0, 0.0, 50.0, 130.0])      # row 3 not selected: untouched

    def test_the_legacy_idiom_really_is_a_no_op(self):
        t = sample()
        t[torch.tensor([True, True, False, False]), 1].clamp_(0.0, 100.0)
        self.assertEqual(t[:, 1].tolist(), [150.0, -20.0, 50.0, 130.0])

    def test_index_tensor_int_slice_and_open_ends(self):
        t = sample()
        clamp_rows_(t, torch.tensor([3]), 1, hi=100.0)
        self.assertEqual(t[3, 1].item(), 100.0)
        clamp_rows_(t, 1, 1, lo=0.0)
        self.assertEqual(t[1, 1].item(), 0.0)
        clamp_rows_(t, slice(0, 2), 1, hi=10.0)
        self.assertEqual(t[:2, 1].tolist(), [10.0, 0.0])
        before = t.clone()
        clamp_rows_(t, torch.ones(4, dtype=torch.bool), 1)                  # no bounds: nothing changes
        self.assertTrue(torch.equal(t, before))

    def test_empty_selection_dtype_and_views(self):
        t = sample()
        clamp_rows_(t, torch.zeros(4, dtype=torch.bool), 1, 0.0, 1.0)
        self.assertEqual(t[:, 1].tolist(), [150.0, -20.0, 50.0, 130.0])
        self.assertEqual(clamp_rows_(t, torch.ones(4, dtype=torch.bool), 0, 0.0, 2.5).dtype, torch.float32)
        big = torch.tensor([[0.0, 500.0]] * 6)
        clamp_rows_(big[:4], torch.tensor([True, False, True, False]), 1, hi=100.0)   # the m_tensor[:n][mask, col] shape
        self.assertEqual(big[:, 1].tolist(), [100.0, 500.0, 100.0, 500.0, 500.0, 500.0])

    def test_nan_is_left_alone_and_values_inside_are_bit_identical(self):
        t = torch.tensor([[float("nan")], [0.1], [99.9]])
        clamp_rows_(t, torch.ones(3, dtype=torch.bool), 0, 0.0, 100.0)
        self.assertTrue(torch.isnan(t[0, 0]))
        self.assertEqual(t[1:, 0].tolist(), torch.tensor([0.1, 99.9]).tolist())


if __name__ == "__main__":
    unittest.main()
