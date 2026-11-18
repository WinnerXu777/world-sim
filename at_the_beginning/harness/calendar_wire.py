"""1008 calendar C4 (1008_calendar_gap.md section 6): what the calendar adds to the wire. Everything here is empty unless ``EDEN_CALENDAR=1``, so a flag-off payload has exactly
its old key set (the strict goldens do not see it).

``world_block(engine)``: the key ``/bootstrap`` ``world`` gains, ``calendar = {enabled, profile, day_ticks, year_ticks, days_per_year, season_ticks, daylight, ticks_per_second,
life_year_ticks}`` (``calendar.describe``). ``time_block(engine)``: the key a ``/frame`` gains, ``time = {tick, day, day_phase, block, season, season_phase, year, light}`` for the
engine's tick (``calendar.now``): ``day`` and ``year`` are whole indices from 0, the phases are in [0, 1), ``light`` in [0, 1] (the sun's curve; 0.05 at night). The existing
``world.ticks_per_year`` and the frame's ``year`` keep their meaning and carry the new values when the flag is on.
"""
from __future__ import annotations

from . import calendar

PHASE_DIGITS = 4


def world_block(engine) -> dict:
    if not calendar.calendar_enabled():
        return {}
    return {"calendar": calendar.describe()}


def time_block(engine) -> dict:
    if not calendar.calendar_enabled():
        return {}
    moment = calendar.now(int(engine.tick))
    return {"time": {"tick": moment.tick, "day": moment.day_index, "day_phase": round(moment.day_phase, PHASE_DIGITS), "block": moment.block, "season": moment.season,
                     "season_phase": round(moment.season_phase, PHASE_DIGITS), "year": moment.year, "light": round(moment.light, PHASE_DIGITS)}}
