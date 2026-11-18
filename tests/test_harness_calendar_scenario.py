"""1008 calendar C2/C3: the rescale scenario (design section 7, item 3), computed from the constants the engine uses, flag on.
It asserts the survival targets of the user calendar by integrating the real per-tick tick functions on a lone resident, so a
change to any multiplier or constant that breaks the pacing fails here."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from harness import calendar as cal  # noqa: E402
from systems.survival import hunger, thirst  # noqa: E402

DAY = cal.USER_DAY_TICKS


class RescaleScenarioTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"})
        patch.start()
        self.addCleanup(patch.stop)

    def lone(self):
        h = torch.zeros((1, 32), dtype=torch.float32)
        h[:, cfg.HP] = 100.0
        return h, torch.ones(1, dtype=torch.bool)

    def run_until(self, tick_fns, done, limit=6 * DAY):
        h, mask = self.lone()
        for tick in range(limit):
            for fn in tick_fns:
                fn(mask, h)
            if done(h):
                return tick + 1, h
        return None, h

    def test_hunger_reaches_the_seek_threshold_in_about_two_fifths_of_a_day(self):
        ticks, _ = self.run_until([hunger.apply_hunger_tick], lambda h: float(h[0, cfg.HUNGER]) >= cfg.FOOD_SEEK_THRESHOLD)
        self.assertTrue(0.3 * DAY <= ticks <= 0.5 * DAY, ticks / DAY)

    def test_thirst_reaches_the_seek_threshold_in_about_a_quarter_day(self):
        ticks, _ = self.run_until([thirst.apply_thirst_tick], lambda h: float(h[0, cfg.THIRST]) >= cfg.WATER_SEEK_THRESHOLD)
        self.assertTrue(0.2 * DAY <= ticks <= 0.35 * DAY, ticks / DAY)

    def test_a_resident_with_no_food_dies_on_day_three_or_four(self):
        ticks, h = self.run_until([hunger.apply_hunger_tick], lambda h: float(h[0, cfg.HP]) <= 0.0)
        self.assertIsNotNone(ticks)
        self.assertTrue(2.8 * DAY <= ticks <= 4.2 * DAY, ticks / DAY)

    def test_a_resident_with_no_water_dies_in_under_a_day_and_a_half(self):
        ticks, _ = self.run_until([thirst.apply_thirst_tick], lambda h: float(h[0, cfg.HP]) <= 0.0)
        self.assertTrue(0.3 * DAY <= ticks <= 1.0 * DAY, ticks / DAY)

    def test_a_node_harvested_to_zero_regrows_within_two_days(self):
        """An authored berry bush (world_map/resources.py example: cap 40, regrow 0.02 per tick), through the real regrow system with summer
        clear-weather modifiers, from empty to its cap."""
        from systems.nature import ecology, weather
        m = torch.zeros((cfg.MAX_ENTITIES, 40), dtype=torch.float32)
        m[0, cfg.M_TYPE], m[0, cfg.M_GROWTH_RATE], m[0, cfg.M_NODE_CAP] = float(cfg.M_RESOURCE_NODE), 0.02, 40.0
        m[0, cfg.M_NODE_KIND] = float(next(iter(ecology.EDIBLE_NODE_KINDS.tolist())))
        multiplier = weather.build_nature_modifiers({"season": "summer", "weather": "clear"})["food_growth"]
        for tick in range(2 * DAY):
            ecology.apply_node_regrow(m, food_multiplier=multiplier)
            if float(m[0, cfg.M_RESOURCE_FOOD]) >= 40.0:
                break
        self.assertGreaterEqual(float(m[0, cfg.M_RESOURCE_FOOD]), 40.0)
        self.assertGreaterEqual(tick, DAY // 4)                  # not instant either

    def test_a_weather_spell_lasts_between_a_seventh_and_a_third_of_a_day(self):
        lo, hi = 60 * cal.rate_scale("weather"), 110 * cal.rate_scale("weather")
        self.assertTrue(0.14 * DAY <= lo and hi <= 0.31 * DAY, (lo / DAY, hi / DAY))

    def test_a_spring_crop_ripens_before_autumn(self):
        spring = 1.20 * 1.0 * cal.rate_scale("farm_growth")        # SEASON_MODIFIERS["spring"]["farm_growth"] with clear weather
        ticks = 100.0 / (cfg.FARM_FOOD_GROWTH_RATE * spring)
        self.assertLess(ticks, cal.USER.season_ticks * 2)          # spring and summer are the first two seasons: 4 days
        self.assertGreater(ticks, 0.5 * DAY)


if __name__ == "__main__":
    unittest.main()
