"""Record op of the labour verbs, run by the ActionRunner on the services' job book: ``job_close`` (the wage was paid)."""
from __future__ import annotations

from .runtime import of

KINDS = ("job_close",)


def execute(op, services, actor: str, tick: int) -> dict:
    if op.kind == "job_close":
        job = of(services).pay(op.args["job"], tick)
        return {"ok": job is not None, "job": op.args["job"]} if job is not None else {"ok": False, "reason": "no_job"}
    return {"ok": False, "reason": "unsupported_op", "kind": op.kind}
