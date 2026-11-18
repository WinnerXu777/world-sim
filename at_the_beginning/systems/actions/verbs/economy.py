"""Economy verbs: request_item, give_item, commission_item, offer_trade, accept_trade.

``give_item`` is an atomic Transfer plus an event and a relationship update. ``request_item`` asks; the asked resident answers by rules
(``respond_to_request``: give / refuse_no_item / refuse_distrust / refuse_thief / refuse_busy) at op time, and a ``give`` goes through this same runner as a
``give_item`` call by the asked resident. ``commission_item`` hands the customer side of the Stage 1 commission loop (order, escrow, the smith's
decision with the rules provider) to ``submit_request`` through the record ops.
``offer_trade`` opens an offer in the services' ``OfferBook`` and the asked resident answers by rules (``respond_to_trade``) at op time; an
``accept`` goes through this same runner as an ``accept_trade`` call by the asked resident (proposer ``rules:trade_response``), which is the atomic swap.
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import action

from .. import reputation
from ..draft import ActionDraft, RecordOp
from . import REGISTRY
from .common import emit, read

GIVE_CLOSENESS = {"giver": 0.03, "receiver": 0.06}      # placeholders, same order of magnitude as the commission closeness table
DISTRUST_CLOSENESS = -0.2
TRADE_CLOSENESS = 0.03


def respond_to_request(world, services, requester: str, target: str, item: str, qty: int) -> dict:
    """The asked resident's rules answer. ``item`` may be empty: the asked resident then offers the first edible it holds.

    Returns ``{"answer": give | refuse_no_item | refuse_distrust | refuse_busy, "item": kind}``. Reads only the asked resident's own pack,
    record and tensor row (it is *their* decision)."""
    from systems.affordance import config as aff
    record = services.record(target) or {}
    relation = (record.get("relationships") or {}).get(requester, {})
    if float(relation.get("closeness", 0.0)) < DISTRUST_CLOSENESS or "rival" in (relation.get("tags") or []):
        return {"answer": "refuse_distrust", "item": item}
    if reputation.enabled() and reputation.refuses(record, requester):      # EDEN_REPUTATION: a known thief is turned away
        return {"answer": "refuse_thief", "item": item}
    if world.table("humans").slot_of(target) is None or read(world, target, "hp") <= 0 or read(world, target, "threat") >= aff.THREAT_BLOCKS_SLEEP:
        return {"answer": "refuse_busy", "item": item}
    pack = services.inventory(target)
    wanted = item or next((k for k in aff.EDIBLE_ITEMS if pack.get(k, 0) >= 1), "")
    if not wanted or pack.get(wanted, 0) < qty:
        return {"answer": "refuse_no_item", "item": wanted or item}
    return {"answer": "give", "item": wanted}


@action("give_item", risk="reversible", precondition="can_give", registry=REGISTRY)
def give_item(world, ctx, target: str = "", item: str = "", qty: int = 1) -> ActionDraft:
    me = ctx.actor
    effects = [fx.Transfer(item, int(qty), me, target)]
    ops = [RecordOp("relationship", {"other": target, "kind": "known", "delta": GIVE_CLOSENESS["giver"]}),
           RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": GIVE_CLOSENESS["receiver"]})]
    return ActionDraft(effects, emit(world, me, "gave_item", {"item": item, "qty": int(qty), "to": target}, others=(target,)), ops,
                       {"item": item, "qty": int(qty), "to": target})


@action("request_item", risk="reversible", precondition="can_request", registry=REGISTRY)
def request_item(world, ctx, target: str = "", item: str = "", qty: int = 1) -> ActionDraft:
    """Ask a neighbour for an item (empty ``item`` = whatever food they can spare). The answer is decided by the asked resident's rules."""
    me = ctx.actor
    ops = [RecordOp("request_response", {"target": target, "item": item, "qty": int(qty)})]
    return ActionDraft([], emit(world, me, "item_requested", {"item": item, "qty": int(qty), "from": target}, others=(target,)), ops,
                       {"item": item, "qty": int(qty), "from": target})


@action("commission_item", risk="reversible", precondition="can_commission", registry=REGISTRY)
def commission_item(world, ctx, target: str = "", recipe: str = "") -> ActionDraft:
    """Order ``recipe`` from the resident at ``target`` through the Stage 1 commission loop (order, escrow, the smith decides)."""
    ops = [RecordOp("commission_request", {"smith": target, "recipe": recipe})]
    return ActionDraft([], None, ops, {"smith": target, "recipe": recipe})


def respond_to_trade(world, services, giver: str, taker: str, give: str, give_qty: int, want: str, want_qty: int) -> str:
    """The asked resident's rules answer to a swap offer: ``accept | refuse_distrust | refuse_busy | refuse_no_item | refuse_unfair | refuse_needs``.

    Reads only the asked resident's own pack, record and row. Fair = the value received (``give``) is at least ``FAIRNESS`` of the value given up (``want``);
    a hungry resident (>= 50) does not swap an edible away for something it cannot eat."""
    from systems.affordance import config as aff
    from ..offers import FAIRNESS, item_value
    record = services.record(taker) or {}
    relation = (record.get("relationships") or {}).get(giver, {})
    if float(relation.get("closeness", 0.0)) < DISTRUST_CLOSENESS or "rival" in (relation.get("tags") or []):
        return "refuse_distrust"
    if reputation.enabled() and reputation.refuses(record, giver):
        return "refuse_thief"
    if world.table("humans").slot_of(taker) is None or read(world, taker, "hp") <= 0 or read(world, taker, "threat") >= aff.THREAT_BLOCKS_SLEEP:
        return "refuse_busy"
    if services.inventory(taker).get(want, 0) < want_qty:
        return "refuse_no_item"
    if want in aff.EDIBLE_ITEMS and give not in aff.EDIBLE_ITEMS and read(world, taker, "hunger") >= 50.0:
        return "refuse_needs"
    if item_value(give) * give_qty < FAIRNESS * item_value(want) * want_qty:
        return "refuse_unfair"
    return "accept"


@action("offer_trade", risk="reversible", precondition="can_trade", registry=REGISTRY)
def offer_trade(world, ctx, target: str = "", give: str = "", want: str = "", give_qty: int = 1, want_qty: int = 1) -> ActionDraft:
    """Offer ``give_qty`` x ``give`` for ``want_qty`` x ``want``. The asked resident answers by its rules; on accept the swap is an ``accept_trade`` call."""
    detail = {"to": target, "give": give, "give_qty": int(give_qty), "want": want, "want_qty": int(want_qty)}
    ops = [RecordOp("trade_offer", {"target": target, "give": give, "give_qty": int(give_qty), "want": want, "want_qty": int(want_qty)})]
    return ActionDraft([], emit(world, ctx.actor, "trade_offered", detail, others=(target,)), ops, detail)


@action("accept_trade", risk="reversible", precondition="offer_open", registry=REGISTRY)
def accept_trade(world, ctx, offer: str = "") -> ActionDraft:
    """Accept an open offer addressed to the actor: both Transfers in one atomic apply, closeness up for both, the offer closed."""
    found, me = ctx.verdict.detail["offer"], ctx.actor
    giver = found["giver"]
    effects = [fx.Transfer(found["give"], found["give_qty"], giver, me), fx.Transfer(found["want"], found["want_qty"], me, giver)]
    ops = [RecordOp("trade_close", {"offer": offer}),
           RecordOp("relationship", {"other": giver, "kind": "known", "delta": TRADE_CLOSENESS}),
           RecordOp("relationship", {"owner": giver, "other": me, "kind": "known", "delta": TRADE_CLOSENESS})]
    detail = {"offer": offer, "with": giver, "got": found["give"], "got_qty": found["give_qty"], "gave": found["want"], "gave_qty": found["want_qty"]}
    return ActionDraft(effects, emit(world, me, "traded", detail, others=(giver,)), ops, detail)
