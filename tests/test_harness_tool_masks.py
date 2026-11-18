"""tool_enlighten, tool_baby_boom and tool_reset_cooldown used `if mask` on an optional tensor mask, which raises for any tensor
with more than one element; they now test `mask is not None`. A narrowing mask must restrict the effect, and no mask means everyone."""
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
from harness import instinct_bits as ib  # noqa: E402


def humans(n=4):
    h = torch.zeros((16, cfg.HUMAN_TENSOR_COLS))
    h[:n, cfg.TYPE] = cfg.AGENT_TYPE_HUMAN
    h[:n, cfg.HP] = 100.0
    h[:n, cfg.H_COOLDOWN] = 50.0
    h[:n, cfg.H_SEX] = 1.0
    return h


def ctx_for(h):
    return {"h_mask": h[:, cfg.TYPE] > 0}


FIRST_TWO = torch.tensor([True, True] + [False] * 14)


class TensorMaskTests(unittest.TestCase):
    def test_reset_cooldown_with_a_tensor_mask_only_touches_the_masked_rows(self):
        h = humans()
        iat.tool_reset_cooldown(ctx_for(h), h, mask=FIRST_TWO)
        self.assertEqual(h[:4, cfg.H_COOLDOWN].tolist(), [0.0, 0.0, 50.0, 50.0])

    def test_reset_cooldown_without_a_mask_touches_everyone(self):
        h = humans()
        iat.tool_reset_cooldown(ctx_for(h), h)
        self.assertEqual(h[:4, cfg.H_COOLDOWN].tolist(), [0.0] * 4)

    def test_enlighten_with_a_tensor_mask_grants_only_the_masked_rows(self):
        h = humans()
        iat.tool_enlighten(ctx_for(h), h, 40, mask=FIRST_TWO)
        self.assertEqual([ib.bits_of(int(ib.read_mask(h, i))) for i in range(4)], [[40], [40], [], []])

    def test_baby_boom_with_a_tensor_mask_only_resets_masked_females(self):
        h = humans()
        iat.tool_baby_boom(ctx_for(h), h, [0], mask=FIRST_TWO)
        self.assertEqual(h[:4, cfg.H_COOLDOWN].tolist(), [0.0, 0.0, 50.0, 50.0])


if __name__ == "__main__":
    unittest.main()
