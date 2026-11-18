"""Headless in-process soak: the real two-map roster world for a full playthrough with a scripted player.

    .venv/Scripts/python.exe tools/soak_headless.py [--ticks 36000] [--out .runtime/soak-result.json]

36000 ticks = 30 minutes of game time at 20 Hz. The scripted player claims Iven, walks to the smith's door, takes the
portal, commissions swords (two real orders use up the smith's iron), is refused, is released, the god gifts iron and
tops up coin, the world is paused and resumed, the player commissions again and collects, then plays idle while the
god heals and changes weather. Per-tick work time, needs, memory (working set), logs and movement drift are recorded.
Uses an isolated temporary data root; nothing under Data_Storage is touched.
"""
import argparse
import ctypes
import json
import logging
import math
import os
import statistics
import sys
import tempfile
import time
import uuid
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--ticks", type=int, default=36000)
parser.add_argument("--out", default=str(ROOT / ".runtime" / "soak-result.json"))
parser.add_argument("--sample-every", type=int, default=600)
parser.add_argument("--resident-writes", choices=("background", "inline"), default="background",
                    help="background (default) mirrors the gameplay server: resident files are captured between ticks and written "
                         "by a worker; inline writes them (with fsync) on the tick thread like the development profile")
args = parser.parse_args()

DATA_ROOT = Path(tempfile.mkdtemp(prefix="eden-soak-", dir=str(ROOT / ".runtime") if (ROOT / ".runtime").exists() else None))
os.environ.update(EDEN_PROFILE="gameplay", EDEN_DATA_ROOT=str(DATA_ROOT), EDEN_MAP="starter_village",
                  EDEN_MAP_FILES=os.pathsep.join(str(ROOT / "world_data" / "maps2d" / f"{name}.json") for name in
                                                 ("starter_village", "smith_interior", "village_lodge_interior", "west_cottage_interior")),
                  EDEN_MAP_ORIGINS=json.dumps({"smith_interior": [620, 0], "village_lodge_interior": [620, 400], "west_cottage_interior": [960, 160]}))
sys.path.insert(0, str(ROOT / "at_the_beginning"))
import asyncio  # noqa: E402

import genesis_config as cfg  # noqa: E402
import map_test as backend  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402
from systems.movement.spatial import is_standable_point, world_contract  # noqa: E402
from systems.roster.driver import runtime  # noqa: E402


class _Counter(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def rss_mb():
    try:
        counters = _Counter()
        counters.cb = ctypes.sizeof(_Counter)
        kernel, psapi = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counter), wintypes.DWORD]
        psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return round(counters.WorkingSetSize / 1048576, 1)
    except Exception:  # noqa: BLE001 - non-Windows: no figure
        return None


class ErrorCatcher(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(f"{record.name}: {record.getMessage()}"[:300])


def percentile(values, p):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)], 3) if ordered else None


class Bot:
    """Scripted player. One ``act`` per tick before ``engine.step()``; phases advance on observed results."""

    def __init__(self, engine):
        self.e = engine
        self.names = {}
        self.phase = "start"
        self.seq = 0
        self.claim = None
        self.pending = None
        self.timeline = []
        self.orders_done = 0
        self.wait_until = 0
        self.refused = None
        self.gift = None

    def log(self, text):
        self.timeline.append((self.e.tick, text))

    def resident(self, name):
        for uid in self.e._human_uid_by_slot:
            if uid and self.e.resident_store.get(uid)["profile"]["name"] == name:
                return uid, self.e._human_slot_for_id(uid)
        raise KeyError(name)

    def pos(self, name):
        _, slot = self.resident(name)
        return float(self.e.state.h_tensor[slot, cfg.X]), float(self.e.state.h_tensor[slot, cfg.Y])

    def envelope(self, god=False):
        base = {"protocol_version": 1, "world_epoch": self.e.world_epoch, "controller_id": "p", "command_id": str(uuid.uuid4())}
        if not god and self.claim:
            base["possession_epoch"] = self.claim["possession_epoch"]
        return base

    def submit(self, command, **body):
        payload = {**self.envelope(command.startswith("god_")), **body}
        received = self.e.command_inbox.submit(self.e, command, payload)
        self.pending = payload["command_id"] if received.get("status") == "received" else None
        if self.pending is None:
            self.log(f"{command} rejected at submit: {received.get('reason')}")
        return received

    def result(self):
        if self.pending is None:
            return {"status": "rejected", "reason": "not_submitted"}
        result = self.e.command_inbox.result(self.pending)
        return result if result and result.get("status") != "received" else None

    def move(self, goal, tolerance, sprint=True):
        iven_x, iven_y = self.pos("Iven")
        dx, dy = goal[0] - iven_x, goal[1] - iven_y
        dist = math.hypot(dx, dy)
        self.seq += 1
        vector = (0.0, 0.0) if dist <= tolerance else (dx / dist, dy / dist)
        payload = {k: self.claim[k] for k in ("protocol_version", "world_epoch", "possession_epoch", "target_kind", "target_id")}
        payload.update(seq=self.seq, move={"x": vector[0], "y": vector[1]}, buttons={"sprint": sprint})
        self.e.player_control.submit_input(self.e, "p", payload)
        return dist <= tolerance

    def idle(self):
        if self.claim:
            self.move(self.pos("Iven"), 1.0)

    def do_claim(self):
        uid, _ = self.resident("Iven")
        self.claim = self.e.player_control.claim_target(self.e, controller_id="p", target_kind="human", target_id=uid)
        self.seq = 0

    def do_release(self):
        self.e.player_control.release_target(self.e, controller_id="p")
        self.claim = None

    def smith_side(self):
        x, y = self.pos("Brann")
        return (x + 8.0, y + 4.0)

    def orders(self):
        return list(self.e.inventory_state.get("work_orders", {}).get("orders", {}).values())

    def act(self):
        e, phase = self.e, self.phase
        if phase == "start":
            self.do_claim()
            self.phase = "to_door"
            self.log("claimed Iven")
        elif phase == "to_door":
            if self.move((128.0, 110.0), 6.0):
                self.submit("portal", portal_id="village:portal_smith")
                self.phase = "portal"
        elif phase == "portal":
            self.idle()
            result = self.result()
            if result:
                self.log(f"portal: {result.get('status')} {result.get('reason') or result.get('to_map')}")
                self.phase = "to_smith"
        elif phase == "to_smith":
            if self.move(self.smith_side(), 4.0):
                self.phase = "request"
        elif phase in ("request", "request_again"):
            self.idle()
            self.submit("commission_request")
            self.phase = "await_request"
        elif phase == "await_request":
            self.idle()
            result = self.result()
            if result:
                self.log(f"request: {result.get('status')} {result.get('code') or result.get('reason')}")
                if result.get("code") == "accepted":
                    self.phase = "await_ready"
                elif result.get("code") == "refused_no_materials":
                    self.refused = e.tick
                    self.phase = "release_for_gift"
                else:
                    self.phase = "idle_forever"
        elif phase == "await_ready":
            self.idle()
            ready = [o for o in self.orders() if o["state"] == "ready"]
            if ready:
                self.order_id = ready[0]["order_id"]
                self.phase = "approach"
        elif phase == "approach":
            if self.move(self.smith_side(), 3.0):
                self.submit("commission_collect", order_id=self.order_id)
                self.phase = "await_collect"
        elif phase == "await_collect":
            self.idle()
            result = self.result()
            if result:
                self.log(f"collect: {result.get('status')} {result.get('state') or result.get('reason')}")
                self.orders_done += 1
                self.phase = "topup" if self.orders_done < 2 else "request_again"
        elif phase == "topup":
            self.do_release()
            self.submit("god_spawn_resource", resource="coin", quantity=100, target_kind="resident", target_id=self.resident("Iven")[0])
            self.phase = "topup_wait"
        elif phase == "topup_wait":
            if self.result():
                self.do_claim()
                self.phase = "request_again"
        elif phase == "release_for_gift":
            self.do_release()
            self.submit("god_spawn_resource", resource="iron_ingot", quantity=4, target_kind="resident", target_id=self.resident("Brann")[0])
            self.phase = "gift_wait"
        elif phase == "gift_wait":
            result = self.result()
            if result:
                self.gift = result
                self.log(f"gift: {result.get('status')} witnesses={result.get('witnesses')}")
                self.submit("god_time", action="pause")
                self.phase = "pause_wait"
        elif phase == "pause_wait":
            if self.result():
                self.wait_until = e.tick + 3  # ticks do not advance while paused; steps are counted separately
                self.paused_steps = 0
                self.phase = "paused"
        elif phase == "paused":
            self.paused_steps += 1
            if self.paused_steps == 100:
                self.submit("god_time", action="resume")
                self.phase = "resume_wait"
        elif phase == "resume_wait":
            if self.result():
                self.do_claim()
                self.phase = "request_again"
        elif phase == "idle_forever":
            self.idle()
        if phase == "request_again" and self.orders_done >= 3:
            self.phase = "idle_forever"
        if phase == "await_collect" and self.orders_done >= 3:
            self.phase = "idle_forever"


async def main():
    catcher = ErrorCatcher()
    logging.getLogger().addHandler(catcher)
    engine = backend.engine
    engine.reset_world()
    await backend.create_genesis(engine, map_name="starter_village")
    # the soak measures the game, not tick-0 provisioning noise: counters start now
    state = runtime(engine)
    mover = state.mover
    counters = {"replanned": 0, "blocked": {}, "plan_calls_start": mover.plan_calls}
    original = mover.step

    def counted(*a, **k):
        result = original(*a, **k)
        counters["replanned"] += int(result.replanned)
        if result.blocked:
            counters["blocked"][result.blocked] = counters["blocked"].get(result.blocked, 0) + 1
        return result
    mover.step = counted

    bot = Bot(engine)
    from concurrent.futures import ThreadPoolExecutor
    from runtime.resident_store import write_resident_batch
    writer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="soak-resident-writer") if args.resident_writes == "background" else None
    write_futures, capture_ms = [], []
    ring, forensics = [], {}  # last 60 ticks of every resident's full tensor row; frozen into the result on a death
    if writer_pool is not None:
        engine.resident_store.background_writes = True  # exactly what the gameplay server's lifespan does
    work_ms, paused_ms, samples, slow_ticks = [], [], [], []
    names = {engine.resident_store.get(u)["profile"]["name"]: u for u in engine._human_uid_by_slot if u}
    last_pos = {n: None for n in names}
    stall = {n: 0 for n in names}
    max_stall = {n: 0 for n in names}
    embedded = {n: 0 for n in names}
    reversals = {n: 0 for n in names}
    last_dir = {n: None for n in names}
    max_step = {n: 0.0 for n in names}
    deaths = []
    rss_start = rss_mb()
    started = time.perf_counter()
    paused_steps = 0
    contract = None
    weather_cycle = ["rain", "clear", "storm", "clear", "cold", "clear"]
    god_ops = 0
    while engine.tick < args.ticks:
        bot.act()
        t0 = time.perf_counter()
        engine.step()
        elapsed = (time.perf_counter() - t0) * 1000.0
        if writer_pool is not None and engine.tick % 20 == 10:  # ResidentWriter.flush_once, once a second, outside the tick
            c0 = time.perf_counter()
            for future in [f for f in write_futures if f.done()]:
                write_futures.remove(future)
                engine.resident_store.acknowledge_writes(future.result())
            jobs = engine.resident_store.capture_dirty(engine.tick, force=True, limit=16)
            if jobs:
                write_futures.append(writer_pool.submit(write_resident_batch, jobs))
            capture_ms.append((time.perf_counter() - c0) * 1000.0)
        if backend.__dict__.get("god_pause_step") and engine.__dict__.get("_god_paused"):
            paused_steps += 1
            paused_ms.append(elapsed)
            continue
        work_ms.append(elapsed)
        tick = engine.tick
        if elapsed > 50.0 and len(slow_ticks) < 2000:
            slow_ticks.append((tick, round(elapsed, 1)))
        contract = world_contract(engine) if tick % 50 == 0 or contract is None else contract
        snapshot_rows = {}
        for name, uid in names.items():
            slot = engine._human_slot_for_id(uid)
            if slot < 0 or float(engine.state.h_tensor[slot, cfg.TYPE]) == 0:
                if name not in [d[1] for d in deaths]:
                    deaths.append((tick, name))
                    forensics[name] = {"tick": tick, "slot": slot, "last_rows": [(t, rows.get(name)) for t, rows in ring[-12:]],
                                       "events": [str(e)[:160] for e in list(engine._pending_events)[:6]],
                                       "age_scale": (engine.resident_store.get(uid).get("roster") or {}).get("age_scale")}
                continue
            snapshot_rows[name] = [round(v, 3) for v in engine.state.h_tensor[slot].tolist()]
            p = (float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))
            controlled = engine.player_control.describe_human_slot(slot) is not None
            if last_pos[name] is not None and not controlled:
                dx, dy = p[0] - last_pos[name][0], p[1] - last_pos[name][1]
                step = math.hypot(dx, dy)
                max_step[name] = max(max_step[name], step)
                goal, at = state.goal_key.get(uid), state.at_anchor.get(uid)
                if goal and not at and step < 0.01:
                    stall[name] += 1
                    max_stall[name] = max(max_stall[name], stall[name])
                else:
                    stall[name] = 0
                if step > 0.2:
                    direction = (dx / step, dy / step)
                    if last_dir[name] and direction[0] * last_dir[name][0] + direction[1] * last_dir[name][1] < -0.9:
                        reversals[name] += 1
                    last_dir[name] = direction
            last_pos[name] = p
            if tick % 20 == 0 and not is_standable_point(p, contract):
                embedded[name] += 1
        ring.append((tick, snapshot_rows))
        del ring[:-60]
        if tick % args.sample_every == 0:
            rows = {}
            for name, uid in names.items():
                slot = engine._human_slot_for_id(uid)
                if slot < 0:
                    continue
                h = engine.state.h_tensor[slot]
                rows[name] = {"hp": round(float(h[cfg.HP]), 1), "hunger": round(float(h[cfg.HUNGER]), 2), "thirst": round(float(h[cfg.THIRST]), 2),
                              "stamina": round(float(h[cfg.H_STAMINA]), 1), "x": round(float(h[cfg.X]), 1), "y": round(float(h[cfg.Y]), 1),
                              "goal": state.goal_key.get(uid), "at": state.at_anchor.get(uid)}
            memory_events = sum(len(engine.resident_store.get(u)["memory"]["recent_events"]) for u in names.values())
            log_path = engine.__dict__.get("_decision_service")
            samples.append({"tick": tick, "rss_mb": rss_mb(), "residents": rows, "memory_events": memory_events,
                            "inventory_state_kb": round(len(json.dumps(engine.inventory_state, default=str)) / 1024, 1),
                            "pending_events": len(engine._pending_events), "command_records": len(engine.command_inbox.records),
                            "talk_lines": len(engine.talk_agent.recent_lines), "orders": len(bot.orders()),
                            "frame_kb": round(len(json.dumps(engine._frame_payload, default=str)) / 1024, 1),
                            "elapsed_s": round(time.perf_counter() - started, 1)})
            print(f"tick {tick:6d}  rss {samples[-1]['rss_mb']} MB  p50 so far {percentile(work_ms, 50)} ms  orders {len(bot.orders())}  bot {bot.phase}", flush=True)
        # periodic god activity once the scripted loop is over
        if bot.phase == "idle_forever" and tick % 3000 == 0 and tick > 0 and not engine.__dict__.get("_god_paused"):
            if bot.claim:
                bot.do_release()
            kind = weather_cycle[god_ops % len(weather_cycle)]
            bot.submit("god_weather", weather=kind)
            god_ops += 1
    wall = time.perf_counter() - started
    rss_end = rss_mb()
    decisions = engine.__dict__.get("_decision_service")
    log_file = Path(str(decisions.status()["log_path"])) if decisions and decisions.status().get("log_path") else None
    if log_file and not log_file.exists():
        candidates = list((DATA_ROOT / "decisions").glob("*.jsonl")) if (DATA_ROOT / "decisions").exists() else []
        log_file = candidates[0] if candidates else None
    result = {
        "ticks": engine.tick, "wall_seconds": round(wall, 1), "budget_ms": 50.0,
        "work_ms": {"mean": round(statistics.fmean(work_ms), 3), "p50": percentile(work_ms, 50), "p95": percentile(work_ms, 95),
                    "p99": percentile(work_ms, 99), "max": round(max(work_ms), 3)},
        "slow_ticks": slow_ticks,
        "overruns_over_50ms": sum(1 for v in work_ms if v > 50.0), "overruns_over_25ms": sum(1 for v in work_ms if v > 25.0),
        "paused_steps": paused_steps, "paused_ms_p99": percentile(paused_ms, 99),
        "rss_mb": {"start": rss_start, "end": rss_end}, "deaths": deaths,
        "needs_max": {n: {k: max(s["residents"][n][k] for s in samples if n in s["residents"]) for k in ("hunger", "thirst")} for n in names},
        "hp_min": {n: min(s["residents"][n]["hp"] for s in samples if n in s["residents"]) for n in names},
        "embedded_samples": embedded, "max_consecutive_stalled_ticks": max_stall, "direction_reversals": reversals, "max_step": {n: round(v, 3) for n, v in max_step.items()},
        "needs_loop": {name: getattr(runtime(engine), name, 0) for name in ("trips_done", "rations", "trip_timeouts", "trip_blocked", "portal_uses")},
        "death_forensics": forensics,
        "graph_writer": engine._memory_graph_writer.status(),
        "resident_writes": {"mode": args.resident_writes, "capture_between_ticks_ms": {"p50": percentile(capture_ms, 50), "p99": percentile(capture_ms, 99),
                                                                                          "max": round(max(capture_ms), 3) if capture_ms else None}},
        "mover": {"plan_calls": mover.plan_calls - counters["plan_calls_start"], "replanned_steps": counters["replanned"], "blocked": counters["blocked"]},
        "orders": [{k: o[k] for k in ("order_id", "state", "progress_ticks", "failure_reason", "refusal_reason")} for o in bot.orders()],
        "bot_timeline": bot.timeline, "decision_log_bytes": log_file.stat().st_size if log_file and log_file.exists() else 0,
        "decision_status": decisions.status() if decisions else None,
        "dispatch_errors": list(DISPATCH.errors), "logged_errors": catcher.records[:20], "logged_error_count": len(catcher.records),
        "final": samples[-1] if samples else None, "samples": samples,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("samples", "final", "bot_timeline")}, indent=1, default=str))
    print("bot timeline:", result["bot_timeline"])


asyncio.run(main())
