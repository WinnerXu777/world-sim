"""Guard posts (``EDEN_DEFEND=1``, default off; needs ``EDEN_AGENT_ACTIONS``): the bounded ``defend`` verb, defend Phase 0 of ``1008_defend_design.md``.

A resident can stand guard over a person or a place for ``GUARD_TICKS``. While the post is open the guard keeps close (a following errand), and when someone attacks the person (or anyone
at the place) in the guard's reach the guard takes the blow instead, at ``TAKE`` of the damage (the Phase 1 combat hook, ``systems/combat/modifiers.py``), and answers the attacker by rules
(warn first; an authority or a fierce guard attacks). ``book`` is the pure data, ``runtime.of`` the book of a services object, ``modifier`` the combat hook, ``ops`` the record op that opens a
post, ``systems/actions/guard_verbs.py`` the verb and ``systems/actions/guard_day.py`` the per-tick pass (posts for authorities and for kin, errands, retaliation, expiry).
"""
from __future__ import annotations

import os

ENV = "EDEN_DEFEND"
GUARD_TICKS = 600           # one watch: a quarter of a game day
GUARD_RADIUS = 40.0         # the guard must stand this close to the charge (or to the post's place) to take a blow
TAKE = 0.6                  # the guard takes this share of the damage
MIN_HP = 30.0               # a guard below this hp does not take posts and does not intercept
KIN_CLOSENESS = 0.5         # a resident stands guard over someone it holds at least this dear (kin, or a close friend) ...
KIN_PROTECTIVENESS = 0.6    # ... if it is protective enough ...
KIN_THREAT = 30.0           # ... and that someone is under threat
RESPONSE_WINDOW = 40        # ticks after a blow in which the guard answers the attacker
RESPONSE_COOLDOWN = 200     # per (guard, attacker)
ATTACKER_MIN_HP = 30.0      # the guard stops attacking someone who is down to this


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"
