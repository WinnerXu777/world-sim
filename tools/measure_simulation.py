"""Short real-simulation timing run; always uses a fresh isolated data directory."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def measure(seconds: float, report_path: Path) -> None:
    run_root = ROOT / ".tmp" / "measurements" / uuid.uuid4().hex
    run_root.mkdir(parents=True)
    os.environ["EDEN_PROFILE"] = "gameplay"
    os.environ["EDEN_DATA_ROOT"] = str(run_root)
    os.environ["EDEN_MAP"] = "playable_village"
    os.environ["EDEN_EMBEDDINGS"] = "lexical"
    sys.path.insert(0, str(ROOT / "at_the_beginning"))
    import map_test as backend

    async with backend.lifespan(backend.app):
        await backend.game_sessions.new("Timing measurement")
        started = time.perf_counter()
        await asyncio.sleep(seconds)
        elapsed = time.perf_counter() - started
        timing = backend.engine.scheduler.status()
        report = {"python": platform.python_version(), "platform": platform.platform(),
                  "device": backend.engine.state.device, "elapsed_seconds": elapsed,
                  "observed_ticks_per_second": backend.engine.tick / elapsed,
                  "tick": backend.engine.tick, "residents": backend.engine.pop_count,
                  "entities": backend.engine.entity_count, "timing": timing,
                  "launch": backend.LAUNCH_CONFIG.status(),
                  "scope": "Small full-simulation backend only; no rendering, input load, or LLM inference"}
    report["shutdown_task_done"] = backend.app.state.simulation_task.done()
    report["running_after_shutdown"] = backend.engine.running
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--report", type=Path, default=ROOT / ".tmp" / "implementation_0905" / "timing.json")
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600:
        parser.error("--seconds must be in (0, 3600]")
    asyncio.run(measure(args.seconds, args.report))
