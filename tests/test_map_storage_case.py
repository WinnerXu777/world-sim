"""The engine's starter storage case on authored maps (H2): near a map storage entity, else skipped; legacy unchanged."""
import unittest
import json
from pathlib import Path

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation, FIXTURES, SMITH
from systems.movement.map_contract import get_map_contract, register_map_contract, register_map_file
from systems.movement.spatial import is_standable_point, snap_to_standable, world_contract
from authored_village import MAP_FILES, load_village_maps

ROOT = Path(__file__).resolve().parents[1]
REAL_VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"


def storage_cases(engine):
    m = engine.state.m_tensor
    return [(slot, float(m[slot, backend.CX]), float(m[slot, backend.CY])) for slot in range(m.shape[0])
            if int(m[slot, backend.M_TYPE]) == int(backend.M_STORAGE_CASE)]


class StarterStorageCaseTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_legacy_maps_still_place_the_case_beside_the_first_resident(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        first = min(slot for slot, uid in enumerate(engine._human_uid_by_slot) if uid)
        expected = (min(float(engine.state.h_tensor[first, backend.X]) + 26.0, backend.MAP_WIDTH - 18.0),
                    min(float(engine.state.h_tensor[first, backend.Y]) + 18.0, backend.MAP_HEIGHT - 18.0))
        positions = [(x, y) for _, x, y in storage_cases(engine)]
        self.assertEqual(len(positions), 2)  # the generator's own case plus the starter case
        self.assertIn(expected, positions)
        self.assertIsNotNone(engine._starter_storage_case_entity_id)

    async def test_an_authored_map_without_a_storage_entity_gets_no_starter_case(self):
        register_map_file(SMITH, base_dir=FIXTURES)  # example_smith has only a forge
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        self.assertEqual(storage_cases(backend.engine), [])
        self.assertIsNone(backend.engine._starter_storage_case_entity_id)

    async def test_a_registered_map_without_entity_data_gets_no_starter_case(self):
        register_map_contract("bare", 2.4, [0, 0, 100, 100], [], anchors=[{"id": "s", "kind": "spawn", "position": [50, 50]}])
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="bare")
        self.assertEqual(storage_cases(backend.engine), [])

    async def test_the_starter_container_is_the_maps_own_storage_entity(self):
        register_map_file(FIXTURES / "tiny_village.json", base_dir=FIXTURES)  # has chest_01 at (12, 4.5)
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="tiny_village")
        engine = backend.engine
        self.assertEqual([(x, y) for _, x, y in storage_cases(engine)], [(12.0, 4.5)])
        self.assertEqual(engine._starter_storage_case_entity_id, "chest_01")
        self.assertIn("chest_01", engine._entity_uid_by_slot)

    async def test_the_real_starter_village_uses_its_supply_crate_as_the_starter_container(self):
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        engine = backend.engine
        cases = storage_cases(engine)
        expected = {e["id"] for path in MAP_FILES for e in json.loads(path.read_text(encoding="utf-8"))["entities"] if e["kind"] == "storage"}
        actual = {engine._entity_uid_by_slot[slot]: (x, y) for slot, x, y in cases}
        self.assertEqual(set(actual), expected)  # all authored storage, no extra starter copy
        self.assertEqual(engine._starter_storage_case_entity_id, "village:supply_crate")
        crate = get_map_contract("starter_village")
        crate = next(e for e in crate["entities"] if e["id"] == "village:supply_crate")
        self.assertEqual(actual["village:supply_crate"], tuple(crate["position"]))

    async def test_the_engines_invented_case_is_not_created_on_the_real_map(self):
        register_map_file(REAL_VILLAGE, base_dir=ROOT / "myassets")
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        engine = backend.engine
        first = min(slot for slot, uid in enumerate(engine._human_uid_by_slot) if uid)
        legacy_spot = (float(engine.state.h_tensor[first, backend.X]) + 26.0, float(engine.state.h_tensor[first, backend.Y]) + 18.0)
        self.assertNotIn(legacy_spot, [(x, y) for _, x, y in storage_cases(engine)])

    async def test_registered_but_not_instantiated_maps_still_snap_the_case_to_a_standable_spot(self):
        # create_genesis over a registered *legacy* name does not instantiate map entities; the H2 fallback applies.
        register_map_file(FIXTURES / "tiny_village.json", name="playable_village", base_dir=FIXTURES)
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        positions = [(x, y) for _, x, y in storage_cases(engine)]
        contract = world_contract(engine)
        spot = next(p for p in positions if abs(p[0] - 12.0) < 1.5 and abs(p[1] - 4.5) < 1.5)
        self.assertTrue(is_standable_point(spot, contract))


if __name__ == "__main__":
    unittest.main()
