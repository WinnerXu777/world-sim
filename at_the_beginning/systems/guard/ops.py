"""Record op of the defend verb, run by the ActionRunner on the services' guard book: ``post_open``."""
from __future__ import annotations

from .runtime import of

KINDS = ("post_open",)


def execute(op, services, actor: str, tick: int) -> dict:
    if op.kind == "post_open":
        args = op.args
        post = of(services).open(actor, args["kind"], args["charge"], tick, args["until"], args.get("radius", 40.0))
        return {"ok": post is not None, "post": post.id, "until": post.until} if post is not None else {"ok": False, "reason": "already_guarding"}
    return {"ok": False, "reason": "unsupported_op", "kind": op.kind}
