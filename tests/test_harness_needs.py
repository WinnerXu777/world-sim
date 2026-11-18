"""S3: hunger/thirst drain as one harness system (EDEN_HARNESS_NEEDS=1), bit-for-bit equal to the two legacy entries."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from authored_village import load_village_maps  # noqa: E402
from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import calendar as cal, engine_hooks as eh, needs  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402
from systems.roster import driver  # noqa: E402


def entry(engine, name):
    return next(e for e in engine._registry if getattr(e["fn"], "__name__", "") == name)


def names(engine):
    return [getattr(e["fn"], "__name__", "") for e in engine._registry]


class NeedsTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        self.env = mock.patch.dict(os.environ, {eh.FLAG: "1", needs.FLAG: "1"})
        self.env.start()
        eh.install(DISPATCH)
        self.engine = backend.engine
        self.engine.reset_world()
        await backend.create_genesis(self.engine, map_name="starter_village")
        DISPATCH.errors.clear()
        h = self.engine.state.h_tensor
        self.live = (h[:, cfg.TYPE] > 0).nonzero(as_tuple=False).flatten()
        self.wrapper = entry(self.engine, needs.NAME)["fn"]
        self.originals = self.wrapper.originals

    async def asyncTearDown(self):
        eh.uninstall(DISPATCH)
        self.env.stop()
        if hasattr(self.engine, "harness"):
            del self.engine.harness
        await super().asyncTearDown()

    def unscaled(self):
        """Force the harness path (no roster rate scaling), for the legacy functions and the wrapper alike."""
        return mock.patch.object(driver, "needs_scale_vector", return_value=None)

    def randomise(self, generator):
        h = self.engine.state.h_tensor
        n = len(self.live)
        rows = self.live
        edge = torch.tensor([0.0, 89.9, 89.95, 89.99, 90.0, 99.96, 100.0, 120.0, -3.0])
        for col, hi in ((cfg.HUNGER, 110.0), (cfg.THIRST, 110.0), (cfg.HP, 100.0), (cfg.MOOD, 100.0)):
            values = torch.rand(n, generator=generator) * hi
            pick = torch.rand(n, generator=generator) < 0.3
            values[pick] = edge[torch.randint(0, len(edge), (int(pick.sum()),), generator=generator)]
            if col in (cfg.HP, cfg.MOOD):
                values = values.clamp(0.0, 100.0)
            h[rows, col] = values
        h[rows, cfg.CRITICAL_HEALTH] = (torch.rand(n, generator=generator) < 0.5).float()
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        keep = torch.rand(n, generator=generator) < 0.7
        mask[rows[keep]] = True
        return mask

    def randomise_supported(self, generator):
        h = self.engine.state.h_tensor
        n = len(self.live)
        rows = self.live
        edge = torch.tensor([0.0, 10.0, 50.0, 89.9, 89.95, 89.99, 90.0, 95.0, 99.0, -3.0])
        for col in (cfg.HUNGER, cfg.THIRST, cfg.HP, cfg.MOOD):
            values = torch.rand(n, generator=generator) * 98.0
            pick = torch.rand(n, generator=generator) < 0.35
            values[pick] = edge[torch.randint(0, len(edge), (int(pick.sum()),), generator=generator)]
            if col in (cfg.HP, cfg.MOOD):
                values = values.clamp(0.0, 100.0)
            h[rows, col] = values
        h[rows, cfg.CRITICAL_HEALTH] = (torch.rand(n, generator=generator) < 0.5).float()
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        keep = torch.rand(n, generator=generator) < 0.75
        mask[rows[keep]] = True
        return mask

    def test_install_swaps_the_two_entries_for_one_at_the_first_priority_and_parity_stays_quiet(self):
        self.assertIn(needs.NAME, names(self.engine))
        self.assertNotIn("instinct_hunger", names(self.engine))
        self.assertNotIn("instinct_thirst", names(self.engine))
        self.assertEqual(entry(self.engine, needs.NAME)["priority"], 15)
        self.assertTrue(needs.install(self.engine))                       # idempotent
        self.assertEqual(names(self.engine).count(needs.NAME), 1)
        for _ in range(3):
            self.engine.step()
        self.assertEqual(self.engine.harness.errors, [])

    def test_the_shipped_village_has_scaled_residents_and_runs_on_harness_without_fallback(self):
        scales = driver.needs_scale_vector(self.engine, self.engine.state.h_tensor)
        self.assertIsNotNone(scales)
        self.assertLess(float(scales.min()), 1.0)
        self.assertAlmostEqual(float(scales.min()), 0.015, places=3)

        mock_h = mock.MagicMock(wraps=self.originals[0])
        mock_t = mock.MagicMock(wraps=self.originals[1])
        spy_wrapper = needs.make_instinct_needs(mock_h, mock_t)

        h = self.engine.state.h_tensor
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[self.live] = True
        ctx = {"engine": self.engine, "h_mask": mask}

        world = eh.runtime(self.engine).world
        rev_before = world.revision

        reference = h.clone()
        self.originals[0](ctx, reference)
        self.originals[1](ctx, reference)

        spy_wrapper(ctx, h)

        mock_h.assert_not_called()
        mock_t.assert_not_called()
        self.assertGreater(world.revision, rev_before)
        self.assertTrue(torch.equal(h, reference))

    def test_random_states_match_the_legacy_entries_bit_for_bit(self):
        generator = torch.Generator().manual_seed(1008)
        h = self.engine.state.h_tensor
        self.enterContext(self.unscaled())
        world = eh.runtime(self.engine).world
        revision = world.revision
        for trial in range(200):
            mask = self.randomise(generator)
            reference = h.clone()
            ctx = {"engine": self.engine, "h_mask": mask}
            self.originals[0](ctx, reference)
            self.originals[1](ctx, reference)
            self.wrapper(ctx, h)
            self.assertTrue(torch.equal(h, reference), f"trial {trial}: diverged in columns "
                            f"{(h != reference).any(dim=0).nonzero().flatten().tolist()}")
        self.assertGreater(world.revision, revision)                       # it went through the applier, not the fallback

    def test_repeated_ticks_stay_equal_from_a_starving_start(self):
        h = self.engine.state.h_tensor
        self.enterContext(self.unscaled())
        mask = self.randomise(torch.Generator().manual_seed(7))
        h[self.live, cfg.HUNGER] = 89.0
        h[self.live, cfg.THIRST] = 88.0
        reference = h.clone()
        ctx = {"engine": self.engine, "h_mask": mask}
        for _ in range(400):
            self.originals[0](ctx, reference)
            self.originals[1](ctx, reference)
            self.wrapper(ctx, h)
        self.assertTrue(torch.equal(h, reference))
        self.assertTrue(bool((h[self.live, cfg.HUNGER] <= 100.0).all()))

    def test_random_states_match_legacy_with_mixed_scales_and_apply_effects(self):
        generator = torch.Generator().manual_seed(2026)
        h = self.engine.state.h_tensor
        world = eh.runtime(self.engine).world
        rev_start = world.revision

        mock_h = mock.MagicMock(wraps=self.originals[0])
        mock_t = mock.MagicMock(wraps=self.originals[1])
        spy_wrapper = needs.make_instinct_needs(mock_h, mock_t)

        candidate_scales = torch.tensor([0.0, 0.015, 0.5, 1.0, 1.2])

        for trial in range(200):
            mask = self.randomise_supported(generator)
            if not mask.any():
                continue
            pick_idx = torch.randint(0, len(candidate_scales), (h.shape[0],), generator=generator)
            scales = candidate_scales[pick_idx]

            reference = h.clone()
            ctx = {"engine": self.engine, "h_mask": mask}

            with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
                self.originals[0](ctx, reference)
                self.originals[1](ctx, reference)
                spy_wrapper(ctx, h)

            self.assertTrue(torch.equal(h, reference), f"trial {trial}: diverged in columns "
                            f"{(h != reference).any(dim=0).nonzero().flatten().tolist()}")

        mock_h.assert_not_called()
        mock_t.assert_not_called()
        self.assertGreater(world.revision, rev_start)

    def test_repeated_ticks_stay_equal_with_mixed_scales_from_starving_start(self):
        h = self.engine.state.h_tensor
        generator = torch.Generator().manual_seed(99)
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[self.live] = True

        h[self.live, cfg.HUNGER] = 89.0
        h[self.live, cfg.THIRST] = 88.0
        h[self.live, cfg.HP] = 80.0
        h[self.live, cfg.MOOD] = 70.0

        scales = torch.ones(h.shape[0])
        n = len(self.live)
        scales[self.live[:n // 3]] = 0.015
        scales[self.live[n // 3: 2 * n // 3]] = 0.5
        scales[self.live[2 * n // 3:]] = 1.0

        reference = h.clone()
        ctx = {"engine": self.engine, "h_mask": mask}
        world = eh.runtime(self.engine).world
        rev_before = world.revision

        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            for _ in range(400):
                self.originals[0](ctx, reference)
                self.originals[1](ctx, reference)
                self.wrapper(ctx, h)

        self.assertTrue(torch.equal(h, reference))
        self.assertGreater(world.revision, rev_before)

    def test_scale_zero_behavior(self):
        h = self.engine.state.h_tensor
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[self.live] = True

        h[self.live, cfg.HUNGER] = 89.98
        h[self.live, cfg.THIRST] = 50.0
        h[self.live, cfg.HP] = 80.0
        h[self.live, cfg.CRITICAL_HEALTH] = 0.0

        scales = torch.zeros(h.shape[0])
        reference = h.clone()
        ctx = {"engine": self.engine, "h_mask": mask}

        world = eh.runtime(self.engine).world
        rev_before = world.revision

        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, reference)
            self.originals[1](ctx, reference)
            self.wrapper(ctx, h)

        self.assertGreater(world.revision, rev_before)
        self.assertTrue(torch.equal(h, reference))
        self.assertTrue(torch.allclose(h[self.live, cfg.HUNGER], torch.full((len(self.live),), 89.98)))
        self.assertTrue((h[self.live, cfg.HP] < 80.0).all())
        self.assertTrue((h[self.live, cfg.CRITICAL_HEALTH] == 0.0).all())

    def test_scale_greater_than_one_supported_and_fallback(self):
        h = self.engine.state.h_tensor
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[self.live] = True

        # Supported case: scale 1.5 with values well within 0..100
        h[self.live, cfg.HUNGER] = 40.0
        h[self.live, cfg.THIRST] = 30.0
        h[self.live, cfg.HP] = 100.0
        scales = torch.full((h.shape[0],), 1.5)

        mock_h = mock.MagicMock(wraps=self.originals[0])
        mock_t = mock.MagicMock(wraps=self.originals[1])
        spy_wrapper = needs.make_instinct_needs(mock_h, mock_t)

        world = eh.runtime(self.engine).world
        rev_before = world.revision
        ctx = {"engine": self.engine, "h_mask": mask}
        reference = h.clone()

        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, reference)
            self.originals[1](ctx, reference)
            spy_wrapper(ctx, h)

        mock_h.assert_not_called()
        mock_t.assert_not_called()
        self.assertGreater(world.revision, rev_before)
        self.assertTrue(torch.equal(h, reference))

        # Unrepresentable fallback case: scale 2.0 where hunger would exceed 100.0
        h[self.live, cfg.HUNGER] = 99.98
        h[self.live, cfg.THIRST] = 30.0
        scales_hi = torch.full((h.shape[0],), 2.0)
        reference_hi = h.clone()

        rev_fallback = world.revision
        with mock.patch.object(driver, "needs_scale_vector", return_value=scales_hi):
            self.originals[0](ctx, reference_hi)
            self.originals[1](ctx, reference_hi)
            spy_wrapper(ctx, h)

        mock_h.assert_called_once()
        mock_t.assert_called_once()
        self.assertEqual(world.revision, rev_fallback)
        self.assertTrue(torch.equal(h, reference_hi))
        self.assertTrue((h[self.live, cfg.HUNGER] > 100.0).all())

    def test_critical_state_timing_at_exact_original_sequential_point(self):
        h = self.engine.state.h_tensor
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[self.live] = True
        scales = torch.full((h.shape[0],), 0.015)
        ctx = {"engine": self.engine, "h_mask": mask}

        # Case A: unscaled hunger >= 90 damages HP, scaled hunger < 90, unscaled thirst < 90 -> critical ends 0.0
        h[self.live, cfg.HUNGER] = 89.98
        h[self.live, cfg.THIRST] = 10.0
        h[self.live, cfg.HP] = 80.0
        h[self.live, cfg.CRITICAL_HEALTH] = 0.0
        reference_a = h.clone()

        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, reference_a)
            self.originals[1](ctx, reference_a)
            self.wrapper(ctx, h)

        self.assertTrue(torch.equal(h, reference_a))
        self.assertTrue((h[self.live, cfg.HUNGER] < 90.0).all())
        self.assertTrue((h[self.live, cfg.HP] < 80.0).all())
        self.assertTrue((h[self.live, cfg.CRITICAL_HEALTH] == 0.0).all())

        # Case B: scaled hunger < 90, unscaled thirst >= 90 damages HP, scaled thirst < 90 -> critical ends 1.0
        h[self.live, cfg.HUNGER] = 10.0
        h[self.live, cfg.THIRST] = 89.95
        h[self.live, cfg.HP] = 80.0
        h[self.live, cfg.CRITICAL_HEALTH] = 0.0
        reference_b = h.clone()

        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, reference_b)
            self.originals[1](ctx, reference_b)
            self.wrapper(ctx, h)

        self.assertTrue(torch.equal(h, reference_b))
        self.assertTrue((h[self.live, cfg.THIRST] < 90.0).all())
        self.assertTrue((h[self.live, cfg.HP] < 80.0).all())
        self.assertTrue((h[self.live, cfg.CRITICAL_HEALTH] == 1.0).all())

        # Case C: scaled hunger >= 90 -> critical ends 1.0
        h[self.live, cfg.HUNGER] = 95.0
        h[self.live, cfg.THIRST] = 10.0
        h[self.live, cfg.CRITICAL_HEALTH] = 0.0
        reference_c = h.clone()

        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, reference_c)
            self.originals[1](ctx, reference_c)
            self.wrapper(ctx, h)

        self.assertTrue(torch.equal(h, reference_c))
        self.assertTrue((h[self.live, cfg.CRITICAL_HEALTH] == 1.0).all())

    def test_calendar_rate_scaling_on_and_off(self):
        h = self.engine.state.h_tensor
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[self.live] = True
        scales = torch.full((h.shape[0],), 0.015)
        ctx = {"engine": self.engine, "h_mask": mask}

        # Calendar off: rate multipliers are 1.0
        with mock.patch.dict(os.environ, {cal.FLAG: "0"}):
            self.assertFalse(cal.calendar_enabled())
            h[self.live, cfg.HUNGER] = 50.0
            h[self.live, cfg.THIRST] = 50.0
            reference_off = h.clone()
            with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
                self.originals[0](ctx, reference_off)
                self.originals[1](ctx, reference_off)
                self.wrapper(ctx, h)
            self.assertTrue(torch.equal(h, reference_off))

        # Calendar on: rate multipliers are active (needs: 0.21, starvation: 0.0015, damage_recovery: 0.2)
        with mock.patch.dict(os.environ, {cal.FLAG: "1"}):
            self.assertTrue(cal.calendar_enabled())
            h[self.live, cfg.HUNGER] = 89.98
            h[self.live, cfg.THIRST] = 89.95
            h[self.live, cfg.HP] = 80.0
            reference_on = h.clone()
            with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
                self.originals[0](ctx, reference_on)
                self.originals[1](ctx, reference_on)
                self.wrapper(ctx, h)
            self.assertTrue(torch.equal(h, reference_on))

    def test_edge_cases_and_fallback_documented(self):
        h = self.engine.state.h_tensor
        initial = h.clone()
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[self.live] = True
        ctx = {"engine": self.engine, "h_mask": mask}
        world = eh.runtime(self.engine).world

        mock_h = mock.MagicMock(wraps=self.originals[0])
        mock_t = mock.MagicMock(wraps=self.originals[1])
        spy = needs.make_instinct_needs(mock_h, mock_t)

        # 1. Negative scale triggers fallback
        scales_neg = torch.full((h.shape[0],), -0.5)
        ref = h.clone()
        rev_before = world.revision
        with mock.patch.object(driver, "needs_scale_vector", return_value=scales_neg):
            self.originals[0](ctx, ref)
            self.originals[1](ctx, ref)
            spy(ctx, h)
        mock_h.assert_called_once()
        mock_t.assert_called_once()
        self.assertEqual(world.revision, rev_before)
        self.assertTrue(torch.equal(h, ref))

        mock_h.reset_mock()
        mock_t.reset_mock()

        # 2. Non-finite scale (NaN) triggers fallback
        scales_nan = torch.full((h.shape[0],), float("nan"))
        ref = h.clone()
        rev_before = world.revision
        with mock.patch.object(driver, "needs_scale_vector", return_value=scales_nan):
            self.originals[0](ctx, ref)
            self.originals[1](ctx, ref)
            spy(ctx, h)
        mock_h.assert_called_once()
        mock_t.assert_called_once()
        self.assertEqual(world.revision, rev_before)
        torch.testing.assert_close(h, ref, rtol=0, atol=0, equal_nan=True)
        # Keep the following boundary cases independent of the NaN fixture.
        h.copy_(initial)

        mock_h.reset_mock()
        mock_t.reset_mock()

        # 3. HP > 100 when taking starvation damage triggers fallback
        h[self.live, cfg.HUNGER] = 95.0
        h[self.live, cfg.HP] = 110.0
        scales = torch.full((h.shape[0],), 0.015)
        ref = h.clone()
        rev_before = world.revision
        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, ref)
            self.originals[1](ctx, ref)
            spy(ctx, h)
        mock_h.assert_called_once()
        mock_t.assert_called_once()
        self.assertEqual(world.revision, rev_before)
        self.assertTrue(torch.equal(h, ref))

        mock_h.reset_mock()
        mock_t.reset_mock()

        # 4. Missing stable human UID triggers fallback
        h[self.live, cfg.HUNGER] = 50.0
        h[self.live, cfg.HP] = 80.0
        corrupt_uids = list(self.engine._human_uid_by_slot)
        corrupt_uids[int(self.live[0])] = None
        ref = h.clone()
        rev_before = world.revision
        with mock.patch.object(self.engine, "_human_uid_by_slot", corrupt_uids), \
             mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, ref)
            self.originals[1](ctx, ref)
            spy(ctx, h)
        mock_h.assert_called_once()
        mock_t.assert_called_once()
        self.assertEqual(world.revision, rev_before)
        self.assertTrue(torch.equal(h, ref))

        mock_h.reset_mock()
        mock_t.reset_mock()

        # 5. Negative hunger/thirst is supported without fallback (unbounded below)
        h[self.live, cfg.HUNGER] = -3.0
        h[self.live, cfg.THIRST] = -3.0
        h[self.live, cfg.HP] = 80.0
        ref = h.clone()
        rev_before = world.revision
        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, ref)
            self.originals[1](ctx, ref)
            spy(ctx, h)
        mock_h.assert_not_called()
        mock_t.assert_not_called()
        self.assertGreater(world.revision, rev_before)
        self.assertTrue(torch.equal(h, ref))
        self.assertTrue((h[self.live, cfg.HUNGER] < 0.0).all())

    def test_inactive_rows_remain_untouched(self):
        h = self.engine.state.h_tensor
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        # Only activate the first live resident
        active_slot = int(self.live[0])
        mask[active_slot] = True

        scales = torch.full((h.shape[0],), 0.015)
        before_all = h.clone()
        reference = h.clone()
        ctx = {"engine": self.engine, "h_mask": mask}

        with mock.patch.object(driver, "needs_scale_vector", return_value=scales):
            self.originals[0](ctx, reference)
            self.originals[1](ctx, reference)
            self.wrapper(ctx, h)

        self.assertTrue(torch.equal(h, reference))
        inactive_mask = ~mask
        self.assertTrue(torch.equal(h[inactive_mask], before_all[inactive_mask]))

    def test_an_empty_mask_changes_nothing(self):
        h = self.engine.state.h_tensor
        self.enterContext(self.unscaled())
        before = h.clone()
        self.wrapper({"engine": self.engine, "h_mask": torch.zeros(h.shape[0], dtype=torch.bool)}, h)
        self.assertTrue(torch.equal(h, before))

    def test_the_flag_is_off_unless_both_switches_are_set(self):
        with mock.patch.dict(os.environ, {needs.FLAG: "0"}):
            self.assertFalse(needs.enabled())
        with mock.patch.dict(os.environ, {needs.FLAG: "1", eh.FLAG: "0"}):
            self.assertFalse(needs.enabled())


if __name__ == "__main__":
    unittest.main()
