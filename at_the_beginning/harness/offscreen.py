"""R6.5 offscreen villages, option A (plan: .orchestration/wsim/handovers/1119wsimimplementation-plan-R6.5.md; design: dormancy_gap.md).

Flag ``EDEN_OFFSCREEN=1`` (default off; needs ``EDEN_WINDOW_DORMANCY=1``, which needs ``EDEN_WINDOW=1``). While residents are away their rows
stay frozen exactly as with the interim dormancy. When a row wakes, its **dormant group** (residents whose chunk or home anchor chunk touch,
D4) is advanced by the missed time with one pure function, ``coarse_ticks`` / ``coarse_days``, in place of the interim capped catch-up:

* food: the group's food rows (the game's food-source types and edible resource nodes in the group's chunks and the ring around them)
  regrow in closed form under their cap; each resident burns ``hunger rate x ticks`` and eats ``that / EAT_HUNGER_RESTORE x EAT_RESOURCE_COST``
  food units; a shortfall is shared, so every resident is fed the same fraction;
* needs: a fed resident ends the day at the active set point (``CATCH_UP_V2``, to be calibrated); the unfed share rises at the normal rate;
  water is taken as available (wells and lakes are not depleted by drinking);
* damage and healing: the ticks spent at hunger or thirst 90 or more cost the normal starvation / dehydration damage; a resident whose
  hunger stays under 70 heals at the normal rate;
* age advances exactly (with the roster age scale); cooldowns decay;
* death by the normal rules (D1): hp 0 (starvation, dehydration) or age past life expectancy (old age), on the day it happens; the dead
  stop eating. The woken row keeps the values that the normal ``instinct_hp_death`` / ``instinct_die`` then act on in the same tick.

The coarse model never moves anyone. Members of a group that are still dormant when the group is computed keep their result in a cache
and get it when they wake. Births while away (D3) are the next step (plan R6.5-births). Flag off, nothing here runs.
"""
from __future__ import annotations

import dataclasses
import math
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import genesis_config as cfg
    from . import calendar as _calendar
    from . import dormancy as _dormancy
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.harness import calendar as _calendar
    from at_the_beginning.harness import dormancy as _dormancy

FLAG = "EDEN_OFFSCREEN"
CHUNK_UNITS = 256.0

# Set points and knobs of the coarse model. hunger_fed / thirst_watered are placeholders until the calibration run
# (tools/offscreen_equivalence.py) measures an active village's daily means; the run waits for the suite lease.
CATCH_UP_V2 = {
    "hunger_fed": 30.0,
    "thirst_watered": 25.0,
    "forage_chunk_radius": 1,     # food rows count for a group in its chunks and this many chunks around them
    "starve_at": 90.0,            # systems/survival: hunger and thirst damage from 90
    "heal_below": 70.0,           # systems/health/recovery: heals while hunger < 70
    "calibrated": False,
}


# D3 births while away. UNCALIBRATED placeholder: the chance that a ready mother (both partners pass the normal readiness rule) conceives on
# one game day. The calibration run (tools/offscreen_equivalence.py on a non-roster village) replaces it. A roster world has no births at all
# (the normal rule: population_fixed), so the starter village gets 0 births whatever this number is.
BIRTH_P_PER_READY_DAY = 0.05
RETRY_EVERY = 20                  # ticks between attempts to place a deferred birth (as the creature store's sweep)


def enabled() -> bool:
    """Read at call time; needs the interim dormancy (which needs the window)."""
    return os.environ.get(FLAG, "") == "1" and _dormancy.enabled()


@dataclass(frozen=True)
class Rates:
    """Per-tick rates of the normal rules, plus the game day."""
    day_ticks: int
    hunger: float
    thirst: float
    starve_damage: float
    thirst_damage: float
    heal: float
    age_step: float
    cooldown_decay: float

    @staticmethod
    def current() -> "Rates":
        needs = _calendar.rate_scale("needs")
        return Rates(day_ticks=int(_calendar.active().day_ticks), hunger=cfg.HUNGER_TICK_RATE * needs, thirst=cfg.THIRST_TICK_RATE * needs,
                     starve_damage=2.0 * _calendar.rate_scale("starvation"),
                     thirst_damage=cfg.THIRST_DAMAGE_RATE * _calendar.rate_scale("damage_recovery"),
                     heal=cfg.HEAL_RATE * _calendar.rate_scale("damage_recovery"), age_step=_calendar.age_step(),
                     cooldown_decay=_calendar.cooldown_decay_rate())


@dataclass(frozen=True)
class Resident:
    uid: str
    sex: float
    age: float
    life_exp: float
    hunger: float
    thirst: float
    hp: float
    stamina: float = 100.0
    threat: float = 0.0
    cooldown: float = 0.0
    infection: float = 0.0
    needs_scale: float = 1.0
    age_scale: float = 1.0
    alive: bool = True
    # R6.5-roster: the roster needs loop (systems/roster/needs.py) as (threshold, drop): from the threshold the resident is met at the village
    # site (the need back to 0: drop = threshold) or by a ration on the spot (drop = ration). None: no loop, the fed/unfed model applies.
    hunger_loop: Optional[Tuple[float, float]] = None
    thirst_loop: Optional[Tuple[float, float]] = None


@dataclass(frozen=True)
class Food:
    key: object
    stock: float
    gain_per_tick: float = 0.0
    cap: Optional[float] = None      # None: the stock does not grow past what it is now


@dataclass
class Result:
    residents: Dict[str, Resident]
    foods: Dict[object, float]
    deaths: List[Tuple[str, int, str]]
    births: List[dict]
    eaten: float = 0.0


# -- the pure model --------------------------------------------------------------------------------------------------------------------
def coarse_days(residents: Sequence[Resident], foods: Sequence[Food], days: float, rates: Rates, *, start_day: int = 0,
                water: bool = True, seed: int = 0, births_allowed: bool = False, birth_p: Optional[float] = None) -> Result:
    """Advance a group by ``days`` game days (a fraction is a partial last day). Pure: plain data in, plain data out."""
    return coarse_ticks(residents, foods, float(days) * rates.day_ticks, rates, start_day=start_day, water=water, seed=seed,
                        births_allowed=births_allowed, birth_p=birth_p)


def coarse_ticks(residents: Sequence[Resident], foods: Sequence[Food], ticks: float, rates: Rates, *, start_day: int = 0,
                 water: bool = True, seed: int = 0, births_allowed: bool = False, birth_p: Optional[float] = None) -> Result:
    """The same, by ticks: whole days first, then the remainder. Independent of the order of ``residents`` and ``foods``.

    Births (``births_allowed``; False on a roster world): after each day's deaths, every ready mother of the group conceives with
    probability ``birth_p`` (default ``BIRTH_P_PER_READY_DAY``) x the day's fraction, drawn from ``rng(seed, day, "offscreen.birth", mother)``;
    the child (key ``birth:<mother>:<day>``) joins the group at age 0 and lives by the same rules from the next day."""
    people = {r.uid: r for r in sorted(residents, key=lambda r: r.uid)}
    stocks = {f.key: float(f.stock) for f in foods}
    plan = sorted(foods, key=lambda f: str(f.key))
    caps = {f.key: float(f.stock if f.cap is None else max(f.cap, 0.0)) for f in plan}
    result = Result(residents=people, foods=stocks, deaths=[], births=[])
    remaining = max(0.0, float(ticks))
    if remaining <= 0.0:
        return result
    day = int(start_day)
    p = BIRTH_P_PER_READY_DAY if birth_p is None else float(birth_p)
    while remaining > 0.0:
        t = float(rates.day_ticks) if remaining >= rates.day_ticks else remaining
        _one_step(result, plan, caps, t, rates, day, water)
        if births_allowed and p > 0.0:
            _births(result, t, rates, day, seed, p)
        remaining -= t
        day += 1
    for uid, r in result.residents.items():
        if r.alive:
            result.residents[uid] = dataclasses.replace(r, stamina=max(r.stamina, 100.0), threat=0.0)
    return result


def _one_step(result: Result, plan: Sequence[Food], caps: dict, t: float, rates: Rates, day: int, water: bool) -> None:
    stocks = result.foods
    for f in plan:                                                                  # closed-form regrowth under the cap
        if f.gain_per_tick > 0.0:
            stocks[f.key] = min(stocks[f.key] + f.gain_per_tick * t, caps[f.key])
    alive = [r for r in result.residents.values() if r.alive]
    starve_at, fed_point = CATCH_UP_V2["starve_at"], CATCH_UP_V2["hunger_fed"]
    rise = {r.uid: rates.hunger * r.needs_scale * t for r in alive}
    # A resident eats only what brings it back to the set point: below it, hunger rises as awake and nothing is eaten (R6.5-fix).
    excess = {r.uid: 0.0 if r.hunger_loop else max(0.0, r.hunger + rise[r.uid] - fed_point) for r in alive}   # loop: unlimited site
    demand = sum(excess[r.uid] / cfg.EAT_HUNGER_RESTORE * cfg.EAT_RESOURCE_COST for r in alive)
    available = sum(stocks[f.key] for f in plan)
    fed = 1.0 if demand <= 0.0 else min(1.0, available / demand)
    eaten = fed * demand
    if eaten > 0.0 and available > 0.0:
        share = eaten / available
        for f in plan:
            stocks[f.key] = max(0.0, stocks[f.key] - stocks[f.key] * share)
    result.eaten += eaten
    for r in alive:
        if r.hunger_loop:
            hunger_raw, starving = _loop(r.hunger + rise[r.uid], r.hunger_loop), 0.0
        else:
            hunger_raw = r.hunger + rise[r.uid] - fed * excess[r.uid]                # = fed x min(prev + rise, set point) + unfed x (prev + rise)
            starving = _ticks_at_or_over(r.hunger, hunger_raw, starve_at, t) if fed < 1.0 else 0.0
        thirst_raw = r.thirst + rates.thirst * r.needs_scale * t
        if r.thirst_loop:
            thirst_raw, parched = _loop(thirst_raw, r.thirst_loop), 0.0
        elif water:
            thirst_raw, parched = min(thirst_raw, CATCH_UP_V2["thirst_watered"]), 0.0       # never raised past its normal rise
        else:
            parched = _ticks_at_or_over(r.thirst, thirst_raw, starve_at, t)
        hunger, thirst = _clamp(hunger_raw, 0.0, 100.0), _clamp(thirst_raw, 0.0, 100.0)
        damage = rates.starve_damage * starving + rates.thirst_damage * parched
        heals = r.hunger < CATCH_UP_V2["heal_below"] and hunger < CATCH_UP_V2["heal_below"] and r.infection < cfg.INFECTION_THRESHOLD
        hp = _clamp(r.hp - damage + (rates.heal * t if heals else 0.0), 0.0, 100.0)
        age = r.age + rates.age_step * r.age_scale * t
        cooldown = max(0.0, r.cooldown - rates.cooldown_decay * t)
        cause = None
        if hp <= 0.0:
            cause = "starvation" if starving >= parched else "dehydration"
        elif age > r.life_exp:
            cause = "old_age"
        result.residents[r.uid] = dataclasses.replace(r, hunger=hunger, thirst=thirst, hp=hp, age=age, cooldown=cooldown, alive=cause is None)
        if cause is not None:
            result.deaths.append((r.uid, day, cause))


def _loop(value: float, loop: Tuple[float, float]) -> float:
    """The roster needs loop in closed form: under the threshold the need is what it rose to; from the threshold every crossing drops it
    by ``drop`` (a site: back to 0). The walk to the site and the stand there (40 / 60 ticks) are taken as instant: an approximation of
    under one trip's ticks of rise per trip."""
    threshold, drop = float(loop[0]), float(loop[1])
    if value < threshold or drop <= 0.0:
        return value
    return (threshold - drop) + math.fmod(value - threshold, drop)


def ready(r: Resident) -> bool:
    """The normal readiness rule (``Engine._slot_ready_for_mating``) on a resident's coarse values; stamina and threat are taken as
    rested while away (the wake sets them so). A cooldown under 1e-9 counts as run out (float residue of the daily decay)."""
    return (r.alive and r.age >= cfg.MATURE_AGE and r.cooldown <= 1e-9 and r.hunger <= cfg.SAFE_REPRO_HUNGER_MAX
            and r.thirst <= cfg.SAFE_REPRO_THIRST_MAX and r.hp >= cfg.SAFE_REPRO_HP_MIN)


def _births(result: Result, t: float, rates: Rates, day: int, seed: int, p: float) -> None:
    try:
        from .rng import Stream
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness.rng import Stream
    people = sorted(result.residents.values(), key=lambda r: r.uid)
    fathers = [r for r in people if r.sex != 1.0 and ready(r)]
    if not fathers:
        return
    chance = min(1.0, p * t / float(rates.day_ticks))
    for mother in [r for r in people if r.sex == 1.0 and ready(r)]:
        stream = Stream(int(seed), int(day), "offscreen.birth", mother.uid)
        if stream.random() >= chance:
            continue
        sex = 0.0 if stream.random() < 0.5 else 1.0
        life_exp = stream.uniform(cfg.LIFE_EXP_MIN, cfg.LIFE_EXP_MAX)
        key = f"birth:{mother.uid}:{day}"
        result.residents[mother.uid] = dataclasses.replace(mother, cooldown=1.0)
        result.residents[key] = Resident(uid=key, sex=sex, age=0.0, life_exp=life_exp, hunger=0.0, thirst=0.0, hp=100.0)
        result.births.append({"key": key, "mother_uid": mother.uid, "father_uid": fathers[0].uid, "day": int(day), "sex": sex,
                              "life_exp": life_exp})


def _ticks_at_or_over(start: float, end: float, threshold: float, t: float) -> float:
    """Ticks of a linear rise from ``start`` to ``end`` over ``t`` ticks spent at or over ``threshold``."""
    if end < threshold:
        return 0.0
    if start >= threshold or end <= start:
        return t
    return t * (end - threshold) / (end - start)


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


# -- groups (D4) ---------------------------------------------------------------------------------------------------------------------
def _chunk(point) -> Tuple[int, int]:
    return (int(math.floor(float(point[0]) / CHUNK_UNITS)), int(math.floor(float(point[1]) / CHUNK_UNITS)))


def cells_of(point, home=None) -> set:
    cells = {_chunk(point)}
    if home is not None:
        cells.add(_chunk(home))
    return cells


def group_residents(points: Dict[str, tuple], homes: Optional[Dict[str, tuple]] = None) -> List[set]:
    """Residents whose chunk or home-anchor chunk touch (8-neighbour) are one group; groups are transitive."""
    homes = homes or {}
    uids = sorted(points)
    cells = {u: cells_of(points[u], homes.get(u)) for u in uids}
    parent = {u: u for u in uids}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for i, a in enumerate(uids):
        for b in uids[i + 1:]:
            if any(abs(p[0] - q[0]) <= 1 and abs(p[1] - q[1]) <= 1 for p in cells[a] for q in cells[b]):
                parent[find(b)] = find(a)
    groups: Dict[str, set] = {}
    for u in uids:
        groups.setdefault(find(u), set()).add(u)
    return list(groups.values())


# -- the engine side -----------------------------------------------------------------------------------------------------------------
def _home_of(engine, uid) -> Optional[tuple]:
    """The roster home (sleep) anchor, if the resident has one; None otherwise (legacy residents)."""
    try:
        from systems.roster.driver import anchor_positions, roster_of
        roster, _ = roster_of(engine, uid)
        if not roster:
            return None
        anchors = anchor_positions(engine, roster)
        point = anchors.get("sleep") or anchors.get("home")
        return (float(point[0]), float(point[1])) if point is not None else None
    except Exception:  # noqa: BLE001 - no roster or no anchor registry: the resident groups by where it stands
        return None


def _scales(engine, h):
    try:
        from systems.roster.driver import age_scale_vector, needs_scale_vector
        return needs_scale_vector(engine, h), age_scale_vector(engine, h)
    except Exception:  # noqa: BLE001
        return None, None


def _resident_from_row(h, slot, uid, needs, ages) -> Resident:
    row = h[slot]
    return Resident(uid=uid, sex=float(row[cfg.H_SEX]), age=float(row[cfg.H_AGE]), life_exp=float(row[cfg.H_LIFE_EXP]),
                    hunger=float(row[cfg.HUNGER]), thirst=float(row[cfg.THIRST]), hp=float(row[cfg.HP]), stamina=float(row[cfg.H_STAMINA]),
                    threat=float(row[cfg.THREAT]), cooldown=float(row[cfg.H_COOLDOWN]), infection=float(row[cfg.H_INFECTION]),
                    needs_scale=float(needs[slot]) if needs is not None else 1.0, age_scale=float(ages[slot]) if ages is not None else 1.0)


def _ladder_food_limit(roster) -> Optional[float]:
    """The agent driver with the ladder and the market balance leaves food under ``LADDER_TIER0_HUNGER`` to the ladder (``inf``:
    ``EDEN_LADDER_STARVE``, no ration at all); None when the plain roster loop decides food."""
    from systems.roster.driver import is_agent_driven
    if not is_agent_driven(roster):
        return None
    from systems.actions import agent_driver
    from systems.actions.market_day import balance_enabled
    if not (agent_driver.actions_enabled() and agent_driver.ladder_module.enabled() and balance_enabled()):
        return None
    return float("inf") if os.environ.get(agent_driver.LADDER_STARVE_ENV, "") == "1" else float(agent_driver.LADDER_TIER0_HUNGER)


def _loops_of(engine, uid) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    """``(hunger_loop, thirst_loop)`` of a roster resident (see ``Resident``), ``(None, None)`` for a resident without a roster."""
    try:
        from systems.roster import needs as roster_needs
        from systems.roster.driver import roster_of
        roster, _ = roster_of(engine, uid)
        if not roster:
            return None, None
        settings, has_sites = roster_needs.settings(roster)
        threshold = float(settings["threshold"])
        loops = {}
        for kind in ("food", "water"):
            site = roster_needs.site_position(engine, settings, kind, has_sites)
            loops[kind] = (threshold, threshold if site is not None else float(settings["ration"]))
        limit = _ladder_food_limit(roster)
        if limit is not None:                                                    # the ladder feeds below the limit (not modelled: no help)
            top, site = max(threshold, limit), loops["food"][1] >= threshold
            loops["food"] = None if math.isinf(limit) else (top, top if site else loops["food"][1])
        return loops["food"], loops["water"]
    except Exception:  # noqa: BLE001 - when the roster cannot be read, the fed/unfed model (never more help than the normal rule gives)
        return None, None


def resident_for(engine, h, slot, uid, needs, ages) -> Resident:
    """The coarse resident of a row, with its roster needs loop."""
    hunger_loop, thirst_loop = _loops_of(engine, uid)
    return dataclasses.replace(_resident_from_row(h, slot, uid, needs, ages), hunger_loop=hunger_loop, thirst_loop=thirst_loop)


def _write_row(h, slot, r: Resident) -> None:
    for col, value in ((cfg.HUNGER, r.hunger), (cfg.THIRST, r.thirst), (cfg.HP, r.hp), (cfg.H_AGE, r.age), (cfg.H_STAMINA, r.stamina),
                       (cfg.THREAT, r.threat), (cfg.H_COOLDOWN, r.cooldown)):
        h[slot, col] = value


def _food_types():
    try:
        import instincts_and_tools as iat
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import instincts_and_tools as iat
    return sorted(int(t) for t in iat.FOOD_SOURCE_TYPES)


def foods_for(engine, cells: Iterable[tuple]) -> List[Food]:
    """The food rows a group lives on: food-source rows with food, in space 0, not burning, within the forage radius of its cells."""
    import torch
    m = engine.state.m_tensor
    cells = list(cells)
    if not cells:
        return []
    radius = int(CATCH_UP_V2["forage_chunk_radius"])
    kind = torch.zeros(m.shape[0], dtype=torch.bool, device=m.device)
    for food_type in _food_types():
        kind |= m[:, cfg.M_TYPE] == float(food_type)
    live = kind & (m[:, cfg.M_SPACE] == 0) & (m[:, cfg.M_BURNING] == 0) & (m[:, cfg.M_RESOURCE_FOOD] > 0)
    cx = torch.floor(m[:, cfg.CX].double() / CHUNK_UNITS).long()
    cy = torch.floor(m[:, cfg.CY].double() / CHUNK_UNITS).long()
    near = torch.zeros_like(live)
    for x, y in cells:
        near |= ((cx - x).abs() <= radius) & ((cy - y).abs() <= radius)
    out = []
    for slot in (live & near).nonzero(as_tuple=False).flatten().tolist():
        node = float(m[slot, cfg.M_TYPE]) == float(cfg.M_RESOURCE_NODE)
        out.append(Food(key=int(slot), stock=float(m[slot, cfg.M_RESOURCE_FOOD]),
                        gain_per_tick=float(m[slot, cfg.M_GROWTH_RATE]) if node else 0.0,
                        cap=float(m[slot, cfg.M_NODE_CAP]) if node else None))
    return out


def wake_all(engine, waking: Dict[str, int], dormant_now: Dict[str, int]) -> List[dict]:
    """Called by ``dormancy.refresh`` for the rows that stopped being dormant this tick (``{uid: dormant since tick}``), with the rows still
    dormant (``{uid: slot}``). Applies a cached result or computes the groups of the woken rows; returns the log entries it added."""
    h = engine.state.h_tensor
    tick = int(engine.tick)
    log = engine.__dict__.setdefault("_offscreen_log", [])
    cache = engine.__dict__.setdefault("_offscreen_cache", {})
    slots = {uid: _dormancy._slot_of(engine, uid) for uid in waking}
    added: List[dict] = []
    todo = {}
    for uid, since in waking.items():
        slot = slots[uid]
        if slot is None:
            cache.pop(uid, None)
            continue
        if uid in cache:
            _write_row(h, slot, cache.pop(uid))
            continue
        todo[uid] = since
    if not todo:
        return added
    since_all = dict(getattr(engine, "_dormant_since", {}) or {})
    since_all.update(waking)
    members = {uid: slots[uid] for uid in todo}
    members.update({uid: slot for uid, slot in dormant_now.items() if uid not in cache})
    points = {uid: (float(h[slot, cfg.X]), float(h[slot, cfg.Y])) for uid, slot in members.items()}
    homes = {uid: _home_of(engine, uid) for uid in members}
    homes = {uid: p for uid, p in homes.items() if p is not None}
    needs, ages = _scales(engine, h)
    rates = Rates.current()
    births_allowed, seed = _births_allowed(engine), _world_seed(engine)
    for group in group_residents(points, homes):
        if not group & set(todo):
            continue
        start = min(int(since_all.get(uid, tick)) for uid in group)
        people = [resident_for(engine, h, members[uid], uid, needs, ages) for uid in sorted(group)]
        cells = set().union(*(cells_of(points[uid], homes.get(uid)) for uid in group))
        foods = foods_for(engine, cells)
        out = coarse_ticks(people, foods, tick - start, rates, start_day=start // rates.day_ticks, seed=seed, births_allowed=births_allowed)
        for birth in out.births:
            child = out.residents[birth["key"]]
            if not child.alive:                                           # born and died while away: logged, nothing to place
                continue
            anchor = points.get(birth["mother_uid"]) or points[sorted(group)[0]]
            _pending(engine).append({"uid": engine._make_human_id(), "group": sorted(group)[0], "mother_uid": birth["mother_uid"],
                                     "father_uid": birth["father_uid"], "day": birth["day"], "sex": birth["sex"],
                                     "life_exp": birth["life_exp"], "age": child.age, "hunger": child.hunger, "at_tick": tick,
                                     "anchor": [anchor[0], anchor[1]], "reason": ""})
            _counters(engine)["births"] += 1
        for f in foods:
            engine.state.m_tensor[int(f.key), cfg.M_RESOURCE_FOOD] = out.foods[f.key]
        for uid in sorted(group):
            if uid in todo:
                _write_row(h, members[uid], out.residents[uid])
            else:
                cache[uid] = out.residents[uid]                       # still dormant: applied when it wakes
        entry = {"tick": tick, "event": "group", "members": sorted(group), "ticks": tick - start, "eaten": round(out.eaten, 6),
                 "foods": len(foods), "births": len(out.births)}
        added.append(entry)
        for uid, day, cause in out.deaths:
            added.append({"tick": tick, "event": "death", "uid": uid, "day": int(day), "cause": cause})
    log.extend(added)
    del log[:-256]
    if engine.__dict__.get("_offscreen_pending"):
        place_pending(engine)
    return added


# -- births at wake (plan R6.5-births) -----------------------------------------------------------------------------------------------
def _births_allowed(engine) -> bool:
    """The normal rule: a roster world's population is its roster (``population_fixed``), so it has no births."""
    try:
        from systems.roster.apply import world_has_roster
        return not world_has_roster(engine)
    except Exception:  # noqa: BLE001 - when the roster cannot be judged, no births (never more than the normal rule allows)
        return False


def _world_seed(engine) -> int:
    try:
        from .window_manager import world_seed_of
        return int(world_seed_of(engine))
    except Exception:  # noqa: BLE001
        return 0


def _pending(engine) -> list:
    return engine.__dict__.setdefault("_offscreen_pending", [])


def _counters(engine) -> dict:
    return engine.__dict__.setdefault("_offscreen_counters", {"births": 0, "births_placed": 0, "births_deferred": 0})


def _integrated(engine, x, y) -> bool:
    manager = getattr(engine, "_window", None)
    if manager is None:
        return False
    ox, oy = manager.frame.origin
    cx, cy = _chunk((x, y))
    return any(c.x - ox == cx and c.y - oy == cy for c in manager.chunks)


def _place_one(engine, birth) -> str:
    """Try to put one counted birth into the world. Returns "" when placed, else the reason it waits ("no_slot" / "no_place")."""
    import torch
    try:
        import instincts_and_tools as iat
        import systems.movement.spatial as spatial
        from . import instinct_bits
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import instincts_and_tools as iat
        import at_the_beginning.systems.movement.spatial as spatial
        from at_the_beginning.harness import instinct_bits
    from .rng import Stream
    h = engine.state.h_tensor
    free = torch.where(h[:, cfg.TYPE] == cfg.AGENT_TYPE_EMPTY)[0]
    if engine._pop_count[0] >= cfg.MAX_HUMANS or not len(free):
        return "no_slot"
    mother, father = _dormancy._slot_of(engine, birth["mother_uid"]), _dormancy._slot_of(engine, birth["father_uid"])
    parent = mother if mother is not None else father
    base = (float(h[parent, cfg.X]), float(h[parent, cfg.Y])) if parent is not None else tuple(birth["anchor"])
    stream = Stream(_world_seed(engine), int(birth["day"]), "offscreen.birth.place", birth["uid"])
    point = spatial.standable_spawn_point(engine, base[0] + stream.uniform(-4.0, 4.0), base[1] + stream.uniform(-4.0, 4.0))
    if point is None or not _integrated(engine, point[0], point[1]):
        return "no_place"
    child = int(free[0].item())
    age = float(birth["age"]) + _calendar.age_step() * max(0, int(engine.tick) - int(birth["at_tick"]))   # a delay does not make it younger
    instincts = float(h[mother, cfg.ACQUIRED_INSTINCT_MASK]) if mother is not None else 0.0
    tribe = float(h[mother, cfg.H_TRIBE]) if mother is not None else 0.0
    if not iat.instinct_born(h, engine._pop_count, float(point[0]), float(point[1]), sex=float(birth["sex"]), life_exp=float(birth["life_exp"]),
                             age=age, hunger=float(birth["hunger"]), parent_instincts=instincts, tribe=tribe):
        return "no_slot"
    if mother is not None:
        instinct_bits.inherit_words(h, child, mother)
    engine._human_uid_by_slot[child] = birth["uid"]                     # the uid reserved when the birth was counted
    engine.resident_store.ensure_resident(birth["uid"], child, h, int(engine.tick))
    parents = [str(u) for u in (birth["mother_uid"], birth["father_uid"]) if str(u or "").strip()]
    engine._pending_birth_links_by_slot[child] = {"tick": int(engine.tick), "parent_ids": parents, "born_day": int(birth["day"])}
    return ""


def place_pending(engine) -> int:
    """Place every counted birth that can be placed now; the others stay pending with their reason (never dropped). Returns how many were placed."""
    pending, counters = _pending(engine), _counters(engine)
    placed, keep = 0, []
    for birth in sorted(pending, key=lambda b: (int(b["day"]), str(b["mother_uid"]), str(b["uid"]))):
        reason = _place_one(engine, birth)
        if reason:
            if birth.get("reason") != reason:
                counters["births_deferred"] += 1
            birth["reason"] = reason
            keep.append(birth)
        else:
            placed += 1
            counters["births_placed"] += 1
            engine.__dict__.setdefault("_offscreen_log", []).append({"tick": int(engine.tick), "event": "birth", "uid": birth["uid"],
                                                                     "mother_uid": birth["mother_uid"], "day": int(birth["day"])})
    pending[:] = keep
    return placed


def retry(engine) -> None:
    """Called by ``dormancy.refresh`` each tick with the flag on: every ``RETRY_EVERY`` ticks, try the deferred births again."""
    if engine.__dict__.get("_offscreen_pending") and int(engine.tick) % RETRY_EVERY == 0:
        place_pending(engine)


# -- save (the optional window key ``offscreen``, written by persistence/world_snapshot.py) -------------------------------------------
PENDING_KEYS = {"uid", "group", "mother_uid", "father_uid", "day", "sex", "life_exp", "age", "hunger", "at_tick", "anchor", "reason"}


def export(engine) -> Optional[dict]:
    """The section to save, or None when nothing is pending (then no key is written and the save is unchanged)."""
    pending = engine.__dict__.get("_offscreen_pending")
    if not pending:
        return None
    return {"pending_births": [dict(b) for b in pending], "counters": dict(_counters(engine))}


def validate_section(section) -> None:
    if not isinstance(section, dict) or not isinstance(section.get("pending_births"), list) or not section["pending_births"]:
        raise ValueError("Invalid offscreen section in the streaming window")
    for birth in section["pending_births"]:
        if not isinstance(birth, dict) or set(birth) != PENDING_KEYS:
            raise ValueError("Invalid pending birth in the offscreen section")


def load(engine, section) -> None:
    """Restore the pending births (``section`` None: nothing pending)."""
    engine._offscreen_pending = [dict(b) for b in section["pending_births"]] if section else []
    engine._offscreen_counters = dict(section.get("counters", {})) if section else {"births": 0, "births_placed": 0, "births_deferred": 0}
