"""Exploration verbs: explore_toward. Walks a fixed step in a compass heading (the legacy ``move_to_place`` task with the snapped point)."""
from __future__ import annotations

from harness.registry import action

from ..draft import ActionDraft, queue_task, roster_driven
from . import REGISTRY
from .common import emit


@action("explore_toward", risk="reversible", precondition="can_move", registry=REGISTRY)
def explore_toward(world, ctx, heading: str = "N") -> ActionDraft:
    detail = ctx.verdict.detail or {}
    x, y = detail.get("to", [0.0, 0.0])
    roster_driven(ctx, "exploring needs the resident to leave its anchors; the anchor driver returns a roster resident to them")
    ops = [queue_task("move_to_place", priority=0.3, summary=f"explore {heading}", target_kind="point", target_place={"x": x, "y": y},
                      metadata={"via": "action", "heading": heading})]
    return ActionDraft([], emit(world, ctx.actor, "began_exploring", {"heading": heading, "to": [x, y]}, visibility="private"), ops,
                       {"heading": heading, "to": [x, y]})
