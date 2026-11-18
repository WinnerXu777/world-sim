"""Exercise real HTTP endpoints against a disposable, full-simulation world."""
import asyncio
import os
import sys
import uuid
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
_test_parent = Path(__file__).resolve().parents[1] / ".tmp" / "tests"
_test_parent.mkdir(parents=True, exist_ok=True)
_test_storage = _test_parent / f"eden-startup-{uuid.uuid4().hex}"
_test_storage.mkdir()
os.environ["EDEN_PROFILE"] = "gameplay"
os.environ["EDEN_DATA_ROOT"] = str(_test_storage)
import map_test as backend


class StartupPreservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        backend.engine.reset_world()

    async def test_connect_reconnect_and_rejected_debug_reset_preserve_world(self):
        await backend.create_genesis(backend.engine, map_name="render_test_village")
        epoch = backend.engine.world_epoch
        ids = list(backend.engine._human_uid_by_slot)
        inventory = repr(backend.engine.inventory_state)
        positions = backend.engine.state.h_tensor.clone()
        for _ in range(3):
            async with httpx.AsyncClient(headers={"X-Eden-Session": backend.SESSION_CAPABILITY}, transport=httpx.ASGITransport(app=backend.app),
                                         base_url="http://127.0.0.1") as client:
                bootstrap = await client.get("/bootstrap")
                self.assertEqual(bootstrap.status_code, 200)
                self.assertEqual(bootstrap.json()["world_epoch"], epoch)
                status = (await client.get("/status")).json()
                self.assertEqual(status["runtime_profile"], "full")
                self.assertEqual(status["launch"]["profile"], "gameplay")
                for url in ("/testing/render_test_village", "/set_map/eden_island",
                            "/load_instinct/test/1"):
                    self.assertEqual((await client.post(url, json={})).status_code, 403)
        self.assertEqual(backend.engine.world_epoch, epoch)
        self.assertEqual(backend.engine._human_uid_by_slot, ids)
        self.assertEqual(repr(backend.engine.inventory_state), inventory)
        self.assertTrue(backend.torch.equal(positions, backend.engine.state.h_tensor))
        self.assertTrue(backend.engine.resident_store.root_dir.is_relative_to(_test_storage))

    async def test_lifespan_runs_real_ticks_and_cancels_owned_task(self):
        async with backend.lifespan(backend.app):
            await backend.create_genesis(backend.engine, map_name="playable_village")
            await asyncio.sleep(.16)
            self.assertGreater(backend.engine.tick, 0)
            self.assertTrue(backend.engine.running)
            task = backend.app.state.simulation_task
            self.assertFalse(task.done())
            async with httpx.AsyncClient(headers={"X-Eden-Session": backend.SESSION_CAPABILITY}, transport=httpx.ASGITransport(app=backend.app),
                                         base_url="http://127.0.0.1") as client:
                timing = (await client.get("/status")).json()["timing"]
                self.assertGreater(timing["sample_count"], 0)
                self.assertIsNotNone(timing["work_ms"]["p95"])
        self.assertTrue(task.done())
        self.assertFalse(backend.engine.running)

    async def test_full_tick_consumes_decree_and_replies_to_player_without_provider(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        # Put the two existing fixture residents within direct hearing range.
        h = backend.engine.state.h_tensor
        h[1, backend.X] = h[0, backend.X] + 2
        h[1, backend.Y] = h[0, backend.Y]
        speaker, listener = backend.engine._human_uid_by_slot[:2]
        async with httpx.AsyncClient(headers={"X-Eden-Session": backend.SESSION_CAPABILITY}, transport=httpx.ASGITransport(app=backend.app),
                                     base_url="http://127.0.0.1") as client:
            claim = await client.post("/control/claim", json={"controller_id": "test_player",
                                      "target_kind": "human", "target_id": speaker})
            self.assertEqual(claim.status_code, 200)
            talk = await client.post("/control/event", json={"controller_id": "test_player", "seq": 1,
                "protocol_version": 1, "world_epoch": backend.engine.world_epoch,
                "possession_epoch": claim.json()["possession_epoch"],
                "event": "talk_command", "action": "talk", "semantic_action": "talk_command",
                "text": "Hello neighbor", "talk_mode": "direct_talk",
                "target_kind": "human", "target_id": listener, "context": "human_tps"})
            self.assertEqual(talk.status_code, 200)
            decree = await client.post("/god_decree", json={"map_actions": [], "human_actions": [],
                                                           "new_entities": [], "new_instincts": []})
            self.assertEqual(decree.status_code, 200)
        self.assertGreater(backend.engine.world_agent.pending_count(), 0)
        backend.engine.step()
        self.assertEqual(backend.engine.world_agent.pending_count(), 0)
        self.assertTrue(backend.engine.world_agent.history)
        replies = [line for line in backend.engine.talk_agent.recent_lines
                   if line["speaker_id"] == listener and line["text"]]
        self.assertTrue(replies, backend.engine.talk_agent.status_snapshot())
        self.assertIsNone(backend.engine.world_model_handler)
        self.assertIsNone(backend.engine.resident_model_handler)


if __name__ == "__main__":
    unittest.main()
