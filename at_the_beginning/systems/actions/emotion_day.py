"""The emotion pass (``EDEN_EMOTION=1``, needs ``EDEN_AGENT_ACTIONS``), called from ``AgentDriver.step`` every ``EMOTION_PERIOD`` ticks (``1008_actions.md`` section 10.22; state and rules: ``systems/emotion``).

For each awake resident (a dormant one is skipped and catches up on waking):

* **Daily, lazy.** Once at least a game day (``gameclock.day_ticks()``) has passed since ``last_decay_tick`` the elapsed days are applied at once (at most 30): negative closeness rises toward 0
  (``rules.GRUDGE_DECAY_PER_DAY``) unless the relation got worse since the last pass (a new offence refreshes it); a grave one (<= -0.7, tagged ``grave``) rises only to -0.35; ``thief``-tagged
  relations belong to the reputation pass and are left alone. Jealous tensions fade; curiosity builds (and is discharged by newly learned places); thrift moves toward its trait-set point and up when food runs short.
* **Grief.** A relation at closeness >= 0.5 to someone now dead starts a grief (level from the closeness, fading over 3 game days), takes the mood down once and writes a memory event.
* **Comfort.** A neighbour in reach that holds the griever at >= 0.3 (less for a loyal one) and is free and calm calls ``comfort`` (the verb itself needs the griever's mood low); each success lifts the grief.
* **Jealousy.** A resident with a partner (mutual closeness >= 0.6) whose partner stands in reach of a third resident the partner holds at >= 0.3 builds tension against the rival; above 0.6 it holds the
  rival a little less dear every pass and, in reach and calm, ``warn``s (cooled down per pair).

Runtime state only for the cooldowns (on the driver); everything else is in the records, saved with them.
"""
from __future__ import annotations

from .dormancy_gate import asleep

EMOTION_PERIOD = 60
COOLDOWN = 600
MAX_NEED = 60.0
MAX_THREAT = 30.0
MAX_COMFORTS = 4            # per pass


def _slot(engine, uid: str):
    slot = engine._human_slot_for_id(uid)
    return slot if slot is not None and slot >= 0 else None


def _awake(engine, uid: str) -> bool:
    import genesis_config as cfg
    slot = _slot(engine, uid)
    return slot is not None and float(engine.state.h_tensor[slot, cfg.HP]) > 0 and not asleep(engine, uid)


def _calm(engine, uid: str) -> bool:
    import genesis_config as cfg
    h, slot = engine.state.h_tensor, _slot(engine, uid)
    return float(h[slot, cfg.HUNGER]) < MAX_NEED and float(h[slot, cfg.THIRST]) < MAX_NEED and float(h[slot, cfg.THREAT]) < MAX_THREAT


def _distance(engine, a: str, b: str) -> float:
    import math
    import genesis_config as cfg
    h = engine.state.h_tensor
    sa, sb = _slot(engine, a), _slot(engine, b)
    return math.hypot(float(h[sa, cfg.X]) - float(h[sb, cfg.X]), float(h[sa, cfg.Y]) - float(h[sb, cfg.Y]))


def _traits(engine, uid: str) -> dict:
    from systems.personality.assign import get_personality_traits
    return get_personality_traits((engine.resident_store.get(uid) or {}).get("personality"))


def _relations(record) -> dict:
    return (record or {}).get("relationships") or {}


def _closeness(record, other: str) -> float:
    return float(_relations(record).get(other, {}).get("closeness", 0.0))


def step(driver, engine, tick: int) -> None:
    from systems.emotion import enabled
    if not enabled() or tick % EMOTION_PERIOD:
        return
    from .gameclock import day_ticks
    store, day = engine.resident_store, day_ticks()
    runner = driver.runner(engine)
    cool = driver.__dict__.setdefault("emotion_cool", {})
    awake = [u for u in engine._human_uid_by_slot if u and store.get(u) is not None and _awake(engine, u)]
    for uid in awake:
        record = store.get(uid)
        if _daily(engine, runner, record, uid, tick, day) | _grief(engine, runner, store, record, uid, tick):
            store._mark_dirty(uid)
    _comfort(driver, engine, runner, store, awake, cool, tick, day)
    _jealousy(driver, engine, runner, store, awake, cool, tick)


# -- daily (lazy catch-up) ------------------------------------------------------------------------------------------------------
def _daily(engine, runner, record, uid: str, tick: int, day: int) -> bool:
    from systems.emotion import of, rules
    block = of(record)
    last = block.get("last_decay_tick")
    traits = _traits(engine, uid)
    drives = block.setdefault("drives", {"curiosity": round(float(traits.get("curiosity", 0.5)) * 0.5, 4), "thrift": rules.thrift_point(traits)})
    if last is None:
        block["last_decay_tick"] = int(tick)
        block["places"] = len(record.get("known_places") or {})
        return True
    days = (int(tick) - int(last)) // day
    discovered = len(record.get("known_places") or {}) - int(block.get("places", 0))
    if discovered > 0:
        block["places"] = block["places"] + discovered
        drives["curiosity"] = round(rules.clamp(drives["curiosity"] - rules.CURIOSITY_DISCHARGE * discovered), 4)
    if days < 1:
        return discovered > 0
    block["last_decay_tick"] = int(last) + days * day
    grudges = block.setdefault("grudges", {})
    for other, relation in _relations(record).items():
        closeness = float(relation.get("closeness", 0.0))
        tags = relation.setdefault("tags", [])
        if closeness >= 0.0:
            grudges.pop(other, None)
            continue
        if any(tag in tags for tag in rules.OWNED_TAGS):
            continue
        before = grudges.get(other)
        if before is not None and closeness < float(before) - 1e-9:        # worse since the last pass: a new offence, nothing heals today
            grudges[other] = closeness
            continue
        grave = rules.is_grave(closeness, tags)
        if grave and rules.GRAVE_TAG not in tags:
            tags.append(rules.GRAVE_TAG)
        relation["closeness"] = grudges[other] = rules.decay_grudge(closeness, days, grave)
    held = block.get("tension") or {}
    for rival in list(held):
        held[rival] = rules.tension_after(held[rival], days)
        if held[rival] <= 0.0:
            del held[rival]
    drives["curiosity"] = round(rules.clamp(drives["curiosity"] + rules.CURIOSITY_RISE_PER_DAY * min(days, rules.MAX_CATCH_UP_DAYS) * (0.5 + float(traits.get("curiosity", 0.5)))), 4)
    pull = rules.THRIFT_PULL_PER_DAY * min(days, rules.MAX_CATCH_UP_DAYS)
    point = rules.thrift_point(traits)
    drives["thrift"] = rules.clamp(drives["thrift"] + max(-pull, min(pull, point - drives["thrift"])))
    if _food(runner, uid) < 2:
        drives["thrift"] = rules.clamp(drives["thrift"] + rules.THRIFT_SCARCITY * min(days, rules.MAX_CATCH_UP_DAYS))
    drives["thrift"] = round(drives["thrift"], 4)
    return True


def _food(runner, uid: str) -> int:
    from systems.inventory import schema
    return sum(int(qty) for kind, qty in runner.services.inventory(uid).items() if "food" in (schema.item_kind_def(kind).get("tags") or ()))


# -- grief ------------------------------------------------------------------------------------------------------------------------
def _grief(engine, runner, store, record, uid: str, tick: int) -> bool:
    from systems.emotion import of, rules
    block = of(record)
    mourned = block.setdefault("mourned", [])
    changed = False
    for other, relation in _relations(record).items():
        if other in mourned or float(relation.get("closeness", 0.0)) < rules.GRIEF_MIN:
            continue
        gone = store.get(other)
        if gone is None or (gone.get("status") or {}).get("alive", True):
            continue
        mourned.append(other)
        level = rules.grief_start(float(relation["closeness"]))
        if rules.grief_now(block.get("grief"), tick, _day()) < level:             # a heavier loss replaces a lighter grief still running
            block["grief"] = {"level": level, "subject": other, "since": int(tick), "relief": 0.0}
        _shock(runner, uid, rules.GRIEF_MOOD_SHOCK * level)
        try:
            store.record_event(uid, tick, "grief", note=f"mourning {other}", other_human_id=other)
        except Exception:
            pass
        changed = True
    return changed


def _day() -> int:
    from .gameclock import day_ticks
    return day_ticks()


def _shock(runner, uid: str, amount: float) -> None:
    from .verbs.common import bounded_delta
    runner.world.apply([bounded_delta(runner.world, uid, "mood", -float(amount))], atomic=True, cause="emotion:grief")


# -- comfort ----------------------------------------------------------------------------------------------------------------------
def _comfort(driver, engine, runner, store, awake: list, cool: dict, tick: int, day: int) -> None:
    from systems.affordance import config
    from systems.emotion import grief_level, of, rules
    done = 0
    for griever in awake:
        record = store.get(griever)
        if grief_level(record, tick, day) < 0.2:
            continue
        for friend in awake:
            if done >= MAX_COMFORTS:
                return
            if friend == griever or friend in driver.ladder.errands or not _calm(engine, friend) or cool.get(("comfort", friend, griever), -1) > tick:
                continue
            if _distance(engine, friend, griever) > config.RADIUS["interact"]:
                continue
            if _closeness(store.get(friend), griever) < rules.threshold(rules.COMFORT_MIN, _traits(engine, friend).get("loyalty", 0.5)):
                continue
            result = runner.run(friend, "comfort", {"target": griever}, proposer="rules")
            if result.ok:
                cool[("comfort", friend, griever)] = tick + COOLDOWN
                grief = of(record)["grief"]
                grief["relief"] = round(float(grief.get("relief", 0.0)) + rules.COMFORT_RELIEF, 4)
                store._mark_dirty(griever)
                driver.ladder.note(tick, friend, "emotion", "comfort", "ok", target=griever)
                done += 1
                break


# -- jealousy ---------------------------------------------------------------------------------------------------------------------
def _partner(store, awake_set: set, uid: str):
    record = store.get(uid)
    from systems.emotion import rules
    best = None
    for other, relation in _relations(record).items():
        closeness = float(relation.get("closeness", 0.0))
        if other in awake_set and closeness >= rules.PARTNER_MIN and _closeness(store.get(other), uid) >= rules.PARTNER_MIN:
            if best is None or (closeness, other) > best:
                best = (closeness, other)
    return None if best is None else best[1]


def _jealousy(driver, engine, runner, store, awake: list, cool: dict, tick: int) -> None:
    from systems.affordance import config
    from systems.emotion import of, rules
    awake_set = set(awake)
    for uid in awake:
        partner = _partner(store, awake_set, uid)
        if partner is None:
            continue
        record, mine = store.get(uid), None
        for rival in awake:
            if rival in (uid, partner) or _closeness(store.get(partner), rival) < rules.RIVAL_MIN:
                continue
            if _distance(engine, partner, rival) > config.RADIUS["interact"]:
                continue
            mine = of(record).setdefault("tension", {})
            step = rules.TENSION_STEP * (0.5 + rules.possessiveness(_traits(engine, uid)))
            mine[rival] = round(rules.clamp(float(mine.get(rival, 0.0)) + step), 4)
            if mine[rival] >= rules.TENSION_WARN:
                relation = _relations(record).get(rival)
                if relation is not None:
                    relation["closeness"] = round(max(-1.0, float(relation.get("closeness", 0.0)) - rules.TENSION_RESENT), 4)
                if (_distance(engine, uid, rival) <= config.RADIUS["interact"] and _calm(engine, uid) and uid not in driver.ladder.errands
                        and cool.get(("warn", uid, rival), -1) <= tick):
                    result = runner.run(uid, "warn", {"target": rival}, proposer="rules")
                    cool[("warn", uid, rival)] = tick + COOLDOWN
                    driver.ladder.note(tick, uid, "emotion", "warn", "ok" if result.ok else result.code, target=rival, why="jealousy")
            store._mark_dirty(uid)
