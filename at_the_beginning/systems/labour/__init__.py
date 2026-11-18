"""Paid work between residents (``EDEN_LABOUR=1``, default off; needs ``EDEN_AGENT_ACTIONS``): ``work_for`` (ask an employer for a shift) -> the employer decides by rules -> the worker
stays near them for the shift -> ``collect_wage`` (the wage moves from the employer's pack to the worker's).

Design: ``1008_market_justice_design.md`` section 9. ``book`` is the pure part (the job record, wage terms); ``systems/actions/labour_verbs.py`` has the verbs. Runtime state only.
"""
from __future__ import annotations

import os

ENV = "EDEN_LABOUR"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"
