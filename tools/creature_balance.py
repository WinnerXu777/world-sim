"""Creature balance probe (1008_creatures_gap.md section 8, decision CREATURE-KERNEL: "tune after seeing numbers in a village scenario").

    .venv/Scripts/python.exe tools/creature_balance.py [--days 10] [--humans 6] [--brain legacy|kernel] [--calendar legacy|user] [--seed 1] [--json out.json]

The real window engine (seed 1008, the starter village pinned) with the creature plan on (EDEN_CREATURES=1): ``--humans`` residents stand about the village, fed and watered every tick,
with a fixed random walk of their own from the legacy instincts; the whole legacy registry runs (``engine.step``), then the window and the kernel. Reported per game day: the
population of every creature species, the damage the residents took and from what, and the deaths (a resident who dies is put back at full health and counted). ``--brain kernel`` switches
sheep, deer and wolf to ``brain: table`` for the run (the numbers of the table are the ones the legacy species already have, plus packs/territory); ``legacy`` leaves them on the
legacy loops. The residents here do not fight back: casualties are an upper bound for a village without hunters; ``duels`` prints the time-to-kill of each hostile species against a
resident with the legacy ``ATTACK_DAMAGE`` so the 'hunters can win' question has numbers.
Needs the tests directory on the path for the window fixture; nothing under Data_Storage is touched.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "at_the_beginning"))

parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=10)
parser.add_argument("--humans", type=int, default=6)
parser.add_argument("--brain", choices=("legacy", "kernel"), default="legacy")
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--json", default="")
parser.add_argument("--start-tick", type=int, default=0, help="set the clock to this tick before the run (user calendar: 72000 = the first tick of winter)")
parser.add_argument("--calendar", choices=("legacy", "user"), default="legacy", help="user = EDEN_CALENDAR=1: a 12000-tick day and one life-year per day (the legacy life-year is 600 ticks: four per day)")
ARGS, REST = parser.parse_known_args()
if ARGS.calendar == "user":
    os.environ["EDEN_CALENDAR"] = "1"
RESULT: dict = {}

from test_creatures_kernel import KernelFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
import torch  # noqa: E402
from systems.creatures import kernel, table  # noqa: E402
from tools.creature_balance_attribution import AttributionObserver  # noqa: E402

DAY = 12000 if ARGS.calendar == "user" else 2400
KERNEL_BRAIN = ("sheep", "deer", "wolf")
LEGACY_NAMES = {row["id"]: name for name, row in table.CREATURES.items()}


def species_counts(m, store=None) -> dict:
    """Live creature rows plus, with ``store``, the creatures kept in the store's records (not in any integrated chunk): a creature that walked off the window is not dead."""
    types = m[:cfg.MAX_ENTITIES, cfg.M_TYPE]
    live = (m[:cfg.MAX_ENTITIES, cfg.M_HP] > 0) & (m[:cfg.MAX_ENTITIES, cfg.M_SPACE] == 0)
    stored = {}
    if store is not None:
        for items in store.records.values():
            for record in items:
                stored[int(record["type"])] = stored.get(int(record["type"]), 0) + 1
    out = {}
    for name, row in table.CREATURES.items():
        n = int(((types == float(row["id"])) & live).sum()) + stored.get(row["id"], 0)
        if n:
            out[name] = n
    return out


class Balance(KernelFixture):
    async def test_run(self):
        engine = self.engine
        engine.world_loaded = True
        torch.manual_seed(ARGS.seed)
        saved = {name: table.CREATURES[name]["brain"] for name in KERNEL_BRAIN}
        if ARGS.brain == "kernel":
            for name in KERNEL_BRAIN:
                table.CREATURES[name]["brain"] = "table"
        self.addCleanup(lambda: [table.CREATURES[name].__setitem__("brain", brain) for name, brain in saved.items()])

        # Reversible causal attribution observer
        self.observer = AttributionObserver(engine=engine, humans_count=ARGS.humans)
        self.observer.install()
        self.addCleanup(self.observer.uninstall)

        events = []
        original = engine._queue_event

        def spy(kind, *args, **kw):
            if kind == "creature_killed":
                events.append(kw.get("species"))
            return original(kind, *args, **kw)
        engine._queue_event = spy
        h = engine.state.h_tensor
        centre = (520.0, 520.0)
        for i in range(ARGS.humans):
            self.human(i, centre[0] + 12.0 * (i % 3), centre[1] + 12.0 * (i // 3))
            self.observer.on_human_reset(i)
        self.run_ticks(26)                                       # integrates the 5 x 5 ring: the plan fills the creature rows
        self.feed()
        day_rows, lost_total, deaths_total = [], 0.0, 0
        before = species_counts(engine.state.m_tensor, self.manager.creatures)
        print(f"start: {before}", flush=True)
        if ARGS.start_tick:
            engine.tick = ARGS.start_tick
        hp_prev = h[:ARGS.humans, cfg.HP].clone()
        lost_day, deaths_day = 0.0, 0
        first_deaths = []
        kills_seen = 0
        for tick in range(1, ARGS.days * DAY + 1):
            self.observer.set_probe_tick(tick)
            engine.step()
            self.manager.tick()
            kernel.step(engine)

            # Capture pre-feed resident state and detect deaths BEFORE existing reset operations
            hp = h[:ARGS.humans, cfg.HP]
            drop = (hp_prev - hp).clamp(min=0.0)
            lost_day += float(drop.sum())

            # Detect dead residents using the actual pre-reset tensor values
            dead_residents = []
            for i in range(ARGS.humans):
                if float(h[i, cfg.TYPE]) != float(cfg.AGENT_TYPE_HUMAN) or float(hp[i]) <= 0.0:
                    dead_residents.append(i)

            # Observe deaths using the actual pre-feed needs, age, and HP state
            for i in dead_residents:
                deaths_day += 1
                death_desc = self.describe_death(i, tick, float(hp_prev[i]))
                if len(first_deaths) < 8:
                    first_deaths.append(death_desc)
                    print("DEATH", first_deaths[-1], flush=True)
                self.human(i, centre[0] + 12.0 * (i % 3), centre[1] + 12.0 * (i // 3))
                self.observer.on_human_reset(i)

            # Feed resident rows every tick: existing harness semantics
            # (needs, stamina and age reset every tick so deaths measure creature combat pressure)
            self.feed()
            hp_prev = h[:ARGS.humans, cfg.HP].clone()
            if tick % DAY == 0:
                counts = species_counts(engine.state.m_tensor, self.manager.creatures)
                kills = events[kills_seen:]
                kills_seen = len(events)
                day = tick // DAY
                row = {"day": day, "population": counts, "hp_lost": round(lost_day, 1), "deaths": deaths_day, "creature_kills": {s: kills.count(s) for s in sorted(set(kills))}}
                day_rows.append(row)
                lost_total += lost_day
                deaths_total += deaths_day
                lost_day, deaths_day = 0.0, 0
                m = engine.state.m_tensor[:cfg.MAX_ENTITIES]
                live = (m[:, cfg.M_HP] > 0) & (m[:, cfg.M_SPACE] == 0) & (m[:, cfg.M_TYPE] >= 40) & (m[:, cfg.M_TYPE] < 80)
                stored = sum(len(items) for items in self.manager.creatures.records.values())
                row["live"], row["stored"] = int(live.sum()), stored
                if bool(live.any()):
                    row["mean_hunger"], row["mean_thirst"] = round(float(m[live, cfg.A_HUNGER].mean()), 1), round(float(m[live, cfg.A_THIRST].mean()), 1)
                print(f"       live {row['live']} stored {stored} hunger {row.get('mean_hunger')} thirst {row.get('mean_thirst')}", flush=True)
                print(f"day {day:2d}: {counts} | hp lost {row['hp_lost']:6.1f} deaths {row['deaths']} | kills {row['creature_kills']}", flush=True)
        attribution_summary = self.observer.summary()
        RESULT.update(
            first_deaths=first_deaths,
            brain=ARGS.brain,
            calendar=ARGS.calendar,
            days=ARGS.days,
            humans=ARGS.humans,
            start=before,
            per_day=day_rows,
            hp_lost=round(lost_total, 1),
            deaths=deaths_total,
            duels=duels(),
            duels_formula_estimates=duels(),
            duels_note="Closed-form formula estimates from table numbers; residents do not fight back in this probe.",
            feed_semantics="harness_fed_every_tick (needs/age/stamina reset every tick so deaths measure creature combat pressure)",
            attribution=attribution_summary,
        )
        print(json.dumps({k: RESULT[k] for k in ("brain", "hp_lost", "deaths", "attribution") if k in RESULT}), flush=True)

    def describe_death(self, i, tick, hp_before) -> dict:
        """True causal death attribution: instruments ordered damage and lethal blow rather than nearest-creature inference."""
        if hasattr(self, "observer") and self.observer is not None:
            return self.observer.describe_death(i, tick, hp_before)
        m = self.engine.state.m_tensor[:cfg.MAX_ENTITIES]
        h = self.engine.state.h_tensor
        out = {
            "tick": self.engine.tick,
            "probe_tick": tick,
            "hp_before": round(hp_before, 1),
            "type_now": float(h[i, cfg.TYPE]),
            "hunger": round(float(h[i, cfg.HUNGER]), 1),
            "thirst": round(float(h[i, cfg.THIRST]), 1),
            "age": round(float(h[i, cfg.H_AGE]), 1),
        }
        live = (m[:, cfg.M_HP] > 0) & (m[:, cfg.M_SPACE] == 0) & (m[:, cfg.M_TYPE] >= 40) & (m[:, cfg.M_TYPE] < 80)
        if bool(live.any()):
            d = ((m[:, cfg.CX] - h[i, cfg.X]) ** 2 + (m[:, cfg.CY] - h[i, cfg.Y]) ** 2).sqrt()
            d = torch.where(live, d, torch.full_like(d, float("inf")))
            k = int(d.argmin())
            out["nearest_creature"] = [LEGACY_NAMES.get(int(m[k, cfg.M_TYPE]), int(m[k, cfg.M_TYPE])), round(float(d[k]), 1)]
        return out

    def feed(self):
        """Reset resident needs, stamina, and age every tick (existing harness semantics).

        NOTE: This probe measures human casualty rate in a starter village without hunters.
        Residents are fed, watered, and rested every tick so that deaths measure creature
        combat pressure rather than starvation, thirst, or old age.
        """
        h = self.engine.state.h_tensor
        for i in range(ARGS.humans):
            h[i, cfg.HUNGER] = 20.0
            h[i, cfg.THIRST] = 20.0
            h[i, cfg.H_STAMINA] = 100.0
            h[i, cfg.H_AGE], h[i, cfg.H_LIFE_EXP], h[i, cfg.H_STRENGTH] = 30.0, 80.0, 50.0


def duels() -> list:
    """Formula estimates (at 20 Hz): closed-form time-to-kill estimates from creature table numbers and ATTACK_DAMAGE.

    NOTE: These are formula estimates derived from table stats, NOT simulated agent duels.
    Residents in this probe do not fight back; these numbers estimate hunter viability if simulated.
    """
    out = []
    hp_human = 100.0
    for name, row in table.CREATURES.items():
        if row["damage"] <= 0 or not (row["hostile"] or name in ("wolf", "tiger")):
            continue
        hits_to_kill = row["hp"] / cfg.ATTACK_DAMAGE
        kills_human = hp_human / row["damage"] * row["cooldown"] / cfg.TICK_RATE_HZ
        out.append({"species": name, "hp": row["hp"], "hunter_seconds_to_kill": round(hits_to_kill, 1), "creature_seconds_to_kill_resident": round(kills_human, 1),
                    "creature_dps": round(row["damage"] / max(row["cooldown"] / cfg.TICK_RATE_HZ, 1e-6), 1),
                    "estimate_type": "closed_form_formula"})
    return out



if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Balance)
    outcome = unittest.TextTestRunner(verbosity=0).run(suite)
    if ARGS.json:
        Path(ARGS.json).write_text(json.dumps(RESULT, indent=1), encoding="utf-8")
    sys.exit(0 if outcome.wasSuccessful() else 1)
