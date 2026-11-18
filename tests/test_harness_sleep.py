"""1008 Part 2.A2 (USER-DEC-6): EDEN_SLEEP, sleep pressure.

The closed form and its calendar-relative rates, the per-tick drag above TIRED against a scalar reference, the sleeping rules (the roster's sleep anchor, indoors at night), the cadence
(a dormant resident keeps its tick and the next update covers the stretch), the mirror in the resident record and the reload, the readers and the registration (priority 34.2, once,
only with the flag, after the temperature instinct)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import calendar, engine_hooks, sleep as S, temperature  # noqa: E402

NIGHT, DAY = 1900, 700            # legacy calendar ticks


class PureTests(unittest.TestCase):
    def test_a_full_day_awake_fraction_fills_the_debt_and_a_sleep_fraction_clears_it_under_both_days(self):
        for day in (2400, 12000):
            self.assertAlmostEqual(S.advance(0.0, S.AWAKE_DAYS * day, False, day), 100.0, places=6)
            self.assertAlmostEqual(S.advance(100.0, S.SLEEP_DAYS * day, True, day), 0.0, places=6)
            self.assertEqual(S.advance(100.0, 10 * day, False, day), 100.0, "clamped")
            self.assertEqual(S.advance(0.0, 10 * day, True, day), 0.0, "clamped")

    def test_the_closed_form_composes(self):
        once = S.advance(10.0, 900, False, 12000)
        twice = S.advance(S.advance(10.0, 400, False, 12000), 500, False, 12000)
        self.assertAlmostEqual(once, twice, places=9)

    def test_pressure_is_zero_up_to_tired_and_one_at_the_top(self):
        self.assertEqual(S.pressure(torch.tensor([0.0, 49.0, 50.0])).tolist(), [0.0, 0.0, 0.0])
        self.assertAlmostEqual(float(S.pressure(torch.tensor(75.0))), 0.5)
        self.assertEqual(float(S.pressure(torch.tensor(100.0))), 1.0)


class SleepFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_SLEEP": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("EDEN_CALENDAR", None)          # R0.6: NIGHT/DAY and the 2400-tick closed forms are the legacy day's; the calendar case sets the flag itself
        self.addCleanup(lambda: self.engine.__dict__.pop("_sleep", None))
        self.addCleanup(lambda: self.engine.__dict__.pop("_sleep_debt_vec", None))
        self.addCleanup(lambda: self.engine.__dict__.pop("_sleep_asleep", None))
        self.engine.tick = NIGHT
        self.rows = []

    def resident(self, slot, indoors=False, stamina=80.0, mood=60.0, debt=None):
        self.place_human(slot, 500.0 + 30.0 * slot, 500.0)
        h = self.engine.state.h_tensor
        h[slot, cfg.HP], h[slot, cfg.H_STAMINA], h[slot, cfg.MOOD] = 100.0, stamina, mood
        h[slot, cfg.H_SHELTER] = 1.0 if indoors else 0.0
        self.engine._human_uid_by_slot[slot] = f"h_t{slot}"
        self.rows.append(slot)
        if debt is not None:
            self.set_debt(slot, debt)

    def set_debt(self, slot, debt):
        S._records(self.engine)[f"h_t{slot}"] = {"debt": float(debt), "tick": int(self.engine.tick), "mirrored": float(debt)}

    def mask(self, *slots):
        mask = torch.zeros(self.engine.state.h_tensor.shape[0], dtype=torch.bool)
        mask[list(slots or self.rows)] = True
        return mask

    def column(self, col, slot):
        return float(self.engine.state.h_tensor[slot, col])

    def tick_to(self, tick, *slots):
        """Advance the engine clock to ``tick`` and run the instinct once on it."""
        self.engine.tick = tick
        return S.apply(self.engine, self.engine.state.h_tensor, self.mask(*slots))


class EffectTests(SleepFixture):
    async def test_a_rested_resident_is_untouched_a_tired_one_pays_in_stamina_and_mood(self):
        self.resident(0, debt=10.0)
        self.resident(1, debt=100.0)
        S.apply(self.engine, self.engine.state.h_tensor, self.mask())            # tick 1900 % 20 == 0: the cadence step runs; the debts are already at this tick
        self.assertEqual((self.column(cfg.H_STAMINA, 0), self.column(cfg.MOOD, 0)), (80.0, 60.0))
        self.assertLess(self.column(cfg.H_STAMINA, 1), 80.0)
        self.assertLess(self.column(cfg.MOOD, 1), 60.0)

    async def test_the_drag_equals_a_scalar_reference(self):
        self.resident(0, debt=75.0)
        S.apply(self.engine, self.engine.state.h_tensor, self.mask())
        scale = float(calendar.rate_scale("needs"))
        from systems.roster.driver import needs_scale_vector
        self.assertIsNone(needs_scale_vector(self.engine, self.engine.state.h_tensor), "this fixture is not a roster world")
        self.assertAlmostEqual(self.column(cfg.H_STAMINA, 0), 80.0 - S.RATE_STAMINA * 0.5 * scale, places=4)
        self.assertAlmostEqual(self.column(cfg.MOOD, 0), 60.0 - S.RATE_MOOD * 0.5 * scale, places=4)

    async def test_a_row_outside_the_mask_is_not_touched(self):
        self.resident(0, debt=100.0)
        self.resident(1, debt=100.0)
        S.apply(self.engine, self.engine.state.h_tensor, self.mask(0))
        self.assertLess(self.column(cfg.H_STAMINA, 0), 80.0)
        self.assertEqual(self.column(cfg.H_STAMINA, 1), 80.0)

    async def test_the_effects_follow_the_calendar_needs_rate(self):
        self.resident(0, debt=100.0)
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            scale = calendar.rate_scale("needs")
            S.apply(self.engine, self.engine.state.h_tensor, self.mask())
        self.assertAlmostEqual(self.column(cfg.H_STAMINA, 0), 80.0 - S.RATE_STAMINA * scale, places=4)


class DebtTests(SleepFixture):
    async def test_awake_through_a_day_the_debt_follows_the_closed_form(self):
        self.resident(0, indoors=False)
        self.tick_to(NIGHT)                                                      # the first update creates the record at tick 1900
        record = S.record_of(self.engine, "h_t0")
        self.assertEqual((record["debt"], record["tick"]), (0.0, NIGHT))
        self.tick_to(NIGHT + 60)                                                 # outdoors at night: awake
        self.assertAlmostEqual(S.debt_of(self.engine, "h_t0"), S.advance(0.0, 60, False, 2400), places=6)

    async def test_indoors_at_night_clears_the_debt_and_indoors_by_day_does_not(self):
        self.resident(0, indoors=True, debt=60.0)
        self.tick_to(NIGHT + 120)
        self.assertAlmostEqual(S.debt_of(self.engine, "h_t0"), S.advance(60.0, 120, True, 2400), places=6)
        self.assertLess(S.debt_of(self.engine, "h_t0"), 60.0)
        self.resident(1, indoors=True, debt=60.0)
        self.engine.tick = DAY
        self.set_debt(1, 60.0)
        self.tick_to(DAY + 120, 1)
        self.assertGreater(S.debt_of(self.engine, "h_t1"), 60.0, "awake in a house at noon")

    async def test_a_sleeper_regains_stamina_and_mood(self):
        self.resident(0, indoors=True, debt=0.0)
        self.tick_to(NIGHT)
        self.assertGreater(self.column(cfg.H_STAMINA, 0), 80.0)
        self.assertGreater(self.column(cfg.MOOD, 0), 60.0)

    async def test_a_roster_resident_at_its_sleep_anchor_is_asleep_even_by_day(self):
        from systems.roster.driver import runtime
        self.resident(0, indoors=False, debt=60.0)
        self.engine.tick = DAY
        self.set_debt(0, 60.0)
        with mock.patch.object(runtime(self.engine), "at_anchor", {"h_t0": "sleep"}):
            self.tick_to(DAY + 120)
        self.assertAlmostEqual(S.debt_of(self.engine, "h_t0"), S.advance(60.0, 120, True, 2400), places=6)

    async def test_a_dormant_row_keeps_its_tick_and_the_next_update_covers_the_stretch(self):
        self.resident(0, debt=20.0)
        self.tick_to(NIGHT + 40)
        before = S.record_of(self.engine, "h_t0")["tick"]
        self.tick_to(NIGHT + 200, 1)                                             # row 0 is outside the mask: nothing for it
        self.assertEqual(S.record_of(self.engine, "h_t0")["tick"], before)
        self.tick_to(NIGHT + 300)
        self.assertAlmostEqual(S.debt_of(self.engine, "h_t0"), S.advance(20.0, 300, False, 2400), places=6, msg="the stretch away is covered in one closed-form step")
        self.assertEqual(S.record_of(self.engine, "h_t0")["tick"], NIGHT + 300)

    async def test_the_cadence_is_the_only_time_the_debt_moves(self):
        self.resident(0, debt=20.0)
        self.tick_to(NIGHT)
        at = S.debt_of(self.engine, "h_t0")
        self.tick_to(NIGHT + 7)                                                  # not a multiple of CADENCE
        self.assertEqual(S.debt_of(self.engine, "h_t0"), at)


class RecordTests(SleepFixture):
    async def test_the_debt_is_mirrored_in_the_resident_record_and_read_back_after_a_reload(self):
        h = self.engine.state.h_tensor
        self.resident(0, debt=0.0)
        resident = self.engine.resident_store.ensure_resident("h_t0", 0, h, self.engine.tick)
        S._records(self.engine).pop("h_t0", None)
        self.tick_to(NIGHT)
        self.tick_to(NIGHT + 600)                                                # outdoors at night: +25 units of debt
        saved = self.engine.resident_store.get("h_t0").get("sleep")
        self.assertIsNotNone(saved)
        self.assertAlmostEqual(saved["debt"], round(S.debt_of(self.engine, "h_t0"), 2))
        S._records(self.engine).clear()                                          # a loaded world: the engine has not seen the resident
        self.assertAlmostEqual(S.debt_of(self.engine, "h_t0"), saved["debt"], places=2)

    async def test_readers_and_thresholds(self):
        self.set_debt(0, 60.0)
        self.set_debt(1, 90.0)
        self.assertEqual((S.tired_of(self.engine, "h_t0"), S.exhausted_of(self.engine, "h_t0")), (True, False))
        self.assertEqual((S.tired_of(self.engine, "h_t1"), S.exhausted_of(self.engine, "h_t1")), (True, True))
        self.assertEqual((S.debt_of(self.engine, "nobody"), S.tired_of(self.engine, "nobody")), (0.0, False))


class RegistrationTests(SleepFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.registry = self.engine._registry
        self.saved = list(self.registry)
        self.addCleanup(lambda: self.registry.__setitem__(slice(None), self.saved))

    async def test_the_genesis_hook_registers_once_after_temperature_only_with_the_flag(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_SLEEP")
            engine_hooks.sleep_genesis_hook(self.engine)
            self.assertNotIn(S.NAME, [e["fn"].__name__ for e in self.registry])
        with mock.patch.dict(os.environ, {"EDEN_TEMPERATURE": "1"}):
            engine_hooks.temperature_genesis_hook(self.engine)
        engine_hooks.sleep_genesis_hook(self.engine)
        engine_hooks.sleep_genesis_hook(self.engine)
        names = [e["fn"].__name__ for e in self.registry]
        self.assertEqual(names.count(S.NAME), 1)
        self.assertEqual(next(e for e in self.registry if e["fn"].__name__ == S.NAME)["priority"], 34.2)
        self.assertLess(names.index("instinct_temperature"), names.index(S.NAME))
        self.assertLess(names.index(S.NAME), names.index("instinct_heal"))

    async def test_the_boot_installs_the_genesis_hook_only_with_the_flag(self):
        from simulation.dispatch import DISPATCH
        self.addCleanup(engine_hooks.uninstall, DISPATCH)
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_SLEEP")
            engine_hooks.uninstall(DISPATCH)
            engine_hooks.install(DISPATCH)
            self.assertNotIn("harness_sleep_genesis", {n for n, _ in DISPATCH.genesis_hooks})
        engine_hooks.uninstall(DISPATCH)
        engine_hooks.install(DISPATCH)
        self.assertIn("harness_sleep_genesis", {n for n, _ in DISPATCH.genesis_hooks})


if __name__ == "__main__":
    unittest.main()
