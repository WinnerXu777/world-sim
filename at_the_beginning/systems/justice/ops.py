"""Record op of the justice verbs, run by the ActionRunner on the services' docket: ``case_close`` (the damages were levied)."""
from __future__ import annotations

from .runtime import of

KINDS = ("case_close",)


def execute(op, services, actor: str, tick: int) -> dict:
    if op.kind == "case_close":
        case = of(services).close(op.args["case"], op.args["outcome"], tick)
        return {"ok": case is not None, "case": op.args["case"], "outcome": op.args["outcome"]} if case is not None else {"ok": False, "reason": "no_case"}
    return {"ok": False, "reason": "unsupported_op", "kind": op.kind}
