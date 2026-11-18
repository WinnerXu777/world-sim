"""WIP-D part 2: terrain-changing disaster powers keep the live map geometry in sync (EDEN_GOD_POWER_PORTS=1).

The legacy disaster functions call ``map_geo.geo_mutate(slot)`` after every terrain conversion (earthquake rubble -> barren,
volcano -> lava, flood -> sea): it re-registers the slot's geometry (tile lookup) and bumps ``map_geo.geo_version``, which
the client map delta and the space columns key on. The harness ports change ``entities.type`` through atomic effects, so on
the live ``EngineWorld`` the same sync has to follow a successful apply. These tests run on the real engine
(``playable_village``) and compare each power with its legacy tool on clones of the same tensors.

The sync must only run for those three powers, only under EDEN_GOD_POWER_PORTS, and never on the per-tick path.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import torch

from test_startup_preservation import backend  # noqa: F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
import instincts_and_tools as legacy
import map_geo
from harness import engine_hooks
from harness import powers as pw
from harness.adapter import EngineWorld
from systems.nature.disasters import apply_flood as nature_apply_flood

FLAG = {"EDEN_GOD_POWER_PORTS": "1"}


class LiveGeoSyncBase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._env = mock.patch.dict(os.environ, FLAG)
        self._env.start()
        await super().asyncSetUp()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.engine = backend.engine
        self.reg = pw.build_registry()
        self.world = EngineWorld(self.engine, seed=1008)
        self.m = self.engine.state.m_tensor
        self.h = self.engine.state.h_tensor
        self.grass = self._slot_of_type(cfg.M_GRASS)
        self.forest = self._slot_of_type(cfg.M_FOREST)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self._env.stop()

    def _slot_of_type(self, entity_type: int) -> int:
        slots = [s for s in sorted(map_geo.MAP_GEO) if int(self.m[s, cfg.M_TYPE]) == entity_type]
        self.assertTrue(slots, f"playable_village has no type {entity_type} entity with geometry")
        return slots[0]

    def _centre(self, slot: int) -> list:
        return [float(self.m[slot, cfg.CX]), float(self.m[slot, cfg.CY])]

    def _legacy_on_clones(self, tool, **kwargs):
        """Run a legacy tool on clones of the live tensors; return (geo_version delta, entity tensor, human tensor, population)."""
        h = self.h.clone()
        m = self.m.clone()
        pop = [int(self.engine._pop_count[0])]
        before = int(map_geo.geo_version)
        tool({"h_mask": h[:, cfg.TYPE] > 0}, m_tensor=m, h_tensor=h, pop_count_ref=pop, device="cpu", **kwargs)
        return int(map_geo.geo_version) - before, m, h, pop[0]

    def _harness_call(self, name: str, args: dict, **kwargs):
        self.engine._force_map_refresh = False
        before = int(map_geo.geo_version)
        res = pw.call(self.world, name, args, registry=self.reg, **kwargs)
        return res, int(map_geo.geo_version) - before


class TerrainPowersSyncGeometry(LiveGeoSyncBase):
    def test_earthquake_rubble_syncs_geometry_like_legacy(self):
        centre = self._centre(self.grass)
        tiles_before = set(map_geo.tiles_of(self.grass))
        with mock.patch("random.random", return_value=0.0):          # legacy: every entity in radius turns to rubble
            legacy_delta, legacy_m, _, _ = self._legacy_on_clones(
                legacy.tool_earthquake, center_x=centre[0], center_y=centre[1], radius=30.0)
        res, delta = self._harness_call("earthquake", {"center": centre, "radius": 30.0, "rubble_draws": [0.0] * 16})
        self.assertTrue(res.ok, res.reason)
        rubble = res.plan.preview["rubble_entities"]
        self.assertIn(self.engine._entity_uid_by_slot[self.grass], rubble)
        self.assertGreaterEqual(legacy_delta, 1)
        self.assertEqual(delta, legacy_delta)                         # one geo_mutate per converted slot, as legacy
        self.assertEqual(delta, len(rubble))
        self.assertTrue(torch.equal(self.m[:, cfg.M_TYPE], legacy_m[:, cfg.M_TYPE]))
        self.assertEqual(int(self.m[self.grass, cfg.M_TYPE]), cfg.M_BARREN)
        self.assertEqual(set(map_geo.tiles_of(self.grass)), tiles_before)   # same footprint, re-registered
        self.assertTrue(self.engine._force_map_refresh)

    def test_volcano_lava_syncs_geometry_like_legacy(self):
        centre = self._centre(self.grass)
        legacy_delta, legacy_m, legacy_h, legacy_pop = self._legacy_on_clones(
            legacy.tool_volcanic_eruption, center_x=centre[0], center_y=centre[1], entity_count_ref=[0])
        res, delta = self._harness_call("volcanic_eruption", {"center": centre})
        self.assertTrue(res.ok, res.reason)
        self.assertGreaterEqual(legacy_delta, 1)
        self.assertEqual(delta, legacy_delta)
        self.assertTrue(torch.equal(self.m[:, cfg.M_TYPE], legacy_m[:, cfg.M_TYPE]))
        self.assertEqual(int(self.m[self.grass, cfg.M_TYPE]), cfg.M_LAVA)
        self.assertTrue(self.engine._force_map_refresh)
        # Death consequences of the inner zone match legacy kill_humans: TYPE 0 rows and the population counter.
        self.assertTrue(torch.equal(self.h[:, cfg.TYPE], legacy_h[:, cfg.TYPE]))
        self.assertEqual(int(self.engine._pop_count[0]), legacy_pop)
        self.assertLess(legacy_pop, 4)

    def test_flood_sea_syncs_geometry_like_legacy(self):
        self.m[self.forest, cfg.M_TYPE] = float(cfg.M_LAKE)             # setup: the forest becomes a lake the flood spreads from
        # The legacy function itself: tool_flood swallows expand_radius (**_) and always floods at 100.
        def legacy_flood(ctx, m_tensor, h_tensor, pop_count_ref, device, expand_radius):
            return nature_apply_flood(ctx, h_tensor, m_tensor, device=device, expand_radius=expand_radius)
        legacy_delta, legacy_m, _, _ = self._legacy_on_clones(legacy_flood, expand_radius=150.0)
        res, delta = self._harness_call("flood", {"expand_radius": 150.0})
        self.assertTrue(res.ok, res.reason)
        self.assertGreaterEqual(legacy_delta, 1)
        self.assertEqual(delta, legacy_delta)
        self.assertEqual(delta, len(res.plan.preview["flooded_entities"]))
        self.assertTrue(torch.equal(self.m[:, cfg.M_TYPE], legacy_m[:, cfg.M_TYPE]))
        self.assertEqual(int(self.m[self.grass, cfg.M_TYPE]), cfg.M_SEA)
        self.assertTrue(self.engine._force_map_refresh)

    def test_command_path_syncs_geometry(self):
        """End to end through the harness_power command executor (engine_hooks.execute_power), the route a client uses."""
        centre = self._centre(self.grass)
        rt = engine_hooks.runtime(self.engine)
        before = int(map_geo.geo_version)
        with mock.patch.object(rt, "registry", self.reg):
            out = engine_hooks.execute_power(self.engine, None, {"power": "earthquake",
                                                                 "args": {"center": centre, "radius": 30.0, "rubble_draws": [0.0] * 8}})
        self.assertTrue(out["ok"], out)
        self.assertGreaterEqual(len(out["preview"]["rubble_entities"]), 1)
        self.assertEqual(int(map_geo.geo_version) - before, len(out["preview"]["rubble_entities"]))
        self.assertEqual(int(self.m[self.grass, cfg.M_TYPE]), cfg.M_BARREN)


class NoSyncOutsideTerrainChanges(LiveGeoSyncBase):
    def test_non_terrain_powers_leave_geometry_alone(self):
        before = int(map_geo.geo_version)
        res, _ = self._harness_call("wildfire", {"center": self._centre(self.forest), "radius": 10.0})
        self.assertTrue(res.ok, res.reason)
        res, _ = self._harness_call("storm", {"center": self._centre(self.grass), "radius": 200.0})
        self.assertTrue(res.ok, res.reason)
        res, _ = self._harness_call("bless", {})
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(int(map_geo.geo_version), before)

    def test_dry_run_and_refusal_do_not_sync(self):
        centre = self._centre(self.grass)
        types = self.m[:, cfg.M_TYPE].clone()
        res, delta = self._harness_call("earthquake", {"center": centre, "radius": 30.0, "rubble_draws": [0.0] * 8}, dry_run=True)
        self.assertTrue(res.ok)
        self.assertEqual(delta, 0)
        res, delta = self._harness_call("earthquake", {"center": [5.0, 895.0], "radius": 1.0})
        self.assertEqual(res.reason, "no_targets")
        self.assertEqual(delta, 0)
        self.assertTrue(torch.equal(self.m[:, cfg.M_TYPE], types))

    def test_flag_off_never_syncs(self):
        """A plan made while the flag was on and applied after it went off changes the tensors but triggers no sync."""
        centre = self._centre(self.grass)
        plan = pw.plan(self.world, "earthquake", {"center": centre, "radius": 30.0, "rubble_draws": [0.0] * 8}, registry=self.reg)
        self.assertTrue(plan.ok)
        before = int(map_geo.geo_version)
        with mock.patch.dict(os.environ, {"EDEN_GOD_POWER_PORTS": "0"}):
            res = pw.apply(self.world, plan, registry=self.reg)
            self.assertTrue(res.ok)
            self.assertEqual(int(self.m[self.grass, cfg.M_TYPE]), cfg.M_BARREN)
            self.assertEqual(int(map_geo.geo_version), before)
            self.assertEqual(set(pw.build_registry().powers), {
                "set_mood", "plague", "bless", "calm_area", "panic_area", "baby_boom", "cull", "enlighten",
                "bounty_area", "scarcity_area"})


if __name__ == "__main__":
    unittest.main()
