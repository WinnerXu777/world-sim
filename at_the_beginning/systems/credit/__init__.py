"""Loans between residents (``EDEN_CREDIT=1``, default off; needs ``EDEN_AGENT_ACTIONS``): ``borrow_item`` -> the lender decides by rules -> ``lend_item``; ``pay_debt``; overdue and default.

Design: ``1008_market_justice_design.md`` section 9. ``book`` is the pure part (the loan record and its arithmetic); ``systems/actions/credit_verbs.py`` has the verbs;
``systems/actions/credit_day.py`` is the periodic pass (repayment errands, overdue notes, defaults). Runtime state only: a save forgets open loans (the items already moved).
"""
from __future__ import annotations

import os

ENV = "EDEN_CREDIT"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"
