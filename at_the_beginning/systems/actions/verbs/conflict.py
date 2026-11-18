"""Conflict verbs: attack, avoid, warn, steal_when_safe.

``attack`` and ``avoid`` queue the legacy combat task (``attack_target`` closes on the target and strikes, ``retreat_from_target`` walks away until a
safe distance); both need the resident's own movement, so a roster resident is refused (``roster_driven``) like ``follow``. ``warn`` is speech: an
event plus, for a non-roster resident, the ``warn_target`` task that walks over and says it. ``attack`` is destructive: the runner's risk gate lets a
model through only above the confidence threshold (D-3).
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import action

from .. import reputation
from ..draft import ActionDraft, ActionRefused, RecordOp, queue_task, roster_driven
from . import REGISTRY
from .common import emit


@action("attack", risk="destructive", precondition="can_attack", registry=REGISTRY)
def attack(world, ctx, target: str = "") -> ActionDraft:
    roster_driven(ctx, "attacking needs the resident to close on the target; the anchor driver moves a roster resident only to its anchors")
    ops = [queue_task("attack_target", priority=0.95, summary=f"attack {target}", target_kind="human", target_id=target,
                      metadata={"via": "action", "target_human_id": target})]
    return ActionDraft([], emit(world, ctx.actor, "began_attack", {"target": target}, others=(target,)), ops, {"target": target})


@action("avoid", risk="reversible", precondition="target_in_perception", registry=REGISTRY)
def avoid(world, ctx, target: str = "") -> ActionDraft:
    roster_driven(ctx, "retreating needs the resident's own movement; the anchor driver moves a roster resident only to its anchors")
    ops = [queue_task("retreat_from_target", priority=0.91, summary=f"keep away from {target}", target_kind="human", target_id=target,
                      metadata={"via": "action", "target_human_id": target})]
    return ActionDraft([], emit(world, ctx.actor, "began_avoiding", {"target": target}, others=(target,), visibility="private"), ops,
                       {"target": target})


@action("warn", risk="reversible", precondition="can_talk", registry=REGISTRY)
def warn(world, ctx, target: str = "") -> ActionDraft:
    ops = []
    if not ctx.is_roster:          # the warn task walks to the target; for a roster resident it would stay active (event only, like greet)
        ops.append(queue_task("warn_target", priority=0.58, summary=f"warn {target}", target_kind="human", target_id=target,
                              metadata={"via": "action", "target_human_id": target}))
    return ActionDraft([], emit(world, ctx.actor, "warned", {"to": target}, others=(target,)), ops, {"target": target})


@action("steal_when_safe", risk="destructive", precondition="can_steal", registry=REGISTRY)
def steal_when_safe(world, ctx, target: str = "", container: str = "", item: str = "", qty: int = 1) -> ActionDraft:
    """Take ``qty`` x ``item`` from a neighbour's pack or an open container when nobody else within help range would see it. Instant (a pickpocket), so it
    needs no movement and works for a roster resident. The ledger gets a ``theft`` event seen only by the thief and the victim (``private``): the world
    keeps the record, the victim does not learn who. **Destructive** (D-3): only the rules proposer, or a model above the confidence threshold, passes the risk gate."""
    owner, me = target or container, ctx.actor
    have = world.items.quantity(owner, item)
    if have < int(qty):
        raise ActionRefused("no_item", f"{owner} holds {have} {item}")
    detail = {"from": owner, "item": item, "qty": int(qty), "kind": "resident" if target else "container"}
    ops = []
    if reputation.enabled():            # EDEN_REPUTATION: the loss comes to light, opinions drop, gossip spreads (``actions/reputation.py``); the runner adds the event id
        ops.append(RecordOp("theft_consequence", {"owner_kind": detail["kind"], "owner": owner, "item": item, "qty": int(qty)}))
    return ActionDraft([fx.Transfer(item, int(qty), owner, me)], emit(world, me, "theft", detail, others=(owner,), visibility="private"), ops, detail)
