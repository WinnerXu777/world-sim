"""Robbery and arrest (``EDEN_ROB=1``): ``rob`` and ``arrest_or_restrain`` (``systems/rob``, ``1008_actions.md`` section 10.20).

On their own ``ROB_REGISTRY`` (``default_registry()`` adds it while the flag is on). Both are destructive: the runner's risk gate lets only the rules proposer through.

* ``rob(target, item?, qty?)``: the victim resists. One deterministic draw (``world.rng("rob", ...)``) against ``rob.p_success`` (hp, temper, a guard over the victim). On a win the goods move
  victim -> robber (declared Transfer), the victim loses ``ROB_DAMAGE`` hp, the culprit is known at once (``theft_consequence`` with ``violent``) and the victim's regard drops again; on a loss the robber
  loses ``ROB_BACKLASH`` hp, the victim keeps its goods and holds the attempt against the robber. Either way it is a ledger event within sight (``local``, radius 80).
* ``arrest_or_restrain(target)``: an authority holds a robber on record for ``ARREST_TICKS`` through ``harness/restraint.py``; the restraint counter then runs out by itself.
"""
from __future__ import annotations

from harness.registry import Registry, action

from .draft import ActionDraft, RecordOp
from .verbs.common import bounded_delta, emit

ROB_REGISTRY = Registry()
VICTIM_GRUDGE = -0.12         # the victim's closeness to the robber after a robbery (on top of the theft opinion drop) or a failed attempt
ARREST_GRUDGE = -0.10         # the held robber's closeness to the authority


@action("rob", risk="destructive", precondition="can_rob", registry=ROB_REGISTRY)
def rob(world, ctx, target: str = "", item: str = "", qty: int = 0) -> ActionDraft:
    """Take food from ``target``'s pack by force; the victim may fight the robber off."""
    from harness import effects as fx
    from systems import rob as rules
    me, detail = ctx.actor, dict(ctx.verdict.detail)
    won = float(world.rng("rob", f"{me}>{target}").random()) < float(detail["p"])
    said = {"to": target, "item": detail["item"], "qty": int(detail["qty"]), "guarded": bool(detail["guarded"]), "won": won}
    if won:
        effects = [fx.Transfer(detail["item"], int(detail["qty"]), target, me), bounded_delta(world, target, "hp", -rules.ROB_DAMAGE)]
        ops = [RecordOp("theft_consequence", {"owner_kind": "resident", "owner": target, "item": detail["item"], "qty": int(detail["qty"]), "violent": True}),
               RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": VICTIM_GRUDGE})]
        return ActionDraft(effects, emit(world, me, "robbery", said, others=(target,)), ops, said)
    effects = [bounded_delta(world, me, "hp", -rules.ROB_BACKLASH)]
    ops = [RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": VICTIM_GRUDGE})]
    return ActionDraft(effects, emit(world, me, "robbery_failed", said, others=(target,)), ops, said)


@action("arrest_or_restrain", risk="destructive", precondition="holds_authority", registry=ROB_REGISTRY)
def arrest_or_restrain(world, ctx, target: str = "") -> ActionDraft:
    """The authority holds the robber in place for ``ARREST_TICKS``."""
    me, ticks = ctx.actor, int(ctx.verdict.detail["ticks"])
    ops = [RecordOp("restrain", {"target": target, "ticks": ticks}),
           RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": ARREST_GRUDGE})]
    said = {"target": target, "ticks": ticks}
    return ActionDraft([], emit(world, me, "arrested", said, others=(target,)), ops, said)
