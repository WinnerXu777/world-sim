"""1008 Part 2.A2 (1008_instincts_wiring_gap.md step 2): EDEN_TEMPERATURE, the comfort instinct.

The data tables and the pure functions, then the vectorised effects against a scalar reference on a real engine's human tensor, the shelter and fire terms, the roster's needs scale,
the mask (a dormant row is not touched), the sources' lifetime and re-base shift, and the registration (priority 34, once, only with the flag)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import calendar, engine_hooks, temperature as T  # noqa: E402


def scalar_effect(felt, scale, hp, stamina, mood, thirst):
    """The documented rules for one resident, in plain Python floats."""
    cold, hot = max(T.COMFORT_LOW - felt, 0.0), max(felt - T.COMFORT_HIGH, 0.0)
    if cold > 0:
        stamina = min(100.0, max(0.0, stamina - T.RATE_STAMINA * cold * scale))
        mood = min(100.0, max(0.0, mood - T.RATE_MOOD * cold * scale))
    harm = max(cold - T.HP_DAMAGE_FROM, 0.0) + max(hot - T.HP_DAMAGE_FROM, 0.0)
    hp -= T.RATE_HP * harm * scale
    if hot > 0:
        thirst = min(100.0, thirst + T.RATE_THIRST * hot * scale)
    return hp, stamina, mood, thirst


class PureTests(unittest.TestCase):
    def test_every_season_weather_and_block_has_a_number_and_winter_nights_are_the_coldest(self):
        for season in calendar.SEASONS:
            for weather in T.WEATHER_OFFSET:
                for block in calendar.BLOCKS:
                    self.assertTrue(-40.0 < T.ambient(season, weather, block) < 60.0)
        self.assertEqual(set(T.SEASON_BASE), set(calendar.SEASONS))
        self.assertEqual(set(T.BLOCK_OFFSET), set(calendar.BLOCKS))
        coldest = min(T.ambient(s, w, b) for s in calendar.SEASONS for w in T.WEATHER_OFFSET for b in calendar.BLOCKS)
        self.assertEqual(coldest, T.ambient("winter", "cold", "night"))
        self.assertGreater(T.ambient("summer", "clear", "day"), T.COMFORT_LOW)
        self.assertLess(T.ambient("winter", "clear", "night"), T.COMFORT_LOW)

    def test_deficits_are_the_distance_outside_the_band(self):
        cold, hot = T.deficits(torch.tensor([-10.0, 8.0, 20.0, 30.0, 40.0]))
        self.assertEqual(cold.tolist(), [18.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(hot.tolist(), [0.0, 0.0, 0.0, 0.0, 10.0])


class TemperatureFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_TEMPERATURE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine._nature_state = {"season": "winter", "weather": "clear"}
        self.addCleanup(lambda: setattr(self.engine, "_nature_state", None))
        self.addCleanup(lambda: self.engine.__dict__.pop("_warmth_sources", None))
        self.engine.tick = 1900                                    # night of the legacy day: -4 + 0 - 6 = -10
        self.rows = []

    def resident(self, slot, x=500.0, y=500.0, shelter=0.0, hp=100.0, stamina=80.0, mood=60.0, thirst=20.0):
        self.place_human(slot, x, y)
        h = self.engine.state.h_tensor
        h[slot, cfg.HP], h[slot, cfg.H_STAMINA], h[slot, cfg.MOOD], h[slot, cfg.THIRST], h[slot, cfg.H_SHELTER] = hp, stamina, mood, thirst, shelter
        self.rows.append(slot)

    def mask(self, *slots):
        mask = torch.zeros(self.engine.state.h_tensor.shape[0], dtype=torch.bool)
        mask[list(slots or self.rows)] = True
        return mask

    def run_once(self, *slots):
        return T.apply(self.engine, self.engine.state.h_tensor, self.mask(*slots))

    def column(self, col, slot):
        return float(self.engine.state.h_tensor[slot, col])


class EffectTests(TemperatureFixture):
    async def test_a_winter_night_unsheltered_costs_comfort_and_health(self):
        self.resident(0)
        state = self.run_once()
        self.assertAlmostEqual(state["ambient"], -10.0)
        self.assertAlmostEqual(float(state["cold"][0]), 18.0)
        self.assertLess(self.column(cfg.HP, 0), 100.0, "18 degrees under the band is past the 10-degree damage line")
        self.assertLess(self.column(cfg.H_STAMINA, 0), 80.0)
        self.assertLess(self.column(cfg.MOOD, 0), 60.0)
        self.assertEqual(self.column(cfg.THIRST, 0), 20.0)

    async def test_shelter_removes_the_damage_and_most_of_the_cost(self):
        self.resident(0)
        self.resident(1, shelter=1.0)
        self.run_once()
        self.assertEqual(self.column(cfg.HP, 1), 100.0, "-10 + 12 = 2: six degrees cold, under the damage line")
        self.assertLess(self.column(cfg.H_STAMINA, 1), 80.0, "still a comfort cost")
        self.assertGreater(self.column(cfg.H_STAMINA, 1), self.column(cfg.H_STAMINA, 0))

    async def test_a_resident_in_an_interior_space_counts_as_sheltered(self):
        self.resident(0)
        self.resident(1)
        self.engine.state.h_tensor[1, cfg.H_SPACE] = 2.0
        state = self.run_once()
        self.assertAlmostEqual(float(state["cold"][0]), 18.0)
        self.assertAlmostEqual(float(state["cold"][1]), 6.0)
        self.assertEqual(self.column(cfg.HP, 1), 100.0)

    async def test_a_fire_within_its_radius_warms_and_one_outside_does_not(self):
        self.resident(0, x=500.0, y=500.0)
        self.resident(1, x=800.0, y=500.0)
        T.add_source(self.engine, 510.0, 500.0)
        state = self.run_once()
        self.assertAlmostEqual(float(state["cold"][0]), 0.0, msg="-10 + 18 = 8: the edge of the band")
        self.assertAlmostEqual(float(state["cold"][1]), 18.0)
        self.assertEqual(self.column(cfg.HP, 0), 100.0)
        self.assertEqual(self.column(cfg.H_STAMINA, 0), 80.0)

    async def test_summer_heat_raises_thirst_and_a_hard_heat_hurts_only_past_the_line(self):
        self.engine._nature_state = {"season": "summer", "weather": "heat"}
        self.engine.tick = 700                                     # day: 22 + 8 + 3 = 33, three over the band
        self.resident(0)
        self.run_once()
        self.assertGreater(self.column(cfg.THIRST, 0), 20.0)
        self.assertEqual(self.column(cfg.HP, 0), 100.0)
        self.assertEqual(self.column(cfg.H_STAMINA, 0), 80.0)

    async def test_comfortable_weather_changes_nothing(self):
        self.engine._nature_state = {"season": "spring", "weather": "clear"}
        self.engine.tick = 700                                     # 12 + 0 + 3 = 15
        self.resident(0)
        before = self.engine.state.h_tensor[0].clone()
        self.run_once()
        self.assertTrue(torch.equal(self.engine.state.h_tensor[0], before))

    async def test_the_vectorised_pass_equals_a_scalar_reference_for_every_row(self):
        for spec in (dict(slot=0), dict(slot=1, shelter=1.0), dict(slot=2, hp=30.0, stamina=3.0, mood=2.0), dict(slot=3, x=900.0, thirst=95.0)):
            self.resident(**spec)
        T.add_source(self.engine, 505.0, 500.0, radius=20.0, bonus=5.0)
        h = self.engine.state.h_tensor
        cols = (cfg.HP, cfg.H_STAMINA, cfg.MOOD, cfg.THIRST)
        before = {s: [float(h[s, c]) for c in cols] for s in self.rows}
        felt = T.effective_temperature(self.engine, h, self.mask()).tolist()
        self.run_once()
        for slot in self.rows:
            want = scalar_effect(felt[slot], calendar.rate_scale("needs"), *before[slot])
            for col, value in zip(cols, want):
                self.assertAlmostEqual(self.column(col, slot), value, places=3, msg=(slot, col))

    async def test_the_rosters_needs_scale_scales_every_effect(self):
        self.resident(0)
        self.resident(1)
        scale = torch.ones(self.engine.state.h_tensor.shape[0])
        scale[1] = 0.1
        with mock.patch("systems.roster.driver.needs_scale_vector", return_value=scale):
            self.run_once()
        lost0, lost1 = 100.0 - self.column(cfg.HP, 0), 100.0 - self.column(cfg.HP, 1)
        self.assertAlmostEqual(lost1, lost0 * 0.1, places=4)
        self.assertAlmostEqual(80.0 - self.column(cfg.H_STAMINA, 1), (80.0 - self.column(cfg.H_STAMINA, 0)) * 0.1, places=4)

    async def test_rows_outside_the_mask_are_not_touched(self):
        self.resident(0)
        self.resident(1)
        before = self.engine.state.h_tensor[1].clone()
        self.run_once(0)
        self.assertTrue(torch.equal(self.engine.state.h_tensor[1], before))
        self.assertLess(self.column(cfg.HP, 0), 100.0)

    async def test_a_winter_night_kills_the_unprepared_and_spares_the_sheltered(self):
        self.resident(0)
        self.resident(1, shelter=1.0)
        for _ in range(600):                                       # one night block of the legacy day
            self.run_once()
        self.assertLess(self.column(cfg.HP, 0), 40.0, "one winter night unsheltered takes most of the health")
        self.assertEqual(self.column(cfg.HP, 1), 100.0)
        for _ in range(600):
            self.run_once()
        self.assertLessEqual(self.column(cfg.HP, 0), 0.0, "two nights without shelter, fire or clothing kill")
        self.assertEqual(self.column(cfg.HP, 1), 100.0)


class SourceTests(TemperatureFixture):
    async def test_a_lit_fire_expires(self):
        T.add_source(self.engine, 10.0, 10.0, ticks=5)
        self.assertEqual(T._fires(self.engine).shape[0], 1)
        self.engine.tick += 5
        self.assertEqual(T._fires(self.engine).shape[0], 0)

    async def test_a_rebase_shifts_the_fires(self):
        T.add_source(self.engine, 10.0, 20.0)
        self.assertEqual(T.shift_sources(self.engine, -256.0, 512.0), 1)
        (source,) = self.engine._warmth_sources
        self.assertEqual((source["x"], source["y"]), (-246.0, 532.0))

    async def test_the_window_rebase_calls_the_shift(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(2)
        T.add_source(self.engine, 100.0, 100.0)
        origin = self.manager.frame.origin
        moved = self.manager.rebase((origin[0] + 1, origin[1]))
        self.assertEqual(moved["moved"]["warmth_sources"], 1)
        self.assertAlmostEqual(self.engine._warmth_sources[0]["x"], 100.0 - 256.0)


class RegistrationTests(TemperatureFixture):
    async def test_the_genesis_hook_registers_one_entry_at_34_only_with_the_flag(self):
        registry = self.engine._registry
        count = lambda: sum(1 for e in registry if e["fn"] is T.instinct_temperature)  # noqa: E731
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_TEMPERATURE")
            engine_hooks.temperature_genesis_hook(self.engine)
            self.assertEqual(count(), 0)
        engine_hooks.temperature_genesis_hook(self.engine)
        engine_hooks.temperature_genesis_hook(self.engine)
        self.assertEqual(count(), 1)
        entry = next(e for e in registry if e["fn"] is T.instinct_temperature)
        self.addCleanup(lambda: registry.remove(entry))
        self.assertEqual(entry["priority"], 34)
        names = [e["fn"].__name__ for e in registry]
        self.assertLess(names.index("instinct_hp_death"), names.index("instinct_temperature"))
        self.assertLess(names.index("instinct_temperature"), names.index("instinct_heal"))

    async def test_the_boot_installs_the_genesis_hook_only_with_the_flag(self):
        from simulation.dispatch import DISPATCH
        self.addCleanup(engine_hooks.uninstall, DISPATCH)
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_TEMPERATURE")
            engine_hooks.uninstall(DISPATCH)
            engine_hooks.install(DISPATCH)
            self.assertNotIn("harness_temperature_genesis", {n for n, _ in DISPATCH.genesis_hooks})
        engine_hooks.uninstall(DISPATCH)
        engine_hooks.install(DISPATCH)
        self.assertIn("harness_temperature_genesis", {n for n, _ in DISPATCH.genesis_hooks})


class ClothingTests(TemperatureFixture):
    """A garment in a resident's pack adds its degrees to the felt temperature (``systems.clothing.insulation_of``); the best garment counts, packs are read on a cadence."""

    def dress(self, slot, *kinds):
        uid = f"h_t{slot}"
        self.engine._human_uid_by_slot[slot] = uid
        packs = self.engine.inventory_state.setdefault("inventories", {})
        packs[f"human:{uid}"] = {"items": [{"kind": kind, "quantity": 1} for kind in kinds]}
        self.addCleanup(packs.pop, f"human:{uid}", None)
        self.addCleanup(lambda: self.engine.__dict__.pop("_clothing", None))

    async def test_the_felt_temperature_adds_the_best_garment_per_resident(self):
        self.resident(0)
        self.resident(1)
        self.resident(2)
        self.dress(0, "cloak")
        self.dress(1, "cloak", "fur_coat")
        felt = T.effective_temperature(self.engine, self.engine.state.h_tensor, self.mask()).tolist()
        self.assertAlmostEqual(felt[1] - felt[2], 9.0, places=4, msg="the fur coat, not the sum")
        self.assertAlmostEqual(felt[0] - felt[2], 4.0, places=4)

    async def test_a_dressed_resident_loses_less_stamina_than_a_bare_one(self):
        self.resident(0)
        self.resident(1)
        self.dress(0, "fur_coat")
        self.run_once()
        self.assertGreater(self.column(cfg.H_STAMINA, 0), self.column(cfg.H_STAMINA, 1))

    async def test_a_row_outside_the_mask_or_without_a_pack_is_bare(self):
        self.resident(0)
        self.resident(1)
        self.dress(0, "cloak")
        vec = T.clothing_vector(self.engine, self.engine.state.h_tensor, self.mask(1))
        self.assertEqual(float(vec[0]), 0.0, "row 0 is dormant")
        self.assertEqual(float(vec[1]), 0.0, "row 1 has no pack")

    async def test_the_pack_is_read_again_after_the_refresh_interval(self):
        self.resident(0)
        self.dress(0)
        self.assertEqual(float(T.clothing_vector(self.engine, self.engine.state.h_tensor, self.mask())[0]), 0.0)
        self.engine.inventory_state["inventories"]["human:h_t0"]["items"].append({"kind": "cloak", "quantity": 1})
        self.engine.tick += T.CLOTHING_REFRESH - 1
        self.assertEqual(float(T.clothing_vector(self.engine, self.engine.state.h_tensor, self.mask())[0]), 0.0)
        self.engine.tick += 1
        self.assertEqual(float(T.clothing_vector(self.engine, self.engine.state.h_tensor, self.mask())[0]), 4.0)

    async def test_a_newly_awake_row_forces_a_read(self):
        self.resident(0)
        self.resident(1)
        self.dress(1, "cloak")
        self.assertEqual(float(T.clothing_vector(self.engine, self.engine.state.h_tensor, self.mask(0))[1]), 0.0)
        self.assertEqual(float(T.clothing_vector(self.engine, self.engine.state.h_tensor, self.mask(0, 1))[1]), 4.0)


if __name__ == "__main__":
    unittest.main()
