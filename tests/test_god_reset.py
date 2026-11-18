"""A new or restored world starts running at normal speed, whatever the previous world's god pause or time scale was.

Found by the backend review: ``_god_paused`` (runtime flag) and the scheduler's time scale survived ``Engine.reset_world``, so a New
Game or Continue started while the god had paused time began frozen at tick 0. Neither is part of a save.
"""
import unittest
import uuid

import httpx

from authored_village import load_village_maps
from test_startup_preservation import backend, _test_storage
from test_map_contract import AsyncRegistryIsolation, LEGACY_PLAYABLE_VILLAGE_CONTRACT, contract_without_epoch
from persistence.sessions import GameSessions
from systems.god.state import is_paused, set_paused


async def authored_world():
    load_village_maps()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    return backend.engine


def advances(engine, steps=3):
    before = engine.tick
    for _ in range(steps):
        engine.step()
    return engine.tick - before


class GodResetCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        set_paused(backend.engine, False)
        backend.engine.scheduler.set_time_scale(1.0)
        await super().asyncTearDown()

    async def test_a_new_world_after_a_pause_and_a_speed_change_starts_running_at_1x(self):
        engine = await authored_world()
        set_paused(engine, True)
        engine.scheduler.set_time_scale(2.0)
        self.assertEqual(advances(engine), 0)  # paused: sanity check of the setup
        engine.reset_world()
        self.assertFalse(is_paused(engine))
        self.assertEqual(engine.scheduler.time_scale, 1.0)
        await backend.create_genesis(engine, map_name="starter_village")
        self.assertEqual(advances(engine), 3)

    async def test_continue_of_a_save_made_while_paused_at_half_speed_starts_running_at_1x(self):
        engine = await authored_world()
        sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime, _test_storage / "gr" / uuid.uuid4().hex[:8],
                                backend.create_genesis, 905, map_name="starter_village")
        sessions.active_id, sessions.active_name, sessions.active_epoch = uuid.uuid4().hex, "Paused", engine.world_epoch
        advances(engine, 5)
        set_paused(engine, True)
        engine.scheduler.set_time_scale(0.5)
        await sessions.save()
        saved_tick = engine.tick
        engine.reset_world()
        await sessions.continue_world(sessions.active_id)
        self.assertEqual(backend.engine.tick, saved_tick)
        self.assertFalse(is_paused(backend.engine))
        self.assertEqual(backend.engine.scheduler.time_scale, 1.0)
        self.assertEqual(advances(backend.engine), 3)

    async def test_reconnect_without_a_reset_keeps_the_pause(self):
        engine = await authored_world()
        sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime, _test_storage / "gr" / uuid.uuid4().hex[:8],
                                backend.create_genesis, 905, map_name="starter_village")
        sessions.active_id, sessions.active_name, sessions.active_epoch = uuid.uuid4().hex, "Reconnect", engine.world_epoch
        set_paused(engine, True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            await client.get("/bootstrap")  # what a reconnecting client does first
            status = (await client.get("/status")).json()
        self.assertTrue(status["god"]["paused"])
        resumed = await sessions.continue_world(sessions.active_id)  # the already-active world: nothing is reset
        self.assertTrue(resumed.get("resumed_active"))
        self.assertTrue(is_paused(engine))
        self.assertEqual(advances(engine), 0)

    async def test_status_reports_a_running_new_world(self):
        engine = await authored_world()
        set_paused(engine, True)
        engine.reset_world()
        await backend.create_genesis(engine, map_name="starter_village")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1") as client:
            status = (await client.get("/status")).json()
        self.assertFalse(status["god"]["paused"])
        self.assertEqual(status["god"]["time_scale"], 1.0)

    async def test_the_legacy_world_after_a_pause_is_unchanged_and_running(self):
        engine = backend.engine
        set_paused(engine, True)
        engine.reset_world()
        await backend.create_genesis(engine, map_name="playable_village")
        self.assertEqual(contract_without_epoch(engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        self.assertEqual(advances(engine), 3)


if __name__ == "__main__":
    unittest.main()
