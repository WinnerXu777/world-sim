"""The action runner: the one path every tier (and the rules) uses to make a resident do something.

    1 schema     registry.validate_call            unknown verb / wrong or extra arguments / wrong types      -> unknown_action | not_implemented | invalid_arguments
    2 grounding  ids must exist as what they claim   a made-up resident / entity / place / recipe / item        -> ungrounded_target | ungrounded_place | ungrounded_recipe | ungrounded_item
    3 legality   the affordance predicate              dead, unreachable, out of range, no item, no room, ...     -> illegal:<reason>
    4 rate/risk  per-actor rate cap, destructive gate                                                             -> rate_limited | risk_gated
    5 plan       fn(world, ctx, **args) -> ActionDraft  pure; undeclared item creation is refused                  -> refused:<reason> | undeclared_item_creation
    6 apply      world.apply(effects + event, atomic, cause="action:<verb>"); re-checks 1-5 if the revision moved    -> stale_plan | apply_failed
    7 ops        RecordOps (task queue, schedule routine, relationship, commission order, request response)       -> reported in the audit, never roll the effects back
    8 audit      one entry per call, accepted or rejected

A rejection changes nothing. ``dry_run`` stops after step 5. Item creation/destruction (H-Q1): the harness applier refuses ``Transfer``
with ``src`` or ``dst`` None unless the apply carries an ``ItemPermit``; the runner builds one from the draft's ``consumes``/``produces``
(summed per item) and passes it as ``world.apply(..., items=permit)``, so the permit lasts for that one apply and nothing global is toggled.
Step 5 still checks every such Transfer against the draft's declaration first, which gives the stable ``undeclared_item_creation`` code.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from harness import effects as fx
from harness.registry import Registry
from systems.affordance.engine import AffordanceEngine

from . import catalog
from .audit import AuditLog
from .draft import ActionDraft, ActionRefused
from .recordops import NullRecordOps, RecordOps

ID_PARAMS = {"target": "target", "source": "target", "node": "target", "container": "target", "place": "place", "recipe": "recipe", "item": "item",
             "give": "item", "want": "item", "about": "resident", "event": "event"}
DESTRUCTIVE_PROPOSERS_OK = ("rules",)


@dataclass
class RateConfig:
    window_ticks: int = 20
    max_calls: int = 8            # accepted calls per actor per window


@dataclass
class RiskConfig:
    min_confidence: float = 0.6   # a non-rules proposer needs at least this top_p for a destructive verb


@dataclass
class ActionContext:
    """What an Action function may read besides ``world``: who acts, the legality verdict it was accepted under, the situation."""
    actor: str
    services: object
    verdict: object
    situation: object
    tick: int
    proposer: str = "rules"
    confidence: Optional[float] = None
    record: Optional[dict] = None

    @property
    def obs(self):
        return self.situation.obs

    @property
    def has_anchors(self) -> bool:
        """The resident has roster anchors (whoever drives it): the schedule routine and a site trip are meaningful for it."""
        return bool((self.record or {}).get("roster"))

    @property
    def is_roster(self) -> bool:
        from systems.roster.driver import is_anchor_driven      # an agent-driven roster resident takes the task branch like any other
        return is_anchor_driven((self.record or {}).get("roster"))


@dataclass
class ActionResult:
    ok: bool
    code: str                     # "ok" or the stable rejection code
    verb: str
    actor: str
    args: dict
    detail: dict = field(default_factory=dict)
    draft: Optional[ActionDraft] = None
    report: object = None
    ops: list = field(default_factory=list)
    audit: Optional[dict] = None
    revision: int = 0


class ActionRunner:
    def __init__(self, world, services, *, registry: Optional[Registry] = None, aff: Optional[AffordanceEngine] = None,
                 record_ops: Optional[RecordOps] = None, audit: Optional[AuditLog] = None, rate: Optional[RateConfig] = None,
                 risk: Optional[RiskConfig] = None):
        self.world, self.services = world, services
        self._registry = registry          # None: ``resource_verbs.default_registry()``, looked up per call (the node verbs follow EDEN_MAP_RESOURCES)
        self.aff = aff or AffordanceEngine(world, services)
        self.record_ops = record_ops or NullRecordOps()
        self.audit = audit or AuditLog()
        self.rate, self.risk = rate or RateConfig(), risk or RiskConfig()
        self._recent: dict = {}          # actor -> list of accepted-call ticks

    @property
    def registry(self) -> Registry:
        if self._registry is not None:
            return self._registry
        from .resource_verbs import default_registry
        return default_registry()

    @registry.setter
    def registry(self, value) -> None:
        self._registry = value

    # -- the pipeline -------------------------------------------------------------------------------------------------
    def run(self, actor: str, verb: str, args: Optional[dict] = None, *, proposer: str = "rules", confidence: Optional[float] = None,
            dry_run: bool = False) -> ActionResult:
        began = time.perf_counter()
        planned = self.plan(actor, verb, args, proposer=proposer, confidence=confidence)
        if not planned.ok or dry_run:
            return self._finish(planned, began, proposer, confidence, dry_run=dry_run)
        return self._finish(self.apply(planned, proposer=proposer, confidence=confidence), began, proposer, confidence)

    def plan(self, actor: str, verb: str, args: Optional[dict] = None, *, proposer: str = "rules", confidence: Optional[float] = None) -> ActionResult:
        result = ActionResult(False, "", str(verb), str(actor), dict(args) if isinstance(args, dict) else {}, revision=self.world.revision)
        if not isinstance(verb, str) or not verb:
            return self._reject(result, "unknown_action", why="verb must be a non-empty string")
        if args is not None and not isinstance(args, dict):
            return self._reject(result, "invalid_arguments", errors=["$: arguments must be an object"])
        args = dict(args or {})
        if verb in catalog.FROZEN_LEGACY:
            return self._reject(result, "legacy_frozen")
        # 1 schema
        if verb not in self.registry.actions:
            return self._reject(result, "not_implemented" if verb in catalog.BY_ID else "unknown_action", known=len(self.registry.actions))
        errors = self.registry.validate_call(verb, args, "action")
        if errors:
            return self._reject(result, "invalid_arguments", errors=errors)
        # 2 grounding
        table = self.world.table("humans")
        if not isinstance(actor, str) or table.slot_of(actor) is None:
            return self._reject(result, "unknown_actor")
        bad = self._ungrounded(args)
        if bad:
            return self._reject(result, bad[0], param=bad[1], value=str(args.get(bad[1])))
        # 3 legality
        situation = self.aff.situation(actor)
        verdict = self.aff.legal(actor, verb, args, situation=situation)
        if not verdict.ok:
            return self._reject(result, f"illegal:{verdict.reason}", **dict(verdict.detail or {}))
        # 4 rate / risk
        spec = self.registry.actions[verb]
        tick = int(self.world.tick)
        if self._rate_limited(actor, tick):
            return self._reject(result, "rate_limited", window=self.rate.window_ticks, max_calls=self.rate.max_calls)
        if spec.extra.get("risk") != "reversible" and not str(proposer).startswith(DESTRUCTIVE_PROPOSERS_OK) \
                and (confidence is None or float(confidence) < self.risk.min_confidence):
            return self._reject(result, "risk_gated", risk=spec.extra.get("risk"), confidence=confidence, needed=self.risk.min_confidence)
        # 5 plan
        ctx = ActionContext(actor, self.services, verdict, situation, tick, proposer, confidence, self.services.record(actor))
        try:
            draft = spec.fn(self.world, ctx, **args)
        except ActionRefused as refusal:
            return self._reject(result, f"refused:{refusal.reason}", why=refusal.detail)
        undeclared = self._undeclared_creation(draft)
        if undeclared:
            return self._reject(result, "undeclared_item_creation", transfer=undeclared)
        result.ok, result.code, result.draft, result.revision = True, "ok", draft, self.world.revision
        result.detail = {"verdict": dict(verdict.detail or {}), "reachability": verdict.reachability, "distance": verdict.distance}
        return result

    def apply(self, planned: ActionResult, *, proposer: str = "rules", confidence: Optional[float] = None) -> ActionResult:
        if not planned.ok:
            return planned
        if planned.revision != self.world.revision:           # something changed since the plan: judge the call again from scratch
            again = self.plan(planned.actor, planned.verb, planned.args, proposer=proposer, confidence=confidence)
            if not again.ok:
                again.detail = {**again.detail, "replanned": True, "was": planned.code}
                return again
            planned = again
            planned.detail["replanned"] = True
        draft = planned.draft
        effects = list(draft.effects) + ([draft.event] if draft.event is not None else [])
        permit = self._permit(draft)
        report = self.world.apply(effects, atomic=True, cause=f"action:{planned.verb}", items=permit) if effects else None
        planned.report = report
        if report is not None and not report.ok:
            planned.ok, planned.code = False, "apply_failed"
            planned.detail = {**planned.detail, "skipped": [(s.kind, s.reason, s.detail) for s in report.skipped]}
            return planned
        self._recent.setdefault(planned.actor, []).append(int(self.world.tick))
        for op in draft.ops:
            planned.ops.append({"kind": op.kind, **self._execute_op(op, planned)})
        planned.revision = self.world.revision
        return planned

    # -- helpers ------------------------------------------------------------------------------------------------------
    def _execute_op(self, op, planned: ActionResult) -> dict:
        tick = int(self.world.tick)
        if op.kind == "request_response":
            return self._request_response(planned, tick, **op.args)
        if op.kind == "trade_offer":
            return self._trade_offer(planned, tick, **op.args)
        if op.kind == "trade_close":
            from .offers import offers_of
            offers_of(self.services).close(op.args["offer"])
            return {"ok": True}
        if op.kind == "theft_consequence":
            return self._theft_consequence(planned, tick, **op.args)
        if op.kind in ("market_sale", "price_set"):
            from systems.market.ops import execute
            return execute(op, self.services, planned.actor, tick)
        if op.kind in ("loan_open", "loan_pay"):
            from systems.credit.ops import execute
            return execute(op, self.services, planned.actor, tick)
        if op.kind == "loan_request":
            return self._loan_request(planned, tick, **op.args)
        if op.kind == "job_close":
            from systems.labour.ops import execute
            return execute(op, self.services, planned.actor, tick)
        if op.kind == "job_request":
            return self._job_request(planned, tick, **op.args)
        if op.kind == "case_close":
            from systems.justice.ops import execute
            return execute(op, self.services, planned.actor, tick)
        if op.kind == "report_request":
            return self._report_request(planned, tick, **op.args)
        if op.kind in ("fire_light", "wound_treat"):
            return self._care_op(op.kind, **op.args)
        if op.kind == "restrain":
            return self._restrain(**op.args)
        if op.kind == "post_open":
            from systems.guard.ops import execute
            return execute(op, self.services, planned.actor, tick)
        return self.record_ops.execute(op, planned.actor, tick)

    def _care_op(self, kind: str, **args) -> dict:
        """EDEN_TEMPERATURE / EDEN_WOUNDS: register a warmth source, or dress a wound (the instinct state lives on the engine behind the record ops)."""
        engine = getattr(self.record_ops, "engine", None)
        if engine is None:
            return {"ok": False, "reason": "no_engine"}
        if kind == "fire_light":
            from harness import temperature
            source = temperature.add_source(engine, args["x"], args["y"], ticks=int(args["ticks"]))
            return {"ok": True, "until": source["until"]}
        from harness import wounds
        done = wounds.treat(engine, args["target"], float(args["strength"]))
        return {"ok": True} if done else {"ok": False, "reason": "no_wound"}

    def _restrain(self, target: str, ticks: int) -> dict:
        """EDEN_ROB: hold a resident in place through the harness restraint (needs the live engine behind the record ops)."""
        from harness import restraint
        engine = getattr(self.record_ops, "engine", None)
        if engine is None:
            return {"ok": False, "reason": "no_engine"}
        slot = engine._human_slot_for_id(target)
        if slot is None or slot < 0:
            return {"ok": False, "reason": "unknown_target"}
        held = restraint.restrain(engine, slot, int(ticks))
        return {"ok": held, "ticks": int(ticks)} if held else {"ok": False, "reason": "not_restrained"}

    def _theft_consequence(self, planned: ActionResult, tick: int, owner_kind: str, owner: str, item: str, qty: int, violent: bool = False) -> dict:
        """EDEN_REPUTATION: schedule how the loss comes to light (``actions/reputation.record_theft``). Needs the live engine behind the record ops."""
        from . import reputation
        engine = getattr(self.record_ops, "engine", None)
        events = getattr(planned.report, "events", None) or []
        if engine is None or not events:
            return {"ok": False, "reason": "no_engine" if engine is None else "no_event"}
        return reputation.record_theft(engine, self.world, planned.actor, owner_kind, owner, item, qty, events[-1].id, tick, violent=violent)

    def _request_response(self, planned: ActionResult, tick: int, target: str, item: str, qty: int) -> dict:
        """The asked resident decides by rules (``verbs.economy.respond_to_request``) and, on ``give``, gives through this same runner."""
        from .verbs.economy import respond_to_request
        answer = respond_to_request(self.world, self.services, planned.actor, target, item, qty)
        out = {"ok": True, "answer": answer["answer"], "item": answer.get("item", item)}
        if answer["answer"] == "give":
            given = self.run(target, "give_item", {"target": planned.actor, "item": answer["item"], "qty": int(qty)}, proposer="rules:request_response")
            out["gave"] = given.ok
            out["give_code"] = given.code
        return out

    def _loan_request(self, planned: ActionResult, tick: int, target: str, item: str, qty: int) -> dict:
        """The asked resident decides by rules (``credit_verbs.respond_to_loan``) and, on ``lend``, lends through this same runner."""
        from .credit_verbs import respond_to_loan
        answer = respond_to_loan(self.world, self.services, planned.actor, target, item, qty)
        out = {"ok": True, "answer": answer["answer"], "item": answer.get("item", item)}
        if answer["answer"] == "lend":
            lent = self.run(target, "lend_item", {"target": planned.actor, "item": answer["item"], "qty": int(qty)}, proposer="rules:loan_response")
            out["lent"], out["lend_code"] = lent.ok, lent.code
        return out

    def _report_request(self, planned: ActionResult, tick: int, target: str, about: str, item: str, qty: int, victim: str) -> dict:
        """The asked authority decides by rules (``justice_verbs.respond_to_report``); a yes opens a case on the docket."""
        from .justice_verbs import respond_to_report
        from .gameclock import day_ticks
        from .offers import item_value
        from systems.justice import runtime
        answer = respond_to_report(self.world, self.services, planned.actor, target, about, victim, tick)
        out = {"ok": True, "answer": answer["answer"], "opened": False}
        if answer["answer"] == "accept":
            case = runtime.of(self.services).open(about, victim, target, planned.actor, item, qty, item_value(item) * int(qty), tick, day_ticks())
            out.update(opened=True, case=case.id, expires=case.expires)
        return out

    def _job_request(self, planned: ActionResult, tick: int, target: str) -> dict:
        """The asked resident decides by rules (``labour_verbs.respond_to_job``); a yes opens a job (nothing moves until ``collect_wage``)."""
        from .labour_verbs import respond_to_job
        from systems.labour import runtime
        book = runtime.of(self.services)
        book.lapse(tick)
        answer = respond_to_job(self.world, self.services, planned.actor, target, tick)
        out = {"ok": True, "answer": answer["answer"], "hired": False}
        if answer["answer"] == "hire":
            job = book.hire(target, planned.actor, answer["item"], answer["qty"], tick)
            out.update(hired=True, job=job.id, ready_at=job.ready_at, expires=job.expires, item=job.item, qty=job.qty)
        return out

    def _trade_offer(self, planned: ActionResult, tick: int, target: str, give: str, give_qty: int, want: str, want_qty: int) -> dict:
        """Open the offer, let the asked resident answer by rules (``verbs.economy.respond_to_trade``); an accept is an ``accept_trade`` call through this runner."""
        from .offers import offers_of
        from .verbs.economy import respond_to_trade
        book = offers_of(self.services)
        offer_id = book.open(planned.actor, target, give, give_qty, want, want_qty, tick)
        answer = respond_to_trade(self.world, self.services, planned.actor, target, give, give_qty, want, want_qty)
        out = {"ok": True, "offer": offer_id, "answer": answer}
        if answer == "accept":
            done = self.run(target, "accept_trade", {"offer": offer_id}, proposer="rules:trade_response")
            out["accepted"], out["accept_code"] = done.ok, done.code
        if answer != "accept" or not out["accepted"]:
            book.close(offer_id)
        return out

    def _ungrounded(self, args: dict):
        table = self.world.table("humans")
        for name, value in args.items():
            kind = ID_PARAMS.get(name)
            if kind is None or not isinstance(value, str) or value == "":
                continue
            if kind == "target":
                if name == "target":
                    if table.slot_of(value) is None:
                        return "ungrounded_target", name
                elif value not in {e.id for e in self.services.entities()}:
                    return "ungrounded_target", name
            elif kind == "place":
                if value not in self._place_ids():
                    return "ungrounded_place", name
            elif kind == "recipe":
                from systems.crafting.resolver import crafting_recipe_ids
                if value not in crafting_recipe_ids():
                    return "ungrounded_recipe", name
            elif kind == "item":
                from systems.inventory.schema import item_kind_def
                if not item_kind_def(value):
                    return "ungrounded_item", name
            elif kind == "resident":
                if table.slot_of(value) is None:
                    return "ungrounded_target", name
            elif kind == "event":
                ledger = getattr(self.world, "events", None)
                if ledger is None or ledger.get(value) is None:
                    return "ungrounded_event", name
        return None

    def _place_ids(self) -> set:
        ids = set()
        for actor in self.world.table("humans").ids:
            if actor is None:
                continue
            ids.update(a.id for a in self.services.anchors(actor).values())
            ids.update(a.id for a in self.services.sites(actor).values() if a is not None)
        ids.update(e.id for e in self.services.entities())
        return ids

    def _rate_limited(self, actor: str, tick: int) -> bool:
        window = [t for t in self._recent.get(actor, []) if tick - t < self.rate.window_ticks]
        self._recent[actor] = window
        return len(window) >= self.rate.max_calls

    @staticmethod
    def _permit(draft: ActionDraft):
        """The draft's declared consumption/production as a harness ``ItemPermit`` (quantities summed per item), None when it declares nothing."""
        if not (draft.consumes or draft.produces):
            return None
        from harness.effects import ItemPermit

        def total(pairs):
            out: dict = {}
            for item, qty in pairs:
                out[item] = out.get(item, 0) + int(qty)
            return out
        return ItemPermit(consume=total(draft.consumes), produce=total(draft.produces))

    @staticmethod
    def _undeclared_creation(draft: ActionDraft):
        declared_out = {(i, int(q)) for i, q in draft.consumes}
        declared_in = {(i, int(q)) for i, q in draft.produces}
        for e in draft.effects:
            if isinstance(e, fx.Transfer):
                if e.dst is None and (e.item, e.qty) not in declared_out:
                    return (e.item, e.qty, "destroy")
                if e.src is None and (e.item, e.qty) not in declared_in:
                    return (e.item, e.qty, "create")
        return None

    def _reject(self, result: ActionResult, code: str, **detail) -> ActionResult:
        result.ok, result.code, result.detail = False, code, detail
        return result

    def _finish(self, result: ActionResult, began: float, proposer: str, confidence, dry_run: bool = False) -> ActionResult:
        draft = result.draft
        entry = {"tick": int(self.world.tick), "actor": result.actor, "verb": result.verb, "args": result.args, "proposer": proposer,
                 "confidence": confidence, "ok": result.ok, "code": result.code, "dry_run": dry_run, "detail": result.detail,
                 "effects": len(draft.effects) if draft is not None else 0, "ops": result.ops,
                 "applied": bool(result.report is not None and result.report.ok) if not dry_run else False,
                 "revision": self.world.revision, "ms": round((time.perf_counter() - began) * 1000.0, 3)}
        result.audit = self.audit.record(entry)
        return result
