"""1008 WS-D P5 (a): ``harness/window.py`` SlotAllocator and release_slots on a synthetic world (the real engine, nothing registered).

The rows of a streaming window come and go while the engine runs. These tests pin what "gone" means: after any sequence of allocate and
release calls that frees every row, the tensors, the id list, the live count, the geometry, the harness index and the caches are as they were,
except that each released slot counts one more generation in ``M_GEN``."""
import random
import sys
import types
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
import map_geo  # noqa: E402
from harness import window  # noqa: E402
from harness.frame import AbsPos  # noqa: E402
from harness.spatial_index import SpatialIndex  # noqa: E402

ANIMAL = 40                      # inside cfg.ANIMAL_TYPES


class WindowSlotTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.engine = engine = backend.engine
        engine.reset_world()
        map_geo.reset_window()
        self.m = engine.state.m_tensor
        self.index = SpatialIndex()
        engine.harness = types.SimpleNamespace(world=types.SimpleNamespace(index=self.index))
        self.addCleanup(lambda: setattr(engine, "harness", None))
        self.addCleanup(engine.reset_world)
        self.alloc = window.SlotAllocator(engine, budget=window.WINDOW_ROW_BUDGET)

    def put(self, n, start=0, m_type=None, geo=False):
        uids = [f"c0_0:t{start + i}" for i in range(n)]
        types_ = [float(cfg.M_FOREST if m_type is None else m_type)] * n
        xs, ys = [10.0 + 7 * (start + i) for i in range(n)], [20.0 + 3 * (start + i) for i in range(n)]
        slots = self.alloc.allocate(uids, types_, xs, ys, {cfg.M_HP: [100.0] * n, cfg.SCALE: [12.0] * n, cfg.M_RESOURCE_FOOD: [30.0] * n})
        if geo:
            for slot, x, y in zip(slots, xs, ys):
                map_geo.register_entity(slot, "circle", x, y, 12.0)
        return uids, slots

    def assert_empty(self, generations=None):
        m = self.m.clone()
        gen = m[:, cfg.M_GEN].clone()
        m[:, cfg.M_GEN] = 0.0
        self.assertFalse(bool(m.any()), "every column other than M_GEN is zero")
        if generations is not None:
            self.assertEqual(gen.tolist(), generations)
        self.assertEqual(self.engine._entity_count_ref[0], 0)
        self.assertEqual([u for u in self.engine._entity_uid_by_slot if u is not None], [])
        self.assertEqual(dict(map_geo.MAP_GEO), {})
        self.assertEqual(dict(map_geo.TILE_TO_ENTITY), {})
        self.assertEqual(len(self.index), 0)
        self.assertEqual(self.alloc.owned, set())

    # -- allocate ------------------------------------------------------------------------------------------------------------
    async def test_allocate_claims_the_lowest_free_rows_and_writes_them(self):
        uids, slots = self.put(5)
        self.assertEqual(slots, [0, 1, 2, 3, 4])
        self.assertEqual([self.engine._entity_uid_by_slot[s] for s in slots], uids)
        self.assertEqual(self.engine._entity_count_ref[0], 5)
        self.assertEqual(float(self.m[2, cfg.CX]), 24.0)
        self.assertEqual(float(self.m[2, cfg.M_TYPE]), float(cfg.M_FOREST))
        self.assertEqual(float(self.m[4, cfg.M_RESOURCE_FOOD]), 30.0)
        self.assertEqual(self.alloc.owned, set(slots))
        _, more = self.put(2, start=5)
        self.assertEqual(more, [5, 6])
        # a hole is refilled first, like entity_born
        self.alloc.release([1])
        _, again = self.put(1, start=9)
        self.assertEqual(again, [1])

    async def test_allocator_writes_what_entity_born_would_write(self):
        slot = iat.entity_born(self.m, self.engine._entity_count_ref, 10.0, 20.0, cfg.M_FOREST, hp=100.0, scale=12.0,
                               col_vals={cfg.M_RESOURCE_FOOD: 30.0})
        born = self.m[slot].clone()
        self.engine._entity_count_ref[0] -= 1
        self.m[slot] = 0.0
        _, slots = self.put(1)
        self.assertEqual(slots, [slot])
        self.assertTrue(torch.equal(self.m[slot], born))

    async def test_refused_requests_change_nothing(self):
        self.put(3, geo=True)
        before = (self.m.clone(), list(self.engine._entity_uid_by_slot), self.engine._entity_count_ref[0], dict(map_geo.TILE_TO_ENTITY))
        small = window.SlotAllocator(self.engine, budget=4)
        small.owned = {0, 1, 2}
        bad = [
            (window.SlotExhausted, lambda: small.allocate(["a", "b"], [1.0, 1.0], [0, 0], [0, 0])),             # over the budget
            (ValueError, lambda: self.alloc.allocate(["a", "a"], [1.0, 1.0], [0, 0], [0, 0])),                   # duplicate uid in the request
            (ValueError, lambda: self.alloc.allocate(["c0_0:t0"], [1.0], [0], [0])),                             # uid already live
            (ValueError, lambda: self.alloc.allocate(["z"], [0.0], [0], [0])),                                   # type 0 is a free row
            (ValueError, lambda: self.alloc.allocate(["z"], [1.0], [0], [0], {cfg.M_GEN: [5.0]})),               # the generation is the allocator's
            (ValueError, lambda: self.alloc.allocate(["z", "y"], [1.0], [0], [0])),                              # ragged
        ]
        for error, call in bad:
            with self.assertRaises(error):
                call()
        self.assertTrue(torch.equal(before[0], self.m))
        self.assertEqual(before[1:3], (list(self.engine._entity_uid_by_slot), self.engine._entity_count_ref[0]))
        self.assertEqual(before[3], dict(map_geo.TILE_TO_ENTITY))

    async def test_running_out_of_rows_is_refused_whole(self):
        big = window.SlotAllocator(self.engine, budget=cfg.MAX_ENTITIES + 50)
        n = cfg.MAX_ENTITIES
        big.allocate([f"u{i}" for i in range(n)], [1.0] * n, [0.0] * n, [0.0] * n)
        self.assertEqual(big.headroom(), 0)
        with self.assertRaises(window.SlotExhausted):
            big.allocate(["extra"], [1.0], [0.0], [0.0])
        big.release(range(n))
        self.assertEqual(big.headroom(), cfg.MAX_ENTITIES)

    # -- release -------------------------------------------------------------------------------------------------------------
    async def test_release_leaves_nothing_behind(self):
        uids, slots = self.put(4, geo=True)
        uid = uids[1]
        self.engine._inventory_seeded_containers.update({uid, f"stock:{uid}", "stock:keep"})
        self.engine._actor_prev_positions[uid] = (1.0, 2.0)
        self.index.insert(uid, 0, AbsPos(0, 0, 3.0, 4.0))
        self.engine._prev_entity_mask[slots[1]] = True
        self.assertIn(slots[1], map_geo.MAP_GEO)
        version = map_geo.geo_version
        self.assertEqual(self.alloc.release([slots[1], slots[1], 900]), [uid])          # duplicates and free rows are skipped
        slot = slots[1]
        self.assertFalse(bool(self.m[slot].clone().index_fill_(0, torch.tensor([cfg.M_GEN]), 0.0).any()))
        self.assertEqual(float(self.m[slot, cfg.M_GEN]), 1.0)
        self.assertIsNone(self.engine._entity_uid_by_slot[slot])
        self.assertNotIn(slot, map_geo.MAP_GEO)
        self.assertNotIn(slot, set(map_geo.TILE_TO_ENTITY.values()))
        self.assertGreater(map_geo.geo_version, version)
        self.assertEqual(self.engine._inventory_seeded_containers, {"stock:keep"})
        self.assertNotIn(uid, self.engine._actor_prev_positions)
        self.assertNotIn(uid, self.index)
        self.assertFalse(bool(self.engine._prev_entity_mask[slot]))
        self.assertEqual(self.engine._entity_count_ref[0], 3)
        self.assertNotIn(slot, self.alloc.owned)
        self.assertTrue(self.engine._force_map_refresh)

    async def test_a_released_slot_has_a_new_generation_and_keeps_it_through_reuse_and_entity_born(self):
        _, (slot,) = self.put(1)
        stale = (slot, window.generation_of(self.engine, slot))
        self.alloc.release([slot])
        self.assertNotEqual(stale, (slot, window.generation_of(self.engine, slot)))
        _, (again,) = self.put(1, start=3)
        self.assertEqual(again, slot)
        self.assertEqual(window.generation_of(self.engine, slot), 1)
        self.alloc.release([slot])
        born = iat.entity_born(self.m, self.engine._entity_count_ref, 5.0, 5.0, cfg.M_FOREST)
        self.assertEqual(born, slot)
        self.assertEqual(window.generation_of(self.engine, slot), 2, "the legacy birth path keeps the counter")
        self.engine._entity_count_ref[0] -= 1

    async def test_animal_release_emits_the_despawn_the_mask_difference_would_have(self):
        uids, slots = self.put(3, m_type=ANIMAL)
        for slot in slots[:2]:
            self.engine._prev_a_mask[slot] = True                     # the client saw these two
            self.engine._prev_entity_mask[slot] = True
        self.engine._pending_despawns.clear()
        before = len(self.engine._pending_events)
        self.alloc.release(slots)
        self.assertEqual(sorted(self.engine._pending_despawns), sorted(uids[:2]))
        events = self.engine._pending_events[before:]
        self.assertEqual([(e["type"], e["id"]) for e in events], [("animal_despawned", u) for u in uids[:2]])
        self.assertFalse(bool(self.engine._prev_a_mask.any()))
        h_mask, a_mask, entity_mask = self.engine._current_masks()
        count = len(self.engine._pending_events)
        self.engine._sync_slot_ids_and_events(h_mask, a_mask, entity_mask)
        self.assertEqual(len(self.engine._pending_events), count, "the next sync finds nothing left to announce")
        self.engine._pending_despawns.clear()
        self.engine._pending_events.clear()

    async def test_other_types_emit_no_despawn(self):
        _, slots = self.put(2)
        self.engine._pending_despawns.clear()
        before = len(self.engine._pending_events)
        self.alloc.release(slots)
        self.assertEqual(self.engine._pending_despawns, [])
        self.assertEqual(len(self.engine._pending_events), before)

    async def test_release_works_on_rows_the_allocator_did_not_claim(self):
        slot = iat.entity_born(self.m, self.engine._entity_count_ref, 50.0, 50.0, cfg.M_FOREST, hp=100.0, scale=10.0, register_geo=True)
        self.engine._entity_uid_by_slot[slot] = "legacy_1"
        self.assertEqual(window.release_slots(self.engine, [slot]), ["legacy_1"])
        self.assertEqual(self.engine._entity_count_ref[0], 0)
        self.assertNotIn(slot, map_geo.MAP_GEO)

    # -- cycles --------------------------------------------------------------------------------------------------------------
    async def test_load_unload_cycles_leave_the_world_as_it_was(self):
        rng = random.Random(1008)
        released_count = [0] * cfg.MAX_ENTITIES
        live = {}
        serial = 0
        for cycle in range(60):
            n = rng.randint(1, 25)
            uids = [f"c{cycle}:{serial + i}" for i in range(n)]
            serial += n
            kinds = [rng.choice((cfg.M_FOREST, cfg.M_FOREST, ANIMAL, cfg.M_FARM)) for _ in range(n)]
            slots = self.alloc.allocate(uids, [float(k) for k in kinds], [rng.uniform(0, 1100) for _ in range(n)],
                                        [rng.uniform(0, 800) for _ in range(n)], {cfg.SCALE: [rng.uniform(4, 30) for _ in range(n)]})
            for slot, uid, kind in zip(slots, uids, kinds):
                live[slot] = uid
                if kind != ANIMAL:
                    map_geo.register_entity(slot, "circle", float(self.m[slot, cfg.CX]), float(self.m[slot, cfg.CY]), float(self.m[slot, cfg.SCALE]))
            drop = rng.sample(sorted(live), rng.randint(0, len(live)))
            self.alloc.release(drop)
            for slot in drop:
                released_count[slot] += 1
                del live[slot]
            self.assertEqual(self.engine._entity_count_ref[0], len(live))
            self.assertEqual(int((self.m[:, cfg.M_TYPE] > 0).sum()), len(live))
            self.assertEqual({s for s, u in enumerate(self.engine._entity_uid_by_slot) if u is not None}, set(live))
            self.assertLessEqual(set(map_geo.MAP_GEO), set(live))
            self.assertLessEqual(set(map_geo.TILE_TO_ENTITY.values()), set(live))
            self.assertEqual(self.alloc.owned, set(live))
        self.alloc.release(sorted(live))
        for slot in live:
            released_count[slot] += 1
        self.assert_empty([float(c) for c in released_count])


if __name__ == "__main__":
    unittest.main()
