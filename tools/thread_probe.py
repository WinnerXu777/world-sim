"""Does torch's intra-op thread pool make tick times jittery when the machine is busy?

    .venv/Scripts/python.exe tools/thread_probe.py --root .runtime/restart-probe-gate --threads 10 --burners 12 --ticks 1200

Restores the saved world in ``--root`` (made by tools/restart_probe.py or copied from a Gate H data root; a restore writes into it, so
pass a copy), sets ``torch.set_num_threads(--threads)``, starts ``--burners`` busy-loop processes (a stand-in for Godot, ffmpeg and
friends), then steps ``--ticks`` ticks directly and prints the per-tick percentiles and the number of ticks over the 50 ms budget.
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", required=True)
parser.add_argument("--threads", type=int, default=0, help="0 = leave torch's default")
parser.add_argument("--burners", type=int, default=0)
parser.add_argument("--ticks", type=int, default=1200)
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
os.environ.update(EDEN_PROFILE="gameplay", EDEN_DATA_ROOT=str((ROOT / args.root).resolve()), EDEN_MAP="starter_village", EDEN_PORT="8013",
                  EDEN_MAP_FILES=os.pathsep.join(str(ROOT / "world_data" / "maps2d" / f"{n}.json") for n in
                                                 ("starter_village", "smith_interior", "village_lodge_interior", "west_cottage_interior")),
                  EDEN_MAP_ORIGINS=json.dumps({"smith_interior": [620, 0], "village_lodge_interior": [620, 400], "west_cottage_interior": [960, 160]}))
sys.path.insert(0, str(ROOT / "at_the_beginning"))
import torch  # noqa: E402
import map_test as backend  # noqa: E402

if args.threads:
    torch.set_num_threads(args.threads)


def pct(values, p):
    ordered = sorted(values)
    return round(ordered[max(0, int(len(ordered) * p / 100 + 0.999999) - 1)], 1)


async def main():
    sessions = backend.game_sessions
    save_id = sessions.store.list_saves()[0]["save_id"] if hasattr(sessions.store, "list_saves") else None
    await sessions.continue_world(save_id)
    for _ in range(40):  # warm up (first-use costs are not what this probe is about)
        backend.engine.step()
    burners = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(args.burners)]
    try:
        time.sleep(1.0)
        durations = []
        for _ in range(args.ticks):
            began = time.perf_counter()
            backend.engine.step()
            durations.append((time.perf_counter() - began) * 1000.0)
            time.sleep(max(0.0, 0.020 - durations[-1] / 1000.0))  # leave idle gaps like the real 20 Hz loop (50 ms period)
    finally:
        for burner in burners:
            burner.kill()
    print(json.dumps({"threads": torch.get_num_threads(), "burners": args.burners, "ticks": args.ticks, "p50": pct(durations, 50), "p95": pct(durations, 95),
                      "p99": pct(durations, 99), "max": round(max(durations), 1), "over_50ms": sum(1 for d in durations if d > 50.0),
                      "over_35ms": sum(1 for d in durations if d > 35.0)}))


asyncio.run(main())
