"""F4-2b: thirsty predators must not oscillate at their home leash."""
import os
from unittest import mock

from test_f4_home import HomeFixture, USER
import genesis_config as cfg
from systems.creatures import table
from test_creatures_kernel import HOME


class PredatorWaterFallbackTests(HomeFixture):
    EDGE = (1080.0, 640.0)
    OUTSIDE = (1136.0, 632.0, 1144.0, 648.0)
    INSIDE = (560.0, 632.0, 568.0, 648.0)

    async def test_long_calendar_redirects_to_home_water_and_drinks(self):
        self.terrain(water=[self.OUTSIDE, self.INSIDE])
        wolf = self.thirsty(self.spawn("wolf", *self.EDGE))
        with mock.patch.dict(os.environ, USER):
            drank = self.go(250, until=lambda: self.column(wolf, cfg.A_THIRST) < 80)
        self.assertTrue(drank)
        self.assertLess(self.pos(wolf)[0], HOME[0])

    async def test_legacy_calendar_does_not_redirect(self):
        self.terrain(water=[self.OUTSIDE, self.INSIDE])
        wolf = self.thirsty(self.spawn("wolf", *self.EDGE))
        self.go(100)
        self.assertGreater(self.pos(wolf)[0], 1000)
        self.assertEqual(self.column(wolf, cfg.A_THIRST), 80)

    async def test_no_home_water_keeps_the_leash(self):
        self.terrain(water=[self.OUTSIDE])
        wolf = self.thirsty(self.spawn("wolf", *self.EDGE))
        with mock.patch.dict(os.environ, USER):
            self.go(50)
        self.assertLess(self.pos(wolf)[0], HOME[0] + 455)
        self.assertEqual(self.column(wolf, cfg.A_THIRST), 80)

