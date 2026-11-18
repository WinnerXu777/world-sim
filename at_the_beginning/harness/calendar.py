"""1008 calendar (design: ``1008_calendar_gap.md``): the day, the night, the seasons, ageing and the per-class rate multipliers.

Pure functions of the tick: no engine state, no torch, no RNG, so everything here is origin-invariant, restart-safe and identical in a
shadow replay. Two profiles share one interface:

* ``LEGACY``: what the tree does today. A day is 2400 ticks cut into four equal blocks, a year is 600 ticks cut into quarters, a
  life-year is a year. Every function returns, bit for bit, what ``weather.season_for_tick``, ``schedule.resolver.tick_to_time_block``
  and ``1 / TICKS_PER_YEAR`` return (the flag-off path calls through these accessors, so the strict golden is the proof).
* ``USER``: a day is 12000 ticks (10 real minutes at 20 ticks per second), a year is 8 days (96000 ticks), a season is 2 days (24000
  ticks). The sun is up for 0.42 to 0.58 of the day depending on the season; ``dawn`` and ``dusk`` are the first and the last 500
  ticks of that time, ``day`` is what lies between them, ``night`` is the rest of the day. A life-year is ``1 / CALENDAR_LIFE_YEARS_PER_DAY``
  game days (decided in USER-DEC-4: one life-year per game day, so adulthood at 18 is 3 hours of play).

``active()`` is ``USER`` when ``EDEN_CALENDAR=1`` (read at call time) and ``LEGACY`` otherwise. Nothing in the tree calls this module yet
(step C0); the accessors replace the readers in step C1.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional

FLAG = "EDEN_CALENDAR"
TICKS_PER_SECOND = 20

SEASONS = ("spring", "summer", "autumn", "winter")
BLOCKS = ("dawn", "day", "dusk", "night")          # the same four names and order as ``schedule.catalog.TIME_BLOCKS``

LEGACY_DAY_TICKS = 2400                            # ``schedule.resolver.DEFAULT_DAY_LENGTH_TICKS``
LEGACY_YEAR_TICKS = 600                            # ``genesis_config.TICKS_PER_YEAR``
USER_DAY_TICKS = 12000
USER_DAYS_PER_YEAR = 8
DAWN_TICKS = USER_DAY_TICKS // 24                  # 500: dawn and dusk each
DAYLIGHT = {"spring": 0.50, "summer": 0.58, "autumn": 0.50, "winter": 0.42}   # fraction of the day with the sun up
LIGHT_FLOOR = 0.05                                 # moon and stars: the light level at night and at the instant of sunrise and sunset
LIGHT_SHAPE = 0.5                                  # exponent of the daytime sine: a quick dawn, a long bright middle
PERCEPTION_DARK_FRACTION = 0.4                     # C3: the share of its scan radius a resident keeps in full darkness (light 0)

CALENDAR_LIFE_YEARS_PER_DAY = 1.0                  # USER-DEC-4: 18 life-years = 18 game days = 3 hours of play

# Starting values (proposals from the design, section 4); the survival scenario tunes them. A class not listed is a typo and raises.
# Applied by the code that owns the constant: ``rate * rate_scale(class)``. 1.0 with the flag off.
RATE_MULTIPLIERS = {
    "needs": 0.21,               # hunger and thirst ticks, animals included: 0 to the seek threshold in ~0.4 day (hunger), ~0.25 day (thirst)
    "damage_recovery": 0.2,      # thirst damage, healing, mood recovery, infection spread / damage / decay: wounds take hours, fevers a day
    "starvation": 0.0015,        # hunger damage once hunger >= 90: no food at all kills on game day 3 to 4 (hunger passes 90 at ~0.7 day, then 100 HP at 0.003 per tick)
    "regrow": 0.2,               # resource and node regrow, lake and well refill, farm water use: about 1 to 2 days
    "farm_growth": 0.04,         # a crop ripens over a season (2 days)
    "weather": 30.0,             # weather spell length: 60..110 ticks becomes 1800..3300 (0.15 to 0.3 day)
    "action": 1.0,               # movement, verb cooldowns, task timeouts, fire burn ticks, attack ranges: real time, unchanged
}


def calendar_enabled() -> bool:
    """1008 calendar: read at call time (bare and package imports share the environment); default off."""
    return os.environ.get(FLAG, "") == "1"


@dataclass(frozen=True)
class Moment:
    """Everything the calendar knows about one tick."""
    tick: int
    day_index: int
    tick_of_day: int
    day_phase: float            # [0, 1)
    block: str
    season: str
    season_phase: float         # [0, 1) progress inside the season
    year: int
    year_phase: float           # [0, 1)
    light: float                # [0, 1]


@dataclass(frozen=True)
class Calendar:
    name: str
    day_ticks: int
    year_ticks: int
    life_year_ticks: float              # ticks per life-year (ageing is decoupled from the calendar year, design section 5)
    daylight: Optional[tuple] = None    # ((season, fraction), ...) or None: four equal blocks, no light curve (LEGACY)

    def __post_init__(self):
        if not (isinstance(self.day_ticks, int) and isinstance(self.year_ticks, int) and self.day_ticks >= 4 and self.year_ticks >= 4):
            raise ValueError("day_ticks and year_ticks must be integers of at least 4")
        if not (math.isfinite(self.life_year_ticks) and self.life_year_ticks > 0):
            raise ValueError("life_year_ticks must be finite and positive")
        if self.daylight is not None:
            table = dict(self.daylight)
            if set(table) != set(SEASONS) or not all(0.0 < float(f) < 1.0 for f in table.values()):
                raise ValueError("daylight needs a fraction in (0, 1) for each of the four seasons")
            if min(table.values()) * self.day_ticks < 2 * DAWN_TICKS + 1:
                raise ValueError("the shortest day must be longer than dawn plus dusk")

    # -- time ------------------------------------------------------------------------------------------------------------
    @property
    def season_ticks(self) -> float:
        return self.year_ticks / 4.0

    @property
    def days_per_year(self) -> float:
        return self.year_ticks / self.day_ticks

    def season_for_tick(self, tick) -> str:
        """Quarters of the year; the expression is ``weather.season_for_tick`` verbatim."""
        phase = (float(tick) % float(self.year_ticks)) / float(self.year_ticks)
        if phase < 0.25:
            return "spring"
        if phase < 0.50:
            return "summer"
        if phase < 0.75:
            return "autumn"
        return "winter"

    def sun_up_ticks(self, season: str) -> int:
        """Ticks of the day (from tick 0 of the day) during which the sun is above the horizon; a whole day for a flat calendar is not defined."""
        if self.daylight is None:
            raise ValueError("this calendar has no daylight table")
        return int(round(dict(self.daylight)[season] * self.day_ticks))

    def block_for_tick(self, tick, day_length_ticks: Optional[int] = None) -> str:
        """``dawn | day | dusk | night``. With ``day_length_ticks`` different from this calendar's day, or without a daylight table, the four
        equal quarters of ``schedule.resolver.tick_to_time_block`` (verbatim): a caller that asks for its own day length keeps it."""
        if self.daylight is None or (day_length_ticks is not None and int(day_length_ticks) != self.day_ticks):
            day_length = max(4, int(self.day_ticks if day_length_ticks is None else day_length_ticks))
            quarter = max(1, day_length // 4)
            return BLOCKS[min(len(BLOCKS) - 1, (int(tick) % day_length) // quarter)]
        tick_of_day = int(tick) % self.day_ticks
        up = self.sun_up_ticks(self.season_for_tick(tick))
        if tick_of_day >= up:
            return "night"
        if tick_of_day < DAWN_TICKS:
            return "dawn"
        if tick_of_day >= up - DAWN_TICKS:
            return "dusk"
        return "day"

    def light_at(self, tick) -> float:
        """Light level in [0, 1]. Continuous in the tick, including across the day boundary (night -> dawn) and across a season boundary
        (seasons change at day boundaries, where the light is ``LIGHT_FLOOR`` on both sides). LEGACY has no curve: 1.0 by day, 0.5 at
        dawn and dusk, 0.0 at night."""
        if self.daylight is None:
            return {"day": 1.0, "dawn": 0.5, "dusk": 0.5, "night": 0.0}[self.block_for_tick(tick)]
        tick_of_day = int(tick) % self.day_ticks
        up = self.sun_up_ticks(self.season_for_tick(tick))
        if tick_of_day >= up:
            return LIGHT_FLOOR
        return LIGHT_FLOOR + (1.0 - LIGHT_FLOOR) * math.sin(math.pi * tick_of_day / up) ** LIGHT_SHAPE

    def year_of(self, tick) -> int:
        return int(tick) // self.year_ticks

    def day_index(self, tick) -> int:
        return int(tick) // self.day_ticks

    def now(self, tick) -> Moment:
        t = int(tick)
        tick_of_day = t % self.day_ticks
        in_year = float(t) % float(self.year_ticks)
        season = self.season_for_tick(t)
        season_phase = (in_year % self.season_ticks) / self.season_ticks
        return Moment(tick=t, day_index=t // self.day_ticks, tick_of_day=tick_of_day, day_phase=tick_of_day / self.day_ticks,
                      block=self.block_for_tick(t), season=season, season_phase=season_phase, year=t // self.year_ticks,
                      year_phase=in_year / self.year_ticks, light=self.light_at(t))

    def day_changed(self, prev_tick, tick) -> range:
        """The day indices that begin after ``prev_tick`` up to and including ``tick``: empty when the day did not change or time went back."""
        return range(self.day_index(prev_tick) + 1, self.day_index(tick) + 1)

    # -- ageing ----------------------------------------------------------------------------------------------------------
    def age_step(self) -> float:
        """Life-years added per tick (``H_AGE`` is in life-years). LEGACY: exactly ``1.0 / TICKS_PER_YEAR``."""
        return 1.0 / self.life_year_ticks

    def cooldown_decay_rate(self) -> float:
        """Per-tick decay of the cooldowns that ``COOLDOWN_DECAY_RATE`` measures in years; they follow the life-year (design section 5)."""
        return 1.0 / self.life_year_ticks


LEGACY = Calendar(name="legacy", day_ticks=LEGACY_DAY_TICKS, year_ticks=LEGACY_YEAR_TICKS, life_year_ticks=float(LEGACY_YEAR_TICKS))
USER = Calendar(name="user", day_ticks=USER_DAY_TICKS, year_ticks=USER_DAY_TICKS * USER_DAYS_PER_YEAR,
                life_year_ticks=USER_DAY_TICKS / CALENDAR_LIFE_YEARS_PER_DAY, daylight=tuple(DAYLIGHT.items()))


def active() -> Calendar:
    return USER if calendar_enabled() else LEGACY


# -- drop-in accessors (what the readers call in step C1) ----------------------------------------------------------------
def now(tick) -> Moment:
    return active().now(tick)


def ticks_per_year() -> int:
    return active().year_ticks


def season_for_tick(tick) -> str:
    return active().season_for_tick(tick)


def tick_to_time_block(tick, *, day_length_ticks: Optional[int] = None) -> str:
    """The block of ``tick``. Flag on, the user calendar answers only for the default day length (a caller with its own day keeps quarters)."""
    cal = active()
    if cal is USER and day_length_ticks is not None and int(day_length_ticks) == LEGACY_DAY_TICKS:
        day_length_ticks = None
    return cal.block_for_tick(tick, day_length_ticks)


def year_of(tick) -> int:
    return active().year_of(tick)


def day_changed(prev_tick, tick) -> range:
    return active().day_changed(prev_tick, tick)


def age_step() -> float:
    return active().age_step()


def cooldown_decay_rate() -> float:
    return active().cooldown_decay_rate()


def rate_scale(cls: str) -> float:
    """Multiplier for a rate class. 1.0 with the flag off; an unknown class is an error either way (a typo must not silently scale by 1)."""
    if cls not in RATE_MULTIPLIERS:
        raise KeyError(f"unknown calendar rate class {cls!r}; known: {sorted(RATE_MULTIPLIERS)}")
    return RATE_MULTIPLIERS[cls] if calendar_enabled() else 1.0


def perception_scale(tick) -> float:
    """C3: the factor on a resident's scan radii at ``tick``. 1.0 with the flag off (legacy has no light curve); flag on,
    ``PERCEPTION_DARK_FRACTION + (1 - PERCEPTION_DARK_FRACTION) * light``: full radius at noon, 0.4 of it at night (light floor 0.05 gives 0.43)."""
    if not calendar_enabled():
        return 1.0
    return PERCEPTION_DARK_FRACTION + (1.0 - PERCEPTION_DARK_FRACTION) * active().light_at(tick)


def describe(cal: Optional[Calendar] = None) -> dict:
    """The facts a client or a save needs (design section 6)."""
    cal = cal or active()
    return {"enabled": cal is not LEGACY, "profile": cal.name, "day_ticks": cal.day_ticks, "year_ticks": cal.year_ticks,
            "days_per_year": cal.days_per_year, "season_ticks": cal.season_ticks, "daylight": dict(cal.daylight) if cal.daylight else None,
            "ticks_per_second": TICKS_PER_SECOND, "life_year_ticks": cal.life_year_ticks}
