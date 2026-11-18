"""generate_chunk(world_seed, cx, cy): a pure function of the seed, the chunk address, the pinned set and the generator version.

Pipeline (all numpy, no per-tile Python loops): window of 34 x 34 tiles (chunk + one tile apron) -> classify.compute_window ->
terrain / footprint / walls / edge mask / props / aggregated resources / spawn table / points of interest -> document -> canonical
bytes + sha256. See 1008_worldgen.md for the format.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from . import assets, noise
from .classify import FOREST_T, Window, compute_window, new_cache
from .pinned import NO_PINS, PinnedSet, as_pinned
from .regions import RegionCache
from .spec import (ACTOR_RADIUS, APRON, B_DESERT, B_FOREST, B_HIGHLAND, B_MEADOW, B_PEAK, B_PLAINS, B_RIVER, B_WATER, B_WETLAND, CHUNK_SPEC,
                   CHUNK_TILES, CHUNK_UNITS, FIELD_MAX, GENERATOR_VERSION, MAX_ENTITIES_PER_CHUNK, MAX_PROPS_PER_CHUNK, MAX_SPAWN_ENTRIES,
                   POSITION_QUANTUM, QUADRANT_TILES, TILE_PX, UNITS_PER_TILE, WALL_HEIGHT)

SALT_PROP, SALT_SPAWN, SALT_ORE, SALT_FISH = 0x501, 0x502, 0x503, 0x504
Q = POSITION_QUANTUM

# prop kinds, in the order their probabilities are accumulated
K_TREE, K_BUSH, K_FLOWER, K_REED, K_FERN, K_BOULDER, K_MUSHROOM, K_LOG, K_COUNT = range(9)
_PROP_PROB = np.zeros((K_COUNT, 16), dtype=np.float64)


def _set(biome, **probs):
    names = {"tree": K_TREE, "bush": K_BUSH, "flower": K_FLOWER, "reed": K_REED, "fern": K_FERN, "boulder": K_BOULDER, "mushroom": K_MUSHROOM, "log": K_LOG}
    for name, p in probs.items():
        _PROP_PROB[names[name], biome] = p


_set(B_PLAINS, tree=0.012, bush=0.005, flower=0.02, fern=0.01)
_set(B_FOREST, tree=0.25, bush=0.004, fern=0.04, boulder=0.004, mushroom=0.012, log=0.005)   # tree overridden by forest density
_set(B_MEADOW, tree=0.005, bush=0.006, flower=0.08, fern=0.01)
_set(B_WETLAND, tree=0.01, reed=0.14, fern=0.05, flower=0.01)
_set(B_HIGHLAND, tree=0.02, boulder=0.07, fern=0.005)
_set(B_PEAK, boulder=0.03)
_set(B_DESERT, boulder=0.008)

# habitat weights for wildlife: species -> {biome: weight}
SPECIES = (
    ("boar", {B_FOREST: 3, B_WETLAND: 1}),
    ("deer", {B_FOREST: 3, B_PLAINS: 2, B_MEADOW: 2}),
    ("goat", {B_HIGHLAND: 3, B_PEAK: 1}),
    ("rabbit", {B_PLAINS: 2, B_MEADOW: 3, B_FOREST: 1}),
    ("sheep", {B_MEADOW: 3, B_PLAINS: 1}),
    ("wolf", {B_FOREST: 2, B_HIGHLAND: 1, B_PLAINS: 1}),
)
SPAWN_MIN_WEIGHT = 300
EDGE_OFFSETS = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))   # N NE E SE S SW W NW


@dataclass(frozen=True)
class GenParams:
    """Caps. Anything that changes output is part of the cache key and the document."""

    max_entities: int = MAX_ENTITIES_PER_CHUNK
    max_props: int = MAX_PROPS_PER_CHUNK

    @property
    def fingerprint(self) -> str:
        if self == DEFAULT_PARAMS:
            return ""
        return f"e{self.max_entities}p{self.max_props}"


DEFAULT_PARAMS = GenParams()


class Chunk:
    """One generated chunk: the canonical bytes (what the wire and the cache hold) plus a lazily parsed document.

    The cache keeps only `payload` bytes alive in practice (about 16 KB); `document` is parsed on first access, so a chunk that is
    only forwarded to a client never pays for the nested Python lists.
    """

    __slots__ = ("cx", "cy", "world_seed", "generator_version", "payload", "sha256", "_doc")

    def __init__(self, cx: int, cy: int, world_seed: int, generator_version: str, payload: bytes, sha256: str, document: Optional[dict] = None):
        self.cx = cx
        self.cy = cy
        self.world_seed = world_seed
        self.generator_version = generator_version
        self.payload = payload
        self.sha256 = sha256
        self._doc = document

    def __eq__(self, other) -> bool:
        return isinstance(other, Chunk) and self.sha256 == other.sha256 and (self.cx, self.cy) == (other.cx, other.cy)

    def __hash__(self) -> int:
        return hash((self.cx, self.cy, self.sha256))

    def __repr__(self) -> str:
        return f"Chunk({self.cx}, {self.cy}, {self.sha256[:12]}, {len(self.payload)} bytes)"

    @property
    def document(self) -> dict:
        if self._doc is None:
            self._doc = json.loads(self.payload.decode("ascii"))
        return self._doc

    @property
    def chunk_id(self) -> str:
        return f"{self.cx}:{self.cy}"

    def layer(self, name: str) -> np.ndarray:
        for layer in self.document["layers"]:
            if layer["name"] == name:
                return np.asarray(layer["tiles"], dtype=np.int16)
        raise KeyError(name)

    @property
    def terrain(self) -> np.ndarray:
        return self.layer("terrain")

    @property
    def entities(self) -> list:
        return self.document["entities"]

    @property
    def walls(self) -> list:
        return self.document["walls"]

    @property
    def pinned_map(self) -> Optional[str]:
        return self.document.get("pinned_map")

    @classmethod
    def from_payload(cls, payload: bytes, cx: Optional[int] = None, cy: Optional[int] = None) -> "Chunk":
        """Rebuild a chunk from wire bytes. With (cx, cy) given nothing is parsed; otherwise the header is read from the document."""
        sha = hashlib.sha256(payload).hexdigest()
        if cx is None or cy is None:
            doc = json.loads(payload.decode("ascii"))
            meta = doc["chunk"]
            return cls(int(meta["cx"]), int(meta["cy"]), int(meta["world_seed"]), meta["generator_version"], payload, sha, doc)
        return cls(cx, cy, 0, GENERATOR_VERSION, payload, sha)


def encode(document: dict) -> bytes:
    return json.dumps(document, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("ascii")


def chunk_key(world_seed: int, cx: int, cy: int, pinned=None, params: GenParams = DEFAULT_PARAMS) -> tuple:
    return (int(world_seed), GENERATOR_VERSION, as_pinned(pinned).fingerprint, params.fingerprint, int(cx), int(cy))


def world_tile(cx: int, cy: int, i: int, j: int) -> tuple[int, int]:
    return cx * CHUNK_TILES + i, cy * CHUNK_TILES + j


# ---------------------------------------------------------------------------------------------------------------- pieces

def edge_mask(terrain: np.ndarray) -> np.ndarray:
    """terrain is the (34, 34) apron window; returns uint8 (32, 32): bit k set when neighbour k has a different, non-empty terrain id."""
    n = CHUNK_TILES
    centre = terrain[1:1 + n, 1:1 + n]
    mask = np.zeros((n, n), dtype=np.uint8)
    for bit, (dx, dy) in enumerate(EDGE_OFFSETS):
        nb = terrain[1 + dy:1 + dy + n, 1 + dx:1 + dx + n]
        differs = (nb != centre) & (nb != 0) & (centre != 0)
        mask |= (differs.astype(np.uint8) << bit)
    return mask


def boxes_from_mask(blocked: np.ndarray) -> list:
    """Decompose a boolean (rows, cols) mask into disjoint tile-aligned rectangles: row runs merged vertically when identical."""
    rows, cols = blocked.shape
    open_boxes: dict = {}          # (x0, x1) -> [y0, y1]
    done = []
    for y in range(rows):
        row = blocked[y]
        runs = []
        if row.any():
            padded = np.concatenate(([False], row, [False]))
            diff = np.diff(padded.astype(np.int8))
            starts = np.nonzero(diff == 1)[0]
            ends = np.nonzero(diff == -1)[0]          # exclusive
            runs = [(int(a), int(b)) for a, b in zip(starts, ends)]
        current = {}
        for run in runs:
            if run in open_boxes and open_boxes[run][1] == y - 1:
                current[run] = [open_boxes[run][0], y]
            else:
                current[run] = [y, y]
        for run, span in open_boxes.items():
            if run not in current:
                done.append((run[0], span[0], run[1], span[1] + 1))
        open_boxes = current
    for run, span in open_boxes.items():
        done.append((run[0], span[0], run[1], span[1] + 1))
    done.sort(key=lambda b: (b[1], b[0], b[2], b[3]))
    return done


def _q(v: float) -> float:
    return float(int(np.rint(v * Q))) / Q


def _jitter(h: np.ndarray):
    return ((h >> np.uint64(9)) & np.uint64(127)).astype(np.int32), ((h >> np.uint64(2)) & np.uint64(127)).astype(np.int32)


def make_props(seed: int, win: Window, inner, clear_radius: int, max_props: int):
    """Visual-only scatter. Returns (kind index array (32, 32), sprite index array, x16, y16 arrays) restricted to occupied tiles."""
    sl = inner
    gx, gy = win.gx[sl], win.gy[sl]
    biome = win.biome[sl]
    h = noise.tile_hash(seed, SALT_PROP, gx, gy)
    u0 = ((h >> np.uint64(48)) & np.uint64(0xFFFF)).astype(np.int64)
    u1 = ((h >> np.uint64(32)) & np.uint64(0xFFFF)).astype(np.int64)
    prob = _PROP_PROB[:, biome]                               # (8, 32, 32)
    fq = win.forest[sl]
    dens = 0.10 + 0.40 * np.clip((fq - FOREST_T) / float(FIELD_MAX - FOREST_T), 0.0, 1.0)
    prob = prob.copy()
    prob[K_TREE] = np.where(biome == B_FOREST, dens, prob[K_TREE])
    cum = np.cumsum(np.floor(prob * 65536.0).astype(np.int64), axis=0)
    kind = (u0[None] >= cum).sum(axis=0)                      # K_COUNT means none
    free = (win.footprint[sl] == 0) & ~win.poi_mask[sl] & (win.pin_d[sl] > clear_radius)
    kind = np.where(free, kind, K_COUNT)
    occupied = kind < K_COUNT
    ys, xs = np.nonzero(occupied)
    k = kind[ys, xs]
    var = u1[ys, xs]
    temp = win.temp[sl][ys, xs]
    elev = win.elev[sl][ys, xs]
    moist = win.moist[sl][ys, xs]
    sprite = np.full(k.shape, assets.P_OAK, dtype=np.int16)
    tree = k == K_TREE
    pine = tree & ((temp < 1800) | (elev > 3000) | ((biome[ys, xs] == B_FOREST) & (var % 10 >= 7)))
    apple = tree & ~pine & (var % 16 == 0) & (moist > 2800) & (temp > 2200)
    sprite[pine] = assets.P_PINE
    sprite[apple] = assets.P_APPLE
    sprite[k == K_BUSH] = assets.P_BERRY
    sprite[k == K_FLOWER] = assets.P_FLOWERS
    sprite[k == K_REED] = assets.P_REEDS
    sprite[k == K_FERN] = np.where(var[k == K_FERN] % 2 == 0, assets.P_FERN, assets.P_GREEN_FERN)
    sprite[k == K_BOULDER] = assets.P_BOULDERS
    sprite[k == K_MUSHROOM] = assets.P_MUSHROOMS
    sprite[k == K_LOG] = assets.P_LOG
    jx, jy = _jitter(h[ys, xs])
    x16 = xs.astype(np.int32) * (UNITS_PER_TILE * Q) + jx
    y16 = ys.astype(np.int32) * (UNITS_PER_TILE * Q) + jy
    if len(k) > max_props:
        keep = np.arange(len(k)) < max_props
        k, sprite, x16, y16, ys, xs = k[keep], sprite[keep], x16[keep], y16[keep], ys[keep], xs[keep]
    return k, sprite, x16, y16, ys, xs


def _centroid16(vals: np.ndarray) -> int:
    n = len(vals)
    return int((2 * int(vals.sum()) + n) // (2 * n))


def make_resources(seed: int, cx: int, cy: int, win: Window, inner, k, x16, y16, ys, xs):
    """Aggregate props and terrain into at most a few entities per 16 x 16 quadrant. Returns a list of dicts with integer fields."""
    feats = []
    qs = QUADRANT_TILES
    biome = win.biome[inner]
    gx, gy = win.gx[inner], win.gy[inner]
    spec = (("forest", "wood", K_TREE, 4), ("stone_outcrop", "stone", K_BOULDER, 2), ("berry_patch", "berries", K_BUSH, 2),
            ("mushroom_patch", "mushrooms", K_MUSHROOM, 2), ("reed_bed", "reeds", K_REED, 4))
    qy_of, qx_of = ys // qs, xs // qs
    for qy in range(2):
        for qx in range(2):
            inq = (qy_of == qy) & (qx_of == qx)
            for kind, resource, pk, need in spec:
                sel = inq & (k == pk)
                n = int(sel.sum())
                if n >= need:
                    feats.append({"kind": kind, "resource": resource, "amount": n, "tiles": n, "x16": _centroid16(x16[sel]), "y16": _centroid16(y16[sel])})
            tile_sl = (slice(qy * qs, qy * qs + qs), slice(qx * qs, qx * qs + qs))
            b = biome[tile_sl]
            # fish: water tiles with a land neighbour (use the apron so border tiles are decided without the neighbouring chunk)
            wsl = (slice(qy * qs, qy * qs + qs + 2), slice(qx * qs, qx * qs + qs + 2))
            is_w = np.isin(win.biome[wsl], (B_WATER, B_RIVER))
            core = is_w[1:-1, 1:-1]
            land_nb = ~(is_w[:-2, 1:-1] & is_w[2:, 1:-1] & is_w[1:-1, :-2] & is_w[1:-1, 2:])
            shore_w = core & land_nb
            nfish = int(shore_w.sum())
            if nfish >= 6:
                fy, fx = np.nonzero(shore_w)
                hh = noise.tile_hash(seed, SALT_FISH, gx[tile_sl][fy, fx], gy[tile_sl][fy, fx])
                pick = int(np.argmin(hh))
                feats.append({"kind": "fish_spot", "resource": "fish", "amount": nfish, "tiles": nfish,
                              "x16": (qx * qs + int(fx[pick])) * UNITS_PER_TILE * Q + UNITS_PER_TILE * Q // 2,
                              "y16": (qy * qs + int(fy[pick])) * UNITS_PER_TILE * Q + UNITS_PER_TILE * Q // 2})
            rock = np.isin(b, (B_HIGHLAND, B_PEAK))
            nrock = int(rock.sum())
            if nrock >= 24 and noise.derive(seed, SALT_ORE, cx * 2 + qx, cy * 2 + qy) % 100 < 30:
                ry_, rx_ = np.nonzero(rock)
                hh = noise.tile_hash(seed, SALT_ORE, gx[tile_sl][ry_, rx_], gy[tile_sl][ry_, rx_])
                pick = int(np.argmin(hh))
                feats.append({"kind": "ore_vein", "resource": "ore", "amount": 20 + nrock // 4, "tiles": nrock,
                              "x16": (qx * qs + int(rx_[pick])) * UNITS_PER_TILE * Q + UNITS_PER_TILE * Q // 2,
                              "y16": (qy * qs + int(ry_[pick])) * UNITS_PER_TILE * Q + UNITS_PER_TILE * Q // 2})
    return feats


def merge_to_cap(feats: list, cap: int) -> list:
    """Merge the closest same-kind pair until at most `cap` remain (weighted centroid, summed amount). Deterministic."""
    feats = sorted(feats, key=lambda f: (f["kind"], f["y16"], f["x16"]))
    while len(feats) > max(cap, 0):
        best = None
        for a in range(len(feats)):
            for b in range(a + 1, len(feats)):
                if feats[a]["kind"] != feats[b]["kind"]:
                    continue
                d = (feats[a]["x16"] - feats[b]["x16"]) ** 2 + (feats[a]["y16"] - feats[b]["y16"]) ** 2
                if best is None or d < best[0]:
                    best = (d, a, b)
        if best is None:                              # nothing mergeable: drop the smallest (lowest amount, then last in order)
            drop = min(range(len(feats)), key=lambda i: (feats[i]["amount"], -i))
            feats.pop(drop)
            continue
        _, a, b = best
        fa, fb = feats[a], feats[b]
        total = fa["amount"] + fb["amount"]
        merged = dict(fa)
        merged["amount"] = total
        merged["tiles"] = fa["tiles"] + fb["tiles"]
        merged["x16"] = int((fa["x16"] * fa["amount"] + fb["x16"] * fb["amount"] + total // 2) // total)
        merged["y16"] = int((fa["y16"] * fa["amount"] + fb["y16"] * fb["amount"] + total // 2) // total)
        feats[a] = merged
        feats.pop(b)
        feats.sort(key=lambda f: (f["kind"], f["y16"], f["x16"]))
    return feats


def make_spawns(seed: int, cx: int, cy: int, win: Window, inner) -> list:
    biome = win.biome[inner]
    gx, gy = win.gx[inner], win.gy[inner]
    free = (win.footprint[inner] == 0) & ~win.poi_mask[inner] & (win.pin_d[inner] > 0)
    counts = np.bincount(biome[free].ravel(), minlength=16)
    entries = []
    for idx, (name, hab) in enumerate(SPECIES):
        weight = sum(int(counts[b]) * w for b, w in hab.items())
        if weight < SPAWN_MIN_WEIGHT:
            continue
        entries.append((-weight, name, idx, hab, weight))
    entries.sort()
    out = []
    for _, name, idx, hab, weight in entries[:MAX_SPAWN_ENTRIES]:
        mx = min(1 + weight // 1200, 4)
        ok = np.isin(biome, tuple(hab)) & free
        ys, xs = np.nonzero(ok)
        hh = noise.tile_hash(seed, SALT_SPAWN + idx, gx[ys, xs], gy[ys, xs])
        order = np.lexsort((np.arange(len(hh)), hh))[:mx]
        jx, jy = _jitter(hh[order])
        slots = [[float(int(xs[o]) * UNITS_PER_TILE + int(jx[n]) / Q), float(int(ys[o]) * UNITS_PER_TILE + int(jy[n]) / Q)] for n, o in enumerate(order)]
        out.append({"species": name, "weight": int(weight), "max": int(mx), "sprite": assets.SPECIES_SPRITES.get(name), "slots": slots})
    return out


# ----------------------------------------------------------------------------------------------------------------- chunk

def _empty_layers() -> list:
    z = [[0] * CHUNK_TILES for _ in range(CHUNK_TILES)]
    return [{"name": "terrain", "kind": "terrain", "palette": dict(assets.TERRAIN_PALETTE), "tiles": z},
            {"name": "decoration", "kind": "decoration", "palette": {}, "tiles": z},
            {"name": "footprint", "kind": "footprint", "palette": dict(assets.FOOTPRINT_PALETTE), "tiles": z}]


def _base_document(world_seed: int, cx: int, cy: int, pinned: PinnedSet, params: GenParams) -> dict:
    return {
        "format_version": "0.2-draft", "map_id": f"chunk_{cx}_{cy}", "revision": 0, "tile_size_px": TILE_PX, "units_per_tile": UNITS_PER_TILE,
        "size_tiles": [CHUNK_TILES, CHUNK_TILES], "actor_radius": ACTOR_RADIUS, "coordinate_system": "top_left_x_right_y_down", "map_kind": "exterior",
        "layers": _empty_layers(), "walls": [], "anchors": [], "portals": [], "entities": [],
        "chunk": {"spec": CHUNK_SPEC, "generator_version": GENERATOR_VERSION, "world_seed": str(int(world_seed)), "cx": int(cx), "cy": int(cy),
                  "pinned": pinned.fingerprint, "pinned_tiles": 0, "params": params.fingerprint},
        "data": {"biome": [[0] * CHUNK_TILES for _ in range(CHUNK_TILES)], "edges": [[0] * CHUNK_TILES for _ in range(CHUNK_TILES)],
                 "prop_palette": list(assets.PROP_SPRITES), "props": [], "spawns": [], "pois": [],
                 "caps": {"max_entities": params.max_entities, "max_props": params.max_props}},
    }


def _finish(doc: dict, world_seed: int, cx: int, cy: int) -> Chunk:
    payload = encode(doc)
    return Chunk(cx, cy, int(world_seed), GENERATOR_VERSION, payload, hashlib.sha256(payload).hexdigest(), doc)


def generate_chunk(world_seed: int, cx: int, cy: int, pinned=None, params: GenParams = DEFAULT_PARAMS, cache: Optional[RegionCache] = None) -> Chunk:
    pinned = as_pinned(pinned)
    cx, cy, world_seed = int(cx), int(cy), int(world_seed)
    doc = _base_document(world_seed, cx, cy, pinned, params)
    area = pinned.fully_pinned_by(cx, cy)
    if area is not None:
        doc["pinned_map"] = area.id
        doc["chunk"]["pinned_tiles"] = CHUNK_TILES * CHUNK_TILES
        return _finish(doc, world_seed, cx, cy)

    n = CHUNK_TILES
    win = compute_window(world_seed, cx * n - APRON, cy * n - APRON, n + 2 * APRON, n + 2 * APRON, pinned, cache)
    inner = (slice(APRON, APRON + n), slice(APRON, APRON + n))
    terrain = win.terrain[inner]
    footprint = win.footprint[inner]
    doc["layers"][0]["tiles"] = terrain.tolist()
    doc["layers"][2]["tiles"] = footprint.tolist()
    doc["data"]["biome"] = win.biome[inner].astype(np.int32).tolist()
    doc["data"]["edges"] = edge_mask(win.terrain).astype(np.int32).tolist()
    doc["chunk"]["pinned_tiles"] = int((win.pin_d[inner] == 0).sum())

    boxes = boxes_from_mask(footprint > 0)
    ts = UNITS_PER_TILE
    doc["walls"] = [{"id": f"c{cx}_{cy}:w{i}", "min": [x0 * ts, y0 * ts], "max": [x1 * ts, y1 * ts], "height": WALL_HEIGHT}
                    for i, (x0, y0, x1, y1) in enumerate(boxes)]

    clear_r = max(1, pinned.blend // 2) if pinned else 0
    k, sprite, x16, y16, ys, xs = make_props(world_seed, win, inner, clear_r, params.max_props)
    doc["data"]["props"] = [[int(s), float(a) / Q, float(b) / Q] for s, a, b in zip(sprite.tolist(), x16.tolist(), y16.tolist())]

    pois = []
    for poi in win.pois:
        ax, ay = poi.anchor
        if cx * n <= ax < cx * n + n and cy * n <= ay < cy * n + n:
            pois.append(poi)
    poi_feats = []
    for i, poi in enumerate(sorted(pois, key=lambda p: p.id)):
        ax, ay = poi.anchor
        lx, ly = (ax - cx * n) * ts + ts // 2, (ay - cy * n) * ts + ts // 2
        poi_feats.append({"kind": f"poi_{poi.kind}", "poi": poi, "x": float(lx), "y": float(ly)})
        doc["data"]["pois"].append({"id": poi.id, "kind": poi.kind, "tile_rect": [poi.x0, poi.y0, poi.w, poi.h], "position": [float(lx), float(ly)]})

    resources = merge_to_cap(make_resources(world_seed, cx, cy, win, inner, k, x16, y16, ys, xs), params.max_entities - len(poi_feats))
    counters: dict = {}
    entities = []
    for f in resources:
        idx = counters.get(f["kind"], 0)
        counters[f["kind"]] = idx + 1
        radius = int(np.clip(round(ts * (f["tiles"] ** 0.5)), 8, 96)) if f["kind"] != "fish_spot" else 12
        e = {"id": f"c{cx}_{cy}:{f['kind']}{idx}", "kind": f["kind"], "interactive": True, "position": [float(f["x16"]) / Q, float(f["y16"]) / Q],
             "resource": f["resource"], "amount": int(f["amount"]), "tiles": int(f["tiles"]), "radius": float(radius)}
        sp = assets.ENTITY_SPRITES.get(f["kind"])
        if sp:
            e["sprite"] = sp
        entities.append(e)
    for pf in poi_feats:
        idx = counters.get(pf["kind"], 0)
        counters[pf["kind"]] = idx + 1
        e = {"id": f"c{cx}_{cy}:{pf['kind']}{idx}", "kind": pf["kind"], "interactive": False, "position": [pf["x"], pf["y"]], "poi": pf["poi"].id}
        sp = assets.ENTITY_SPRITES.get(pf["kind"])
        if sp:
            e["sprite"] = sp
        entities.append(e)
    doc["entities"] = entities
    doc["data"]["spawns"] = make_spawns(world_seed, cx, cy, win, inner)
    return _finish(doc, world_seed, cx, cy)


def generate_payload(args: tuple) -> tuple:
    """Pool entry point: (seed, cx, cy, pinned, params) -> (cx, cy, payload bytes, sha256, generation ms). Pickle-friendly."""
    seed, cx, cy, pinned, params = args
    start = time.perf_counter()
    chunk = generate_chunk(seed, cx, cy, pinned, params, _worker_cache())
    return cx, cy, chunk.payload, chunk.sha256, (time.perf_counter() - start) * 1000.0


_WORKER_CACHE: Optional[RegionCache] = None


def _worker_cache() -> RegionCache:
    global _WORKER_CACHE
    if _WORKER_CACHE is None:
        _WORKER_CACHE = new_cache()
    return _WORKER_CACHE
