"""Per-tick spike and GC diagnostic for the seeded village (1008 R2-H1).

usage: .venv/Scripts/python.exe tools/spike_probe.py TICKS BG GC [--cprofile40]
  BG = 1: background resident writes + writer pool as the server does; 0: synchronous writes inside the tick (what model_server/gate_a.py did)
  GC = none | freeze | thr   (freeze: gc.freeze() after boot; thr: gc.set_threshold(50000, 20, 100))
Prints one JSON line: all-ticks mean/p50/p95/p99/max, the tick%40==1 steps vs the others, and GC pauses per generation.
--cprofile40 also profiles only the steps that end on tick%40==1 and prints the top cumulative entries.
"""
import asyncio, cProfile, gc, io, json, pstats, sys, time, os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))
TICKS, BG, GCMODE = int(sys.argv[1]), sys.argv[2] == "1", sys.argv[3]
PROF40 = "--cprofile40" in sys.argv
from harness.headless import boot_engine, configure_environment

def pct(v, p):
    v = sorted(v); return v[min(len(v) - 1, int(round((len(v) - 1) * p / 100)))]

async def main():
    configure_environment()
    backend, engine = await boot_engine(1008)
    if GCMODE == "freeze":
        gc.collect(); gc.freeze()
    elif GCMODE == "thr":
        gc.set_threshold(50000, 20, 100)
    pauses = []
    st = {}
    def probe(phase, info):
        if phase == "start": st["t"] = time.perf_counter(); st["gen"] = info["generation"]
        else: pauses.append((info["generation"], (time.perf_counter() - st["t"]) * 1000.0, engine.tick))
    gc.callbacks.append(probe)
    pool = None; futures = []
    if BG:
        engine.resident_store.background_writes = True
        pool = ThreadPoolExecutor(max_workers=1)
        from runtime.resident_store import write_resident_batch
    ms, ticks = [], []
    pr = cProfile.Profile() if PROF40 else None
    for _ in range(TICKS):
        t = engine.tick
        use = pr is not None and t % 40 == 0   # step() runs with engine.tick == t and increments; the slow one is reported as tick%40==1 after the step
        if use: pr.enable()
        t0 = time.perf_counter(); engine.step(); d = (time.perf_counter() - t0) * 1000.0
        if use: pr.disable()
        ms.append(d); ticks.append(engine.tick)
        if BG and engine.tick % 20 == 10:
            for f in [f for f in futures if f.done()]:
                futures.remove(f); engine.resident_store.acknowledge_writes(f.result())
            jobs = engine.resident_store.capture_dirty(engine.tick, force=True, limit=16)
            if jobs: futures.append(pool.submit(write_resident_batch, jobs))
    if pool: pool.shutdown(wait=True)
    spike = [m for m, t in zip(ms, ticks) if t % 40 == 1]; rest = [m for m, t in zip(ms, ticks) if t % 40 != 1]
    out = {"ticks": TICKS, "bg": BG, "gc": GCMODE,
           "all": {k: round(f, 2) for k, f in (("mean", sum(ms) / len(ms)), ("p50", pct(ms, 50)), ("p95", pct(ms, 95)), ("p99", pct(ms, 99)), ("max", max(ms)))},
           "tick%40==1": {"n": len(spike), "mean": round(sum(spike) / len(spike), 2), "p50": round(pct(spike, 50), 2), "max": round(max(spike), 2)},
           "others": {"mean": round(sum(rest) / len(rest), 2), "p99": round(pct(rest, 99), 2), "max": round(max(rest), 2)},
           "gc": {g: {"n": sum(1 for p in pauses if p[0] == g), "total_ms": round(sum(p[1] for p in pauses if p[0] == g), 1), "max_ms": round(max([p[1] for p in pauses if p[0] == g] or [0]), 1)} for g in (0, 1, 2)}}
    print(json.dumps(out))
    if pr:
        s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(28)
        print("\n".join(l[:170] for l in s.getvalue().splitlines()[:70]))
asyncio.run(main())
