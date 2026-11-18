"""Why is the first minute after a backend restart + Continue slow? In-process, no sockets, two cold Python processes.

    .venv/Scripts/python.exe tools/restart_probe.py make    --root .runtime/restart-probe [--ticks 3000]
    .venv/Scripts/python.exe tools/restart_probe.py restore --root .runtime/restart-probe [--seconds 75] [--profile]

``make`` (process A): the four-map roster world, ``--ticks`` headless ticks, one save in the data root. ``restore`` (process B, a fresh
interpreter like a restarted server): runs the real app lifespan (tick loop, autosave, resident writer) and an ASGI client in one event
loop, measures how long ``POST /session/continue`` takes and how long concurrent ``GET /status`` calls and a 5 ms heartbeat are
blocked meanwhile, then times every tick of the first ``--seconds`` of real time (a 20 Hz client load: /frame 20 Hz, /status 1 Hz).
``--profile`` repeats the step timing under cProfile and prints what the heaviest ticks spent their time in.
"""
import argparse
import asyncio
import cProfile
import io
import json
import os
import pstats
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("make", "restore"))
parser.add_argument("--root", default=".runtime/restart-probe")
parser.add_argument("--ticks", type=int, default=3000)
parser.add_argument("--seconds", type=float, default=75.0)
parser.add_argument("--profile", action="store_true")
parser.add_argument("--routes", action="store_true", help="after Continue time the first and the repeated call of every route the client uses")
parser.add_argument("--out", default="")
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
DATA = (ROOT / args.root).resolve()
DATA.mkdir(parents=True, exist_ok=True)
os.environ.update(EDEN_PROFILE="gameplay", EDEN_DATA_ROOT=str(DATA), EDEN_MAP="starter_village", EDEN_PORT="8013",
                  EDEN_MAP_FILES=os.pathsep.join(str(ROOT / "world_data" / "maps2d" / f"{n}.json") for n in
                                                 ("starter_village", "smith_interior", "village_lodge_interior", "west_cottage_interior")),
                  EDEN_MAP_ORIGINS=json.dumps({"smith_interior": [620, 0], "village_lodge_interior": [620, 400], "west_cottage_interior": [960, 160]}))
sys.path.insert(0, str(ROOT / "at_the_beginning"))
T0 = time.perf_counter()
import httpx  # noqa: E402
import map_test as backend  # noqa: E402  (the import itself is the cold-start cost of a restarted server)
IMPORT_S = time.perf_counter() - T0


def pct(values, p):
    ordered = sorted(values)
    return round(ordered[max(0, int(len(ordered) * p / 100 + 0.999999) - 1)], 2) if ordered else None


async def make():
    import random
    import numpy as np
    import torch
    random.seed(905); np.random.seed(905); torch.manual_seed(905)
    sessions = backend.game_sessions
    await sessions.new("restart-probe")
    started = time.perf_counter()
    for _ in range(args.ticks):
        backend.engine.step()
    print(f"made: {args.ticks} ticks in {time.perf_counter() - started:.1f} s, residents {backend.engine.pop_count}, tick {backend.engine.tick}")
    await sessions.save()
    print("saved:", sessions.active_id)


async def restore():
    engine = backend.engine
    step_log = []  # (tick, ms, wall seconds since the world went live)
    profiles = []
    original_step = engine.step
    live = {"t0": None}

    def timed_step():
        if args.profile:
            profile = cProfile.Profile()
            profile.enable()
        began = time.perf_counter()
        original_step()
        ms = (time.perf_counter() - began) * 1000.0
        if args.profile:
            profile.disable()
            profiles.append((ms, engine.tick, profile))
            profiles.sort(key=lambda item: -item[0])
            del profiles[6:]
        if live["t0"] is not None:
            step_log.append((engine.tick, ms, time.perf_counter() - live["t0"]))

    engine.step = timed_step
    phases = {}

    def timed(owner, name):
        original = getattr(owner, name)

        async def awaited(*a, **k):
            began = time.perf_counter()
            try:
                return await original(*a, **k)
            finally:
                phases[name] = round((time.perf_counter() - began) * 1000.0, 1)

        def plain(*a, **k):
            began = time.perf_counter()
            try:
                return original(*a, **k)
            finally:
                phases[name] = round((time.perf_counter() - began) * 1000.0, 1)
        setattr(owner, name, awaited if asyncio.iscoroutinefunction(original) else plain)

    from persistence import codec, world_snapshot, sessions as sessions_module
    timed(codec, "loads")
    timed(world_snapshot, "validate")
    timed(world_snapshot, "restore")
    timed(engine, "reset_world")
    timed(backend.game_sessions.store, "read")

    lag = []
    status_ms = []
    frame_ms = []
    phase = {"name": "boot", "continuing": False}

    async with backend.app.router.lifespan_context(backend.app):
        transport = httpx.ASGITransport(app=backend.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1", timeout=60) as client:
            boot = (await client.get("/bootstrap")).json()
            headers = {"X-Eden-Session": boot["session_capability"]}
            saves = (await client.get("/session")).json()["saves"]
            save_id = saves[0]["save_id"]

            async def heartbeat():
                while True:
                    began = time.perf_counter()
                    await asyncio.sleep(0.005)
                    late = (time.perf_counter() - began - 0.005) * 1000.0
                    if late > 20.0:
                        lag.append((round(late, 1), phase["name"], round(time.perf_counter() - T0, 2)))

            async def poller():
                tick_count = 0
                while True:
                    began = time.perf_counter()
                    await client.get("/frame")
                    frame_ms.append(((time.perf_counter() - began) * 1000.0, phase["name"]))
                    tick_count += 1
                    if tick_count % 20 == 0:
                        began = time.perf_counter()
                        await client.get("/status")
                        status_ms.append(((time.perf_counter() - began) * 1000.0, phase["name"]))
                    await asyncio.sleep(0.05)

            tight = {"waits": []}

            async def tight_status():  # a client that asks for /status as fast as it can: how long does one answer wait?
                while True:
                    began = time.perf_counter()
                    await client.get("/status")
                    tight["waits"].append((time.perf_counter() - began) * 1000.0)

            beat, poll = asyncio.create_task(heartbeat()), asyncio.create_task(poller())
            await asyncio.sleep(1.0)
            phase["name"] = "continue"
            hammer = asyncio.create_task(tight_status())
            before = time.perf_counter()
            response = await client.post("/session/continue", json={"save_id": save_id}, headers=headers)
            continue_ms = (time.perf_counter() - before) * 1000.0
            hammer.cancel()
            print(f"/status during Continue: {len(tight['waits'])} calls, longest wait {max(tight['waits'], default=0):.1f} ms, median {pct(tight['waits'], 50)} ms")
            phase["name"] = "live"
            live["t0"] = time.perf_counter()
            print(f"POST /session/continue -> {response.status_code} in {continue_ms:.0f} ms (world tick {engine.tick})")
            if args.routes:
                await asyncio.sleep(3.0)
                agents = (await client.get("/frame")).json()["agents"]
                smith = next(a["id"] for a in agents if a.get("roster_key") == "smith")
                mara = next(a["id"] for a in agents if a.get("roster_key") == "builder")
                maps = (await client.get("/bootstrap")).json()["maps"]
                calls = [("GET", "/bootstrap", None), ("GET", "/session", None), ("GET", "/status", None), ("GET", "/frame", None),
                         ("GET", "/control/state", None), ("GET", "/commission/state?controller_id=probe", None), ("GET", f"/god/inspect/{smith}", None),
                         ("GET", "/map_delta", None), ("GET", f"/inventory/owner/human/{mara}", None), ("GET", f"/resident/{mara}", None)]
                calls += [("GET", m["url"], None) for m in maps]
                calls += [("POST", "/control/claim", {"controller_id": "probe", "target_kind": "human", "target_id": mara}),
                          ("GET", "/commission/state?controller_id=probe", None), ("POST", "/control/release", {"controller_id": "probe"})]
                route_ms = {}
                for method, path, body in calls:
                    times = []
                    for _ in range(3):
                        began = time.perf_counter()
                        reply = await (client.get(path) if method == "GET" else client.post(path, json=body, headers=headers))
                        times.append(round((time.perf_counter() - began) * 1000.0, 1))
                    route_ms[f"{method} {path.split('?')[0]}"] = {"status": reply.status_code, "ms_first_second_third": times, "bytes": len(reply.content)}
                print("ROUTES", json.dumps(route_ms, indent=1))
            await asyncio.sleep(args.seconds)
            status = (await client.get("/status")).json()
            beat.cancel(); poll.cancel()

    during = [m for m, name in status_ms if name == "continue"]
    result = {
        "cold_import_s": round(IMPORT_S, 2), "continue_ms": round(continue_ms), "continue_phases_ms": phases,
        "status_during_continue_ms": [round(m, 1) for m in during], "frame_during_continue_ms": [round(m, 1) for m, n in frame_ms if n == "continue"],
        "loop_lag_over_20ms": lag[:40], "loop_lag_max_ms": max([x[0] for x in lag], default=0),
        "ticks_timed": len(step_log),
        "work_ms_first_1200": {"p50": pct([m for _, m, _ in step_log[:1200]], 50), "p95": pct([m for _, m, _ in step_log[:1200]], 95),
                                "p99": pct([m for _, m, _ in step_log[:1200]], 99), "max": pct([m for _, m, _ in step_log[:1200]], 100)},
        "work_ms_after_1200": {"p50": pct([m for _, m, _ in step_log[1200:]], 50), "p95": pct([m for _, m, _ in step_log[1200:]], 95),
                                "p99": pct([m for _, m, _ in step_log[1200:]], 99), "max": pct([m for _, m, _ in step_log[1200:]], 100)},
        "ticks_over_50ms": [(t, round(m, 1), round(w, 2)) for t, m, w in step_log if m > 50.0][:40],
        "ticks_over_35ms_count_by_10s": {str(int(w // 10) * 10): sum(1 for _, m, ww in step_log if m > 35.0 and int(ww // 10) == int(w // 10)) for _, _, w in step_log},
        "server_timing": status.get("timing"), "persistence": status.get("persistence"),
    }
    print(json.dumps(result, indent=1))
    if args.profile:
        for ms, tick, profile in profiles:
            buffer = io.StringIO()
            pstats.Stats(profile, stream=buffer).sort_stats("cumulative").print_stats(14)
            print(f"\n=== heaviest step {ms:.0f} ms (profiled) tick {tick}\n" + "\n".join(buffer.getvalue().splitlines()[4:24]))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")


asyncio.run(make() if args.mode == "make" else restore())
