"""1008 WS-D P3d: the wire. With EDEN_SPACES=1 humans, animals and map entities carry ``space``, ``maps[]`` entries carry ``space`` and
/bootstrap carries ``spaces``; with the flag off every key set is exactly today's (pinned here: flag on = flag off + the named keys)."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from test_map_portals import real_world  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
import map_geo  # noqa: E402
from harness import engine_hooks as eh, spaces  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402
from systems.movement.map_contract import maps_block  # noqa: E402

ON = {"EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1"}


class WireTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        DISPATCH.clear()

    async def asyncTearDown(self):
        eh.uninstall(DISPATCH)
        DISPATCH.clear()
        await super().asyncTearDown()

    async def world(self, on):
        patcher = mock.patch.dict(os.environ, ON if on else {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        if not on:
            os.environ.pop("EDEN_SPACES", None)
        else:
            eh.install(DISPATCH)
        engine = await real_world()
        slot = iat.animal_born(engine.state.m_tensor, engine._entity_count_ref, 200.0, 150.0, cfg.M_TIGER, device=engine.state.device)
        self.assertNotEqual(slot, -1)
        spaces.refresh(engine)
        return engine, slot

    def key_sets(self, engine, animal_slot):
        entity_slot = next(s for s in sorted(map_geo.MAP_GEO) if engine._entity_uid_by_slot[s])
        return {"human": set(engine._export_human(0)), "animal": set(engine._export_animal(animal_slot)),
                "map_entity": set(engine._export_map_entity(entity_slot))}

    async def test_key_sets_flag_on_equal_flag_off_plus_space(self):
        engine, animal = await self.world(False)
        off = self.key_sets(engine, animal)
        for name, keys in off.items():
            self.assertNotIn("space", keys, name)
        self.assertTrue(all("space" not in entry for entry in maps_block(engine)))
        off_bootstrap = set(json.loads((await backend.bootstrap()).body))
        self.assertNotIn("spaces", off_bootstrap)
        engine, animal = await self.world(True)
        on = self.key_sets(engine, animal)
        for name in off:
            self.assertEqual(on[name], off[name] | {"space"}, name)
        self.assertEqual(set(json.loads((await backend.bootstrap()).body)), off_bootstrap | {"spaces"})
        for index, entry in enumerate(maps_block(engine)):
            self.assertEqual(entry["space"], index)

    async def test_values_follow_the_columns(self):
        engine, animal = await self.world(True)
        smith = spaces.space_of_map(engine, "smith_interior")
        self.assertEqual(engine._export_human(0)["space"], smith)         # the first resident is the smith, inside the smith interior
        self.assertEqual(engine._export_human(1)["space"], 0)
        self.assertEqual(engine._export_animal(animal)["space"], 0)
        in_smith = {s for s in map_geo.MAP_GEO if int(engine.state.m_tensor[s, cfg.M_SPACE]) == smith}
        self.assertTrue(in_smith, "the smith interior has map entities")
        for slot in in_smith:
            self.assertEqual(engine._export_map_entity(slot)["space"], smith)

    async def test_bootstrap_spaces_is_the_table_and_agrees_with_maps(self):
        engine, _ = await self.world(True)
        body = json.loads((await backend.bootstrap()).body)
        self.assertEqual(body["spaces"], json.loads(json.dumps(spaces.space_table(engine))))
        self.assertEqual([s["space"] for s in body["spaces"]], [m["space"] for m in body["maps"]])
        self.assertEqual([s["map_id"] for s in body["spaces"]], [m["map_id"] for m in body["maps"]])
        self.assertEqual([s["sha256"] for s in body["spaces"]], [m["sha256"] for m in body["maps"]])
        self.assertEqual([s["origin"] for s in body["spaces"]], [m["origin"] for m in body["maps"]])
        self.assertEqual(body["spaces"][0]["kind"], "overworld")
        self.assertEqual({s["kind"] for s in body["spaces"][1:]}, {"interior"})

    async def test_legacy_world_has_no_spaces_and_no_maps_even_with_the_flag(self):
        patcher = mock.patch.dict(os.environ, ON, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        body = json.loads((await backend.bootstrap()).body)
        self.assertNotIn("maps", body)
        self.assertNotIn("spaces", body)


if __name__ == "__main__":
    unittest.main()
