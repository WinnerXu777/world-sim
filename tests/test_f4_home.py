"""F4-2 fix after seed 1 of the 10-day runs (reports/f4_seeds.md): two wolves born in the window killed residents 20 times. A creature born in the
window has a uid ``e_*`` with no home chunk, so it had no leash on either calendar, and F4-2 (water search ``WATER_SEARCH_LONG``, thirst before
the leash) kept such wolves alive and let them walk to any water, the village's included. Under a non-legacy calendar a newborn now takes its
mother's home (the nearest creature of its species within ``ADOPT_RADIUS`` that has one) or else the chunk it was born in, and only species with
no prey put thirst before the leash and search ``WATER_SEARCH_LONG``; predators keep the leash and the legacy ``WATER_SEARCH``. The legacy
calendar is unchanged, so the strict goldens do not move."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_creatures_kernel import HOME  # noqa: E402
from test_creatures_feed import FeedFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from systems.creatures import kernel, table  # noqa: E402

USER = {"EDEN_CALENDAR": "1"}
TICKS = 20                                          # a wolf walks 3.5 per tick (70 units); wandering covers at most half of that
BEYOND = (HOME[0] + 500.0, HOME[1])                 # 500 from the home of chunk (2, 2): beyond the wolf leash (450) and the sheep leash (400)
LAKE = [(1220.0, 600.0, 1300.0, 680.0)]             # nearest tile centre 84 units east of BEYOND: in sight, away from home
FAR_LAKE = [(1040.0, 600.0, 1120.0, 680.0)]         # nearest tile centre 404 units east of HOME: beyond WATER_SEARCH, inside the wolf leash


class HomeFixture(FeedFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for name in ("deer", "sheep", "wolf"):                                    # as creature_balance --brain kernel
            patcher = mock.patch.dict(table.CREATURES[name], {"brain": "table"})
            patcher.start()
            self.addCleanup(patcher.stop)

    def home(self, slot):
        return self.engine.__dict__.get("_creature_home", {}).get(self.engine._entity_uid_by_slot[slot])

    def thirsty(self, slot):
        self.engine.state.m_tensor[slot, cfg.A_THIRST] = 80.0
        return slot


class SearchTests(unittest.TestCase):
    def test_user_predators_keep_the_legacy_search(self):
        with mock.patch.dict(os.environ, USER):
            self.assertEqual(kernel.water_search(hunts=True), kernel.WATER_SEARCH)
            self.assertEqual(kernel.water_search(hunts=False), kernel.WATER_SEARCH_LONG)

    def test_legacy_search_is_the_same_for_both(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_CALENDAR", None)
            self.assertEqual(kernel.water_search(hunts=True), kernel.WATER_SEARCH)
            self.assertEqual(kernel.water_search(hunts=False), kernel.WATER_SEARCH)


class NewbornHomeTests(HomeFixture):
    async def test_user_a_newborn_takes_its_mothers_home(self):
        self.terrain()
        self.spawn("sheep", 900.0, 300.0)                                         # the mother: uid c2_2:fauna:sheep1, standing in chunk (3, 1)
        lamb = self.spawn("sheep", 904.0, 303.0, uid="e_000901")
        with mock.patch.dict(os.environ, USER):
            self.go(1)
        self.assertEqual(self.home(lamb), (2, 2), "its mother's home chunk, not the chunk it was born in")

    async def test_user_a_newborn_alone_takes_its_birth_chunk(self):
        self.terrain()
        cub = self.spawn("wolf", 900.0, 300.0, uid="e_000902")
        with mock.patch.dict(os.environ, USER):
            self.go(1)
        self.assertEqual(self.home(cub), (3, 1))

    async def test_user_a_newborn_is_leashed(self):
        self.terrain()
        self.spawn("wolf", BEYOND[0] + 4.0, BEYOND[1] + 3.0)                       # the mother, homed in chunk (2, 2)
        cub = self.spawn("wolf", *BEYOND, uid="e_000903")
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertLess(self.pos(cub)[0] - BEYOND[0], -40.0, "past its mother's leash: it walks home")

    async def test_legacy_a_newborn_has_no_home(self):
        self.terrain()
        self.spawn("wolf", BEYOND[0] + 4.0, BEYOND[1] + 3.0)
        cub = self.spawn("wolf", *BEYOND, uid="e_000904")
        self.go(TICKS)
        self.assertFalse(self.home(cub))
        self.assertGreater(self.pos(cub)[0] - BEYOND[0], -40.0, "no leash: it only wanders")


class PredatorLeashTests(HomeFixture):
    async def test_user_a_thirsty_wolf_past_its_leash_stays_leashed(self):
        self.terrain(water=LAKE)
        wolf = self.thirsty(self.spawn("wolf", *BEYOND))
        with mock.patch.dict(os.environ, USER):
            self.go(60)
        self.assertEqual(self.column(wolf, cfg.A_THIRST), 80.0, "turned back at the leash edge, never reaches the water")
        self.assertLess(self.pos(wolf)[0], BEYOND[0])

    async def test_user_a_thirsty_wolf_does_not_seek_water_beyond_the_legacy_search(self):
        self.terrain(water=FAR_LAKE)
        wolf = self.thirsty(self.spawn("wolf", *HOME))
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertLess(self.pos(wolf)[0] - HOME[0], 50.0, "404 units: beyond WATER_SEARCH, only wandering")

    async def test_user_a_thirsty_sheep_past_its_leash_still_goes(self):
        self.terrain(water=LAKE)
        sheep = self.thirsty(self.spawn("sheep", *BEYOND))
        with mock.patch.dict(os.environ, USER):
            drank = self.go(80, until=lambda: self.column(sheep, cfg.A_THIRST) < 80.0)
        self.assertTrue(drank, "a species with no prey: thirst beats the leash")

    async def test_user_a_thirsty_newborn_lamb_past_its_mothers_leash_still_goes(self):
        self.terrain(water=LAKE)
        self.spawn("sheep", BEYOND[0] - 4.0, BEYOND[1] - 3.0)                      # the mother, homed in chunk (2, 2)
        lamb = self.thirsty(self.spawn("sheep", *BEYOND, uid="e_000905"))
        with mock.patch.dict(os.environ, USER):
            drank = self.go(80, until=lambda: self.column(lamb, cfg.A_THIRST) < 80.0)
        self.assertTrue(drank, "its new home does not stop the walk to water")


if __name__ == "__main__":
    unittest.main()
