"""F4-3: a wounded creature flees only from a real threat nearby, under EDEN_CALENDAR. Sheep and deer have ``flee_hp`` 1.0 and animals never heal,
so one HP lost made ``fleeing`` true for life, and the flee ran from the nearest animal of any kind (usually a herd-mate), at any distance: it
overrode the walk to water and grazing (F4-2 probe smoke, reports/f4_thirst.md). Under a non-legacy calendar a wounded creature flees only when a
human or a harmful animal (another species that bites, hunts it or is feared) is within ``WOUND_RANGE``, and every flight runs from the nearer of
those two; on the legacy calendar the rule is unchanged, so the strict goldens do not move."""
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
FAR_LAKE = [(1040.0, 600.0, 1120.0, 680.0)]        # 404 units east of HOME: found under the calendar's water search (F4-2)
TICKS = 20                                          # a fleeing deer runs 5.0 per tick (100 units); wandering covers at most half the walk per tick


class FleeFixture(FeedFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for name in ("deer", "sheep", "wolf"):                                    # as creature_balance --brain kernel
            patcher = mock.patch.dict(table.CREATURES[name], {"brain": "table"})
            patcher.start()
            self.addCleanup(patcher.stop)

    def dx(self, slot):
        return self.pos(slot)[0] - HOME[0]


class WoundRangeTests(FleeFixture):
    def test_the_range_is_beyond_the_predators_reach(self):
        self.assertGreaterEqual(kernel.WOUND_RANGE, 2 * 60.0)

    async def test_user_a_wounded_thirsty_deer_walks_past_its_herd_mate_to_water(self):
        self.terrain(water=FAR_LAKE)
        deer = self.spawn("deer", *HOME, hp=90.0)
        self.spawn("deer", HOME[0] + 100.0, HOME[1])                            # a herd-mate, between it and the lake
        self.engine.state.m_tensor[deer, cfg.A_THIRST] = 80.0
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertGreater(self.dx(deer), 60.0, "a herd-mate is no threat: it walks east to the water")

    async def test_legacy_a_wounded_deer_still_runs_from_its_herd_mate(self):
        self.terrain(water=FAR_LAKE)
        deer = self.spawn("deer", *HOME, hp=90.0)
        self.spawn("deer", HOME[0] + 100.0, HOME[1])
        self.engine.state.m_tensor[deer, cfg.A_THIRST] = 80.0
        self.go(TICKS)
        self.assertLess(self.dx(deer), -60.0, "today's rule: flee from the nearest animal")

    async def test_user_a_wounded_deer_ignores_a_far_human(self):
        self.terrain()
        deer = self.spawn("deer", *HOME, hp=90.0)
        self.human(0, HOME[0] + 300.0, HOME[1])
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertGreater(self.dx(deer), -50.0, "300 units is beyond WOUND_RANGE: no flight")

    async def test_user_a_wounded_deer_flees_a_near_human(self):
        self.terrain()
        deer = self.spawn("deer", *HOME, hp=90.0)
        self.human(0, HOME[0] + 80.0, HOME[1])                                   # beyond the deer's fear radius (70), inside WOUND_RANGE
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertLess(self.dx(deer), -30.0, "it runs away from the human")
        self.assertGreaterEqual(80.0 - self.dx(deer), kernel.WOUND_RANGE - 6.0, "out to the edge of WOUND_RANGE, where the flight ends")

    async def test_user_a_wounded_sheep_flees_a_wolf(self):
        self.terrain()
        sheep = self.spawn("sheep", *HOME, hp=90.0)
        wolf = self.spawn("wolf", HOME[0] + 80.0, HOME[1])                       # sheep fear radius 0: only the wound makes it run
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertLess(self.dx(sheep), -25.0, "it runs away from the wolf")
        apart = ((self.pos(sheep)[0] - self.pos(wolf)[0]) ** 2 + (self.pos(sheep)[1] - self.pos(wolf)[1]) ** 2) ** 0.5
        self.assertGreater(apart, 100.0, "to about WOUND_RANGE (the wolf wanders meanwhile)")

    async def test_user_a_wounded_wolf_does_not_flee_its_pack_mate(self):
        self.terrain()
        wolf = self.spawn("wolf", *HOME, hp=20.0)                                # below flee_hp 0.25
        self.spawn("wolf", HOME[0] + 50.0, HOME[1])
        with mock.patch.dict(os.environ, USER):
            self.go(TICKS)
        self.assertGreater(self.dx(wolf), -50.0, "its own kind is no threat")


if __name__ == "__main__":
    unittest.main()
