"""The bonds pass (``EDEN_BONDS=1``), called from ``AgentDriver.step`` every ``BONDS_PERIOD`` ticks: chance encounters between residents that stand within talking distance.

Rules only (no errands: people walk to each other for food, work and justice; bonds happen when they meet), one verb per resident per pass, in this order:

1. **forgive** the neighbour it holds a grudge against, if it is merciful (a thief only if very merciful; the reputation pass removes the tag when the closeness reaches 0);
2. **apologise** to a neighbour that holds a grudge against it, if it has a conscience (``ladder.conscience`` above ``APOLOGY_CONSCIENCE``);
3. **befriend** the nearest neighbour it is not hostile to, if it is sociable (sociability above ``SOCIABLE``), not hungry or threatened;
4. **court** a neighbour it is fond of (closeness >= ``bonds.rules.COURT_MIN`` both ways), by the more sociable of the two only.

A pair is not tried again for ``PAIR_COOLDOWN`` ticks (per verb, whatever the outcome). Runtime state (cooldowns) lives on the driver and is dropped when it is rebuilt.
"""
from __future__ import annotations

from .dormancy_gate import asleep

BONDS_PERIOD = 60
PAIR_COOLDOWN = 600
FORGIVE_MERCY = 0.5
FORGIVE_THIEF_MERCY = 0.7
APOLOGY_CONSCIENCE = 0.1
SOCIABLE = 0.5
MAX_NEED = 60.0
MAX_THREAT = 30.0


def _alive(engine, human_id: str) -> bool:
    import genesis_config as cfg
    slot = engine._human_slot_for_id(human_id)
    return slot is not None and slot >= 0 and float(engine.state.h_tensor[slot, cfg.HP]) > 0 and not asleep(engine, human_id)


def _calm(engine, human_id: str) -> bool:
    import genesis_config as cfg
    h = engine.state.h_tensor
    slot = engine._human_slot_for_id(human_id)
    return float(h[slot, cfg.HUNGER]) < MAX_NEED and float(h[slot, cfg.THIRST]) < MAX_NEED and float(h[slot, cfg.THREAT]) < MAX_THREAT


def _distance(engine, a: str, b: str) -> float:
    import math
    import genesis_config as cfg
    h = engine.state.h_tensor
    sa, sb = engine._human_slot_for_id(a), engine._human_slot_for_id(b)
    return math.hypot(float(h[sa, cfg.X]) - float(h[sb, cfg.X]), float(h[sa, cfg.Y]) - float(h[sb, cfg.Y]))


def _relation(engine, owner: str, other: str) -> dict:
    return ((engine.resident_store.get(owner) or {}).get("relationships") or {}).get(other) or {}


def _traits(engine, human_id: str) -> dict:
    from systems.personality.assign import get_personality_traits
    return get_personality_traits((engine.resident_store.get(human_id) or {}).get("personality"))


def _cooling(cool: dict, key: tuple, tick: int) -> bool:
    return cool.get(key, -1) > tick


def step(driver, engine, tick: int) -> None:
    from systems.bonds import enabled, rules
    if not enabled() or tick % BONDS_PERIOD != 0:
        return
    from systems.affordance import config
    from .ladder import conscience
    runner = driver.runner(engine)
    cool = driver.__dict__.setdefault("bond_cool", {})
    residents = [h for h in engine._human_uid_by_slot if h and _alive(engine, h) and h not in driver.ladder.errands]
    for actor in residents:
        if not _calm(engine, actor):
            continue
        near = sorted((n for n in residents if n != actor and _distance(engine, actor, n) <= config.RADIUS["interact"]), key=lambda n: (_distance(engine, actor, n), n))
        if not near:
            continue
        traits = _traits(engine, actor)
        call = _choose(engine, actor, near, traits, rules, cool, tick, conscience)
        if call is None:
            continue
        verb, params = call
        result = runner.run(actor, verb, params, proposer="rules:bonds")
        driver.routed[f"{verb}:ok" if result.ok else f"{verb}:{result.code}"] += 1
        cool[(verb, actor, params["target"])] = tick + PAIR_COOLDOWN         # a refusal is not repeated at once either
        if result.ok:
            if verb in ("befriend", "court"):
                cool[(verb, params["target"], actor)] = tick + PAIR_COOLDOWN       # the other side does not repeat what just happened to it


def _choose(engine, actor, near, traits, rules, cool, tick, conscience):
    mercy = float(traits.get("mercy", 0.5))
    for other in near:
        mine = float(_relation(engine, actor, other).get("closeness", 0.0))
        if mine <= rules.GRUDGE and not _cooling(cool, ("forgive", actor, other), tick):
            thief = "thief" in (_relation(engine, actor, other).get("tags") or [])
            if mercy >= (FORGIVE_THIEF_MERCY if thief else FORGIVE_MERCY):
                return "forgive", {"target": other}
    if conscience(traits) > APOLOGY_CONSCIENCE:
        for other in near:
            theirs = float(_relation(engine, other, actor).get("closeness", 0.0))
            if theirs <= rules.GRUDGE and not _cooling(cool, ("apologise", actor, other), tick):
                return "apologise", {"target": other}
    if float(traits.get("sociability", 0.5)) > SOCIABLE:
        for other in near:
            mine, theirs = float(_relation(engine, actor, other).get("closeness", 0.0)), float(_relation(engine, other, actor).get("closeness", 0.0))
            if min(mine, theirs) < rules.HOSTILE or _cooling(cool, ("befriend", actor, other), tick):
                continue
            if min(mine, theirs) >= rules.COURT_MIN and float(traits.get("sociability", 0.5)) >= float(_traits(engine, other).get("sociability", 0.5)) and not _cooling(cool, ("court", actor, other), tick):
                return "court", {"target": other}
            return "befriend", {"target": other}
    return None
