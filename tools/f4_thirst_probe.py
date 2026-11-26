"""F4 diagnosis probe (thirst deaths under EDEN_CALENDAR): where is the water, and why does a thirsty creature not reach it?

    .venv/Scripts/python.exe tools/f4_thirst_probe.py --thirst-json f4.json [--boot-only]
                                                      [f3_animal_deaths.py / creature_balance.py args: --days 3 --brain kernel --calendar user --seed 1
                                                       --deaths-json f3.json [--json balance.json]]

Runs ``tools/f3_animal_deaths.py`` (and through it ``tools/creature_balance.py``) unchanged and only observes after every ``kernel.step``,
with the kernel's own helpers (``collide._grids`` water tiles, ``collide.near_water``, the home chunk from the uid, the table's leash).

* ``--boot-only``: at observed tick ``--boot-tick`` (default 1; plan spawns arrive later), write a table per home chunk (uid prefix ``c<x>_<y>:fauna:``): the distance from the
  chunk centre (the kernel's ``home``) to the nearest water tile, against ``WATER_SEARCH`` and the species' leash, plus each creature's own
  distance to water, and per chunk of the window its water tiles and centre-to-water distance. Then exit.
* full run: per drinking creature per tick, the conditions of ``kernel.step``'s thirst move as they stand after the step (the next step's input):
  ``seek`` (thirst > SEEK_THIRST, water within WATER_SEARCH, not already within a tile of it), ``unseen`` (thirsty, no water within
  WATER_SEARCH), ``leashed`` (thirsty and farther than its leash from its home centre: ``homeward`` overrides the thirst move), ``near`` (within a
  tile of water), ``drank`` (thirst fell this tick), the window edge, and per thirst death its last chunk and distances.
  F4-2: the search radius is ``kernel.water_search()`` when the kernel has it (1024 under EDEN_CALENDAR after F4-2), else ``WATER_SEARCH``. Per seeker
  (thirsty, water in range, not yet near) the move that won the step, from the kernel's own ``C_STATE``: ``seek_flee`` / ``seek_return`` (the leash) /
  ``seek_chase``; ``seek_held`` (``collide.resolve`` cut the move short: walls, slabs, the shore); ``wounded`` / ``seek_wounded`` (HP below
  ``flee_hp`` x the table HP: the kernel's flee-on-wounds holds for life, animals do not heal). ``collide.resolve`` is wrapped to read the
  per-row cut; rows are matched to slots by their resolved position. F4-3: ``flee`` (the kernel's state is flee), ``flee_human`` (and the nearest
  threat is a human, i.e. a resident, not a harmful animal), ``flee_no_threat`` (no human and no harmful animal at all: the old herd-mate flight).
  F4-2 after seed 1 (resident deaths): the home is the kernel's own cached home when it has one (a newborn's adopted home), and the search radius is
  ``kernel.water_search(hunts=...)`` per species when the kernel takes it. Per hostile creature per tick within its ``aggro_range`` of a resident:
  ``near_res`` and its split ``near_res_chase`` / ``_attack`` / ``_water`` (thirsty, walking to water) / ``_return`` (the leash) / ``_thirsty`` /
  ``_hungry`` (hunger > ``kernel.HUNGRY``) / ``_born`` (uid ``e_*``) / ``_beyond_leash``. At each resident death (``Balance.describe_death``) the
  killer's last per-tick record; ``resident_deaths`` holds the total, the distinct victims and killers, and every record.
Engine files are not touched; nothing is written but the JSON files.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

mine = argparse.ArgumentParser(add_help=False)
mine.add_argument("--thirst-json", required=True)
mine.add_argument("--boot-only", action="store_true")
mine.add_argument("--boot-tick", type=int, default=1, help="observed tick of the home-chunk table (plan spawns arrive after the first tick)")
MINE, REST = mine.parse_known_args()
sys.argv = [sys.argv[0]] + REST                            # f3_animal_deaths and creature_balance parse their own arguments at import

import torch  # noqa: E402

import tools.f3_animal_deaths as f3  # noqa: E402

cb, cfg, kernel, table = f3.cb, f3.cfg, f3.kernel, f3.table
from systems.creatures import collide  # noqa: E402

DRINKERS = {row["id"]: name for name, row in table.CREATURES.items() if row["diet"]["eats"] != ["none"]}
LEASH = {row["id"]: float(row["territory"]["leash"]) for row in table.CREATURES.values()}
WOUND_HP = {row["id"]: float(row["flee_hp"]) * float(row["hp"]) for row in table.CREATURES.values()}   # HP below this: the kernel's flee-on-wounds
CHUNK = kernel.CHUNK_UNITS
S_FLEE, S_CHASE, S_RETURN, S_ATTACK = (float(table.STATES[k]) for k in ("flee", "chase", "return", "attack"))
HOSTILE = {row["id"] for row in table.CREATURES.values() if row["hostile"]}
HUNTS = {row["id"]: bool(row["diet"]["prey"]) for row in table.CREATURES.values()}
AGGRO_RANGE = {row["id"]: float(row["aggro_range"]) for row in table.CREATURES.values()}


_ID = {name: row["id"] for name, row in table.CREATURES.items()}
HARM = torch.zeros(80, 80, dtype=torch.bool)                  # HARM[i, j]: species j can hurt species i (F4-3's rule: another species that bites, hunts i or is feared)
for _ni, _ri in table.CREATURES.items():
    for _nj, _rj in table.CREATURES.items():
        if _ni != _nj and (float(_rj["damage"]) > 0 or _ni in _rj["diet"]["prey"] or _nj in _ri["fear"]["species"]):
            HARM[_ri["id"], _rj["id"]] = True


def threat_split(engine, pos, types):
    """(nearest live human [N], nearest harmful animal [N]) distances, for telling a flight from a resident from one from a predator."""
    h = engine.state.h_tensor
    live = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.H_SPACE] == 0) & (h[:, cfg.HP] > 0)
    hpos = h[live][:, [cfg.X, cfg.Y]].cpu().float()
    inf = torch.full((pos.shape[0],), float("inf"))
    dh = torch.cdist(pos.float(), hpos).min(dim=1).values if hpos.shape[0] else inf
    m = engine.state.m_tensor[:cfg.MAX_ENTITIES]
    alive = (m[:, cfg.M_HP] > 0) & torch.isin(m[:, cfg.M_TYPE], torch.tensor(sorted(cfg.ANIMAL_TYPES), dtype=m.dtype, device=m.device)) & (m[:, cfg.M_SPACE] == 0)
    apos, atype = m[alive][:, [cfg.CX, cfg.CY]].cpu().float(), m[alive, cfg.M_TYPE].long().cpu()
    if apos.shape[0] == 0:
        return dh, inf
    d = torch.cdist(pos.float(), apos)
    harm = HARM[torch.tensor(types, dtype=torch.long)][:, atype]
    return dh, torch.where(harm, d, torch.full_like(d, float("inf"))).min(dim=1).values


def search_radius(hunts: bool = False) -> float:
    if not hasattr(kernel, "water_search"):
        return float(kernel.WATER_SEARCH)
    try:
        return float(kernel.water_search(hunts=hunts))
    except TypeError:                                         # the kernel before the predator rule
        return float(kernel.water_search())


def human_dist(engine, pos):
    """Distance [N] from each position to the nearest live human (a resident in creature_balance)."""
    h = engine.state.h_tensor
    live = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.H_SPACE] == 0) & (h[:, cfg.HP] > 0)
    hpos = h[live][:, [cfg.X, cfg.Y]].cpu().float()
    if hpos.shape[0] == 0 or pos.shape[0] == 0:
        return torch.full((pos.shape[0],), float("inf"))
    return torch.cdist(pos.float(), hpos).min(dim=1).values


HELD: dict = {}                                               # resolved (x, y) -> the move was cut short, from the last kernel resolve
_inner_resolve = collide.resolve


def _resolve(engine, start, desired, kind):
    out, held = _inner_resolve(engine, start, desired, kind)
    HELD.clear()
    cut = ((out.double().cpu() - desired.double().cpu()).abs().sum(dim=1) > 1e-9).tolist()
    for (x, y), c in zip(out.cpu().tolist(), cut):
        HELD[(x, y)] = HELD.get((x, y), False) or c
    return out, held


assert kernel.collide is collide, "the probe must wrap the kernel's own collide module"
collide.resolve = _resolve                                   # the kernel calls collide.resolve through the module


def water_centres(engine):
    found = collide._grids(engine)
    if found is None:
        return None
    water, col0, row0 = found[0], found[3], found[4]
    tiles = water.nonzero(as_tuple=False)
    if tiles.shape[0] == 0:
        return torch.zeros(0, 2)
    return torch.stack([(tiles[:, 1] + col0 + 0.5) * collide.TILE, (tiles[:, 0] + row0 + 0.5) * collide.TILE], dim=1).float()


def nearest(xy: torch.Tensor, centres) -> torch.Tensor:
    if centres is None or centres.shape[0] == 0 or xy.shape[0] == 0:
        return torch.full((xy.shape[0],), float("inf"))
    return torch.cdist(xy.float(), centres).min(dim=1).values


def origin(engine):
    return engine._window.frame.origin if getattr(engine, "_window", None) is not None else (0, 0)


def rows(engine):
    """(slots, uids, species ids, positions [N,2], thirst [N]) of the live drinking creatures."""
    m = engine.state.m_tensor[:cfg.MAX_ENTITIES]
    types = m[:, cfg.M_TYPE]
    live = (m[:, cfg.M_HP] > 0) & torch.isin(types, torch.tensor(sorted(DRINKERS), dtype=types.dtype, device=types.device))
    slots = live.nonzero(as_tuple=False).flatten().tolist()
    uids = engine._entity_uid_by_slot
    keep = [s for s in slots if uids[s]]
    if not keep:
        return [], [], [], torch.zeros(0, 2), torch.zeros(0)
    idx = torch.tensor(keep, device=m.device)
    return keep, [uids[s] for s in keep], [int(t) for t in types[idx].tolist()], m[idx][:, [cfg.CX, cfg.CY]].cpu(), m[idx, cfg.A_THIRST].cpu()


def extras(engine, slots):
    """(hp [N], kernel state [N], hunger [N]) of the given slots."""
    m = engine.state.m_tensor
    if not slots:
        return torch.zeros(0), torch.zeros(0), torch.zeros(0)
    idx = torch.tensor(slots, device=m.device)
    return m[idx, cfg.M_HP].cpu(), m[idx, table.C_STATE].cpu(), m[idx, cfg.A_HUNGER].cpu()


def home_of(uid, ox, oy, engine=None):
    """(home chunk, home centre) as the kernel sees it: its cached home when it has one (a newborn's adopted home), else the uid's chunk."""
    entry = engine.__dict__.get("_creature_home", {}).get(uid) if engine is not None else None
    if entry is False:
        return None, None
    if entry is None:
        found = kernel._HOME.match(uid or "")
        if not found:
            return None, None
        entry = (int(found.group(1)), int(found.group(2)))
    hx, hy = entry
    return (hx, hy), ((hx - ox) * CHUNK + CHUNK / 2.0, (hy - oy) * CHUNK + CHUNK / 2.0)


def chunk_of(x, y, ox, oy):
    return f"c{ox + int(x // CHUNK)}_{oy + int(y // CHUNK)}"


class Thirst:
    def __init__(self):
        self.stats = defaultdict(lambda: defaultdict(int))     # uid -> counters
        self.last = {}                                        # uid -> last per-tick record
        self.resident_deaths = []                             # one record per resident death, with the killer's last per-tick record
        self.thirst_prev = {}
        self.tick = 0
        self.seconds = 0.0
        self.boot = None
        self.window = None
        self.chunks = None
        self.boot_at = None

    def boot_table(self, engine):
        ox, oy = origin(engine)
        centres = water_centres(engine)
        slots, uids, types, pos, thirst = rows(engine)
        own = nearest(pos, centres)
        groups = defaultdict(list)
        for i, uid in enumerate(uids):
            home, centre = home_of(uid, ox, oy)
            key = f"c{home[0]}_{home[1]}" if home else "no_home"
            groups[(key, DRINKERS[types[i]])].append((i, centre))
        out = []
        for (key, species), members in sorted(groups.items()):
            leash = LEASH[table.CREATURES[species]["id"]]
            entry = {"home": key, "species": species, "count": len(members), "leash": leash,
                     "own_to_water": sorted(round(float(own[i]), 1) for i, _ in members)}
            centre = members[0][1]
            if centre is not None:
                d = float(nearest(torch.tensor([centre]), centres)[0])
                entry["centre_to_water"] = round(d, 1)
                entry["verdict"] = ("no water in the window" if d == float("inf") else
                                    "water inside the leash" if d <= leash else
                                    "water beyond the leash, visible from its edge" if d <= leash + kernel.WATER_SEARCH else
                                    "no water within leash + WATER_SEARCH")
            out.append(entry)
        x0, y0, x1, y1 = kernel._limits()
        self.window = {"origin": list(origin(engine)), "limits": [x0, y0, x1, y1], "water_tiles": 0 if centres is None else int(centres.shape[0]),
                       "water_grid": None if collide._grids(engine) is None else {"col0": int(collide._grids(engine)[3]), "row0": int(collide._grids(engine)[4]),
                                                                                    "shape": list(collide._grids(engine)[0].shape), "tile": collide.TILE}}
        self.boot = out
        self.chunks = []
        if centres is not None:
            x0, y0, x1, y1 = kernel._limits()
            for cy in range(int(y0 // CHUNK), int(y1 // CHUNK)):
                for cx in range(int(x0 // CHUNK), int(x1 // CHUNK)):
                    lo = torch.tensor([cx * CHUNK, cy * CHUNK]); hi = lo + CHUNK
                    inside = int(((centres >= lo) & (centres < hi)).all(dim=1).sum()) if centres.shape[0] else 0
                    d = float(nearest(torch.tensor([[cx * CHUNK + CHUNK / 2.0, cy * CHUNK + CHUNK / 2.0]]), centres)[0])
                    self.chunks.append({"chunk": f"c{ox + cx}_{oy + cy}", "water_tiles": inside, "centre_to_water": round(d, 1)})
        self.boot_at = self.tick

    def observe(self, engine):
        self.tick += 1
        ox, oy = origin(engine)
        centres = water_centres(engine)
        slots, uids, types, pos, thirst = rows(engine)
        if not uids:
            return
        dist = nearest(pos, centres)
        near = collide.near_water(engine, pos).cpu()
        hp, state, hunger = extras(engine, slots)
        radius = {False: search_radius(False), True: search_radius(True)}
        fleeing_any = bool((state == S_FLEE).any())
        dh, d_harm = threat_split(engine, pos, types) if fleeing_any else (None, None)
        res_d = human_dist(engine, pos) if any(ty in HOSTILE for ty in types) else None
        x0, y0, x1, y1 = kernel._limits()
        for i, uid in enumerate(uids):
            s = self.stats[uid]
            t = float(thirst[i])
            x, y = float(pos[i, 0]), float(pos[i, 1])
            home, centre = home_of(uid, ox, oy, engine)
            leash = LEASH[types[i]]
            to_home = ((x - centre[0]) ** 2 + (y - centre[1]) ** 2) ** 0.5 if centre else 0.0
            thirsty = t > kernel.SEEK_THIRST
            seen = float(dist[i]) <= radius[HUNTS[types[i]]]
            wounded = float(hp[i]) < WOUND_HP[types[i]]
            st = float(state[i])
            born = not kernel._HOME.match(uid or "")
            s["ticks"] += 1
            s["wounded"] += int(wounded)
            if res_d is not None and types[i] in HOSTILE and float(res_d[i]) <= AGGRO_RANGE[types[i]]:
                s["near_res"] += 1
                s["near_res_chase"] += int(st == S_CHASE)
                s["near_res_attack"] += int(st == S_ATTACK)
                s["near_res_water"] += int(thirsty and seen and not bool(near[i]))
                s["near_res_return"] += int(st == S_RETURN)
                s["near_res_thirsty"] += int(thirsty)
                s["near_res_hungry"] += int(float(hunger[i]) > kernel.HUNGRY)
                s["near_res_born"] += int(born)
                s["near_res_beyond_leash"] += int(centre is not None and to_home > leash)
            if st == S_FLEE:
                s["flee"] += 1
                s["flee_human"] += int(float(dh[i]) <= float(d_harm[i]))     # the nearest threat is a human (a resident in creature_balance)
                s["flee_no_threat"] += int(float(dh[i]) == float("inf") and float(d_harm[i]) == float("inf"))
            if thirsty:
                s["thirsty"] += 1
                seeking = seen and not bool(near[i])
                s["seek"] += int(seeking)
                s["unseen"] += int(not seen)
                s["unseen_240"] += int(float(dist[i]) > kernel.WATER_SEARCH)
                s["leashed"] += int(centre is not None and to_home > leash)
                s["leashed_seen"] += int(centre is not None and to_home > leash and seen)
                if seeking:
                    s["seek_flee"] += int(st == S_FLEE)
                    s["seek_return"] += int(st == S_RETURN)
                    s["seek_chase"] += int(st == S_CHASE)
                    s["seek_held"] += int(HELD.get((x, y), False))
                    s["seek_wounded"] += int(wounded)
            if t >= 90.0:
                s["dehydrated"] += 1
            s["near"] += int(bool(near[i]))
            prev = self.thirst_prev.get(uid)
            if prev is not None and t < prev - 1e-6:
                s["drank"] += 1
                s["last_drink_tick"] = self.tick
            s["edge"] += int(x <= x0 + 1.0 or y <= y0 + 1.0 or x >= x1 - 2.0 or y >= y1 - 2.0)
            self.thirst_prev[uid] = t
            self.last[uid] = {"tick": self.tick, "chunk": chunk_of(x, y, ox, oy), "x": round(x, 1), "y": round(y, 1), "thirst": round(t, 2),
                              "to_water": round(float(dist[i]), 1), "to_home": round(to_home, 1), "leash": leash, "near": bool(near[i]),
                              "hp": round(float(hp[i]), 1), "state": int(st), "hunger": round(float(hunger[i]), 2), "born": born,
                              "home": list(home) if home else None, "to_resident": None if res_d is None else round(float(res_d[i]), 1)}
            if wounded and "first_wound_tick" not in s:
                s["first_wound_tick"] = self.tick

    def resident_death(self, record: dict) -> None:
        killer = record.get("killer_uid")
        self.resident_deaths.append({"tick": record.get("tick"), "victim_uid": record.get("victim_uid"), "killer_uid": killer,
                                     "killer_species": record.get("killer_species"), "killer": self.last.get(killer)})

    def resident_summary(self) -> dict:
        records = self.resident_deaths
        by_killer = defaultdict(int)
        for r in records:
            by_killer[str(r["killer_uid"])] += 1
        return {"total": len(records), "distinct_victims": len({r["victim_uid"] for r in records}),
                "distinct_pairs": len({(r["victim_uid"], r["killer_uid"]) for r in records}), "by_killer": dict(by_killer), "records": records}


THIRST = Thirst()
COUNTERS = ("ticks", "thirsty", "seek", "unseen", "unseen_240", "leashed", "leashed_seen", "dehydrated", "near", "drank", "edge",
            "wounded", "seek_flee", "seek_return", "seek_chase", "seek_held", "seek_wounded", "flee", "flee_human", "flee_no_threat",
            "near_res", "near_res_chase", "near_res_attack", "near_res_water", "near_res_return", "near_res_thirsty", "near_res_hungry",
            "near_res_born", "near_res_beyond_leash")
_inner_describe = cb.Balance.describe_death


def _describe_death(self, i, tick, hp_before):
    out = _inner_describe(self, i, tick, hp_before)
    THIRST.resident_death(out)
    return out


cb.Balance.describe_death = _describe_death                   # creature_balance calls self.describe_death at each resident death
_inner_step = cb.kernel.step


def _step(engine):
    n = _inner_step(engine)
    if f3.TRACKER.active:
        began = time.perf_counter()
        THIRST.observe(engine)
        if THIRST.boot is None and THIRST.tick >= MINE.boot_tick:
            THIRST.boot_table(engine)
            if MINE.boot_only:
                Path(MINE.thirst_json).write_text(json.dumps({"args": REST, "boot_tick": THIRST.boot_at, "window": THIRST.window, "boot": THIRST.boot,
                                                              "chunks": THIRST.chunks}, indent=1), encoding="utf-8")
                print(json.dumps(THIRST.boot), flush=True)
                os._exit(0)                                   # boot only: the table is all that was asked for
        THIRST.seconds += time.perf_counter() - began
    return n


cb.kernel.step = _step


def summarise() -> dict:
    deaths = [d for d in f3.TRACKER.departures if d["kind"] == "death"]
    per_death = []
    for d in deaths:
        if d["cause"] != "thirst":
            continue
        s = THIRST.stats.get(d["uid"], {})
        per_death.append({"uid": d["uid"], "species": d["species"], "gone_tick": d["gone_tick"], "newborn": not f3.FAUNA.match(d["uid"]),
                          **{k: s.get(k, 0) for k in COUNTERS},
                          "last_drink_tick": s.get("last_drink_tick"), "first_wound_tick": s.get("first_wound_tick"), "last": THIRST.last.get(d["uid"])})
    totals = defaultdict(lambda: defaultdict(int))
    for uid, s in THIRST.stats.items():
        sp = f3.TRACKER.species_of.get(uid, "?")
        for k, v in s.items():
            if k not in ("last_drink_tick", "first_wound_tick"):
                totals[sp][k] += v
    return {"args": REST, "ticks_observed": THIRST.tick, "observe_seconds": round(THIRST.seconds, 1), "window": THIRST.window, "search_radius": {"no_prey": search_radius(False), "hunts": search_radius(True)},
            "boot_tick": THIRST.boot_at, "boot": THIRST.boot, "chunks": THIRST.chunks, "thirst_deaths": per_death, "species_ticks": {k: dict(v) for k, v in totals.items()},
            "resident_deaths": THIRST.resident_summary()}


if __name__ == "__main__":
    suite = cb.unittest.defaultTestLoader.loadTestsFromTestCase(cb.Balance)
    outcome = cb.unittest.TextTestRunner(verbosity=0).run(suite)
    if cb.ARGS.json:
        Path(cb.ARGS.json).write_text(json.dumps(cb.RESULT, indent=1), encoding="utf-8")
    Path(f3.EXTRA.deaths_json).write_text(json.dumps(f3.summarise(), indent=1), encoding="utf-8")
    Path(MINE.thirst_json).write_text(json.dumps(summarise(), indent=1), encoding="utf-8")
    print(json.dumps({"thirst_deaths": len(summarise()["thirst_deaths"])}), flush=True)
    sys.exit(0 if outcome.wasSuccessful() else 1)
