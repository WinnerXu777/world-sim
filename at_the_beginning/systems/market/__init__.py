"""The settlement market (``EDEN_MARKET=1``, default off; needs ``EDEN_AGENT_ACTIONS``): stalls with a price list, scarcity from supply and demand, coin.

Design: ``1008_market_justice_design.md`` section 8. ``book`` is the pure part (prices, scarcity, ring of sales); ``systems/actions/market_verbs.py`` holds the
verbs ``buy`` / ``sell`` / ``set_price``. Runtime state only (stock and coin are inventories and already saved; prices are derived and restart from the reference).
"""
from __future__ import annotations

import os

ENV = "EDEN_MARKET"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"
