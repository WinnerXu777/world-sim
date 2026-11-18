"""Characterization of KNOWN BUGS in the legacy engine (1008 D0 audit). Each test documents CURRENT, WRONG behaviour so a
later fix flips it deliberately: when you fix the bug, change the assertion and rename the test, in the same commit.
"""
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from harness.numerics import pairwise_distances  # noqa: E402
import instincts_and_tools as iat  # noqa: E402


def bits(value):
    return [b for b in range(64) if (int(value) >> b) & 1]


class FixedGD02AcquiredInstinctMask(unittest.TestCase):
    """G-D0-2 (FIXED, option A'): the 64-bit mask used to live in one float32 column, so bits were lost once a high bit was
    granted. It is now three exact 24-bit words (harness/instinct_bits.py); tests/test_harness_gd02_legacy.py covers every site."""

    def grant(self, h, bit):
        ctx = {"h_mask": torch.ones(h.shape[0], dtype=torch.bool)}
        iat.tool_grant_instinct(ctx, h, torch.ones(h.shape[0], dtype=torch.bool), bit)

    def test_FixedGD02_low_bit_survives_high_bit_grants(self):
        from harness import instinct_bits as ib
        h = torch.zeros((2, cfg.HUMAN_TENSOR_COLS))
        h[:, cfg.TYPE] = cfg.AGENT_TYPE_HUMAN
        self.grant(h, 3)
        self.assertEqual(bits(h[0, cfg.ACQUIRED_INSTINCT_MASK].long()), [3])
        self.grant(h, 30)
        self.grant(h, 40)
        self.assertEqual(ib.bits_of(int(ib.read_mask(h, 0))), [3, 30, 40])      # before the fix: [30, 40]
        self.assertEqual(bits(h[0, cfg.ACQUIRED_INSTINCT_MASK].long()), [3])    # the legacy column holds only bits 0..23

    def test_grants_inside_one_24_bit_window_are_safe(self):
        h = torch.zeros((1, cfg.HUMAN_TENSOR_COLS))
        h[:, cfg.TYPE] = cfg.AGENT_TYPE_HUMAN
        for bit in (0, 5, 17, 23):
            self.grant(h, bit)
        self.assertEqual(bits(h[0, cfg.ACQUIRED_INSTINCT_MASK].long()), [0, 5, 17, 23])


class FixedGD01CdistMatmulPath(unittest.TestCase):
    """G-D0-1 (FIXED in the cdist-swap commit): torch.cdist switches to a lossy matmul formulation above 25 rows. The legacy
    code now calls ``harness.numerics.pairwise_distances`` at all 11 sites; this class keeps the reason and guards the fix."""

    def test_torch_default_cdist_is_still_inexact_above_25_rows_which_is_why_the_helper_exists(self):
        torch.manual_seed(1)
        a, b = torch.rand(26, 2) * 40 + 1000, torch.rand(25, 2) * 40 + 1000
        exact = torch.cdist(a.double(), b.double(), compute_mode="donot_use_mm_for_euclid_dist").float()
        self.assertGreater((torch.cdist(a, b) - exact).abs().max().item(), 1e-3)  # torch's default is lossy
        self.assertLess((pairwise_distances(a, b) - exact).abs().max().item(), 1e-4)  # the helper is not
        small = torch.cdist(a[:25], b)
        self.assertLess((small - exact[:25]).abs().max().item(), 1e-4)  # 25 x 25 takes the exact path

    def test_no_legacy_source_calls_torch_cdist_directly(self):
        root = Path(__file__).resolve().parents[1] / "at_the_beginning"
        offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                     if "harness" not in p.relative_to(root).parts and "torch.cdist(" in p.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [], "use harness.numerics.pairwise_distances (exact above 25 rows)")


class FixedGD03MaskClamp(unittest.TestCase):
    """G-D0-3 / audit G-D0-4 (FIXED in the dead-clamp commit): ``t[bool_or_index_tensor, col].clamp_(...)`` clamped a COPY, so 30
    legacy clamp sites did nothing. They now call ``harness.clamp.clamp_rows_``. The two sites that index with an integer
    (``resolver.py`` hunter_slot, ``thirst.py`` slot) always worked and were left alone."""

    def humans(self, rows=3):
        h = torch.zeros((rows, cfg.HUMAN_TENSOR_COLS))
        h[:, cfg.TYPE] = cfg.AGENT_TYPE_HUMAN
        return h

    def test_set_mood_clamps_to_0_100(self):
        h = self.humans()
        mask = torch.ones(3, dtype=torch.bool)
        iat.tool_set_mood({"h_mask": mask}, h, mask, 150.0)
        self.assertEqual(h[:, cfg.MOOD].tolist(), [100.0, 100.0, 100.0])      # was 150 before the fix
        iat.tool_set_mood({"h_mask": mask}, h, mask, -30.0)
        self.assertEqual(h[:, cfg.MOOD].tolist(), [0.0, 0.0, 0.0])

    def test_plague_infection_is_capped_at_100(self):
        from systems.health.effects import apply_plague_effect
        h = self.humans(1)
        h[0, cfg.HP] = 100.0
        h[0, cfg.H_INFECTION] = 90.0
        h[0, cfg.THREAT] = 95.0
        h[0, cfg.MOOD] = 10.0
        apply_plague_effect(torch.ones(1, dtype=torch.bool), h)
        self.assertEqual((float(h[0, cfg.H_INFECTION]), float(h[0, cfg.THREAT]), float(h[0, cfg.MOOD])), (100.0, 100.0, 0.0))  # was 120, 110, -10

    def test_human_cooldown_decays_to_zero_and_stays_there(self):
        h = self.humans(2)
        h[0, cfg.H_COOLDOWN] = 0.001
        mask = torch.ones(2, dtype=torch.bool)
        for _ in range(5):
            iat.instinct_cooldown({"h_mask": mask}, h)
        self.assertEqual(h[:, cfg.H_COOLDOWN].tolist(), [0.0, 0.0])           # was drifting to -6 per 3600 ticks

    def test_a_working_clamp_at_an_integer_index_is_unchanged(self):
        h = self.humans(1)
        h[0, cfg.MOOD] = 150.0
        h[0, cfg.MOOD].clamp_(max=100.0)
        self.assertEqual(float(h[0, cfg.MOOD]), 100.0)

    def test_no_dead_mask_clamp_idiom_remains_in_the_legacy_sources(self):
        import re
        root = Path(__file__).resolve().parents[1] / "at_the_beginning"
        pattern = re.compile(r"\[[^\]]*(mask|affected|selected|infected|females|isolated|spreads_to|idx|irrigated|storm_agents|not_fire)[^\]]*,[^\]]*\]\.clamp_\(")
        hits = [f"{p.relative_to(root)}:{n}" for p in root.rglob("*.py") if "harness" not in p.relative_to(root).parts
                for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
        self.assertEqual(hits, [], "use harness.clamp.clamp_rows_ (t[mask, col].clamp_ clamps a copy and does nothing)")


if __name__ == "__main__":
    unittest.main()
