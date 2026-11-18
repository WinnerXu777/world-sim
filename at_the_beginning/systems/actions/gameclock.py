"""The one place that says how long a game day is, in ticks (reputation decay, the market's daily update, loans and cases, grudge decay, any later per-day rule).

Legacy calendar: 2400 ticks a day. With ``EDEN_CALENDAR=1`` the day is the calendar's (12000 ticks, ``harness/calendar.py``): ``day_ticks()`` answers it at call time. A scenario that sets ``DAY_TICKS`` itself
(the s1 commons and market runs use short days) keeps its value under both calendars; only the untouched default follows the flag.
"""
from __future__ import annotations

DAY_TICKS = 2400                  # the legacy day, and the value a scenario overrides
LEGACY_DAY_TICKS = 2400


def day_ticks() -> int:
    """Ticks in a game day right now: the scenario's ``DAY_TICKS`` if it was changed, else the active calendar's day (legacy 2400, ``EDEN_CALENDAR=1``: 12000)."""
    if DAY_TICKS != LEGACY_DAY_TICKS:
        return int(DAY_TICKS)
    from harness import calendar
    return int(calendar.active().day_ticks)


def day_of(tick: int) -> int:
    return int(tick) // day_ticks()
