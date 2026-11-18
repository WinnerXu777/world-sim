"""Social verbs: greet, chat, follow, ask_for_help, comfort, share_news, gossip. Each queues the legacy social task for the target; greet and chat also nudge the relationship.

The social tasks walk toward the target themselves, so for a roster resident (task movement suppressed) they only complete when the target is
already close; ``tests/test_actions_roster.py`` measures that and the result is in ``1008_actions.md`` section 10.
"""
from __future__ import annotations

from harness import effects as fx
from harness.registry import action

from ..draft import ActionDraft, RecordOp, queue_task, roster_driven
from . import REGISTRY
from .common import emit

GREET_CLOSENESS = 0.02       # placeholder
CHAT_CLOSENESS = 0.03
COMFORT_CLOSENESS = 0.05


def _talk(world, ctx, target: str, act: str, closeness: float, **extra) -> ActionDraft:
    me = ctx.actor
    ops = [RecordOp("relationship", {"other": target, "kind": "known", "delta": closeness})]
    if not ctx.is_roster:          # the talk task walks to the target; for a roster resident it would stay active forever (event + closeness only)
        ops.insert(0, queue_task("talk_to_target", priority=0.4, summary=f"{act} {target}", target_kind="human", target_id=target,
                                 metadata={"via": "action", "speech_act": act, "target_human_id": target, **extra}))
    return ActionDraft([], emit(world, me, f"{act}ed" if act == "greet" else "chatted", {"to": target, **extra}, others=(target,)), ops,
                       {"target": target, "act": act, **extra})


@action("greet", risk="reversible", precondition="can_talk", registry=REGISTRY)
def greet(world, ctx, target: str = "") -> ActionDraft:
    return _talk(world, ctx, target, "greet", GREET_CLOSENESS)


@action("chat", risk="reversible", precondition="can_talk", registry=REGISTRY)
def chat(world, ctx, target: str = "", topic: str = "") -> ActionDraft:
    return _talk(world, ctx, target, "chat", CHAT_CLOSENESS, **({"topic": topic} if topic else {}))


@action("follow", risk="reversible", precondition="target_reachable", registry=REGISTRY)
def follow(world, ctx, target: str = "") -> ActionDraft:
    roster_driven(ctx, "following needs the resident to move after the target; the anchor driver moves a roster resident only to its anchors")
    ops = [queue_task("follow_target", priority=0.33, summary=f"follow {target}", target_kind="human", target_id=target,
                      metadata={"via": "action", "target_human_id": target, "hold_ticks": 20})]
    return ActionDraft([], emit(world, ctx.actor, "began_following", {"target": target}, others=(target,), visibility="private"), ops,
                       {"target": target})


@action("ask_for_help", risk="reversible", precondition="can_call_help", registry=REGISTRY)
def ask_for_help(world, ctx, target: str = "") -> ActionDraft:
    """Call out for help (the legacy ``call_for_help`` task signals the nearest supporter and completes by itself, no walking)."""
    meta = {"via": "action", **({"target_human_id": target} if target else {})}
    ops = [queue_task("call_for_help", priority=0.72, summary="call for help", metadata=meta)]
    return ActionDraft([], emit(world, ctx.actor, "called_for_help", {"to": target} if target else {}, others=(target,) if target else ()), ops,
                       {"target": target})


@action("comfort", risk="reversible", precondition="can_comfort", registry=REGISTRY)
def comfort(world, ctx, target: str = "") -> ActionDraft:
    """Reassure a distressed neighbour. The ``comfort_target`` task walks over first; a roster resident gets the event and the closeness only (like greet)."""
    ops = [RecordOp("relationship", {"other": target, "kind": "known", "delta": COMFORT_CLOSENESS})]
    if not ctx.is_roster:
        ops.insert(0, queue_task("comfort_target", priority=0.41, summary=f"comfort {target}", target_kind="human", target_id=target,
                                 metadata={"via": "action", "target_human_id": target}))
    return ActionDraft([], emit(world, ctx.actor, "comforted", {"to": target}, others=(target,)), ops, {"target": target})


NEWS_CLOSENESS = 0.02
GOSSIP_OPINION_SHARE = 0.5          # the listener takes this share of the teller's closeness to the person talked about ...
GOSSIP_OPINION_CAP = 0.05           # ... capped per telling


def _tell(world, ctx, target: str, event_id: str, act: str, **extra) -> ActionDraft:
    """The listener becomes a witness of the ledger event (the same event id: the ledger adds the witness, no second event), gets a memory note, and both
    sides' closeness moves a little. A non-roster teller also queues the talk task (it walks over); a roster resident gets the effects only, like ``greet``."""
    me, found = ctx.actor, world.events.get(event_id)
    effects = [fx.Emit(found.type, actors=(me, target), place=found.place, space=found.space, visibility="private", event_id=found.id)]
    ops = [RecordOp("memory_note", {"owner": target, "kind": "heard_news", "other": me, "event": found.id, "about": extra.get("about", ""), "event_kind": found.type}),
           RecordOp("relationship", {"other": target, "kind": "known", "delta": NEWS_CLOSENESS}),
           RecordOp("relationship", {"owner": target, "other": me, "kind": "known", "delta": NEWS_CLOSENESS})]
    about = extra.get("about")
    if about:
        liking = float(((ctx.record or {}).get("relationships") or {}).get(about, {}).get("closeness", 0.0))
        opinion = max(-GOSSIP_OPINION_CAP, min(GOSSIP_OPINION_CAP, liking * GOSSIP_OPINION_SHARE))
        if opinion:
            ops.append(RecordOp("relationship", {"owner": target, "other": about, "kind": "known", "delta": opinion}))
    if not ctx.is_roster:
        ops.insert(0, queue_task("talk_to_target", priority=0.4, summary=f"{act} {target}", target_kind="human", target_id=target,
                                 metadata={"via": "action", "speech_act": act, "target_human_id": target}))
    detail = {"to": target, "event": found.id, "kind": found.type, **extra}
    return ActionDraft(effects, emit(world, me, "shared_news" if act == "share_news" else "gossiped", detail, others=(target,), visibility="private"), ops, detail)


@action("share_news", risk="reversible", precondition="knows_event", registry=REGISTRY)
def share_news(world, ctx, target: str = "", event: str = "") -> ActionDraft:
    """Tell a neighbour about an event the resident witnessed (a ledger event id): the neighbour becomes a witness and remembers being told."""
    return _tell(world, ctx, target, event, "share_news")


@action("gossip", risk="reversible", precondition="knows_event", registry=REGISTRY)
def gossip(world, ctx, target: str = "", about: str = "") -> ActionDraft:
    """Tell a neighbour the latest event the resident witnessed that involves ``about``; the listener's opinion of ``about`` moves toward the teller's."""
    return _tell(world, ctx, target, ctx.verdict.detail["event"], "gossip", about=about)
