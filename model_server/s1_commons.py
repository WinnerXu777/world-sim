"""S-1 ``commons`` scenario: market + credit + labour + justice (+ reputation) all on, on the authored ``family_farm`` map, deliberately messy.

    .venv/Scripts/python.exe -m model_server.s1_commons --seeds 1008,1,2 --ticks 4000 --json commons.json     (one fresh process per run, a table at the end)
    .venv/Scripts/python.exe -m model_server.s1_commons --seed 1008 --ticks 4000 --single                       (one run in this process)

Five residents, one scarcity: the blight has taken the bushes and the family's food, a demand shock hits the stall's rations, and everyone is somebody:

* ``neighbour_orrin`` keeps the stall (his pantry), pays wages from what he holds and lends to friends.
* ``neighbour_elsa`` is the guard (``roster.authority``) *and* a customer: she is hungry, holds a little coin and no food, so she buys at Orrin's stall like anyone else.
* ``family_mara`` is the honest debtor: high conscience, a little coin; she works, borrows and repays.
* ``family_tomas`` is the defaulter and the thief: low conscience, the neighbours do not trust him much (closeness 0.1); he borrows, does not repay, is refused, and steals when desperate; the
  guard hears of it and levies damages.
* ``family_lina`` is the worker: 16, hungry, works shifts for Orrin and buys.

Checks (``verdict``): nobody dies; no *silent* starvation (a resident past ``--max-hunger`` with no ladder entry in the last ``--silent-window`` ticks, or an errand left standing past its
time-to-live); no deadlock (the number of actions in the second half of the run is not zero); coin and every other item are conserved except by declared consumption; no errors. The numbers are
reported whatever they are: peak hunger, deaths, thefts, cases and damages, loans (opened / repaid / overdue / defaulted), wages (hired / paid), stall sales, per-rung counts.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_server import s1_family_farm as farm  # noqa: E402

STALL, KEEPER, GUARD = farm.STALL, "neighbour_orrin", "neighbour_elsa"
DAY_TICKS = 600
FLAGS = dict(EDEN_AGENT_ACTIONS="1", EDEN_AGENT_LADDER="1", EDEN_REPUTATION="1", EDEN_MARKET="1", EDEN_CREDIT="1", EDEN_LABOUR="1", EDEN_JUSTICE="1")
TRAITS = {**farm.TRAITS,
          "family_tomas": {"mercy": 0.2, "loyalty": 0.3, "discipline": 0.15, "deceitfulness": 0.8, "greed": 0.7, "aggression": 0.4, "protectiveness": 0.9, "caution": 0.2,
                           "pride": 0.3, "vengefulness": 0.3},
          "neighbour_elsa": {**farm.TRAITS["neighbour_elsa"], "discipline": 0.8, "protectiveness": 0.7}}
COIN = {"family_mara": 3, GUARD: 6}                     # the rest hold none


def roster(needs_scale: float, keeper_rations: int = 4) -> dict:
    def person(key, name, sex, age, anchors, stock=None):
        return {"key": key, "name": name, "sex": sex, "age": age, "role": "gatherer", "archetype": "stoic_survivor", "traits": TRAITS[key], "anchors": anchors,
                "stock": stock or {}, "personal": {"coin": COIN[key]} if key in COIN else {}, "inventory": {"slots": 16, "weight": 60.0}, "work_mode": "anchor_only", "needs_sites": False}
    base = farm.roster("trade", needs_scale)
    by_key = {r["key"]: r for r in base["residents"]}
    out = []
    for key in ("family_mara", "family_tomas", "family_lina", "neighbour_orrin", "neighbour_elsa"):
        r = dict(by_key[key])
        r["traits"] = TRAITS[key]
        r["personal"] = {"coin": COIN[key]} if key in COIN else {}
        r["stock"] = {"rations": keeper_rations} if key == KEEPER and keeper_rations else {}
        out.append(r)
    base["residents"] = out
    return base


def configure(needs_scale: float, keeper_rations: int = 4) -> Path:
    data_root = Path(tempfile.mkdtemp(prefix="eden-s1commons-"))
    roster_dir = data_root / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "family_farm.json").write_text(json.dumps(roster(needs_scale, keeper_rations), indent=1), encoding="utf-8")
    os.environ.update(
        EDEN_PROFILE="gameplay", EDEN_DATA_ROOT=str(data_root), EDEN_MAP="family_farm", EDEN_EMBEDDINGS="lexical", EDEN_ROSTER_DIR=str(roster_dir),
        EDEN_MAP_FILES=os.pathsep.join(str(ROOT / "world_data" / "maps2d" / f"{name}.json") for name in farm.MAP_NAMES),
        EDEN_MAP_ORIGINS=json.dumps(farm.MAP_ORIGINS), EDEN_MAP_RESOURCES="1", EDEN_ROSTER_DRIVER="agent", **FLAGS)
    for path in (str(ROOT), str(ROOT / "at_the_beginning")):
        if path not in sys.path:
            sys.path.insert(0, path)
    return data_root


def setup(engine, args) -> dict:
    """The blight, the stall, the guard, the relationships and the hunger."""
    import genesis_config as cfg
    from systems.actions.agent_driver import driver_of
    from systems.market import runtime as market_runtime
    keys = farm.keys_of(engine)
    h = engine.state.h_tensor
    for key, uid in keys.items():
        record = engine.resident_store.get(uid)
        record["roster"]["driver"] = "agent"
        if key == GUARD:
            record["roster"]["authority"] = True
        if key == KEEPER:
            record["roster"]["stall"] = STALL
        engine.resident_store.touch_resident(uid)
    for key in ("family_mara", "family_tomas", "family_lina"):
        h[engine._human_slot_for_id(keys[key]), cfg.HUNGER] = args.mara_hunger if key == "family_mara" else args.family_hunger
    h[engine._human_slot_for_id(keys[GUARD]), cfg.HUNGER] = args.guard_hunger
    import random
    jitter = random.Random(args.seed)                      # the seed also shuffles who starts how hungry (+-6), so the runs differ in more than the world's draws
    for key in sorted(keys):
        slot = engine._human_slot_for_id(keys[key])
        h[slot, cfg.HUNGER] = max(0.0, min(95.0, float(h[slot, cfg.HUNGER]) + jitter.uniform(-6.0, 6.0))) if args.seed != 1008 else float(h[slot, cfg.HUNGER])
    kind_of = {}
    family = ("family_mara", "family_tomas", "family_lina")
    for a in family:
        for b in family:
            if a != b:
                engine.resident_store.update_relationship(keys[a], keys[b], "family", 0.4, 0)
    for neighbour in (KEEPER, GUARD):
        for fam in family:
            close = 0.1 if fam == "family_tomas" else 0.45 if fam == "family_mara" else 0.25
            engine.resident_store.update_relationship(keys[fam], keys[neighbour], "neighbour", close, 0)
            engine.resident_store.update_relationship(keys[neighbour], keys[fam], "neighbour", close, 0)
        kind_of[neighbour] = "neighbour"
    engine.resident_store.update_relationship(keys[KEEPER], keys[GUARD], "neighbour", 0.5, 0)
    engine.resident_store.update_relationship(keys[GUARD], keys[KEEPER], "neighbour", 0.5, 0)
    from harness import effects as fx
    from harness.adapter import EngineWorld
    world = EngineWorld(engine, seed=0)
    removed = {}
    for entity in ("family:pantry", "family_interior:storage"):
        for item in ("rations", "crop_bundle", "fish_catch", "berries", "mushrooms"):
            have = world.items.quantity(entity, item)
            if have:
                report = world.apply([fx.Transfer(item, have, entity, None)], atomic=True, cause="scenario:blight", items=fx.ItemPermit(consume={item: have}))
                removed[f"{entity}:{item}"] = have if report.ok else -1
    table = world.table("entities")
    for node in ("family:bush_far_1", "family:bush_far_2", "family:bush_far_3"):
        slot = table.slot_of(node)
        if slot is not None:
            for column in ("food", "node_stock", "growth_rate"):
                if column in table.columns:
                    table.tensor[slot, table.columns[column]] = 0.0
    for item, qty in ({"rations": args.stall_rations} if args.stall_rations else {}).items():
        world.apply([fx.Transfer(item, qty, None, STALL)], atomic=True, cause="scenario:stall", items=fx.ItemPermit(produce={item: qty}))
    services = driver_of(engine).runner(engine).services
    market_runtime.register_stall(services, STALL)
    from systems.credit import runtime as credit_runtime
    loans = credit_runtime.of(services)                  # yesterday's debts (the items were eaten long ago): the honest one is repaid, the other goes bad
    owed = {}
    for lender, borrower in ((KEEPER, "family_mara"), (GUARD, "family_tomas")):
        loan = loans.open(keys[lender], keys[borrower], "rations", 1, 0.45, 0, args.day_ticks)
        owed[f"{borrower}->{lender}"] = loan.id
    return {"loans": owed, "removed": removed, "stall": STALL, "keeper": KEEPER, "guard": GUARD}


def totals(world) -> dict:
    return {k: int(world.items.total(k)) for k in sorted(world.items.items())}


async def run(args) -> dict:
    os.environ.update(FLAGS)
    if args.rob:                                                   # the top rung and its answer: guard posts, robbery, arrest by restraint
        os.environ.update(EDEN_DEFEND="1", EDEN_ROB="1", EDEN_RESTRAINT="1")
    if args.rungs:
        os.environ["EDEN_LADDER_RUNGS"] = args.rungs
    os.environ["EDEN_AGENT_TIER1"] = args.tier1
    os.environ["EDEN_SEED"] = str(args.seed)                       # the world's deterministic draws (reputation notice / trace) are keyed by it
    configure(args.needs_scale, args.keeper_rations)
    import map_test as backend  # noqa: PLC0415
    from harness.headless import seed_globals
    engine = backend.engine
    engine.reset_world()
    seed_globals(args.seed)
    await backend.create_genesis(engine, map_name="family_farm")
    from systems.actions import gameclock, reputation
    gameclock.DAY_TICKS = args.day_ticks
    from systems.actions.agent_driver import driver_of
    from systems.credit import runtime as credit_runtime
    from systems.justice import runtime as justice_runtime
    from systems.labour import runtime as labour_runtime
    from systems.market import runtime as market_runtime
    import genesis_config as cfg
    keys = farm.keys_of(engine)
    names = {uid: key for key, uid in keys.items()}
    started = setup(engine, args)
    driver = driver_of(engine)
    runner = driver.runner(engine)
    services = runner.services
    market, loans, jobs, docket = market_runtime.of(services), credit_runtime.of(services), labour_runtime.of(services), justice_runtime.of(services)
    h = engine.state.h_tensor
    items_start = totals(runner.world)
    peak, dead_at, timeline, last_action = {k: 0.0 for k in keys}, {}, [], {}
    seen = 0
    # Additive diagnostics: the historical digest payload stays unchanged.
    from systems.actions.labour_verbs import wage_for
    hunger_sum = {k: 0.0 for k in keys}
    tail_sum = {k: 0.0 for k in keys}
    tail_peak = {k: 0.0 for k in keys}
    tail_rescues = {k: 0 for k in keys}
    floor_cycle_ticks = {k: 0 for k in keys}
    tier0_rescues = {k: 0 for k in keys}
    previous_hunger = {k: float(h[engine._human_slot_for_id(uid), cfg.HUNGER]) for k, uid in keys.items()}
    wage_capacity_samples = {k: 0 for k in keys}
    tail_ticks = min(1000, args.ticks)
    wage_samples = 0
    from model_server.economy_audit import FoodRationAudit
    with FoodRationAudit(engine, names, driver, args.ticks - tail_ticks) as food_audit:
        for tick in range(args.ticks):
            engine.step()
            if args.shock_at is not None and int(engine.tick) >= args.shock_at:
                market.shock["rations"] = args.shock
            for key, uid in keys.items():
                slot = engine._human_slot_for_id(uid)
                peak[key] = max(peak[key], float(h[slot, cfg.HUNGER]))
                hunger = float(h[slot, cfg.HUNGER])
                hunger_sum[key] += hunger
                if tick >= args.ticks - tail_ticks:
                    tail_sum[key] += hunger
                    tail_peak[key] = max(tail_peak[key], hunger)
                    tail_rescues[key] += int(previous_hunger[key] >= 89.0 and hunger <= 67.0)
                floor_cycle_ticks[key] += int(hunger >= 65.0)
                tier0_rescues[key] += int(previous_hunger[key] >= 89.0 and hunger <= 67.0)
                previous_hunger[key] = hunger
                if float(h[slot, cfg.HP]) <= 0 and key not in dead_at:
                    dead_at[key] = int(engine.tick)
            log = driver.ladder.log
            for entry in log[seen:]:
                if entry["code"] not in ("errand", "errand_expired"):
                    last_action[names.get(entry["actor"], entry["actor"])] = entry["tick"]
            seen = len(log)
            if tick % args.sample == 0:
                wage_samples += 1
                for key, uid in keys.items():
                    wage_capacity_samples[key] += int(bool(wage_for(services, uid)[0]))
                timeline.append(farm.snapshot(engine, keys, int(engine.tick)))
    ledger = runner.world.events
    events = {}
    for event in ledger.events():
        events[event.type] = events.get(event.type, 0) + 1
    ladder_counts = dict(driver.ladder.counts)
    half = args.ticks // 2
    late_actions = sum(1 for e in driver.ladder.log if e["tick"] >= half and e["code"] not in ("errand", "errand_expired"))
    cases = [{"id": c.id, "thief": names.get(c.thief), "victim": names.get(c.victim), "authority": names.get(c.authority), "status": c.status, "outcome": c.outcome} for c in docket.cases.values()]
    loan_rows = [{"id": l.id, "lender": names.get(l.lender), "borrower": names.get(l.borrower), "item": l.item, "qty": l.qty, "status": l.status, "owed": round(l.owed, 2)} for l in loans.loans.values()]
    wage_rows = [{"id": j.id, "employer": names.get(j.employer), "worker": names.get(j.worker), "item": j.item, "qty": j.qty, "status": j.status} for j in jobs.jobs.values()]
    stall = market.stalls.get(STALL)
    stuck = [{"who": names.get(h_id, h_id), "purpose": e.purpose, "target": names.get(e.target, e.target), "expires": e.expires} for h_id, e in driver.ladder.errands.items() if e.expires < int(engine.tick) - 1]
    silent = [k for k, v in peak.items() if v >= args.max_hunger and int(engine.tick) - last_action.get(k, -10 ** 9) > args.silent_window]
    answers = {}
    for e in driver.ladder.log:                          # what the asked residents answered (the verb succeeded; the answer may be a refusal)
        answer = (e.get("op") or {}).get("answer")
        if answer:
            answers[f"{e['verb']}:{answer}"] = answers.get(f"{e['verb']}:{answer}", 0) + 1
    rep = reputation.of(engine)
    items_end = totals(runner.world)
    farm_produced = sum(int(e.payload.get("qty", 0)) for e in ledger.events() if e.type == "farm_harvested")
    result = {
        "seed": args.seed, "ticks": args.ticks, "start": started,
        "peak_hunger": {k: round(v, 1) for k, v in peak.items()}, "dead_at": dead_at,
        "thefts": events.get("theft", 0), "cases": cases, "damages_levied": events.get("damages_levied", 0),
        "loans": {"opened": loans.counts.get("opened", 0), "repaid": loans.counts.get("repaid", 0), "overdue": loans.counts.get("overdue", 0), "defaulted": loans.counts.get("defaulted", 0), "rows": loan_rows},
        "wages": {"hired": jobs.counts.get("hired", 0), "paid": jobs.counts.get("paid", 0), "lapsed": jobs.counts.get("lapsed", 0), "rows": wage_rows},
        "stall": {"sales": len(stall.sales) if stall else 0, "ask_end": market.ask(STALL, "rations"), "factors": market.history[-6:]},
        "ladder_counts": ladder_counts, "answers": answers, "events": events, "reputation": dict(rep.counts),
        "items_start": items_start, "items_end": items_end, "silent_starvation": silent, "stuck_errands": stuck, "late_actions": late_actions, "errors": driver.errors,
        "last_action": last_action, "timeline": timeline[:: max(1, len(timeline) // 30)],
        "balance": {
            "exact_food_ration_calls": food_audit.summary(),
            "rest_routes": {k: v for k, v in driver.routed.items() if "rest" in k},
            "yielded_resident_ticks": driver.yielded,
            "mean_hunger": {k: round(v / max(1, args.ticks), 2) for k, v in hunger_sum.items()},
            "tail_mean_hunger": {k: round(v / max(1, tail_ticks), 2) for k, v in tail_sum.items()},
            "tail_peak_hunger": {k: round(v, 2) for k, v in tail_peak.items()},
            "tail_probable_tier0_rescues": tail_rescues,
            "floor_cycle_ticks_ge65": floor_cycle_ticks,
            "probable_tier0_rescues": tier0_rescues,
            "wage_capacity_samples": wage_capacity_samples, "wage_samples": wage_samples,
            "stall_coin_end": services.inventory(STALL).get("coin", 0),
            "keeper_coin_end": services.inventory(keys[KEEPER]).get("coin", 0),
            "collect_till": {k: v for k, v in driver.routed.items() if k.startswith("market.collect_till:")},
            "declared_farm_crop_bundles": farm_produced,
        },
    }
    result["digest"] = hashlib.sha256(json.dumps({k: result[k] for k in ("peak_hunger", "dead_at", "cases", "loans", "wages", "ladder_counts", "events", "items_end", "timeline", "last_action")},
                                                 sort_keys=True, default=str).encode()).hexdigest()[:16]
    result["verdict"] = verdict(result, args)
    return result


def verdict(r: dict, args) -> dict:
    declared = {"crop_bundle": r.get("balance", {}).get("declared_farm_crop_bundles", 0)}
    created = {k for k in r["items_end"] if r["items_end"][k] > r["items_start"].get(k, 0) + declared.get(k, 0)}
    checks = {
        "nobody_dies": not r["dead_at"],
        "no_silent_starvation": not r["silent_starvation"],
        "no_stuck_errands": not r["stuck_errands"],
        "no_deadlock": r["late_actions"] > 0,
        "coin_conserved": r["items_start"].get("coin") == r["items_end"].get("coin"),
        "nothing_created": not created,
        "no_errors": r["errors"] == 0,
    }
    return {"checks": checks, "pass": all(checks.values()), "created": sorted(created)}


def row(r: dict) -> dict:
    ladder = r["ladder_counts"]
    ok = lambda rung: sum(v for k, v in ladder.items() if k.startswith(rung + ":") and k.endswith(":ok"))      # noqa: E731
    return {"seed": r["seed"], "digest": r["digest"], "dead": len(r["dead_at"]), "peak": max(r["peak_hunger"].values()), "thefts": r["thefts"],
            "cases": len(r["cases"]), "levied": r["damages_levied"], "robbed": r["events"].get("robbery", 0), "fought_off": r["events"].get("robbery_failed", 0), "arrested": r["events"].get("arrested", 0), "loans": r["loans"]["opened"], "repaid": r["loans"]["repaid"], "defaulted": r["loans"]["defaulted"],
            "hired": r["wages"]["hired"], "paid": r["wages"]["paid"], "sales": r["stall"]["sales"], "pass": r["verdict"]["pass"],
            "ok_by_rung": {rung: ok(rung) for rung in ("forage", "work", "buy", "trade", "beg", "borrow", "steal", "rob")}}


def table(rows: list) -> str:
    cols = ("seed", "digest", "dead", "peak", "thefts", "cases", "levied", "robbed", "fought_off", "arrested", "loans", "repaid", "defaulted", "hired", "paid", "sales", "pass")
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--seeds", default="1008,1,2")
    p.add_argument("--seed", type=int, default=1008)
    p.add_argument("--tier1", choices=("rules", "matrix"), default="rules", help="EDEN_AGENT_TIER1 for the agent driver")
    p.add_argument("--rob", action="store_true", help="EDEN_ROB (+ EDEN_DEFEND, EDEN_RESTRAINT): the rob rung, guard posts and arrest")
    p.add_argument("--rungs", default="", help="stress run: only these ladder rungs (comma list, e.g. forage,rob)")
    p.add_argument("--single", action="store_true", help="run one seed in this process")
    p.add_argument("--repeat", action="store_true", help="run the first seed twice (determinism digest)")
    p.add_argument("--ticks", type=int, default=4000)
    p.add_argument("--day-ticks", type=int, default=DAY_TICKS, dest="day_ticks")
    p.add_argument("--needs-scale", type=float, default=1.0, dest="needs_scale")
    p.add_argument("--family-hunger", type=float, default=80.0, dest="family_hunger")
    p.add_argument("--mara-hunger", type=float, default=40.0, dest="mara_hunger")
    p.add_argument("--guard-hunger", type=float, default=70.0, dest="guard_hunger")
    p.add_argument("--keeper-rations", type=int, default=4, dest="keeper_rations", help="rations Orrin carries")
    p.add_argument("--stall-rations", type=int, default=2, dest="stall_rations", help="rations on the stall's shelf")
    p.add_argument("--max-hunger", type=float, default=90.0, dest="max_hunger")
    p.add_argument("--silent-window", type=int, default=800, dest="silent_window")
    p.add_argument("--shock-at", type=int, default=1200, dest="shock_at")
    p.add_argument("--shock", type=float, default=3.0)
    p.add_argument("--sample", type=int, default=50)
    p.add_argument("--json")
    return p


def forward(args) -> list:
    return ["--seed", str(args.seed), "--ticks", str(args.ticks), "--day-ticks", str(args.day_ticks), "--needs-scale", str(args.needs_scale), "--family-hunger", str(args.family_hunger),
            "--guard-hunger", str(args.guard_hunger), "--mara-hunger", str(args.mara_hunger), "--keeper-rations", str(args.keeper_rations), "--stall-rations", str(args.stall_rations), "--max-hunger", str(args.max_hunger), "--silent-window", str(args.silent_window), "--shock-at", str(args.shock_at),
            "--shock", str(args.shock), "--sample", str(args.sample), "--tier1", args.tier1] + (["--rob"] if args.rob else []) + (["--rungs", args.rungs] if args.rungs else [])


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.single:
        result = asyncio.run(run(args))
        if args.json:
            Path(args.json).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        print(json.dumps(row(result), default=str))
        return 0 if result["verdict"]["pass"] else 1
    seeds = [int(s) for s in args.seeds.split(",") if s]
    plan = seeds + ([seeds[0]] if args.repeat else [])
    rows, full = [], []
    for index, seed in enumerate(plan):
        out = Path(tempfile.mkdtemp(prefix="commons-")) / "run.json"
        sub = argparse.Namespace(**{**vars(args), "seed": seed})
        proc = subprocess.run([sys.executable, "-m", "model_server.s1_commons", "--single", "--json", str(out), *forward(sub)], cwd=str(ROOT), capture_output=True, text=True)
        if not out.exists():
            print(f"seed {seed}: no result\n{proc.stdout[-2000:]}\n{proc.stderr[-3000:]}")
            return 2
        data = json.loads(out.read_text(encoding="utf-8"))
        rows.append(row(data))
        full.append(data)
    print(table(rows))
    if args.repeat:
        print(f"\ndeterminism: seed {seeds[0]} digests {rows[0]['digest']} vs {rows[-1]['digest']} -> {'identical' if rows[0]['digest'] == rows[-1]['digest'] else 'DIFFERENT'}")
    for r in rows:
        print(f"seed {r['seed']} ok by rung: {r['ok_by_rung']}")
    for data in full:
        print(f"seed {data['seed']} answers: {data['answers']}")
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows, "runs": full}, indent=1, default=str), encoding="utf-8")
    failed = [r for r in rows if not r["pass"]]
    return 1 if failed or (args.repeat and rows[0]["digest"] != rows[-1]["digest"]) else 0


if __name__ == "__main__":
    sys.exit(main())
