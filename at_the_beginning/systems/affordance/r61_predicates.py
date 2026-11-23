"""R6.1 predicates, installed dynamically only while enabled."""
from .predicates import VerbDef, attack, _social, _talk_candidates, no, yes
from .bonds_predicates import _closeness

def retaliate(S, target=""):
    base = attack(S, target)
    if not base.ok:
        return base
    record = S.services.record(S.actor) or {}
    for goal in record.get("goals", []):
        if goal.get("kind") == "retaliate" and goal.get("target_id") == target and goal.get("status", "active") == "active":
            return yes({"justification": {"kind": "goal", "id": goal.get("id", ""), "target": target}}, distance=base.distance)
    for event in (record.get("memory") or {}).get("recent_events", []):
        if event.get("kind") in ("attacked", "harmed") and event.get("other_human_id") == target:
            return yes({"justification": {"kind": "harm", "tick": event.get("tick"), "target": target}}, distance=base.distance)
    return no("no_justification")

def forgive(S, target=""):
    from systems.bonds import rules
    from .predicates import _alive
    dead = _alive(S)
    if dead: return dead
    if not isinstance(target, str) or not target: return no("invalid_params", field="target")
    if target == S.actor: return no("self_target")
    if S.services.record(target) is None: return no("no_target", target=target)
    delta = rules.forgive_delta(_closeness(S, S.actor, target))
    return yes({"delta": delta}) if delta > 0 else no("no_grievance")

def forgive_candidates(S):
    relations = (S.services.record(S.actor) or {}).get("relationships") or {}
    return [{"target": other} for other in sorted(relations) if _closeness(S, S.actor, other) <= -0.05]

def invite(S, target="", place=""):
    if not isinstance(place, str) or not place: return no("invalid_params", field="place")
    places = {e.id for e in S.services.entities()}
    for actor in S.world.table("humans").ids:
        if actor is not None:
            places.update(a.id for a in S.services.anchors(actor).values())
            places.update(a.id for a in S.services.sites(actor).values() if a is not None)
    if place not in places: return no("no_place", place=place)
    return _social(S, target)

def invite_candidates(S):
    places = sorted({a.id for a in list(S.obs.anchors.values()) + [a for a in S.obs.sites.values() if a is not None]})
    return [{"target": c["target"], "place": p} for c in _talk_candidates(S) for p in places]

DEFS = {"retaliate": VerbDef("retaliate", "can_retaliate", retaliate, _talk_candidates), "forgive": VerbDef("forgive", "has_grudge", forgive, forgive_candidates), "invite": VerbDef("invite", "can_invite", invite, invite_candidates)}
