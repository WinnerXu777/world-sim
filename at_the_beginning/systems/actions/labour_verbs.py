"""Labour verbs (``EDEN_LABOUR=1``): ``work_for`` (ask for a paid shift) and ``collect_wage`` (``1008_market_justice_design.md`` section 9).

On their own ``LABOUR_REGISTRY`` (``default_registry()`` adds them while the flag is on). ``work_for`` only asks: the employer answers by rules at op time (``respond_to_job``: reads
the employer's own pack, record and row) and a yes opens a job in the services' ``JobBook`` (nothing moves yet; the wage stays in the employer's pack). The worker then stays near the
employer for ``WORK_TICKS`` (the ladder's ``labour`` errand follows them) and ``collect_wage`` moves the wage, one atomic Transfer, if the employer still holds it.
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import Registry, action

from . import reputation
from .draft import ActionDraft, RecordOp
from .verbs.common import emit, read

LABOUR_REGISTRY = Registry()
CLOSE = {"employer": 0.05, "worker": 0.05}
DISTRUST_CLOSENESS = -0.2


def wage_for(services, employer: str) -> tuple:
    """``(item, qty)`` the employer can pay: the food it holds most of beyond the one unit it keeps, else coin; ``("", 0)`` when it cannot pay."""
    from systems.affordance import config as aff
    from systems.actions.offers import item_value
    from systems.labour import book as lb
    pack = services.inventory(employer)
    foods = sorted(((pack.get(k, 0), k) for k in aff.EDIBLE_ITEMS if pack.get(k, 0) >= lb.wage_units(item_value(k)) + lb.KEEP), reverse=True)
    if foods:
        item = foods[0][1]
        return item, lb.wage_units(item_value(item))
    coin = lb.wage_units(item_value("coin"))
    return ("coin", coin) if pack.get("coin", 0) >= coin else ("", 0)


def respond_to_job(world, services, worker: str, employer: str, tick: int) -> dict:
    """The asked resident's rules answer: ``hire | refuse_distrust | refuse_thief | refuse_defaulter | refuse_busy | refuse_staffed | refuse_no_wage``."""
    from systems.affordance import config as aff
    from systems.credit import runtime as credit_runtime
    from systems.labour import book as lb, runtime
    record = services.record(employer) or {}
    relation = (record.get("relationships") or {}).get(worker, {})
    tags = relation.get("tags") or []
    if float(relation.get("closeness", 0.0)) < DISTRUST_CLOSENESS or "rival" in tags:
        return {"answer": "refuse_distrust"}
    if reputation.enabled() and reputation.refuses(record, worker):
        return {"answer": "refuse_thief"}
    if "defaulter" in tags or credit_runtime.of(services).defaulted(worker, employer):
        return {"answer": "refuse_defaulter"}
    if world.table("humans").slot_of(employer) is None or read(world, employer, "hp") <= 0 or read(world, employer, "threat") >= aff.THREAT_BLOCKS_SLEEP:
        return {"answer": "refuse_busy"}
    if runtime.of(services).staff(employer, tick) >= lb.MAX_WORKERS:
        return {"answer": "refuse_staffed"}
    item, qty = wage_for(services, employer)
    if not item:
        return {"answer": "refuse_no_wage"}
    return {"answer": "hire", "item": item, "qty": qty}


@action("work_for", risk="reversible", precondition="can_work_for", registry=LABOUR_REGISTRY)
def work_for(world, ctx, target: str = "") -> ActionDraft:
    """Ask a neighbour for a paid shift. The employer answers by rules; a yes opens the job and the worker stays near them until it is done."""
    ops = [RecordOp("job_request", {"target": target})]
    return ActionDraft([], emit(world, ctx.actor, "work_asked", {"of": target}, others=(target,)), ops, {"of": target})


@action("collect_wage", risk="reversible", precondition="can_collect_wage", registry=LABOUR_REGISTRY)
def collect_wage(world, ctx, target: str = "") -> ActionDraft:
    """The shift is done: the employer's wage moves to the worker, one atomic Transfer, and the job closes."""
    me, job = ctx.actor, ctx.verdict.detail["job"]
    ops = [RecordOp("job_close", {"job": job["id"]}),
           RecordOp("relationship", {"other": target, "kind": "known", "delta": CLOSE["worker"]}),
           RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": CLOSE["employer"]})]
    detail = {"job": job["id"], "item": job["item"], "qty": job["qty"], "from": target}
    return ActionDraft([fx.Transfer(job["item"], job["qty"], target, me)], emit(world, me, "wage_paid", detail, others=(target,)), ops, detail)
