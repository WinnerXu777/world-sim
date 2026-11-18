"""Gate A harness: the real headless engine for N ticks against the mock model server with injected faults.

    .venv/Scripts/python.exe -m model_server.gate_a --ticks 36000 --models on     # 30 game minutes, faults injected
    .venv/Scripts/python.exe -m model_server.gate_a --ticks 36000 --models off    # baseline: same traffic, every role off
    .venv/Scripts/python.exe -m model_server.gate_a --compare --ticks 36000       # both, then the verdict

Synthetic but realistic traffic: every resident asks a Tier 2 decision every 2 game seconds (through ``DecisionService`` and
``ClefDecisionProvider``), and the legacy hooks (``run_tiny_model_mode_batch`` / ``run_world_model_mode_batch``) are called for
normal_live, talk_reply, resident_reasoning and decree. The model server runs in a SEPARATE process (a real HTTP hop) with
timeouts, garbage, slow, bad-result, stale and 500 replies injected deterministically; at 60 percent of the run the server is
killed to check that the game degrades to rules. The tick is timed with and without the model traffic.

Startup mirrors the gameplay server (``map_test.lifespan``, ``tools/profile_tick.py``): resident writes are background writes
(``resident_store.background_writes = True``) flushed by a one-thread writer pool once per game second, outside the tick figures, and the
loaded world is gc-frozen unless ``--gc-freeze 0`` (sets ``EDEN_GC_FREEZE=0``). The 2 x 2 for R3-M1 is models off/on x ``--gc-freeze`` 0/1.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAULTS = [{"kind": "hang", "rate": 0.03, "delay_ms": 3000}, {"kind": "slow", "rate": 0.05, "delay_ms": 1500},
          {"kind": "garbage", "rate": 0.04}, {"kind": "bad_result", "rate": 0.03}, {"kind": "stale", "rate": 0.03},
          {"kind": "error500", "rate": 0.03}]
STAGE1_P99_MS = 28.0
SLOW_TICK_MS = 50.0


def percentile(values, p):
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(len(ordered) * p / 100.0) - 1))] if ordered else 0.0


def stats(values):
    return {"n": len(values), "p50": round(percentile(values, 50), 3), "p95": round(percentile(values, 95), 3),
            "p99": round(percentile(values, 99), 3), "max": round(max(values, default=0.0), 3)}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def spawn_server(faults):
    port = free_port()
    env = {**os.environ, "EDEN_MODEL_PORT": str(port), "EDEN_MODEL_FAULTS": json.dumps(faults), "EDEN_MODEL_FAULT_SEED": "1008",
           "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen([sys.executable, "-m", "model_server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import httpx
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get(url + "/health", trust_env=False, timeout=1.0).status_code == 200:
                return proc, url
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("model server subprocess did not start")


class Traffic:
    """The synthetic model traffic driven from the tick loop."""

    def __init__(self, engine, plane, service):
        import genesis_config as cfg
        self.cfg, self.engine, self.plane, self.service = cfg, engine, plane, service
        self.serial = 0
        self.tally = {"decisions": 0, "stale_applied_refused": 0, "legacy_calls": 0, "legacy_answers": 0, "legacy_stand_ins": 0}
        self.modes = {}
        self.followup_modes = {}
        self.previous = []
        self.errors = []
        self.ran = []
        self.pump_ms = 0.0

    def residents(self):
        return [(uid, slot) for slot, uid in enumerate(self.engine._human_uid_by_slot) if uid]

    def state_of(self, slot):
        row = self.engine.state.h_tensor[slot]
        return {"hunger": round(float(row[self.cfg.HUNGER]), 2), "thirst": round(float(row[self.cfg.THIRST]), 2),
                "hp": round(float(row[self.cfg.HP]), 2), "threat": round(float(row[self.cfg.THREAT]), 2)}

    def step(self, tick):
        self.ran = []                      # what this tick did, for the slow-tick log
        try:
            t = time.perf_counter()
            self.plane.pump()
            self.pump_ms = (time.perf_counter() - t) * 1000.0
            if tick % 40 == 0:
                self.ran.append("decisions")
                self.decisions(tick)
            if tick % 100 == 50:
                self.ran.append("legacy:normal_live")
                self.legacy("normal_live", "tiny", lambda uid, s: {"resident_model_mode": "normal_live", "human_id": uid,
                                                                    "local_state": self.state_of(s), "nearby": {}})
            if tick % 300 == 120:
                self.ran.append("legacy:talk_reply")
                self.legacy("talk_reply", "tiny", lambda uid, s: {
                    "resident_model_mode": "talk_reply", "talk_mode": "direct_talk", "speaker_id": "p", "listener_id": uid,
                    "prompt_case": {"utterance": f"hello {tick}", "allowed_physical_intents": ["flee", "back_away", "call_help"]}})
            if tick % 600 == 300:
                self.ran.append("legacy:resident_reasoning")
                self.legacy("resident_reasoning", "world", lambda uid, s: {"world_model_mode": "resident_reasoning", "resident_id": uid,
                                                                            "reason": f"review_{tick}"})
            if tick % 1200 == 600:
                self.ran.append("legacy:decree")
                self.legacy("decree", "world", lambda uid, s: {"world_model_mode": "decree", "query": f"decree {tick}"}, one=True)
        except Exception as exc:  # noqa: BLE001 - counted: the gate fails on any exception reaching here
            self.errors.append(f"tick {tick}: {type(exc).__name__}: {exc}")

    def decisions(self, tick):
        from systems.decision import DecisionOption, DecisionRequest
        for request in self.previous:   # the answer to last cycle's question may be in the cache by now
            again = self.service.decide(request)
            self.followup_modes[again.provider_mode] = self.followup_modes.get(again.provider_mode, 0) + 1
        self.previous = []
        for index, (uid, slot) in enumerate(self.residents()):
            self.serial += 1
            state = self.state_of(slot)
            ids = ("eat", "drink", "rest", "work", "socialise") if index % 2 == 0 else ("continue_plan_step", "USE_BRAIN", "REPLAN")
            request = DecisionRequest(job_id=f"gate:{self.serial}", resident_id=uid, world_epoch=self.engine.world_epoch,
                                      state_revision=tick // 40, tick=tick, trigger=f"gate_event:{self.serial}", question_kind="choice",
                                      options=tuple(DecisionOption(i, i) for i in ids), state=state,
                                      priority=("active", "background", "critical")[index % 3],
                                      deadline_ms=(1000, 2500, 400)[index % 3])
            result = self.service.decide(request)
            self.modes[result.provider_mode] = self.modes.get(result.provider_mode, 0) + 1
            self.tally["decisions"] += 1
            stale = self.serial % 7 == 0
            applied = self.service.apply_if_fresh(request, result, world_epoch=self.engine.world_epoch,
                                                  state_revision=request.state_revision + (1 if stale else 0))
            if stale and not applied:
                self.tally["stale_applied_refused"] += 1
            self.previous.append(request)

    def legacy(self, mode, which, build, one=False):
        cases = [build(uid, slot) for uid, slot in self.residents()]
        cases = cases[:1] if one else cases
        runner = self.engine.run_tiny_model_mode_batch if which == "tiny" else self.engine.run_world_model_mode_batch
        answers = runner(mode=mode, cases=cases, engine=self.engine)
        self.tally["legacy_calls"] += 1
        for answer in answers or []:
            self.tally["legacy_answers" if answer else "legacy_stand_ins"] += 1


def configure_plane(engine, url, models, game_clock):
    from systems.commission.engine import decision_service
    from systems.decision import ClefDecisionProvider
    from systems.modelplane import Endpoint, ModelPlane, ModelPlaneConfig, ModelSwitch
    from systems.modelplane.adapters.legacy import install

    cfg = ModelPlaneConfig(endpoints={r: Endpoint(url) for r in ("decide", "resident", "dialogue", "world")}, breaker_threshold=5,
                           breaker_open_s=2.0)
    for limits in cfg.limits.values():
        limits.update(max_in_flight=16, per_minute=100000)
    service = decision_service(engine)
    plane = ModelPlane(cfg, ModelSwitch(), log=service.log, game_clock=game_clock)
    service.provider = ClefDecisionProvider(plane)
    install(engine, plane)
    if models != "off":
        plane.set_modes(tier2=models, tier3_resident=models, tier3_dialogue=models, tier3_world=models)
    return plane, service


async def run(args):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "at_the_beginning"))
    os.environ["EDEN_GC_FREEZE"] = str(args.gc_freeze)         # read by harness.gcpolicy at create_genesis time
    from harness.headless import boot_engine, configure_environment
    configure_environment()
    backend, engine = await boot_engine(args.seed)
    engine.resident_store.background_writes = True               # exactly what the gameplay server's lifespan does
    writer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gate-resident-writer")
    write_futures = []
    from runtime.resident_store import write_resident_batch
    routes = sorted(r.path for r in backend.app.routes if "model" in getattr(r, "path", ""))
    hooked_plane = engine.__dict__.get("_model_plane")
    proc = url = None
    if args.models != "off":
        proc, url = spawn_server(FAULTS if not args.clean else [])
    plane, service = configure_plane(engine, url or "http://127.0.0.1:9", args.models, lambda: engine.tick / 20.0)
    sweep = None
    if args.sweep and args.models != "off":                      # the Tier 3 escalation sweep drives THIS plane (the backend's own plane stays off)
        from simulation.dispatch import DISPATCH
        from systems.modelplane.tier3.escalation import install as install_escalation
        engine.__dict__["_model_plane"] = plane
        sweep = install_escalation(DISPATCH, plane)
        sweep_times = []                                          # (ms, residents evaluated) of every sweep call, to count the ticks the sweep made slow
        inner = sweep.sweep

        def timed_sweep(engine_, tick):
            began = time.perf_counter()
            report = inner(engine_, tick)
            sweep_times.append(((time.perf_counter() - began) * 1000.0, report["examined"]))
            return report
        sweep.sweep = timed_sweep
    traffic = Traffic(engine, plane, service)
    step_ms, total_ms, killed_at, server_stats = [], [], None, None
    slow, slowest = [], []                  # every tick over SLOW_TICK_MS, and the 10 slowest ticks whatever their time
    gc_state = {"start": 0.0, "ms": 0.0}
    gc_runs = {0: [], 1: [], 2: []}          # per generation: (tick, ms) of every collection during the run

    def gc_probe(phase, info):
        if phase == "start":
            gc_state["start"] = time.perf_counter()
        else:
            took = (time.perf_counter() - gc_state["start"]) * 1000.0
            gc_state["ms"] += took
            gc_runs[info["generation"]].append((engine.tick, round(took, 3)))
    gc.callbacks.append(gc_probe)
    kill_tick = int(args.ticks * 0.6)
    started = time.perf_counter()
    base_tick = engine.tick
    while engine.tick - base_tick < args.ticks:
        if proc is not None and killed_at is None and engine.tick - base_tick >= kill_tick:
            import httpx
            try:
                server_stats = httpx.get(url + "/v1/stats", trust_env=False, timeout=2.0).json()
            except httpx.HTTPError:
                server_stats = None
            proc.kill()
            proc.wait(timeout=10)
            killed_at = engine.tick
        if args.stress and engine.tick % 100 == 0:        # same perturbation in every cell: starve N rotating residents so the sweep has something to judge
            import genesis_config as cfg
            uids = [u for u in engine._human_uid_by_slot if u]
            for k in range(args.stress if uids else 0):
                engine.state.h_tensor[engine._human_slot_for_id(uids[(engine.tick // 100 + k) % len(uids)]), cfg.HUNGER] = float(args.stress_level)
        gc_state["ms"] = 0.0
        t0 = time.perf_counter()
        engine.step()
        t1 = time.perf_counter()
        traffic.step(engine.tick)
        t2 = time.perf_counter()
        step_ms.append((t1 - t0) * 1000.0)
        total_ms.append((t2 - t0) * 1000.0)
        if engine.tick % 20 == 10:          # ResidentWriter.flush_once, once per game second, outside the tick figures
            for future in [f for f in write_futures if f.done()]:
                write_futures.remove(future)
                engine.resident_store.acknowledge_writes(future.result())
            jobs = engine.resident_store.capture_dirty(engine.tick, force=True, limit=16)
            if jobs:
                write_futures.append(writer_pool.submit(write_resident_batch, jobs))
        if (t2 - t0) * 1000.0 > SLOW_TICK_MS or len(slowest) < 10 or (t2 - t0) * 1000.0 > slowest[0][0]:
            client = plane.client.status() if hasattr(plane, "client") else {}
            rec = {"tick": engine.tick, "total_ms": round((t2 - t0) * 1000.0, 2), "engine_step_ms": round((t1 - t0) * 1000.0, 2),
                   "hook_ms": round((t2 - t1) * 1000.0, 2), "pump_ms": round(traffic.pump_ms, 2), "hook_did": list(traffic.ran), "gc_ms": round(gc_state["ms"], 2),
                   "client_queued": client.get("queued"), "client_outbox": client.get("outbox"),
                   "breakers": {u.rsplit("/", 1)[-1]: b.get("state") for u, b in client.get("breakers", {}).items()}}
            if (t2 - t0) * 1000.0 > SLOW_TICK_MS and len(slow) < 500:
                slow.append(rec)
            slowest.append(((t2 - t0) * 1000.0, engine.tick, rec))
            slowest.sort(key=lambda r: r[0])
            del slowest[:-10]
        spare = 0.05 / args.speed - (t2 - t0)
        if spare > 0:                       # the real loop sleeps between ticks; without this the worker threads starve for the GIL
            time.sleep(spare)
    wall = time.perf_counter() - started
    gc.callbacks.remove(gc_probe)
    writer_pool.shutdown(wait=True)
    time.sleep(0.3)
    plane.pump()
    status = plane.status()
    after_kill = traffic.modes
    if proc is not None and proc.poll() is None:
        proc.kill()
    plane.close()
    fallbacks = {}
    for lanes in status["metrics"].values():
        for lane, body in lanes.items():
            if lane == "reasons":
                for reason, count in body.items():
                    fallbacks[reason] = fallbacks.get(reason, 0) + count
    gc_summary = {f"gen{g}": {"n": len(runs), "total_ms": round(sum(ms for _, ms in runs), 2), "max_ms": max((ms for _, ms in runs), default=0.0),
                              "slowest": sorted(runs, key=lambda r: -r[1])[:5]} for g, runs in gc_runs.items()}
    return {"args": vars(args), "sweep": None if sweep is None else sweep.status(),
            "sweep_ms": None if sweep is None else {"calls": len(sweep_times), "evaluated": sum(1 for _, n in sweep_times if n), "over_1ms": sum(1 for t, _ in sweep_times if t > 1.0),
                                                    "over_3ms": sum(1 for t, _ in sweep_times if t > 3.0), "max": round(max((t for t, _ in sweep_times), default=0.0), 3),
                                                    "mean": round(sum(t for t, _ in sweep_times) / max(1, len(sweep_times)), 4)}, "wall_s": round(wall, 1), "ticks": args.ticks, "model_routes": routes,
            "background_writes": True, "gc": gc_summary, "gc_frozen_objects": gc.get_freeze_count(),
            "map_test_plane_present": hooked_plane is not None, "killed_server_at_tick": killed_at,
            "engine_step_ms": stats(step_ms), "step_plus_model_hook_ms": stats(total_ms), "decision_modes": after_kill, "followup_modes": traffic.followup_modes,
            "traffic": traffic.tally, "errors": traffic.errors, "reasons": dict(sorted(fallbacks.items())),
            "slow_ticks_over_ms": SLOW_TICK_MS, "slow_tick_count": len(slow), "slow_ticks": slow[:200],
            "slowest_ticks": [r[2] for r in sorted(slowest, reverse=True)],
            "server_fault_hits": (server_stats or {}).get("fault_hits"), "server_requests": (server_stats or {}).get("requests"),
            "decision_counts": dict(service.counts), "metrics": status["metrics"],
            "breakers": status["client"]["breakers"], "network_calls": status["client"]["network_calls"]}


def verdict(result, baseline=None):
    """List of (check, ok, detail). Used by --compare and by the test."""
    checks = []
    off = result["args"]["models"] == "off"
    checks.append(("zero exceptions reached the tick", not result["errors"], f"{len(result['errors'])} errors {result['errors'][:2]}"))
    if off:
        checks.append(("models off: zero network calls", result["network_calls"] == 0, f"{result['network_calls']} calls"))
        checks.append(("models off: every decision answered by rules", set(result["decision_modes"]) <= {"rules"}, str(result["decision_modes"])))
        return checks
    hits = result.get("server_fault_hits") or {}
    clean = result["args"].get("clean")
    if not clean:
        checks.append(("every injected fault kind fired", all(hits.get(k["kind"], 0) > 0 for k in FAULTS), str(hits)))
    reasons = result["reasons"]
    checks.append(("faults ended as fallbacks (not failures)", clean or sum(v for k, v in reasons.items() if k not in
                   ("disabled", "duplicate", "cooldown")) > 0, str(reasons)))
    modes = result["decision_modes"]
    follow = result["followup_modes"]
    checks.append(("some model answers were used", follow.get("mock", 0) > 0, str(follow)))
    checks.append(("some decisions fell back to rules", clean or modes.get("fallback", 0) > 0, str(modes)))
    checks.append(("server killed mid-run: breaker opened", result["killed_server_at_tick"] is None or any(
        b["opened_count"] > 0 for b in result["breakers"].values()), str(result["breakers"])))
    checks.append(("stale applications were refused", result["traffic"]["stale_applied_refused"] > 0, str(result["traffic"])))
    tick_p99 = result["step_plus_model_hook_ms"]["p99"]
    if baseline is not None:
        base_p99 = baseline["step_plus_model_hook_ms"]["p99"]
        checks.append(("tick p99 unchanged vs models-off baseline (<= +2 ms)", tick_p99 <= base_p99 + 2.0, f"{tick_p99} vs {base_p99} ms"))
    checks.append((f"tick p99 within the Stage 1 baseline ({STAGE1_P99_MS} ms)", tick_p99 <= STAGE1_P99_MS, f"{tick_p99} ms"))
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ticks", type=int, default=36000)
    parser.add_argument("--seed", type=int, default=1008)
    parser.add_argument("--models", choices=("off", "shadow", "on"), default="on")
    parser.add_argument("--speed", type=float, default=1.0, help="1.0 = real 20 Hz pacing (sleep between ticks); 2.0 = twice as fast")
    parser.add_argument("--gc-freeze", type=int, choices=(0, 1), default=1, help="1 = the server's policy (gc.freeze after load); 0 = EDEN_GC_FREEZE=0")
    parser.add_argument("--clean", action="store_true", help="no injected faults (still kills the server at 60 percent)")
    parser.add_argument("--sweep", action="store_true", help="models on: also install the Tier 3 escalation sweep on the harness plane (resident role in the --models mode)")
    parser.add_argument("--stress", type=int, default=0, help="every 100 ticks set hunger to --stress-level on this many rotating residents (any --models mode)")
    parser.add_argument("--stress-level", type=float, default=85.0, help="hunger (0..100) the --stress residents are set to; 95 starves every resident within ~900 ticks and leaves an empty world")
    parser.add_argument("--compare", action="store_true", help="run off then on in fresh processes and print the verdict")
    parser.add_argument("--json", default="", help="write the result JSON here")
    args = parser.parse_args(argv)
    if args.compare:
        results = {}
        for mode in ("off", "on"):
            out = ROOT / ".runtime" / f"gate-a-{mode}.json"
            out.parent.mkdir(exist_ok=True)
            subprocess.run([sys.executable, "-m", "model_server.gate_a", "--ticks", str(args.ticks), "--models", mode, "--seed",
                            str(args.seed), "--speed", str(args.speed), "--gc-freeze", str(args.gc_freeze), "--json", str(out)]
                           + (["--clean"] if args.clean else []), cwd=str(ROOT),
                           env={**os.environ, "PYTHONPATH": str(ROOT)}, check=True)
            results[mode] = json.loads(out.read_text(encoding="utf-8"))
        ok = True
        for result, base in ((results["off"], None), (results["on"], results["off"])):
            print(f"\n== models {result['args']['models']}: {result['ticks']} ticks in {result['wall_s']} s, "
                  f"step+hook p50/p99/max {result['step_plus_model_hook_ms']['p50']}/{result['step_plus_model_hook_ms']['p99']}/"
                  f"{result['step_plus_model_hook_ms']['max']} ms")
            for name, passed, detail in verdict(result, base):
                ok &= passed
                print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail[:200]}")
            print(f"   ticks over {result['slow_ticks_over_ms']} ms: {result['slow_tick_count']}; the 5 slowest:")
            for rec in result["slowest_ticks"][:5]:
                print(f"   tick {rec['tick']}: total {rec['total_ms']} ms (engine {rec['engine_step_ms']}, hook {rec['hook_ms']}, pump {rec['pump_ms']}, gc {rec['gc_ms']}) "
                      f"hook did {rec['hook_did']} queued {rec['client_queued']} breakers {rec['breakers']}")
        return 0 if ok else 1
    import asyncio
    result = asyncio.run(run(args))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("wall_s", "engine_step_ms", "step_plus_model_hook_ms", "decision_modes", "followup_modes", "traffic", "errors",
                                              "reasons", "server_fault_hits", "network_calls", "gc", "gc_frozen_objects")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
