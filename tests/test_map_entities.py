"""Authored map entities become real tensor entities with the map-file id as the backend id (G6)."""
from authored_village import MAP_FILES, load_village_maps
import json
import unittest
import uuid
from pathlib import Path

from test_startup_preservation import backend, _test_storage
import genesis_config as cfg
from test_map_contract import AsyncRegistryIsolation, FIXTURES, SMITH
from persistence import codec, world_snapshot
from persistence.sessions import GameSessions
from systems.map.authored import entity_type_for_kind, instantiate_authored_entities
from systems.movement.map_contract import (get_map_contract, load_from_environment, map_entity, register_map_file, wall_owners)
from systems.movement.spatial import map_wall_boxes, map_wall_boxes_ignoring, world_contract

ROOT = Path(__file__).resolve().parents[1]
REAL_VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
REAL_SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"
TINY = FIXTURES / "tiny_village.json"


def rows_by_id(engine):
    m = engine.state.m_tensor
    return {uid: slot for slot, uid in enumerate(engine._entity_uid_by_slot) if uid and int(m[slot, backend.M_TYPE]) > 0}


async def authored_world(path=TINY, name=None):
    register_map_file(path, name=name, base_dir=FIXTURES if path.parent == FIXTURES else ROOT / "myassets")
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name=name or json.loads(path.read_text(encoding="utf-8"))["map_id"])
    return backend.engine


class EntityInstantiationTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_interactive_entities_get_the_map_file_ids_and_types(self):
        engine = await authored_world()
        rows = rows_by_id(engine)
        m = engine.state.m_tensor
        self.assertEqual(int(m[rows["forge_01"], backend.M_TYPE]), int(cfg.M_MAP_OBJECT))
        self.assertEqual(int(m[rows["chest_01"], backend.M_TYPE]), int(backend.M_STORAGE_CASE))
        self.assertAlmostEqual(float(m[rows["forge_01"], backend.CX]), 8.5, places=5)  # tensors are float32
        self.assertAlmostEqual(float(m[rows["forge_01"], backend.CY]), 3.6, places=5)
        self.assertEqual((float(m[rows["chest_01"], backend.CX]), float(m[rows["chest_01"], backend.CY])), (12.0, 4.5))
        self.assertNotIn("tree_deco_01", rows)  # decorative entities stay in the map file
        self.assertFalse([uid for uid in rows if uid.startswith("e_") and uid not in ("forge_01", "chest_01")])

    async def test_ids_are_not_the_generated_pattern(self):
        engine = await authored_world()
        self.assertNotRegex("forge_01", r"^e_\d{6}$")
        self.assertEqual(engine._entity_uid_by_slot.count("forge_01"), 1)

    async def test_instantiation_is_idempotent(self):
        engine = await authored_world()
        before = (list(engine._entity_uid_by_slot), engine.state.m_tensor.clone(), engine._entity_count_ref[0])
        self.assertEqual(instantiate_authored_entities(engine, "tiny_village"), [])
        self.assertEqual(before[0], list(engine._entity_uid_by_slot))
        self.assertTrue(bool((before[1] == engine.state.m_tensor).all()))
        self.assertEqual(before[2], engine._entity_count_ref[0])

    async def test_ids_survive_ticks(self):
        engine = await authored_world()
        for _ in range(5):
            engine.step()
        rows = rows_by_id(engine)
        self.assertIn("forge_01", rows)
        self.assertIn("chest_01", rows)

    async def test_storage_gets_a_container_and_the_first_one_is_the_seeded_starter(self):
        engine = await authored_world()
        self.assertEqual(engine._starter_storage_case_entity_id, "chest_01")
        container = backend.get_container_inventory(engine.inventory_state, "chest_01")
        self.assertIsNotNone(container)
        self.assertTrue(backend.has_item(container, "rations", 4))
        self.assertIn("chest_01", engine._inventory_seeded_containers)

    async def test_only_storage_has_map_geometry_objects_stay_inert(self):
        engine = await authored_world()
        rows = rows_by_id(engine)
        self.assertIn(rows["chest_01"], backend.map_geo.MAP_GEO)
        self.assertNotIn(rows["forge_01"], backend.map_geo.MAP_GEO)
        exported = engine._export_map_entities()
        self.assertIn("chest_01", exported)
        self.assertNotIn("forge_01", exported)

    async def test_legacy_worlds_are_untouched(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        m = backend.engine.state.m_tensor
        self.assertEqual(int((m[:, backend.M_TYPE] == cfg.M_MAP_OBJECT).sum()), 0)
        self.assertEqual(entity_type_for_kind("storage"), backend.M_STORAGE_CASE)
        self.assertEqual(entity_type_for_kind("forge"), cfg.M_MAP_OBJECT)

    async def test_walk_through_the_engine_loop_with_instantiated_entities(self):
        engine = await authored_world()
        for _ in range(20):
            engine.step()
        self.assertTrue(engine.world_loaded)


class RealMapsEntityTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_all_four_real_maps_instantiate_every_interactive_entity_once(self):
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        engine = backend.engine
        wanted = []
        for path in MAP_FILES:
            wanted += [e["id"] for e in json.loads(path.read_text(encoding="utf-8"))["entities"] if e["interactive"]]
        rows = rows_by_id(engine)
        self.assertEqual(sorted(uid for uid in rows if uid in wanted), sorted(wanted))
        self.assertEqual(len(wanted), len(set(wanted)))
        smith_chest = map_entity("starter_village", "smith:output_chest")
        self.assertEqual(smith_chest["kind"], "storage")
        self.assertEqual(smith_chest["position"], [64.0 + 620.0, 48.0])  # shifted by the interior's origin
        m = engine.state.m_tensor
        self.assertEqual(float(m[rows["smith:output_chest"], backend.CX]), 684.0)

    async def test_only_the_first_storage_of_the_primary_map_is_seeded(self):
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        engine = backend.engine
        self.assertEqual(engine._starter_storage_case_entity_id, "village:supply_crate")
        self.assertEqual(sorted(engine._inventory_seeded_containers), ["village:supply_crate"])
        chest = backend.get_container_inventory(engine.inventory_state, "smith:output_chest")
        self.assertIsNotNone(chest)
        self.assertFalse(backend.has_item(chest, "rations", 1))

    async def test_save_and_restore_keep_ids_types_and_containers(self):
        load_village_maps()
        sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                _test_storage / "map_entities" / uuid.uuid4().hex, backend.create_genesis, 905,
                                map_name="starter_village")
        await sessions.new("Entities")
        engine = backend.engine
        before_ids = list(engine._entity_uid_by_slot)
        before_rows = engine.state.m_tensor.clone()
        before_starter = engine._starter_storage_case_entity_id
        save_id = sessions.active_id
        engine.reset_world()
        await sessions.continue_world(save_id)
        self.assertEqual(before_ids, list(backend.engine._entity_uid_by_slot))
        self.assertTrue(bool((before_rows == backend.engine.state.m_tensor).all()))
        self.assertEqual(before_starter, backend.engine._starter_storage_case_entity_id)
        self.assertEqual(instantiate_authored_entities(backend.engine, "starter_village"), [])  # nothing is created twice
        container = backend.get_container_inventory(backend.engine.inventory_state, "village:supply_crate")
        self.assertTrue(backend.has_item(container, "rations", 4))


class WallOwnerBookkeepingTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_owner_lookup_and_ignoring_the_targets_own_footprint(self):
        engine = await authored_world(SMITH)
        self.assertEqual(wall_owners("example_smith"), {"example_smith:wall_forge": "example_smith:forge"})
        self.assertEqual(wall_owners("playable_village"), {})
        full = map_wall_boxes(engine)
        self.assertIn("example_smith:wall_forge", [b["id"] for b in full])
        without = map_wall_boxes_ignoring(engine, "example_smith:forge")
        self.assertNotIn("example_smith:wall_forge", [b["id"] for b in without])
        self.assertEqual(len(without), len(full) - 1)
        self.assertEqual(len(map_wall_boxes_ignoring(engine, "someone_else")), len(full))

    async def test_the_contract_itself_does_not_carry_owner_data(self):
        engine = await authored_world(SMITH)
        for box in world_contract(engine)["boxes"]:
            self.assertEqual(sorted(box), ["height", "id", "max", "min"])

    async def test_legacy_maps_have_no_ignoring_variant(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.assertIsNone(map_wall_boxes_ignoring(backend.engine, "e_000006"))

    async def test_the_forge_entity_is_instantiated_where_the_map_says(self):
        engine = await authored_world(SMITH)
        rows = rows_by_id(engine)
        m = engine.state.m_tensor
        self.assertEqual((float(m[rows["example_smith:forge"], backend.CX]), float(m[rows["example_smith:forge"], backend.CY])), (24.0, 16.0))
        info = map_entity("example_smith", "example_smith:forge")
        self.assertEqual((info["kind"], info["interactive"]), ("forge", True))
        self.assertIsNone(map_entity("example_smith", "nope"))


if __name__ == "__main__":
    unittest.main()
