"""Survival verbs: eat, drink, rest, sleep, flee_to, seek_shelter, hide.

Atomic part first (a ration from the pack is an item Transfer plus the need deltas, exactly the numbers of the legacy ``eat_food`` handler);
anything that needs walking or a source in the world is a queued legacy task, or, for a roster resident (whose task movement is suppressed),
the schedule-routine route. Which route works on which resident is measured in ``tests/test_actions_roster.py`` and written up in
``1008_actions.md`` section 10.
"""
from __future__ import annotations

import genesis_config as cfg
from harness import effects as fx
from harness.registry import action
from systems.affordance.config import EDIBLE_ITEMS

from ..draft import ActionDraft, queue_task, roster_driven, set_routine, site_trip
from . import REGISTRY
from .common import bounded_delta, emit, read

HIDE_TICKS = 8       # placeholder: the legacy default hold of wait_in_hiding


@action("eat", risk="reversible", precondition="can_eat", consumes=EDIBLE_ITEMS, registry=REGISTRY)
def eat(world, ctx, item: str = "", place: str = "") -> ActionDraft:
    """Eat an edible item from the pack, or go to the food source (a site or a food resource)."""
    detail = ctx.verdict.detail or {}
    me = ctx.actor
    if detail.get("source") == "pack":
        kind = str(detail["item"])
        effects = [fx.Transfer(kind, 1, me, None), bounded_delta(world, me, "hunger", -float(cfg.EAT_HUNGER_RESTORE)),
                   bounded_delta(world, me, "mood", 0.25), bounded_delta(world, me, "stamina", 0.4)]
        return ActionDraft(effects, emit(world, me, "ate", {"item": kind, "source": "pack"}), [], {"item": kind, "source": "pack"},
                           consumes=((kind, 1),))
    roster_driven(ctx, "a roster resident eats at its food site through the roster needs loop when hunger reaches the threshold")
    if ctx.has_anchors and detail.get("source") == "site":          # an agent-driven roster resident: the needs loop's own trip, started now
        return ActionDraft([], emit(world, me, "went_to_eat", {"place": detail.get("place", "")}, visibility="private"), [site_trip("food")],
                           {"source": "site", "place": detail.get("place"), "route": "site_trip"})
    task = queue_task("eat_food", priority=0.9, summary="source nearby food", target_kind="resource", target_id="food",
                      metadata={"via": "action", "place": detail.get("place", "")})
    return ActionDraft([], emit(world, me, "went_to_eat", {"place": detail.get("place", "")}, visibility="private"), [task],
                       {"source": detail.get("source"), "place": detail.get("place")})


@action("drink", risk="reversible", precondition="can_drink", registry=REGISTRY)
def drink(world, ctx, place: str = "") -> ActionDraft:
    """Go to a water source and drink (the legacy ``fetch_water`` task does the drinking)."""
    detail = ctx.verdict.detail or {}
    roster_driven(ctx, "a roster resident drinks at its water site through the roster needs loop when thirst reaches the threshold")
    if ctx.has_anchors and detail.get("source") == "site":
        return ActionDraft([], emit(world, ctx.actor, "went_to_drink", {"place": detail.get("place", "")}, visibility="private"), [site_trip("water")],
                           {"source": "site", "place": detail.get("place"), "route": "site_trip"})
    task = queue_task("fetch_water", priority=0.88, summary="drink or fetch nearby water", target_kind="resource", target_id="water",
                      metadata={"via": "action", "place": detail.get("place", "")})
    return ActionDraft([], emit(world, ctx.actor, "went_to_drink", {"place": detail.get("place", "")}, visibility="private"), [task],
                       {"source": detail.get("source"), "place": detail.get("place")})


@action("rest", risk="reversible", precondition="can_rest", registry=REGISTRY)
def rest(world, ctx) -> ActionDraft:
    """Recover stamina and hp where the resident stands (the legacy ``sleep`` task with mode rest)."""
    task = queue_task("sleep", priority=0.52, summary="rest and recover stamina",
                      metadata={"stamina": round(read(world, ctx.actor, "stamina", 100.0), 2), "sheltered": bool(read(world, ctx.actor, "shelter") > 0),
                                "mode": "rest", "via": "action"})
    return ActionDraft([], emit(world, ctx.actor, "began_rest", {}, visibility="private"), [task], {})


@action("sleep", risk="reversible", precondition="can_sleep", registry=REGISTRY)
def sleep(world, ctx, place: str = "") -> ActionDraft:
    """Go home and sleep. A roster resident is walked by the schedule routine; others get ``seek_shelter`` then ``sleep`` tasks."""
    detail = ctx.verdict.detail or {}
    me = ctx.actor
    if ctx.has_anchors:
        ops = [set_routine("sleep", reason="action:sleep")]
    else:
        stamina = read(world, me, "stamina", 100.0)
        ops = [queue_task("seek_shelter", priority=0.7, summary="go home to sleep", target_kind="place", target_id="shelter",
                          metadata={"via": "action"}),
               queue_task("sleep", priority=0.52, summary="sleep", metadata={"stamina": round(stamina, 2), "sheltered": False, "via": "action"})]
    return ActionDraft([], emit(world, me, "went_to_sleep", {"place": detail.get("place", place)}, visibility="private"), ops,
                       {"route": "routine" if ctx.has_anchors else "tasks", "place": detail.get("place", place)})


@action("flee_to", risk="reversible", precondition="can_flee", registry=REGISTRY)
def flee_to(world, ctx, place: str = "") -> ActionDraft:
    """Run to a safe place. A roster resident is walked home by the routine (``return_home``); others get the legacy ``flee_target`` task."""
    detail = ctx.verdict.detail or {}
    me = ctx.actor
    if ctx.has_anchors:
        ops = [set_routine("return_home", reason="action:flee_to")]
    else:
        ops = [queue_task("flee_target", priority=0.97, summary="flee immediate danger", metadata={"reason": "danger", "via": "action"})]
    return ActionDraft([], emit(world, me, "fled", {"place": detail.get("place", place)}), ops,
                       {"route": "routine" if ctx.has_anchors else "tasks", "place": detail.get("place", place)})


@action("seek_shelter", risk="reversible", precondition="shelter_reachable", registry=REGISTRY)
def seek_shelter(world, ctx, place: str = "") -> ActionDraft:
    """Go to the nearest shelter. A roster resident is walked home by the routine (``return_home``); others get the legacy ``seek_shelter`` task."""
    detail = ctx.verdict.detail or {}
    if ctx.has_anchors:
        ops = [set_routine("return_home", reason="action:seek_shelter")]
    else:
        ops = [queue_task("seek_shelter", priority=0.86, summary="seek shelter", target_kind="place", target_id="shelter", metadata={"via": "action"})]
    return ActionDraft([], emit(world, ctx.actor, "sought_shelter", {"place": detail.get("place", place)}, visibility="private"), ops,
                       {"route": "routine" if ctx.has_anchors else "tasks", "place": detail.get("place", place)})


@action("hide", risk="reversible", precondition="can_hide", registry=REGISTRY)
def hide(world, ctx, place: str = "") -> ActionDraft:
    """Stay quiet where the resident stands for a few ticks (the legacy ``wait_in_hiding`` task ends by itself after ``hold_ticks``)."""
    detail = ctx.verdict.detail or {}
    ops = [queue_task("wait_in_hiding", priority=0.41, summary="hide and wait", metadata={"via": "action", "hold_ticks": HIDE_TICKS})]
    return ActionDraft([], emit(world, ctx.actor, "went_into_hiding", {"place": detail.get("place", place)}, visibility="private"), ops,
                       {"hold_ticks": HIDE_TICKS, "place": detail.get("place", place)})
