"""F4-2: thirst under EDEN_CALENDAR (reports/f4_thirst.md, F4-1). Thirsty creatures spent 69-98% of their thirsty ticks more than ``WATER_SEARCH``
(240 units) from any water, so the kernel never walked them to it (deer of c0_-1 / c4_-1 spawn 387-486 units from water), and the leash pulled deer
home past water they could see. Under a non-legacy calendar the search reaches ``WATER_SEARCH_LONG`` and a creature walking to water is not leashed;
on the legacy calendar both stay as they were (240, the leash wins), so the strict goldens do not move."""
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
from systems.creatures import kernel, table  # noqa: E402

USER = {"EDEN_CALENDAR": "1"}
FAR_LAKE = [(1040.0, 600.0, 1120.0, 680.0)]        # nearest tile centre 404 units east of HOME: beyond 240, inside the deer leash (500)
TICKS = 20                                          # a deer walks 3.5 per tick: 70 units straight; wandering covers at most 35


class SearchRadiusTests(unittest.TestCase):
    def test_legacy_search_is_unchanged(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_CALENDAR", None)
            self.assertIs(calendar.active(), calendar.LEGACY)
            self.assertEqual(kernel.water_search(), kernel.WATER_SEARCH)
            self.assertEqual(kernel.water_search(), 240.0)

    def test_user_search_reaches_far_water(self):
        with mock.patch.dict(os.environ, USER):
            self.assertIs(calendar.active(), calendar.USER)
            self.assertEqual(kernel.water_search(), kernel.WATER_SEARCH_LONG)
            self.assertGreater(kernel.WATER_SEARCH_LONG, 486.0, "covers the farthest dying deer of F4-1b")


class DeerThirstFixture(FeedFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(table.CREATURES["deer"], {"brain": "table"})      # as creature_balance --brain kernel
        patcher.start()
        self.addCleanup(patcher.stop)

    def thirsty_deer(self, x, y):
        deer = self.spawn("deer", x, y)
        self.engine.state.m_tensor[deer, cfg.A_THIRST] = 80.0
        return deer


class FarWaterTests(DeerThirstFixture):
    async def test_user_calendar_a_thirsty_deer_walks_to_water_400_units_away(self):
        self.terrain(water=FAR_LAKE)
        deer = self.thirsty_deer(*HOME)
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertGreater(self.pos(deer)[0] - HOME[0], 60.0, "it walks east, straight to the lake")

    async def test_legacy_water_400_units_away_is_not_sought(self):
        self.terrain(water=FAR_LAKE)
        deer = self.thirsty_deer(*HOME)
        self.go(TICKS)
        self.assertEqual(self.column(deer, cfg.A_THIRST), 80.0)
        self.assertLess(self.pos(deer)[0] - HOME[0], 50.0, "beyond WATER_SEARCH: no thirst move, only wandering")


class LeashTests(DeerThirstFixture):
    START = (HOME[0] + 520.0, HOME[1])                 # 520 from home: beyond the deer leash (500)
    LAKE = [(1240.0, 600.0, 1320.0, 680.0)]            # 84 units further east: in sight, away from home
    DRINK_TICKS = 60                                   # the walk takes about 24 ticks

    async def test_user_calendar_thirst_beats_the_leash(self):
        self.terrain(water=self.LAKE)
        deer = self.thirsty_deer(*self.START)
        with mock.patch.dict(os.environ, USER):
            drank = self.go(self.DRINK_TICKS, until=lambda: self.column(deer, cfg.A_THIRST) < 80.0)
        self.assertTrue(drank, "it keeps going to the water and drinks")
        self.assertGreater(self.pos(deer)[0], self.START[0] + 40.0)

    async def test_legacy_the_leash_still_wins(self):
        self.terrain(water=self.LAKE)
        deer = self.thirsty_deer(*self.START)
        self.go(self.DRINK_TICKS)
        self.assertEqual(self.column(deer, cfg.A_THIRST), 80.0, "turned back at the leash edge, never reaches the water")
        self.assertLess(self.pos(deer)[0], self.START[0])

    async def test_user_calendar_a_deer_that_is_not_thirsty_is_still_leashed(self):
        self.terrain(water=self.LAKE)
        deer = self.spawn("deer", *self.START)
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertLess(((self.pos(deer)[0] - HOME[0]) ** 2 + (self.pos(deer)[1] - HOME[1]) ** 2) ** 0.5, 510.0)


if __name__ == "__main__":
    unittest.main()
