"""1008 window: the legacy 0..MAP_WIDTH x 0..MAP_HEIGHT clamps are limits only with EDEN_WINDOW off. Flag off every site clamps exactly as before;
flag on a position keeps its (negative or far) window-local value."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
import instincts_and_tools as it  # noqa: E402
from harness import limits  # noqa: E402
from runtime import common  # noqa: E402
from systems.nature import disasters  # noqa: E402


class LimitsBase(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("EDEN_WINDOW", None)

    def window(self):
        os.environ["EDEN_WINDOW"] = "1"


class WorldLimitsTests(LimitsBase):
    def test_flag_off_is_the_legacy_rectangle(self):
        self.assertEqual(limits.world_limits(), (0.0, 0.0, float(cfg.MAP_WIDTH), float(cfg.MAP_HEIGHT)))

    def test_window_has_no_limit(self):
        self.window()
        self.assertEqual(limits.world_limits(), limits.UNBOUNDED)


class SiteTests(LimitsBase):
    def humans(self, x, y):
        h = torch.zeros((2, 32), dtype=torch.float32)
        h[0, cfg.X], h[0, cfg.Y] = x, y
        return h

    def test_clamp_point(self):
        self.assertEqual(it._clamp_point(-5.0, 5000.0), (0.0, float(cfg.MAP_HEIGHT)))
        self.window()
        self.assertEqual(it._clamp_point(-5.0, 5000.0), (-5.0, 5000.0))

    def test_move_toward_and_away(self):
        for fn, sign in ((common.move_toward, 1.0), (common.move_away, -1.0)):
            os.environ.pop("EDEN_WINDOW", None)
            h = self.humans(float(cfg.MAP_WIDTH) - 1.0, 1.0)
            fn(h, 0, h[0, cfg.X].item() + 100.0, 1.0, 10.0)           # toward: east past the edge; away: west past it
            self.assertGreaterEqual(float(h[0, cfg.X]), 0.0)
            self.assertLessEqual(float(h[0, cfg.X]), float(cfg.MAP_WIDTH))
            self.window()
            h = self.humans(float(cfg.MAP_WIDTH) - 1.0, 1.0)
            fn(h, 0, h[0, cfg.X].item() + 100.0, 1.0, 10.0)
            self.assertAlmostEqual(float(h[0, cfg.X]), float(cfg.MAP_WIDTH) - 1.0 + 10.0 * sign, places=3)
        os.environ.pop("EDEN_WINDOW", None)
        h = self.humans(2.0, 2.0)
        common.move_away(h, 0, 100.0, 2.0, 10.0)
        self.assertEqual(float(h[0, cfg.X]), 0.0)                       # legacy: pinned at the west edge
        self.window()
        h = self.humans(2.0, 2.0)
        common.move_away(h, 0, 100.0, 2.0, 10.0)
        self.assertAlmostEqual(float(h[0, cfg.X]), -8.0, places=4)      # window: the far side of the origin is just negative coordinates

    def test_migration_push(self):
        ctx = {"h_mask": torch.tensor([True, False])}
        mask = torch.tensor([True, True])
        for on in (False, True):
            os.environ.pop("EDEN_WINDOW", None)
            if on:
                self.window()
            h = self.humans(3.0, 3.0)
            it.tool_migration(ctx, h, mask, -500.0, 3.0, force=10.0)
            self.assertEqual(float(h[0, cfg.X]), -7.0 if on else 0.0)

    def test_storm_displacement(self):
        ctx = {"h_mask": torch.tensor([True, False])}
        for on in (False, True):
            os.environ.pop("EDEN_WINDOW", None)
            if on:
                self.window()
            torch.manual_seed(1)
            h = self.humans(1.0, 1.0)
            h[0, cfg.X] = -100.0
            disasters.apply_storm(ctx, h, center_x=0.0, center_y=0.0, radius=10000.0,
                                  agent_radial_mask_fn=lambda *_: torch.tensor([True, False]))
            self.assertEqual(float(h[0, cfg.X]) >= 0.0, not on)


if __name__ == "__main__":
    unittest.main()
