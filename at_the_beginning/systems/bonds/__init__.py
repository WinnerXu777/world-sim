"""Bonds between residents (``EDEN_BONDS=1``, default off; needs ``EDEN_AGENT_ACTIONS``): ``court``, ``befriend``, ``apologise``, ``forgive``.

All four are closeness steps on the two residents' relationship records, the state the reputation, credit and labour rules already read (a friend at closeness >= 0.4 lends at par). No new
store: ``rules`` is the pure part (who may do what, how big the step is), ``systems/actions/bonds_verbs.py`` the verbs, ``systems/actions/bonds_day.py`` the periodic pass that makes
residents use them. Design: ``1008_actions.md`` section 10.16. An apology never makes a friend and never erases a theft (it is worth half against a ``thief`` tag); forgiving moves a grudge
toward 0, not past it, and the reputation pass removes the ``thief`` tag when the closeness reaches 0.
"""
from __future__ import annotations

import os

ENV = "EDEN_BONDS"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"
