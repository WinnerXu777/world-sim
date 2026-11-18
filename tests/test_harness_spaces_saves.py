"""1008 WS-D P3e: save format 2 under EDEN_SPACES=1. Flag off writes today's format 1 byte for byte in its structure; flag on writes schema 2
with a ``world_format`` block; a save of the other format is refused by ``validate`` before anything changes, with the approved texts;
``list_saves`` / GET /session say per save whether it can be continued (``compatible``)."""
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend, _test_storage  # noqa: E402
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from authored_village import load_village_maps  # noqa: E402
from fastapi import HTTPException  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import engine_hooks as eh, spaces  # noqa: E402
from persistence import codec, world_snapshot  # noqa: E402
from persistence.checkpoints import CheckpointStore  # noqa: E402
from persistence.sessions import GameSessions  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402

ON = {"EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1"}
TEXT_FORMAT_1 = ("This save was made by an earlier version of the game (world format 1), in which interiors shared the overworld's "
                 "coordinate frame. This version keeps interiors as separate spaces (world format 2), so the save cannot be continued. "
                 "Start a new world; the old save file has not been changed or deleted.")
TEXT_FORMAT_2 = ("This save was made with separate interior spaces (world format 2, EDEN_SPACES=1), but this session runs without them, "
                 "so it cannot be continued. Start the game with EDEN_SPACES=1 to continue it. The save file has not been changed.")


class SaveFormatTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        DISPATCH.clear()
        load_village_maps()
        self.sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                     _test_storage / "p3e" / uuid.uuid4().hex[:8], backend.create_genesis, 905, map_name="starter_village")

    async def asyncTearDown(self):
        eh.uninstall(DISPATCH)
        DISPATCH.clear()
        await super().asyncTearDown()

    def flag(self, on):
        patcher = mock.patch.dict(os.environ, ON if on else {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        if not on:
            os.environ.pop("EDEN_SPACES", None)
        else:
            eh.install(DISPATCH)

    async def new_world(self, on, name="W"):
        self.flag(on)
        return await self.sessions.new(name)

    def payload(self):
        return codec.loads(world_snapshot.capture(backend.engine, backend.map_geo))

    # -- texts ---------------------------------------------------------------------------------------------------------------
    def test_refusal_texts_are_the_approved_ones_verbatim(self):
        self.assertEqual(world_snapshot.REFUSAL_FORMAT_1_WITH_SPACES, TEXT_FORMAT_1)
        self.assertEqual(world_snapshot.REFUSAL_FORMAT_2_WITHOUT_SPACES, TEXT_FORMAT_2)
        self.assertTrue(issubclass(world_snapshot.SaveFormatError, ValueError))

    # -- capture -------------------------------------------------------------------------------------------------------------
    async def test_flag_off_writes_schema_1_without_world_format(self):
        await self.new_world(False)
        payload = self.payload()
        self.assertEqual(payload["schema"], 1)
        self.assertNotIn("world_format", payload)
        self.assertEqual(world_snapshot.current_format(), 1)

    async def test_flag_on_writes_schema_2_with_the_space_layout(self):
        await self.new_world(True)
        payload = self.payload()
        self.assertEqual(payload["schema"], 2)
        fmt = payload["world_format"]
        self.assertEqual(fmt["format"], 2)
        self.assertEqual([s["map_id"] for s in fmt["spaces"]],
                         ["starter_village", "smith_interior", "village_lodge_interior", "west_cottage_interior"])
        self.assertEqual([s["space"] for s in fmt["spaces"]], [0, 1, 2, 3])
        self.assertEqual(set(payload) - {"world_format"}, set(self.payload_keys_flag_off()))

    def payload_keys_flag_off(self):
        return ("schema", "engine", "humans", "entities", "geometry", "residents", "runtimes", "instinct_bits", "registry", "rng")

    # -- validate / restore --------------------------------------------------------------------------------------------------
    async def test_format_2_round_trip_restores_the_space_columns(self):
        await self.new_world(True)
        spaces.refresh(backend.engine)
        payload = self.payload()
        humans, entities = backend.engine.state.h_tensor.clone(), backend.engine.state.m_tensor.clone()
        self.assertGreater(float(humans[:, cfg.H_SPACE].sum()), 0.0, "the smith stands in an interior")
        backend.engine.state.h_tensor[:, cfg.H_SPACE] = 0.0
        backend.engine.state.m_tensor[:, cfg.M_SPACE] = 0.0
        world_snapshot.restore(payload, backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime)
        self.assertTrue(torch.equal(backend.engine.state.h_tensor, humans))
        self.assertTrue(torch.equal(backend.engine.state.m_tensor, entities))
        self.assertGreater(float(entities[:, cfg.M_SPACE].sum()), 0.0)

    async def test_format_1_save_is_refused_with_the_approved_text_and_nothing_changes(self):
        await self.new_world(False)
        old = self.payload()
        self.flag(True)
        before = (backend.engine.world_epoch, backend.engine.state.h_tensor.clone(), backend.engine.tick)
        with self.assertRaises(world_snapshot.SaveFormatError) as caught:
            world_snapshot.validate(old, backend.engine)
        self.assertEqual(str(caught.exception), TEXT_FORMAT_1)
        with self.assertRaises(world_snapshot.SaveFormatError):
            world_snapshot.restore(old, backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime)
        self.assertEqual(before[0], backend.engine.world_epoch)
        self.assertTrue(torch.equal(before[1], backend.engine.state.h_tensor))
        self.assertEqual(before[2], backend.engine.tick)

    async def test_format_2_save_is_refused_without_the_flag_with_the_approved_text(self):
        await self.new_world(True)
        new = self.payload()
        self.flag(False)
        with self.assertRaises(world_snapshot.SaveFormatError) as caught:
            world_snapshot.validate(new, backend.engine)
        self.assertEqual(str(caught.exception), TEXT_FORMAT_2)

    async def test_format_1_still_loads_with_the_flag_off(self):
        await self.new_world(False)
        payload = self.payload()
        world_snapshot.validate(payload, backend.engine)
        world_snapshot.restore(payload, backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime)

    async def test_a_layout_that_differs_from_the_registered_maps_is_refused(self):
        await self.new_world(True)
        payload = self.payload()
        payload["world_format"]["spaces"][1]["origin"] = [1.0, 1.0]
        with self.assertRaises(ValueError) as caught:
            world_snapshot.validate(payload, backend.engine)
        self.assertNotIsInstance(caught.exception, world_snapshot.SaveFormatError)
        self.assertIn("do not match the maps registered", str(caught.exception))
        missing = self.payload()
        del missing["world_format"]
        with self.assertRaises(ValueError):
            world_snapshot.validate(missing, backend.engine)

    # -- manifests and listing -----------------------------------------------------------------------------------------------
    async def test_manifest_entries_and_listing(self):
        store = CheckpointStore(_test_storage / "p3e-list" / uuid.uuid4().hex[:8])
        old_id, new_id, legacy_id = (uuid.uuid4().hex for _ in range(3))
        store.commit(old_id, "old", 1, b"x")                                   # default: format 1, entry keeps today's keys exactly
        self.assertEqual(set(store.manifest(old_id)["generations"][0]), {"id", "sha256", "tick", "saved_at"})
        store.commit(new_id, "new", 2, b"y", 2)
        self.assertEqual(store.manifest(new_id)["generations"][0]["world_format"], 2)
        store.commit(legacy_id, "legacy", 3, b"z")
        by_name = lambda: {s["name"]: s for s in store.list_saves()}           # noqa: E731
        self.flag(False)
        listed = by_name()
        self.assertNotIn("compatible", listed["old"])                           # flag off, format 1: listing keys unchanged
        self.assertEqual(set(listed["old"]), {"save_id", "name", "id", "sha256", "tick", "saved_at"})
        self.assertIs(listed["new"]["compatible"], False)                       # flag off, format 2: greyed out
        self.flag(True)
        listed = by_name()
        self.assertIs(listed["old"]["compatible"], False)                       # flag on, format 1
        self.assertIs(listed["legacy"]["compatible"], False)                    # entries without the key count as format 1
        self.assertIs(listed["new"]["compatible"], True)                        # flag on, format 2

    async def test_session_saves_record_their_format_and_continue_is_refused_over_http_400(self):
        created = await self.new_world(False, "old world")
        old_id = created["active_save_id"]
        self.assertNotIn("world_format", self.sessions.store.manifest(old_id)["generations"][0])
        self.flag(True)
        fresh = backend.Engine()                   # a new process: nothing is active, so Continue really reads the save
        resumed = GameSessions(fresh, backend.map_geo, backend.ar.PlayerControlRuntime, self.sessions.store.root,
                               backend.create_genesis, 905, map_name="starter_village")
        epoch, tick = fresh.world_epoch, fresh.tick
        with self.assertRaises(HTTPException) as caught:
            await backend._session_operation(resumed.continue_world, old_id)
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (400, TEXT_FORMAT_1))
        self.assertEqual((fresh.world_epoch, fresh.tick), (epoch, tick))
        self.assertTrue((self.sessions.store.directory(old_id) / "manifest.json").exists(), "the old save file is not deleted")
        new = await resumed.new("new world")
        self.assertEqual(resumed.store.manifest(new["active_save_id"])["generations"][0]["world_format"], 2)
        listing = {s["save_id"]: s for s in resumed.store.list_saves()}
        self.assertIs(listing[old_id]["compatible"], False)
        self.assertIs(listing[new["active_save_id"]]["compatible"], True)
        self.flag(False)
        other = GameSessions(backend.Engine(), backend.map_geo, backend.ar.PlayerControlRuntime, resumed.store.root,
                             backend.create_genesis, 905, map_name="starter_village")
        with self.assertRaises(HTTPException) as caught:
            await backend._session_operation(other.continue_world, new["active_save_id"])
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (400, TEXT_FORMAT_2))


if __name__ == "__main__":
    unittest.main()
