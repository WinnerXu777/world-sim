"""The guard pass (``EDEN_DEFEND=1``, needs ``EDEN_AGENT_ACTIONS``), called from ``AgentDriver.step`` every tick (cheap with no posts) (``1008_defend_design.md`` Phase 0).

* **Install.** The first tick the flag is on, the combat hook (``systems/guard/modifier.py``) is set on ``systems.combat.modifiers`` (never over another model's hook).
* **Tend.** Each open post: closed at ``until``; closed if the guard or the person guarded is down, the guard is dormant, or the guard's own needs call it off (a guard on watch never starves: the
  ladder does not run for a resident on an errand); a place post's position is read from the services every tick. A guard whose errand is gone gets a *holding* errand that follows the charge.
* **Open (every ``GUARD_PERIOD`` ticks, at most ``MAX_NEW`` posts).** By rules, for a free, calm, healthy resident: an authority stands guard over the nearest resident under threat that it does not hold in
  distrust; a protective resident stands guard over someone it holds dear (kin or a close friend) who is under threat. The resident walks to them (the ``guard`` errand follows) and calls ``defend``.
* **Answer.** A blow a guard took (``GuardBook.blows``) is answered once per (guard, attacker) pair: an authority or a fierce guard (aggression >= ``FIERCE``) attacks the attacker at once, anyone
  else warns first and attacks if the same attacker strikes again after the warning.

Runtime state only: the book lives on the services, the errands on the ladder. Place posts are opened by the verb (a model's or a Tier 2 choice); the rules open person posts.
"""
from __future__ import annotations

import math

from .dormancy_gate import asleep

GUARD_PERIOD = 10
MAX_NEW = 4
SCAN_RADIUS = 160.0
FIERCE = 0.6
MAX_NEED = 60.0
TRUST_FLOOR = -0.2           # an authority does not stand guard over someone it holds in distrust


def _slot(engine, human_id: str):
    slot = engine._human_slot_for_id(human_id)
    return slot if slot is not None and slot >= 0 else None


def _alive(engine, human_id: str) -> bool:
    import genesis_config as cfg
    slot = _slot(engine, human_id)
    return slot is not None and float(engine.state.h_tensor[slot, cfg.HP]) > 0 and not asleep(engine, human_id)


def _read(engine, human_id: str, column: str) -> float:
    import genesis_config as cfg
    return float(engine.state.h_tensor[_slot(engine, human_id), getattr(cfg, column)])


def _distance(engine, a: str, b: str) -> float:
    import genesis_config as cfg
    h = engine.state.h_tensor
    sa, sb = _slot(engine, a), _slot(engine, b)
    return math.hypot(float(h[sa, cfg.X]) - float(h[sb, cfg.X]), float(h[sa, cfg.Y]) - float(h[sb, cfg.Y]))


def _traits(engine, human_id: str) -> dict:
    from systems.personality.assign import get_personality_traits
    return get_personality_traits((engine.resident_store.get(human_id) or {}).get("personality"))


def _closeness(engine, owner: str, other: str) -> float:
    relation = ((engine.resident_store.get(owner) or {}).get("relationships") or {}).get(other) or {}
    return float(relation.get("closeness", 0.0))


def _kin_closeness(engine, guard: str, base: float) -> float:
    """The closeness a guard asks before it stands over someone: ``base``, lowered for a loyal resident and raised for a disloyal one while ``EDEN_EMOTION`` is on (loyalty derived from the trait)."""
    from systems.emotion import enabled, rules
    return rules.threshold(base, _traits(engine, guard).get("loyalty", 0.5)) if enabled() else base


def _needy(engine, human_id: str) -> bool:
    return _read(engine, human_id, "HUNGER") >= MAX_NEED or _read(engine, human_id, "THIRST") >= MAX_NEED


def _install(driver, engine) -> None:
    from systems.combat import modifiers
    from systems.guard import modifier, runtime
    if getattr(modifiers.COMBAT_MODIFIER, "guard", False) and getattr(modifiers.COMBAT_MODIFIER, "engine", None) is engine:
        return
    if modifiers.COMBAT_MODIFIER is not None and not getattr(modifiers.COMBAT_MODIFIER, "guard", False):
        driver.routed["guard.hook_taken"] += 1             # another model owns the hook: posts still work as intent and errands, they do not shield
        return
    hook = modifier.make(engine, lambda: runtime.of(driver.runner(engine).services))
    hook.guard, hook.engine = True, engine
    modifiers.set_modifier(hook)


def place_xy(runner, place: str):
    """Where a named place is now (an anchor, a food / water site or an authored entity), or None."""
    services = runner.services
    for actor in runner.world.table("humans").ids:
        if actor is None:
            continue
        for anchor in services.anchors(actor).values():
            if anchor.id == place:
                return float(anchor.x), float(anchor.y)
        for anchor in services.sites(actor).values():
            if anchor is not None and anchor.id == place:
                return float(anchor.x), float(anchor.y)
    for fact in services.entities():
        if fact.id == place:
            return float(fact.x), float(fact.y)
    return None


def step(driver, engine, tick: int) -> None:
    from systems.guard import enabled, runtime
    if not enabled():
        return
    _install(driver, engine)
    runner = driver.runner(engine)
    book = runtime.of(runner.services)
    if book.posts:
        _tend(driver, engine, runner, book, tick)
    if tick % GUARD_PERIOD:
        return
    if len(book.blows) > book.answered:
        _answer(driver, engine, runner, book, tick)
    _open(driver, engine, runner, book, tick)


# -- tend -------------------------------------------------------------------------------------------------------------------------
def _close(driver, book, post, reason: str, tick: int) -> None:
    book.close(post.id, reason, tick)
    errand = driver.ladder.errands.get(post.guard)
    if errand is not None and errand.purpose in ("guard", "guard_place"):
        del driver.ladder.errands[post.guard]
    driver.ladder.note(tick, post.guard, "guard", "defend", f"closed:{reason}", charge=post.charge)


def _tend(driver, engine, runner, book, tick: int) -> None:
    for post in book.active():
        if tick >= post.until:
            _close(driver, book, post, "expired", tick)
        elif not _alive(engine, post.guard):
            _close(driver, book, post, "dormant" if _slot(engine, post.guard) is not None and asleep(engine, post.guard) else "guard_down", tick)
        elif _needy(engine, post.guard):
            _close(driver, book, post, "needs", tick)
        elif post.kind == "person" and not _alive(engine, post.charge):
            _close(driver, book, post, "charge_gone", tick)
        elif post.kind == "place":
            xy = place_xy(runner, post.charge)
            if xy is None:
                _close(driver, book, post, "lost", tick)
                continue
            post.xy = xy
            errand = driver.ladder.errands.get(post.guard)
            if errand is not None and errand.purpose == "guard_place":
                errand.position = xy
        if post.status == "open" and post.guard not in driver.ladder.errands and tick % GUARD_PERIOD == 0:
            driver.ladder.hold_guard(engine, post)


# -- open -------------------------------------------------------------------------------------------------------------------------
def _free(driver, engine, book, human_id: str) -> bool:
    from systems.guard import MIN_HP
    return (_alive(engine, human_id) and human_id not in driver.ladder.errands and book.of_guard(human_id) is None
            and _read(engine, human_id, "HP") >= MIN_HP and not _needy(engine, human_id))


def _open(driver, engine, runner, book, tick: int) -> None:
    from systems.guard import KIN_CLOSENESS, KIN_PROTECTIVENESS, KIN_THREAT
    from systems.justice import law
    threatened = sorted(h for h in engine._human_uid_by_slot if h and _alive(engine, h) and _read(engine, h, "THREAT") >= KIN_THREAT and not book.for_charge(h))
    if not threatened:
        return
    opened = 0
    for guard in [h for h in engine._human_uid_by_slot if h]:
        if opened >= MAX_NEW:
            return
        if not _free(driver, engine, book, guard) or _read(engine, guard, "THREAT") >= KIN_THREAT:
            continue
        authority = law.is_authority(engine.resident_store.get(guard) or {})
        protective = float(_traits(engine, guard).get("protectiveness", 0.5)) >= KIN_PROTECTIVENESS
        if not (authority or protective):
            continue
        options = []
        for charge in threatened:
            if charge == guard or book.for_charge(charge) or driver.ladder.cooling(guard, "guard", charge, tick):
                continue
            distance, closeness = _distance(engine, guard, charge), _closeness(engine, guard, charge)
            if distance > SCAN_RADIUS:
                continue
            if closeness >= _kin_closeness(engine, guard, KIN_CLOSENESS) and protective:
                options.append((-closeness, distance, charge))
            elif authority and closeness >= TRUST_FLOOR:
                options.append((1.0 - min(closeness, 0.99), distance, charge))
        if not options:
            continue
        charge = min(options)[2]
        driver.ladder.start_guard(driver, engine, runner, guard, charge, tick)
        opened += 1


# -- answer -----------------------------------------------------------------------------------------------------------------------
def _answer(driver, engine, runner, book, tick: int) -> None:
    from systems.guard import ATTACKER_MIN_HP, RESPONSE_COOLDOWN, RESPONSE_WINDOW
    from systems.justice import law
    fresh = book.blows[book.answered:]
    book.answered = len(book.blows)
    for blow in fresh:
        guard, attacker = blow.guard, blow.attacker
        if tick - blow.tick > RESPONSE_WINDOW or not attacker or not _alive(engine, guard) or not _alive(engine, attacker):
            continue
        if _read(engine, attacker, "HP") < ATTACKER_MIN_HP or book.cool.get((guard, attacker), -1) > tick:
            continue
        fierce = law.is_authority(engine.resident_store.get(guard) or {}) or float(_traits(engine, guard).get("aggression", 0.5)) >= FIERCE
        warned = book.cool.get((guard, attacker, "warned"), -1) >= 0
        verb = "attack" if (fierce or warned) else "warn"
        result = runner.run(guard, verb, {"target": attacker}, proposer="rules:guard")
        driver.routed[f"guard.{verb}:{'ok' if result.ok else result.code}"] += 1
        driver.ladder.note(tick, guard, "guard", verb, "ok" if result.ok else result.code, target=attacker)
        if verb == "warn" and result.ok:
            book.cool[(guard, attacker, "warned")] = tick
        if result.ok:
            book.cool[(guard, attacker)] = tick + RESPONSE_COOLDOWN
            book.counts[f"answered:{verb}"] += 1
