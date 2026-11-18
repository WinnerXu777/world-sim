"""Measure the chunk generator and streaming service (1008_worldgen.md section 7). Everything printed is measured on this machine.

    .venv/Scripts/python.exe tools/bench_chunks.py                       # everything, real time (about 10 minutes; take .runtime/fullsuite.lock first)
    .venv/Scripts/python.exe tools/bench_chunks.py --sections gen,payload,lru --quick
    .venv/Scripts/python.exe tools/bench_chunks.py --sections walk --compress 10      # time-compressed stress: the world moves 10x faster

Sections:
  gen      per-chunk generation ms in one process (warm and cold region cache), and the window-vs-rest split
  payload  bytes per chunk: raw canonical JSON, zlib level 6 and 1, and the same layers as raw int16
  lru      cache hit and miss cost, parse cost of the lazy document, memory per chunk (tracemalloc)
  pool     worker-process throughput, single-request round trip, a burst of the 99-chunk generation ring, cold start
  walk     simulated walk and run of 5000 units through plan_stream + ChunkService (real clock): prefetch lead vs generation latency,
           void-barrier hits, per-tick main-thread cost of planning, pumping and integration (a chunk is "integrated" when it is taken
           from the cache; the real tensor work of D6 is NOT measured here)

NOT measured here (stated in 1008_worldgen.md): the engine-side integration cost (m_tensor slots, wall boxes, spatial hash), the client,
disk, cross-machine timing, the effect of the tick running in the same process (GIL), battery / thermal throttling.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import platform
import statistics
import sys
import time
import tracemalloc
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

import numpy as np

from systems.worldgen import PinnedSet, generate_chunk, starter_village_area
from systems.worldgen import classify
from systems.worldgen import generate as gen
from systems.worldgen.rings import Actor, ChunkCoord, RingConfig, chunk_of, plan_stream
from systems.worldgen.service import ChunkService

SEED = 1008
VILLAGE = PinnedSet([starter_village_area()])


def pct(values, p):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * p / 100.0) - 1))]


def summary(values, digits=3):
    values = list(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "min": round(min(values), digits), "p50": round(pct(values, 50), digits), "p95": round(pct(values, 95), digits),
            "p99": round(pct(values, 99), digits), "max": round(max(values), digits), "mean": round(statistics.fmean(values), digits)}


def area(n_x, n_y, x0=-12, y0=-12):
    return [(x0 + i, y0 + j) for j in range(n_y) for i in range(n_x)]


# --------------------------------------------------------------------------------------------------------------------- gen
def bench_gen(quick):
    coords = area(12, 12) if quick else area(30, 30)
    warm_cache = classify.new_cache()
    for cx, cy in coords[:10]:
        generate_chunk(SEED, cx, cy, VILLAGE, cache=warm_cache)               # import / allocator warm-up
    warm, cold, window = [], [], []
    for cx, cy in coords:
        t = time.perf_counter()
        generate_chunk(SEED, cx, cy, VILLAGE, cache=warm_cache)
        warm.append((time.perf_counter() - t) * 1000)
    for cx, cy in coords[: len(coords) // 3]:
        t = time.perf_counter()
        generate_chunk(SEED, cx, cy, VILLAGE, cache=classify.new_cache())
        cold.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        classify.compute_window(SEED, cx * 32 - 1, cy * 32 - 1, 34, 34, VILLAGE, classify.new_cache())
        window.append((time.perf_counter() - t) * 1000)
    return {"chunks": len(coords), "warm_region_cache_ms": summary(warm), "cold_region_cache_ms": summary(cold),
            "window_only_cold_ms": summary(window), "note": "single process, one chunk at a time, no other load from this tool"}


# ----------------------------------------------------------------------------------------------------------------- payload
def bench_payload(quick):
    coords = area(12, 12) if quick else area(30, 30)
    raw, z6, z1 = [], [], []
    for cx, cy in coords:
        c = generate_chunk(SEED, cx, cy, VILLAGE)
        raw.append(len(c.payload))
        z6.append(len(zlib.compress(c.payload, 6)))
        z1.append(len(zlib.compress(c.payload, 1)))
    int16 = 3 * 32 * 32 * 2
    return {"chunks": len(coords), "raw_json_bytes": summary(raw, 0), "zlib6_bytes": summary(z6, 0), "zlib1_bytes": summary(z1, 0),
            "three_layers_as_raw_int16_bytes": int16, "plan_estimate_bytes": 6000}


# --------------------------------------------------------------------------------------------------------------------- lru
def bench_lru(quick):
    svc = ChunkService(SEED, VILLAGE, workers=0, inline_budget=10 ** 6, lru_capacity=1024)
    coords = [ChunkCoord(*c) for c in area(20, 20)]
    for c in coords:
        svc.request(c, 0.0)
    svc.pump()
    n = 20000 if quick else 200000
    probe = coords[:50]
    t = time.perf_counter()
    for i in range(n):
        svc.get(probe[i % 50])
    hit_us = (time.perf_counter() - t) / n * 1e6
    missing = ChunkCoord(10 ** 7, 10 ** 7)
    t = time.perf_counter()
    for _ in range(n):
        svc.get(missing)
    miss_us = (time.perf_counter() - t) / n * 1e6
    parse, layer = [], []
    for c in coords[:100]:
        chunk = gen.Chunk(c.x, c.y, SEED, gen.GENERATOR_VERSION, svc.peek(c).payload, "x")
        t = time.perf_counter()
        chunk.document
        parse.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        chunk.layer("terrain")
        layer.append((time.perf_counter() - t) * 1000)
    tracemalloc.start()
    base = tracemalloc.take_snapshot()
    held = [generate_chunk(SEED, 40 + i, 40, VILLAGE) for i in range(200)]
    after_docs = tracemalloc.take_snapshot()
    only_bytes = [gen.Chunk(c.cx, c.cy, SEED, gen.GENERATOR_VERSION, c.payload, c.sha256) for c in held]
    held_docs_bytes = sum(s.size_diff for s in after_docs.compare_to(base, "filename"))
    del held
    tracemalloc.stop()
    return {"hit_us": round(hit_us, 3), "miss_us": round(miss_us, 3), "lazy_parse_ms": summary(parse), "layer_to_numpy_ms": summary(layer),
            "bytes_per_chunk_parsed_document_plus_payload": round(held_docs_bytes / 200), "bytes_per_chunk_payload_only": round(statistics.fmean(len(c.payload) for c in only_bytes)),
            "lru_entries": len(svc.cache), "note": "cache holds payload bytes (+ sha string); a parsed document exists only after .document is touched"}


# -------------------------------------------------------------------------------------------------------------------- pool
def drain(svc, wanted, timeout=120.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        svc.pump()
        if all(svc.peek(c) is not None for c in wanted):
            return time.perf_counter() - t0
        time.sleep(0.0005)
    raise TimeoutError("pool bench timed out")


def bench_pool(quick, workers):
    out = {"workers": workers}
    t = time.perf_counter()
    svc = ChunkService(SEED, VILLAGE, workers=workers, lru_capacity=4096)
    svc.warm()
    out["pool_start_s"] = round(time.perf_counter() - t, 3)
    n_burst = 120 if quick else 400
    coords = [ChunkCoord(*c) for c in area(20, 20 if not quick else 6, 60, 60)][:n_burst]
    for c in coords:
        svc.request(c, 0.0)
    elapsed = drain(svc, coords)
    out["burst"] = {"chunks": len(coords), "seconds": round(elapsed, 3), "chunks_per_s": round(len(coords) / elapsed, 1),
                    "queue_to_ready_ms": summary(svc.latency_ms), "in_worker_ms": summary(svc.generation_ms)}
    n_single = 40 if quick else 150
    lat = []
    singles = [ChunkCoord(200 + i, -50) for i in range(n_single)]
    for c in singles:
        t = time.perf_counter()
        svc.request(c, 0.0)
        drain(svc, [c])
        lat.append((time.perf_counter() - t) * 1000)
    out["single_request_round_trip_ms"] = summary(lat)
    ring = [ChunkCoord(x, y) for x in range(-300, -291) for y in range(-300, -291)]
    t = time.perf_counter()
    for c in ring:
        svc.request(c, 0.0)
    ring_s = drain(svc, ring)
    out["ring_burst_81"] = {"seconds": round(ring_s, 3), "per_chunk_ms": round(ring_s / 81 * 1000, 2)}
    out["stats"] = svc.stats()
    svc.close()
    return out


# -------------------------------------------------------------------------------------------------------------------- walk
class Walk:
    """Real-clock walk through the streaming stack. `compress` makes the world move that many times faster per real second."""

    TICK = 0.05

    def __init__(self, speed, distance, workers, compress, turn=False, lru=512):
        self.speed, self.distance, self.compress, self.turn = speed, distance, compress, turn
        self.svc = ChunkService(SEED, VILLAGE, workers=workers, lru_capacity=lru)
        self.cfg = RingConfig()
        self.integrated: set = set()
        self.first_wanted: dict = {}
        self.ready_at: dict = {}
        self.sim_at: dict = {}
        self.integrated_at: dict = {}

    def run(self):
        svc, cfg = self.svc, self.cfg
        svc.warm()
        x, y = 200.0, 150.0
        vx = self.speed
        start = time.perf_counter()
        # cold start: the simulation ring around the spawn point must exist before play begins (this is the loading screen, not a barrier)
        plan = plan_stream([Actor(x, y, vx, 0.0)], cfg=cfg)
        svc.set_wanted({c: p for c, p in plan.priority.items()})
        cold_deadline = time.perf_counter() + 60
        while any(svc.peek(c) is None for c in plan.simulate) and time.perf_counter() < cold_deadline:
            svc.pump()
            time.sleep(0.0005)
        cold_start_s = time.perf_counter() - start
        self.integrated = set(plan.simulate)
        t0 = time.perf_counter()
        ticks = 0
        barrier = 0
        moved = 0.0
        tick_ms, plan_ms, pump_ms = [], [], []
        integrate_per_tick = collections.Counter()
        last_sim: set = set(plan.simulate)
        total_ticks_limit = int(self.distance / (self.speed * self.TICK)) * (2 if self.turn else 1) * 3 + 2000
        while moved < self.distance * (2 if self.turn else 1) and ticks < total_ticks_limit:
            tick_start = time.perf_counter()
            vt = (tick_start - t0) * self.compress                      # virtual seconds
            direction = 1.0 if (not self.turn or moved < self.distance) else -1.0
            vx = direction * self.speed
            step = vx * self.TICK
            nx = x + step
            nxt_chunk = chunk_of(nx, y, cfg)
            if nxt_chunk not in self.integrated:
                barrier += 1                                           # the actor is held at the edge of the loaded world
            else:
                x = nx
                moved += abs(step)
            p0 = time.perf_counter()
            cached = [ChunkCoord(k[4], k[5]) for k in svc.cache.keys()]
            plan = plan_stream([Actor(x, y, vx, 0.0)], loaded=self.integrated, cached=cached, in_flight=list(svc._in_flight), cfg=cfg)
            svc.apply_plan(plan)
            plan_ms.append((time.perf_counter() - p0) * 1000)
            for c in plan.wanted:
                self.first_wanted.setdefault(c, vt)
            for c in plan.simulate - last_sim:
                self.sim_at.setdefault(c, vt)
            last_sim = set(plan.simulate)
            q0 = time.perf_counter()
            for chunk in svc.pump():
                self.ready_at.setdefault(ChunkCoord(chunk.cx, chunk.cy), (time.perf_counter() - t0) * self.compress)
            pump_ms.append((time.perf_counter() - q0) * 1000)
            took = 0                                                    # integration: at most ONE chunk per tick, spread across ticks
            for c in plan.integrate:
                if svc.peek(c) is not None:
                    self.integrated.add(c)
                    self.integrated_at.setdefault(c, vt)
                    took += 1
                    break
            integrate_per_tick[took] += 1
            for c in plan.unload:
                self.integrated.discard(c)
            ticks += 1
            used = time.perf_counter() - tick_start
            tick_ms.append(used * 1000)
            delay = self.TICK / self.compress - used
            if delay > 0:
                time.sleep(delay)
        wall = time.perf_counter() - t0
        gen_lat = list(svc.latency_ms)
        lead_req_to_sim = [self.sim_at[c] - self.first_wanted[c] for c in self.sim_at if c in self.first_wanted and c in self.ready_at]
        slack = [self.sim_at[c] - self.ready_at[c] for c in self.sim_at if c in self.ready_at]
        int_slack = [self.integrated_at[c] - self.ready_at[c] for c in self.integrated_at if c in self.ready_at]
        stats = svc.stats()
        svc.close()
        return {"speed_u_per_s": self.speed, "distance_units": self.distance * (2 if self.turn else 1), "compress": self.compress, "turn_back": self.turn,
                "ticks": ticks, "wall_s": round(wall, 2), "virtual_s": round(wall * self.compress, 1), "cold_start_5x5_s": round(cold_start_s, 3),
                "void_barrier_hits": barrier, "chunks_generated": stats["counters"].get("completed", 0), "chunks_integrated": len(self.integrated_at),
                "request_to_sim_ring_lead_s": summary(lead_req_to_sim, 2), "ready_to_sim_ring_slack_s": summary(slack, 2),
                "ready_to_integrated_s": summary(int_slack, 2),
                "generation_latency_ms_queue_plus_gen": summary(gen_lat), "in_worker_ms": summary(svc.generation_ms) if svc.generation_ms else {"n": 0},
                "main_thread_ms_per_tick": summary(tick_ms), "plan_stream_and_apply_ms": summary(plan_ms), "pump_ms": summary(pump_ms),
                "integrations_per_tick": dict(integrate_per_tick), "cache": stats["cache"], "cancelled": stats["counters"].get("cancelled_queued", 0)
                + stats["counters"].get("cancelled_in_flight", 0)}


def bench_walk(quick, workers, compress, which):
    out = {}
    scale = 0.2 if quick else 1.0
    plans = {"walk": ("walk_5000u_at_20ups", dict(speed=20.0, distance=5000 * scale, turn=False)),
             "run": ("run_5000u_at_40ups", dict(speed=40.0, distance=5000 * scale, turn=False)),
             "there": ("walk_there_and_back_2x2500u", dict(speed=20.0, distance=2500 * scale, turn=True))}
    for short, (name, kw) in plans.items():
        if which and short not in which:
            continue
        out[name] = Walk(workers=workers, compress=compress, **kw).run()
        print(f"  {name}: barrier hits {out[name]['void_barrier_hits']}, slack min {out[name]['ready_to_sim_ring_slack_s'].get('min')} s", flush=True)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sections", default="gen,payload,lru,pool,walk")
    parser.add_argument("--quick", action="store_true", help="small samples and 1/5 of the walking distance (smoke test; numbers are not the published ones)")
    parser.add_argument("--workers", type=int, default=2, help="worker processes for pool and walk (default 2: the game keeps most cores for the tick)")
    parser.add_argument("--compress", type=float, default=1.0, help="walk: world moves this many times faster than real time (1 = honest real time)")
    parser.add_argument("--walks", default="", help="comma list: walk, run, there (default all)")
    parser.add_argument("--json", default=str(ROOT / ".runtime" / "bench_chunks.json"))
    args = parser.parse_args(argv)
    sections = [s for s in args.sections.split(",") if s]
    result = {"machine": {"platform": platform.platform(), "python": sys.version.split()[0], "numpy": np.__version__, "cpu_count": os.cpu_count()},
              "generator_version": gen.GENERATOR_VERSION, "seed": SEED, "quick": args.quick, "workers": args.workers}
    if "gen" in sections:
        print("gen ...", flush=True)
        result["gen"] = bench_gen(args.quick)
    if "payload" in sections:
        print("payload ...", flush=True)
        result["payload"] = bench_payload(args.quick)
    if "lru" in sections:
        print("lru ...", flush=True)
        result["lru"] = bench_lru(args.quick)
    if "pool" in sections:
        print("pool ...", flush=True)
        result["pool"] = bench_pool(args.quick, args.workers)
    if "walk" in sections:
        print("walk ...", flush=True)
        result["walk"] = bench_walk(args.quick, args.workers, args.compress, [w for w in args.walks.split(",") if w])
    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
