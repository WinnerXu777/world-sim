"""Record ops of the credit verbs, run by the ActionRunner on the services' loan book: ``loan_open`` and ``loan_pay``."""
from __future__ import annotations

from .runtime import of

KINDS = ("loan_open", "loan_pay")


def execute(op, services, actor: str, tick: int) -> dict:
    from systems.actions.gameclock import day_ticks
    book, args = of(services), op.args
    if op.kind == "loan_open":
        loan = book.open(args["lender"], args["borrower"], args["item"], args["qty"], args.get("closeness", 0.0), tick, day_ticks())
        return {"ok": True, "loan": loan.id, "owed": loan.owed, "due": loan.due}
    if op.kind == "loan_pay":
        loan = book.pay(args["loan"], args["item"], args["qty"], tick)
        if loan is None:
            return {"ok": False, "reason": "no_loan"}
        return {"ok": True, "loan": loan.id, "owed": loan.owed, "status": loan.status}
    return {"ok": False, "reason": "unsupported_op", "kind": op.kind}
