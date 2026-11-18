"""G-005 step 2: authored-map resources become tensor rows behind EDEN_MAP_RESOURCES (default off, then nothing changes)."""
import json
import os
import tempfile
import uuid
import unittest
from pathlib import Path
from unittest import mock

import torch

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation, FIXTURES
from test_map_entities import TINY, rows_by_id
from test_startup_preservation import _test_storage
from authored_village import load_village_maps
from persistence.sessions import GameSessions
import genesis_config as cfg
from systems.map import resources
from systems.map.authored import instantiate_authored_entities, upgrade_authored_entities
from systems.movement.map_contract import register_map_file
from systems.nature import ecology

NAME = "tiny_village_resources"
EXTRA = [
    {"id": "bush_01", "kind": "berry_bush", "interactive": True, "position": [5, 9], "sprite": "sprites/chest.png",
     "resource": "berries", "amount": 24, "cap": 40, "regrow": 0.5, "radius": 6},
    {"id": "well_01", "kind": "well", "interactive": True, "position": [2, 9], "sprite": "sprites/chest.png"},
    {"id": "plot_01", "kind": "farm_plot", "interactive": True, "position": [3, 11], "sprite": "sprites/chest.png", "resource": "crops", "amount": 10},
    {"id": "ore_01", "kind": "ore_vein", "interactive": True, "position": [12, 12], "sprite": "sprites/chest.png",
     "resource": "ore", "amount": 500, "regrow": 0.25},
    {"id": "shelter_01", "kind": "shelter", "interactive": True, "position": [14, 10], "sprite": "sprites/chest.png", "capacity": 6},
    {"id": "bed_01", "kind": "bed", "interactive": True, "position": [9, 5], "sprite": "sprites/chest.png", "capacity": 2},
    {"id": "crate_01", "kind": "crate", "interactive": True, "position": [13, 5], "sprite": "sprites/chest.png",
     "stock": {"rations": 3, "wood_bundle": 5}},
]


def write_map(tmp):
    data = json.loads(TINY.read_text(encoding="utf-8"))
    data["map_id"] = NAME
    data["entities"] = data["entities"] + EXTRA
    path = Path(tmp) / f"{NAME}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


async def world(tmp, flag):
    register_map_file(write_map(tmp), name=NAME, base_dir=FIXTURES)
    backend.engine.reset_world()
    with mock.patch.dict(os.environ, {resources.FLAG: "1"} if flag else {}, clear=False):
        if not flag:
            os.environ.pop(resources.FLAG, None)
        await backend.create_genesis(backend.engine, map_name=NAME)
    return backend.engine


def col(engine, rows, uid, c):
    return float(engine.state.m_tensor[rows[uid], c])


class FlagOffTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_flag_off_everything_is_inert_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, False)
            rows = rows_by_id(engine)
            m = engine.state.m_tensor
            for uid in ("bush_01", "well_01", "plot_01", "ore_01", "shelter_01", "bed_01"):
                self.assertEqual(int(m[rows[uid], cfg.M_TYPE]), int(cfg.M_MAP_OBJECT), uid)
                self.assertNotIn(rows[uid], backend.map_geo.MAP_GEO, uid)
            self.assertEqual(int(m[rows["crate_01"], cfg.M_TYPE]), int(cfg.M_STORAGE_CASE))
            self.assertFalse(backend.has_item(backend.get_container_inventory(engine.inventory_state, "crate_01"), "wood_bundle", 1))
            self.assertEqual(upgrade_authored_entities(engine, NAME), [])

    def test_enabled_reads_the_environment_at_call_time(self):
        with mock.patch.dict(os.environ, {resources.FLAG: "1"}):
            self.assertTrue(resources.enabled())
        with mock.patch.dict(os.environ, {resources.FLAG: "0"}):
            self.assertFalse(resources.enabled())


class FlagOnTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_types_columns_and_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, True)
            rows = rows_by_id(engine)
            m = engine.state.m_tensor
            self.assertEqual(int(m[rows["bush_01"], cfg.M_TYPE]), int(cfg.M_RESOURCE_NODE))
            self.assertEqual(col(engine, rows, "bush_01", cfg.M_NODE_KIND), 1.0)
            self.assertEqual(col(engine, rows, "bush_01", cfg.M_RESOURCE_FOOD), 24.0)
            self.assertEqual(col(engine, rows, "bush_01", cfg.M_NODE_CAP), 40.0)
            self.assertEqual(col(engine, rows, "bush_01", cfg.M_DEPLETED_TICK), -1.0)
            self.assertAlmostEqual(col(engine, rows, "bush_01", cfg.M_GROWTH_RATE), 0.5, places=6)
            self.assertEqual(col(engine, rows, "bush_01", cfg.SCALE), 6.0)
            self.assertEqual(int(m[rows["well_01"], cfg.M_TYPE]), int(cfg.M_WELL))
            self.assertEqual(col(engine, rows, "well_01", cfg.S_BUILD_PROGRESS), 100.0)
            self.assertGreater(col(engine, rows, "well_01", cfg.M_RESOURCE_WATER), 0.0)
            self.assertEqual(int(m[rows["plot_01"], cfg.M_TYPE]), int(cfg.M_FARM))
            self.assertEqual(col(engine, rows, "plot_01", cfg.M_RESOURCE_FOOD), 10.0)
            self.assertEqual(int(m[rows["ore_01"], cfg.M_TYPE]), int(cfg.M_RESOURCE_NODE))
            self.assertEqual(col(engine, rows, "ore_01", cfg.M_NODE_STOCK), 500.0)
            self.assertEqual(col(engine, rows, "ore_01", cfg.M_RESOURCE_FOOD), 0.0)
            self.assertEqual(int(m[rows["shelter_01"], cfg.M_TYPE]), int(cfg.M_HOUSE))
            self.assertEqual(col(engine, rows, "shelter_01", cfg.S_SHELTER_CAP), 6.0)
            self.assertEqual(int(m[rows["bed_01"], cfg.M_TYPE]), int(cfg.M_MAP_OBJECT))  # kind-based, stays inert
            self.assertEqual(int(m[rows["forge_01"], cfg.M_TYPE]), int(cfg.M_MAP_OBJECT))
            for uid in ("bush_01", "well_01", "plot_01", "ore_01", "shelter_01"):
                self.assertIn(rows[uid], backend.map_geo.MAP_GEO, uid)
            self.assertNotIn(rows["bed_01"], backend.map_geo.MAP_GEO)
            self.assertNotIn(rows["forge_01"], backend.map_geo.MAP_GEO)

    async def test_storage_stock_is_seeded_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, True)
            crate = backend.get_container_inventory(engine.inventory_state, "crate_01")
            self.assertTrue(backend.has_item(crate, "rations", 3))
            self.assertTrue(backend.has_item(crate, "wood_bundle", 5))
            self.assertFalse(backend.has_item(crate, "wood_bundle", 6))
            self.assertEqual(upgrade_authored_entities(engine, NAME), [])
            self.assertFalse(backend.has_item(backend.get_container_inventory(engine.inventory_state, "crate_01"), "wood_bundle", 6))

    async def test_food_resolver_finds_the_berry_bush(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, True)
            rows = rows_by_id(engine)
            hit = engine._resolve_task_resource_target(5.0, 9.5, "food", radius=40.0)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["slot"], rows["bush_01"])

    async def test_completed_structures_are_hidden_from_task_resolvers_by_the_flood_alias(self):
        """Known legacy quirk, pinned so a fix is a deliberate change: S_BUILD_PROGRESS and M_FLOODED are the same column (9) and
        ``best_resource_entity`` skips rows with M_FLOODED > 0, so a completed well or farm (build 100) is never a task target.
        The water cycle and the instincts are not affected; resource nodes (no build column) are found."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, True)
            rows = rows_by_id(engine)
            self.assertEqual(col(engine, rows, "well_01", cfg.M_FLOODED), 100.0)
            self.assertIsNone(engine._resolve_task_resource_target(2.0, 9.5, "water", radius=40.0))

    async def test_regrow_edible_and_material_nodes_up_to_the_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, True)
            rows = rows_by_id(engine)
            m = engine.state.m_tensor
            m[rows["bush_01"], cfg.M_RESOURCE_FOOD] = 0.0
            m[rows["bush_01"], cfg.M_DEPLETED_TICK] = 7.0
            m[rows["ore_01"], cfg.M_NODE_STOCK] = 499.9
            ecology.apply_node_regrow(m)
            self.assertAlmostEqual(col(engine, rows, "bush_01", cfg.M_RESOURCE_FOOD), 0.5, places=5)
            self.assertEqual(col(engine, rows, "bush_01", cfg.M_DEPLETED_TICK), -1.0)  # recovered
            self.assertAlmostEqual(col(engine, rows, "ore_01", cfg.M_NODE_STOCK), 500.0, places=4)  # capped at max(amount, default)
            for _ in range(200):
                ecology.apply_node_regrow(m)
            self.assertAlmostEqual(col(engine, rows, "bush_01", cfg.M_RESOURCE_FOOD), 40.0, places=4)
            self.assertAlmostEqual(col(engine, rows, "ore_01", cfg.M_NODE_STOCK), 500.0, places=4)

    async def test_no_regrow_without_rate_or_while_burning(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, True)
            rows = rows_by_id(engine)
            m = engine.state.m_tensor
            m[rows["bush_01"], cfg.M_RESOURCE_FOOD] = 1.0
            m[rows["bush_01"], cfg.M_BURNING] = 1.0
            m[rows["ore_01"], cfg.M_GROWTH_RATE] = 0.0
            m[rows["ore_01"], cfg.M_NODE_STOCK] = 10.0
            ecology.apply_node_regrow(m)
            self.assertEqual(col(engine, rows, "bush_01", cfg.M_RESOURCE_FOOD), 1.0)
            self.assertEqual(col(engine, rows, "ore_01", cfg.M_NODE_STOCK), 10.0)

    async def test_engine_steps_with_nodes_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, True)
            rows = rows_by_id(engine)
            engine.state.m_tensor[rows["bush_01"], cfg.M_RESOURCE_FOOD] = 1.0
            for _ in range(5):
                engine.step()
            self.assertGreater(col(engine, rows, "bush_01", cfg.M_RESOURCE_FOOD), 1.0)

    async def test_upgrade_brings_inert_rows_up_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = await world(tmp, False)
            rows = rows_by_id(engine)
            with mock.patch.dict(os.environ, {resources.FLAG: "1"}):
                done = upgrade_authored_entities(engine, NAME)
                self.assertEqual(sorted(done), ["bush_01", "ore_01", "plot_01", "shelter_01", "well_01"])
                m = engine.state.m_tensor
                self.assertEqual(int(m[rows["bush_01"], cfg.M_TYPE]), int(cfg.M_RESOURCE_NODE))
                self.assertEqual(col(engine, rows, "bush_01", cfg.M_RESOURCE_FOOD), 24.0)
                self.assertIn(rows["bush_01"], backend.map_geo.MAP_GEO)
                snapshot = m.clone()
                self.assertEqual(upgrade_authored_entities(engine, NAME), [])
                self.assertTrue(bool((snapshot == m).all()))
                crate = backend.get_container_inventory(engine.inventory_state, "crate_01")
                self.assertTrue(backend.has_item(crate, "wood_bundle", 5))
                self.assertFalse(backend.has_item(crate, "wood_bundle", 6))


class RestoreTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """world_snapshot.restore calls upgrade_authored_entities: an old (flag off) save upgrades once with the flag on, never with it off."""
    RESOURCE_IDS = ("village:well", "village:wood_pile", "village:stone_pile", "village:berry_patch", "smith:iron_pile")

    async def sessions(self):
        load_village_maps()
        return GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                            _test_storage / "map_resources" / uuid.uuid4().hex, backend.create_genesis, 906, map_name="starter_village")

    async def reload(self, sessions, save_id, flag):
        backend.engine.reset_world()
        with mock.patch.dict(os.environ, {resources.FLAG: "1"} if flag else {}, clear=False):
            if not flag:
                os.environ.pop(resources.FLAG, None)
            await sessions.continue_world(save_id)
        return backend.engine

    def types(self, engine):
        rows = rows_by_id(engine)
        return {uid: int(engine.state.m_tensor[rows[uid], cfg.M_TYPE]) for uid in self.RESOURCE_IDS if uid in rows}

    async def test_flag_off_save_restores_identically_with_the_flag_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(resources.FLAG, None)
            sessions = await self.sessions()
            await sessions.new("Resources")
            before = backend.engine.state.m_tensor.clone()
            ids = list(backend.engine._entity_uid_by_slot)
            save_id = sessions.active_id
        engine = await self.reload(sessions, save_id, False)
        self.assertTrue(bool((before == engine.state.m_tensor).all()))
        self.assertEqual(ids, list(engine._entity_uid_by_slot))
        self.assertEqual(set(self.types(engine).values()), {int(cfg.M_MAP_OBJECT)})

    async def test_flag_off_save_upgrades_once_with_the_flag_on(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(resources.FLAG, None)
            sessions = await self.sessions()
            await sessions.new("Resources")
            save_id = sessions.active_id
            old = backend.engine.state.m_tensor.clone()
        engine = await self.reload(sessions, save_id, True)
        got = self.types(engine)
        self.assertEqual(got["village:well"], int(cfg.M_WELL))
        for uid in ("village:wood_pile", "village:stone_pile", "village:berry_patch", "smith:iron_pile"):
            self.assertEqual(got[uid], int(cfg.M_RESOURCE_NODE), uid)
        rows = rows_by_id(engine)
        self.assertIn(rows["village:berry_patch"], backend.map_geo.MAP_GEO)
        self.assertEqual(col(engine, rows, "village:berry_patch", cfg.M_RESOURCE_FOOD), 40.0)
        changed = (old != engine.state.m_tensor).any(dim=1).nonzero(as_tuple=False).flatten().tolist()
        self.assertEqual(sorted(changed), sorted(rows[u] for u in self.RESOURCE_IDS))      # only the five resource rows changed
        # a world already upgraded restores unchanged (the upgrade is idempotent)
        after = engine.state.m_tensor.clone()
        self.assertEqual(upgrade_authored_entities(engine, "starter_village"), [])
        self.assertTrue(bool((after == engine.state.m_tensor).all()))

    async def test_a_flag_on_world_restores_identically(self):
        with mock.patch.dict(os.environ, {resources.FLAG: "1"}, clear=False):
            sessions = await self.sessions()
            await sessions.new("Resources")
            before = backend.engine.state.m_tensor.clone()
            save_id = sessions.active_id
        engine = await self.reload(sessions, save_id, True)
        self.assertTrue(bool((before == engine.state.m_tensor).all()))


class SpecTests(unittest.TestCase):
    def test_defaults_for_a_bare_kind(self):
        spec = resources.spec_for({"kind": "berry_bush"})
        self.assertEqual(spec["m_type"], cfg.M_RESOURCE_NODE)
        self.assertEqual(spec["col_vals"][cfg.M_RESOURCE_FOOD], 40.0)

    def test_amount_above_the_column_is_clamped_for_food_only(self):
        spec = resources.spec_for({"kind": "berry_bush", "resource": {"name": "berries", "amount": 5000.0}})
        self.assertEqual(spec["col_vals"][cfg.M_RESOURCE_FOOD], float(cfg.MAX_ENTITY_FOOD))
        ore = resources.spec_for({"kind": "ore_vein", "resource": {"name": "ore", "amount": 5000.0}})
        self.assertEqual(ore["col_vals"][cfg.M_NODE_STOCK], 5000.0)

    def test_inert_and_storage_kinds_have_no_spec(self):
        for kind in ("forge", "bed", "hearth", "chest", "door"):
            self.assertIsNone(resources.spec_for({"kind": kind}), kind)

    def test_stock_only_for_storage_kinds(self):
        self.assertEqual(resources.stock_of({"kind": "crate", "resource": {"stock": {"a": 1}}}), {"a": 1})
        self.assertEqual(resources.stock_of({"kind": "forge", "resource": {"stock": {"a": 1}}}), {})


if __name__ == "__main__":
    unittest.main()
