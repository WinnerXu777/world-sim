"""1008 calendar C0: ``harness/calendar.py``. The LEGACY profile must be today's functions bit for bit; the USER profile has exact block and
season boundaries, a continuous light curve, a monotonic day index and a closed-form ``day_changed``."""
import math
import os
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from harness import calendar as cal  # noqa: E402
from systems.nature import weather  # noqa: E402
from systems.schedule import resolver  # noqa: E402

ON = {"EDEN_CALENDAR": "1"}


class LegacyIsTodayTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ticks(self):
        rng = random.Random(1008)
        return list(range(0, 5000)) + [rng.randrange(0, 10_000_000) for _ in range(2000)] + [599, 600, 601, 149, 150, 299, 300, 449, 450, 2399, 2400]

    def test_season_matches_weather(self):
        self.assertEqual(cal.LEGACY_YEAR_TICKS, cfg.TICKS_PER_YEAR)
        for env_patch in ({"EDEN_CALENDAR": None}, {"EDEN_CALENDAR": "0"}):
            with mock.patch.dict(os.environ, clear=False):
                if env_patch["EDEN_CALENDAR"] is None:
                    os.environ.pop("EDEN_CALENDAR", None)
                else:
                    os.environ["EDEN_CALENDAR"] = env_patch["EDEN_CALENDAR"]
                for tick in self.ticks():
                    self.assertEqual(cal.LEGACY.season_for_tick(tick), weather.season_for_tick(tick), tick)
                for tick in (0.0, 149.999, 150.0, 599.5, 1234.75):                  # the legacy function takes any number
                    self.assertEqual(cal.LEGACY.season_for_tick(tick), weather.season_for_tick(tick), tick)
        with mock.patch.dict(os.environ, ON):
            self.assertEqual(weather.season_for_tick(150), "spring")
            self.assertEqual(weather.season_for_tick(150), cal.USER.season_for_tick(150))
            with mock.patch.dict(os.environ, clear=False):
                os.environ.pop("EDEN_CALENDAR", None)
                self.assertEqual(weather.season_for_tick(150), "summer")
                self.assertEqual(weather.season_for_tick(150), cal.LEGACY.season_for_tick(150))
            self.assertEqual(weather.season_for_tick(150), "spring")
            self.assertEqual(weather.season_for_tick(150), cal.USER.season_for_tick(150))

    def test_block_matches_the_resolver(self):
        self.assertEqual(cal.LEGACY_DAY_TICKS, resolver.DEFAULT_DAY_LENGTH_TICKS)
        for env_patch in ({"EDEN_CALENDAR": None}, {"EDEN_CALENDAR": "0"}):
            with mock.patch.dict(os.environ, clear=False):
                if env_patch["EDEN_CALENDAR"] is None:
                    os.environ.pop("EDEN_CALENDAR", None)
                else:
                    os.environ["EDEN_CALENDAR"] = env_patch["EDEN_CALENDAR"]
                for tick in self.ticks():
                    self.assertEqual(cal.LEGACY.block_for_tick(tick), resolver.tick_to_time_block(tick), tick)
                for length in (4, 5, 7, 100, 1000, 2400, 9999):
                    for tick in range(0, 300, 7):
                        self.assertEqual(cal.LEGACY.block_for_tick(tick, length), resolver.tick_to_time_block(tick, day_length_ticks=length), (tick, length))
        with mock.patch.dict(os.environ, ON):
            self.assertEqual(resolver.tick_to_time_block(500), "day")
            self.assertEqual(resolver.tick_to_time_block(500), cal.USER.block_for_tick(500))
            with mock.patch.dict(os.environ, clear=False):
                os.environ.pop("EDEN_CALENDAR", None)
                self.assertEqual(resolver.tick_to_time_block(500), "dawn")
                self.assertEqual(resolver.tick_to_time_block(500), cal.LEGACY.block_for_tick(500))
            self.assertEqual(resolver.tick_to_time_block(500), "day")
            self.assertEqual(resolver.tick_to_time_block(500), cal.USER.block_for_tick(500))

    def test_age_step_and_cooldown_rate_are_the_old_constants(self):
        self.assertEqual(cal.LEGACY.age_step(), 1.0 / cfg.TICKS_PER_YEAR)
        self.assertEqual(cal.LEGACY.cooldown_decay_rate(), cfg.COOLDOWN_DECAY_RATE)
        self.assertEqual(cal.LEGACY.year_ticks, cfg.TICKS_PER_YEAR)

    def test_flag_off_the_module_accessors_are_legacy(self):
        for env_patch in ({"EDEN_CALENDAR": None}, {"EDEN_CALENDAR": "0"}):
            with mock.patch.dict(os.environ, clear=False):
                if env_patch["EDEN_CALENDAR"] is None:
                    os.environ.pop("EDEN_CALENDAR", None)
                else:
                    os.environ["EDEN_CALENDAR"] = env_patch["EDEN_CALENDAR"]
                self.assertIs(cal.active(), cal.LEGACY)
                self.assertEqual(cal.ticks_per_year(), cfg.TICKS_PER_YEAR)
                self.assertEqual(cal.age_step(), 1.0 / cfg.TICKS_PER_YEAR)
                for tick in self.ticks()[:3000]:
                    self.assertEqual(cal.season_for_tick(tick), weather.season_for_tick(tick))
                    self.assertEqual(cal.tick_to_time_block(tick), resolver.tick_to_time_block(tick))
                    self.assertEqual(cal.tick_to_time_block(tick, day_length_ticks=777), resolver.tick_to_time_block(tick, day_length_ticks=777))
                for name in cal.RATE_MULTIPLIERS:
                    self.assertEqual(cal.rate_scale(name), 1.0)
        with mock.patch.dict(os.environ, ON):
            self.assertIs(cal.active(), cal.USER)
            with mock.patch.dict(os.environ, clear=False):
                os.environ.pop("EDEN_CALENDAR", None)
                self.assertIs(cal.active(), cal.LEGACY)
            self.assertIs(cal.active(), cal.USER)


class UserCalendarTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_shape(self):
        u = cal.USER
        self.assertEqual((u.day_ticks, u.year_ticks, u.season_ticks, u.days_per_year), (12000, 96000, 24000.0, 8.0))
        self.assertEqual(u.age_step(), 1.0 / 12000)                      # one life-year per game day
        self.assertEqual(u.life_year_ticks * 18, 18 * 12000)             # adulthood: 18 game days = 216000 ticks = 3 hours at 20 Hz
        self.assertEqual(18 * 12000 / cal.TICKS_PER_SECOND / 3600, 3.0)

    def test_season_boundaries_are_exact(self):
        u = cal.USER
        for boundary, before, after in ((24000, "spring", "summer"), (48000, "summer", "autumn"), (72000, "autumn", "winter"), (96000, "winter", "spring")):
            self.assertEqual((u.season_for_tick(boundary - 1), u.season_for_tick(boundary)), (before, after), boundary)
        self.assertEqual(u.season_for_tick(0), "spring")
        self.assertEqual(u.season_for_tick(96000 * 5 + 30000), "summer")

    def test_blocks_by_season(self):
        u = cal.USER
        expected = {"spring": (6000, 5000), "summer": (6960, 5960), "autumn": (6000, 5000), "winter": (5040, 4040)}      # (sun up, day block)
        for index, season in enumerate(cal.SEASONS):
            base = index * 24000
            up, day = expected[season]
            self.assertEqual(u.sun_up_ticks(season), up)
            self.assertEqual(u.block_for_tick(base), "dawn")
            self.assertEqual(u.block_for_tick(base + 499), "dawn")
            self.assertEqual(u.block_for_tick(base + 500), "day")
            self.assertEqual(u.block_for_tick(base + up - 501), "day")
            self.assertEqual(u.block_for_tick(base + up - 500), "dusk")
            self.assertEqual(u.block_for_tick(base + up - 1), "dusk")
            self.assertEqual(u.block_for_tick(base + up), "night")
            self.assertEqual(u.block_for_tick(base + 11999), "night")
            self.assertEqual(u.block_for_tick(base + 12000), "dawn")                   # the second day of the season starts the same way
            counts = {name: 0 for name in cal.BLOCKS}
            for t in range(12000):
                counts[u.block_for_tick(base + t)] += 1
            self.assertEqual(counts, {"dawn": 500, "day": day, "dusk": 500, "night": 12000 - up}, season)

    def test_a_caller_with_its_own_day_length_keeps_quarters(self):
        u = cal.USER
        for length in (2400, 100, 777):
            for tick in range(0, 400, 3):
                self.assertEqual(u.block_for_tick(tick, length), cal.LEGACY.block_for_tick(tick, length))
        with mock.patch.dict(os.environ, ON):
            self.assertIs(cal.active(), cal.USER)
            self.assertEqual(cal.tick_to_time_block(5000, day_length_ticks=2400), u.block_for_tick(5000))      # the default length: the user calendar answers
            self.assertEqual(cal.tick_to_time_block(5000), u.block_for_tick(5000))
            self.assertEqual(cal.tick_to_time_block(300, day_length_ticks=100), cal.LEGACY.block_for_tick(300, 100))

    def test_day_index_is_monotonic_and_day_changed_crosses_each_boundary_once(self):
        u = cal.USER
        last = -1
        for tick in range(0, 50_000, 37):
            index = u.now(tick).day_index
            self.assertGreaterEqual(index, last)
            last = index
        self.assertEqual(list(u.day_changed(11999, 12000)), [1])
        self.assertEqual(list(u.day_changed(12000, 12001)), [])
        self.assertEqual(list(u.day_changed(0, 11999)), [])
        self.assertEqual(list(u.day_changed(5, 36000)), [1, 2, 3])                 # a long jump: every day crossed
        self.assertEqual(list(u.day_changed(36000, 5)), [])                        # time never runs backwards here
        crossed = []
        for tick in range(1, 100_000):
            crossed.extend(u.day_changed(tick - 1, tick))
        self.assertEqual(crossed, list(range(1, 100_000 // 12000 + 1)))

    def test_light_is_continuous_bounded_and_peaks_at_noon(self):
        u = cal.USER
        previous = u.light_at(0)
        biggest_step = 0.0
        for tick in range(1, 4 * 96000 // 10):
            light = u.light_at(tick)
            self.assertTrue(0.0 <= light <= 1.0, (tick, light))
            biggest_step = max(biggest_step, abs(light - previous))
            previous = light
        self.assertLess(biggest_step, 0.1)                                        # no jumps, also across the day and season boundaries
        for boundary in (11999, 12000, 23999, 24000, 47999, 48000):
            self.assertLess(abs(u.light_at(boundary) - u.light_at(boundary - 1)), 0.1, boundary)
        self.assertEqual(u.light_at(0), cal.LIGHT_FLOOR)
        self.assertEqual(u.light_at(11999), cal.LIGHT_FLOOR)
        self.assertAlmostEqual(u.light_at(3000), 1.0, places=9)                    # a spring day is 6000 ticks: noon at 3000
        self.assertGreater(u.light_at(3480 + 24000), u.light_at(100 + 24000))     # summer noon

    def test_now_fields_agree(self):
        u = cal.USER
        m = u.now(96000 + 24000 + 12000 + 700)
        self.assertEqual((m.year, m.season, m.day_index, m.tick_of_day, m.block), (1, "summer", 11, 700, "day"))
        self.assertAlmostEqual(m.day_phase, 700 / 12000)
        self.assertAlmostEqual(m.season_phase, 12700 / 24000)
        self.assertAlmostEqual(m.year_phase, 36700 / 96000)
        self.assertEqual(u.now(10).tick, 10)

    def test_no_state_and_origin_invariance(self):
        u = cal.USER
        a = [u.now(t) for t in range(0, 500, 11)]
        b = [u.now(t) for t in range(0, 500, 11)]
        self.assertEqual(a, b)
        for t in (0, 777, 31337):
            for shift in (96000, 96000 * 40):                                      # whole years later: the same moment of the year
                shifted, base = u.now(t + shift), u.now(t)
                self.assertEqual((shifted.block, shifted.season, shifted.tick_of_day, shifted.light), (base.block, base.season, base.tick_of_day, base.light))
                self.assertEqual(shifted.year, base.year + shift // 96000)

    def test_invalid_calendars_are_refused(self):
        with self.assertRaises(ValueError):
            cal.Calendar("x", 3, 600, 600.0)
        with self.assertRaises(ValueError):
            cal.Calendar("x", 2400, 600, float("nan"))
        with self.assertRaises(ValueError):
            cal.Calendar("x", 12000, 96000, 12000.0, daylight=(("spring", 0.5),))
        with self.assertRaises(ValueError):
            cal.Calendar("x", 1000, 8000, 1000.0, daylight=tuple({s: 0.5 for s in cal.SEASONS}.items()))      # a 500-tick day cannot hold dawn and dusk


class ResolverDelegationTests(unittest.TestCase):
    """C1: ``schedule.resolver.tick_to_time_block`` asks the calendar only with the flag on and the default day length."""
    def setUp(self):
        patcher = mock.patch.dict(os.environ, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_flag_off_is_the_old_function(self):
        for env_patch in ({"EDEN_CALENDAR": None}, {"EDEN_CALENDAR": "0"}):
            with mock.patch.dict(os.environ, clear=False):
                if env_patch["EDEN_CALENDAR"] is None:
                    os.environ.pop("EDEN_CALENDAR", None)
                else:
                    os.environ["EDEN_CALENDAR"] = env_patch["EDEN_CALENDAR"]
                for tick in range(0, 5000, 13):
                    self.assertEqual(resolver.tick_to_time_block(tick), cal.LEGACY.block_for_tick(tick))
                    self.assertEqual(resolver.tick_to_time_block(tick, day_length_ticks=1000), cal.LEGACY.block_for_tick(tick, 1000))
        with mock.patch.dict(os.environ, ON):
            self.assertEqual(resolver.tick_to_time_block(500), "day")
            self.assertEqual(resolver.tick_to_time_block(500), cal.USER.block_for_tick(500))
            with mock.patch.dict(os.environ, clear=False):
                os.environ.pop("EDEN_CALENDAR", None)
                self.assertEqual(resolver.tick_to_time_block(500), "dawn")
                self.assertEqual(resolver.tick_to_time_block(500), cal.LEGACY.block_for_tick(500))
            self.assertEqual(resolver.tick_to_time_block(500), "day")
            self.assertEqual(resolver.tick_to_time_block(500), cal.USER.block_for_tick(500))

    def test_flag_on_default_length_uses_the_long_day_other_lengths_keep_quarters(self):
        with mock.patch.dict(os.environ, ON):
            for tick in (0, 499, 500, 5000, 5999, 6000, 11999, 12000, 30000, 70000):
                self.assertEqual(resolver.tick_to_time_block(tick), cal.USER.block_for_tick(tick), tick)
                self.assertEqual(resolver.tick_to_time_block(tick, day_length_ticks=2400), cal.USER.block_for_tick(tick), tick)
                self.assertEqual(resolver.tick_to_time_block(tick, day_length_ticks=1000), cal.LEGACY.block_for_tick(tick, 1000), tick)
            self.assertEqual(resolver.tick_to_time_block(5000), "day")
            self.assertEqual(resolver.tick_to_time_block(9000), "night")          # spring: the sun is up for 6000 of the 12000 ticks


class RatesAndFlagTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_flag_on_selects_the_user_calendar(self):
        with mock.patch.dict(os.environ, ON):
            self.assertIs(cal.active(), cal.USER)
            self.assertEqual(cal.ticks_per_year(), 96000)
            self.assertEqual(cal.age_step(), 1.0 / 12000)
            self.assertEqual(cal.year_of(96000 * 3 + 5), 3)
            self.assertEqual(cal.rate_scale("needs"), cal.RATE_MULTIPLIERS["needs"])
            self.assertEqual(cal.rate_scale("action"), 1.0)
            self.assertTrue(cal.describe()["enabled"])
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "0"}):
            self.assertIs(cal.active(), cal.LEGACY)

    def test_unknown_rate_class_is_an_error_in_both_modes(self):
        with mock.patch.dict(os.environ, ON):
            with self.assertRaises(KeyError):
                cal.rate_scale("hunger")
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_CALENDAR", None)
            with self.assertRaises(KeyError):
                cal.rate_scale("hunger")

    def test_starting_multipliers_hit_the_design_targets(self):
        r = cal.RATE_MULTIPLIERS
        hunger_to_seek = 50.0 / (cfg.HUNGER_TICK_RATE * r["needs"])
        thirst_to_seek = 45.0 / (cfg.THIRST_TICK_RATE * r["needs"])
        self.assertAlmostEqual(hunger_to_seek / cal.USER_DAY_TICKS, 0.4, delta=0.07)          # ~0.4 day from fed to hungry
        self.assertAlmostEqual(thirst_to_seek / cal.USER_DAY_TICKS, 0.25, delta=0.07)         # ~0.25 day from drunk to thirsty
        self.assertEqual((60 * r["weather"], 110 * r["weather"]), (1800, 3300))
        self.assertAlmostEqual(1800 / cal.USER_DAY_TICKS, 0.15)
        self.assertAlmostEqual(3300 / cal.USER_DAY_TICKS, 0.275)

    def test_describe_is_json_ready(self):
        import json
        for calendar in (cal.LEGACY, cal.USER):
            text = json.dumps(cal.describe(calendar))
            self.assertIn(calendar.name, text)
        self.assertEqual(cal.describe(cal.USER)["season_ticks"], 24000.0)
        self.assertFalse(cal.describe(cal.LEGACY)["enabled"])


if __name__ == "__main__":
    unittest.main()
