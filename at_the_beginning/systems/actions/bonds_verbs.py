"""Bond verbs (``EDEN_BONDS=1``): ``court``, ``befriend``, ``apologise``, ``forgive`` (``1008_actions.md`` section 10.16).

On their own ``BONDS_REGISTRY`` (``default_registry()`` adds them while the flag is on). Every effect is a relationship step on the two records (``RecordOp("relationship")``) plus an
event; the amounts come from the predicate's detail (computed from the records at the same instant, so the legality check and the effect cannot disagree).
"""
from __future__ import annotations

from harness.registry import Registry, action

from .draft import ActionDraft, RecordOp
from .verbs.common import emit

BONDS_REGISTRY = Registry()


def _both(me: str, target: str, delta_mine: float, delta_theirs: float) -> list:
    return [RecordOp("relationship", {"other": target, "kind": "known", "delta": delta_mine}),
            RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": delta_theirs})]


@action("befriend", risk="reversible", precondition="can_befriend", registry=BONDS_REGISTRY)
def befriend(world, ctx, target: str = "") -> ActionDraft:
    """Spend time with a neighbour: both closeness values rise a little (up to the cap)."""
    step = ctx.verdict.detail["step"]
    return ActionDraft([], emit(world, ctx.actor, "befriended", {"to": target, "step": step}, others=(target,)), _both(ctx.actor, target, step, step), {"target": target, "step": step})


@action("court", risk="reversible", precondition="can_court", registry=BONDS_REGISTRY)
def court(world, ctx, target: str = "") -> ActionDraft:
    """Courtship without mating: a slow two-way closeness step, only between residents who already like each other."""
    step = ctx.verdict.detail["step"]
    return ActionDraft([], emit(world, ctx.actor, "courted", {"to": target, "step": step}, others=(target,)), _both(ctx.actor, target, step, step), {"target": target, "step": step})


@action("apologise", risk="reversible", precondition="has_harmed", registry=BONDS_REGISTRY)
def apologise(world, ctx, target: str = "", event: str = "") -> ActionDraft:
    """Say sorry to someone who holds a grudge against the actor: the listener's closeness moves toward 0 (by its mercy; half against a thief tag)."""
    effect = ctx.verdict.detail["effect"]
    from systems.bonds.rules import SELF_RELIEF
    ops = [RecordOp("relationship", {"owner": target, "other": ctx.actor, "kind": "known", "delta": effect}),
           RecordOp("relationship", {"other": target, "kind": "known", "delta": SELF_RELIEF}),
           RecordOp("memory_note", {"owner": target, "kind": "heard_apology", "other": ctx.actor, "event": event, "about": "", "event_kind": "apology"})]
    return ActionDraft([], emit(world, ctx.actor, "apologised", {"to": target, "effect": effect, **({"event": event} if event else {})}, others=(target,)), ops,
                       {"target": target, "effect": effect})


@action("forgive", risk="reversible", precondition="has_grudge", registry=BONDS_REGISTRY)
def forgive(world, ctx, target: str = "") -> ActionDraft:
    """Let a grudge go: the actor's own closeness to the target moves toward 0 (never past it)."""
    delta = ctx.verdict.detail["delta"]
    ops = [RecordOp("relationship", {"other": target, "kind": "known", "delta": delta})]
    return ActionDraft([], emit(world, ctx.actor, "forgave", {"target": target, "delta": delta}, others=(target,)), ops, {"target": target, "delta": delta})
