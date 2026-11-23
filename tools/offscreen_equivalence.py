"""R6.5 calibration and equivalence probe for the offscreen coarse model (harness/offscreen.py, plan 1119wsimimplementation-plan-R6.5.md step 6).

    .venv/Scripts/python.exe tools/offscreen_equivalence.py [--days 5] [--calendar legacy|user] [--seed 1] [--no-roster] [--start-hungry [60]] [--json out.json]
        [--map starter_village|playable_village|...] [--warmup-days 1]
    .venv/Scripts/python.exe tools/offscreen_equivalence.py --pool run1.json run2.json ...      (no run: pool the fits)

Boots the real engine headlessly (``harness/headless.py``: the starter village with its roster, no window, so every resident is active), takes the
residents and the food rows at the start, then runs ``engine.step()`` for ``--days`` game days, sampling every ``--sample`` ticks:
population, mean hunger and thirst of the live residents, the food stock of the start's food rows, and every death (a uid whose row is gone).
At the end it runs ``offscreen.coarse_ticks`` from the start values over the same ticks and prints both side by side:

* the measured set points for ``CATCH_UP_V2`` (``hunger_fed``, ``thirst_watered``): the active means over the second half of the run;
* population, mean hunger and thirst, food stock and deaths at the end, active versus coarse.

``--no-roster`` (births, D3): the same village without its roster (``EDEN_ROSTER_DIR`` points at an empty folder inside the run's temporary
data root, never in the repo), so it lives by the normal mating rule; a roster world has no births. The run counts **births** (uids that
appear, checked every tick) and **ready mother-days** (every ``--ready-every`` ticks: live women, ``H_SEX`` 1, that pass the engine's own
``_slot_ready_for_mating`` while at least one man does too), and estimates the birth chance per ready mother-day as births over ready
mother-days, printed with its count basis next to ``BIRTH_P_PER_READY_DAY``. The coarse run then uses that estimate (births allowed).

``--start-hungry [V]`` (default 60): after the warm-up steps every live resident's hunger and thirst are set to ``V``, so the run shows
where an active village brings them back to (a steady state, if it has one) instead of a slow rise from 0.

``--map`` (R65-CAL) boots another map the same way (a built-in one such as ``playable_village``: no roster, a well, grass and a forest,
4 villagers), so the fed and watered set points of non-roster residents can be measured; roster residents never use them (dormancy_gap
section 9). Every run also writes ``fit``: per need, every live resident's value in every sample after ``--warmup-days``, pooled (mean,
p10 / p50 / p90, the means of the first and second half, ``steady`` when those differ by at most max(1, 10%)); the births chance gets its
exact Poisson 95% interval (``p_95``). ``--pool`` pools the fits of several runs into the calibrated values.

A heavy run (minutes per game day on the legacy calendar's 2400-tick day): run it in an archive extract, under the ``suite`` lease, one process.
Nothing under Data_Storage is touched (headless.configure_environment uses a temporary data root).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--days", type=float, default=5.0)
parser.add_argument("--calendar", choices=("legacy", "user"), default="legacy")
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--sample", type=int, default=100, help="ticks between samples")
parser.add_argument("--ready-every", type=int, default=10, help="ticks between readiness counts (--no-roster)")
parser.add_argument("--no-roster", action="store_true", help="run the village without its roster, by the normal mating rule (births)")
parser.add_argument("--start-hungry", type=float, nargs="?", const=60.0, default=None,
                    help="set every resident's hunger and thirst to this value (default 60) before the run")
parser.add_argument("--json", default="")
parser.add_argument("--map", default="starter_village",
                    help="the map to boot (R65-CAL: playable_village, a built-in non-roster village with a well, grass and a forest)")
parser.add_argument("--warmup-days", type=float, default=1.0, help="the steady-state fit uses the samples after this many game days")
parser.add_argument("--pool", nargs="+", default=None, metavar="JSON",
                    help="no run: pool the fits of earlier --json outputs into the calibrated values (set points, births chance)")

DEFAULT_MAP = "starter_village"


def environment_for(args) -> dict:
    """The EDEN_* variables a run sets on top of headless.configure_environment (empty for the 1119 runs: starter village, legacy)."""
    env = {}
    if args.map != DEFAULT_MAP:
        env["EDEN_MAP"] = args.map
    if args.calendar == "user":
        env["EDEN_CALENDAR"] = "1"
    return env


def steady_fit(samples, key, after_tick) -> dict:
    """The set point of one need: every live resident's value in every sample after ``after_tick``, pooled. Steady when the means of the
    first and the second half of those samples (in time) differ by at most max(1, 10% of the mean)."""
    kept = [s for s in samples if s["tick"] > after_tick and s.get(key)]
    values = [v for s in kept for v in s[key]]
    if not values:
        return {"n": 0, "mean": None, "p10": None, "p50": None, "p90": None, "first_half_mean": None, "second_half_mean": None,
                "steady": False, "values": []}
    ordered = sorted(values)

    def at(q):
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

    def mean_of(part):
        vals = [v for s in part for v in s[key]]
        return sum(vals) / len(vals) if vals else None
    half = len(kept) // 2
    first, second = mean_of(kept[:half]), mean_of(kept[half:])
    mean = sum(values) / len(values)
    steady = first is not None and second is not None and abs(first - second) <= max(1.0, 0.1 * abs(mean))
    return {"n": len(values), "mean": mean, "p10": at(0.1), "p50": at(0.5), "p90": at(0.9), "first_half_mean": first,
            "second_half_mean": second, "steady": steady, "values": values}


def _poisson_cdf(k: int, mu: float) -> float:
    term = total = math.exp(-mu)
    for i in range(1, k + 1):
        term *= mu / i
        total += term
    return total


def _solve(f, lo: float, hi: float) -> float:
    """f is increasing on [lo, hi] with f(lo) < 0 < f(hi): bisection to 1e-9."""
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if f(mid) < 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return (lo + hi) / 2.0


def poisson_interval(k: int, exposure: float, alpha: float = 0.05) -> tuple:
    """The exact (Garwood) two-sided interval of a Poisson rate: k events over ``exposure`` (here ready mother-days)."""
    if exposure <= 0:
        return None, None
    top = 10.0 * (k + 10)
    low = 0.0 if k == 0 else _solve(lambda mu: (1.0 - _poisson_cdf(k - 1, mu)) - alpha / 2.0, 0.0, top)
    high = _solve(lambda mu: alpha / 2.0 - _poisson_cdf(k, mu), 0.0, top)
    return low / exposure, high / exposure


def pooled_fit(results) -> dict:
    """The calibrated values from several runs: set points = the mean of every pooled sample value; births chance = births over ready
    mother-days, with its exact 95% interval."""
    hungers = [v for r in results for v in r["fit"]["hungers"]["values"]]
    thirsts = [v for r in results for v in r["fit"]["thirsts"]["values"]]
    births = sum(int(r["births"]["active"]) for r in results)
    days = sum(float(r["births"]["ready_mother_days"]) for r in results)
    return {"runs": len(results), "hunger_fed": sum(hungers) / len(hungers) if hungers else None,
            "thirst_watered": sum(thirsts) / len(thirsts) if thirsts else None, "samples": [len(hungers), len(thirsts)],
            "births": births, "ready_mother_days": days, "birth_p": births / days if days > 0 else None,
            "birth_p_95": poisson_interval(births, days)}


def ready_counts(engine, cfg, rows):
    """(ready women, ready men) among the live rows, by the engine's own readiness rule."""
    h = engine.state.h_tensor
    women = sum(1 for s in rows.values() if float(h[s, cfg.H_SEX]) == 1.0 and engine._slot_ready_for_mating(s))
    men = sum(1 for s in rows.values() if float(h[s, cfg.H_SEX]) != 1.0 and engine._slot_ready_for_mating(s))
    return women, men


def live_rows(engine, cfg):
    h = engine.state.h_tensor
    return {engine._human_uid_by_slot[s]: s for s in range(h.shape[0])
            if float(h[s, cfg.TYPE]) == float(cfg.AGENT_TYPE_HUMAN) and engine._human_uid_by_slot[s]}


async def run(args) -> dict:
    from harness import headless
    data_root = headless.configure_environment()
    if args.no_roster:
        empty = Path(data_root) / "empty_rosters"                                # in the run's temporary data root, never in the repo
        empty.mkdir(parents=True, exist_ok=True)
        os.environ["EDEN_ROSTER_DIR"] = str(empty)
    os.environ.update(environment_for(args))                                  # before map_test is imported: it reads them at import
    if args.map == DEFAULT_MAP:
        backend, engine = await headless.boot_engine(args.seed)
    else:                                                                       # headless.boot_engine with another map (R65-CAL)
        import map_test as backend
        engine = backend.engine
        engine.reset_world()
        headless.seed_globals(args.seed)
        await backend.create_genesis(engine, map_name=args.map)
    import genesis_config as cfg
    from harness import offscreen
    for _ in range(3):                                                         # let the id sync give every row a uid
        engine.step()
    h = engine.state.h_tensor
    start_rows = live_rows(engine, cfg)
    if args.start_hungry is not None:
        for slot in start_rows.values():
            h[slot, cfg.HUNGER] = h[slot, cfg.THIRST] = float(args.start_hungry)
    needs, ages = offscreen._scales(engine, h)
    people = [offscreen.resident_for(engine, h, slot, uid, needs, ages) for uid, slot in sorted(start_rows.items())]   # with the roster loop
    points = {uid: (float(h[slot, cfg.X]), float(h[slot, cfg.Y])) for uid, slot in start_rows.items()}
    cells = set().union(*(offscreen.cells_of(p, offscreen._home_of(engine, uid)) for uid, p in points.items())) if points else set()
    foods = offscreen.foods_for(engine, cells)
    rates = offscreen.Rates.current()
    ticks = int(round(args.days * rates.day_ticks))
    from systems.roster.apply import world_has_roster
    roster_world = bool(world_has_roster(engine))
    samples, deaths, began = [], [], time.time()
    alive = set(start_rows)
    seen = set(start_rows)
    births, ready_women_ticks, ready_checks = [], 0.0, 0
    for t in range(1, ticks + 1):
        engine.step()
        for uid in engine._human_uid_by_slot:
            if uid and uid not in seen:
                seen.add(uid)
                births.append({"uid": uid, "tick": t})
        if not roster_world and t % args.ready_every == 0:                    # --no-roster, or a map without a roster (playable_village)
            women, men = ready_counts(engine, cfg, live_rows(engine, cfg))
            ready_checks += 1
            if men:
                ready_women_ticks += women * args.ready_every
        if t % args.sample == 0 or t == ticks:
            rows = live_rows(engine, cfg)
            gone = sorted(alive - set(rows))
            for uid in gone:
                deaths.append({"uid": uid, "tick": t})
            alive = set(rows) & alive
            hs = [float(h[s, cfg.HUNGER]) for s in rows.values()]
            ts = [float(h[s, cfg.THIRST]) for s in rows.values()]
            stock = sum(float(engine.state.m_tensor[int(f.key), cfg.M_RESOURCE_FOOD]) for f in foods)
            samples.append({"tick": t, "population": len(rows), "hungers": [round(v, 4) for v in hs], "thirsts": [round(v, 4) for v in ts],
                            "hunger": sum(hs) / len(hs) if hs else None,
                            "thirst": sum(ts) / len(ts) if ts else None, "food_stock": stock})
            print(json.dumps({k: v for k, v in samples[-1].items() if k not in ("hungers", "thirsts")}), flush=True)
    half = [s for s in samples if s["tick"] > ticks / 2 and s["hunger"] is not None]
    ready_mother_days = ready_women_ticks / float(rates.day_ticks)
    p_measured = len(births) / ready_mother_days if ready_mother_days > 0 else None
    warm = int(round(args.warmup_days * rates.day_ticks))
    fit = {"after_tick": warm, "hungers": steady_fit(samples, "hungers", warm), "thirsts": steady_fit(samples, "thirsts", warm)}
    coarse = offscreen.coarse_ticks(people, foods, ticks, rates, births_allowed=not roster_world, birth_p=p_measured or 0.0,
                                    seed=args.seed)
    survivors = [r for r in coarse.residents.values() if r.alive]
    end = samples[-1] if samples else {}
    end_rows = live_rows(engine, cfg)
    per_resident = {uid: {"active": [round(float(h[s, cfg.HUNGER]), 3), round(float(h[s, cfg.THIRST]), 3)],
                          "coarse": [round(coarse.residents[uid].hunger, 3), round(coarse.residents[uid].thirst, 3)]
                          if uid in coarse.residents else None,
                          "loops": [coarse.residents[uid].hunger_loop, coarse.residents[uid].thirst_loop] if uid in coarse.residents else None}
                    for uid, s in sorted(end_rows.items())}
    result = {
        "args": vars(args), "ticks": ticks, "seconds": round(time.time() - began, 1), "residents_at_start": len(people), "food_rows": len(foods),
        "measured_set_points": {"hunger_fed": sum(s["hunger"] for s in half) / len(half) if half else None,
                                "thirst_watered": sum(s["thirst"] for s in half) / len(half) if half else None},
        "active_end": {"population": end.get("population"), "hunger": end.get("hunger"), "thirst": end.get("thirst"),
                       "food_stock": end.get("food_stock"), "deaths": deaths},
        "coarse_end": {"population": len(survivors), "hunger": sum(r.hunger for r in survivors) / len(survivors) if survivors else None,
                       "thirst": sum(r.thirst for r in survivors) / len(survivors) if survivors else None,
                       "food_stock": sum(coarse.foods.values()), "deaths": [{"uid": u, "day": d, "cause": c} for u, d, c in coarse.deaths]},
        "roster_world": roster_world,
        "per_resident_end": per_resident,
        "births": {"active": len(births), "ready_mother_days": round(ready_mother_days, 3), "readiness_checks": ready_checks,
                   "p_measured": p_measured, "basis": f"{len(births)} births / {ready_mother_days:.2f} ready mother-days",
                   "p_95": poisson_interval(len(births), ready_mother_days),
                   "p_placeholder": offscreen.BIRTH_P_PER_READY_DAY, "coarse_births_at_p_measured": len(coarse.births),
                   "active_list": births},
        "set_points_used": {k: offscreen.CATCH_UP_V2[k] for k in ("hunger_fed", "thirst_watered", "calibrated")},
        "fit": fit,
        "samples": samples,
    }
    return result


def _without_values(fit: dict) -> dict:
    return {k: ({kk: vv for kk, vv in v.items() if kk != "values"} if isinstance(v, dict) else v) for k, v in fit.items()}


def main() -> int:
    args = parser.parse_args()
    if args.pool:
        print(json.dumps(pooled_fit([json.loads(Path(f).read_text(encoding="utf-8")) for f in args.pool]), indent=2))
        return 0
    result = asyncio.run(run(args))
    text = json.dumps({k: (_without_values(v) if k == "fit" else v) for k, v in result.items() if k != "samples"}, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
