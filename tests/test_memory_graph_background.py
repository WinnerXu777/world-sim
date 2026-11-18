"""The memory graph is written off the tick path (worker thread, debounced) and is current on disk after a clean shutdown."""
from authored_village import MAP_FILES, load_village_maps
import json
import os
import pickle
import threading
import unittest
from pathlib import Path

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation
import systems.memory.state_memoryrag as memory_module
from systems.memory.state_memoryrag import BackgroundGraphWriter, write_graph_file
from systems.movement.map_contract import load_from_environment

ROOT = Path(__file__).resolve().parents[1]
VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"


async def roster_world():
    load_village_maps()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    return backend.engine


def graph_on_disk():
    with backend.MEMORY_RAG_GRAPH_PATH.open("rb") as handle:
        return pickle.load(handle)


class WriterTests(unittest.TestCase):
    def test_writes_atomically_coalesces_and_drains(self):
        import tempfile
        directory = Path(tempfile.mkdtemp(prefix="mg", dir=backend.MEMORY_RAG_GRAPH_PATH.parent.parent))
        target = directory / "g.pkl"
        writer = BackgroundGraphWriter()
        for index in range(20):
            writer.submit(target, pickle.dumps({"n": index}), index)
        self.assertTrue(writer.drain(5.0))
        self.assertEqual(pickle.loads(target.read_bytes()), {"n": 19})  # the newest blob always wins
        self.assertLessEqual(writer.writes, 20)
        self.assertEqual((writer.errors, list(directory.glob("*.tmp"))), (0, []))

    def test_a_failing_write_is_counted_and_never_raised(self):
        writer = BackgroundGraphWriter()
        blocker = backend.MEMORY_RAG_GRAPH_PATH.parent / "a-file-not-a-directory"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_bytes(b"x")
        writer.submit(blocker / "g.pkl", b"data", 1)
        self.assertTrue(writer.drain(5.0))
        self.assertEqual(writer.errors, 1)
        self.assertTrue(writer.last_error)

    def test_discard_drops_what_has_not_started(self):
        writer = BackgroundGraphWriter()
        with writer._cond:  # hold the lock so the thread cannot take the job before we discard it
            writer._pending = (backend.MEMORY_RAG_GRAPH_PATH.parent / "never.pkl", b"x", 0)
        writer.discard()
        self.assertFalse((backend.MEMORY_RAG_GRAPH_PATH.parent / "never.pkl").exists())


class EngineTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._interval = backend.MEMORY_RAG_BACKGROUND_SAVE_INTERVAL_SEC
        self._write = memory_module.write_graph_file
        self.write_threads = []

        def recording(target, blob, count):
            self.write_threads.append(threading.get_ident())
            return self._write(target, blob, count)
        memory_module.write_graph_file = recording

    async def asyncTearDown(self):
        backend.MEMORY_RAG_BACKGROUND_SAVE_INTERVAL_SEC = self._interval
        memory_module.write_graph_file = self._write
        await super().asyncTearDown()

    async def test_the_tick_path_never_writes_the_graph_itself(self):
        backend.MEMORY_RAG_BACKGROUND_SAVE_INTERVAL_SEC = 0.0
        engine = await roster_world()
        self.write_threads.clear()  # genesis may save inline; only what happens after this counts
        engine.flush_memory_graph_queue(force=True, save=False)
        main = threading.get_ident()
        for _ in range(600):
            engine.step()
        engine._memory_graph_writer.drain(5.0)
        self.assertGreater(engine._memory_graph_writer.writes, 0)
        self.assertNotIn(main, self.write_threads)
        self.assertEqual(engine._memory_graph_writer.errors, 0)

    async def test_saves_are_debounced(self):
        backend.MEMORY_RAG_BACKGROUND_SAVE_INTERVAL_SEC = 3600.0
        engine = await roster_world()
        self.write_threads.clear()  # genesis may save inline; only what happens after this counts
        engine.flush_memory_graph_queue(force=True, save=False)
        for _ in range(600):
            engine.step()
        engine._memory_graph_writer.drain(5.0)
        self.assertLessEqual(engine._memory_graph_writer.writes, 1)

    async def test_the_graph_on_disk_is_current_after_finalize(self):
        backend.MEMORY_RAG_BACKGROUND_SAVE_INTERVAL_SEC = 3600.0  # nothing is written by the ticks themselves
        engine = await roster_world()
        self.write_threads.clear()  # genesis may save inline; only what happens after this counts
        engine.flush_memory_graph_queue(force=True, save=False)
        for _ in range(100):
            engine.step()
        human_id = next(u for u in engine._human_uid_by_slot if u)
        engine.resident_store.record_event(human_id, engine.tick, "gift_received", note="unique-marker-for-the-test")
        engine.step()
        self.assertTrue(engine.finalize_memory_graph())
        payload = graph_on_disk()
        self.assertIn(f"resident:{human_id}", payload["nodes"])
        self.assertTrue(any("unique-marker-for-the-test" in json.dumps(vars(node), default=str) for node in payload["nodes"].values()),
                        "the newest memory event is missing from the file")
        self.assertEqual(len(payload["nodes"]), len(engine.memory_rag.nodes))
        self.assertEqual(list(backend.MEMORY_RAG_GRAPH_PATH.parent.glob("*.tmp")), [])

    async def test_a_session_save_queues_the_current_graph_without_blocking(self):
        engine = await roster_world()
        self.write_threads.clear()  # genesis may save inline; only what happens after this counts
        engine.flush_memory_graph_queue(force=True, save=False)
        self.assertTrue(engine.queue_memory_graph_write())
        self.assertTrue(engine._memory_graph_writer.drain(5.0))
        self.assertEqual(len(graph_on_disk()["nodes"]), len(engine.memory_rag.nodes))
        self.assertNotIn(threading.get_ident(), self.write_threads)

    async def test_an_explicit_save_is_still_synchronous_and_beats_older_background_blobs(self):
        engine = await roster_world()
        self.write_threads.clear()  # genesis may save inline; only what happens after this counts
        engine.flush_memory_graph_queue(force=True, save=False)
        engine.queue_memory_graph_write()
        engine.sync_memory_graph(save=True)
        self.assertIn(threading.get_ident(), self.write_threads)
        self.assertTrue(backend.MEMORY_RAG_GRAPH_PATH.exists())

    async def test_reset_world_discards_a_pending_background_write(self):
        engine = await roster_world()
        self.write_threads.clear()  # genesis may save inline; only what happens after this counts
        engine.flush_memory_graph_queue(force=True, save=False)
        engine.queue_memory_graph_write()
        engine.reset_world()
        self.assertFalse(backend.MEMORY_RAG_GRAPH_PATH.exists())


if __name__ == "__main__":
    unittest.main()
