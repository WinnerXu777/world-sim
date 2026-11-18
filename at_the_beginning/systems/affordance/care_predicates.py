"""Legality of ``light_fire`` (``EDEN_TEMPERATURE=1``) and ``treat_wound`` (``EDEN_WOUNDS=1``); flag off: ``not_wired`` and no candidates. Imported at the end of ``predicates.py``.

Both read 9d882a's instinct state through the engine behind the services (``harness/temperature.py``, ``harness/wounds.py``); a services object without an engine (the synthetic Scene) answers
``no_engine``, so the engine tests carry these verbs. Predicate ids are the catalog's: ``can_light_fire``, ``can_treat``.
"""
from __future__ import annotations

import math
from importlib import import_module

from . import config
from .predicates import Verdict, _alive, _nearest_neighbours, _social, no, verb, yes

FUEL = "wood_bundle"
FIRE_SPACING = 20.0          # no second fire within this of a lit one
TREATMENTS = (("bandage", 1.0), ("herb_bundle", 0.6))       # item, strength (the share of the bleed it stops), best first


def _engine(S):
    return getattr(S.services, "engine", None)


def _flag(flag: str, module: str):
    return None if import_module(f"harness.{module}").enabled() else no("not_wired", why=f"{flag} is off")


def _held(S, actor: str) -> dict:
    return S.services.inventory(actor)


# -- light_fire (place?, fuel?) ----------------------------------------------------------------------------------------------------------------------------
def _candidates_fire(S):
    from harness import temperature
    if not temperature.enabled() or not S.obs.alive or _held(S, S.actor).get(FUEL, 0) < 1:
        return []
    return [{}]


@verb("light_fire", "can_light_fire", _candidates_fire)
def light_fire(S, place: str = "", fuel: str = "") -> Verdict:
    dead = _alive(S) or _flag("EDEN_TEMPERATURE", "temperature")
    if dead:
        return dead
    engine = _engine(S)
    if engine is None:
        return no("no_engine")
    if not isinstance(place, str) or not isinstance(fuel, str):
        return no("invalid_params", field="place/fuel")
    kind = fuel or FUEL
    if kind != FUEL:
        return no("invalid_params", field="fuel", allowed=[FUEL])
    if _held(S, S.actor).get(kind, 0) < 1:
        return no("no_item", item=kind)
    x, y = S.obs.x, S.obs.y
    if place:
        from .places_predicates import _perceived
        seen = _perceived(S).get(place)
        if seen is None:
            return no("not_perceived", place=place)
        x, y = float(seen[1]), float(seen[2])
        if math.hypot(x - S.obs.x, y - S.obs.y) > config.RADIUS["interact"]:
            return no("out_of_range", distance=round(math.hypot(x - S.obs.x, y - S.obs.y), 2))
    from harness import temperature
    fires = temperature._fires(engine)
    if fires.shape[0] and bool((((fires[:, 0] - x) ** 2 + (fires[:, 1] - y) ** 2) ** 0.5 <= FIRE_SPACING).any()):
        return no("fire_near")
    return yes({"x": float(x), "y": float(y), "fuel": kind})


# -- treat_wound (target?, item?) ----------------------------------------------------------------------------------------------------------------------------
def _treatment(S, item: str):
    held = _held(S, S.actor)
    for kind, strength in TREATMENTS:
        if (not item or item == kind) and held.get(kind, 0) >= 1:
            return kind, strength
    return None


def _candidates_treat(S):
    from harness import wounds
    engine = _engine(S)
    if engine is None or not wounds.enabled() or not S.obs.alive or _treatment(S, "") is None:
        return []
    out = [{}] if wounds.wounded_of(engine, S.actor) else []
    out += [{"target": n.id} for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"] and wounds.wounded_of(engine, n.id)]
    return out


@verb("treat_wound", "can_treat", _candidates_treat)
def treat_wound(S, target: str = "", item: str = "") -> Verdict:
    from harness import wounds
    dead = _alive(S) or _flag("EDEN_WOUNDS", "wounds")
    if dead:
        return dead
    engine = _engine(S)
    if engine is None:
        return no("no_engine")
    if not isinstance(target, str) or not isinstance(item, str) or (item and item not in dict(TREATMENTS)):
        return no("invalid_params", field="target/item")
    subject = target or S.actor
    distance = 0.0
    if subject != S.actor:
        base = _social(S, subject, radius=config.RADIUS["interact"])
        if not base.ok:
            return base
        distance = base.distance
    if not wounds.wounded_of(engine, subject):
        return no("not_needed", target=subject)
    chosen = _treatment(S, item)
    if chosen is None:
        return no("no_item", item=item or "bandage")
    kind, strength = chosen
    return yes({"subject": subject, "item": kind, "strength": strength}, distance=distance)
