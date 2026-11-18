"""gameclock.day_ticks follows EDEN_CALENDAR for the untouched default and keeps a scenario's own day."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import unittest
import unittest.mock

from harness import calendar
from systems.actions import gameclock, reputation


class Clock(unittest.TestCase):
    def test_flag_off_the_day_is_the_legacy_one(self):
        with unittest.mock.patch.dict("os.environ", {"EDEN_CALENDAR": ""}):
            self.assertEqual(gameclock.day_ticks(), 2400)
            self.assertEqual(gameclock.day_of(4800), 2)
            self.assertEqual(reputation.decay_period(), reputation.DECAY_PERIOD)

    def test_the_calendar_flag_swaps_the_default_day_and_the_forgiveness_step(self):
        with unittest.mock.patch.dict("os.environ", {"EDEN_CALENDAR": "1"}):
            self.assertEqual(gameclock.day_ticks(), calendar.USER_DAY_TICKS)
            self.assertEqual(gameclock.day_of(2 * calendar.USER_DAY_TICKS), 2)
            self.assertEqual(reputation.decay_period(), calendar.USER_DAY_TICKS // 4)

    def test_a_scenario_that_sets_its_own_day_keeps_it_under_both_calendars(self):
        with unittest.mock.patch.object(gameclock, "DAY_TICKS", 600):
            for flag in ("", "1"):
                with unittest.mock.patch.dict("os.environ", {"EDEN_CALENDAR": flag}):
                    self.assertEqual(gameclock.day_ticks(), 600)


if __name__ == "__main__":
    unittest.main()
