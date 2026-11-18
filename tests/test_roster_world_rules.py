"""A running roster world keeps its rules when the roster file on disk changes, breaks or disappears.

Found by the 90-minute soak: the roster file was rewritten (new residents whose anchors the running world had not placed)
while the server ran; the per-tick roster check re-read the file, said "no roster", and the world fell back to legacy NPC
rules (attacks, random disasters, legacy needs) and residents died.
"""
import json
import os
import unittest
from driver_pin import pin_anchor
import uuid
from pathlib import Path
from unittest import mock

from authored_village import load_village_maps
from test_startup_preservation import backend, _test_storage
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from instincts_and_tools import engine_has_roster
from systems.roster.apply import clear_roster_cache, has_roster, world_has_roster
from systems.roster.driver import anchor_driven_slots, needs_scale_vector

ROOT = Path(__file__).resolve().parents[1]
VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"


async def roster_world():
    load_village_maps()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    return backend.engine


class WorldRulesTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)

    def roster_dir(self):
        directory = _test_storage / "rd" / uuid.uuid4().hex[:8]
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    async def assert_world_unchanged(self, engine, note):
        self.assertFalse(has_roster("starter_village"), note)  # the file says no (that is what creating a new world would see)
        self.assertTrue(world_has_roster(engine), note)
        self.assertTrue(engine_has_roster(engine), note)
        self.assertEqual(len(anchor_driven_slots(engine)), 8, note)
        self.assertIsNotNone(needs_scale_vector(engine, engine.state.h_tensor), note)
        for _ in range(30):
            engine.step()
        self.assertTrue(bool((engine.state.h_tensor[:8, cfg.HP] >= 99.9).all()), note)

    async def test_a_missing_roster_file_does_not_change_the_running_world(self):
        engine = await roster_world()
        engine.step()
        with mock.patch.dict(os.environ, {"EDEN_ROSTER_DIR": str(self.roster_dir())}):
            clear_roster_cache()
            await self.assert_world_unchanged(engine, "missing file")

    async def test_a_broken_roster_file_does_not_change_the_running_world(self):
        engine = await roster_world()
        engine.step()
        directory = self.roster_dir()
        (directory / "starter_village.json").write_text("{ this is not json", encoding="utf-8")
        with mock.patch.dict(os.environ, {"EDEN_ROSTER_DIR": str(directory)}):
            clear_roster_cache()
            self.assertTrue(world_has_roster(engine))
            for _ in range(30):
                engine.step()  # must not raise either
            self.assertTrue(engine_has_roster(engine))

    async def test_a_new_roster_naming_anchors_the_world_never_placed_does_not_change_the_running_world(self):
        engine = await roster_world()
        engine.step()
        data = json.loads((ROOT / "world_data" / "rosters" / "starter_village.json").read_text(encoding="utf-8"))
        extra = json.loads(json.dumps(data["residents"][1]))
        extra.update(key="newcomer", name="Newcomer")
        extra["anchors"] = {"spawn": "village:spawn", "work": "lodge:not_placed_in_this_world"}
        data["residents"].append(extra)
        directory = self.roster_dir()
        (directory / "starter_village.json").write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.dict(os.environ, {"EDEN_ROSTER_DIR": str(directory)}):
            clear_roster_cache()
            await self.assert_world_unchanged(engine, "roster with unplaced anchors")

    async def test_legacy_and_rosterless_worlds_are_not_roster_worlds(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        for _ in range(5):
            engine.step()
        self.assertFalse(world_has_roster(engine))
        self.assertFalse(engine_has_roster(engine))
        self.assertIsNone(needs_scale_vector(engine, engine.state.h_tensor))

    async def test_a_new_world_reads_the_file_again(self):
        engine = await roster_world()
        self.assertTrue(world_has_roster(engine))
        engine.reset_world()
        with mock.patch.dict(os.environ, {"EDEN_ROSTER_DIR": str(self.roster_dir())}):
            clear_roster_cache()
            await backend.create_genesis(backend.engine, map_name="starter_village")  # no roster file now: no roster residents
            self.assertFalse(world_has_roster(backend.engine))


if __name__ == "__main__":
    unittest.main()
