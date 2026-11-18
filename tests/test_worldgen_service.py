"""Rings (pure planner) and ChunkService (priority queue, cancellation, LRU, worker processes)."""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from systems.worldgen import PinnedSet, generate_chunk, starter_village_area
from systems.worldgen import generate as gen
from systems.worldgen.rings import (Actor, CameraChunkWindow, ChunkCoord, RingConfig, actor_rings, blocked_by_void, chunk_of, chunk_priority, heading,
                                    plan_stream)
from systems.worldgen.service import ChunkCache, ChunkService

VILLAGE = PinnedSet([starter_village_area()])
CU = 256.0


def at(cx, cy, vx=0.0, vy=0.0):
    return Actor((cx + 0.5) * CU, (cy + 0.5) * CU, vx, vy)


def explode(args):
    """Worker entry that fails for one chunk (module level so worker processes can import it)."""
    if args[1] == 3 and args[2] == 3:
        raise RuntimeError("boom")
    return gen.generate_payload(args)


class RingTests(unittest.TestCase):
    def test_defaults_are_the_d11_rings(self):
        cfg = RingConfig()
        self.assertEqual((cfg.simulation_radius, cfg.prefetch_extra, cfg.lead_extra, cfg.keep_extra, cfg.render_margin), (2, 2, 2, 1, 1))
        self.assertEqual(cfg.prefetch_radius, 4)
        self.assertEqual(cfg.chunk_units, 256.0)

    def test_a_standing_actor_has_a_5x5_simulation_ring_and_a_9x9_generation_ring(self):
        plan = plan_stream([at(10, -4)])
        self.assertEqual(len(plan.simulate), 25)
        self.assertEqual(len(plan.wanted), 81)
        self.assertEqual({(c.x, c.y) for c in plan.simulate}, {(x, y) for x in range(8, 13) for y in range(-6, -1)})
        self.assertEqual(len(plan.integrate), 25)
        self.assertEqual(plan.unload, ())
        self.assertEqual(plan.render, frozenset())

    def test_a_moving_actor_prefetches_two_more_chunks_ahead_and_none_behind(self):
        east = plan_stream([at(0, 0, vx=20.0)])
        xs = sorted({c.x for c in east.wanted})
        self.assertEqual((xs[0], xs[-1]), (-4, 6))                       # 4 behind, 4 + 2 lead ahead
        self.assertEqual(len(east.wanted), 11 * 9)
        north_west = plan_stream([at(0, 0, vx=-14.0, vy=-14.0)])
        self.assertEqual((min(c.x for c in north_west.wanted), min(c.y for c in north_west.wanted)), (-6, -6))     # diagonal lead: 2 along each axis rounded
        slow = plan_stream([at(0, 0, vx=1.0)])
        self.assertEqual(len(slow.wanted), 81)                           # below lead_min_speed: no heading, no bias
        self.assertIsNone(heading(Actor(0, 0, 1.0, 0.0), RingConfig()))
        self.assertAlmostEqual(heading(Actor(0, 0, 0.0, -5.0), RingConfig())[1], -1.0)

    def test_the_lead_never_shrinks_the_simulation_ring(self):
        sim, pre = actor_rings(at(2, 2, vx=-30.0, vy=5.0), RingConfig())
        self.assertTrue(sim <= pre)
        self.assertEqual(len(sim), 25)

    def test_load_and_unload_sets_with_hysteresis(self):
        loaded = {ChunkCoord(x, 0) for x in range(-2, 3)}
        plan = plan_stream([at(0, 0)], loaded=[(c.chunk_id) for c in loaded])                 # ids as strings are accepted
        self.assertEqual(len(plan.integrate), 25 - 5)
        self.assertEqual(plan.unload, ())
        # the actor walked 3 chunks east: chunk -2 is 5 away (beyond sim 2 + hysteresis 1), chunk 0 is 3 away (kept), chunk 3 is new
        plan = plan_stream([at(3, 0)], loaded=loaded)
        self.assertIn(ChunkCoord(-2, 0), plan.unload)
        self.assertNotIn(ChunkCoord(2, 0), plan.unload)
        self.assertNotIn(ChunkCoord(1, 0), plan.unload)
        self.assertIn(ChunkCoord(5, 0), set(plan.integrate))
        self.assertTrue(set(plan.unload).isdisjoint(plan.simulate))
        # farthest first
        dist = [abs(c.x - 3) for c in plan.unload]
        self.assertEqual(dist, sorted(dist, reverse=True))

    def test_chunks_in_the_simulation_ring_are_never_unloaded_and_never_prefetched_twice(self):
        loaded = {ChunkCoord(x, y) for x in range(-2, 3) for y in range(-2, 3)}
        plan = plan_stream([at(0, 0)], loaded=loaded, cached=[ChunkCoord(4, 4)], in_flight=[ChunkCoord(-4, -4)])
        self.assertEqual(plan.unload, ())
        self.assertEqual(plan.integrate, ())
        self.assertNotIn(ChunkCoord(4, 4), plan.prefetch)               # already cached
        self.assertNotIn(ChunkCoord(-4, -4), plan.prefetch)             # already requested
        self.assertNotIn(ChunkCoord(0, 0), plan.prefetch)               # already loaded
        self.assertIn(ChunkCoord(4, -4), plan.prefetch)

    def test_cached_chunks_outside_the_keep_ring_are_dropped(self):
        cached = [ChunkCoord(0, 0), ChunkCoord(5, 0), ChunkCoord(6, 0), ChunkCoord(30, 30)]     # prefetch ring 4 + keep 1 = 5
        plan = plan_stream([at(0, 0)], cached=cached)
        self.assertEqual(set(plan.drop), {ChunkCoord(6, 0), ChunkCoord(30, 30)})

    def test_priority_simulation_first_then_nearest_then_ahead(self):
        a = at(0, 0, vx=20.0)
        plan = plan_stream([a])
        order = list(plan.integrate) + list(plan.prefetch)
        first_prefetch = len(plan.integrate)
        self.assertTrue(all(plan.priority[c] < 1000 for c in order[:first_prefetch]))
        self.assertTrue(all(plan.priority[c] >= 1000 for c in order[first_prefetch:]))
        self.assertEqual(order[0], ChunkCoord(0, 0))
        ahead, behind = ChunkCoord(3, 0), ChunkCoord(-3, 0)
        self.assertLess(chunk_priority(ahead, [a], RingConfig(), False), chunk_priority(behind, [a], RingConfig(), False))
        still = at(0, 0)
        self.assertEqual(chunk_priority(ahead, [still], RingConfig(), False), chunk_priority(behind, [still], RingConfig(), False))

    def test_priorities_with_two_actors_use_the_nearest(self):
        near_second = plan_stream([at(0, 0), at(20, 0)])
        self.assertEqual(len(near_second.simulate), 50)
        self.assertEqual(near_second.priority[ChunkCoord(20, 0)], near_second.priority[ChunkCoord(0, 0)])

    def test_the_planner_is_pure(self):
        args = dict(actors=[at(3, -2, 10.0, 5.0), at(-7, 8)], loaded=[ChunkCoord(1, 1)], cached=[ChunkCoord(2, 2)])
        one, two = plan_stream(**args), plan_stream(**args)
        self.assertEqual(one, two)

    def test_render_ring_comes_from_the_camera_window_math_of_chunking_py(self):
        view = CameraChunkWindow(center_x=2.5 * CU, center_y=0.5 * CU, view_world_w=1000.0, view_world_h=600.0, margin_chunks=1)
        plan = plan_stream([at(2, 0)], view=view)
        self.assertIn(ChunkCoord(2, 0), plan.render)
        self.assertIn(ChunkCoord(4, 1), plan.render)
        self.assertEqual(len(plan.render), 7 * 5)                     # 1000 / 256 -> 4 chunks + 2 margin, 600 / 256 -> 3 chunks + 2 margin

    def test_chunk_addresses_floor_for_negative_positions(self):
        self.assertEqual(chunk_of(-0.001, -0.001), ChunkCoord(-1, -1))
        self.assertEqual(chunk_of(255.999, 256.0), ChunkCoord(0, 1))
        self.assertEqual(chunk_of(-256.0, 0.0), ChunkCoord(-1, 0))

    def test_the_void_barrier_predicate(self):
        loaded = {ChunkCoord(0, 0), ChunkCoord(1, 0)}
        self.assertFalse(blocked_by_void(300.0, 10.0, loaded))
        self.assertTrue(blocked_by_void(520.0, 10.0, loaded))
        self.assertTrue(blocked_by_void(-1.0, 10.0, loaded))


class CacheTests(unittest.TestCase):
    def chunk(self, n):
        return generate_chunk(1, n, 0)

    def test_lru_evicts_the_least_recently_used_and_counts(self):
        cache = ChunkCache(3)
        for n in range(3):
            cache.put(("k", n), self.chunk(n))
        self.assertIsNotNone(cache.get(("k", 0)))                      # refresh 0
        cache.put(("k", 3), self.chunk(3))                              # evicts 1
        self.assertNotIn(("k", 1), cache)
        self.assertIn(("k", 0), cache)
        self.assertIsNone(cache.get(("k", 1)))
        stats = cache.stats()
        self.assertEqual((stats["hits"], stats["misses"], stats["evictions"], stats["size"]), (1, 1, 1, 3))
        self.assertAlmostEqual(stats["hit_rate"], 0.5)

    def test_keys_include_seed_version_pinned_and_params(self):
        k = gen.chunk_key(1008, 3, 4, VILLAGE)
        self.assertEqual(k[0], 1008)
        self.assertEqual(k[1], gen.GENERATOR_VERSION)
        self.assertEqual(k[2], VILLAGE.fingerprint)
        self.assertEqual(k[-2:], (3, 4))
        self.assertNotEqual(k, gen.chunk_key(1009, 3, 4, VILLAGE))
        self.assertNotEqual(k, gen.chunk_key(1008, 3, 4, None))
        self.assertNotEqual(k, gen.chunk_key(1008, 3, 4, VILLAGE, gen.GenParams(max_entities=4)))


class InlineServiceTests(unittest.TestCase):
    def make(self, **kw):
        return ChunkService(1008, VILLAGE, workers=0, **kw)

    def test_request_pump_get_and_dedupe(self):
        svc = self.make(inline_budget=10)
        c = ChunkCoord(3, 1)
        self.assertEqual(svc.request(c, 1.0), "queued")
        self.assertEqual(svc.request(c, 2.0), "queued")                  # already queued with a better priority: unchanged
        self.assertEqual(svc.request(c, 0.5), "updated")
        self.assertIsNone(svc.get(c))
        ready = svc.pump()
        self.assertEqual([(r.cx, r.cy) for r in ready], [(3, 1)])
        self.assertEqual(svc.request(c, 0.0), "cached")
        self.assertEqual(svc.get(c).payload, generate_chunk(1008, 3, 1, VILLAGE).payload)
        self.assertEqual(svc.cache.stats()["hits"], 1)
        self.assertEqual(svc.cache.stats()["misses"], 1)
        self.assertEqual(svc.counters["completed"], 1)

    def test_pending_count_and_busy_track_the_queue_for_a_pump_loop(self):
        svc = self.make(inline_budget=1)
        self.assertEqual((svc.pending_count(), svc.busy()), (0, False))
        svc.request(ChunkCoord(3, 1), 1.0)
        svc.request(ChunkCoord(3, 2), 2.0)
        self.assertEqual((svc.pending_count(), svc.busy()), (2, True))
        svc.pump()                                                       # inline budget 1: one chunk per pump
        self.assertEqual(svc.pending_count(), 1)
        svc.pump()
        self.assertEqual((svc.pending_count(), svc.busy()), (0, False))

    def test_lowest_priority_value_is_generated_first(self):
        svc = self.make(inline_budget=1)
        for n, pri in ((5, 9.0), (6, 1.0), (7, 5.0), (8, 0.0)):
            svc.request(ChunkCoord(n, 0), pri)
        order = []
        for _ in range(4):
            order += [r.cx for r in svc.pump()]
        self.assertEqual(order, [8, 6, 7, 5])

    def test_reprioritising_does_not_generate_twice(self):
        svc = self.make(inline_budget=10)
        c = ChunkCoord(0, 5)
        svc.request(c, 5.0)
        svc.request(c, 1.0)
        svc.request(c, 0.1)
        self.assertEqual(len(svc.pump()), 1)
        self.assertEqual(svc.pump(), [])
        self.assertEqual(svc.counters["completed"], 1)

    def test_set_wanted_cancels_stale_requests_before_they_start(self):
        svc = self.make(inline_budget=2)
        old = [ChunkCoord(n, 0) for n in range(10)]
        for c in old:
            svc.request(c, float(c.x))
        svc.pump()                                                         # two generated: 0 and 1
        result = svc.set_wanted({ChunkCoord(100, 0): 0.0, ChunkCoord(101, 0): 1.0})      # the player turned around
        self.assertEqual(result["cancelled"], 8)
        done = []
        for _ in range(3):
            done += [(r.cx, r.cy) for r in svc.pump()]
        self.assertEqual(done, [(100, 0), (101, 0)])
        self.assertEqual(svc.counters["cancelled_queued"], 8)
        self.assertEqual(svc.counters["completed"], 4)
        self.assertFalse(any(svc.peek(c) for c in old[2:]))

    def test_apply_plan_drops_far_chunks_and_queues_the_ring(self):
        svc = self.make(inline_budget=200)
        plan = plan_stream([at(0, 0)])
        info = svc.apply_plan(plan)
        self.assertEqual(info["queued"], 81)
        self.assertEqual(len(svc.pump()), 81)
        far = plan_stream([at(50, 50)], cached=[c for c in plan.wanted])
        svc.apply_plan(far, evict_dropped=True)
        self.assertEqual(sum(1 for c in plan.wanted if svc.peek(c)), 0)
        self.assertEqual(svc.cache.evictions, 0)                         # explicit evictions are not LRU evictions
        self.assertEqual(svc.pump()[0].cx in range(46, 55), True)

    def test_lru_capacity_bounds_memory_and_evicted_chunks_regenerate_to_the_same_bytes(self):
        svc = self.make(inline_budget=20, lru_capacity=4)
        for n in range(8):
            svc.request(ChunkCoord(n, 0), float(n))
        svc.pump()
        self.assertLessEqual(len(svc.cache), 4)
        self.assertGreater(svc.cache.evictions, 0)
        self.assertIsNone(svc.peek(ChunkCoord(0, 0)))
        again = svc.get_blocking(ChunkCoord(0, 0))
        self.assertEqual(again.payload, generate_chunk(1008, 0, 0, VILLAGE).payload)

    def test_a_failing_chunk_never_raises_out_of_pump_and_can_be_retried(self):
        calls = {"n": 0}

        def flaky(args):
            calls["n"] += 1
            if args[1] == 3 and calls["n"] < 3:
                raise RuntimeError("disk on fire")
            return gen.generate_payload(args)

        svc = self.make(inline_budget=10, generate=flaky)
        bad = ChunkCoord(3, 0)
        svc.request(bad, 0.0)
        svc.request(ChunkCoord(4, 0), 1.0)
        ready = svc.pump()
        self.assertEqual([r.cx for r in ready], [4])
        self.assertIn("disk on fire", svc.failed[bad])
        self.assertEqual(svc.stats()["failed"], 1)
        svc.request(bad, 0.0)
        svc.pump()
        self.assertNotIn(bad, svc.failed)
        self.assertIsNotNone(svc.peek(bad))

    def test_stats_report_latency_and_generation_time(self):
        svc = self.make(inline_budget=10)
        for n in range(6):
            svc.request(ChunkCoord(n, 2), 0.0)
        svc.pump()
        s = svc.stats()
        self.assertEqual(s["generation_ms"]["n"], 6)
        self.assertGreater(s["generation_ms"]["p50"], 0.0)
        self.assertGreaterEqual(s["latency_ms"]["p99"], s["latency_ms"]["p50"])
        self.assertEqual(s["cache"]["size"], 6)


class PoolServiceTests(unittest.TestCase):
    def test_workers_produce_the_requested_chunks_and_cancellation_works_with_a_full_pipe(self):
        with ChunkService(1008, VILLAGE, workers=2, max_in_flight=2) as svc:
            svc.warm()
            coords = [ChunkCoord(n, n) for n in range(10, 40)]
            for i, c in enumerate(coords):
                svc.request(c, float(i))
            svc.pump()
            self.assertLessEqual(len(svc._in_flight), 2)
            svc.set_wanted({ChunkCoord(500, 500): 0.0})                    # everything queued is stale now
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and svc.peek(ChunkCoord(500, 500)) is None:
                svc.pump()
                time.sleep(0.002)
            got = svc.peek(ChunkCoord(500, 500))
            self.assertIsNotNone(got)
            self.assertEqual(got.payload, generate_chunk(1008, 500, 500, VILLAGE).payload)
            self.assertGreater(svc.counters["cancelled_queued"], 20)
            self.assertLess(svc.counters["dispatched"], 8)                 # most of the 30 never started

    def test_a_worker_exception_is_contained_and_the_pool_keeps_working(self):
        with ChunkService(1008, VILLAGE, workers=1, generate=explode) as svc:
            svc.request(ChunkCoord(3, 3), 0.0)
            svc.request(ChunkCoord(4, 4), 1.0)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and (svc.peek(ChunkCoord(4, 4)) is None or ChunkCoord(3, 3) not in svc.failed):
                svc.pump()
                time.sleep(0.002)
            self.assertIn("boom", svc.failed[ChunkCoord(3, 3)])
            self.assertIsNotNone(svc.peek(ChunkCoord(4, 4)))

    def test_get_blocking_for_tools(self):
        with ChunkService(7, None, workers=1) as svc:
            c = svc.get_blocking(ChunkCoord(-4, 9), timeout=60)
            self.assertEqual(c.payload, generate_chunk(7, -4, 9).payload)
            self.assertIs(svc.get(ChunkCoord(-4, 9)), c)


if __name__ == "__main__":
    unittest.main()
