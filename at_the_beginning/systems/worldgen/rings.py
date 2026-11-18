"""The four rings of D11 as configuration, and a pure function from actor positions and velocities to load / unload / prefetch sets.

Pure Python, no I/O, no engine. Chunk addresses and the camera-window math come from `systems/map/chunking.py` (stdlib only), which
is loaded by file path so that importing this module does not pull in `systems.map` (whose package `__init__` imports the engine).
"""
from __future__ import annotations

import importlib.util
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .spec import CHUNK_UNITS


def _load_chunking():
    name = "systems_map_chunking_for_worldgen"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parents[1] / "map" / "chunking.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


chunking = _load_chunking()
ChunkCoord = chunking.ChunkCoord
CameraChunkWindow = chunking.CameraChunkWindow


@dataclass(frozen=True)
class RingConfig:
    """Radii are in chunks (256 units). Defaults are the D11 initial values."""

    chunk_units: float = float(CHUNK_UNITS)
    simulation_radius: int = 2        # 5 x 5 around each actor: chunk entities live in the tensors, full Tier 0
    prefetch_extra: int = 2           # generation ring = simulation + 2, cached ahead of need, no entities yet
    lead_extra: int = 2               # extra prefetch in the direction of travel
    unload_extra: int = 1             # a loaded chunk stays loaded until it is this far beyond the simulation ring (hysteresis)
    keep_extra: int = 1               # a cached chunk stays cached until it is this far beyond the prefetch ring (hysteresis)
    render_margin: int = 1            # render ring: camera rectangle plus this many chunks (client cost only)
    lead_min_speed: float = 2.0       # units/s below which an actor has no heading
    forward_bias: float = 0.35        # priority discount for chunks straight ahead

    @property
    def prefetch_radius(self) -> int:
        return self.simulation_radius + self.prefetch_extra


@dataclass(frozen=True)
class Actor:
    """World position in units (float64 is exact for any coordinate this game can reach) and velocity in units per second."""

    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0


@dataclass(frozen=True)
class StreamPlan:
    simulate: frozenset            # chunks that must be integrated (simulation ring of every actor)
    integrate: tuple               # simulate - loaded, nearest first: bring these into the engine
    unload: tuple                  # loaded chunks beyond the hysteresis radius, farthest first
    prefetch: tuple                # chunks beyond the simulation ring (prefetch ring incl. lead) not cached, in flight or loaded, best first
    generate: tuple                # everything that should be queued for generation (integrate + prefetch, not cached / in flight), best first
    wanted: frozenset              # simulate | prefetch ring: everything generation should produce
    keep: frozenset                # chunks the cache may keep (wanted dilated by keep_extra)
    drop: tuple                    # cached chunks outside `keep`
    render: frozenset              # chunks the client should hold, when a camera view is given
    priority: dict                 # chunk -> priority (lower = sooner), for every chunk in `wanted`


def chunk_of(x: float, y: float, cfg: RingConfig = RingConfig()) -> "ChunkCoord":
    return chunking.chunk_coord_for_world_point(x, y, chunk_px_w=cfg.chunk_units, chunk_px_h=cfg.chunk_units)


def heading(actor: Actor, cfg: RingConfig) -> Optional[tuple]:
    speed = math.hypot(actor.vx, actor.vy)
    if speed < cfg.lead_min_speed:
        return None
    return actor.vx / speed, actor.vy / speed


def _square(center, radius: int) -> Iterable:
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            yield ChunkCoord(center.x + dx, center.y + dy)


def actor_rings(actor: Actor, cfg: RingConfig):
    """(simulate set, prefetch-ring set including the lead) for one actor."""
    here = chunk_of(actor.x, actor.y, cfg)
    simulate = set(_square(here, cfg.simulation_radius))
    prefetch = set(_square(here, cfg.prefetch_radius))
    h = heading(actor, cfg)
    if h is not None and cfg.lead_extra > 0:
        m = max(abs(h[0]), abs(h[1]))                      # the dominant axis advances `lead_extra` chunks; a diagonal heading leads on both axes
        shift = (int(round(h[0] / m * cfg.lead_extra)), int(round(h[1] / m * cfg.lead_extra)))
        if shift != (0, 0):
            prefetch |= set(_square(ChunkCoord(here.x + shift[0], here.y + shift[1]), cfg.prefetch_radius))
    return simulate, prefetch


def dilate(chunks: Iterable, by: int) -> set:
    out = set()
    for c in chunks:
        for dy in range(-by, by + 1):
            for dx in range(-by, by + 1):
                out.add(ChunkCoord(c.x + dx, c.y + dy))
    return out


def chunk_priority(coord, actors: Sequence[Actor], cfg: RingConfig, in_simulation: bool) -> float:
    """Lower is sooner. Distance in chunks from the nearest actor, discounted for chunks ahead of its heading."""
    best = math.inf
    cu = cfg.chunk_units
    ccx, ccy = (coord.x + 0.5) * cu, (coord.y + 0.5) * cu
    for a in actors:
        dx, dy = ccx - a.x, ccy - a.y
        dist = math.hypot(dx, dy) / cu
        h = heading(a, cfg)
        if h is not None and dist > 0:
            cos = (dx * h[0] + dy * h[1]) / (dist * cu)
            dist *= 1.0 - cfg.forward_bias * max(cos, -1.0)
        best = min(best, dist)
    return (0.0 if in_simulation else 1000.0) + best


def plan_stream(actors: Sequence[Actor], loaded: Iterable = (), cached: Iterable = (), in_flight: Iterable = (), cfg: RingConfig = RingConfig(),
                view: Optional["CameraChunkWindow"] = None) -> StreamPlan:
    """Pure: the same inputs always give the same plan. `loaded` = integrated chunks, `cached` = chunks whose bytes are in the LRU,
    `in_flight` = chunks already requested from the generator."""
    loaded_set = chunking.normalize_chunk_set(loaded)
    cached_set = chunking.normalize_chunk_set(cached)
    flight_set = chunking.normalize_chunk_set(in_flight)
    simulate: set = set()
    prefetch_ring: set = set()
    for a in actors:
        s, p = actor_rings(a, cfg)
        simulate |= s
        prefetch_ring |= p
    wanted = simulate | prefetch_ring
    priority = {c: chunk_priority(c, actors, cfg, c in simulate) for c in wanted}
    order = lambda c: (priority.get(c, math.inf), c.x, c.y)       # noqa: E731
    integrate = tuple(sorted(simulate - loaded_set, key=order))
    unload_keep = dilate(simulate, cfg.unload_extra)
    unload = tuple(sorted(loaded_set - unload_keep, key=lambda c: (-min((math.hypot((c.x + 0.5) * cfg.chunk_units - a.x, (c.y + 0.5) * cfg.chunk_units - a.y) for a in actors), default=0.0), c.x, c.y)))
    pending = wanted - cached_set - flight_set - loaded_set
    prefetch = tuple(sorted(pending - simulate, key=order))
    generate = tuple(sorted(pending, key=order))
    keep = dilate(wanted, cfg.keep_extra) | (loaded_set - set(unload))
    drop = tuple(sorted(cached_set - keep, key=lambda c: (c.x, c.y)))
    render: set = set()
    if view is not None:
        render = set(chunking.chunks_for_camera_window(view, chunk_px_w=cfg.chunk_units, chunk_px_h=cfg.chunk_units))
    return StreamPlan(frozenset(simulate), integrate, unload, prefetch, generate, frozenset(wanted), frozenset(keep), drop, frozenset(render), priority)


def blocked_by_void(x: float, y: float, loaded: Iterable, cfg: RingConfig = RingConfig()) -> bool:
    """True when (x, y) lies in a chunk that is not integrated: the boundary of the loaded area acts as an invisible wall (D11)."""
    return chunk_of(x, y, cfg) not in chunking.normalize_chunk_set(loaded)
