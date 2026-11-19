"""F3 diagnosis probe (sheep/boar decline after R0.3): attribute every animal death in the creature balance run to a cause.

    .venv/Scripts/python.exe tools/f3_animal_deaths.py [creature_balance.py args, e.g. --days 10 --brain kernel --calendar user --seed 1]
                                                       [--json balance.json] --deaths-json f3.json

Runs ``tools/creature_balance.py`` unchanged (same village, residents, brains, calendar and per-day table) and only observes: after every
``kernel.step`` it reads the live animal rows (uid, species, HP, age, life expectancy, hunger, thirst, sex) and the ``creature_killed``
events. Engine files are not touched; nothing is written but the two JSON files.

Per animal uid it records arrival (initial / spawned by the plan / born / restored from the creature store) and departure:
* ``killed:<species>`` / ``killed:human`` - a ``creature_killed`` event names the killer uid;
* ``old_age`` - its age passed its life expectancy (the legacy ``animal_instinct_die`` age rule; snapshots round the age to 4 places, so the
  test allows two ticks of ageing plus the rounding: F3-1 found 14 old-age deaths tagged ``vanished`` without it);
* ``starvation`` / ``thirst`` / ``attack_unattributed`` - HP reached 0; the cause is the largest share of the HP it lost in its last
  ``WINDOW`` ticks, split by the starvation and dehydration rules (hunger or thirst >= 90) and the rest (attacks);
* ``old_age_stored`` - it was stashed in the creature store (its chunk left the window) and the store's catch-up found it past its life;
* ``stashed`` (not a death) - its chunk left the window; it is counted with the store's records;
* ``vanished`` - gone with HP > 0, not past its life and not in the store (reported with its last snapshot).

Breeding (F3-2): per species, the ticks mature females spent ``ready`` (cooldown 0: only a male within the mate radius is missing), ``held`` by the
kernel (cooldown pinned at ``kernel.hold_cooldown()`` this tick, float32 tolerance; ``held_hungry`` when her hunger is above ``kernel.BREED_HUNGER_MAX``, else the crowded
pasture rule) or ``recovering`` (any other cooldown: after a birth).
"""
from __future__ import annotations

import argparse
import json
import re
import time
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

extra = argparse.ArgumentParser(add_help=False)
extra.add_argument("--deaths-json", required=True)
EXTRA, PASS_ON = extra.parse_known_args()
sys.argv = [sys.argv[0]] + PASS_ON                         # creature_balance parses its own arguments at import

import tools.creature_balance as cb  # noqa: E402

cfg, kernel, table = cb.cfg, cb.kernel, cb.table
from harness import calendar as _calendar  # noqa: E402

FAUNA = re.compile(r"^c-?\d+_-?\d+:fauna:")
NAMES = {row["id"]: name for name, row in table.CREATURES.items()}
WINDOW = 200                                               # ticks of HP history behind an HP death
COLS = (cfg.M_TYPE, cfg.M_HP, cfg.A_AGE, cfg.A_LIFE_EXP, cfg.A_HUNGER, cfg.A_THIRST, cfg.A_SEX)
AGE_SLACK = 1e-4                                           # the snapshot's 4-place age rounding (both values rounded: 2 x 0.00005)


class Tracker:
    def __init__(self):
        self.prev: dict = {}                               # uid -> snapshot dict
        self.history: dict = defaultdict(lambda: deque(maxlen=WINDOW))   # uid -> per-tick (starve, thirst, other) HP loss
        self.stashed: dict = {}                            # uid -> last snapshot
        self.seen: set = set()
        self.species_of: dict = {}
        self.killed: dict = {}                             # uid -> killer uid (or None)
        self.arrivals, self.departures, self.initial = [], [], []
        self.engine = None
        self.tick = 0
        self.observe_seconds = 0.0
        self.active = False                                # set by the balance run's first feed(), right before its tick loop
        self.breeding: dict = defaultdict(Counter)         # species -> female-tick counts (mature_female, ready, held, held_hungry, recovering)

    def hook(self, engine):
        self.engine = engine
        inner = engine._queue_event

        def spy(kind, *args, **kw):
            if kind == "creature_killed" and args:
                self.killed[args[0]] = kw.get("killer_uid")
            return inner(kind, *args, **kw)
        engine._queue_event = spy

    def snapshot(self, engine) -> dict:
        m = engine.state.m_tensor[:cfg.MAX_ENTITIES]
        types = m[:, cfg.M_TYPE]
        mask = (types >= 40) & (types < 80) & (m[:, cfg.M_SPACE] == 0)
        slots = mask.nonzero().flatten().tolist()
        if not slots:
            return {}
        rows = m[slots][:, list(COLS)].tolist()
        uids = engine._entity_uid_by_slot
        out = {}
        for slot, (t, hp, age, life, hunger, thirst, sex) in zip(slots, rows):
            uid = uids[slot]
            if uid is None:
                uid = f"slot{slot}:{int(t)}"
            out[uid] = {"slot": slot, "species": NAMES.get(int(t), int(t)), "hp": round(hp, 3), "age": round(age, 4), "life_exp": round(life, 4),
                        "hunger": round(hunger, 2), "thirst": round(thirst, 2), "sex": int(sex), "tick": self.tick}
        return out

    def observe(self, engine):
        if not self.active:
            return
        if self.engine is None:
            self.hook(engine)
        self.tick += 1
        cur = self.snapshot(engine)
        index = self._store_index()
        if self.tick == 1:
            for uid, snap in cur.items():
                self.initial.append({"uid": uid, **snap})
        self.count_breeding(engine)
        starve = self.starve = 1.5 * _calendar.rate_scale("starvation")
        dry = self.dry = cfg.THIRST_DAMAGE_RATE * _calendar.rate_scale("damage_recovery")
        for uid, snap in cur.items():
            self.species_of[uid] = snap["species"]
            before = self.prev.get(uid)
            if before is None:
                if uid in self.stashed:
                    self.stashed.pop(uid)
                    kind = "restored"
                elif uid in self.seen:
                    kind = "reappeared"
                elif self.tick == 1:
                    kind = "initial"
                else:
                    kind = "spawned" if FAUNA.match(uid) else "born"
                self.seen.add(uid)
                if kind != "initial":
                    self.arrivals.append({"kind": kind, "uid": uid, **snap})
                continue
            loss = max(0.0, before["hp"] - snap["hp"])
            s = min(loss, starve) if snap["hunger"] >= 90.0 else 0.0
            d = min(loss - s, dry) if snap["thirst"] >= 90.0 else 0.0
            self.history[uid].append((s, d, loss - s - d))
        for uid, before in self.prev.items():
            if uid in cur:
                continue
            if uid in index:
                self.stashed[uid] = before
                self.departures.append({"kind": "stashed", "uid": uid, **before, "gone_tick": self.tick})
                continue
            self.departures.append({"kind": "death", "cause": self.cause(uid, before), "uid": uid, **before, "gone_tick": self.tick,
                                    "hp_loss_last_window": [round(sum(x[k] for x in self.history[uid]), 2) for k in range(3)]})
            self.history.pop(uid, None)
        for uid in [u for u in self.stashed if u not in index and u not in cur]:
            before = self.stashed.pop(uid)
            self.departures.append({"kind": "death", "cause": "old_age_stored", "uid": uid, **before, "gone_tick": self.tick})
        self.prev = cur

    def count_breeding(self, engine):
        m = engine.state.m_tensor[:cfg.MAX_ENTITIES]
        types = m[:, cfg.M_TYPE]
        fem = ((types >= 40) & (types < 80) & (m[:, cfg.M_SPACE] == 0) & (m[:, cfg.M_HP] > 0) & (m[:, cfg.A_SEX] == 1.0)
               & (m[:, cfg.A_AGE] >= cfg.ANIMAL_MATURE_TICKS))
        if not bool(fem.any()):
            return
        t, cd, hunger = types[fem], m[fem, cfg.A_COOLDOWN], m[fem, cfg.A_HUNGER]
        hold = kernel.hold_cooldown() if hasattr(kernel, "hold_cooldown") else float(kernel.HOLD_COOLDOWN)   # F3-4 scales the hold to the calendar
        held = (cd - hold).abs() <= 1e-6 * max(1.0, hold)
        hungry = held & (hunger > kernel.BREED_HUNGER_MAX)
        for sid in t.unique().tolist():
            mine = t == sid
            c = self.breeding[NAMES.get(int(sid), int(sid))]
            n, ready, h, hh = int(mine.sum()), int((mine & (cd <= 0.0)).sum()), int((mine & held).sum()), int((mine & hungry).sum())
            c["mature_female"] += n
            c["ready"] += ready
            c["held"] += h
            c["held_hungry"] += hh
            c["recovering"] += n - ready - h

    def _store_index(self) -> set:
        manager = getattr(self, "manager", None)
        return set(manager.creatures.index) if manager is not None else set()

    def cause(self, uid, before) -> str:
        if uid in self.killed and self.killed[uid]:
            killer = self.killed[uid]
            humans = set(u for u in self.engine._human_uid_by_slot if u)
            if killer in humans or str(killer).startswith("h_"):
                return "killed:human"
            return f"killed:{self.species_of.get(killer, 'unknown')}"
        if before["age"] + 2.0 * _calendar.age_step() + AGE_SLACK > before["life_exp"]:
            return "old_age"
        parts = [sum(x[k] for x in self.history[uid]) for k in range(3)]
        # the needs rules and the legacy death rule run in the same engine.step, so a row killed by hunger or thirst is zeroed before it is
        # seen at HP 0: an HP death is also a row that was losing HP and had no more than its next tick's expected loss left
        expected = (self.starve if before["hunger"] >= 90.0 else 0.0) + (self.dry if before["thirst"] >= 90.0 else 0.0)
        if before["hp"] <= 0.0 or uid in self.killed or (expected > 0.0 and before["hp"] <= expected + 1e-6):
            if max(parts) <= 0.0:
                return "attack_unattributed"
            return ("starvation", "thirst", "attack_unattributed")[parts.index(max(parts))]
        return "vanished"


TRACKER = Tracker()
_original_step = kernel.step


def _step(engine):
    n = _original_step(engine)
    began = time.perf_counter()
    TRACKER.observe(engine)
    TRACKER.observe_seconds += time.perf_counter() - began
    return n


cb.kernel.step = _step
_original_run = cb.Balance.test_run


async def _run(self):
    TRACKER.manager = self.manager
    feed = self.feed

    def first_feed():
        TRACKER.active = True                              # the run's start: the rows now present are the initial population
        self.feed = feed
        return feed()
    self.feed = first_feed
    return await _original_run(self)


cb.Balance.test_run = _run


def summarise() -> dict:
    deaths = [d for d in TRACKER.departures if d["kind"] == "death"]
    out = {"args": PASS_ON, "calendar": {"day_ticks": cb.DAY, "life_year_ticks": _calendar.active().life_year_ticks,
                                         "year_ticks": _calendar.active().year_ticks, "age_step_per_tick": _calendar.age_step(),
                                         "mature_life_years": cfg.ANIMAL_MATURE_TICKS,
                                         "birth_recovery_life_years": _calendar.active().year_ticks / _calendar.active().life_year_ticks},
           "ticks_observed": TRACKER.tick, "observe_seconds": round(TRACKER.observe_seconds, 1), "species": {}}
    for name in sorted({d["species"] for d in deaths} | {a["species"] for a in TRACKER.arrivals} | {i["species"] for i in TRACKER.initial}):
        mine = [d for d in deaths if d["species"] == name]
        init = [i for i in TRACKER.initial if i["species"] == name]
        out["species"][name] = {
            "initial": len(init),
            "initial_age_life": sorted([[i["age"], i["life_exp"], i["sex"]] for i in init]),
            "arrivals": dict(Counter(a["kind"] for a in TRACKER.arrivals if a["species"] == name)),
            "deaths_by_cause": dict(Counter(d["cause"] for d in mine)),
            "deaths": [{k: d.get(k) for k in ("uid", "cause", "gone_tick", "age", "life_exp", "hp", "hunger", "thirst", "sex", "hp_loss_last_window")} for d in mine],
            "births": [{k: a[k] for k in ("uid", "tick", "sex", "life_exp")} for a in TRACKER.arrivals if a["species"] == name and a["kind"] == "born"],
            "stashed_events": sum(1 for d in TRACKER.departures if d["kind"] == "stashed" and d["species"] == name),
            "end_live": sum(1 for s in TRACKER.prev.values() if s["species"] == name),
            "end_stored": sum(1 for s in TRACKER.stashed.values() if s["species"] == name),
            "breeding_female_ticks": dict(TRACKER.breeding.get(name, {})),
        }
    store = getattr(TRACKER, "manager", None)
    out["store_counters"] = dict(store.creatures.counters) if store is not None else None
    return out


if __name__ == "__main__":
    suite = cb.unittest.defaultTestLoader.loadTestsFromTestCase(cb.Balance)
    outcome = cb.unittest.TextTestRunner(verbosity=0).run(suite)
    if cb.ARGS.json:
        Path(cb.ARGS.json).write_text(json.dumps(cb.RESULT, indent=1), encoding="utf-8")
    Path(EXTRA.deaths_json).write_text(json.dumps(summarise(), indent=1), encoding="utf-8")
    print(json.dumps({n: {k: v[k] for k in ("initial", "arrivals", "deaths_by_cause", "end_live", "end_stored")} for n, v in summarise()["species"].items()}), flush=True)
    sys.exit(0 if outcome.wasSuccessful() else 1)
