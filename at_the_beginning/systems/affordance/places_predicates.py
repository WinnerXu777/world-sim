"""Legality of the place-memory verbs ``mark_place``, ``remember_place``, ``ask_directions`` (``EDEN_PLACES=1``; flag off: ``not_wired`` and no candidates). Imported at the end of ``predicates.py``."""
from __future__ import annotations

from . import config
from .predicates import Verdict, _alive, _social, no, verb, yes


def _flag_off():
    from systems.places import enabled
    return None if enabled() else no("not_wired", why="EDEN_PLACES is off")


def _known(S) -> dict:
    from systems.places import FIELD
    return (S.obs.record or {}).get(FIELD) or {}


# -- mark_place (the name is the model's / rules' choice: the mask lists no candidates) ---------------------------------------------------------------
@verb("mark_place", "can_move", lambda S: [])
def mark_place(S, name: str = "") -> Verdict:
    from systems.places import clean_name
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    if not clean_name(name):
        return no("invalid_params", field="name")
    return yes({"name": clean_name(name)})


# -- remember_place (a perceived place: an anchor, a site or an entity in view) ---------------------------------------------------------------------
def _perceived(S) -> dict:
    """``{id: (kind, x, y)}`` of what the actor can name right now."""
    out = {}
    for _, anchor in sorted(S.obs.anchors.items()):
        out[anchor.id] = ("anchor", anchor.x, anchor.y)
    for _, site in sorted(S.obs.sites.items()):
        if site is not None:
            out[site.id] = ("site", site.x, site.y)
    for seen in S.obs.entities:
        out[seen.fact.id] = ("entity", seen.fact.x, seen.fact.y)
    return out


def _candidates_remember(S):
    from systems.places import enabled
    if not enabled() or not S.obs.alive:
        return []
    known = _known(S)
    return [{"place": pid} for pid in sorted(_perceived(S)) if pid not in known][:6]


@verb("remember_place", "perceives", _candidates_remember)
def remember_place(S, place: str = "") -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    if not isinstance(place, str) or not place:
        return no("invalid_params", field="place")
    seen = _perceived(S).get(place)
    if seen is None:
        return no("not_perceived", place=place)
    kind, x, y = seen
    return yes({"kind": kind, "x": float(x), "y": float(y)})


# -- ask_directions (explicit names only: the mask lists no candidates) --------------------------------------------------------------------------------
@verb("ask_directions", "can_talk", lambda S: [])
def ask_directions(S, target: str = "", name: str = "") -> Verdict:
    from systems.places import clean_name
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    name = clean_name(name)
    if not name:
        return no("invalid_params", field="name")
    base = _social(S, target, radius=config.RADIUS["interact"])
    if not base.ok:
        return base
    if name in _known(S):
        return no("not_needed", name=name)
    return base
