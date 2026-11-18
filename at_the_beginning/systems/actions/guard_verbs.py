"""The ``defend`` verb (``EDEN_DEFEND=1``): stand guard over a person (``target``) or a place (``place``) for ``GUARD_TICKS`` (``systems/guard``, ``1008_defend_design.md`` Phase 0).

On its own ``GUARD_REGISTRY`` (``default_registry()`` adds it while the flag is on). The verb opens a post in the guard book (the runner's ``post_open`` op) and says so; the post is what the
combat hook reads (``systems/guard/modifier.py``) and what the guard pass keeps the guard close to (``guard_day``). Reversible: a post only ever ends, nothing is destroyed.
"""
from __future__ import annotations

from harness.registry import Registry, action

from .draft import ActionDraft, RecordOp
from .verbs.common import emit

GUARD_REGISTRY = Registry()
THANKS = 0.03          # the person guarded holds the guard slightly dearer


@action("defend", risk="reversible", precondition="can_defend", registry=GUARD_REGISTRY)
def defend(world, ctx, target: str = "", place: str = "") -> ActionDraft:
    """Open a guard post over ``target`` (a person in reach) or ``place`` (a place the actor perceives)."""
    from systems.guard import GUARD_RADIUS, GUARD_TICKS
    detail = dict(ctx.verdict.detail)
    kind, charge = detail["kind"], detail["charge"]
    until = int(ctx.tick) + GUARD_TICKS
    ops = [RecordOp("post_open", {"kind": kind, "charge": charge, "until": until, "radius": GUARD_RADIUS})]
    others = ()
    if kind == "person":
        others = (charge,)
        ops.append(RecordOp("relationship", {"owner": charge, "other": ctx.actor, "kind": "known", "delta": THANKS}))
    said = {"kind": kind, "charge": charge, "until": until}
    return ActionDraft([], emit(world, ctx.actor, "began_guarding", said, others=others), ops, said)
