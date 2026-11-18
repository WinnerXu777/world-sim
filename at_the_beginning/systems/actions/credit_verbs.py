"""Credit verbs (``EDEN_CREDIT=1``): ``borrow_item`` (ask), ``lend_item`` (the lender's side of a yes) and ``pay_debt`` (``1008_market_justice_design.md`` section 9).

Like the market and node verbs they live on their own ``CREDIT_REGISTRY`` (``default_registry()`` adds them while the flag is on). ``borrow_item`` only asks: the asked resident
answers by rules at op time (``respond_to_loan``: reads the lender's own pack, record and row) and a yes is a ``lend_item`` call *by the lender* through the same runner
(proposer ``rules:loan_response``), which is the atomic Transfer plus the loan record op. ``pay_debt`` pays what is owed in any item the lender can hold; the loan is
denominated in value, so a different food or coin settles it.
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import Registry, action

from . import reputation
from .draft import ActionDraft, RecordOp
from .verbs.common import emit, read

CREDIT_REGISTRY = Registry()
CLOSE = {"lender": 0.04, "borrower": 0.04, "repaid_lender": 0.08, "repaid_borrower": 0.04}     # placeholders, same order as the other economy closeness tables
DISTRUST_CLOSENESS = -0.2
MIN_CLOSENESS = 0.05           # a lender knows the borrower at least a little


def respond_to_loan(world, services, borrower: str, lender: str, item: str, qty: int) -> dict:
    """The asked resident's rules answer: ``lend | refuse_distrust | refuse_thief | refuse_defaulter | refuse_stranger | refuse_indebted | refuse_busy | refuse_no_item``.

    Reads only the lender's own pack, record and row, and the loan book (a debt between the two is no secret to either)."""
    from systems.affordance import config as aff
    from systems.credit import book as credit_book, runtime
    record = services.record(lender) or {}
    relation = (record.get("relationships") or {}).get(borrower, {})
    closeness = float(relation.get("closeness", 0.0))
    tags = relation.get("tags") or []
    if closeness < DISTRUST_CLOSENESS or "rival" in tags:
        return {"answer": "refuse_distrust", "item": item}
    if reputation.enabled() and reputation.refuses(record, borrower):
        return {"answer": "refuse_thief", "item": item}
    loans = runtime.of(services)
    if "defaulter" in tags or loans.defaulted(borrower, lender):
        return {"answer": "refuse_defaulter", "item": item}
    if world.table("humans").slot_of(lender) is None or read(world, lender, "hp") <= 0 or read(world, lender, "threat") >= aff.THREAT_BLOCKS_SLEEP:
        return {"answer": "refuse_busy", "item": item}
    if closeness < MIN_CLOSENESS and relation.get("kind") != "family" and "family" not in tags:
        return {"answer": "refuse_stranger", "item": item}
    if loans.between(borrower, lender) is not None:
        return {"answer": "refuse_indebted", "item": item}
    pack = services.inventory(lender)
    wanted = item or next((k for k in aff.EDIBLE_ITEMS if pack.get(k, 0) >= qty + credit_book.KEEP), "")
    if not wanted or pack.get(wanted, 0) < qty + credit_book.KEEP:
        return {"answer": "refuse_no_item", "item": wanted or item}
    return {"answer": "lend", "item": wanted}


@action("borrow_item", risk="reversible", precondition="can_borrow", registry=CREDIT_REGISTRY)
def borrow_item(world, ctx, target: str = "", item: str = "", qty: int = 1) -> ActionDraft:
    """Ask a neighbour for a loan of an item (empty ``item`` = whatever food they can spare). The lender answers by rules; a yes is a ``lend_item`` call by the lender."""
    ops = [RecordOp("loan_request", {"target": target, "item": item, "qty": int(qty)})]
    return ActionDraft([], emit(world, ctx.actor, "loan_asked", {"item": item, "qty": int(qty), "from": target}, others=(target,)), ops,
                       {"item": item, "qty": int(qty), "from": target})


@action("lend_item", risk="reversible", precondition="can_lend", registry=CREDIT_REGISTRY)
def lend_item(world, ctx, target: str = "", item: str = "", qty: int = 1) -> ActionDraft:
    """The lender hands over the item and a loan is opened (terms: at par for a friend, a quarter over for anyone else)."""
    me = ctx.actor
    relation = ((ctx.record or {}).get("relationships") or {}).get(target, {})
    ops = [RecordOp("loan_open", {"lender": me, "borrower": target, "item": item, "qty": int(qty), "closeness": float(relation.get("closeness", 0.0))}),
           RecordOp("relationship", {"other": target, "kind": "known", "delta": CLOSE["lender"]}),
           RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": CLOSE["borrower"]})]
    return ActionDraft([fx.Transfer(item, int(qty), me, target)], emit(world, me, "lent", {"item": item, "qty": int(qty), "to": target}, others=(target,)), ops,
                       {"item": item, "qty": int(qty), "to": target})


@action("pay_debt", risk="reversible", precondition="has_debt", registry=CREDIT_REGISTRY)
def pay_debt(world, ctx, target: str = "", item: str = "", qty: int = 1) -> ActionDraft:
    """Pay the lender ``qty`` x ``item`` against the open loan (any item the lender can hold: the loan is in value)."""
    me, loan = ctx.actor, ctx.verdict.detail["loan"]
    ops = [RecordOp("loan_pay", {"loan": loan, "item": item, "qty": int(qty)}),
           RecordOp("relationship", {"other": target, "kind": "known", "delta": CLOSE["repaid_borrower"]}),
           RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": CLOSE["repaid_lender"]})]
    detail = {"loan": loan, "item": item, "qty": int(qty), "to": target}
    return ActionDraft([fx.Transfer(item, int(qty), me, target)], emit(world, me, "debt_paid", detail, others=(target,)), ops, detail)
