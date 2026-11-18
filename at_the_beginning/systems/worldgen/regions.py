"""Coarse region grid for features larger than a chunk (lakes, forest patches, ruins and other points of interest).

A region is REGION_CHUNKS x REGION_CHUNKS chunks (256 x 256 tiles). Each region's features come from hashes of
(seed, region x, region y, kind, slot) only. A feature may stick out of its region by at most MAX_FEATURE_RADIUS tiles, so a
chunk looks at every region within that distance of its window and emits the part of each feature that overlaps it. Two chunks
that see the same feature compute identical parameters, so seams (including region seams) cannot disagree.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import noise
from .spec import MAX_FEATURE_RADIUS, REGION_TILES

K_LAKE, K_FOREST, K_POI = 11, 12, 13

LAKE_SLOT_PERCENT = (45, 15)
FOREST_SLOT_PERCENT = (60, 40, 25)
POI_SLOT_PERCENT = (90, 50)

POI_KINDS = ("ruin", "camp", "shrine", "cave")
POI_WEIGHTS = (40, 25, 20, 15)


@dataclass(frozen=True)
class Lake:
    id: str
    cx: int          # centre tile (world tile coordinates)
    cy: int
    rx: int          # radii in tiles
    ry: int


@dataclass(frozen=True)
class ForestPatch:
    id: str
    cx: int
    cy: int
    r: int
    strength: int    # added to the forest field at the centre, falling to 0 at the rim


@dataclass(frozen=True)
class PoiCandidate:
    id: str
    kind: str
    x0: int          # tile rectangle [x0, x0 + w) x [y0, y0 + h)
    y0: int
    w: int
    h: int
    salt: int        # per-POI hash domain for tile decisions inside it

    @property
    def anchor(self) -> tuple[int, int]:
        return self.x0 + self.w // 2, self.y0 + self.h // 2


@dataclass(frozen=True)
class RegionRaw:
    lakes: tuple[Lake, ...]
    forests: tuple[ForestPatch, ...]
    pois: tuple[PoiCandidate, ...]


def _h(seed: int, kind: int, rx: int, ry: int, slot: int, part: int) -> int:
    return noise.derive(seed, kind, rx, ry, slot, part)


def region_raw(seed: int, rx: int, ry: int) -> RegionRaw:
    base_x, base_y = rx * REGION_TILES, ry * REGION_TILES
    lakes, forests, pois = [], [], []
    for slot, pct in enumerate(LAKE_SLOT_PERCENT):
        if _h(seed, K_LAKE, rx, ry, slot, 0) % 100 < pct:
            lakes.append(Lake(f"lake:{rx}:{ry}:{slot}", base_x + _h(seed, K_LAKE, rx, ry, slot, 1) % REGION_TILES,
                              base_y + _h(seed, K_LAKE, rx, ry, slot, 2) % REGION_TILES,
                              8 + _h(seed, K_LAKE, rx, ry, slot, 3) % 17, 6 + _h(seed, K_LAKE, rx, ry, slot, 4) % 15))
    for slot, pct in enumerate(FOREST_SLOT_PERCENT):
        if _h(seed, K_FOREST, rx, ry, slot, 0) % 100 < pct:
            forests.append(ForestPatch(f"forest:{rx}:{ry}:{slot}", base_x + _h(seed, K_FOREST, rx, ry, slot, 1) % REGION_TILES,
                                       base_y + _h(seed, K_FOREST, rx, ry, slot, 2) % REGION_TILES,
                                       14 + _h(seed, K_FOREST, rx, ry, slot, 3) % 22, 900 + _h(seed, K_FOREST, rx, ry, slot, 4) % 1200))
    for slot, pct in enumerate(POI_SLOT_PERCENT):
        if _h(seed, K_POI, rx, ry, slot, 0) % 100 < pct:
            pick = _h(seed, K_POI, rx, ry, slot, 1) % sum(POI_WEIGHTS)
            kind = POI_KINDS[-1]
            for name, weight in zip(POI_KINDS, POI_WEIGHTS):
                if pick < weight:
                    kind = name
                    break
                pick -= weight
            w, h = {"ruin": (7 + _h(seed, K_POI, rx, ry, slot, 2) % 4, 6 + _h(seed, K_POI, rx, ry, slot, 3) % 3),
                    "camp": (5, 5), "shrine": (3, 3), "cave": (5, 4)}[kind]
            cx = base_x + 12 + _h(seed, K_POI, rx, ry, slot, 4) % (REGION_TILES - 24)
            cy = base_y + 12 + _h(seed, K_POI, rx, ry, slot, 5) % (REGION_TILES - 24)
            pois.append(PoiCandidate(f"poi:{rx}:{ry}:{slot}", kind, cx - w // 2, cy - h // 2, w, h, _h(seed, K_POI, rx, ry, slot, 6)))
    return RegionRaw(tuple(lakes), tuple(forests), tuple(pois))


def regions_near(gx0: int, gy0: int, width: int, height: int, margin: int = MAX_FEATURE_RADIUS):
    """Region coordinates whose features can touch the tile window, in a fixed order."""
    rx0 = (gx0 - margin) // REGION_TILES
    rx1 = (gx0 + width - 1 + margin) // REGION_TILES
    ry0 = (gy0 - margin) // REGION_TILES
    ry1 = (gy0 + height - 1 + margin) // REGION_TILES
    return [(rx, ry) for ry in range(ry0, ry1 + 1) for rx in range(rx0, rx1 + 1)]


class RegionCache:
    """Small per-process cache of RegionRaw; purely an optimisation (every entry is recomputable from the key)."""

    def __init__(self, limit: int = 4096):
        self.limit = limit
        self._raw: dict = {}
        self.extra: dict = {}          # accepted points of interest (filled by classify.accepted_pois)

    def raw(self, seed: int, rx: int, ry: int) -> RegionRaw:
        key = (seed, rx, ry)
        value = self._raw.get(key)
        if value is None:
            if len(self._raw) >= self.limit:
                self._raw.clear()
            value = self._raw[key] = region_raw(seed, rx, ry)
        return value
