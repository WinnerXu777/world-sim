"""Creature collision (``1008_creatures_gap.md`` section 11, added on c3's decision CREATURE-KERNEL): the kernel's moves go through the same wall boxes humans slide against.

The boxes are the movement contract's own: the window's chunk boxes (rock, ruin walls and water bodies come from the footprint layer), the void boxes around the integrated set, the placed
maps' boxes (interior containment slabs) and the live ``M_WALL`` rows, so a house a resident built is a wall for a wolf. ``slide`` of ``systems/movement/spatial.py`` is re-done here for
N creatures at once (float64, the same X-then-Y sweep, the same 1e-4 tolerances, deterministic: no ``random``), with three differences, each on purpose:

* a creature that starts inside the inflated margin of a wall (a spawn on a tile next to rock) is not frozen: it may move, but never into the wall box itself (the final position is
  rejected against the raw boxes), and one that starts inside a raw box (a wall built on top of it) may walk out;
* three movement classes: ``land`` (every box, and the terrain-water tiles the footprint layer misses: shallows), ``fly`` (ignores the generated chunk boxes - rock, water, ruin - but not the
  void, interior, or built walls, so a crow cannot enter a closed building) and ``swim`` (ignores the generated boxes and may only stand on water tiles);
* ``blocked_segments``: a wall between attacker and victim stops the blow (a goblin does not hit a resident through the wall of the shelter).

Space != 0 stays unreachable twice over: the kernel only moves space-0 rows and clamps them to the window frame, and pockets/interiors lie outside that frame (and behind their slabs).
"""
from __future__ import annotations

import re
from typing import Optional

import torch

try:
    from harness.numerics import pairwise_distances, window_enabled
    from systems.movement.map_contract import compose_group
    from systems.movement.spatial import RADIUS, placed_boxes_for_window, wall_boxes
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.numerics import pairwise_distances, window_enabled
    from at_the_beginning.systems.movement.map_contract import compose_group
    from at_the_beginning.systems.movement.spatial import RADIUS, placed_boxes_for_window, wall_boxes

LAND, FLY, SWIM = 0, 1, 2
EPS = 1e-4
TERRAIN_WATER = 3          # systems/worldgen/spec.py; asserted equal in the tests
FOOT_WATER = 1
TILE = 8.0
CHUNK_TILES = 32
_GENERATED = re.compile(r"^c-?\d+_-?\d+:w\d+$")      # ids of the generator's chunk boxes (void boxes are ``void:..``)
_BOXES: dict = {}                                    # (engine id) -> (key, static tensor [B, 4], generated flag [B])
_MASKS: dict = {}                                    # chunk sha256 -> (water [32, 32] bool, graze [32, 32] bool)
_GRIDS: dict = {}                                    # (engine id) -> (revision, water grid, graze grid, near-water grid, col0, row0)
TERRAIN_SAND = 2
TERRAIN_GRASS = 1


def water_mask_of(document: dict) -> torch.Tensor:
    """bool [32, 32] (row = tile y, column = tile x): terrain water or a water-body footprint. Pure."""
    return terrain_masks(document)[0]


def terrain_masks(document: dict) -> tuple:
    """(water, graze) bool [32, 32]: water = terrain water or a water-body footprint; graze = grass or sand with nothing built on it (what a grazer can eat from). Pure."""
    layers = {layer["name"]: layer["tiles"] for layer in document["layers"]}
    terrain = torch.tensor(layers["terrain"], dtype=torch.int16)
    footprint = torch.tensor(layers["footprint"], dtype=torch.int16)
    water = (terrain == TERRAIN_WATER) | (footprint == FOOT_WATER)
    graze = ((terrain == TERRAIN_GRASS) | (terrain == TERRAIN_SAND)) & (footprint == 0)
    return water, graze


def _static_boxes(engine) -> tuple:
    """(boxes [B, 4] float64 as min_x, min_y, max_x, max_y, generated [B] bool) for the window contract and the placed maps; cached while the window revision stands."""
    contract = getattr(engine, "_window_contract", None) or {}
    window = contract.get("boxes", [])
    group = compose_group(getattr(engine, "_map_name", None))
    placed = placed_boxes_for_window(group["boxes"], contract if window_enabled() else None, group["entries"]) if group is not None else []   # F1: no slabs over chunks
    key = (contract.get("revision"), id(placed), len(placed), len(window))
    cached = _BOXES.get(id(engine))
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]
    rows = [[b["min"][0], b["min"][1], b["max"][0], b["max"][1]] for b in placed] + [[b["min"][0], b["min"][1], b["max"][0], b["max"][1]] for b in window]
    flags = [False] * len(placed) + [bool(_GENERATED.match(str(b["id"]))) for b in window]
    boxes = torch.tensor(rows, dtype=torch.float64).reshape(-1, 4)
    generated = torch.tensor(flags, dtype=torch.bool)
    _BOXES[id(engine)] = (key, boxes, generated)
    return boxes, generated


def boxes_for(engine) -> tuple:
    """(boxes [B, 4], generated [B]): the static part plus the live ``M_WALL`` rows (never flagged generated)."""
    boxes, generated = _static_boxes(engine)
    live = wall_boxes(engine.state.m_tensor, engine._entity_uid_by_slot)
    if live:
        extra = torch.tensor([[w["min"][0], w["min"][1], w["max"][0], w["max"][1]] for w in live], dtype=torch.float64)
        boxes = torch.cat([boxes, extra])
        generated = torch.cat([generated, torch.zeros(len(live), dtype=torch.bool)])
    return boxes, generated


def _grids(engine) -> Optional[tuple]:
    """(water, graze, near, col0, row0): bool grids [352, 352] over the window's tile frame built from the integrated chunks' documents (``near`` = water within one tile);
    rebuilt when the window revision changes."""
    manager = getattr(engine, "_window", None)
    if manager is None:
        return None
    revision = (getattr(engine, "_window_contract", None) or {}).get("revision")
    cached = _GRIDS.get(id(engine))
    if cached is not None and cached[0] == revision:
        return cached[1:]
    try:
        from harness.window import WINDOW_FRAME
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness.window import WINDOW_FRAME
    width, height, (col0, row0) = WINDOW_FRAME
    water = torch.zeros(height, width, dtype=torch.bool)
    graze = torch.zeros(height, width, dtype=torch.bool)
    for coord, state in manager.chunks.items():
        masks = _MASKS.get(state.sha256)
        if masks is None:
            chunk = manager.service.peek(coord)
            if chunk is None:
                continue
            masks = terrain_masks(chunk.document)
            if len(_MASKS) > 512:
                _MASKS.clear()
            _MASKS[state.sha256] = masks
        lx, ly = manager._local_origin(coord)
        c, r = int(round(lx / TILE)) - col0, int(round(ly / TILE)) - row0
        if 0 <= c <= width - CHUNK_TILES and 0 <= r <= height - CHUNK_TILES:
            water[r:r + CHUNK_TILES, c:c + CHUNK_TILES] = masks[0]
            graze[r:r + CHUNK_TILES, c:c + CHUNK_TILES] = masks[1]
    near = torch.nn.functional.max_pool2d(water.float().unsqueeze(0).unsqueeze(0), 3, stride=1, padding=1)[0, 0] > 0
    _GRIDS[id(engine)] = (revision, water, graze, near, col0, row0)
    return water, graze, near, col0, row0


def _water_grid(engine) -> Optional[tuple]:
    """(water grid, col0, row0) - the shape ``in_water`` reads (tests patch this)."""
    found = _grids(engine)
    return None if found is None else (found[0], found[3], found[4])


def _lookup(engine, xy: torch.Tensor, which: int) -> torch.Tensor:
    found = _grids(engine)
    if found is None or xy.shape[0] == 0:
        return torch.zeros(xy.shape[0], dtype=torch.bool)
    grid, col0, row0 = found[which], found[3], found[4]
    c = torch.floor(xy[:, 0].double() / TILE).long() - col0
    r = torch.floor(xy[:, 1].double() / TILE).long() - row0
    ok = (c >= 0) & (c < grid.shape[1]) & (r >= 0) & (r < grid.shape[0])
    return grid[r.clamp(0, grid.shape[0] - 1), c.clamp(0, grid.shape[1] - 1)] & ok


def on_graze(engine, xy: torch.Tensor) -> torch.Tensor:
    """bool [N]: the tile under each position is grass or sand with nothing built on it."""
    return _lookup(engine, xy, 1)


def near_water(engine, xy: torch.Tensor) -> torch.Tensor:
    """bool [N]: a water tile within one tile of each position (a creature drinks from the shore)."""
    return _lookup(engine, xy, 2)


def toward_water(engine, xy: torch.Tensor, radius: float) -> tuple:
    """``(vector [N, 2], found [N])``: the vector to the centre of the nearest water tile within ``radius`` units, and whether there is one."""
    found = _grids(engine)
    n = xy.shape[0]
    if found is None or n == 0:
        return torch.zeros(n, 2), torch.zeros(n, dtype=torch.bool)
    water, col0, row0 = found[0], found[3], found[4]
    tiles = water.nonzero(as_tuple=False)
    if tiles.shape[0] == 0:
        return torch.zeros(n, 2), torch.zeros(n, dtype=torch.bool)
    centres = torch.stack([(tiles[:, 1] + col0 + 0.5) * TILE, (tiles[:, 0] + row0 + 0.5) * TILE], dim=1).float()
    d = pairwise_distances(xy.float(), centres)
    best, arg = d.min(dim=1)
    return centres[arg] - xy.float(), best <= radius


def in_water(engine, xy: torch.Tensor) -> torch.Tensor:
    """bool [N]: the tile under each position is water (False outside the integrated chunks)."""
    found = _water_grid(engine)
    if found is None or xy.shape[0] == 0:
        return torch.zeros(xy.shape[0], dtype=torch.bool)
    grid, col0, row0 = found
    c = torch.floor(xy[:, 0].double() / TILE).long() - col0
    r = torch.floor(xy[:, 1].double() / TILE).long() - row0
    ok = (c >= 0) & (c < grid.shape[1]) & (r >= 0) & (r < grid.shape[0])
    return grid[r.clamp(0, grid.shape[0] - 1), c.clamp(0, grid.shape[1] - 1)] & ok


def slide_many(start: torch.Tensor, desired: torch.Tensor, boxes: torch.Tensor, radius: float = RADIUS) -> torch.Tensor:
    """N creatures slid through ``boxes`` ([B, 4] raw boxes). ``start`` and ``desired`` are float64 [N, 2]; returns float64 [N, 2]."""
    if boxes.shape[0] == 0 or start.shape[0] == 0:
        return desired
    lo = torch.minimum(start, desired).min(dim=0).values - 2.0 * radius - 1.0           # boxes that no sweep can reach are dropped
    hi = torch.maximum(start, desired).max(dim=0).values + 2.0 * radius + 1.0
    keep = (boxes[:, 2] >= lo[0]) & (boxes[:, 0] <= hi[0]) & (boxes[:, 3] >= lo[1]) & (boxes[:, 1] <= hi[1])
    boxes = boxes[keep]
    if boxes.shape[0] == 0:
        return desired
    x, y = start[:, 0:1], start[:, 1:2]
    nx, ny = desired[:, 0], desired[:, 1]
    rx0, ry0, rx1, ry1 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    a, b, c, d = rx0 - radius, ry0 - radius, rx1 + radius, ry1 + radius
    inside_raw = ((rx0 < x) & (x < rx1) & (ry0 < y) & (y < ry1)).any(dim=1)             # a wall was built on it: let it walk out
    inf = torch.full_like(a, float("inf"))
    in_y = (b < y) & (y < d)
    right = in_y & (x <= a + EPS) & (nx.unsqueeze(1) > a)
    left = in_y & (x >= c - EPS) & (nx.unsqueeze(1) < c)
    nx = torch.minimum(nx, torch.where(right, a.expand_as(right), inf.expand_as(right)).min(dim=1).values)
    nx = torch.maximum(nx, torch.where(left, c.expand_as(left), -inf.expand_as(left)).max(dim=1).values)
    in_x = (a < nx.unsqueeze(1)) & (nx.unsqueeze(1) < c)
    below = in_x & (y <= b + EPS) & (ny.unsqueeze(1) > b)
    above = in_x & (y >= d - EPS) & (ny.unsqueeze(1) < d)
    ny = torch.minimum(ny, torch.where(below, b.expand_as(below), inf.expand_as(below)).min(dim=1).values)
    ny = torch.maximum(ny, torch.where(above, d.expand_as(above), -inf.expand_as(above)).max(dim=1).values)
    out = torch.stack([nx, ny], dim=1)
    enters = ((rx0 < out[:, 0:1]) & (out[:, 0:1] < rx1) & (ry0 < out[:, 1:2]) & (out[:, 1:2] < ry1)).any(dim=1)
    free = inside_raw
    out = torch.where((enters & ~free).unsqueeze(1), start, out)
    return torch.where(free.unsqueeze(1), desired, out)


def resolve(engine, start: torch.Tensor, desired: torch.Tensor, kind: torch.Tensor) -> tuple:
    """Where each creature ends up: ``(positions float32 [N, 2], held)`` with ``held`` the number whose move was cut short. ``kind`` is LAND / FLY / SWIM per row."""
    s, d = start.double().cpu(), desired.double().cpu()
    kind = kind.cpu()
    boxes, generated = boxes_for(engine)
    out = d.clone()
    land = kind == LAND
    other = ~land
    if bool(land.any()):
        out[land] = slide_many(s[land], d[land], boxes)
    if bool(other.any()):
        out[other] = slide_many(s[other], d[other], boxes[~generated])
    wet = in_water(engine, out.float())
    was_wet = in_water(engine, s.float())
    stop = (land & wet & ~was_wet) | ((kind == SWIM) & ~wet)
    out = torch.where(stop.unsqueeze(1), s, out)
    held = int(((out - d).abs().sum(dim=1) > 1e-9).sum())
    return out.to(start.dtype).to(start.device), held


def blocked_segments(engine, a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """bool [N]: the closed segment a -> b touches a wall box (slab test, all boxes). For gating blows: a wall stops them."""
    n = a.shape[0]
    if n == 0:
        return torch.zeros(0, dtype=torch.bool)
    boxes, _ = boxes_for(engine)
    if boxes.shape[0] == 0:
        return torch.zeros(n, dtype=torch.bool)
    p, q = a.double().cpu(), b.double().cpu()
    lo = torch.minimum(p, q).min(dim=0).values - 1.0
    hi = torch.maximum(p, q).max(dim=0).values + 1.0
    boxes = boxes[(boxes[:, 2] >= lo[0]) & (boxes[:, 0] <= hi[0]) & (boxes[:, 3] >= lo[1]) & (boxes[:, 1] <= hi[1])]
    if boxes.shape[0] == 0:
        return torch.zeros(n, dtype=torch.bool)
    enter = torch.zeros(n, boxes.shape[0], dtype=torch.float64)
    leave = torch.ones(n, boxes.shape[0], dtype=torch.float64)
    miss = torch.zeros(n, boxes.shape[0], dtype=torch.bool)
    for axis in range(2):
        s0, delta = p[:, axis:axis + 1], (q - p)[:, axis:axis + 1]
        lo_b, hi_b = boxes[:, axis].unsqueeze(0), boxes[:, axis + 2].unsqueeze(0)
        parallel = delta.abs() < 1e-9
        safe = torch.where(parallel, torch.ones_like(delta), delta)
        t0, t1 = (lo_b - s0) / safe, (hi_b - s0) / safe
        first, last = torch.minimum(t0, t1), torch.maximum(t0, t1)
        miss |= parallel & ~((lo_b <= s0) & (s0 <= hi_b))
        enter = torch.where(parallel, enter, torch.maximum(enter, first))
        leave = torch.where(parallel, leave, torch.minimum(leave, last))
    return ((enter <= leave) & ~miss).any(dim=1).to(a.device)
