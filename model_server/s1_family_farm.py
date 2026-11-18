"""S-1 family_farm scenario (R5 deliverable B): a hungry family, a rich neighbour, and the escalation ladder + reputation over N ticks.

    .venv/Scripts/python.exe -m model_server.s1_family_farm --variant steal --ticks 3000 --json out.json

The map is the authored ``family_farm`` (farm + two interiors). Five residents: ``family_mara`` (mother, high conscience), ``family_tomas`` (father, low
conscience, very protective), ``family_lina`` (youngest, 16), ``neighbour_orrin`` and ``neighbour_elsa`` (merciful, well stocked). Household = the prefix of
the roster key, and of the entity ids (``family:pantry``, ``neighbour:pantry``, ``family_interior:storage``). Scarcity is applied by the scenario, not
the map: the family's pantry and its pack are emptied, the family starts hungry, and the *variant* decides which rungs of the ladder work:

* ``forage``: the far bushes are alive (the ladder forages; nobody trades, begs or steals);
* ``trade``: no bush stock, the family holds coin (a fair trade is accepted);
* ``beg``: no stock, no coin (the merciful neighbour gives);
* ``steal``: no stock, no coin, the neighbours distrust the family (begging and trading are refused): the ladder reaches the neighbour's pantry.
* ``market`` (``EDEN_MARKET=1``): the family has coin and no food; Orrin keeps a stall (his pantry, stocked) and reprices it from the day's scarcity; the ladder's ``buy``
  rung pays the stall's price. ``--shock-at T --shock F`` multiplies the day's demand for rations from tick T (a panic / blight), ``--day-ticks N`` shortens the game day.

Pass criteria (``verdict``): nobody dies; no *unexplained* starvation (every resident whose hunger passes ``--max-hunger`` has ledger/audit events that
explain it); the ladder acted (rung counts); the expected rung fired for the variant; with ``--reputation`` a witnessed or discovered theft produced the
opinion drop, the ``thief`` tag and gossip. The digest of the timeline is deterministic for a seed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_NAMES = ("family_farm", "family_home_interior", "neighbour_home_interior")
MAP_ORIGINS = {"family_home_interior": [600, 0], "neighbour_home_interior": [600, 340]}
CARRIED = {"rations": 4, "crop_bundle": 2}      # what a neighbour carries on the person (a pantry is not asked: respond_to_request reads the pack)
VARIANTS = ("forage", "trade", "beg", "steal", "market")
STALL = "neighbour:pantry"        # the market variant: the neighbour's pantry is its stall (a storage entity registered with the market)
STALL_STOCK = {"rations": 4}
MARKET_DAY_TICKS = 600           # the scenario runs short days so a few thousand ticks hold several daily price updates
KEEPER = "neighbour_orrin"

TRAITS = {
    "family_mara": {"mercy": 0.85, "loyalty": 0.85, "discipline": 0.75, "deceitfulness": 0.1, "greed": 0.2, "aggression": 0.1, "protectiveness": 0.8,
                    "caution": 0.5, "pride": 0.4},
    "family_tomas": {"mercy": 0.3, "loyalty": 0.5, "discipline": 0.3, "deceitfulness": 0.6, "greed": 0.6, "aggression": 0.4, "protectiveness": 0.9,
                     "caution": 0.3, "pride": 0.3, "vengefulness": 0.3},
    "family_lina": {"mercy": 0.6, "loyalty": 0.6, "discipline": 0.4, "deceitfulness": 0.2, "greed": 0.3, "aggression": 0.1, "protectiveness": 0.3},
    "neighbour_orrin": {"mercy": 0.6, "loyalty": 0.7, "discipline": 0.7, "deceitfulness": 0.1, "greed": 0.3, "aggression": 0.2, "protectiveness": 0.6,
                        "caution": 0.7, "pride": 0.5, "sociability": 0.7},
    "neighbour_elsa": {"mercy": 0.8, "loyalty": 0.7, "discipline": 0.5, "deceitfulness": 0.1, "greed": 0.2, "aggression": 0.1, "protectiveness": 0.6,
                       "caution": 0.5, "pride": 0.3, "sociability": 0.8, "vengefulness": 0.1},
}


def roster(variant: str, needs_scale: float) -> dict:
    def person(key, name, sex, age, role, anchors, personal=None, stock=None):
        return {"key": key, "name": name, "sex": sex, "age": age, "role": role, "archetype": "stoic_survivor", "traits": TRAITS[key], "anchors": anchors,
                "stock": stock or {}, "personal": personal or {}, "inventory": {"slots": 16, "weight": 60.0}, "work_mode": "anchor_only", "needs_sites": False}
    coin = {"coin": 12} if variant in ("trade", "market") else {}
    return {"map_id": "family_farm", "needs_scale": needs_scale, "age_scale": 0.0,
            "needs": {"threshold": 30, "ration": 25, "water": {"anchor": "family:well_use", "ticks": 30}, "food": {"anchor": None, "ticks": 60}},
            "residents": [      # one work / talk / home anchor per resident (the roster validator forbids sharing); the roles match the anchors' for_role
                person("family_mara", "Mara", 1, 34, "gatherer", {"spawn": "family:spawn", "work": "family:plot_1_work", "talk": "family:talk_trade",
                                                                  "home": "family:door_anchor", "sleep": "family_interior:sleep_1"}, coin),
                person("family_tomas", "Tomas", 0, 38, "gatherer", {"spawn": "family:spawn", "work": "family:wood_use", "talk": "family_interior:talk",
                                                                    "sleep": "family_interior:sleep_2"}),
                person("family_lina", "Lina", 1, 16, "gatherer", {"spawn": "family:spawn", "work": "family:pantry_use", "sleep": "family_interior:sleep_3"}),
                person("neighbour_orrin", "Orrin", 0, 52, "gatherer", {"spawn": "neighbour:spawn", "work": "neighbour:plot_1_work",
                                                                       "talk": "neighbour_interior:talk", "home": "neighbour:door_anchor",
                                                                       "sleep": "neighbour_interior:sleep_1"}, stock=CARRIED),
                person("neighbour_elsa", "Elsa", 1, 47, "gatherer", {"spawn": "neighbour:spawn", "work": "neighbour:plot_2_work",
                                                                     "sleep": "neighbour_interior:sleep_2"}, stock=CARRIED),
            ]}


def configure(variant: str, needs_scale: float, data_root: Path | None = None) -> Path:
    """Environment for the farm world (before ``map_test`` is imported)."""
    data_root = Path(data_root or tempfile.mkdtemp(prefix="eden-s1farm-"))
    roster_dir = data_root / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (roster_dir / "family_farm.json").write_text(json.dumps(roster(variant, needs_scale), indent=1), encoding="utf-8")
    os.environ.update(
        EDEN_PROFILE="gameplay", EDEN_DATA_ROOT=str(data_root), EDEN_MAP="family_farm", EDEN_EMBEDDINGS="lexical", EDEN_ROSTER_DIR=str(roster_dir),
        EDEN_MAP_FILES=os.pathsep.join(str(ROOT / "world_data" / "maps2d" / f"{name}.json") for name in MAP_NAMES),
        EDEN_MAP_ORIGINS=json.dumps(MAP_ORIGINS), EDEN_MAP_RESOURCES="1", EDEN_ROSTER_DRIVER="agent")
    for path in (str(ROOT), str(ROOT / "at_the_beginning")):
        if path not in sys.path:
            sys.path.insert(0, path)
    return data_root


async def boot(variant: str, seed: int, needs_scale: float = 0.05):
    configure(variant, needs_scale)
    import map_test as backend  # noqa: PLC0415 - after configure()
    from harness.headless import seed_globals
    engine = backend.engine
    engine.reset_world()
    seed_globals(seed)
    await backend.create_genesis(engine, map_name="family_farm")
    return backend, engine


def keys_of(engine) -> dict:
    return {engine.resident_store.get(u)["roster"]["key"]: u for u in engine._human_uid_by_slot if u}


def scarcity(engine, variant: str, family_hunger: float = 55.0) -> dict:
    """Make the family hungry and poor; the variant decides which rungs can work. Returns what was set (for the report)."""
    import genesis_config as cfg
    from systems.roster.driver import roster_of
    keys = keys_of(engine)
    h = engine.state.h_tensor
    for key, uid in keys.items():
        record = engine.resident_store.get(uid)
        record["roster"]["driver"] = "agent"
        engine.resident_store.touch_resident(uid)
    for key in ("family_mara", "family_tomas", "family_lina"):
        h[engine._human_slot_for_id(keys[key]), cfg.HUNGER] = family_hunger
    relations = []
    pairs = [(a, b, "family") for a in ("family_mara", "family_tomas", "family_lina") for b in ("family_mara", "family_tomas", "family_lina") if a != b]
    pairs += [(a, b, "neighbour") for a in ("family_mara", "family_tomas") for b in ("neighbour_orrin", "neighbour_elsa")]
    pairs += [(b, a, "neighbour") for a, b, _ in list(pairs) if _ == "neighbour"]
    closeness = -0.5 if variant == "steal" else 0.25
    for a, b, kind in pairs:
        engine.resident_store.update_relationship(keys[a], keys[b], kind, 0.4 if kind == "family" else closeness, 0)
        relations.append((a, b, kind))
    return {"family_hunger": family_hunger, "relations": len(relations)}


def setup_world(engine, variant: str) -> dict:
    """Empty the family's storage of food, stop the bushes for the variants that must not forage, and make the neighbours' attitude to the family."""
    import genesis_config as cfg
    from harness import effects as fx
    from harness.adapter import EngineWorld
    world = EngineWorld(engine, seed=0)
    removed = {}
    for entity in ("family:pantry", "family_interior:storage"):
        for item in ("rations", "crop_bundle", "fish_catch", "berries", "mushrooms"):
            have = world.items.quantity(entity, item)
            if have:
                report = world.apply([fx.Transfer(item, have, entity, None)], atomic=True, cause="scenario:scarcity",
                                     items=fx.ItemPermit(consume={item: have}))
                removed[f"{entity}:{item}"] = have if report.ok else -1
    table = world.table("entities")
    if variant != "forage":
        for node in ("family:bush_far_1", "family:bush_far_2", "family:bush_far_3"):
            slot = table.slot_of(node)
            if slot is not None:
                for column in ("food", "node_stock", "growth_rate"):          # no stock and no regrowth: a blight
                    if column in table.columns:
                        table.tensor[slot, table.columns[column]] = 0.0
    market = {}
    if variant == "market":
        stocked = {}
        for item, qty in STALL_STOCK.items():
            report = world.apply([fx.Transfer(item, qty, None, STALL)], atomic=True, cause="scenario:stall", items=fx.ItemPermit(produce={item: qty}))
            stocked[item] = qty if report.ok else -1
        from systems.market import runtime
        from systems.actions.agent_driver import driver_of
        runtime.register_stall(driver_of(engine).runner(engine).services, STALL)
        for uid in engine._human_uid_by_slot:
            record = engine.resident_store.get(uid) if uid else None
            if record and record["roster"]["key"] == KEEPER:
                record["roster"]["stall"] = STALL
                engine.resident_store.touch_resident(uid)
        market = {"stall": STALL, "stocked": stocked, "keeper": KEEPER}
    return {"removed": removed, "market": market}


def snapshot(engine, keys: dict, tick: int) -> dict:
    import genesis_config as cfg
    h = engine.state.h_tensor
    out = {}
    for key, uid in keys.items():
        slot = engine._human_slot_for_id(uid)
        out[key] = {"x": round(float(h[slot, cfg.X]), 1), "y": round(float(h[slot, cfg.Y]), 1), "hunger": round(float(h[slot, cfg.HUNGER]), 2),
                    "thirst": round(float(h[slot, cfg.THIRST]), 2), "hp": round(float(h[slot, cfg.HP]), 2)}
    return {"tick": tick, "residents": out}


def attach_tier3(engine, mode: str):
    """The mock model server (clean, no faults) and a plane whose resident role is ``mode`` (shadow | on); the escalation sweep drives this plane.
    Returns ``(plane, server process)``. The other roles stay off: this acceptance is about the resident plan path."""
    from model_server import gate_a
    from simulation.dispatch import DISPATCH
    from systems.modelplane.tier3.escalation import install
    proc, url = gate_a.spawn_server([])
    plane, _service = gate_a.configure_plane(engine, url, "off", lambda: engine.tick / 20.0)
    plane.set_modes(tier3_resident=mode)
    engine.__dict__["_model_plane"] = plane
    install(DISPATCH, plane)
    return plane, proc


async def run(args) -> dict:
    os.environ["EDEN_AGENT_ACTIONS"] = "1"
    os.environ["EDEN_AGENT_LADDER"] = "0" if args.no_ladder else "1"
    os.environ["EDEN_REPUTATION"] = "1" if args.reputation else "0"
    os.environ["EDEN_AGENT_TIER1"] = args.tier1
    os.environ["EDEN_MARKET"] = "1" if args.variant == "market" else "0"
    for flag in ("EDEN_CREDIT", "EDEN_LABOUR", "EDEN_JUSTICE"):          # these variants test the older rungs: the newer ones (s1_commons) stay out unless asked
        os.environ[flag] = "0"
    backend, engine = await boot(args.variant, args.seed, args.needs_scale)
    if args.variant == "market":
        from systems.actions import gameclock
        gameclock.DAY_TICKS = args.day_ticks or MARKET_DAY_TICKS
    from systems.actions.agent_driver import driver_of
    from systems.actions import reputation
    keys = keys_of(engine)
    names = {uid: key for key, uid in keys.items()}
    started = scarcity(engine, args.variant, args.family_hunger)
    started.update(setup_world(engine, args.variant))
    driver = driver_of(engine)
    plane = server = None
    if args.tier3 != "off":
        plane, server = attach_tier3(engine, args.tier3)
    timeline, peak = [], {key: 0.0 for key in keys}
    market_book = coin_days = None
    if args.variant == "market":
        from systems.market import runtime as market_runtime
        market_book, coin_days = market_runtime.of(driver.runner(engine).services), []
        coin_start = int(driver.runner(engine).world.items.total("coin"))
    import genesis_config as cfg
    h = engine.state.h_tensor
    dead_at = {}
    for tick in range(args.ticks):
        engine.step()
        if market_book is not None:
            if args.shock_at is not None and int(engine.tick) >= args.shock_at:
                market_book.shock["rations"] = args.shock
            if tick % args.sample == 0:
                coin_days.append({"tick": int(engine.tick), "coin_total": int(driver.runner(engine).world.items.total("coin")),
                                  "ask_rations": market_book.ask(STALL, "rations"), "factor": market_book.f("rations"),
                                  "stall_rations": driver.runner(engine).services.inventory(STALL).get("rations", 0),
                                  "till": driver.runner(engine).services.inventory(STALL).get("coin", 0)})
        if plane is not None:
            plane.pump()
        for key, uid in keys.items():
            slot = engine._human_slot_for_id(uid)
            peak[key] = max(peak[key], float(h[slot, cfg.HUNGER]))
            if float(h[slot, cfg.HP]) <= 0 and key not in dead_at:
                dead_at[key] = int(engine.tick)
        if tick % args.sample == 0:
            timeline.append(snapshot(engine, keys, int(engine.tick)))
    runner = driver.runner(engine)
    ledger = runner.world.events
    types = {}
    for event in ledger.events():
        types[event.type] = types.get(event.type, 0) + 1
    rep = reputation.of(engine)
    relations = {}
    for a, ua in keys.items():
        record = engine.resident_store.get(ua) or {}
        for b, ub in keys.items():
            relation = (record.get("relationships") or {}).get(ub)
            if relation and a != b:
                relations[f"{a}->{b}"] = {"kind": relation.get("kind"), "closeness": relation.get("closeness"), "tags": relation.get("tags")}
    pantry = {entity: dict(runner.services.inventory(entity)) for entity in ("family:pantry", "neighbour:pantry")}
    result = {"variant": args.variant, "seed": args.seed, "ticks": args.ticks, "flags": {"ladder": not args.no_ladder, "reputation": args.reputation, "tier1": args.tier1, "tier3": args.tier3},
              "start": started, "peak_hunger": {k: round(v, 2) for k, v in peak.items()}, "dead_at": dead_at,
              "ladder": {"counts": dict(driver.ladder.counts), "log": [{**e, "actor": names.get(e["actor"], e["actor"])} for e in driver.ladder.log]},
              "routed": dict(driver.routed), "events": types,
              "reputation": {"counts": dict(rep.counts), "log": [{k: (names.get(v, v) if isinstance(v, str) else v) for k, v in e.items()} for e in rep.log]},
              "relations": relations, "pantry_end": pantry, "errors": driver.errors, "timeline": timeline[:: max(1, len(timeline) // 40)]}
    if plane is not None:
        plane.pump()
        escalator_runner = plane.escalator._ctx[1][3] if plane.escalator._ctx[1] else None      # the sweep's own runner: its audit holds the Tier 3 plan steps
        result["tier3"] = {"mode": args.tier3, "escalation": plane.escalator.status(), "resident": plane.status().get("tier3", {}),
                           "plan_audit": [dict(e) for e in list(escalator_runner.audit.entries)[:20]] if escalator_runner else []}
        plane.close()
        server.terminate()
    if market_book is not None:
        stall = market_book.stalls.get(STALL)
        result["market"] = {"stall": STALL, "coin_start": coin_start, "coin_end": int(runner.world.items.total("coin")), "days": coin_days[:: max(1, len(coin_days) // 40)],
                            "factors": market_book.history, "shock_at": args.shock_at, "shock": args.shock if args.shock_at is not None else None,
                            "sales": [{"tick": x.tick, "who": names.get(x.who, x.who), "item": x.item, "qty": x.qty, "price": x.price, "kind": x.kind} for x in (stall.sales if stall else [])],
                            "ask_end": market_book.ask(STALL, "rations"), "log": driver.market_log}
    result["digest"] = hashlib.sha256(json.dumps({k: result[k] for k in ("peak_hunger", "dead_at", "ladder", "events", "reputation", "relations", "pantry_end", "timeline") + (("market",) if "market" in result else ())},
                                                 sort_keys=True, default=str).encode()).hexdigest()[:16]
    result["verdict"] = verdict(result, args)
    return result


def verdict(result: dict, args) -> dict:
    """The S-1 acceptance checks (names are stable; the numbers are reported whatever they are)."""
    counts = result["ladder"]["counts"]
    acted = {rung: sum(v for k, v in counts.items() if k.startswith(rung + ":") and not k.endswith(("errand", "errand_expired"))) for rung in ("forage", "buy", "trade", "beg", "steal")}
    ok_codes = {rung: counts.get(f"{rung}:ok", 0) for rung in acted}
    explained = {key for entry in result["ladder"]["log"] for key in [entry["actor"]]}
    family = ("family_mara", "family_tomas", "family_lina")
    unexplained = [k for k in family if result["peak_hunger"][k] >= args.max_hunger and k not in explained]
    expected = {"forage": "forage", "trade": "trade", "beg": "beg", "steal": "steal", "market": "buy"}[result["variant"]]
    checks = {
        "nobody_dies": not result["dead_at"],
        "no_unexplained_starvation": not unexplained,
        "ladder_acted": any(acted.values()),
        "expected_rung_succeeded": ok_codes[expected] > 0,
        "no_errors": result["errors"] == 0,
    }
    if result["variant"] == "trade":
        checks["traded_event"] = result["events"].get("traded", 0) > 0
    if result["variant"] == "market":
        market, sales = result["market"], [x for x in result["market"]["sales"] if x["kind"] == "buy"]
        checks["bought_event"] = result["events"].get("bought", 0) > 0
        checks["no_theft_while_affordable"] = result["events"].get("theft", 0) == 0
        checks["coin_conserved"] = market["coin_start"] == market["coin_end"]
        checks["paid_the_stall_price"] = bool(sales) and all(x["price"] >= 1 for x in sales)
        if market["shock_at"] is not None:
            before = [x["price"] for x in sales if x["tick"] < market["shock_at"]]
            after = [x["price"] for x in sales if x["tick"] >= market["shock_at"]]
            shock_day = market["shock_at"] // (args.day_ticks or MARKET_DAY_TICKS)
            pre = [x["factors"].get("rations", 1.0) for x in market["factors"] if x["day"] <= shock_day]
            checks["price_rose_after_shock"] = bool(pre) and market["factors"][-1]["factors"].get("rations", 1.0) > pre[-1]
            checks["bought_less_after_shock"] = (not after) or len(after) <= len(before) or sum(x["qty"] for x in after) <= sum(x["qty"] for x in before)
    if result["variant"] == "steal":
        checks["theft_event"] = result["events"].get("theft", 0) > 0
        if result["flags"]["reputation"]:
            rep = result["reputation"]["counts"]
            checks["loss_discovered"] = result["events"].get("loss_discovered", 0) > 0
            checks["opinion_drop_if_known"] = rep.get("opinion_drop", 0) > 0 or rep.get("discovered", 0) == rep.get("theft", 0) - rep.get("unknown", 0)
    return {"checks": checks, "acted": acted, "succeeded": ok_codes, "unexplained": unexplained, "pass": all(checks.values())}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--variant", choices=VARIANTS, default="steal")
    p.add_argument("--ticks", type=int, default=3000)
    p.add_argument("--seed", type=int, default=1008)
    p.add_argument("--needs-scale", type=float, default=1.0, dest="needs_scale")
    p.add_argument("--family-hunger", type=float, default=40.0, dest="family_hunger")
    p.add_argument("--max-hunger", type=float, default=90.0, dest="max_hunger")
    p.add_argument("--sample", type=int, default=50)
    p.add_argument("--reputation", action="store_true")
    p.add_argument("--no-ladder", action="store_true")
    p.add_argument("--tier1", choices=("rules", "matrix"), default="rules", help="EDEN_AGENT_TIER1 for the agent driver")
    p.add_argument("--tier3", choices=("off", "shadow", "on"), default="off", help="resident role against the mock model server (needs gate_a's server spawn)")
    p.add_argument("--day-ticks", type=int, default=0, dest="day_ticks", help="market variant: ticks in a game day (default %d)" % MARKET_DAY_TICKS)
    p.add_argument("--shock-at", type=int, default=None, dest="shock_at", help="market variant: from this tick the day's demand for rations is multiplied by --shock")
    p.add_argument("--shock", type=float, default=3.0)
    p.add_argument("--json")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    result = asyncio.run(run(args))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    brief = {k: result[k] for k in ("variant", "flags", "peak_hunger", "dead_at", "events", "digest", "verdict")}
    brief["ladder_counts"], brief["reputation_counts"] = result["ladder"]["counts"], result["reputation"]["counts"]
    print(json.dumps(brief, indent=1, default=str))
    return 0 if result["verdict"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
