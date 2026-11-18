"""Legality of the bond verbs ``court``, ``befriend``, ``apologise``, ``forgive`` (``EDEN_BONDS=1``; flag off: ``not_wired`` and no candidates). Imported at the end of ``predicates.py``.

The amounts of the effect are part of the verdict's detail (computed here from the two records), so the runner applies exactly what was judged.
"""
from __future__ import annotations

from . import config
from .predicates import Verdict, _alive, _nearest_neighbours, _social, _target, no, verb, yes


def _flag_off():
    from systems.bonds import enabled
    return None if enabled() else no("not_wired", why="EDEN_BONDS is off")


def _closeness(S, owner: str, other: str) -> float:
    relation = ((S.services.record(owner) or {}).get("relationships") or {}).get(other) or {}
    return float(relation.get("closeness", 0.0))


def _tags(S, owner: str, other: str) -> list:
    relation = ((S.services.record(owner) or {}).get("relationships") or {}).get(other) or {}
    return list(relation.get("tags") or [])


def _mercy(S, human_id: str) -> float:
    from systems.personality.assign import get_personality_traits
    return float(get_personality_traits((S.services.record(human_id) or {}).get("personality")).get("mercy", 0.5))


def _near(S):
    from systems.bonds import enabled
    if not enabled() or not S.obs.alive:
        return []
    return [n for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]]


def _kind(S, owner: str, other: str) -> str:
    relation = ((S.services.record(owner) or {}).get("relationships") or {}).get(other) or {}
    return str(relation.get("kind") or "")


# -- befriend ----------------------------------------------------------------------------------------------------------------------------------
@verb("befriend", "can_befriend", lambda S: [{"target": n.id} for n in _near(S)])
def befriend(S, target: str = "") -> Verdict:
    from systems.bonds import rules
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    base = _social(S, target, radius=config.RADIUS["interact"])
    if not base.ok:
        return base
    mine, theirs = _closeness(S, S.actor, target), _closeness(S, target, S.actor)
    if min(mine, theirs) < rules.HOSTILE:
        return no("refuse_distrust", mine=round(mine, 2), theirs=round(theirs, 2))
    step = rules.befriend_step(mine, theirs)
    if step <= 0.0:
        return no("not_needed", closeness=round(min(mine, theirs), 2))
    return yes({"step": step}, distance=base.distance)


# -- court -------------------------------------------------------------------------------------------------------------------------------------
@verb("court", "can_court", lambda S: [{"target": n.id} for n in _near(S)])
def court(S, target: str = "") -> Verdict:
    from systems.bonds import rules
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    base = _social(S, target, radius=config.RADIUS["interact"])
    if not base.ok:
        return base
    if _kind(S, S.actor, target) == "family" or _kind(S, target, S.actor) == "family":
        return no("kin", target=target)
    mine, theirs = _closeness(S, S.actor, target), _closeness(S, target, S.actor)
    if min(mine, theirs) < rules.COURT_MIN:
        return no("refuse_distrust", mine=round(mine, 2), theirs=round(theirs, 2))
    step = rules.court_step(min(mine, theirs))
    if step <= 0.0:
        return no("not_needed", closeness=round(min(mine, theirs), 2))
    return yes({"step": step}, distance=base.distance)


# -- apologise (the listener holds a grudge against the actor) ---------------------------------------------------------------------------------
def _candidates_apologise(S):
    from systems.bonds import rules
    return [{"target": n.id} for n in _near(S) if _closeness(S, n.id, S.actor) <= rules.GRUDGE]


@verb("apologise", "has_harmed", _candidates_apologise)
def apologise(S, target: str = "", event: str = "") -> Verdict:
    from systems.bonds import rules
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    if not isinstance(event, str):
        return no("invalid_params", field="event")
    base = _social(S, target, radius=config.RADIUS["interact"])
    if not base.ok:
        return base
    theirs = _closeness(S, target, S.actor)
    if theirs > rules.GRUDGE:
        return no("no_grievance", closeness=round(theirs, 2))
    effect = rules.apology_effect(theirs, _mercy(S, target), "thief" in _tags(S, target, S.actor))
    return yes({"effect": effect}, distance=base.distance)


# -- forgive (the actor holds the grudge; needs no proximity) ------------------------------------------------------------------------------
def _candidates_forgive(S):
    from systems.bonds import enabled, rules
    if not enabled() or not S.obs.alive:
        return []
    relations = (S.services.record(S.actor) or {}).get("relationships") or {}
    return [{"target": other} for other in sorted(relations) if float(relations[other].get("closeness", 0.0)) <= rules.GRUDGE][:6]


@verb("forgive", "has_grudge", _candidates_forgive)
def forgive(S, target: str = "") -> Verdict:
    from systems.bonds import rules
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    if not isinstance(target, str) or not target:
        return no("invalid_params", field="target")
    if target == S.actor:
        return no("self_target")
    if S.services.record(target) is None:
        return no("no_target", target=target)
    delta = rules.forgive_delta(_closeness(S, S.actor, target))
    if delta <= 0.0:
        return no("no_grievance", closeness=round(_closeness(S, S.actor, target), 2))
    return yes({"delta": delta})
