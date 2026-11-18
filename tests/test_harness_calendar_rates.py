"""1008 calendar C2: the rate classes reach the rates. Flag off every value is the legacy constant (multiplier 1.0, bit for bit);
with ``EDEN_CALENDAR=1`` each class scales the sites it owns (hunger / thirst ticks, damage and healing, infection, regrow, farm growth,
weather spell lengths, animal needs)."""
import os
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from harness import calendar as cal  # noqa: E402
from systems.health import recovery  # noqa: E402
from systems.nature import ecology, weather  # noqa: E402
from systems.social import grouping  # noqa: E402
from systems.survival import hunger, thirst  # noqa: E402

ON = {"EDEN_CALENDAR": "1"}
R = cal.RATE_MULTIPLIERS


def humans(n=3):
    h = torch.zeros((n, 32), dtype=torch.float32)
    h[:, cfg.HP] = 80.0
    return h, torch.ones(n, dtype=torch.bool)


class Flag:
    """A context that runs with the calendar flag on or off."""
    def __init__(self, on):
        self.on = on

    def __enter__(self):
        self.patch = mock.patch.dict(os.environ)
        self.patch.start()
        os.environ.pop("EDEN_CALENDAR", None)
        if self.on:
            os.environ["EDEN_CALENDAR"] = "1"

    def __exit__(self, *exc):
        self.patch.stop()


class NeedsTests(unittest.TestCase):
    def test_hunger_and_thirst_ticks(self):
        for on, scale in ((False, 1.0), (True, R["needs"])):
            with Flag(on):
                h, mask = humans()
                hunger.apply_hunger_tick(mask, h)
                thirst.apply_thirst_tick(mask, h)
                self.assertEqual(float(h[0, cfg.HUNGER]), float(torch.tensor(0.0) + cfg.HUNGER_TICK_RATE * scale), on)
                self.assertEqual(float(h[0, cfg.THIRST]), float(torch.tensor(0.0) + cfg.THIRST_TICK_RATE * scale), on)

    def test_starvation_and_dehydration_damage(self):
        for on, hungry, thirsty in ((False, 1.0, 1.0), (True, R["starvation"], R["damage_recovery"])):
            with Flag(on):
                h, mask = humans()
                h[:, cfg.HUNGER] = 95.0
                hunger.apply_hunger_tick(mask, h)
                self.assertAlmostEqual(float(h[0, cfg.HP]), 80.0 - 2.0 * hungry, places=5)
                h, mask = humans()
                h[:, cfg.THIRST] = 95.0
                thirst.apply_thirst_tick(mask, h)
                self.assertAlmostEqual(float(h[0, cfg.HP]), 80.0 - cfg.THIRST_DAMAGE_RATE * thirsty, places=5)

    def test_healing_and_mood_recovery(self):
        for on, scale in ((False, 1.0), (True, R["damage_recovery"])):
            with Flag(on):
                h, mask = humans()
                recovery.apply_heal_tick(mask, h)
                self.assertAlmostEqual(float(h[0, cfg.HP]), 80.0 + cfg.HEAL_RATE * scale, places=5)
                h, mask = humans()
                h[:, cfg.MOOD] = 10.0
                grouping.apply_emotional_recovery(mask, h)
                self.assertAlmostEqual(float(h[0, cfg.MOOD]), 10.0 + cfg.MOOD_RECOVERY_RATE * scale, places=5)

    def test_threat_decay_is_action_time_and_never_scaled(self):
        for on in (False, True):
            with Flag(on):
                h, mask = humans()
                h[:, cfg.THREAT] = 5.0
                grouping.apply_emotional_recovery(mask, h)
                self.assertAlmostEqual(float(h[0, cfg.THREAT]), 5.0 - cfg.THREAT_DECAY_RATE, places=5)


class NatureTests(unittest.TestCase):
    def test_growth_modifiers(self):
        state = {"season": "spring", "weather": "clear"}
        with Flag(False):
            base = weather.build_nature_modifiers(state)
        with Flag(True):
            scaled = weather.build_nature_modifiers(state)
        self.assertAlmostEqual(scaled["food_growth"], base["food_growth"] * R["regrow"])
        self.assertAlmostEqual(scaled["water_growth"], base["water_growth"] * R["regrow"])
        self.assertAlmostEqual(scaled["farm_growth"], base["farm_growth"] * R["farm_growth"])

    def test_weather_spell_length(self):
        for on, (lo, hi) in ((False, (60, 110)), (True, (1800, 3300))):
            with Flag(on):
                lengths = set()
                for seed in range(60):
                    random.seed(seed)
                    engine = mock.Mock(_nature_state=None)
                    state = weather.ensure_nature_state(engine, tick=0)
                    lengths.add(state["weather_ends_tick"] - state["weather_started_tick"])
                self.assertTrue(all(isinstance(v, int) for v in lengths))
                self.assertGreaterEqual(min(lengths), lo, on)
                self.assertLessEqual(max(lengths), hi, on)
                self.assertGreater(max(lengths) - min(lengths), (hi - lo) // 2, on)

    def test_flag_off_consumes_the_same_random_draws(self):
        with Flag(False):
            random.seed(1008)
            engine = mock.Mock(_nature_state=None)
            state = weather.ensure_nature_state(engine, tick=0)
            random.seed(1008)
            weather._choose_weather("spring")                  # the one draw before the spell length
            expected = random.randint(60, 110)
        self.assertEqual(state["weather_ends_tick"] - state["weather_started_tick"], expected)

    def test_farm_water_use(self):
        for on, scale in ((False, 1.0), (True, R["regrow"])):
            with Flag(on):
                m = torch.zeros((cfg.MAX_ENTITIES, 40), dtype=torch.float32)
                m[0, cfg.M_TYPE], m[0, cfg.S_BUILD_PROGRESS] = float(cfg.M_FARM), 100.0
                m[0, cfg.M_RESOURCE_WATER], m[0, cfg.M_GROWTH_RATE] = 50.0, 0.1
                ecology.apply_water_cycle(m)
                self.assertAlmostEqual(float(m[0, cfg.M_RESOURCE_WATER]), 50.0 - cfg.FARM_WATER_USE_RATE * scale, places=5)


class AnimalTests(unittest.TestCase):
    def test_animal_needs_and_age(self):
        import instincts_and_tools as it
        for on, needs, damage, starve, age in ((False, 1.0, 1.0, 1.0, 1.0 / cfg.TICKS_PER_YEAR), (True, R["needs"], R["damage_recovery"], R["starvation"], 1.0 / 12000)):
            with Flag(on):
                m = torch.zeros((8, 40), dtype=torch.float32)
                m[:, cfg.M_HP] = 50.0
                mask = torch.ones(8, dtype=torch.bool)
                it.animal_instinct_hunger({"a_mask": mask}, m)
                it.animal_instinct_thirst({"a_mask": mask}, m)
                self.assertAlmostEqual(float(m[0, cfg.A_HUNGER]), cfg.ANIMAL_HUNGER_TICK_RATE * needs, places=6)
                self.assertAlmostEqual(float(m[0, cfg.A_THIRST]), cfg.ANIMAL_THIRST_TICK_RATE * needs, places=6)
                m[:, cfg.A_HUNGER] = 95.0
                m[:, cfg.A_THIRST] = 95.0
                m[:, cfg.M_HP] = 50.0
                it.animal_instinct_hunger({"a_mask": mask}, m)
                it.animal_instinct_thirst({"a_mask": mask}, m)
                self.assertAlmostEqual(float(m[0, cfg.M_HP]), 50.0 - 1.5 * starve - cfg.THIRST_DAMAGE_RATE * damage, places=4)
                m[:, cfg.A_AGE] = 0.0
                it.animal_instinct_age({"a_mask": mask}, m)
                self.assertAlmostEqual(float(m[0, cfg.A_AGE]), age, places=7)


class ResidentTtlTests(unittest.TestCase):
    def test_memory_ttl_uses_the_calendar_year(self):
        from runtime import resident_store
        with Flag(False):
            self.assertEqual(resident_store._resolve_ttl_ticks(2), 2 * cfg.TICKS_PER_YEAR)
        with Flag(True):
            self.assertEqual(resident_store._resolve_ttl_ticks(2), 2 * 96000)


if __name__ == "__main__":
    unittest.main()
