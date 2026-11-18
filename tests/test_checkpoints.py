import json
import asyncio
import threading
import random
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

from test_startup_preservation import backend, _test_storage
from persistence import codec, world_snapshot
from persistence.checkpoints import CheckpointStore, CheckpointError, atomic_write
from persistence.sessions import GameSessions


class CheckpointStorageTests(unittest.TestCase):
    def setUp(self):
        self.store = CheckpointStore(_test_storage / "ck" / uuid.uuid4().hex[:8])
        self.save_id = uuid.uuid4().hex

    def test_failure_before_manifest_commit_preserves_previous_generation(self):
        self.store.commit(self.save_id, "Village", 1, b"first complete world")
        def fail_manifest(path, data):
            if path.name == "manifest.json":
                raise PermissionError("locked manifest")
            return atomic_write(path, data)
        with patch("persistence.checkpoints.atomic_write", side_effect=fail_manifest):
            with self.assertRaises(PermissionError):
                self.store.commit(self.save_id, "Village", 2, b"uncommitted world")
        payload, info = self.store.read(self.save_id)
        self.assertEqual(payload, b"first complete world")
        self.assertEqual(info["tick"], 1)
        self.assertEqual(len(self.store.manifest(self.save_id)["generations"]), 1)

    def test_corrupt_latest_generation_recovers_last_complete_one(self):
        self.store.commit(self.save_id, "Village", 1, b"first")
        second = self.store.commit(self.save_id, "Village", 2, b"second")
        (self.store.directory(self.save_id) / f"{second['id']}.json.gz").write_bytes(b"interrupted write")
        payload, info = self.store.read(self.save_id)
        self.assertEqual(payload, b"first")
        self.assertTrue(info["recovered_previous"])

    def test_invalid_save_id_cannot_escape_root(self):
        for save_id in ("../ResidentAgents", "C:/windows", "", "a" * 31):
            with self.subTest(save_id=save_id), self.assertRaises(CheckpointError):
                self.store.directory(save_id)

    def test_data_only_codec_preserves_tensor_tuple_set_and_integer_keys(self):
        original = {1: {"tensor": torch.tensor([[1., 2.]]), "tuple": (1, 2), "set": {3, 4}},
                    "array": np.array([1, 2], dtype=np.uint32)}
        restored = codec.loads(codec.dumps(original))
        self.assertTrue(torch.equal(restored[1]["tensor"], original[1]["tensor"]))
        self.assertEqual(restored[1]["tuple"], (1, 2))
        self.assertEqual(restored[1]["set"], {3, 4})
        self.assertTrue(np.array_equal(restored["array"], original["array"]))
        with self.assertRaises(TypeError):
            codec.dumps(lambda: None)


class WorldCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        backend.engine.reset_world()
        self.sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
            _test_storage / "wt" / uuid.uuid4().hex[:8], backend.create_genesis, 905)

    async def test_cancelled_save_holds_lock_until_disk_commit_finishes(self):
        await self.sessions.new("Cancellation")
        entered, release = threading.Event(), threading.Event()
        commit = self.sessions.store.commit
        def delayed_commit(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release writer")
            return commit(*args)
        with patch.object(self.sessions.store, "commit", side_effect=delayed_commit):
            saving = asyncio.create_task(self.sessions.save())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                saving.cancel()
                await asyncio.sleep(0)
                self.assertFalse(saving.done())
                self.assertTrue(self.sessions._lock.locked())
                saving.cancel()  # Repeated cancellation must not release ownership.
                await asyncio.sleep(0)
                self.assertTrue(self.sessions._lock.locked())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await saving
        self.assertFalse(self.sessions._lock.locked())
        self.assertEqual(len(self.sessions.store.manifest(self.sessions.active_id)["generations"]), 2)

    async def test_fresh_engine_restores_world_inventory_residents_geometry_rng_and_tick(self):
        created = await self.sessions.new("Persistent village")
        source = backend.engine
        source.step()
        speaker, listener = source._human_uid_by_slot[:2]
        source.resident_store._cache[speaker]["profile"]["name"] = "Mara the Smith"
        source.world_agent.queue_decree({"map_actions": [], "human_actions": [], "new_entities": [], "new_instincts": []})
        source.player_control.claim_target(source, controller_id="test", target_kind="human", target_id=speaker)
        await self.sessions.save()
        expected = codec.loads(world_snapshot.capture(source, backend.map_geo))
        expected_random = (random.random(), np.random.random(), torch.rand(1))
        old_epoch = source.world_epoch
        fresh = backend.Engine()
        resumed = GameSessions(fresh, backend.map_geo, backend.ar.PlayerControlRuntime,
                               self.sessions.store.root, backend.create_genesis, 905)
        await resumed.continue_world(created["active_save_id"])
        self.assertTrue(torch.equal(fresh.state.h_tensor, expected["humans"]))
        self.assertTrue(torch.equal(fresh.state.m_tensor, expected["entities"]))
        self.assertEqual(fresh.inventory_state, expected["engine"]["inventory_state"])
        self.assertEqual(fresh.resident_store._cache, expected["residents"])
        self.assertEqual(fresh.tick, expected["engine"]["tick"])
        self.assertEqual(fresh._human_uid_by_slot, expected["engine"]["_human_uid_by_slot"])
        self.assertEqual(backend.map_geo.TILE_TO_ENTITY, expected["geometry"]["tiles"])
        self.assertEqual(fresh.world_agent._queue, expected["runtimes"]["world_agent"]["_queue"])
        self.assertEqual(fresh.player_control.status_snapshot()["sessions"], [])
        self.assertNotEqual(fresh.world_epoch, old_epoch)
        self.assertEqual(random.random(), expected_random[0])
        self.assertEqual(np.random.random(), expected_random[1])
        self.assertTrue(torch.equal(torch.rand(1), expected_random[2]))
        fresh.step()
        self.assertEqual(fresh.tick, expected["engine"]["tick"] + 1)

    async def test_continue_active_world_is_idempotent_and_new_uses_separate_slot(self):
        first = await self.sessions.new("First")
        backend.engine.step()
        epoch, tick = backend.engine.world_epoch, backend.engine.tick
        await self.sessions.continue_world(first["active_save_id"])
        self.assertEqual((backend.engine.world_epoch, backend.engine.tick), (epoch, tick))
        second = await self.sessions.new("Second")
        self.assertNotEqual(first["active_save_id"], second["active_save_id"])
        self.assertEqual(len(self.sessions.store.list_saves()), 2)
        await self.sessions.continue_world(first["active_save_id"])
        self.assertEqual(backend.engine.tick, tick)

    async def test_invalid_checkpoint_does_not_mutate_active_world(self):
        await self.sessions.new("Preserve me")
        epoch = backend.engine.world_epoch
        human_state = backend.engine.state.h_tensor.clone()
        bad_id = uuid.uuid4().hex
        self.sessions.store.commit(bad_id, "Bad schema", 0, codec.dumps({"schema": 999}))
        with self.assertRaises(ValueError):
            await self.sessions.continue_world(bad_id)
        self.assertEqual(backend.engine.world_epoch, epoch)
        self.assertTrue(torch.equal(backend.engine.state.h_tensor, human_state))


if __name__ == "__main__":
    unittest.main()
