"""Cost of the affordance engine on the real booted Stage 1 engine. Run in a fresh process, with the machine otherwise idle:

    .venv/Scripts/python.exe at_the_beginning/systems/affordance/bench.py [--ticks 200] [--runs 100] [--json .runtime/bench_affordance.json]

Reports p50/p95/p99/max in milliseconds per call for: ``observe`` (one resident), ``options`` (every verb, one resident), ``mask``
(the 8 residents), reachability with a cold and a warm cache, and the worst reachability cases (a detour search, a search that exhausts
its budget). Numbers are what this machine measured, not targets.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "at_the_beginning"))


def percentiles(samples):
    ordered = sorted(samples)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]  # noqa: E731
    return {"n": len(ordered), "p50": round(pick(0.50), 3), "p95": round(pick(0.95), 3), "p99": round(pick(0.99), 3),
            "max": round(ordered[-1], 3), "mean": round(statistics.fmean(ordered), 3)}


def timed(fn, runs):
    out = []
    for _ in range(runs):
        began = time.perf_counter()
        fn()
        out.append((time.perf_counter() - began) * 1000.0)
    return percentiles(out)


async def main(args):
    from harness import headless
    headless.configure_environment()
    backend, engine = await headless.boot_engine(1008)
    for _ in range(args.ticks):
        engine.step()
    import genesis_config as cfg
    from harness.adapter import EngineWorld
    from systems.affordance import AffordanceEngine, EngineServices, Reach
    world = EngineWorld(engine, seed=1008)
    services = EngineServices(engine)
    aff = AffordanceEngine(world, services)
    residents = [u for u in engine._human_uid_by_slot if u]
    result = {"tick": engine.tick, "residents": len(residents), "machine": {"python": sys.version.split()[0]}}
    # make the resident population varied: some hungry, thirsty, one far away
    for i, h in enumerate(residents):
        engine.state.h_tensor[engine._human_slot_for_id(h), cfg.HUNGER] = 20.0 + 10.0 * i
        engine.state.h_tensor[engine._human_slot_for_id(h), cfg.THIRST] = 15.0 * i
    result["observe_one"] = timed(lambda: aff.observation(residents[1]), args.runs)
    result["options_one_cold_reach"] = timed(lambda: (aff.reach.clear(), aff.options(residents[1])), args.runs)
    aff.options(residents[1])
    result["options_one_warm_reach"] = timed(lambda: aff.options(residents[1]), args.runs)
    result["options_one_include_illegal"] = timed(lambda: aff.options(residents[1], include_illegal=True), args.runs)
    # step 5: the mask with exact path lengths (before) against connected components (after)
    result["mask_8_cold_reach_exact"] = timed(lambda: (aff.reach.clear(), aff.mask(residents, exact=True)), args.runs)
    aff.mask(residents, exact=True)
    result["mask_8_warm_reach_exact"] = timed(lambda: aff.mask(residents, exact=True), args.runs)
    began = time.perf_counter()
    aff.reach.components_for(aff.services.contract())
    result["components_first_build_ms"] = round((time.perf_counter() - began) * 1000.0, 2)
    result["components_count"] = aff.reach.components_for(aff.services.contract()).count
    result["mask_8_cold_reach_components"] = timed(lambda: (aff.reach.clear(), aff.mask(residents)), args.runs)
    aff.mask(residents)
    result["mask_8_warm_reach_components"] = timed(lambda: aff.mask(residents), args.runs)
    result["mask_equal_exact_vs_components"] = bool((aff.mask(residents, exact=True) == aff.mask(residents)).all())
    result["commission_options"] = timed(lambda: aff.commission_options(residents[0], residents[3], "sword"), args.runs)
    result["reach_stats_after"] = dict(aff.reach.stats)

    # worst reachability: a detour search and an exhausted budget on the real map
    from systems.affordance.testing import WalledServices, box
    builder, gatherer = residents[1], residents[2]
    engine.state.h_tensor[engine._human_slot_for_id(builder), cfg.X] = 150.0
    engine.state.h_tensor[engine._human_slot_for_id(builder), cfg.Y] = 160.0
    engine.state.h_tensor[engine._human_slot_for_id(gatherer), cfg.X] = 220.0
    engine.state.h_tensor[engine._human_slot_for_id(gatherer), cfg.Y] = 160.0
    walled = WalledServices(engine, [box("w", 183.0, 120.0, 187.0, 200.0)])
    reach = Reach(walled)
    result["reach_detour_search_cold"] = timed(lambda: (reach.clear(), reach.check((150.0, 160.0), (220.0, 160.0))), max(5, args.runs // 5))
    reach.components_for(walled.contract())
    result["reach_detour_components_cold"] = timed(lambda: (reach.clear(), reach.check((150.0, 160.0), (220.0, 160.0), need_length=False)), max(5, args.runs // 5))
    result["reach_detour_components_mode"] = reach.check((150.0, 160.0), (220.0, 160.0), need_length=False).mode
    closed = WalledServices(engine, [box("w", 183.0, 0.0, 187.0, 480.0)])   # splits the village: the search floods one half
    reach2 = Reach(closed)
    result["reach_exhausted_budget_cold"] = timed(lambda: (reach2.clear(), reach2.check((150.0, 160.0), (220.0, 160.0))), max(3, args.runs // 10))
    result["reach_exhausted_verdict"] = {"ok": reach2.check((150.0, 160.0), (220.0, 160.0)).ok, "mode": reach2.check((150.0, 160.0), (220.0, 160.0)).mode}
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    for key, value in result.items():
        if isinstance(value, dict) and "p50" in value:
            print(f"{key:34s} p50 {value['p50']:8.3f}  p95 {value['p95']:8.3f}  p99 {value['p99']:8.3f}  max {value['max']:8.3f} ms  (n={value['n']})")
    print("components: first build", result["components_first_build_ms"], "ms,", result["components_count"], "components; mask equal:", result["mask_equal_exact_vs_components"])
    print("reach stats", result["reach_stats_after"], "| exhausted:", result["reach_exhausted_verdict"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=200)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--json", default=str(ROOT / ".runtime" / "bench_affordance.json"))
    asyncio.run(main(parser.parse_args()))
