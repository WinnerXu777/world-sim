"""1008 calendar C3: the consumers of the light curve. Light-driven perception radius first: 1.0 flag off, a continuous factor in
[PERCEPTION_DARK_FRACTION, 1] flag on."""
import math
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness import calendar as cal  # noqa: E402
from runtime import human_runtime  # noqa: E402


class PerceptionScaleTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("EDEN_CALENDAR", None)

    def test_flag_off_is_exactly_one_at_every_hour(self):
        for tick in range(0, 5 * 2400, 37):
            self.assertEqual(cal.perception_scale(tick), 1.0)
            self.assertEqual(human_runtime._perception_scale(tick), 1.0)

    def test_flag_on_range_and_extremes(self):
        os.environ["EDEN_CALENDAR"] = "1"
        values = [cal.perception_scale(t) for t in range(0, 8 * 12000, 25)]
        self.assertGreaterEqual(min(values), cal.PERCEPTION_DARK_FRACTION)
        self.assertLessEqual(max(values), 1.0)
        night = cal.perception_scale(11000)                       # tick of day 11000, past sunset in every season
        self.assertAlmostEqual(night, cal.PERCEPTION_DARK_FRACTION + (1 - cal.PERCEPTION_DARK_FRACTION) * cal.LIGHT_FLOOR)
        noon = cal.perception_scale(int(cal.USER.sun_up_ticks("spring") / 2))
        self.assertAlmostEqual(noon, 1.0, places=3)

    def test_flag_on_is_continuous_across_day_and_season_boundaries(self):
        os.environ["EDEN_CALENDAR"] = "1"
        for boundary in (12000, 24000, 12000 * 2 * 4 - 1000, 96000):
            a, b = cal.perception_scale(boundary - 1), cal.perception_scale(boundary)
            self.assertLess(abs(a - b), 0.01, boundary)
        self.assertTrue(all(math.isfinite(cal.perception_scale(t)) for t in range(0, 96000, 101)))


if __name__ == "__main__":
    unittest.main()
