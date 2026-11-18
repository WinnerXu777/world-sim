"""Justice by an authority resident (``EDEN_JUSTICE=1``, default off; needs ``EDEN_AGENT_ACTIONS`` and ``EDEN_REPUTATION``): a knower reports a theft to the authority, the authority
decides by rules, walks to the thief and levies damages for the victim.

Design: ``1008_market_justice_design.md`` section 10. ``law`` is the pure part (who is an authority, what damages are owed, what can be levied); ``docket`` the case book;
``systems/actions/justice_verbs.py`` the verbs (``report_theft``, ``levy_damages``); ``systems/actions/justice_day.py`` the periodic pass (reports, enforcement errands, lapse).
No violence: an authority can only collect, and never takes a resident's last unit of food. Runtime state only.
"""
from __future__ import annotations

import os

ENV = "EDEN_JUSTICE"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"
