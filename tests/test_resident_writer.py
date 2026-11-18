import asyncio
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_resident_persistence as fixtures
from persistence.resident_writer import ResidentWriter
from runtime.resident_store import write_resident_batch


class ResidentWriterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.ResidentPersistenceTests.setUp(self)

    async def test_retry_can_succeed_without_advancing_simulation_tick(self):
        sessions = SimpleNamespace(engine=SimpleNamespace(resident_store=self.store, tick=20), _lock=asyncio.Lock())
        writer = ResidentWriter(sessions)
        with patch("runtime.resident_store._atomic_write_json", side_effect=PermissionError("locked")):
            await writer.flush_once()
        self.assertIn("h_000001", self.store.save_errors)
        self.assertIn("h_000001", self.store._dirty)
        await writer.flush_once()
        self.assertEqual(json.loads(self.path.read_text()), {"version": 2})
        self.assertFalse(self.store._dirty)
        self.assertFalse(self.store.save_errors)

    async def test_slow_writer_leaves_owner_responsive_and_retains_new_revision(self):
        self.store.background_writes = True
        self.store.touch_resident("h_000001")
        sessions = SimpleNamespace(engine=SimpleNamespace(resident_store=self.store, tick=20), _lock=asyncio.Lock())
        started, release = threading.Event(), threading.Event()

        def slow_write(jobs):
            started.set()
            if not release.wait(3):
                raise TimeoutError("Test did not release writer")
            return write_resident_batch(jobs)

        with patch("persistence.resident_writer.write_resident_batch", side_effect=slow_write):
            task = asyncio.create_task(ResidentWriter(sessions).flush_once())
            try:
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await asyncio.sleep(.001)
                self.store._cache["h_000001"]["version"] = 3
                self.store.touch_resident("h_000001")
                self.store.flush_dirty(force=True)
                self.assertTrue(sessions._lock.locked())
                self.assertFalse(task.done())
                self.assertEqual(json.loads(self.path.read_text()), {"version": 1})
            finally:
                release.set()
                await task
        self.assertIn("h_000001", self.store._dirty)
        self.assertEqual(json.loads(self.path.read_text()), {"version": 2})
        sessions.engine.tick = 40
        await ResidentWriter(sessions).flush_once()
        self.assertEqual(json.loads(self.path.read_text()), {"version": 3})
        self.assertFalse(self.store._dirty)

    async def test_cancel_drains_disk_job_before_world_lock_is_released(self):
        sessions = SimpleNamespace(engine=SimpleNamespace(resident_store=self.store, tick=20), _lock=asyncio.Lock())
        started, release = threading.Event(), threading.Event()

        def slow_write(jobs):
            started.set()
            if not release.wait(3):
                raise TimeoutError("Test did not release writer")
            return write_resident_batch(jobs)

        with patch("persistence.resident_writer.write_resident_batch", side_effect=slow_write):
            task = asyncio.create_task(ResidentWriter(sessions).flush_once())
            try:
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await asyncio.sleep(.001)
                task.cancel()
                await asyncio.sleep(.01)
                self.assertFalse(task.done())
                self.assertTrue(sessions._lock.locked())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertFalse(sessions._lock.locked())
        self.assertIn("h_000001", self.store._dirty)
