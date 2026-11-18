"""Legality of the market verbs ``buy``, ``sell`` and ``set_price`` (``EDEN_MARKET=1``; with the flag off they answer ``not_wired`` and propose nothing).

Imported at the end of ``predicates.py``. A stall is a perceived storage entity that ``systems.market.runtime.is_stall`` knows; its goods and till are its inventory, which
anyone standing at it can see (like any container). Prices come from the services' ``MarketBook``; nothing here reads another resident's pack or memory.
"""
from __future__ import annotations

from . import config
from .predicates import Verdict, _alive, _positive_int, _storage_near, no, verb, yes

COIN = "coin"


def _flag_off():
    from systems.market import enabled
    return None if enabled() else no("not_wired", why="EDEN_MARKET is off")


def _stalls_near(S) -> list:
    from systems.market import runtime
    return [e for e in _storage_near(S) if runtime.is_stall(S.services, e.fact.id)]


def _book(S):
    from systems.market import runtime
    return runtime.of(S.services)


def _stall(S, container):
    """``(entity, None)`` for a perceived stall, else ``(None, Verdict)``."""
    from systems.market import runtime
    if not isinstance(container, str) or not container:
        return None, no("invalid_params", field="container")
    e = S.obs.entity(container)
    if e is None or e.fact.kind not in config.STORAGE_KINDS or not e.fact.alive or not runtime.is_stall(S.services, container):
        return None, no("no_stall", container=str(container))
    return e, None


def _reach(S, e):
    reach = S.interact(e.fact.x, e.fact.y, e.fact.id, e.fact.interact_radius)
    return None if reach.ok else Verdict(False, reach.reason, {"container": e.fact.id}, "", reach.distance), reach


def _household_of_actor(S) -> str:
    from systems.actions.ladder import household_of_resident
    record = S.services.record(S.actor) or {}
    key = (record.get("roster") or {}).get("key") or S.actor
    return household_of_resident(key)


def _item_ok(item):
    return None if isinstance(item, str) and item and item != COIN else no("invalid_params", field="item")


# -- buy ----------------------------------------------------------------------------------------------------------------------------
def _candidates_buy(S):
    from systems.market import enabled
    if not enabled() or not S.obs.alive:
        return []
    book, coin, out = _book(S), S.obs.inventory.get(COIN, 0), []
    for e in _stalls_near(S):
        for kind, q in sorted(S.services.inventory(e.fact.id).items()):
            if kind != COIN and q > 0 and book.ask(e.fact.id, kind) <= coin:
                out.append({"container": e.fact.id, "item": kind, "qty": 1})
    return out


@verb("buy", "can_buy", _candidates_buy)
def buy(S, container: str = "", item: str = "", qty: int = 1) -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    bad = _positive_int(qty, "qty") or _item_ok(item)
    if bad:
        return bad
    e, problem = _stall(S, container)
    if problem:
        return problem
    stock = S.services.inventory(container).get(item, 0)
    if stock < qty:
        return no("out_of_stock", item=item, stock=stock)
    price = _book(S).ask(container, item)
    have = S.obs.inventory.get(COIN, 0)
    if have < price * qty:
        return no("cannot_afford", item=item, price=price, have=have)
    room = S.world.items.room(S.actor, item)
    if room is not None and room < qty:
        return no("no_room", item=item, room=room)
    till = S.world.items.room(container, COIN)
    if till is not None and till < price * qty:
        return no("stall_full", container=container)
    problem, reach = _reach(S, e)
    return problem or yes({"price": price, "stall": container}, distance=reach.distance)


# -- sell ---------------------------------------------------------------------------------------------------------------------------
def _candidates_sell(S):
    from systems.market import enabled
    if not enabled() or not S.obs.alive:
        return []
    book, out = _book(S), []
    for e in _stalls_near(S):
        stall_pack = S.services.inventory(e.fact.id)
        for kind, q in sorted(S.obs.inventory.items()):
            if kind != COIN and q > 0 and stall_pack.get(kind, 0) < book.target(e.fact.id, kind) and stall_pack.get(COIN, 0) >= book.bid(e.fact.id, kind):
                out.append({"container": e.fact.id, "item": kind, "qty": 1})
    return out


@verb("sell", "can_sell", _candidates_sell)
def sell(S, container: str = "", item: str = "", qty: int = 1) -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    bad = _positive_int(qty, "qty") or _item_ok(item)
    if bad:
        return bad
    e, problem = _stall(S, container)
    if problem:
        return problem
    if S.obs.inventory.get(item, 0) < qty:
        return no("no_item", item=item, have=S.obs.inventory.get(item, 0))
    book, pack = _book(S), S.services.inventory(container)
    if pack.get(item, 0) + qty > max(book.target(container, item), qty):
        return no("not_wanted", item=item, stock=pack.get(item, 0), target=book.target(container, item))
    price = book.bid(container, item)
    if pack.get(COIN, 0) < price * qty:
        return no("till_empty", item=item, price=price, till=pack.get(COIN, 0))
    room = S.world.items.room(container, item)
    if room is not None and room < qty:
        return no("stall_full", container=container, item=item)
    room = S.world.items.room(S.actor, COIN)
    if room is not None and room < price * qty:
        return no("no_room", item=COIN, room=room)
    problem, reach = _reach(S, e)
    return problem or yes({"price": price, "stall": container}, distance=reach.distance)


# -- set_price ----------------------------------------------------------------------------------------------------------------------
def _candidates_set_price(S):
    return []       # the keeper's routine reprices (``systems/actions/shopkeeper``); the verb is not enumerated for the macro menu


@verb("set_price", "owns_shop", _candidates_set_price)
def set_price(S, container: str = "", item: str = "", price: int = 1) -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    bad = _positive_int(price, "price") or _item_ok(item)
    if bad:
        return bad
    e, problem = _stall(S, container)
    if problem:
        return problem
    from systems.market import runtime
    if runtime.owner_household(container) != _household_of_actor(S):
        return no("not_owner", container=container)
    lo, hi = _book(S).bounds(item)
    if not lo <= price <= hi:
        return no("price_out_of_bounds", price=price, low=lo, high=hi)
    problem, reach = _reach(S, e)
    return problem or yes({"low": lo, "high": hi}, distance=reach.distance)
