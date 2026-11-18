"""Per-tile classification over a window of world tiles: fields -> biome -> terrain / blocked, including region features,
points of interest and the blend into pinned areas. Everything here is a function of (seed, tile, pinned set), never of a chunk.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import fields, noise
from .pinned import NO_PINS, PinnedSet
from .regions import PoiCandidate, RegionCache, regions_near
from .spec import (B_DESERT, B_FOREST, B_FORD, B_HIGHLAND, B_MEADOW, B_PEAK, B_PLAINS, B_RIVER, B_RUIN, B_SHORE, B_VOID, B_WATER, B_WETLAND,
                   FIELD_MAX, FOOT_RUIN, FOOT_ROCK, FOOT_WATER, TERRAIN_GRASS, TERRAIN_PAVING, TERRAIN_ROCK, TERRAIN_SAND, TERRAIN_WATER)

# Calibrated on 1M tiles at seed 1008 (tools in 1008_worldgen.md section 2); all integers on the 12-bit field scale.
SEA = 800
SHORE_BAND = 140
ROCK = 3600
PEAK = 4060
RIVER_MAX_ELEV = 3300
RIVER_BASE = 14            # half width in 1/16 tile at the narrowest
RIVER_WIDTH_DIV = 256      # + river_width // 256 -> half width 0.9 to 1.9 tiles
FORD_T = 3400
WET_MOISTURE = 3400
WET_ELEV = SEA + 500
DESERT_TEMP = 3200
DESERT_MOISTURE = 1000
FOREST_T = 2800
MEADOW_MOISTURE = 2600
LAKE_DEPTH = 1400
LAND_MID = 2400
CLIMATE_RADIUS = 64        # tiles around a pinned area over which temperature and moisture are pulled to temperate values
CLIMATE_TEMP = 2200
CLIMATE_MOIST = 2000

BIOME_TO_TERRAIN = np.zeros(16, dtype=np.int16)
for _b, _t in ((B_WATER, TERRAIN_WATER), (B_SHORE, TERRAIN_SAND), (B_PLAINS, TERRAIN_GRASS), (B_FOREST, TERRAIN_GRASS), (B_MEADOW, TERRAIN_GRASS),
               (B_HIGHLAND, TERRAIN_ROCK), (B_DESERT, TERRAIN_SAND), (B_WETLAND, TERRAIN_GRASS), (B_RIVER, TERRAIN_WATER), (B_FORD, TERRAIN_SAND),
               (B_RUIN, TERRAIN_PAVING), (B_PEAK, TERRAIN_ROCK)):
    BIOME_TO_TERRAIN[_b] = _t

BIOME_TO_FOOTPRINT = np.zeros(16, dtype=np.int16)
BIOME_TO_FOOTPRINT[B_WATER] = FOOT_WATER
BIOME_TO_FOOTPRINT[B_RIVER] = FOOT_WATER
BIOME_TO_FOOTPRINT[B_PEAK] = FOOT_ROCK

_LAND_OK = (B_PLAINS, B_FOREST, B_MEADOW, B_DESERT, B_WETLAND)
SALT_POI_TILE = 0x901


@dataclass
class Window:
    gx0: int
    gy0: int
    width: int
    height: int
    gx: np.ndarray
    gy: np.ndarray
    pin_d: np.ndarray
    elev: np.ndarray
    moist: np.ndarray
    temp: np.ndarray
    forest: np.ndarray
    biome: np.ndarray           # uint8
    terrain: np.ndarray         # int16 palette id, 0 = pinned / empty
    footprint: np.ndarray       # int16: 1 water, 2 rock, 3 ruin wall, 0 free
    poi_mask: np.ndarray        # bool: tile belongs to an accepted POI rectangle
    pois: list = field(default_factory=list)   # accepted PoiCandidate overlapping the window


def _circle_d2(gx, gy, cx, cy, rx, ry):
    dx = (gx - cx) / float(rx)
    dy = (gy - cy) / float(ry)
    return dx * dx + dy * dy


def _overlaps(gx0, gy0, w, h, cx, cy, rx, ry, pad=0):
    return not (cx + rx + pad < gx0 or cx - rx - pad >= gx0 + w or cy + ry + pad < gy0 or cy - ry - pad >= gy0 + h)


def compute_window(seed: int, gx0: int, gy0: int, width: int, height: int, pinned: PinnedSet = NO_PINS, cache: RegionCache | None = None,
                   with_pois: bool = True) -> Window:
    cache = cache or _DEFAULT_CACHE
    gx, gy = fields.window_grid(gx0, gy0, width, height)
    elev = fields.elevation(seed, gx, gy).astype(np.int32)
    moist = fields.moisture(seed, gx, gy)
    temp = fields.temperature(seed, gx, gy)
    fnoise = fields.forest_noise(seed, gx, gy)
    rd = fields.river_distance(seed, gx, gy)
    rw = fields.river_width(seed, gx, gy)
    ford = fields.ford_noise(seed, gx, gy)

    forest = (fnoise.astype(np.int32) * 2 + moist.astype(np.int32)) // 3
    edge = None
    for rx_, ry_ in regions_near(gx0, gy0, width, height):
        raw = cache.raw(seed, rx_, ry_)
        for lake in raw.lakes:
            if not _overlaps(gx0, gy0, width, height, lake.cx, lake.cy, lake.rx, lake.ry, pad=10):
                continue
            if edge is None:
                edge = fields.lake_edge_noise(seed, gx, gy)
            d2 = _circle_d2(gx, gy, lake.cx, lake.cy, lake.rx, lake.ry) + (edge - 0.5) * 0.6
            depth = np.floor((1.0 - d2) * LAKE_DEPTH).astype(np.int32)
            elev -= np.maximum(depth, 0)
        for patch in raw.forests:
            if not _overlaps(gx0, gy0, width, height, patch.cx, patch.cy, patch.r, patch.r):
                continue
            d2 = _circle_d2(gx, gy, patch.cx, patch.cy, patch.r, patch.r)
            gain = np.floor((1.0 - d2) * patch.strength).astype(np.int32)
            forest += np.maximum(gain, 0)
    elev = np.clip(elev, 0, FIELD_MAX)
    forest = np.clip(forest, 0, FIELD_MAX)

    if pinned:
        pin_d = pinned.distance(gx, gy)
        cband = (pin_d >= 1) & (pin_d <= CLIMATE_RADIUS)
        if cband.any():
            d = pin_d.astype(np.int32)
            temp = np.where(cband, (temp * d + CLIMATE_TEMP * (CLIMATE_RADIUS + 1 - d)) // (CLIMATE_RADIUS + 1), temp)
            moist = np.where(cband, (moist * d + CLIMATE_MOIST * (CLIMATE_RADIUS + 1 - d)) // (CLIMATE_RADIUS + 1), moist)
            forest = np.where(cband, (forest * d + 1500 * (CLIMATE_RADIUS + 1 - d)) // (CLIMATE_RADIUS + 1), forest)
        band = (pin_d >= 1) & (pin_d <= pinned.blend)
        if band.any():
            d = pin_d.astype(np.int32)
            mixed = (elev * d + LAND_MID * (pinned.blend + 1 - d)) // (pinned.blend + 1)
            elev = np.where(band, mixed, elev)
        clear = (pin_d >= 1) & (pin_d <= max(1, pinned.blend // 2))
    else:
        pin_d = np.full(gx.shape, 1 << 20, dtype=np.int32)
        clear = np.zeros(gx.shape, dtype=bool)

    biome = np.full(gx.shape, B_PLAINS, dtype=np.uint8)
    biome[moist >= MEADOW_MOISTURE] = B_MEADOW
    biome[forest >= FOREST_T] = B_FOREST
    biome[(moist >= WET_MOISTURE) & (elev < WET_ELEV)] = B_WETLAND
    biome[(temp >= DESERT_TEMP) & (moist < DESERT_MOISTURE)] = B_DESERT
    biome[elev > ROCK] = B_HIGHLAND
    biome[elev > PEAK] = B_PEAK
    biome[elev < SEA + SHORE_BAND] = B_SHORE
    river = (rd < RIVER_BASE + rw // RIVER_WIDTH_DIV) & (elev < RIVER_MAX_ELEV) & ~clear
    biome[river] = np.where(ford[river] > FORD_T, B_FORD, B_RIVER)
    biome[elev < SEA] = B_WATER
    if clear.any():
        biome[clear] = B_PLAINS
    biome[pin_d == 0] = B_VOID

    terrain = BIOME_TO_TERRAIN[biome].copy()
    footprint = BIOME_TO_FOOTPRINT[biome].copy()
    poi_mask = np.zeros(gx.shape, dtype=bool)
    win = Window(gx0, gy0, width, height, gx, gy, pin_d, elev.astype(np.int32), moist, temp, forest.astype(np.int32), biome, terrain, footprint, poi_mask)
    if with_pois:
        for poi in accepted_pois_near(seed, gx0, gy0, width, height, pinned, cache):
            apply_poi(seed, win, poi)
            win.pois.append(poi)
    return win


def accepted_pois_near(seed: int, gx0: int, gy0: int, width: int, height: int, pinned: PinnedSet, cache: RegionCache):
    out = []
    for rx_, ry_ in regions_near(gx0, gy0, width, height):
        for poi in accepted_pois(seed, rx_, ry_, pinned, cache):
            if poi.x0 < gx0 + width and poi.x0 + poi.w > gx0 and poi.y0 < gy0 + height and poi.y0 + poi.h > gy0:
                out.append(poi)
    return out


def accepted_pois(seed: int, rx: int, ry: int, pinned: PinnedSet, cache: RegionCache) -> tuple:
    key = ("poi", seed, pinned.fingerprint, rx, ry)
    hit = cache.extra.get(key)
    if hit is not None:
        return hit
    accepted = []
    for poi in cache.raw(seed, rx, ry).pois:
        if pinned and pinned.min_distance_rect(poi.x0 - 2, poi.y0 - 2, poi.w + 4, poi.h + 4) <= pinned.blend:
            continue
        probe = compute_window(seed, poi.x0 - 2, poi.y0 - 2, poi.w + 4, poi.h + 4, pinned, cache, with_pois=False)
        inner = probe.biome[2:-2, 2:-2]
        if poi.kind == "cave":
            rocky = np.isin(inner, (B_HIGHLAND, B_PEAK)).mean() >= 0.5
            ok = bool(rocky) and not np.isin(probe.biome, (B_WATER, B_RIVER, B_VOID)).any()
        else:
            ok = bool(np.isin(probe.biome, _LAND_OK).all())
        if ok:
            accepted.append(poi)
    if len(cache.extra) > cache.limit:
        cache.extra.clear()
    cache.extra[key] = tuple(accepted)
    return cache.extra[key]


def apply_poi(seed: int, win: Window, poi: PoiCandidate) -> None:
    """Rewrite the tiles of `win` that fall inside the POI rectangle (pure per-tile function of the POI parameters)."""
    gx, gy = win.gx, win.gy
    inside = (gx >= poi.x0) & (gx < poi.x0 + poi.w) & (gy >= poi.y0) & (gy < poi.y0 + poi.h)
    if not inside.any():
        return
    win.poi_mask |= inside
    if poi.kind == "camp":
        win.biome[inside] = B_PLAINS
        win.terrain[inside] = TERRAIN_GRASS
        win.footprint[inside] = 0
    elif poi.kind == "shrine":
        win.biome[inside] = B_RUIN
        win.terrain[inside] = TERRAIN_PAVING
        win.footprint[inside] = 0
    elif poi.kind == "ruin":
        h = noise.tile_hash(seed, SALT_POI_TILE ^ (poi.salt & 0xFFFFFF), gx, gy)
        perimeter = inside & ((gx == poi.x0) | (gx == poi.x0 + poi.w - 1) | (gy == poi.y0) | (gy == poi.y0 + poi.h - 1))
        door = (gy == poi.y0 + poi.h - 1) & (gx == poi.x0 + poi.w // 2)
        broken = ((h >> np.uint64(40)) % np.uint64(100)) < np.uint64(30)
        wall = perimeter & ~door & ~broken
        win.biome[inside] = B_RUIN
        win.terrain[inside] = TERRAIN_PAVING
        win.footprint[inside] = 0
        win.footprint[wall] = FOOT_RUIN
    elif poi.kind == "cave":
        entrance = (gy == poi.y0 + poi.h - 1) & (gx == poi.x0 + poi.w // 2)
        win.biome[inside] = B_HIGHLAND
        win.terrain[inside] = TERRAIN_ROCK
        win.footprint[inside] = FOOT_ROCK
        win.footprint[entrance] = 0


_DEFAULT_CACHE = RegionCache()


def new_cache(limit: int = 4096) -> RegionCache:
    return RegionCache(limit)
