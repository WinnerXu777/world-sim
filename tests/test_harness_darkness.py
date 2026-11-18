"""1008 Part 2.A2 (USER-DEC-6): EDEN_DARKNESS, darkness unease.

The pure unease, the per-tick effect against a scalar reference, outdoors versus indoors, the fire relief, the threat cap, the calendar light under both calendars, the masked rows, the
reader and the registration (priority 34.4, once, only with the flag, after the sleep instinct)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import calendar, darkness as D, engine_hooks, sleep as S, temperature  # noqa: E402

NIGHT, DAY = 1900, 700            # legacy calendar ticks


class PureTests(unittest.TestCase):
    def test_unease_is_the_dark_outdoors_less_the_fire(self):
        outdoors = torch.tensor([True, True, False, True])
        fire = torch.tensor([False, True, False, False])
        got = D.unease(0.0, outdoors, fire).tolist()
        self.assertAlmostEqual(got[0], 1.0)
        self.assertAlmostEqual(got[1], 1.0 - D.FIRE_RELIEF, places=6)
        self.assertEqual(got[2], 0.0)
        self.assertAlmostEqual(D.unease(0.25, outdoors, fire).tolist()[0], 0.75, places=6)
        self.assertEqual(D.unease(1.0, outdoors, fire).tolist(), [0.0] * 4, "full light: no unease")

    def test_light_outside_the_unit_interval_is_clamped(self):
        self.assertEqual(D.unease(-3.0, torch.tensor([True]), torch.tensor([False])).tolist(), [1.0])
        self.assertEqual(D.unease(7.0, torch.tensor([True]), torch.tensor([False])).tolist(), [0.0])


class DarkFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_DARKNESS": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("EDEN_CALENDAR", None)          # R0.6: NIGHT and the block light values are the legacy day's; the calendar case sets the flag itself
        self.addCleanup(lambda: self.engine.__dict__.pop("_darkness", None))
        self.engine.tick = NIGHT
        self.rows = []

    def resident(self, slot, x=500.0, y=500.0, indoors=False, mood=60.0, threat=0.0):
        self.place_human(slot, x, y)
        h = self.engine.state.h_tensor
        h[slot, cfg.HP], h[slot, cfg.MOOD], h[slot, cfg.THREAT] = 100.0, mood, threat
        h[slot, cfg.H_SHELTER] = 1.0 if indoors else 0.0
        self.rows.append(slot)

    def mask(self, *slots):
        mask = torch.zeros(self.engine.state.h_tensor.shape[0], dtype=torch.bool)
        mask[list(slots or self.rows)] = True
        return mask

    def column(self, col, slot):
        return float(self.engine.state.h_tensor[slot, col])

    def run_once(self, *slots):
        return D.apply(self.engine, self.engine.state.h_tensor, self.mask(*slots))


class EffectTests(DarkFixture):
    async def test_a_resident_outdoors_at_night_loses_mood_and_gains_threat_by_the_scalar_reference(self):
        self.resident(0)
        scale = float(calendar.rate_scale("needs"))
        self.run_once()
        self.assertAlmostEqual(self.column(cfg.MOOD, 0), 60.0 - D.RATE_MOOD * scale, places=4)
        self.assertAlmostEqual(self.column(cfg.THREAT, 0), D.RATE_THREAT * scale, places=4)
        self.assertEqual(D.unease_of(self.engine, 0), 1.0)

    async def test_by_day_or_indoors_nothing_happens(self):
        self.resident(0, indoors=True)
        self.run_once()
        self.assertEqual((self.column(cfg.MOOD, 0), self.column(cfg.THREAT, 0)), (60.0, 0.0))
        self.assertEqual(D.unease_of(self.engine, 0), 0.0)
        self.resident(1)
        self.engine.tick = DAY
        self.run_once(1)
        self.assertEqual((self.column(cfg.MOOD, 1), self.column(cfg.THREAT, 1)), (60.0, 0.0))

    async def test_dusk_is_half_the_night(self):
        self.resident(0)
        self.engine.tick = 1500                                                  # legacy dusk: light 0.5
        self.assertAlmostEqual(calendar.active().light_at(1500), 0.5)
        self.run_once()
        self.assertAlmostEqual(D.unease_of(self.engine, 0), 0.5)

    async def test_the_threat_stops_at_the_cap_and_a_higher_threat_is_left_alone(self):
        self.resident(0, threat=D.THREAT_CAP - 0.001)
        self.resident(1, threat=60.0)
        self.run_once()
        self.assertAlmostEqual(self.column(cfg.THREAT, 0), D.THREAT_CAP, places=4)
        self.assertEqual(self.column(cfg.THREAT, 1), 60.0, "never lowered")

    async def test_a_row_outside_the_mask_is_not_touched(self):
        self.resident(0)
        self.resident(1)
        self.run_once(0)
        self.assertLess(self.column(cfg.MOOD, 0), 60.0)
        self.assertEqual(self.column(cfg.MOOD, 1), 60.0)

    async def test_the_effect_follows_the_calendar(self):
        self.resident(0)
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            scale = calendar.rate_scale("needs")
            self.engine.tick = 96000 - 100                                       # deep night of the long calendar: light 0.05
            light = calendar.active().light_at(self.engine.tick)
            self.assertLess(light, 0.1)
            self.run_once()
        self.assertAlmostEqual(self.column(cfg.MOOD, 0), 60.0 - D.RATE_MOOD * (1.0 - light) * scale, places=4)

    async def test_mood_does_not_go_below_zero(self):
        self.resident(0, mood=0.001)
        self.run_once()
        self.assertEqual(self.column(cfg.MOOD, 0), 0.0)


class FireTests(DarkFixture):
    async def test_a_resident_by_a_fire_is_eased_and_one_beyond_its_radius_is_not(self):
        self.resident(0, x=500.0, y=500.0)
        self.resident(1, x=900.0, y=900.0)
        fires = torch.tensor([[505.0, 500.0, 60.0]])
        with mock.patch.object(temperature, "_fires", return_value=fires):
            self.run_once()
        self.assertAlmostEqual(D.unease_of(self.engine, 0), 1.0 - D.FIRE_RELIEF, places=6)
        self.assertEqual(D.unease_of(self.engine, 1), 1.0)
        self.assertLess(self.column(cfg.MOOD, 1), self.column(cfg.MOOD, 0))

    async def test_a_lit_fire_registered_with_the_temperature_module_counts(self):
        self.resident(0)
        self.addCleanup(lambda: self.engine.__dict__.pop("_warmth_sources", None))
        temperature.add_source(self.engine, 505.0, 500.0, radius=60.0)
        self.run_once()
        self.assertAlmostEqual(D.unease_of(self.engine, 0), 1.0 - D.FIRE_RELIEF, places=6)


class ReaderTests(DarkFixture):
    async def test_the_reader_is_zero_before_the_first_tick(self):
        self.assertIsNone(D.state_of(self.engine))
        self.assertEqual(D.unease_of(self.engine, 0), 0.0)


class RegistrationTests(DarkFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.registry = self.engine._registry
        self.saved = list(self.registry)
        self.addCleanup(lambda: self.registry.__setitem__(slice(None), self.saved))

    async def test_the_genesis_hook_registers_once_after_sleep_only_with_the_flag(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_DARKNESS")
            engine_hooks.darkness_genesis_hook(self.engine)
            self.assertNotIn(D.NAME, [e["fn"].__name__ for e in self.registry])
        engine_hooks.sleep_genesis_hook.__call__(self.engine) if S.enabled() else S.install(self.engine)
        engine_hooks.darkness_genesis_hook(self.engine)
        engine_hooks.darkness_genesis_hook(self.engine)
        names = [e["fn"].__name__ for e in self.registry]
        self.assertEqual(names.count(D.NAME), 1)
        self.assertEqual(next(e for e in self.registry if e["fn"].__name__ == D.NAME)["priority"], 34.4)
        self.assertLess(names.index(S.NAME), names.index(D.NAME))
        self.assertLess(names.index(D.NAME), names.index("instinct_heal"))

    async def test_the_boot_installs_the_genesis_hook_only_with_the_flag(self):
        from simulation.dispatch import DISPATCH
        self.addCleanup(engine_hooks.uninstall, DISPATCH)
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_DARKNESS")
            engine_hooks.uninstall(DISPATCH)
            engine_hooks.install(DISPATCH)
            self.assertNotIn("harness_darkness_genesis", {n for n, _ in DISPATCH.genesis_hooks})
        engine_hooks.uninstall(DISPATCH)
        engine_hooks.install(DISPATCH)
        self.assertIn("harness_darkness_genesis", {n for n, _ in DISPATCH.genesis_hooks})


if __name__ == "__main__":
    unittest.main()
