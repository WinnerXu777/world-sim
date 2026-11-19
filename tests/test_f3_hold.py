"""F3-4: the kernel's breeding hold (crowded pasture, hunger) pins the cooldown for the same 600 ticks under both calendars. It pinned
``HOLD_COOLDOWN = 1.0`` life-year, which the cooldown decay turns into 600 ticks on the legacy calendar but a whole game day (12,000 ticks) under
EDEN_CALENDAR: sheep were ready to breed 3.5% of their mature time (reports/f3_decline.md, F3-3). On the legacy calendar the hold stays exactly 1.0."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_creatures_kernel import HOME  # noqa: E402
from test_creatures_feed import FeedFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import calendar  # noqa: E402
from systems.creatures import kernel  # noqa: E402

USER = {"EDEN_CALENDAR": "1"}


class HoldScaleTests(unittest.TestCase):
    def test_legacy_hold_is_exactly_one(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_CALENDAR", None)
            self.assertIs(calendar.active(), calendar.LEGACY)
            self.assertEqual(kernel.hold_cooldown(), 1.0)
            self.assertEqual(kernel.hold_cooldown(), kernel.HOLD_COOLDOWN)
            self.assertEqual(kernel.hold_cooldown() / calendar.cooldown_decay_rate(), float(calendar.LEGACY_YEAR_TICKS))

    def test_user_hold_lasts_the_same_ticks(self):
        with mock.patch.dict(os.environ, USER):
            self.assertIs(calendar.active(), calendar.USER)
            self.assertAlmostEqual(kernel.hold_cooldown(), calendar.LEGACY_YEAR_TICKS / calendar.active().life_year_ticks, places=12)
            self.assertAlmostEqual(kernel.hold_cooldown() / calendar.cooldown_decay_rate(), float(calendar.LEGACY_YEAR_TICKS), places=6)
            self.assertLess(kernel.hold_cooldown(), kernel.HOLD_COOLDOWN)


class UserCalendarHoldTests(FeedFixture):
    def pinned(self, slot):
        hold = kernel.hold_cooldown()
        value = self.column(slot, cfg.A_COOLDOWN)
        self.assertGreater(value, 0.0)
        self.assertLessEqual(value, hold + 1e-6, "pinned at the scaled hold, not at one life-year")
        self.assertGreaterEqual(value, hold - 3 * calendar.cooldown_decay_rate() - 1e-6)

    async def test_a_hungry_creature_is_held_for_600_ticks_worth(self):
        self.terrain(graze=False)
        hungry = self.spawn("fox", *HOME, hunger=60.0)
        fed = self.spawn("fox", HOME[0] + 200.0, HOME[1], hunger=10.0)
        with mock.patch.dict(os.environ, USER):
            self.go(3)
            self.pinned(hungry)
        self.assertEqual(self.column(fed, cfg.A_COOLDOWN), 0.0)

    async def test_a_full_pasture_holds_for_600_ticks_worth(self):
        self.terrain()
        crowd = [self.spawn("goat", 1000.0 + 0.1 * i, 1000.0, hunger=10.0) for i in range(kernel.CELL_CAPACITY + 1)]
        with mock.patch.dict(os.environ, USER):
            self.go(2)
            for slot in crowd:
                self.pinned(slot)


if __name__ == "__main__":
    unittest.main()
