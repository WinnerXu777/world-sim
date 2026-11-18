"""Legality of ``rob`` and ``arrest_or_restrain`` (``EDEN_ROB=1``; flag off: ``not_wired`` and no candidates). Imported at the end of ``predicates.py``.

Neither lists mask candidates: the ladder makes the call (the rung ``rob``; the enforcement errand's arrest after damages), and a model reaches them through the typed options only when a future gate
allows it. The verdict's detail carries what the Action applies (item, quantity, the odds; the hold length).
"""
from __future__ import annotations

from . import config
from .predicates import Verdict, _alive, _social, no, verb, yes


def _flag_off():
    from systems.rob import enabled
    return None if enabled() else no("not_wired", why="EDEN_ROB is off")


def _traits(S, human_id: str) -> dict:
    from systems.personality.assign import get_personality_traits
    return get_personality_traits((S.services.record(human_id) or {}).get("personality"))


def guarded(S, target: str) -> bool:
    """A guard with an open post over ``target`` stands in reach of it, awake and fit."""
    from systems import guard
    from systems.guard import runtime
    if not guard.enabled():
        return False
    table = S.world.table("humans")
    here = table.position(table.slot_of(target))
    for post in runtime.of(S.services).for_charge(target):
        slot = table.slot_of(post.guard)
        if slot is None or table.get(post.guard, "hp") < guard.MIN_HP:
            continue
        there = table.position(slot)
        if ((there[0] - here[0]) ** 2 + (there[1] - here[1]) ** 2) ** 0.5 <= post.radius:
            return True
    return False


def _unavailable(S, target: str):
    """The victim (or the prisoner) must be an awake resident of the engine and not a player's body."""
    engine = getattr(S.services, "engine", None)
    if engine is None:
        return None
    from systems.actions.dormancy_gate import asleep
    from systems.rob import controlled
    slot = engine._human_slot_for_id(target)
    if asleep(engine, target):
        return no("target_dormant", target=target)
    if controlled(engine, slot):
        return no("target_controlled", target=target)
    return None


# -- rob ---------------------------------------------------------------------------------------------------------------------------------------
@verb("rob", "can_rob", lambda S: [])
def rob(S, target: str = "", item: str = "", qty: int = 0) -> Verdict:
    from systems import rob as rules
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    if S.obs.hp < rules.ROB_MIN_HP:
        return no("too_hurt", hp=round(S.obs.hp, 1))
    if not isinstance(item, str) or isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
        return no("invalid_params", field="item/qty")
    base = _social(S, target, radius=config.RADIUS["interact"])
    if not base.ok:
        return base
    away = _unavailable(S, target)
    if away is not None:
        return away
    held = S.services.inventory(target)
    kind = item if item else next((k for k in config.EDIBLE_ITEMS if held.get(k, 0) >= 1), "")
    if kind not in config.EDIBLE_ITEMS:
        return no("invalid_params", field="item") if item else no("nothing_to_take", target=target)
    have = int(held.get(kind, 0))
    if have < 1:
        return no("nothing_to_take", target=target, item=kind)
    take = min(have, qty or 1)
    n = S.obs.neighbour(target)
    cover = guarded(S, target)
    odds = rules.p_success(rules.power(S.obs.hp, _traits(S, S.actor).get("aggression", 0.5)), rules.power(n.hp, _traits(S, target).get("aggression", 0.5), cover))
    return yes({"item": kind, "qty": take, "guarded": cover, "p": round(odds, 3)}, distance=base.distance)


# -- arrest_or_restrain (the authority holds a convicted robber) ---------------------------------------------------------------------------------
@verb("arrest_or_restrain", "holds_authority", lambda S: [])
def arrest_or_restrain(S, target: str = "") -> Verdict:
    from harness import restraint
    from systems import rob as rules
    from systems.justice import law
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    if not restraint.enabled():
        return no("not_wired", why="EDEN_RESTRAINT is off")
    base = _social(S, target, radius=config.RADIUS["interact"])
    if not base.ok:
        return base
    if not law.is_authority(S.services.record(S.actor) or {}):
        return no("not_authority")
    engine = getattr(S.services, "engine", None)
    if engine is None:
        return no("no_engine")
    away = _unavailable(S, target)
    if away is not None:
        return away
    if not rules.robber_on_record(engine, target):
        return no("not_convicted", target=target)
    if restraint.is_restrained(engine, engine._human_slot_for_id(target)):
        return no("already_restrained", target=target)
    return yes({"ticks": rules.ARREST_TICKS}, distance=base.distance)
