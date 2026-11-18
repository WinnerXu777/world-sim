"""The market's pure part: prices, the stall's sales ring, scarcity from supply and demand. No engine, no I/O; every number here is unit-tested.

Prices are whole coin. The settlement scarcity factor ``f`` per item scales the reference price ``R = round(value * f)``; a stall sells (ask) at ``value * f *
MARKUP`` rounded up and buys (bid) at ``value * f * BID`` rounded down, unless its keeper has set an own ask with ``set_price`` (bounded to ``0.5R .. 3R``).
Once a day ``MarketBook.daily_update`` folds the day's sales, unmet purchases, stall stock and any outside supply into the smoothed demand and supply, and
``f = clamp((demand + 1) / (supply + 1), 0.5, 3)``. A demand shock (a god tool, an event) multiplies the day's demand, a blight lowers the outside supply: both
move ``f`` through the same formula, with no special case.
"""
from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Callable, Optional

MARKUP = 1.25                 # a stall resells at this margin over the scarcity-scaled value
BID = 0.6                     # and buys at this share of it
BOUND_LO, BOUND_HI = 0.5, 3.0  # set_price stays within these multiples of the reference price
SCARCITY_MIN, SCARCITY_MAX = 0.5, 3.0
SMOOTHING = 0.3               # weight of today in the demand / supply averages
STOCK_DAYS = 3.0              # stall stock counts as this many days of supply (stock / STOCK_DAYS per day)
RING = 200                    # sales remembered per stall
GOUGE = 2.0                   # an ask above this multiple of R while a buyer is starving is gouging (reputation input)
WANT_DAYS = 2.0               # a stall wants stock for this many days of its own sales, and at least MIN_TARGET units
MIN_TARGET = 2

Value = Callable[[str], float]


def _round(x: float) -> int:
    return int(math.floor(x + 0.5))


def reference(value: float, factor: float) -> int:
    return max(1, _round(float(value) * float(factor)))


def default_ask(value: float, factor: float) -> int:
    return max(1, int(math.ceil(float(value) * float(factor) * MARKUP - 1e-9)))


def default_bid(value: float, factor: float) -> int:
    return min(default_ask(value, factor), max(1, int(math.floor(float(value) * float(factor) * BID + 1e-9))))


def price_bounds(value: float, factor: float) -> tuple:
    """``(lowest, highest)`` ask a keeper may set."""
    r = reference(value, factor)
    lo = max(1, int(math.ceil(r * BOUND_LO - 1e-9)))
    return lo, max(lo, int(math.ceil(r * BOUND_HI - 1e-9)))


def scarcity(demand: float, supply: float) -> float:
    return max(SCARCITY_MIN, min(SCARCITY_MAX, (float(demand) + 1.0) / (float(supply) + 1.0)))


def smooth(previous: float, today: float) -> float:
    return (1.0 - SMOOTHING) * float(previous) + SMOOTHING * float(today)


@dataclass
class Sale:
    tick: int
    item: str
    qty: int
    price: int          # per unit
    kind: str           # "buy" (a resident bought from the stall) | "sell" (a resident sold to it)
    who: str


@dataclass
class Stall:
    id: str
    owner: str                                    # household prefix of the stall's id
    prices: dict = field(default_factory=dict)    # item -> own ask in coin (set by the keeper); absent = the default ask
    sales: deque = field(default_factory=lambda: deque(maxlen=RING))
    bought: Counter = field(default_factory=Counter)      # today's units sold BY the stall (residents bought)
    sold: Counter = field(default_factory=Counter)        # today's units sold TO the stall
    unmet: Counter = field(default_factory=Counter)       # today's units wanted and not in stock
    turnover: dict = field(default_factory=dict)          # item -> smoothed units the stall sells per day


class MarketBook:
    def __init__(self, value: Value):
        self.value = value
        self.stalls: dict = {}
        self.factor: dict = {}              # item -> scarcity factor (1.0 when never updated)
        self.demand: dict = {}              # item -> smoothed units wanted per day
        self.supply: dict = {}              # item -> smoothed units offered per day
        self.shock: dict = {}               # item -> multiplier on the day's demand (a god tool / event sets it)
        self.last_day: Optional[int] = None
        self.history: list = []             # [{"day", "factors": {item: f}}]

    # -- stalls and prices ------------------------------------------------------------------------------------------------------
    def stall(self, stall_id: str) -> Stall:
        found = self.stalls.get(stall_id)
        if found is None:
            found = self.stalls[stall_id] = Stall(stall_id, str(stall_id).split(":", 1)[0].removesuffix("_interior"))
        return found

    def f(self, item: str) -> float:
        return float(self.factor.get(item, 1.0))

    def reference(self, item: str) -> int:
        return reference(self.value(item), self.f(item))

    def ask(self, stall_id: str, item: str) -> int:
        own = self.stall(stall_id).prices.get(item)
        return int(own) if own else default_ask(self.value(item), self.f(item))

    def bid(self, stall_id: str, item: str) -> int:
        return min(self.ask(stall_id, item), default_bid(self.value(item), self.f(item)))

    def bounds(self, item: str) -> tuple:
        return price_bounds(self.value(item), self.f(item))

    def set_ask(self, stall_id: str, item: str, price: int) -> None:
        self.stall(stall_id).prices[item] = int(price)

    def target(self, stall_id: str, item: str) -> int:
        """The stock the stall wants to hold: ``WANT_DAYS`` of its own sales, at least ``MIN_TARGET``."""
        return max(MIN_TARGET, int(math.ceil(WANT_DAYS * self.stall(stall_id).turnover.get(item, 0.0))))

    # -- what happened ----------------------------------------------------------------------------------------------------------
    def record_sale(self, tick: int, stall_id: str, item: str, qty: int, price: int, kind: str, who: str) -> None:
        stall = self.stall(stall_id)
        stall.sales.append(Sale(int(tick), item, int(qty), int(price), kind, who))
        (stall.bought if kind == "buy" else stall.sold)[item] += int(qty)

    def record_unmet(self, stall_id: str, item: str, qty: int = 1) -> None:
        self.stall(stall_id).unmet[item] += int(qty)

    def gouging(self, stall_id: str, item: str) -> bool:
        return self.ask(stall_id, item) > GOUGE * self.reference(item)

    # -- the daily update ---------------------------------------------------------------------------------------------------------
    def daily_update(self, day: int, stock: Optional[dict] = None, outside_supply: Optional[dict] = None) -> Optional[dict]:
        """Fold one day into the factors. ``stock``: item -> units on the stalls' shelves now. ``outside_supply``: item -> units the settlement's nodes and
        fields offer per day (a blight lowers it). Returns ``{item: (old, new)}`` for the changed factors, or None when the day was already folded (the first
        call only fixes the day)."""
        if self.last_day is None:
            self.last_day = int(day)
            return None
        if int(day) <= self.last_day:
            return None
        self.last_day = int(day)
        stock, outside_supply = stock or {}, outside_supply or {}
        wanted, offered = Counter(), Counter()
        for stall in self.stalls.values():
            for item, n in stall.bought.items():
                wanted[item] += n
            for item, n in stall.unmet.items():
                wanted[item] += n
            for item, n in stall.sold.items():
                offered[item] += n
        items = sorted(set(wanted) | set(offered) | set(stock) | set(outside_supply) | set(self.demand) | set(self.supply))
        changed = {}
        for item in items:
            demand_today = wanted[item] * float(self.shock.get(item, 1.0))
            supply_today = offered[item] + float(stock.get(item, 0)) / STOCK_DAYS + float(outside_supply.get(item, 0.0))
            self.demand[item] = smooth(self.demand.get(item, 0.0), demand_today)
            self.supply[item] = smooth(self.supply.get(item, 0.0), supply_today)
            new = round(scarcity(self.demand[item], self.supply[item]), 4)
            old = self.f(item)
            if new != old:
                changed[item] = (old, new)
            self.factor[item] = new
        for stall in self.stalls.values():
            for item in sorted(set(stall.turnover) | set(stall.bought)):
                stall.turnover[item] = smooth(stall.turnover.get(item, 0.0), stall.bought[item])
            stall.bought.clear()
            stall.sold.clear()
            stall.unmet.clear()
        self.history.append({"day": int(day), "factors": dict(self.factor)})
        return changed
