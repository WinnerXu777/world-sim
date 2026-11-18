"""Harvest already grown farm food into declared inventory, behind economy balance."""
from harness import effects as fx
from harness.registry import Registry, action
from .draft import ActionDraft
from .verbs.common import emit

ECONOMY_REGISTRY = Registry()


@action("harvest_farm", risk="reversible", precondition="can_harvest_farm", produces=("crop_bundle",), registry=ECONOMY_REGISTRY)
def harvest_farm(world, ctx, farm="", qty=1):
    stock = float(world.table("entities").get(farm, "food"))
    detail = {"farm": farm, "item": "crop_bundle", "qty": qty}
    return ActionDraft([fx.Set("entities", (farm,), "food", stock - qty), fx.Transfer("crop_bundle", qty, None, ctx.actor)],
                       emit(world, ctx.actor, "farm_harvested", detail), [], detail, produces=(("crop_bundle", qty),))
