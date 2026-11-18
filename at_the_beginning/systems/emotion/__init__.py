"""Social-emotional state and slow drives of a resident (``EDEN_EMOTION=1``, default off; needs ``EDEN_AGENT_ACTIONS``) (design: ``1008_instincts`` 2.A4 / 2.A5, ``1008_actions.md`` section 10.22).

Everything lives in the resident's own record, ``record["emotion"]``, and is updated by one cadence pass (``systems/actions/emotion_day.py``), never per tick:

* ``grief`` ``{"level", "subject", "since", "relief"}``: a death of someone held close (closeness >= ``rules.GRIEF_MIN``) lowers mood once and fades over ``rules.GRIEF_DAYS`` game days;
* ``tension`` ``{rival: 0..1}``: jealousy, a partner's attention to someone else;
* ``drives`` ``{"curiosity", "thrift"}``: two slow levels in 0..1 (the spec ships two first), set from traits and moved by what happens;
* ``grudges`` ``{other: closeness at the last pass}`` and ``last_decay_tick``: the lazy catch-up of the daily grudge decay (a dormant resident applies the days it missed at once on waking);
* ``mourned`` the dead already mourned, ``known_places`` the count last seen (curiosity's discharge).

``rules`` is the pure part. Loyalty and gratitude are not stored: loyalty is derived from the relationship record and the trait (``rules.threshold``), gratitude is the closeness steps the verbs already give.
"""
from __future__ import annotations

import os

ENV = "EDEN_EMOTION"
FIELD = "emotion"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"


def of(record: dict) -> dict:
    """The record's emotion block, created on first use."""
    block = record.get(FIELD)
    if not isinstance(block, dict):
        block = record[FIELD] = {}
    return block


def read(record) -> dict:
    """The block without creating it (``{}`` for none)."""
    block = (record or {}).get(FIELD)
    return block if isinstance(block, dict) else {}


def grief_level(record, tick: int, day_ticks: int) -> float:
    """The current grief (0..1) of a record."""
    from . import rules
    return rules.grief_now(read(record).get("grief"), tick, day_ticks)


def tension(record) -> float:
    """The strongest jealous tension (0..1) in a record."""
    held = read(record).get("tension") or {}
    return max((float(v) for v in held.values()), default=0.0)


def drive(record, name: str, default: float = 0.0) -> float:
    return float(((read(record).get("drives")) or {}).get(name, default))
