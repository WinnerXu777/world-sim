"""Market verbs (``EDEN_MARKET=1``): ``buy``, ``sell`` and ``set_price`` at a stall (``1008_market_justice_design.md`` section 8).

Like the resource-node verbs they live on their own ``MARKET_REGISTRY`` (the 65-verb catalog vocabulary and the S1 registry stay as pinned; the catalog rows stay
``new`` until the flag is on by default) and ``default_registry()`` adds them while the flag is on. A stall is a storage entity (``systems/market/runtime``): its goods
and its till (coin) are its inventory, so a purchase is one atomic apply of two Transfers (coin to the stall, goods to the buyer), conservation-checked by the harness.
The stall id travels in the ``container`` parameter (grounded like the other storage verbs). Prices come from the services' ``MarketBook``.
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import Registry, action

from .draft import ActionDraft, RecordOp
from .verbs.common import emit

MARKET_REGISTRY = Registry()
EVENT_RADIUS = 12.0         # neighbours who watch a sale learn the price


@action("buy", risk="reversible", precondition="can_buy", registry=MARKET_REGISTRY)
def buy(world, ctx, container: str = "", item: str = "", qty: int = 1) -> ActionDraft:
    """Buy ``qty`` x ``item`` from the stall at its ask: coin to the till, goods to the pack, one atomic apply."""
    detail = ctx.verdict.detail
    price, total = int(detail["price"]), int(detail["price"]) * int(qty)
    effects = [fx.Transfer("coin", total, ctx.actor, container), fx.Transfer(item, int(qty), container, ctx.actor)]
    ops = [RecordOp("market_sale", {"stall": container, "item": item, "qty": int(qty), "price": price, "kind": "buy"})]
    payload = {"stall": container, "item": item, "qty": int(qty), "price": price, "total": total}
    return ActionDraft(effects, emit(world, ctx.actor, "bought", payload, radius=EVENT_RADIUS), ops, payload)


@action("sell", risk="reversible", precondition="can_sell", registry=MARKET_REGISTRY)
def sell(world, ctx, container: str = "", item: str = "", qty: int = 1) -> ActionDraft:
    """Sell ``qty`` x ``item`` to the stall at its bid: goods to the stall, coin from the till to the pack, one atomic apply."""
    detail = ctx.verdict.detail
    price, total = int(detail["price"]), int(detail["price"]) * int(qty)
    effects = [fx.Transfer(item, int(qty), ctx.actor, container), fx.Transfer("coin", total, container, ctx.actor)]
    ops = [RecordOp("market_sale", {"stall": container, "item": item, "qty": int(qty), "price": price, "kind": "sell"})]
    payload = {"stall": container, "item": item, "qty": int(qty), "price": price, "total": total}
    return ActionDraft(effects, emit(world, ctx.actor, "sold", payload, radius=EVENT_RADIUS), ops, payload)


@action("set_price", risk="reversible", precondition="owns_shop", registry=MARKET_REGISTRY)
def set_price(world, ctx, container: str = "", item: str = "", price: int = 1) -> ActionDraft:
    """The keeper sets the stall's ask for ``item`` (within 0.5x..3x of the reference price)."""
    payload = {"stall": container, "item": item, "price": int(price)}
    ops = [RecordOp("price_set", dict(payload))]
    return ActionDraft([], emit(world, ctx.actor, "price_set", payload, radius=EVENT_RADIUS), ops, payload)
