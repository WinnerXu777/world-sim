"""Record ops of the market verbs (run by the ``ActionRunner`` after the atomic apply, on the services' market book): ``market_sale`` and ``price_set``."""
from __future__ import annotations

from .runtime import of

KINDS = ("market_sale", "price_set")


def execute(op, services, actor: str, tick: int) -> dict:
    book = of(services)
    args = op.args
    if op.kind == "market_sale":
        book.record_sale(tick, args["stall"], args["item"], args["qty"], args["price"], args["kind"], actor)
        return {"ok": True}
    if op.kind == "price_set":
        book.set_ask(args["stall"], args["item"], args["price"])
        return {"ok": True}
    return {"ok": False, "reason": "unsupported_op", "kind": op.kind}
