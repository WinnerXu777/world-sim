"""Cost of the Tier 1 feature builder and the shadow report on a seeded headless engine. Fresh process, machine otherwise idle:

    .venv/Scripts/python.exe at_the_beginning/systems/affordance/bench_features.py [--ticks 600] [--runs 200] [--json .runtime/bench_features.json]

Prints and writes: build_features cost per call for 8 residents (and a synthetic larger batch of repeated residents, for scaling only),
and the ``shadow_compare`` report of an unperturbed run plus a seeded perturbed run (stress states). Numbers are what this machine measured.
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


async def main(args):
    from harness import headless
    headless.configure_environment()
    backend, engine = await headless.boot_engine(1008)
    for _ in range(200):
        engine.step()
    from harness.adapter import EngineWorld
    from systems.affordance import EngineServices
    from systems.decision import features as feat
    world, services = EngineWorld(engine, seed=1008), EngineServices(engine)
    residents = [u for u in engine._human_uid_by_slot if u]
    out = {"tick": engine.tick, "residents": len(residents)}
    for label, group in (("build_8", residents), ("build_8_repeated_x12", residents * 12)):
        samples = []
        for _ in range(args.runs):
            began = time.perf_counter()
            feat.build_features(world, services, group)
            samples.append((time.perf_counter() - began) * 1000.0)
        out[label] = percentiles(samples)
    out["shadow_unperturbed"] = feat.shadow_compare(engine, ticks=args.ticks, sample_every=40)
    out["shadow_perturbed_seed7"] = feat.shadow_compare(engine, ticks=0, sample_every=1, perturb_seed=7)
    perturbed = {}
    for seed in range(100, 100 + args.stress):
        report = feat.shadow_compare(engine, ticks=0, sample_every=1, perturb_seed=seed)
        for key, count in report["confusion"].items():
            perturbed[key] = perturbed.get(key, 0) + count
    out["stress_confusion_total"] = dict(sorted(perturbed.items()))
    out["stress_states"] = args.stress * len(residents)
    spoke = sum(c for c in perturbed.values())
    agreed = sum(c for k, c in perturbed.items() if k.split("->")[0] == k.split("->")[1])
    out["stress_agreement"] = round(agreed / spoke, 4) if spoke else None
    text = json.dumps(out, indent=2, default=str)
    print(text)
    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=int, default=600)
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--stress", type=int, default=50, help="number of seeded perturbed samples of all residents")
    parser.add_argument("--json", default=str(ROOT / ".runtime" / "bench_features.json"))
    asyncio.run(main(parser.parse_args()))
