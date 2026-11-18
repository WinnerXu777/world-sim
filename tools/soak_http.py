"""Real-time HTTP soak against a running backend: a client-like load for N seconds, then /status timing.

Start the backend on a fresh data root with both real maps (see tools/live_smoke_smith.py), then:
    .venv/Scripts/python.exe tools/soak_http.py [--seconds 300]
Load: GET /frame at 20 Hz, POST /control/input at 5 Hz (a possessed villager walks a square in the village),
GET /commission/state and /status once a second. Client latencies and the server's scheduler timing are printed as JSON.
"""
import argparse
import json
import math
import os
import time

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=float, default=300.0)
parser.add_argument("--out", default="")
args = parser.parse_args()
BASE = f"http://127.0.0.1:{os.environ.get('EDEN_SMOKE_PORT', '8013')}"
c = httpx.Client(base_url=BASE, timeout=10)


def pct(values, p):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)], 2) if ordered else None


def summary(values):
    return {"n": len(values), "p50": pct(values, 50), "p95": pct(values, 95), "p99": pct(values, 99), "max": round(max(values), 2) if values else None}


H = {"X-Eden-Session": c.get("/bootstrap").json()["session_capability"]}
c.post("/session/new", json={"name": "http-soak"}, headers=H)
frame = c.get("/frame").json()
me = next(a for a in frame["agents"] if a["name"] == "Iven")
claim = c.post("/control/claim", json={"controller_id": "soak", "target_kind": "human", "target_id": me["id"]}, headers=H).json()
env = {k: claim[k] for k in ("protocol_version", "world_epoch", "possession_epoch", "target_kind", "target_id")}
status0 = c.get("/status").json()
frame_ms, input_ms, state_ms, status_ms, errors = [], [], [], [], []
squares = [(1, 0), (0, 1), (-1, 0), (0, -1)]
seq, start = 0, time.perf_counter()
next_tick = start
iteration = 0
while time.perf_counter() - start < args.seconds:
    now = time.perf_counter()
    if now < next_tick:
        time.sleep(next_tick - now)
    next_tick += 0.05
    iteration += 1
    try:
        t = time.perf_counter()
        c.get("/frame").raise_for_status()
        frame_ms.append((time.perf_counter() - t) * 1000)
        if iteration % 4 == 0:
            seq += 1
            vector = squares[int((time.perf_counter() - start) // 4) % 4]
            t = time.perf_counter()
            response = c.post("/control/input", json={**env, "controller_id": "soak", "seq": seq, "move": {"x": vector[0], "y": vector[1]},
                                                     "buttons": {"sprint": False}}, headers=H)
            input_ms.append((time.perf_counter() - t) * 1000)
            if response.status_code != 200:
                errors.append(f"input {response.status_code} {response.text[:80]}")
        if iteration % 20 == 0:
            t = time.perf_counter()
            c.get("/commission/state", params={"controller_id": "soak"})
            state_ms.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            c.get("/status")
            status_ms.append((time.perf_counter() - t) * 1000)
    except Exception as exc:  # noqa: BLE001 - record and keep loading
        errors.append(f"{type(exc).__name__}: {exc}"[:120])
status1 = c.get("/status").json()
print(json.dumps({"seconds": args.seconds, "client_ms": {"frame": summary(frame_ms), "input": summary(input_ms), "commission_state": summary(state_ms),
                                                          "status": summary(status_ms)},
                  "errors": errors[:10], "error_count": len(errors), "server_timing_start": status0["timing"], "server_timing_end": status1["timing"],
                  "tick_start": status0["tick"], "tick_end": status1["tick"], "pop": status1["pop"],
                  "persistence": status1.get("persistence"), "session": {k: status1["session"].get(k) for k in ("last_saved_tick", "error")}},
                 indent=1, default=str))
if args.out:
    open(args.out, "w", encoding="utf-8").write(json.dumps({"timing": status1["timing"]}))
