"""The creature behaviour kernel (``1008_creatures_gap.md`` sections 5 and 8): one vectorised step for the rows whose table entry says ``brain: table``.

No ``for`` over animals and no ``random``: every roll is a counter-based hash of ``(tick, slot, generation, stream)``, so the same seed and the same row layout replay bit for bit.
Per tick, for the active table-brain creatures ``C`` (alive, space 0, not dormant):

1. **activity**: ``activity[time block]`` is the chance a creature moves on its own this tick (a hash roll, not ``random``); fleeing and attacking are never throttled;
2. **perception**: the distance to every live human and to every other live animal (C x H and C x A matrices; ``C`` is bounded by the creature row quota, so this is a few thousand
   floats), the nearest threat (feared kind or human it fears), the nearest prey (``diet.prey``), the nearest human it may attack (``diet.humans``: ``always``, ``hungry`` = hunger over 50,
   ``cornered`` = a human within 1.5 reach or itself wounded);
3. **state** (lowest to highest priority, later assignments win): wander, cohere to the group's centroid, return home beyond ``territory.leash``, chase a target in ``aggro_range`` (decided
   per 20-tick epoch with ``aggro`` as the probability, so a wolf does not flicker), attack in range off cooldown, flee (hp under ``flee_hp`` or a threat inside ``fear.radius``);
4. **move** by the state's speed (walk, run) and write ``C_STATE``; attacks go through ``apply_human_damage`` / ``apply_entity_damage`` like the legacy loop, human victims get THREAT 100;
5. a kill refills the killer's hunger and queues ``creature_killed`` ``{species, pos, killer_uid}`` once per dead creature (the legacy ``animal_instinct_die`` zeroes the row on the next tick,
   so the scan runs at the end of the tick, from the step hook).

Home is derived from the uid (``c{cx}_{cy}:fauna:...`` -> that chunk's centre in the current window frame); creatures with another uid (god tools, births) have no home pull.
"""
from __future__ import annotations

import math
import re
from typing import Optional

import torch

try:
    import genesis_config as cfg
    import map_geo
    from harness import calendar as _calendar
    from harness.numerics import pairwise_distances, window_enabled
    from systems.health.damage import apply_entity_damage, apply_human_damage
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import map_geo
    from at_the_beginning.harness import calendar as _calendar
    from at_the_beginning.harness.numerics import pairwise_distances, window_enabled
    from at_the_beginning.systems.health.damage import apply_entity_damage, apply_human_damage
from . import collide, enabled, table as T

EPOCH = 20                  # ticks a chase decision stands
HEADING_TICKS = 32          # ticks a wander heading stands
WANDER_FRACTION = 0.5       # fraction of the walk speed a wandering creature uses
KILL_FEED = 30.0            # hunger a killer loses per kill
GRAZE_RATE = 0.06           # (legacy calendar; times calendar.rate_scale("needs") like the drain) hunger a grazer loses per tick standing on grass or sand (twice the legacy drain, ANIMAL_HUNGER_TICK_RATE 0.03)
FORAGE_CELL = 64.0           # units: a cell of 8x8 tiles
CELL_FOOD = 0.09            # hunger a forage cell can take off its grazers per tick, shared (three grazers at the legacy drain 0.03: the carrying capacity, about 48 per chunk)
CELL_CAPACITY = 3           # grazers a forage cell feeds (CELL_FOOD / the legacy drain 0.03)
BREED_HUNGER_MAX = 40.0     # hunger above which a creature does not breed
HOLD_COOLDOWN = 1.0         # the breeding cooldown the kernel pins on a creature that may not breed (the legacy birth rule needs it at zero), in legacy life-years
DRINK_RATE = 0.4            # thirst lost per tick within a tile of water (ten times the drain, 0.04)
SEEK_THIRST = 50.0          # thirst above which a creature walks to the nearest water within WATER_SEARCH units
WATER_SEARCH = 240.0
WATER_SEARCH_LONG = 1024.0  # the search under a non-legacy calendar (F4-2): herds spawned 387-486 units from water never drank within 240
WOUND_RANGE = 120.0         # under a non-legacy calendar a wounded creature flees only from a human or a harmful animal this near (F4-3; twice the predators' aggro range)
ADOPT_RADIUS = 16.0         # under a non-legacy calendar a newborn takes the home of the nearest of its species this near (its mother: born within 5 units, seen one step later)
HUNGRY = 50.0
CORNER_REACH = 1.5          # a "cornered" animal attacks humans within this many reaches
CHUNK_UNITS = 256.0
_HOME = re.compile(r"^c(-?\d+)_(-?\d+):fauna:")
_COLUMNS = ("hp", "walk", "run", "damage", "range", "cooldown", "aggro", "aggro_range", "flee_hp", "fear_humans", "fear_radius", "leash", "cohesion",
            "dawn", "day", "dusk", "night", "h_always", "h_hungry", "h_cornered", "table", "eats_none", "fly", "swim", "herb", "drinks")
_CACHE: dict = {}


def hold_cooldown() -> float:
    """The breeding hold in the active calendar's life-years: ``HOLD_COOLDOWN`` legacy life-years, i.e. the same 600 ticks of cooldown decay under
    both calendars (F3-4; exactly ``HOLD_COOLDOWN`` on the legacy calendar, 0.05 under EDEN_CALENDAR, where one life-year is a whole game day)."""
    return HOLD_COOLDOWN * _calendar.LEGACY_YEAR_TICKS / _calendar.active().life_year_ticks


def long_calendar() -> bool:
    """A non-legacy calendar is active (EDEN_CALENDAR): the gate of the F4-2 thirst rules, like the F3 litter in ``animal_tool_reproduce``."""
    return _calendar.active() is not _calendar.LEGACY


def water_search(hunts: bool = False) -> float:
    """How far a thirsty creature looks for water: ``WATER_SEARCH`` on the legacy calendar; under a non-legacy one ``WATER_SEARCH_LONG`` for a
    species with no prey (F4-2) and still ``WATER_SEARCH`` for one that ``hunts``: predators keep their leash and look for water from inside it."""
    return WATER_SEARCH_LONG if long_calendar() and not hunts else WATER_SEARCH


def params(device) -> tuple:
    """``(P, index, prey, fear, ids)``: a (80, K) parameter table indexed by ``M_TYPE``, name -> column, bool (80, 80) prey and fear matrices, and the table-brain ids."""
    key = (str(device), id(T.CREATURES), tuple(r["brain"] for r in T.CREATURES.values()))
    cached = _CACHE.get("params")
    if cached is not None and cached[0] == key:
        return cached[1]
    index = {name: i for i, name in enumerate(_COLUMNS)}
    P = torch.zeros(80, len(_COLUMNS), dtype=torch.float32)
    prey = torch.zeros(80, 80, dtype=torch.bool)
    fear = torch.zeros(80, 80, dtype=torch.bool)
    for name, row in T.CREATURES.items():
        i = row["id"]
        values = {"hp": row["hp"], "walk": row["speed"]["walk"], "run": row["speed"]["run"], "damage": row["damage"], "range": row["range"],
                  "cooldown": row["cooldown"], "aggro": row["aggro"], "aggro_range": row["aggro_range"], "flee_hp": row["flee_hp"],
                  "fear_humans": float(row["fear"]["humans"]), "fear_radius": row["fear"]["radius"], "leash": row["territory"]["leash"],
                  "cohesion": row["group"]["cohesion"], **{b: row["activity"][b] for b in T.TIME_BLOCKS},
                  "h_always": float(row["diet"]["humans"] == "always"), "h_hungry": float(row["diet"]["humans"] == "hungry"),
                  "h_cornered": float(row["diet"]["humans"] == "cornered"), "table": float(row["brain"] == "table"),
                  "eats_none": float(row["diet"]["eats"] == ["none"]), "fly": float(bool(row["flight"])), "swim": float(bool(row["swim"])),
                  "herb": float(bool({"grass", "forest"} & set(row["diet"]["eats"]))), "drinks": float(row["diet"]["eats"] != ["none"])}
        for column, value in values.items():
            P[i, index[column]] = float(value)
        for other in row["diet"]["prey"]:
            prey[i, T.id_of(other)] = True
        for other in row["fear"]["species"]:
            fear[i, T.id_of(other)] = True
    ids = torch.tensor([r["id"] for r in T.CREATURES.values() if r["brain"] == "table"], dtype=torch.float32)
    built = (P.to(device), index, prey.to(device), fear.to(device), ids.to(device))
    _CACHE["params"] = (key, built)
    return built


def table_brain_mask(m_types: torch.Tensor) -> torch.Tensor:
    """Rows whose type is a table-brain species (what the legacy animal loops must leave alone)."""
    return torch.isin(m_types, params(m_types.device)[4])


def legacy_rows(a_mask: torch.Tensor, m_tensor: torch.Tensor) -> torch.Tensor:
    """The identity hook of the two legacy animal loops: ``a_mask`` itself unless ``EDEN_CREATURES`` is on, then without the rows the kernel owns."""
    if not enabled() or not bool(a_mask.any()):
        return a_mask
    return a_mask & ~table_brain_mask(m_tensor[:, cfg.M_TYPE])


def unit(tick: int, slots: torch.Tensor, gens: torch.Tensor, stream: int) -> torch.Tensor:
    """Counter-based uniform [0, 1): a hash of (tick, slot, generation, stream); identical on every run and independent of the order of the rows."""
    x = (slots.long() * 0x9E3779B1 + gens.long() * 0x85EBCA77 + int(tick) * 0xC2B2AE3D + int(stream) * 0x27D4EB2F) & 0xFFFFFFFF
    x = x ^ (x >> 15)
    x = (x * 0x2C1B3C6D) & 0xFFFFFFFF
    x = x ^ (x >> 12)
    x = (x * 0x297A2D39) & 0xFFFFFFFF
    x = x ^ (x >> 15)
    return (x.double() / 4294967296.0).float()


def _home_chunks(engine, uids, pos=None, types=None) -> tuple:
    """(has_home bool list, chunk x list, chunk y list) from the uids; cached per uid. Under a non-legacy calendar, given the rows' ``pos`` and
    ``types``, a uid with no home chunk (a creature born in the window, ``e_*``) takes the home of the nearest creature of its species within
    ``ADOPT_RADIUS`` that has one (its mother), else the chunk it stands in (F4-2: born creatures had no leash). Legacy: no home, as before."""
    cache = engine.__dict__.setdefault("_creature_home", {})
    adopt = pos is not None and long_calendar()
    entries, new = [], []
    for i, uid in enumerate(uids):
        entry = cache.get(uid)
        if entry is None:
            found = _HOME.match(uid or "")
            if found:
                entry = cache[uid] = (int(found.group(1)), int(found.group(2)))
            elif adopt and uid:
                new.append(i)
            else:
                entry = cache[uid] = False
        entries.append(entry)
    if new:
        ox, oy = engine._window.frame.origin if getattr(engine, "_window", None) is not None else (0, 0)
        homed = [j for j, e in enumerate(entries) if e]
        for i in new:
            entry = False
            if homed:
                cand = torch.tensor(homed, device=pos.device)
                d = (pos[cand] - pos[i]).norm(dim=1)
                d = torch.where(types[cand] == types[i], d, torch.full_like(d, float("inf")))
                best, arg = d.min(dim=0)
                if float(best) <= ADOPT_RADIUS:
                    entry = entries[homed[int(arg)]]
            if not entry:
                entry = (ox + math.floor(float(pos[i, 0]) / CHUNK_UNITS), oy + math.floor(float(pos[i, 1]) / CHUNK_UNITS))
            entries[i] = cache[uids[i]] = entry
            homed.append(i)
    has, xs, ys = [], [], []
    for entry in entries:
        has.append(bool(entry))
        xs.append(entry[0] if entry else 0)
        ys.append(entry[1] if entry else 0)
    return has, xs, ys


def _block_index(tick: int) -> int:
    return T.TIME_BLOCKS.index(_calendar.tick_to_time_block(tick))


def _limits() -> tuple:
    width, height, (col0, row0) = _frame()
    tile = float(map_geo.TILE_SIZE)
    return col0 * tile, row0 * tile, (col0 + width) * tile, (row0 + height) * tile


def _frame():
    try:
        from harness.window import WINDOW_FRAME
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness.window import WINDOW_FRAME
    return WINDOW_FRAME


def step(engine) -> int:
    """One kernel tick for ``engine`` (a step hook). Returns the number of creatures that acted. No-op unless ``EDEN_CREATURES`` and ``EDEN_WINDOW`` are on."""
    if not enabled() or not window_enabled():
        return 0
    acted = _step(engine)
    _scan_kills(engine)                    # last: damage dealt this tick (by the kernel, the resolver, hunger) is visible before the legacy die zeroes the row
    return acted


def _step(engine) -> int:
    m, h = engine.state.m_tensor, engine.state.h_tensor
    n = cfg.MAX_ENTITIES
    P, col, PREY, FEAR, ids = params(m.device)
    types = m[:n, cfg.M_TYPE].long()
    alive = torch.isin(m[:n, cfg.M_TYPE], torch.tensor(sorted(cfg.ANIMAL_TYPES), dtype=m.dtype, device=m.device)) & (m[:n, cfg.M_SPACE] == 0) & (m[:n, cfg.M_HP] > 0)
    mine = alive & torch.isin(m[:n, cfg.M_TYPE], ids)
    dormant = getattr(engine, "_dormant_a", None)
    if dormant is not None:
        mine &= ~dormant[:n]
    cidx = mine.nonzero(as_tuple=False).flatten()
    if cidx.numel() == 0:
        return 0
    tick = int(engine.tick)
    pos = m[cidx][:, [cfg.CX, cfg.CY]]
    t = types[cidx]
    p = P[t]
    hp = m[cidx, cfg.M_HP]
    hp_frac = hp / p[:, col["hp"]].clamp(min=1e-6)
    hunger = m[cidx, cfg.A_HUNGER]
    slots = cidx
    gens = m[cidx, cfg.M_GEN]
    count = int(cidx.numel())
    inf = torch.full((count,), float("inf"), device=m.device)

    # -- perception ----------------------------------------------------------------------------------------------------------
    h_live = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.H_SPACE] == 0) & (h[:, cfg.HP] > 0)
    h_slots = h_live.nonzero(as_tuple=False).flatten()
    if h_slots.numel():
        hpos = h[h_slots][:, [cfg.X, cfg.Y]]
        dist_h = pairwise_distances(pos, hpos)
        dh, dh_arg = dist_h.min(dim=1)
    else:
        hpos = pos[:0]
        dh, dh_arg = inf.clone(), torch.zeros(count, dtype=torch.long, device=m.device)
    a_slots = alive.nonzero(as_tuple=False).flatten()
    apos = m[a_slots][:, [cfg.CX, cfg.CY]]
    dist_a = pairwise_distances(pos, apos)
    dist_a[cidx.unsqueeze(1) == a_slots.unsqueeze(0)] = float("inf")                       # not itself
    a_types = types[a_slots]
    prey_d = torch.where(PREY[t][:, a_types], dist_a, torch.full_like(dist_a, float("inf")))
    fear_d = torch.where(FEAR[t][:, a_types], dist_a, torch.full_like(dist_a, float("inf")))
    dp, dp_arg = prey_d.min(dim=1)
    df, df_arg = fear_d.min(dim=1)

    # -- decisions -----------------------------------------------------------------------------------------------------------
    epoch = tick // EPOCH
    chase_roll = unit(epoch, slots, gens, 1) < p[:, col["aggro"]]
    active = unit(tick, slots, gens, 0) < p[:, col[T.TIME_BLOCKS[_block_index(tick)]]]
    reach = p[:, col["range"]]
    wounded = hp_frac < 0.95
    human_ok = ((p[:, col["h_always"]] > 0) | ((p[:, col["h_hungry"]] > 0) & (hunger > HUNGRY))
                | ((p[:, col["h_cornered"]] > 0) & ((dh < reach * CORNER_REACH) | wounded)))
    aggro_range = p[:, col["aggro_range"]]
    human_target = human_ok & (dh < aggro_range) & (chase_roll | (dh < reach))
    prey_target = (dp < aggro_range) & (hunger > 20.0) & chase_roll & (p[:, col["damage"]] > 0)
    use_human = human_target & (~prey_target | (dh <= dp))
    use_prey = prey_target & ~use_human
    chasing = use_human | use_prey
    t_dist = torch.where(use_human, dh, torch.where(use_prey, dp, inf))
    scared_human = (p[:, col["fear_humans"]] > 0) & (dh < p[:, col["fear_radius"]])
    scared_animal = df < p[:, col["fear_radius"]]
    hurt = hp_frac < p[:, col["flee_hp"]]
    long_cal = long_calendar()
    hunts = PREY[t].any(dim=1) if long_cal else None                                            # a species with prey: keeps its leash when thirsty (F4-2 after seed 1)
    if long_cal:                                                                                # F4-3: a wound sends it running only from a real threat nearby
        harm = (P[a_types, col["damage"]] > 0).unsqueeze(0) | PREY[a_types][:, t].T | FEAR[t][:, a_types]
        harm = harm & (a_types.unsqueeze(0) != t.unsqueeze(1))                                  # another species that bites, hunts it or is feared: never a herd-mate
        d_harm, harm_arg = torch.where(harm, dist_a, torch.full_like(dist_a, float("inf"))).min(dim=1)
        fleeing = (hurt & (torch.minimum(dh, d_harm) < WOUND_RANGE)) | scared_human | scared_animal
    else:
        fleeing = hurt | scared_human | scared_animal
    can_hit = chasing & (t_dist <= reach) & (m[cidx, T.C_STATE_TICKS] <= 0.0) & (p[:, col["damage"]] > 0)
    attacking = can_hit & ~fleeing
    if bool(attacking.any()):                                                                 # a wall between them stops the blow
        aim = torch.where(use_human.unsqueeze(1), hpos[dh_arg] if hpos.shape[0] else pos, apos[dp_arg])
        attacking = attacking & ~collide.blocked_segments(engine, pos, aim)

    # -- vectors -------------------------------------------------------------------------------------------------------------
    target_pos = torch.where(use_human.unsqueeze(1), hpos[dh_arg] if hpos.shape[0] else pos, apos[dp_arg])
    d_any, any_arg = dist_a.min(dim=1)
    human_pos = hpos[dh_arg] if hpos.shape[0] else pos
    if long_cal:                                                                                # F4-3: the nearer of a human and a harmful animal
        origin_dist = torch.stack([dh, d_harm], dim=1)
        origin_pos = torch.stack([human_pos, apos[harm_arg]], dim=1)
    else:
        origin_dist = torch.stack([dh, df, d_any], dim=1)
        origin_pos = torch.stack([human_pos, apos[df_arg], apos[any_arg]], dim=1)             # the nearest of: a human, a feared kind, any animal (what hurt it)
    threat_pos = origin_pos[torch.arange(count, device=m.device), origin_dist.argmin(dim=1)]
    move = torch.zeros_like(pos)
    state = torch.zeros(count, device=m.device)
    walk, run = p[:, col["walk"]], p[:, col["run"]]

    angle = unit(tick // HEADING_TICKS, slots, gens, 2) * math.tau
    wander = torch.stack([torch.cos(angle), torch.sin(angle)], dim=1) * (walk * WANDER_FRACTION).unsqueeze(1)
    moves = active & (unit(tick // HEADING_TICKS, slots, gens, 3) < 0.7)
    move = torch.where(moves.unsqueeze(1), wander, move)
    state = torch.where(moves, torch.full_like(state, float(T.STATES["wander"])), state)

    group = m[cidx, T.C_GROUP].long()
    gid, inverse = torch.unique(group, return_inverse=True)
    sums = torch.zeros(gid.numel(), 2, device=m.device).index_add_(0, inverse, pos)
    members = torch.zeros(gid.numel(), device=m.device).index_add_(0, inverse, torch.ones(count, device=m.device))
    centre = sums[inverse] / members[inverse].clamp(min=1.0).unsqueeze(1)
    to_centre = centre - pos
    far = (group != 0) & (members[inverse] > 1) & (to_centre.norm(dim=1) > p[:, col["cohesion"]]) & active
    move = torch.where(far.unsqueeze(1), _toward(to_centre, walk), move)
    state = torch.where(far, torch.full_like(state, float(T.STATES["wander"])), state)

    has_home, hx, hy = _home_chunks(engine, [engine._entity_uid_by_slot[s] for s in cidx.tolist()], pos, t)
    ox, oy = engine._window.frame.origin if getattr(engine, "_window", None) is not None else (0, 0)
    home = torch.tensor([[(a - ox) * CHUNK_UNITS + CHUNK_UNITS / 2.0, (b - oy) * CHUNK_UNITS + CHUNK_UNITS / 2.0] for a, b in zip(hx, hy)], device=m.device).reshape(-1, 2)
    thirsty = (p[:, col["drinks"]] > 0) & (m[cidx, cfg.A_THIRST] > SEEK_THIRST)
    going = torch.zeros(count, dtype=torch.bool, device=m.device)
    if long_cal:
        divert = engine.__dict__.setdefault("_creature_water_home", set())
        divert.intersection_update(engine._entity_uid_by_slot[int(cidx[i])] for i in thirsty.nonzero(as_tuple=False).flatten().tolist())
    if bool(thirsty.any()):                                                                    # walk to the nearest water (the legacy loops had no food or water in the window at all)
        rows = thirsty.nonzero(as_tuple=False).flatten()
        vec, found = collide.toward_water(engine, pos[rows], water_search())
        if long_cal:                                                                            # predators keep the legacy search (F4-2 after seed 1)
            found = found & (~hunts[rows].to(found.device) | (vec.norm(dim=1) <= water_search(hunts=True)).to(found.device))
        if long_cal:
            # Remember a diversion until the animal drinks: during the return trip
            # both lakes can be outside the normal search radius.
            uids = [engine._entity_uid_by_slot[int(cidx[i])] for i in rows.tolist()]
            homed = torch.tensor(has_home, dtype=torch.bool, device=m.device)[rows]
            outside = (pos[rows] + vec.to(pos.device) - home[rows]).norm(dim=1) > p[rows, col["leash"]]
            candidates = hunts[rows] & homed & ((found.to(m.device) & outside) | torch.tensor([uid in divert for uid in uids], device=m.device))
            if bool(candidates.any()):
                indices = candidates.nonzero(as_tuple=False).flatten()
                home_vec, home_found = collide.toward_water(engine, home[rows[indices]], WATER_SEARCH_LONG)
                valid = home_found.to(m.device) & (home_vec.to(m.device).norm(dim=1) <= p[rows[indices], col["leash"]])
                for j, ok in zip(indices.tolist(), valid.tolist()):
                    if ok:
                        divert.add(uids[j])
                    else:
                        divert.discard(uids[j])
                chosen = indices[valid]
                vec[chosen] = (home[rows[chosen]] + home_vec[valid].to(m.device) - pos[rows[chosen]]).to(vec.device)
                found[chosen] = True
        going[rows] = found & ~collide.near_water(engine, pos[rows])
        full = torch.zeros_like(pos)
        full[rows] = vec.to(pos.device)
        move = torch.where(going.unsqueeze(1), _toward(full, walk), move)
        state = torch.where(going, torch.full_like(state, float(T.STATES["wander"])), state)
    to_home = home - pos
    homeward = torch.tensor(has_home, dtype=torch.bool, device=m.device) & (to_home.norm(dim=1) > p[:, col["leash"]])
    if long_cal:                                                                                # F4-2: thirst beats the leash for a species with no prey (flee and chase still win); predators and legacy: the leash wins
        homeward = homeward & ~(going & ~hunts)
    move = torch.where(homeward.unsqueeze(1), _toward(to_home, walk), move)
    state = torch.where(homeward, torch.full_like(state, float(T.STATES["return"])), state)

    move = torch.where(chasing.unsqueeze(1), _toward(target_pos - pos, run), move)
    state = torch.where(chasing, torch.full_like(state, float(T.STATES["chase"])), state)
    stop = chasing & (t_dist <= reach * 0.8)
    move = torch.where(stop.unsqueeze(1), torch.zeros_like(move), move)
    state = torch.where(attacking, torch.full_like(state, float(T.STATES["attack"])), state)
    move = torch.where(fleeing.unsqueeze(1), _toward(pos - threat_pos, run), move)
    state = torch.where(fleeing, torch.full_like(state, float(T.STATES["flee"])), state)

    # -- act -----------------------------------------------------------------------------------------------------------------
    x0, y0, x1, y1 = _limits()
    new = pos + move
    new[:, 0] = new[:, 0].clamp(x0, x1 - 1.0)
    new[:, 1] = new[:, 1].clamp(y0, y1 - 1.0)
    kind = torch.where(p[:, col["swim"]] > 0, torch.full_like(state, float(collide.SWIM)), torch.where(p[:, col["fly"]] > 0, torch.full_like(state, float(collide.FLY)), torch.zeros_like(state))).long()
    new, held = collide.resolve(engine, pos, new, kind)                                      # walls, built walls, interior slabs, water
    if held:
        engine.__dict__.setdefault("_creature_stats", {"held": 0})["held"] += held
    m[cidx, cfg.CX], m[cidx, cfg.CY] = new[:, 0], new[:, 1]
    hold = hold_cooldown()
    need = float(_calendar.rate_scale("needs"))                                                  # intake keeps pace with the drain, which the calendar scales (1.0 flag off)
    drinking = (p[:, col["drinks"]] > 0) & collide.near_water(engine, new)
    if bool(drinking.any()):
        m[cidx[drinking], cfg.A_THIRST] = (m[cidx[drinking], cfg.A_THIRST] - DRINK_RATE * need).clamp(min=0.0)
    grazing = (p[:, col["herb"]] > 0) & collide.on_graze(engine, new) & ~fleeing
    if bool(grazing.any()):
        rows = cidx[grazing]
        tile = torch.floor(new[grazing].double() / FORAGE_CELL).long()                                 # the grass of a forage cell is finite: the grazers in one cell share CELL_FOOD
        key = tile[:, 0] * 100003 + tile[:, 1]
        _, inverse, counts = torch.unique(key, return_inverse=True, return_counts=True)
        eat = torch.clamp(CELL_FOOD * need / counts[inverse].float(), max=GRAZE_RATE * need).to(m.dtype)
        m[rows, cfg.A_HUNGER] = (m[rows, cfg.A_HUNGER] - eat).clamp(min=0.0)
        crowded = rows[counts[inverse] > CELL_CAPACITY]                                         # no litters on a full pasture
        m[crowded, cfg.A_COOLDOWN] = m[crowded, cfg.A_COOLDOWN].clamp(min=hold)
    starving = cidx[m[cidx, cfg.A_HUNGER] > BREED_HUNGER_MAX]                                   # nor when hungry: the legacy birth rule (cooldown only) ignores food, so the kernel holds the cooldown
    m[starving, cfg.A_COOLDOWN] = m[starving, cfg.A_COOLDOWN].clamp(min=hold)
    m[cidx, T.C_STATE] = state
    timer = m[cidx, T.C_STATE_TICKS]
    m[cidx, T.C_STATE_TICKS] = (timer - 1.0).clamp(min=0.0)
    eats_none = p[:, col["eats_none"]] > 0
    if bool(eats_none.any()):
        m[cidx[eats_none], cfg.A_HUNGER] = 0.0
        m[cidx[eats_none], cfg.A_THIRST] = 0.0
    if bool(attacking.any()):
        _attack(engine, cidx, p, col, attacking, use_human, h_slots, dh_arg, a_slots, dp_arg)
        m[cidx[attacking], T.C_STATE_TICKS] = p[attacking][:, col["cooldown"]]
    return count


def _toward(vec: torch.Tensor, speed: torch.Tensor) -> torch.Tensor:
    norm = vec.norm(dim=1, keepdim=True).clamp(min=1e-6)
    return vec / norm * speed.unsqueeze(1)


def queue_human_kill(m: torch.Tensor, victim_slot: int, attacker_slot: int) -> None:
    """Pass a lethal resolver hit to the engine's creature death scan."""
    pending = getattr(m, "_creature_human_kills", None)
    if pending is None:
        pending = m._creature_human_kills = {}
    pending[victim_slot] = (int(m[victim_slot, cfg.M_GEN]), attacker_slot)


def record_killer(engine, victim_slot: int, killer_uid: str) -> bool:
    """Bind lethal attribution to both slot and current victim UID; the first successful attacker wins.

    Called only after actual combat damage. No loot, feeding or kill event is performed here.
    """
    if not enabled() or not killer_uid:
        return False
    m = engine.state.m_tensor
    if not 0 <= victim_slot < len(engine._entity_uid_by_slot):
        return False
    victim_uid = engine._entity_uid_by_slot[victim_slot]
    if (not victim_uid or float(m[victim_slot, cfg.M_HP]) > 0.0
            or int(m[victim_slot, cfg.M_TYPE]) not in {int(r["id"]) for r in T.CREATURES.values()}
            or victim_uid in engine.__dict__.get("_creature_killed", set())):
        return False
    killers = engine.__dict__.setdefault("_creature_killers", {})
    previous = killers.get(victim_slot)
    if previous is None or previous[0] != victim_uid:
        killers[victim_slot] = (victim_uid, killer_uid)
    return True


def _attack(engine, cidx, p, col, attacking, use_human, h_slots, dh_arg, a_slots, dp_arg) -> None:
    m, h = engine.state.m_tensor, engine.state.h_tensor
    who = attacking.nonzero(as_tuple=False).flatten()
    damage = p[who][:, col["damage"]]
    hit_human = use_human[who]
    if bool(hit_human.any()):
        victims = h_slots[dh_arg[who][hit_human]]
        total = torch.zeros(h.shape[0], device=h.device).index_add_(0, victims, damage[hit_human])
        mask = total > 0
        apply_human_damage(mask, h, total[mask], hp_col=cfg.HP)
        h[mask, cfg.THREAT] = 100.0
    animal = ~hit_human
    if bool(animal.any()):
        victims = a_slots[dp_arg[who][animal]]
        total = torch.zeros(m.shape[0], device=m.device).index_add_(0, victims, damage[animal])
        mask = total > 0
        before = m[victims, cfg.M_HP].clone()
        apply_entity_damage(mask, m, total[mask], hp_col=cfg.M_HP)
        after = m[victims, cfg.M_HP]
        uids = engine._entity_uid_by_slot
        for k, victim in enumerate(victims.tolist()):
            if float(before[k]) > 0.0 >= float(after[k]):
                record_killer(engine, victim, uids[int(cidx[who[animal][k]])])
                m[cidx[who[animal][k]], cfg.A_HUNGER] = max(0.0, float(m[cidx[who[animal][k]], cfg.A_HUNGER]) - KILL_FEED)


def _scan_kills(engine) -> None:
    """Queue ``creature_killed`` once for every creature row that has HP 0 while its type is a creature (run before the legacy die zeroes it, i.e. at the end of the tick)."""
    m = engine.state.m_tensor
    human_kills = vars(m).pop("_creature_human_kills", {})
    n = cfg.MAX_ENTITIES
    all_creatures = torch.isin(m[:n, cfg.M_TYPE], torch.tensor([float(r["id"]) for r in T.CREATURES.values()], dtype=m.dtype, device=m.device))
    dead = all_creatures & (m[:n, cfg.M_HP] <= 0.0) & (m[:n, cfg.M_SPACE] == 0)
    if not bool(dead.any()):
        return
    seen: set = engine.__dict__.setdefault("_creature_killed", set())
    killers: dict = engine.__dict__.setdefault("_creature_killers", {})
    for slot in dead.nonzero(as_tuple=False).flatten().tolist():
        uid = engine._entity_uid_by_slot[slot]
        if not uid or uid in seen:
            continue
        human_kill = human_kills.get(slot)
        if human_kill is not None:
            generation, attacker_slot = human_kill
            # The scan runs before the engine retires human slot UIDs for the tick.
            if generation == int(m[slot, cfg.M_GEN]):
                record_killer(engine, slot, engine._human_uid_by_slot[attacker_slot])
        seen.add(uid)
        attribution = killers.pop(slot, None)
        killer_uid = attribution[1] if attribution is not None and attribution[0] == uid else None
        engine._queue_event("creature_killed", uid, slot, species=T.name_of(m[slot, cfg.M_TYPE]), pos=[float(m[slot, cfg.CX]), float(m[slot, cfg.CY])],
                            killer_uid=killer_uid)
    if len(seen) > 4096:
        seen.clear()


# ---- install -------------------------------------------------------------------------------------------------------------------------------------------------
_INSTALLED: dict = {}
LEGACY_FIVE = (cfg.M_SHEEP, cfg.M_DEER, cfg.M_TIGER, cfg.M_WOLF, cfg.M_FISH)      # their numbers are the legacy ones already (the parity test); left alone
DICT_NAMES = ("ANIMAL_LIFE_EXP", "ANIMAL_SCALE", "ANIMAL_BASE_AGGRESSION", "ANIMAL_MOVE_STEP", "ANIMAL_PREY")


def install() -> int:
    """Write the table into the legacy per-species dictionaries (in place: ``instincts_and_tools`` imported the same dict objects) and the type schema for every species that is not
    one of the legacy five, so births, ageing, the legacy loops and the client's ``type_label`` / ``state`` see the new ids. Idempotent; ``uninstall`` removes exactly what was added."""
    if _INSTALLED:
        return 0
    derived = T.legacy_dicts(cfg.AGENT_TYPE_HUMAN)
    added = {name: [] for name in DICT_NAMES}
    for name in DICT_NAMES:
        target = getattr(cfg, name)
        for ident, value in derived[name].items():
            if ident in LEGACY_FIVE or ident in target:
                continue
            target[ident] = value
            added[name].append(ident)
    schema = []
    attrs = [{"col": c, "name": n, "dtype": d} for c, n, d in ((cfg.A_AGE, "age", "float"), (cfg.A_LIFE_EXP, "life_exp", "float"), (cfg.A_SEX, "sex", "int"),
                                                                    (cfg.A_COOLDOWN, "cooldown", "float"), (cfg.A_HUNGER, "hunger", "float"),
                                                                    (cfg.A_AGGRESSION, "aggression", "float"), (cfg.A_THIRST, "thirst", "float"),
                                                                    (T.C_VARIANT, "variant", "int"), (T.C_STATE, "behaviour", "int"))]
    for row in T.CREATURES.values():
        if row["id"] in LEGACY_FIVE or row["id"] in cfg.MAP_SCHEMA:
            continue
        cfg.MAP_SCHEMA[row["id"]] = {"label": row["label"], "mobile": True, "attrs": [dict(a) for a in attrs]}
        schema.append(row["id"])
    _INSTALLED.update({"dicts": added, "schema": schema})
    return sum(len(v) for v in added.values()) + len(schema)


def uninstall() -> None:
    for name, idents in _INSTALLED.get("dicts", {}).items():
        for ident in idents:
            getattr(cfg, name).pop(ident, None)
    for ident in _INSTALLED.get("schema", []):
        cfg.MAP_SCHEMA.pop(ident, None)
    _INSTALLED.clear()
