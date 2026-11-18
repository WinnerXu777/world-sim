"""Tier 1 acceptance (R3-INT step 4, ``1008_agent_driver_design.md``): the agent driver over one game day on the real headless engine.

    .venv/Scripts/python.exe -m model_server.tier1_acceptance --tier1 rules  --ticks 2400 --json out_rules.json
    .venv/Scripts/python.exe -m model_server.tier1_acceptance --tier1 matrix --ticks 2400 --json out_matrix.json
    .venv/Scripts/python.exe -m model_server.tier1_acceptance --compare --ticks 2400            # both, then the comparison

All eight roster residents are bound to ``driver == "agent"`` (the player-claimed customer is skipped by the driver, as in play). A game day is
``DEFAULT_DAY_LENGTH_TICKS`` = 2400 ticks. At tick 0 the customer asks the smith for a sword (the real commission loop, real work time); when it is
ready the customer collects it. Per tick, for every agent-driven resident, the run records position, hunger, thirst, HP and the *reason* it is not
moving. A resident is **idle** on a tick when it did not move and has no reason: not at an anchor (``RosterRuntime.at_anchor``), no food/water trip
in progress, no queued or active task. The acceptance checks (defaults are the stated bounds; the run reports the measured values whatever they are):

* ``commission``: the order reaches ``ready`` and is delivered, one sword;
* ``needs_bounded``: the highest hunger or thirst any agent resident reaches stays at or below ``--max-need`` (default 60: the trip threshold is 30,
  a trip takes under 200 ticks at the shipped need rate), and nobody dies (HP above 0);
* ``idle``: the longest run of consecutive idle ticks of any resident is at most ``--max-idle`` (default 30);
* ``failures``: Tier 1 raised no exception (``AgentDriver.errors``), the driver left no resident without a goal for more than ``--max-idle`` ticks and
  ``run:failed`` count is 0. NOTE: the agent driver walks goals (AnchorMover); it does not call ``ActionRunner`` yet, so the runner audit log has no
  entries from Tier 1 and the ``run:failed`` count is the Tier 3 / runner counter (0 when no plan runs), reported separately;
* ``budget``: Tier 1 decisions per tick on average at most ``--max-decisions`` (default 1.0) and the slowest ``decide`` call at most
  ``--max-decide-ms`` (default 25.0).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAY_TICKS = 2400


def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1))))]


async def run(args) -> dict:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "at_the_beginning"))
    from harness.headless import boot_engine, configure_environment
    configure_environment()
    if args.actions:
        os.environ["EDEN_AGENT_ACTIONS"] = "1"             # Tier 1 macros that are not walks run through ActionRunner (audit entries below)
    backend, engine = await boot_engine(args.seed)
    import genesis_config as cfg
    from systems.actions.agent_driver import AgentDriver, MatrixTier1, RulesTier1
    from systems.commission.engine import find_smith
    from systems.roster.driver import runtime
    tier1 = MatrixTier1() if args.tier1 == "matrix" else RulesTier1()
    driver = AgentDriver(tier1, period=args.period)
    engine.__dict__["_agent_driver"] = driver
    humans = [u for u in engine._human_uid_by_slot if u]
    for human_id in humans:
        binding = engine.resident_store.get(human_id)["roster"]
        binding["driver"] = "agent"
        if args.needs_scale is not None:
            binding["needs_scale"] = args.needs_scale       # the shipped 0.015 gives no trip in a day (hunger 1.8): a faster clock makes "bounded" a real test
    smith_id, _ = find_smith(engine)
    customer = next(u for u in humans if engine.resident_store.get(u)["roster"]["key"] == "iven")
    claim = engine.player_control.claim_target(engine, controller_id="cust", target_kind="human", target_id=customer)
    engine.player_control.clock = lambda: 0.0                          # the possession does not lapse during the day
    env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch")} | {"controller_id": "cust"}
    h = engine.state.h_tensor
    slot_of = {u: engine._human_slot_for_id(u) for u in humans}

    def pos(u):
        return float(h[slot_of[u], cfg.X]), float(h[slot_of[u], cfg.Y])

    def customer_next_to_smith(dx, dy):
        x, y = pos(smith_id)
        h[slot_of[customer], cfg.X], h[slot_of[customer], cfg.Y] = x + dx, y + dy

    def command(action, **extra):
        payload = {**env, "command_id": str(uuid.uuid4()), **extra}
        received = engine.command_inbox.submit(engine, action, payload)
        engine.step()
        return received, engine.command_inbox.result(payload["command_id"])

    warm_ms = driver.warm(engine)                                  # the cold-start cost, paid once and reported apart from the per-decision figures
    decide_ms, decide_slowest = [], []
    inner_decide = tier1.decide

    def timed_decide(engine_, rows):
        began = time.perf_counter()
        try:
            return inner_decide(engine_, rows)
        finally:
            took = (time.perf_counter() - began) * 1000.0
            decide_ms.append(took)
            decide_slowest.append((round(took, 2), int(engine_.tick) - began_tick, len(rows)))
            decide_slowest.sort(reverse=True)
            del decide_slowest[5:]
    tier1.decide = timed_decide
    step_ms, driver_ms = [], []
    inner_step = driver.step

    def timed_step(engine_):
        began = time.perf_counter()
        try:
            return inner_step(engine_)
        finally:
            driver_ms.append((time.perf_counter() - began) * 1000.0)
    driver.step = timed_step

    customer_next_to_smith(9.0, 3.0)
    began_tick = int(engine.tick)
    received, result = command("commission_request")
    accepted = bool(result and result.get("code") == "accepted")
    order = next(iter(engine.inventory_state.get("work_orders", {}).get("orders", {}).values()), None)
    timeline = {"requested": int(engine.tick) - began_tick, "accepted": accepted}
    state = runtime(engine)
    watched = [u for u in humans if u != customer]
    last_pos = {u: pos(u) for u in watched}
    idle_run = {u: 0 for u in watched}
    idle_max = {u: (0, 0) for u in watched}                      # human -> (longest run, tick it ended)
    worst = {"hunger": 0.0, "thirst": 0.0, "min_hp": 100.0}
    worst_at = {}
    delivered = None
    reasons = {"anchor": 0, "trip": 0, "task": 0, "moved": 0, "idle": 0}
    for _ in range(args.ticks - (int(engine.tick) - began_tick)):
        began = time.perf_counter()
        engine.step()
        step_ms.append((time.perf_counter() - began) * 1000.0)
        tick = int(engine.tick) - began_tick
        if order is not None:
            if "working" not in timeline and order["state"] == "working":
                timeline["working"] = tick
            if "ready" not in timeline and order["state"] == "ready":
                timeline["ready"] = tick
                customer_next_to_smith(6.0, 2.0)
                _, delivered = command("commission_collect", order_id=order["order_id"])
                timeline["delivered"] = int(engine.tick) - began_tick
        for u in watched:
            x, y = pos(u)
            moved = math.hypot(x - last_pos[u][0], y - last_pos[u][1]) > 1e-6
            last_pos[u] = (x, y)
            record = engine.resident_store.get(u) or {}
            busy = any(str(t.get("status", "")) in ("queued", "active") for t in record.get("tasks", []) or [])
            if moved:
                reasons["moved"] += 1
                idle_run[u] = 0
            elif state.at_anchor.get(u):
                reasons["anchor"] += 1
                idle_run[u] = 0
            elif u in state.trips:
                reasons["trip"] += 1
                idle_run[u] = 0
            elif busy:
                reasons["task"] += 1
                idle_run[u] = 0
            else:
                reasons["idle"] += 1
                idle_run[u] += 1
                if idle_run[u] > idle_max[u][0]:
                    idle_max[u] = (idle_run[u], tick)
            for need, column in (("hunger", cfg.HUNGER), ("thirst", cfg.THIRST)):
                value = float(h[slot_of[u], column])
                if value > worst[need]:
                    worst[need], worst_at[need] = value, (u, tick)
            hp = float(h[slot_of[u], cfg.HP])
            worst["min_hp"] = min(worst["min_hp"], hp)
    orders = list(engine.inventory_state.get("work_orders", {}).get("orders", {}).values())
    swords = 0
    for record in engine.inventory_state["inventories"].values():
        swords += sum(i["quantity"] for i in record["items"] if i["kind"] == "sword")
    final_positions = {u: [round(v, 4) for v in pos(u)] for u in humans}
    longest = max(idle_max.values(), key=lambda t: t[0])
    ticks_run = len(step_ms)
    runner = driver._runner_ctx[1]
    audit = list(runner.audit.entries) if runner is not None else []
    by_verb: dict = {}
    for entry in audit:
        by_verb.setdefault(entry["verb"], {}).setdefault(entry["code"], 0)
        by_verb[entry["verb"]][entry["code"]] += 1
    rejections = [{"tick": e["tick"], "actor": e["actor"], "verb": e["verb"], "code": e["code"], "detail": e.get("detail")} for e in audit if not e["ok"]]
    tier3_failed = 0
    plane_esc = engine.__dict__.get("_tier3_escalator")
    if plane_esc is not None:
        tier3_failed = sum(v for k, v in plane_esc.counts.items() if str(k).startswith("run:failed"))
    result_dict = {
        "tier1": args.tier1, "actions_flag": bool(args.actions), "needs_scale": args.needs_scale, "ticks": int(engine.tick) - began_tick, "seed": args.seed, "period": driver.period, "residents": len(watched), "day_ticks": DAY_TICKS,
        "commission": {"accepted": accepted, "final_state": orders[0]["state"] if orders else None, "swords_in_world": swords, "timeline": timeline,
                       "collect_code": (delivered or {}).get("code") if isinstance(delivered, dict) else None},
        "needs": {"max_hunger": round(worst["hunger"], 2), "max_thirst": round(worst["thirst"], 2), "min_hp": round(worst["min_hp"], 2),
                  "worst_at": {k: [v[0], v[1]] for k, v in worst_at.items()}, "trips_done": state.trips_done, "rations": state.rations,
                  "trip_timeouts": state.trip_timeouts, "trip_blocked": state.trip_blocked},
        "idle": {"longest_run": longest[0], "ended_at_tick": longest[1], "per_resident": {u: idle_max[u][0] for u in watched}, "tick_reasons": reasons},
        "failures": {"tier1_errors": driver.errors, "run_failed": tier3_failed + len(rejections), "no_legal_rows": getattr(tier1, "no_legal", 0),
                     "rejections": rejections[:20]},
        "actions": {"enabled": bool(args.actions), "audit_entries": len(audit), "by_verb": by_verb, "routed": dict(driver.routed),
                    "proposers": sorted({str(e.get("proposer")) for e in audit}), "first_ticks": [e["tick"] for e in audit[:5]]},
        "budget": {"decisions": driver.decided, "decisions_per_tick": round(driver.decided / max(ticks_run, 1), 4), "interrupts": driver.interrupts,
                   "warm_ms": round(warm_ms, 2), "decide_calls": len(decide_ms), "slowest_decide_calls": [{"ms": a, "tick": b, "rows": n} for a, b, n in decide_slowest], "decide_ms": {"mean": round(sum(decide_ms) / max(len(decide_ms), 1), 3),
                                                                  "p99": round(percentile(decide_ms, 99), 3), "max": round(max(decide_ms or [0.0]), 3)},
                   "driver_step_ms": {"mean": round(sum(driver_ms) / max(len(driver_ms), 1), 3), "p99": round(percentile(driver_ms, 99), 3),
                                      "max": round(max(driver_ms or [0.0]), 3)},
                   "tick_ms": {"mean": round(sum(step_ms) / max(ticks_run, 1), 3), "p99": round(percentile(step_ms, 99), 3), "max": round(max(step_ms), 3)}},
        "driver_status": driver.status(), "final_positions": final_positions,
    }
    result_dict["verdict"] = verdict(result_dict, args)
    return result_dict


def verdict(result: dict, args) -> dict:
    checks = {
        "commission": bool(result["commission"]["accepted"]) and "delivered" in result["commission"]["timeline"] and result["commission"]["swords_in_world"] == 1,
        "needs_bounded": max(result["needs"]["max_hunger"], result["needs"]["max_thirst"]) <= args.max_need and result["needs"]["min_hp"] > 0.0,
        "idle": result["idle"]["longest_run"] <= args.max_idle,
        "failures": result["failures"]["tier1_errors"] == 0 and result["failures"]["run_failed"] == 0,
        "budget": result["budget"]["decisions_per_tick"] <= args.max_decisions and result["budget"]["decide_ms"]["max"] <= args.max_decide_ms,
    }
    if result["actions"]["enabled"]:
        checks["actions"] = result["actions"]["audit_entries"] > 0 and all(p.startswith("tier1") for p in result["actions"]["proposers"])
    return {"ok": all(checks.values()), "checks": checks, "bounds": {"max_need": args.max_need, "max_idle": args.max_idle,
                                                                     "max_decisions": args.max_decisions, "max_decide_ms": args.max_decide_ms}}


def compare(rules: dict, matrix: dict) -> dict:
    same_positions = rules["final_positions"] == matrix["final_positions"]
    return {"final_positions_equal": same_positions, "commission_timeline_equal": rules["commission"]["timeline"] == matrix["commission"]["timeline"],
            "decisions": [rules["budget"]["decisions"], matrix["budget"]["decisions"]],
            "tick_ms_mean": [rules["budget"]["tick_ms"]["mean"], matrix["budget"]["tick_ms"]["mean"]],
            "decide_ms_max": [rules["budget"]["decide_ms"]["max"], matrix["budget"]["decide_ms"]["max"]],
            "idle_longest": [rules["idle"]["longest_run"], matrix["idle"]["longest_run"]],
            "max_need": [max(rules["needs"]["max_hunger"], rules["needs"]["max_thirst"]), max(matrix["needs"]["max_hunger"], matrix["needs"]["max_thirst"])]}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tier1", choices=("rules", "matrix"), default="rules")
    p.add_argument("--ticks", type=int, default=DAY_TICKS)
    p.add_argument("--seed", type=int, default=1008)
    p.add_argument("--period", type=int, default=10)
    p.add_argument("--needs-scale", type=float, default=1.0, help="roster needs_scale for every resident (shipped 0.015: no trip in a day); 0 keeps the shipped value")
    p.add_argument("--max-need", type=float, default=60.0)
    p.add_argument("--max-idle", type=int, default=30)
    p.add_argument("--max-decisions", type=float, default=1.0)
    p.add_argument("--max-decide-ms", type=float, default=25.0)
    p.add_argument("--actions", action="store_true", help="EDEN_AGENT_ACTIONS=1: route Tier 1 action macros through ActionRunner")
    p.add_argument("--json", default="")
    p.add_argument("--compare", action="store_true", help="run rules then matrix in two processes and print the comparison")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.needs_scale == 0:
        args.needs_scale = None
    if args.compare:
        import subprocess
        outs = {}
        for kind in ("rules", "matrix"):
            out = Path(args.json or ROOT / ".runtime") / f"tier1_acceptance_{kind}.json" if not args.json else Path(f"{args.json}.{kind}.json")
            cmd = [sys.executable, "-m", "model_server.tier1_acceptance", "--tier1", kind, "--ticks", str(args.ticks), "--seed", str(args.seed), "--period", str(args.period), "--needs-scale", str(args.needs_scale or 0),
                   *(["--actions"] if args.actions else []),
                   "--max-need", str(args.max_need), "--max-idle", str(args.max_idle), "--max-decisions", str(args.max_decisions),
                   "--max-decide-ms", str(args.max_decide_ms), "--json", str(out)]
            subprocess.run(cmd, cwd=str(ROOT), check=False, env={**os.environ, "EDEN_ROSTER_DRIVER": "anchor"})
            outs[kind] = json.loads(Path(out).read_text(encoding="utf-8"))
        print(json.dumps({"compare": compare(outs["rules"], outs["matrix"]), "rules_ok": outs["rules"]["verdict"]["ok"],
                          "matrix_ok": outs["matrix"]["verdict"]["ok"]}, indent=2))
        return 0 if outs["rules"]["verdict"]["ok"] and outs["matrix"]["verdict"]["ok"] else 1
    result = asyncio.run(run(args))
    text = json.dumps(result, indent=2)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("tier1", "ticks", "commission", "needs", "idle", "failures", "actions", "budget", "verdict")}, indent=2))
    return 0 if result["verdict"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
