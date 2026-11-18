import asyncio
import unittest
import uuid
import threading
from unittest.mock import patch
from test_startup_preservation import backend, _test_storage
from persistence.sessions import GameSessions
from persistence import codec


class SessionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        backend.engine.reset_world()
        self.sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                    _test_storage / "lifecycle" / uuid.uuid4().hex, backend.create_genesis, 905)

    async def test_lifespan_saves_final_tick_and_drains_owned_tasks(self):
        with patch.object(backend, "game_sessions", self.sessions):
            async with backend.lifespan(backend.app):
                await self.sessions.new("Shutdown village")
                await asyncio.sleep(.12)
            data, info = self.sessions.store.read(self.sessions.active_id)
            self.assertEqual(info["tick"], backend.engine.tick)
            self.assertGreater(info["tick"], 0)
            self.assertEqual(codec.loads(data)["engine"]["tick"], backend.engine.tick)
            self.assertTrue(backend.app.state.simulation_task.done())
            self.assertTrue(backend.app.state.autosave_task.done())

    async def test_autosave_failure_preserves_previous_generation_then_retries(self):
        await self.sessions.new("Autosave village")
        backend.engine.step()
        self.sessions.autosave_interval = .01
        task = asyncio.create_task(self.sessions.autosave_loop())
        try:
            with patch.object(self.sessions.store, "commit", side_effect=PermissionError("locked manifest")):
                for _ in range(100):
                    if self.sessions.last_error:
                        break
                    await asyncio.sleep(.005)
                self.assertIn("locked manifest", self.sessions.last_error or "")
                self.assertEqual(self.sessions.store.read(self.sessions.active_id)[1]["tick"], 0)
            for _ in range(100):
                if self.sessions.last_saved_tick == 1 and self.sessions.last_error is None:
                    break
                await asyncio.sleep(.005)
            self.assertEqual(self.sessions.last_saved_tick, 1)
            self.assertIsNone(self.sessions.last_error)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_reset_world_cannot_overwrite_previous_active_slot_on_shutdown(self):
        await self.sessions.new("Keep this save")
        before = self.sessions.store.manifest(self.sessions.active_id)
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        await self.sessions.shutdown()
        self.assertEqual(self.sessions.store.manifest(self.sessions.active_id), before)

    async def test_shutdown_failure_is_reported_and_keeps_complete_save(self):
        await self.sessions.new("Keep last generation")
        backend.engine.step()
        with patch.object(self.sessions.store, "commit", side_effect=PermissionError("locked shutdown")):
            with self.assertRaises(PermissionError):
                await self.sessions.shutdown()
        self.assertIn("locked shutdown", self.sessions.last_error)
        self.assertEqual(self.sessions.store.read(self.sessions.active_id)[1]["tick"], 0)

    async def test_shutdown_waits_for_active_autosave_before_final_checkpoint(self):
        self.sessions.autosave_interval = .02
        entered, release = threading.Event(), threading.Event()
        commit = self.sessions.store.commit
        def delayed_commit(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Writer not released by test")
            return commit(*args)
        with patch.object(backend, "game_sessions", self.sessions):
            lifecycle = backend.lifespan(backend.app)
            await lifecycle.__aenter__()
            await self.sessions.new("Drain before exit")
            with patch.object(self.sessions.store, "commit", side_effect=delayed_commit):
                closing = None
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                    closing = asyncio.create_task(lifecycle.__aexit__(None, None, None))
                    await asyncio.sleep(.02)
                    self.assertFalse(closing.done())
                    self.assertTrue(backend.app.state.simulation_task.done())
                finally:
                    release.set()
                    if closing is None:
                        await lifecycle.__aexit__(None, None, None)
                    else:
                        await closing
            self.assertTrue(backend.app.state.autosave_task.done())
            self.assertEqual(self.sessions.store.read(self.sessions.active_id)[1]["tick"], backend.engine.tick)
