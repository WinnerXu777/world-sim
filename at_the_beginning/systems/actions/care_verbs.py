"""Care verbs: ``light_fire`` (``EDEN_TEMPERATURE=1``) and ``treat_wound`` (``EDEN_WOUNDS=1``) (``1008_actions.md`` section 10.21).

On their own ``CARE_REGISTRY`` (``default_registry()`` adds it while either instinct flag is on; each predicate answers ``not_wired`` for its own flag off). Both are reversible and consume one declared
item: ``light_fire`` burns a ``wood_bundle`` and registers a warmth source at the spot through ``temperature.add_source`` (op ``fire_light``, needs the engine behind the record ops);
``treat_wound`` uses a ``bandage`` (stops the bleed) or a ``herb_bundle`` (stops 60 % of it) through ``wounds.treat`` (op ``wound_treat``) on the actor or on a neighbour in reach.
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import Registry, action

from .draft import ActionDraft, RecordOp
from .verbs.common import emit

CARE_REGISTRY = Registry()
FIRE_TICKS = 1200          # how long a lit bundle burns
THANKS = 0.04              # the one treated holds the carer dearer


@action("light_fire", risk="reversible", precondition="can_light_fire", registry=CARE_REGISTRY)
def light_fire(world, ctx, place: str = "", fuel: str = "") -> ActionDraft:
    """Burn a bundle of wood to warm the spot (the actor's own, or a place within reach)."""
    detail = dict(ctx.verdict.detail)
    ops = [RecordOp("fire_light", {"x": detail["x"], "y": detail["y"], "ticks": FIRE_TICKS})]
    said = {"at": [detail["x"], detail["y"]], "ticks": FIRE_TICKS}
    return ActionDraft([fx.Transfer(detail["fuel"], 1, ctx.actor, None)], emit(world, ctx.actor, "fire_lit", said), ops, said, consumes=((detail["fuel"], 1),))


@action("treat_wound", risk="reversible", precondition="can_treat", registry=CARE_REGISTRY)
def treat_wound(world, ctx, target: str = "", item: str = "") -> ActionDraft:
    """Dress a bleeding wound (own or a neighbour's) with a bandage or herbs from the pack."""
    detail = dict(ctx.verdict.detail)
    subject = detail["subject"]
    ops = [RecordOp("wound_treat", {"target": subject, "strength": detail["strength"]})]
    others = ()
    if subject != ctx.actor:
        others = (subject,)
        ops.append(RecordOp("relationship", {"owner": subject, "other": ctx.actor, "kind": "known", "delta": THANKS}))
    said = {"subject": subject, "item": detail["item"], "strength": detail["strength"]}
    return ActionDraft([fx.Transfer(detail["item"], 1, ctx.actor, None)], emit(world, ctx.actor, "wound_treated", said, others=others), ops, said, consumes=((detail["item"], 1),))
