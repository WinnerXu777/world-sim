"""1008 Phase 2 (balance finding of the village probe): kernel creatures graze on grass tiles and drink at the shore, because the legacy eat/drink loops found nothing to eat or drink in the
chunk world and every grazer starved in about a day. Hand-built terrain grids stand in for the integrated chunks."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_creatures_kernel import HOME, DAY, KernelFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness.window import WINDOW_FRAME  # noqa: E402
from harness import calendar  # noqa: E402
from systems.creatures import collide, kernel, table  # noqa: E402


class FeedFixture(KernelFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ)          # R0.6: the flag-off rates are the legacy day's; the calendar case sets EDEN_CALENDAR=1 itself
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("EDEN_CALENDAR", None)

    def terrain(self, water=(), graze=True):
        """Patch the grids: ``water`` is a list of (x0, y0, x1, y1) unit rectangles; everything else is grass when ``graze``."""
        width, height, (col0, row0) = WINDOW_FRAME
        wet = torch.zeros(height, width, dtype=torch.bool)
        for x0, y0, x1, y1 in water:
            wet[int(y0 // 8) - row0:int(y1 // 8) - row0, int(x0 // 8) - col0:int(x1 // 8) - col0] = True
        grass = ~wet if graze else torch.zeros_like(wet)
        near = torch.nn.functional.max_pool2d(wet.float().unsqueeze(0).unsqueeze(0), 3, stride=1, padding=1)[0, 0] > 0
        patcher = mock.patch.object(collide, "_grids", return_value=(wet, grass, near, col0, row0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def column(self, slot, col):
        return float(self.engine.state.m_tensor[slot, col])


class GrazeTests(FeedFixture):
    async def test_a_grazer_on_grass_eats_a_carnivore_does_not(self):
        self.terrain()
        goat = self.spawn("goat", *HOME, hunger=50.0)
        goblin = self.spawn("goblin", HOME[0] + 100.0, HOME[1], hunger=50.0)
        self.go(10)
        self.assertLess(self.column(goat, cfg.A_HUNGER), 50.0 - 9 * kernel.GRAZE_RATE)
        self.assertEqual(self.column(goblin, cfg.A_HUNGER), 50.0)

    async def test_grazers_on_one_tile_share_its_grass(self):
        self.terrain()
        alone = self.spawn("goat", *HOME, hunger=50.0)
        crowd = [self.spawn("goat", 1000.0 + 0.1 * i, 1000.0, hunger=50.0) for i in range(6)]
        self.go(10)
        eaten_alone = 50.0 - self.column(alone, cfg.A_HUNGER)
        eaten_crowd = 50.0 - self.column(crowd[0], cfg.A_HUNGER)
        self.assertGreater(eaten_alone, 0.0)
        self.assertLess(eaten_crowd, eaten_alone * 0.6, "six on one tile get a sixth of the tile each, not the full rate")

    async def test_intake_keeps_pace_with_the_drain_under_the_calendar(self):
        self.terrain()
        lone = self.spawn("goat", *HOME, hunger=50.0)
        crowd = [self.spawn("goat", 1000.0 + 0.1 * i, 1000.0, hunger=50.0) for i in range(6)]
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            scale = calendar.rate_scale("needs")
            self.assertLess(scale, 0.5)
            self.go(10)
        self.assertAlmostEqual(50.0 - self.column(lone, cfg.A_HUNGER), 10 * kernel.GRAZE_RATE * scale, places=4, msg="the intake rate is scaled like the drain")
        self.assertAlmostEqual(50.0 - self.column(crowd[0], cfg.A_HUNGER), 10 * kernel.CELL_FOOD * scale / 6, places=4, msg="the cell's food is scaled too")

    async def test_no_grass_no_meal_and_hunger_never_goes_below_zero(self):
        self.terrain(graze=False)
        goat = self.spawn("goat", *HOME, hunger=50.0)
        self.go(10)
        self.assertEqual(self.column(goat, cfg.A_HUNGER), 50.0)
        self.terrain()
        full = self.spawn("goat", HOME[0] + 20.0, HOME[1], hunger=0.01)
        self.go(5)
        self.assertEqual(self.column(full, cfg.A_HUNGER), 0.0)

    async def test_a_fleeing_grazer_does_not_stop_to_eat(self):
        self.terrain()
        rabbit = self.spawn("rabbit", *HOME, hunger=50.0)
        self.spawn("fox", HOME[0] + 15.0, HOME[1], hunger=0.0)
        self.go(1)
        self.assertEqual(self.column(rabbit, table.C_STATE), float(table.STATES["flee"]), "the rabbit runs from the fox")
        self.assertEqual(self.column(rabbit, cfg.A_HUNGER), 50.0)


class BreedingHoldTests(FeedFixture):
    async def test_a_hungry_creature_has_its_cooldown_pinned_a_fed_one_does_not(self):
        self.terrain(graze=False)
        hungry = self.spawn("fox", *HOME, hunger=60.0)
        fed = self.spawn("fox", HOME[0] + 200.0, HOME[1], hunger=10.0)
        self.go(3)
        self.assertGreaterEqual(self.column(hungry, cfg.A_COOLDOWN), kernel.HOLD_COOLDOWN)
        self.assertEqual(self.column(fed, cfg.A_COOLDOWN), 0.0)

    async def test_a_full_pasture_holds_the_cooldown_of_every_grazer_on_it(self):
        self.terrain()
        crowd = [self.spawn("goat", 1000.0 + 0.1 * i, 1000.0, hunger=10.0) for i in range(kernel.CELL_CAPACITY + 1)]
        lone = self.spawn("goat", 2000.0, 2000.0, hunger=10.0)
        self.go(2)
        for slot in crowd:
            self.assertGreaterEqual(self.column(slot, cfg.A_COOLDOWN), kernel.HOLD_COOLDOWN)
        self.assertEqual(self.column(lone, cfg.A_COOLDOWN), 0.0)


class DrinkTests(FeedFixture):
    LAKE = [(760.0, 600.0, 840.0, 680.0)]

    async def test_a_thirsty_creature_walks_to_the_shore_and_drinks(self):
        self.terrain(water=self.LAKE)
        goat = self.spawn("goat", 700.0, 640.0, **{"hunger": 0.0})
        self.engine.state.m_tensor[goat, cfg.A_THIRST] = 80.0
        self.assertTrue(self.go(400, until=lambda: self.column(goat, cfg.A_THIRST) < 80.0 - 5.0), "it reaches the water and its thirst falls")
        self.assertLess(self.pos(goat)[0], 760.0 + 8.0)

    async def test_water_beyond_the_search_radius_is_not_sought(self):
        self.terrain(water=[(1400.0, 1400.0, 1480.0, 1480.0)])
        goat = self.spawn("goat", *HOME)
        self.engine.state.m_tensor[goat, cfg.A_THIRST] = 80.0
        self.go(50)
        self.assertEqual(self.column(goat, cfg.A_THIRST), 80.0)

    async def test_a_creature_that_eats_nothing_never_drinks(self):
        self.terrain(water=self.LAKE)
        skeleton = self.spawn("skeleton", 750.0, 640.0)
        self.engine.state.m_tensor[skeleton, cfg.A_THIRST] = 80.0
        self.go(5)
        self.assertEqual(self.column(skeleton, cfg.A_THIRST), 0.0, "pinned at zero by the diet 'none' rule")


class TerrainMaskTests(unittest.TestCase):
    def test_masks_follow_the_layers(self):
        def layer(name, kind, rows):
            return {"name": name, "kind": kind, "tiles": rows}
        terrain = [[1] * 32 for _ in range(32)]
        terrain[0][0], terrain[0][1], terrain[0][2], terrain[0][3] = 3, 2, 4, 5          # water, sand, rock, paving
        footprint = [[0] * 32 for _ in range(32)]
        footprint[1][1] = 1                                                              # a water body on grass
        footprint[1][2] = 3                                                              # a ruin wall
        water, graze = collide.terrain_masks({"layers": [layer("terrain", "terrain", terrain), layer("decoration", "decoration", [[0] * 32] * 32),
                                                         layer("footprint", "footprint", footprint)]})
        self.assertEqual([bool(water[0, i]) for i in range(4)], [True, False, False, False])
        self.assertTrue(bool(water[1, 1]))
        self.assertEqual([bool(graze[0, i]) for i in range(4)], [False, True, False, False])
        self.assertFalse(bool(graze[1, 1]) or bool(graze[1, 2]))
        self.assertTrue(bool(graze[5, 5]))


if __name__ == "__main__":
    unittest.main()
