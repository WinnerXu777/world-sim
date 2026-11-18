"""Winter scenario for EDEN_TEMPERATURE (1008_instincts_wiring_gap.md step 2 balance gate): the roster village over a winter, as a table row.

    .venv/Scripts/python.exe tools/winter_probe.py --calendar legacy|user [--ticks N] [--seed 1] [--temperature on|off]

Boots the real starter village (``harness.headless``), starts the clock at the first tick of winter and steps. ``--calendar user`` sets EDEN_CALENDAR=1 (a 12000-tick day, a
96000-tick year: winter is the last quarter, 24000 ticks); ``legacy`` is the 2400-tick day with the 600-tick year (a 150-tick winter, repeating). Prints one JSON line:
residents, deaths, deaths while cold, hp lost to cold, resident-ticks under the comfort band / past the damage line / of those sheltered, the mean felt cold, and the final
mean stamina and mood of the survivors. Fuel, fires and clothing have no mechanism yet (the light_fire verb and the item class are model-plane work): the row says so.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--calendar", choices=("legacy", "user"), default="legacy")
parser.add_argument("--ticks", type=int, default=0)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--temperature", choices=("on", "off"), default="on")
parser.add_argument("--spaces", action="store_true", help="EDEN_SPACES=1 + EDEN_PERCEPTION_BOUNDED=1: interiors are spaces, so a resident inside the cottage or smithy counts as sheltered")
args = parser.parse_args()
if args.calendar == "user":
    os.environ["EDEN_CALENDAR"] = "1"
if args.spaces:
    os.environ.update(EDEN_SPACES="1", EDEN_PERCEPTION_BOUNDED="1")
if args.temperature == "on":
    os.environ["EDEN_TEMPERATURE"] = "1"
sys.path.insert(0, str(ROOT / "at_the_beginning"))
import asyncio  # noqa: E402

from harness.headless import boot_engine, configure_environment  # noqa: E402


async def main() -> dict:
    configure_environment()
    from harness import calendar, temperature
    backend, engine = await boot_engine(args.seed)
    import genesis_config as cfg
    import torch
    cal = calendar.active()
    winter_start = int(cal.year_ticks * 3 / 4)
    ticks = args.ticks or (int(cal.year_ticks / 4) if args.calendar == "user" else 2400)
    engine.tick = winter_start
    h = engine.state.h_tensor
    alive0 = int(((h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.HP] > 0)).sum())
    deaths = deaths_cold = 0
    prev_alive = alive0
    cold_sum = n_cold = 0.0
    for _ in range(ticks):
        engine.step()
        state = temperature.state_of(engine)
        live = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.HP] > 0)
        alive = int(live.sum())
        if state is not None and live.any():
            cold_sum += float(state["cold"][live].sum())
            n_cold += float(live.sum())
        if alive < prev_alive:
            deaths += prev_alive - alive
            if state is not None and float(state["cold"].max()) > temperature.HP_DAMAGE_FROM:
                deaths_cold += prev_alive - alive
        prev_alive = alive
    live = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.HP] > 0)
    totals = engine.__dict__.get("_temperature_totals", {})
    return {"calendar": args.calendar, "spaces": args.spaces, "temperature": args.temperature, "ticks": ticks, "start_tick": winter_start, "residents": alive0, "alive_at_end": int(live.sum()),
            "deaths": deaths, "deaths_with_a_damaging_cold_present": deaths_cold, "hp_lost_to_cold": round(totals.get("hp", 0.0), 1),
            "resident_ticks_cold": totals.get("cold_ticks", 0), "resident_ticks_damaging": totals.get("damaging_ticks", 0),
            "resident_ticks_cold_sheltered": totals.get("sheltered_cold_ticks", 0), "mean_cold_degrees": round(cold_sum / max(n_cold, 1.0), 3),
            "survivor_mean_stamina": round(float(h[live, cfg.H_STAMINA].mean()), 1) if live.any() else None,
            "survivor_mean_mood": round(float(h[live, cfg.MOOD].mean()), 1) if live.any() else None,
            "fires_lit": 0, "clothing": "no mechanism yet"}


print(json.dumps(asyncio.run(main())))
