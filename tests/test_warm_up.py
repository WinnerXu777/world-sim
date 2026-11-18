"""First-use costs of a new or restored world are paid on the New/Continue request, not on its first game ticks.

Found by ``tools/restart_probe.py``: the first tick after a Continue spent about 45 ms loading the memory graph (``import faiss`` 29 ms,
the pickle, the index) and syncing every restored resident into it; with the machine busy that tick alone overran the 50 ms budget.
"""
import sys
import unittest
import uuid

from authored_village import load_village_maps
from test_startup_preservation import backend, _test_storage
from test_map_contract import AsyncRegistryIsolation
from persistence.sessions import GameSessions


def make_sessions(name):
    return GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime, _test_storage / "wu" / uuid.uuid4().hex[:8],
                        backend.create_genesis, 905, map_name="starter_village")


class WarmUpCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        self.loads = 0
        self._original = backend.build_or_load_default_memory_rag

        def counting(*a, **k):
            self.loads += 1
            return self._original(*a, **k)
        backend.build_or_load_default_memory_rag = counting

    async def asyncTearDown(self):
        backend.build_or_load_default_memory_rag = self._original
        await super().asyncTearDown()

    async def test_continue_loads_the_memory_graph_and_syncs_every_resident_before_the_first_tick(self):
        sessions = make_sessions("continue")
        await sessions.new("Warm")
        for _ in range(30):
            backend.engine.step()
        await sessions.save()
        save_id = sessions.active_id
        backend.engine.reset_world()
        self.loads = 0
        await sessions.continue_world(save_id)
        engine = backend.engine
        self.assertEqual(self.loads, 1)  # loaded during the request
        self.assertIsNotNone(engine.memory_rag)
        self.assertEqual(engine.resident_store.pending_memory_dirty_ids(), [])
        humans = [u for u in engine._human_uid_by_slot if u]
        self.assertTrue(all(f"resident:{uid}" in engine.memory_rag.nodes for uid in humans))
        for _ in range(5):
            engine.step()
        self.assertEqual(self.loads, 1)  # the first ticks load nothing

    async def test_new_game_warms_up_too(self):
        sessions = make_sessions("new")
        self.loads = 0
        await sessions.new("Warm new")
        self.assertEqual(self.loads, 1)
        for _ in range(5):
            backend.engine.step()
        self.assertEqual(self.loads, 1)

    async def test_a_failing_warm_up_never_fails_the_request(self):
        sessions = make_sessions("failing")
        await sessions.new("Warm failing")
        await sessions.save()
        save_id = sessions.active_id
        backend.engine.reset_world()
        original = backend.engine.warm_up_world

        def broken():
            raise RuntimeError("memory graph unavailable")
        backend.engine.warm_up_world = broken
        try:
            result = await sessions.continue_world(save_id)
        finally:
            backend.engine.warm_up_world = original
        self.assertTrue(result["ok"])
        self.assertTrue(backend.engine.world_loaded)
        self.assertIsNone(sessions.last_error)

    async def test_the_process_warm_up_imports_the_index_library_once(self):
        backend.engine.warm_up_process()
        self.assertIn("faiss", sys.modules)  # the first import cost no longer lands on a tick
        backend.engine.warm_up_process()  # idempotent


if __name__ == "__main__":
    unittest.main()
