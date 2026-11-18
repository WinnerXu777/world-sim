"""Justice verbs (``EDEN_JUSTICE=1``): ``report_theft`` (a knower tells an authority) and ``levy_damages`` (the authority collects from the thief) (``1008_market_justice_design.md`` section 10).

On their own ``JUSTICE_REGISTRY`` (``default_registry()`` adds them while the flag is on). ``report_theft`` only reports: the authority answers by rules at op time
(``respond_to_report``: reads the authority's own record, row and the docket) and a yes opens a case. ``levy_damages`` is the authority's own verb, called when it stands by the thief: one atomic
set of Transfers thief -> victim (the stolen item first, then coin, then other goods; never the last unit of food), the case closes, and the thief's standing with both drops or recovers.
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import Registry, action

from .draft import ActionDraft, RecordOp
from .verbs.common import emit, read

JUSTICE_REGISTRY = Registry()
DISTRUST_CLOSENESS = -0.2
CLOSE = {"thief_to_authority": -0.15, "victim_to_authority": 0.06, "victim_to_thief": 0.10}


def respond_to_report(world, services, reporter: str, authority: str, about: str, victim: str, tick: int) -> dict:
    """The asked resident's rules answer: ``accept | refuse_not_authority | refuse_distrust | refuse_busy | refuse_known_case | refuse_conflict``."""
    from systems.affordance import config as aff
    from systems.justice import law, runtime
    record = services.record(authority) or {}
    if not law.is_authority(record):
        return {"answer": "refuse_not_authority"}
    if authority in (about, victim):
        return {"answer": "refuse_conflict"}
    relation = (record.get("relationships") or {}).get(reporter, {})
    if float(relation.get("closeness", 0.0)) < DISTRUST_CLOSENESS or "rival" in (relation.get("tags") or []):
        return {"answer": "refuse_distrust"}
    if world.table("humans").slot_of(authority) is None or read(world, authority, "hp") <= 0 or read(world, authority, "threat") >= aff.THREAT_BLOCKS_SLEEP:
        return {"answer": "refuse_busy"}
    runtime.of(services).lapse(tick)
    if runtime.of(services).against(about, victim) is not None:
        return {"answer": "refuse_known_case"}
    return {"answer": "accept"}


@action("report_theft", risk="reversible", precondition="can_report_theft", registry=JUSTICE_REGISTRY)
def report_theft(world, ctx, target: str = "", about: str = "", item: str = "", qty: int = 1, victim: str = "") -> ActionDraft:
    """Tell an authority that ``about`` took ``qty`` x ``item`` from ``victim`` (default: the reporter). The authority decides by rules whether to open a case."""
    victim = victim or ctx.actor
    ops = [RecordOp("report_request", {"target": target, "about": about, "item": item, "qty": int(qty), "victim": victim})]
    return ActionDraft([], emit(world, ctx.actor, "theft_reported", {"to": target, "about": about, "item": item, "qty": int(qty), "victim": victim}, others=(target, about)), ops,
                       {"to": target, "about": about})


@action("levy_damages", risk="reversible", precondition="can_levy", registry=JUSTICE_REGISTRY)
def levy_damages(world, ctx, target: str = "") -> ActionDraft:
    """The authority stands by the thief with an open case: damages move from the thief to the victim, one atomic set of Transfers, and the case closes."""
    me, case, taken, outcome = ctx.actor, ctx.verdict.detail["case"], ctx.verdict.detail["levy"], ctx.verdict.detail["outcome"]
    ops = [RecordOp("case_close", {"case": case["id"], "outcome": outcome}),
           RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": CLOSE["thief_to_authority"]}),
           RecordOp("relationship", {"owner": case["victim"], "other": me, "kind": "known", "delta": CLOSE["victim_to_authority"]})]
    if taken:
        ops.append(RecordOp("relationship", {"owner": case["victim"], "other": target, "kind": "known", "delta": CLOSE["victim_to_thief"]}))
    detail = {"case": case["id"], "thief": target, "victim": case["victim"], "taken": [list(t) for t in taken], "outcome": outcome}
    effects = [fx.Transfer(kind, int(qty), target, case["victim"]) for kind, qty in taken]
    return ActionDraft(effects, emit(world, me, "damages_levied", detail, others=(target, case["victim"])), ops, detail)
