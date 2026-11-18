"""Legality of ``defend`` with ``EDEN_DEFEND=1`` (``predicates.defend`` delegates here; flag off it keeps its S1 verdict and candidates). Free of import cycles: ``predicates`` is imported inside the functions.

A guard needs hp >= ``guard.MIN_HP`` and no open post; it names exactly one of a person within talking distance (``target``) or a place it perceives (``place``). The verdict's detail carries
``{"kind", "charge"}`` for the Action.
"""
from __future__ import annotations

from . import config


def candidates(S) -> list:
    from systems.guard import MIN_HP, runtime
    from .places_predicates import _perceived
    from .predicates import _nearest_neighbours
    if not S.obs.alive or S.obs.hp < MIN_HP or runtime.of(S.services).of_guard(S.actor) is not None:
        return []
    out = [{"target": n.id} for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]]
    perceived = _perceived(S)
    for key in ("home", "sleep"):
        anchor = S.obs.anchors.get(key)
        if anchor is not None and anchor.id in perceived:
            out.append({"place": anchor.id})
    return out


def judge(S, target: str = "", place: str = ""):
    from systems.guard import MIN_HP, runtime
    from .places_predicates import _perceived
    from .predicates import _alive, _social, no, yes
    dead = _alive(S)
    if dead:
        return dead
    if bool(target) == bool(place):
        return no("invalid_params", field="target|place", why="name exactly one")
    if S.obs.hp < MIN_HP:
        return no("too_hurt", hp=round(S.obs.hp, 1))
    if runtime.of(S.services).of_guard(S.actor) is not None:
        return no("already_guarding")
    if target:
        if target == S.actor:
            return no("self_target")
        base = _social(S, target, radius=config.RADIUS["interact"])
        if not base.ok:
            return base
        return yes({"kind": "person", "charge": target}, distance=base.distance)
    seen = _perceived(S).get(place)
    if seen is None:
        return no("not_perceived", place=place)
    return yes({"kind": "place", "charge": place})
