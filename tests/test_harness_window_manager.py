"""1008 WS-D P5 (c): the WindowManager on a synthetic world (real engine, real generator, ChunkService with workers=0 so a chunk is ready the tick
it is requested). One chunk is integrated or unloaded per tick, nearest first / farthest first; rows, geometry, wall boxes and void boxes follow the
integrated set; an unloaded chunk stores a delta against the generated state and gets it back."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
import genesis_config as cfg  # noqa: E402
import map_geo  # noqa: E402
from harness import engine_hooks as eh, spaces, window, window_manager  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402
from systems.movement.spatial import world_contract  # noqa: E402
from systems.worldgen import PinnedSet, starter_village_area  # noqa: E402
from systems.worldgen.rings import ChunkCoord, RingConfig  # noqa: E402
from systems.worldgen.service import ChunkService  # noqa: E402

ON = {"EDEN_WINDOW": "1", "EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1", "EDEN_MAP_RESOURCES": "1"}


class WindowFixture(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, ON)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = engine = backend.engine
        engine.reset_world()
        map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear()
        map_geo.configure_window(352, 352, (-160, -160), sparse=True)
        self.addCleanup(map_geo.reset_window)
        self.addCleanup(engine.reset_world)
        self.service = ChunkService(1008, pinned=PinnedSet([starter_village_area()]), workers=0)
        self.addCleanup(self.service.close)
        self.manager = window_manager.WindowManager(engine, self.service)
        self.addCleanup(lambda: setattr(engine, "_window", None))
        self.addCleanup(lambda: setattr(engine, "_window_contract", None))

    def place_human(self, slot, x, y):
        h = self.engine.state.h_tensor
        h[slot] = 0.0
        h[slot, cfg.TYPE], h[slot, cfg.X], h[slot, cfg.Y] = float(cfg.AGENT_TYPE_HUMAN), x, y

    def run_ticks(self, n):
        for _ in range(n):
            self.engine.tick += 1
            self.manager.tick()


class IntegrationTests(WindowFixture):
    async def test_one_chunk_per_tick_nearest_first_until_the_ring_is_full(self):
        self.place_human(0, 520.0, 520.0)                                      # chunk (2, 2)
        self.run_ticks(1)
        self.assertEqual(len(self.manager.chunks), 1)
        self.assertEqual(next(iter(self.manager.chunks)), ChunkCoord(2, 2), "the chunk the resident stands in comes first")
        self.run_ticks(24)
        self.assertEqual(len(self.manager.chunks), 25)
        self.assertEqual(set(self.manager.chunks), {ChunkCoord(x, y) for x in range(0, 5) for y in range(0, 5)})
        self.run_ticks(5)
        self.assertEqual(len(self.manager.chunks), 25, "nothing more to integrate; nothing unloads inside the hysteresis ring")
        self.assertEqual([entry[1] for entry in self.manager.log], ["integrate"] * 25)

    async def test_rows_geometry_and_ids_follow_the_chunks(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        m = self.engine.state.m_tensor
        owned = sorted(self.manager.allocator.owned)
        self.assertGreater(len(owned), 20)
        self.assertEqual(int((m[:, cfg.M_TYPE] > 0).sum()), len(owned))
        self.assertEqual(self.engine._entity_count_ref[0], len(owned))
        for slot in owned:
            uid = self.engine._entity_uid_by_slot[slot]
            self.assertRegex(uid, r"^c\d+_\d+:")
            self.assertIn(slot, map_geo.MAP_GEO)
            cx, cy = (int(v) for v in uid.split(":")[0][1:].split("_"))
            x, y = float(m[slot, cfg.CX]), float(m[slot, cfg.CY])
            self.assertTrue(cx * 256 <= x < (cx + 1) * 256 and cy * 256 <= y < (cy + 1) * 256, (uid, x, y))
        self.assertEqual(float(m[owned, cfg.M_SPACE].abs().sum()), 0.0)

    async def test_walls_and_void_boxes_reach_the_contract_and_the_flag_gates_them(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        published = self.engine._window_contract
        voids = [b for b in published["boxes"] if b["id"].startswith("void:")]
        self.assertEqual(len(voids), 20, "one box per outer edge of a 5 x 5 block")
        self.assertEqual(published["bounds"], [0.0, 0.0, 1280.0, 1280.0])
        contract = world_contract(self.engine)
        ids = {b["id"] for b in contract["boxes"]}
        self.assertTrue({b["id"] for b in published["boxes"]} <= ids)
        self.assertEqual(contract["bounds"][2], 1280.0)
        revision = contract["revision"]
        self.assertEqual(world_contract(self.engine)["revision"], revision, "stable while the set is unchanged")
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "0"}):
            plain = world_contract(self.engine)
            self.assertFalse(any(b["id"].startswith(("void:", "c")) for b in plain["boxes"]))
            self.assertNotEqual(plain["revision"], revision)

    async def test_the_void_box_closes_a_gap_to_an_actor(self):
        from systems.movement import spatial
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        contract = world_contract(self.engine)
        end = spatial.slide((1270.0, 600.0), (1290.0, 600.0), contract)
        self.assertLess(end[0], 1280.0, "an actor cannot walk out of the integrated block")

    async def test_budget_defers_integration_and_counts_it(self):
        self.manager.allocator.budget = 12
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(30)
        self.assertLessEqual(len(self.manager.allocator.owned), 12)
        self.assertGreater(self.manager.counters["deferred_budget"], 0)
        self.assertLess(len(self.manager.chunks), 25)


class UnloadTests(WindowFixture):
    async def test_leaving_unloads_one_chunk_per_tick_and_releases_everything(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        before_rows = len(self.manager.allocator.owned)
        self.place_human(0, 2600.0, 520.0)                                    # ten chunks east
        self.run_ticks(1)
        unloaded = [e for e in self.manager.log if e[1] == "unload"]
        self.assertLessEqual(len(unloaded), 1)
        self.run_ticks(60)
        left = set(self.manager.chunks)
        self.assertFalse(any(c.x <= 1 for c in left), "far chunks are unloaded")
        owned = self.manager.allocator.owned
        self.assertEqual(int((self.engine.state.m_tensor[:, cfg.M_TYPE] > 0).sum()), len(owned))
        self.assertEqual(set(map_geo.MAP_GEO), set(owned))
        self.assertEqual({s for s, u in enumerate(self.engine._entity_uid_by_slot) if u is not None}, set(owned))
        self.assertNotEqual(len(owned), before_rows)

    async def test_a_delta_survives_unload_and_a_removed_entity_stays_removed(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        m = self.engine.state.m_tensor
        coord = ChunkCoord(2, 2)
        state = self.manager.chunks[coord]
        self.assertGreaterEqual(len(state.slots), 2)
        keep_slot, drop_slot = state.slots[0], state.slots[1]
        keep_uid, drop_uid = state.uids[0], state.uids[1]
        food_col = cfg.M_RESOURCE_FOOD if float(m[keep_slot, cfg.M_RESOURCE_FOOD]) > 0 else cfg.M_NODE_STOCK
        original = float(m[keep_slot, food_col])
        m[keep_slot, food_col] = original / 2.0
        m[drop_slot, cfg.M_TYPE] = 0.0                                          # the game destroyed it
        self.manager.unload(coord)
        self.assertEqual(self.manager.deltas[coord][drop_uid], {"removed": True})
        self.assertIn(food_col, self.manager.deltas[coord][keep_uid]["cols"])
        chunk = self.service.peek(coord) or self.service.get_blocking(coord)
        self.manager.integrate(coord, chunk)
        again = self.manager.chunks[coord]
        self.assertNotIn(drop_uid, again.uids)
        slot = again.slots[again.uids.index(keep_uid)]
        self.assertEqual(float(m[slot, food_col]), original / 2.0)
        self.manager.unload(coord)
        self.manager.integrate(coord, chunk)
        self.assertEqual(float(m[self.manager.chunks[coord].slots[self.manager.chunks[coord].uids.index(keep_uid)], food_col]), original / 2.0)

    async def test_an_untouched_chunk_leaves_no_delta(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        self.manager.unload(ChunkCoord(3, 3))
        self.assertNotIn(ChunkCoord(3, 3), self.manager.deltas)


class InstallTests(WindowFixture):
    async def test_flags_are_checked_and_the_hooks_are_registered(self):
        DISPATCH.clear()
        self.addCleanup(lambda: (eh.uninstall(DISPATCH), DISPATCH.clear()))
        with mock.patch.dict(os.environ, {"EDEN_MAP_RESOURCES": "0"}):
            with self.assertRaises(spaces.SpaceConfigError) as caught:
                eh.install(DISPATCH)
        self.assertIn("EDEN_MAP_RESOURCES", str(caught.exception))
        with mock.patch.dict(os.environ, {"EDEN_SPACES": "0"}):
            with self.assertRaises(spaces.SpaceConfigError) as caught:
                eh.install(DISPATCH)
        self.assertIn("EDEN_SPACES", str(caught.exception))
        self.assertTrue(eh.install(DISPATCH))
        self.assertIn("harness_window", {name for name, _ in DISPATCH.step_hooks})
        self.assertIn("harness_window_genesis", {name for name, _ in DISPATCH.genesis_hooks})

    async def test_the_step_hook_ticks_the_manager_for_the_current_world(self):
        self.place_human(0, 520.0, 520.0)
        self.engine.tick += 1
        eh.window_hook(self.engine)
        self.assertEqual(len(self.manager.chunks), 1)
        self.assertIs(window_manager.manager_for(self.engine), self.manager)

    async def test_stats_report_pump_and_tick_cost(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(10)
        stats = self.manager.stats()
        self.assertEqual(stats["pump_ms"]["n"], 10)
        self.assertEqual(stats["tick_ms"]["n"], 10)
        self.assertEqual(stats["counters"]["integrated"], 10)


if __name__ == "__main__":
    unittest.main()
