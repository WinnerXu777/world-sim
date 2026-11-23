"""Opt-in retaliation, forgiveness and short-lived invitations."""
import os
from harness.registry import Registry, action
from .draft import ActionDraft, RecordOp, queue_task, roster_driven
from .verbs.common import emit

REGISTRY = Registry()
def enabled():
    return os.environ.get("EDEN_VERBS_R61") == "1"

@action("retaliate", risk="destructive", precondition="can_retaliate", registry=REGISTRY)
def retaliate(world, ctx, target: str = ""):
    roster_driven(ctx, "retaliation requires movement")
    justification = ctx.verdict.detail["justification"]
    task = queue_task("attack_target", priority=0.95, summary=f"retaliate against {target}", target_kind="human", target_id=target, metadata={"via": "action", "target_human_id": target, "justification": justification})
    return ActionDraft([], emit(world, ctx.actor, "began_retaliation", {"target": target, "justification": justification}, others=(target,)), [task], {"target": target, "justification": justification})

@action("forgive", risk="reversible", precondition="has_grudge", registry=REGISTRY)
def forgive(world, ctx, target: str = ""):
    delta = ctx.verdict.detail["delta"]
    ops = [RecordOp("relationship", {"other": target, "kind": "known", "delta": delta}), RecordOp("r61_clear_goal", {"target": target})]
    return ActionDraft([], emit(world, ctx.actor, "forgave", {"target": target, "delta": delta}, others=(target,)), ops, {"target": target, "delta": delta})

@action("invite", risk="reversible", precondition="can_invite", registry=REGISTRY)
def invite(world, ctx, target: str = "", place: str = ""):
    return ActionDraft([], emit(world, ctx.actor, "invited", {"target": target, "place": place}, others=(target,)), [RecordOp("r61_invite", {"target": target, "place": place})], {"target": target, "place": place})

class InvitationBook:
    def __init__(self):
        self.records = []
    def open(self, actor, target, place, tick):
        record = {"id": f"invitation_{len(self.records)+1:05d}", "who": actor, "whom": target, "place": place, "time": tick, "expires": tick + 60, "state": "pending"}
        self.records.append(record)
        return record
    def expire(self, tick):
        for record in self.records:
            if record["state"] == "pending" and tick >= record["expires"]:
                record["state"] = "expired"
    def answer(self, record, tick, closeness, mood):
        self.expire(tick)
        if record["state"] == "pending":
            record["state"] = "accepted" if closeness >= 0 and mood >= 40 else "declined"
        return record["state"]

def invitations_of(services):
    owner = getattr(services, "engine", services)
    return owner.__dict__.setdefault("_r61_invitations", InvitationBook())
