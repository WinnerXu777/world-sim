"""Work verbs: go_to_work, work_shift, gather_resource, craft, store_item, fetch_item.

``craft``, ``store_item`` and ``fetch_item`` are atomic item effects (conservation-checked by the harness applier); the others queue the
legacy task that does the work, or set the schedule routine for a roster resident.
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import action

from ..draft import ActionDraft, ActionRefused, queue_task, roster_driven, set_routine
from . import REGISTRY
from .common import bounded_delta, emit


@action("go_to_work", risk="reversible", precondition="has_work_anchor", registry=REGISTRY)
def go_to_work(world, ctx, place: str = "") -> ActionDraft:
    """Walk to the work anchor: the ``work_site`` routine for a roster resident, a ``move_to_place`` task for anyone else."""
    anchor = ctx.obs.anchors["work"]
    if ctx.has_anchors:
        ops = [set_routine("work_site", reason="action:go_to_work")]
    else:
        ops = [queue_task("move_to_place", priority=0.35, summary="go to work", target_kind="place", target_id=anchor.id,
                          target_place={"x": anchor.x, "y": anchor.y}, metadata={"via": "action"})]
    return ActionDraft([], emit(world, ctx.actor, "went_to_work", {"place": anchor.id}, visibility="private"), ops,
                       {"route": "routine" if ctx.has_anchors else "tasks", "place": anchor.id})


@action("work_shift", risk="reversible", precondition="can_work", registry=REGISTRY)
def work_shift(world, ctx) -> ActionDraft:
    """Do the occupation's work task (chop_wood, fish_work, farm_work, build_work, gather_work, hunt_work, heal_work, trade_run, patrol_area)."""
    from systems.tasks.families.occupation import suggested_occupation_task_kind
    record = ctx.record or {}
    kind = suggested_occupation_task_kind(record)
    if kind in ("idle", "return_home", "socialize"):
        raise ActionRefused("no_work_task", f"occupation {ctx.obs.occupation!r} has no work task of its own")
    roster_driven(ctx, "work tasks need a worksite the task system resolves itself; for a roster resident they stay active and do nothing")
    ops = [queue_task(kind, priority=0.6, summary=f"work shift: {kind}", metadata={"via": "action", "occupation": ctx.obs.occupation})]
    return ActionDraft([], emit(world, ctx.actor, "began_work_shift", {"task": kind}, visibility="private"), ops, {"task": kind})


@action("gather_resource", risk="reversible", precondition="resource_reachable", registry=REGISTRY)
def gather_resource(world, ctx, source: str = "", qty: int = 1) -> ActionDraft:
    """Collect the material a gather node yields (the legacy ``gather_material`` task, by item kind)."""
    item = ctx.verdict.detail["item"]
    roster_driven(ctx, "gathering needs the resident to walk to the node; the anchor driver returns a roster resident to its anchor")
    ops = [queue_task("gather_material", priority=0.6, summary=f"gather {item}", target_kind="item", target_id=item,
                      requested_quantity=int(qty), metadata={"via": "action", "source": source})]
    return ActionDraft([], emit(world, ctx.actor, "began_gathering", {"item": item, "source": source}, visibility="private"), ops,
                       {"item": item, "source": source, "qty": int(qty)})


@action("craft", risk="reversible", precondition="recipe_craftable", registry=REGISTRY)
def craft(world, ctx, recipe: str = "", qty: int = 1) -> ActionDraft:
    """Craft at the station in reach: ingredients are consumed and the output is created in the same atomic apply (the recipe's time cost is not modelled here)."""
    from systems.crafting.resolver import crafting_recipe_def, crafting_recipe_ingredients
    detail = ctx.verdict.detail
    me, n = ctx.actor, int(qty)
    consumed = tuple((str(i["item_kind"]), int(i.get("quantity", 1)) * n) for i in crafting_recipe_ingredients(recipe))
    produced = ((str(detail["output"]), int(detail["quantity"])),)
    effects = [fx.Transfer(item, q, me, None) for item, q in consumed] + [fx.Transfer(produced[0][0], produced[0][1], None, me)]
    effects.append(bounded_delta(world, me, "mood", 0.2))
    return ActionDraft(effects, emit(world, me, "crafted", {"recipe": recipe, "output": produced[0][0], "quantity": produced[0][1]}), [],
                       {"recipe": recipe, "consumes": dict(consumed), "produces": dict(produced), "time_cost": crafting_recipe_def(recipe).get("time_cost")},
                       consumes=consumed, produces=produced)


@action("store_item", risk="reversible", precondition="storage_reachable", registry=REGISTRY)
def store_item(world, ctx, item: str = "", qty: int = 1, container: str = "") -> ActionDraft:
    effects = [fx.Transfer(item, int(qty), ctx.actor, container)]
    return ActionDraft(effects, emit(world, ctx.actor, "stored_item", {"item": item, "qty": int(qty), "container": container}), [],
                       {"item": item, "qty": int(qty), "container": container})


@action("fetch_item", risk="reversible", precondition="item_in_storage", registry=REGISTRY)
def fetch_item(world, ctx, item: str = "", qty: int = 1, container: str = "") -> ActionDraft:
    effects = [fx.Transfer(item, int(qty), container, ctx.actor)]
    return ActionDraft(effects, emit(world, ctx.actor, "fetched_item", {"item": item, "qty": int(qty), "container": container}), [],
                       {"item": item, "qty": int(qty), "container": container})
