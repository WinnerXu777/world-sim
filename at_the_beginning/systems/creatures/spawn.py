"""The creature spawn plan (``1008_creatures_gap.md`` section 6): a PURE function from a generated chunk document and the table to the creatures that chunk starts with.

No engine, no torch, no random state: every choice is a hash of ``(world seed, cx, cy, species, index, purpose)`` (blake2b), so the plan is the same in any process, in
any call order, and for any window. The generator is not touched: the plan reads what chunks already carry (``data.spawns`` for the species the generator knows, ``data.pois``
for the rest) and the terrain/footprint layers to keep jittered positions on legal land.

A plan record is chunk-local: ``x, y`` in 0..256 units from the chunk corner, so the window glue adds the chunk's origin and a re-base needs nothing.
Record keys: ``uid, species, id, x, y, group, variant, sex, age, life_exp, hp``. ``age`` is in the same unit as ``A_AGE``/``A_LIFE_EXP`` (years).
"""
from __future__ import annotations

import hashlib
import math
import struct
from typing import Optional

from . import table as _table

CHUNK_UNITS = 256.0
TILE_UNITS = 8.0
CHUNK_TILES = 32
TERRAIN_WATER = 3          # systems/worldgen/spec.py TERRAIN_WATER; asserted equal in the tests
MAX_PER_CHUNK = 12         # creatures one chunk may start with, whatever the entries say
JITTER_TRIES = 5
EDGE_MARGIN = 6.0
GROUP_MOD = 1 << 20        # group ids stay exact in float32


def _digest(seed: int, cx: int, cy: int, *tags) -> int:
    raw = struct.pack("<qqq", int(seed), int(cx), int(cy)) + "|".join(str(t) for t in tags).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "little")


def _unit(h: int) -> float:
    return (h >> 11) / float(1 << 53)


def _free(document: dict, x: float, y: float) -> bool:
    """True if the tile under chunk-local ``(x, y)`` is land with no footprint (rock, ruin wall, water body)."""
    tx, ty = int(x // TILE_UNITS), int(y // TILE_UNITS)
    if not (0 <= tx < CHUNK_TILES and 0 <= ty < CHUNK_TILES):
        return False
    layers = {layer["name"]: layer["tiles"] for layer in document["layers"]}
    terrain = layers["terrain"][ty][tx]
    return terrain != TERRAIN_WATER and layers["footprint"][ty][tx] == 0


def _place(document: dict, seed: int, cx: int, cy: int, species: str, n: int, anchor: tuple, radius: float) -> tuple:
    """A free position within ``radius`` of ``anchor`` (hash-jittered, up to JITTER_TRIES tries); the anchor itself if none is free."""
    for attempt in range(JITTER_TRIES):
        h = _digest(seed, cx, cy, species, n, "jitter", attempt)
        angle = _unit(h) * math.tau
        dist = _unit(_digest(seed, cx, cy, species, n, "dist", attempt)) * radius
        x = min(CHUNK_UNITS - EDGE_MARGIN, max(EDGE_MARGIN, anchor[0] + dist * math.cos(angle)))
        y = min(CHUNK_UNITS - EDGE_MARGIN, max(EDGE_MARGIN, anchor[1] + dist * math.sin(angle)))
        if _free(document, x, y):
            return x, y
    return (min(CHUNK_UNITS - EDGE_MARGIN, max(EDGE_MARGIN, anchor[0])), min(CHUNK_UNITS - EDGE_MARGIN, max(EDGE_MARGIN, anchor[1])))


def _record(document: dict, seed: int, cx: int, cy: int, name: str, row: dict, n: int, anchor: tuple, group: int, spread: float) -> dict:
    x, y = _place(document, seed, cx, cy, name, n, anchor, spread)
    lo, hi = row["life_exp"]
    life = lo + _unit(_digest(seed, cx, cy, name, n, "life")) * (hi - lo)
    variants = row["variants"]
    variant = 0
    if variants and _digest(seed, cx, cy, name, n, "variant?") % 8 == 0:
        variant = 1 + _digest(seed, cx, cy, name, n, "variant") % len(variants)
    return {"uid": f"c{cx}_{cy}:fauna:{name}{n}", "species": name, "id": row["id"], "x": round(x, 3), "y": round(y, 3), "group": group, "variant": variant,
            "sex": float(_digest(seed, cx, cy, name, n, "sex") & 1), "age": round(_unit(_digest(seed, cx, cy, name, n, "age")) * 0.6 * lo, 4),
            "life_exp": round(life, 4), "hp": float(row["hp"])}


def _group_size(seed: int, cx: int, cy: int, name: str, row: dict, salt: str) -> int:
    lo, hi = row["group"]["size"]
    return lo + _digest(seed, cx, cy, name, salt, "size") % (hi - lo + 1)


def _group_id(cx: int, cy: int, name: str, salt: str) -> int:
    return 1 + _digest(0, cx, cy, name, salt, "group") % (GROUP_MOD - 1)


def plan(document: dict, table: Optional[dict] = None, *, world_seed: Optional[int] = None) -> list:
    """The creatures chunk ``document`` starts with, as an ordered list of plain dicts (species id, then index). Disabled species never appear.

    Rules, per enabled species with a habitat:
      * ``spawn_entry``: the generator's own ``data.spawns`` entry of that name (if the chunk has one) is a candidate; it is taken with probability ``spawn_p`` (one hash per
        chunk and species); a taken entry makes one group of ``group.size`` creatures around the entry's slots in turn;
      * ``companion``: the same, around the first slot of the companion's entry, only if the chunk has that entry;
      * ``poi``: for every POI of the listed kinds, a group (taken with ``spawn_p``) around the POI's position.
    """
    table = _table.CREATURES if table is None else table
    meta = document["chunk"]
    cx, cy = int(meta["cx"]), int(meta["cy"])
    seed = int(world_seed if world_seed is not None else meta["world_seed"])
    entries = {s["species"]: s for s in document["data"].get("spawns", [])}
    pois = document["data"].get("pois", [])
    out: list = []
    for name, row in sorted(table.items(), key=lambda kv: kv[1]["id"]):
        habitat = row["habitat"]
        if not row["enabled"] or not habitat:
            continue
        index = 0
        if "spawn_entry" in habitat or "companion" in habitat:
            source = entries.get(habitat.get("spawn_entry") or habitat.get("companion"))
            if source is None or not source["slots"]:
                continue
            if _unit(_digest(seed, cx, cy, name, "entry")) >= row["spawn_p"]:
                continue
            size = _group_size(seed, cx, cy, name, row, "entry")
            group = _group_id(cx, cy, name, "entry")
            slots = source["slots"]
            for k in range(size):
                anchor = slots[k % len(slots)] if "spawn_entry" in habitat else slots[0]
                out.append(_record(document, seed, cx, cy, name, row, index, (float(anchor[0]), float(anchor[1])), group, 28.0))
                index += 1
        else:
            for poi in pois:
                if poi["kind"] not in habitat["poi"] or _unit(_digest(seed, cx, cy, name, poi["id"], "poi")) >= row["spawn_p"]:
                    continue
                size = _group_size(seed, cx, cy, name, row, poi["id"])
                group = _group_id(cx, cy, name, poi["id"])
                for _ in range(size):
                    out.append(_record(document, seed, cx, cy, name, row, index, (float(poi["position"][0]), float(poi["position"][1])), group, 36.0))
                    index += 1
    return out[:MAX_PER_CHUNK]
