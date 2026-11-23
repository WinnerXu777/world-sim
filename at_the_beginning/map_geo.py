"""
map_geo.py
==========
Geometric layer for the entity registry.

Decoupling principle
────────────────────
m_tensor stores ATTRIBUTE STATE   (HP, food, fire counter, age…) — changes every tick.
MAP_GEO  stores SHAPE / GEOMETRY  (circle centre, radius, tile_mask) — changes rarely.

Two mutation rates handled separately:
  Every tick    → instincts write m_tensor cols directly
  Event-driven  → tools call geo_mutate() which recomputes tile_mask + bumps geo_version

Spatial query pattern (O(1) per agent per tick)
────────────────────────────────────────────────
    # Convert agent pixel position → background tile index
    tile_idx = _px_to_tile_idx(ax, ay)
    # Look up which entity (if any) covers that tile
    entity_id = TILE_TO_ENTITY.get(tile_idx, -1)
    # Read entity attributes from m_tensor
    food = m_tensor[entity_id, M_RESOURCE_FOOD]

No polygon math in the hot loop.  tile_mask is precomputed once per geo_mutate call.

Public API
──────────
    register_entity(eid, shape, cx, cy, r, device)  — add/update geometry
    unregister_entity(eid)                           — remove on entity death
    geo_mutate(eid, cx, cy, r, device)               — update shape, recompute mask
    entity_at(ax, ay) -> int                         — which entity is at pixel pos?
    entities_in_radius(cx, cy, r, m_type) -> list    — entity ids near a point
    get_geo_json() -> dict                           — serialise for /get_map
"""

import math

import torch
from genesis_config import GRID_W, GRID_H, TILE_SIZE, MAX_BG_TILES

# =============================================================================
# FRAME (1008 P4)
# =============================================================================
# The tile frame is GRID_W x GRID_H tiles whose tile (0, 0) is world tile (_ORIGIN_COL, _ORIGIN_ROW).  Default: the legacy full-world
# frame (origin 0, genesis_config sizes, dense (GRID_H, GRID_W) boolean masks).  ``configure_window`` swaps in a smaller frame (the
# streaming window of EDEN_WINDOW) and, optionally, SPARSE masks: each area entity stores only the bounding box of its tiles.
# GRID_W / GRID_H are module globals that ``configure_window`` reassigns; read them as ``map_geo.GRID_W`` (never copy them at import).

_ORIGIN_COL: int = 0
_ORIGIN_ROW: int = 0
_SPARSE: bool = False
_POCKETS: list = []
POCKET_TILES: int = 32
"""P5 (e): interior pockets of the window format. Each pocket is its own POCKET_TILES x POCKET_TILES tile frame at a fixed layout
origin (px); its tiles are keyed in TILE_TO_ENTITY after the main frame (``GRID_W * GRID_H + pocket * POCKET_TILES ** 2 + row * POCKET_TILES +
col``). Empty (the default) means one frame and the behaviour of P4."""

# =============================================================================
# MODULE-LEVEL STATE
# =============================================================================

geo_version: int = 0
"""Incremented on every geometry write.  Viewer polls /map_version and
re-fetches /get_map only when this number changes."""

MAP_GEO: dict[int, dict] = {}
"""
entity_id → {
    "shape":     "circle" | "polygon",
    "cx":        float,
    "cy":        float,
    "r":         float,            # circle only
    "points":    [(x,y), …],      # polygon only
    "tile_mask": BoolTensor(GRID_H, GRID_W),
}
"""

TILE_TO_ENTITY: dict[int, int] = {}
"""
Flat background tile index → entity_id.
Built from MAP_GEO tile_masks.  Last-writer wins for overlapping entities
(structures built on top of natural features take priority).
Rebuilt incrementally on register/unregister — never full-scan.
"""

# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def configure_window(grid_w: int, grid_h: int, origin_tile: tuple[int, int] = (0, 0), sparse: bool = True) -> None:
    """Use a (grid_h, grid_w) tile frame whose tile (0, 0) is world tile ``origin_tile`` = (col, row), with sparse bounding-box masks
    (``sparse``) or dense frame-sized masks.  Call before any geometry is registered; the full legacy frame at origin (0, 0) with
    sparse masks is bit-identical to the default (the P4 proof)."""
    global GRID_W, GRID_H, _ORIGIN_COL, _ORIGIN_ROW, _SPARSE
    if MAP_GEO or TILE_TO_ENTITY:
        raise RuntimeError("map_geo.configure_window: geometry is already registered; reset the world first")
    if int(grid_w) < 1 or int(grid_h) < 1:
        raise ValueError("map_geo.configure_window: the frame must have at least one tile")
    GRID_W, GRID_H = int(grid_w), int(grid_h)
    _ORIGIN_COL, _ORIGIN_ROW = int(origin_tile[0]), int(origin_tile[1])
    _SPARSE = bool(sparse)


def configure_pockets(origins_px) -> None:
    """Window mode: register the interior pocket frames (``[(x_px, y_px), ...]`` of each pocket's lower-left corner; whole tiles). Call
    before any geometry is registered, after ``configure_window``."""
    if MAP_GEO or TILE_TO_ENTITY:
        raise RuntimeError("map_geo.configure_pockets: geometry is already registered; reset the world first")
    if not _SPARSE:
        raise RuntimeError("map_geo.configure_pockets: pockets need the sparse window frame")
    cleaned = []
    for x, y in origins_px:
        if x % TILE_SIZE or y % TILE_SIZE:
            raise ValueError("map_geo.configure_pockets: a pocket origin must be a whole number of tiles")
        cleaned.append((int(x) // TILE_SIZE, int(y) // TILE_SIZE))
    _POCKETS[:] = cleaned


def reset_window() -> None:
    """Back to the legacy frame (genesis_config sizes, origin 0, dense masks)."""
    import genesis_config
    global GRID_W, GRID_H, _ORIGIN_COL, _ORIGIN_ROW, _SPARSE
    GRID_W, GRID_H, _ORIGIN_COL, _ORIGIN_ROW, _SPARSE = genesis_config.GRID_W, genesis_config.GRID_H, 0, 0, False
    _POCKETS.clear()


def window_frame() -> dict:
    """The frame in use: sizes, origin tile (col, row) and mask mode."""
    frame = {"grid_w": GRID_W, "grid_h": GRID_H, "origin_tile": [_ORIGIN_COL, _ORIGIN_ROW], "sparse": _SPARSE}
    if _POCKETS:
        frame["pockets"] = [list(p) for p in _POCKETS]
    return frame


def sparse_enabled() -> bool:
    return _SPARSE


def _main_frame() -> tuple:
    """(origin col, origin row, width, height, key base, pocket id) of the main tile frame."""
    return (_ORIGIN_COL, _ORIGIN_ROW, GRID_W, GRID_H, 0, None)


def _pocket_frame(pocket: int) -> tuple:
    col, row = _POCKETS[pocket]
    return (col, row, POCKET_TILES, POCKET_TILES, GRID_W * GRID_H + pocket * POCKET_TILES * POCKET_TILES, pocket)


def _frame_at(px: float, py: float, strict: bool = False):
    """The tile frame holding the point: the main frame, or the pocket whose square contains it. With pockets configured a point in neither
    gives None when ``strict`` (a query outside every frame finds nothing), else the main frame (clamped, as in P4)."""
    if not _POCKETS:
        return _main_frame()
    col, row = math.floor(px / TILE_SIZE), math.floor(py / TILE_SIZE)
    if _ORIGIN_COL <= col < _ORIGIN_COL + GRID_W and _ORIGIN_ROW <= row < _ORIGIN_ROW + GRID_H:
        return _main_frame()
    for index, (pc, pr) in enumerate(_POCKETS):
        if pc <= col < pc + POCKET_TILES and pr <= row < pr + POCKET_TILES:
            return _pocket_frame(index)
    return None if strict else _main_frame()


def _px_to_tile_idx(px: float, py: float, frame=None) -> int:
    """Convert a pixel position to a flat background tile index (of the frame holding it, clamped to it)."""
    col0, row0, width, height, base, _ = frame or _frame_at(px, py)
    col = math.floor(px / TILE_SIZE) - col0
    row = math.floor(py / TILE_SIZE) - row0
    col = max(0, min(col, width - 1))
    row = max(0, min(row, height - 1))
    return base + row * width + col


def tile_center_px(tile_idx: int) -> tuple[float, float]:
    """The pixel position of the centre of a flat tile index (main frame, or a pocket's when the index is past the main frame)."""
    idx = int(tile_idx)
    if _POCKETS and idx >= GRID_W * GRID_H:
        pocket, rest = divmod(idx - GRID_W * GRID_H, POCKET_TILES * POCKET_TILES)
        row, col = divmod(rest, POCKET_TILES)
        return ((col + _POCKETS[pocket][0]) * TILE_SIZE + TILE_SIZE / 2.0, (row + _POCKETS[pocket][1]) * TILE_SIZE + TILE_SIZE / 2.0)
    row, col = divmod(idx, GRID_W)
    return ((col + _ORIGIN_COL) * TILE_SIZE + TILE_SIZE / 2.0, (row + _ORIGIN_ROW) * TILE_SIZE + TILE_SIZE / 2.0)


def _clip_to_space(mask: torch.Tensor, x: float, y: float, row0: int = 0, col0: int = 0, frame=None) -> torch.Tensor:
    """EDEN_SPACES: an area entity covers only the tiles of its own space (an interior's tiles never map to an overworld row, nor the
    other way round). Identity with the flag off or without interiors.  ``row0`` / ``col0``: frame position of the mask's top-left tile
    (sparse boxes); the frame origin is added here."""
    try:
        from harness.spaces import clip_tile_mask
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness.spaces import clip_tile_mask
    origin_col, origin_row = (_ORIGIN_COL, _ORIGIN_ROW) if frame is None else (frame[0], frame[1])
    return clip_tile_mask(mask, x, y, TILE_SIZE, row0 + origin_row, col0 + origin_col)


def _compute_circle_mask(cx: float, cy: float, r: float,
                          device: str) -> torch.Tensor:
    """
    Return bool tensor (GRID_H, GRID_W) — True for every background tile
    whose centre lies within radius r of (cx, cy).
    Computed once per geo_mutate call; never runs in the tick loop.
    """
    gx = ((torch.arange(GRID_W, dtype=torch.float32, device=device) + _ORIGIN_COL)
          * TILE_SIZE + TILE_SIZE / 2)
    gy = ((torch.arange(GRID_H, dtype=torch.float32, device=device) + _ORIGIN_ROW)
          * TILE_SIZE + TILE_SIZE / 2)
    grid_y, grid_x = torch.meshgrid(gy, gx, indexing="ij")
    dist = ((grid_x - cx) ** 2 + (grid_y - cy) ** 2).sqrt()
    return dist < r


def _compute_polygon_mask(points: list[tuple[float, float]],
                           device: str) -> torch.Tensor:
    """
    Ray-casting polygon fill on the background tile grid.
    points: list of (x, y) pixel vertices (closed polygon).
    Returns bool tensor (GRID_H, GRID_W).
    """
    gx = ((torch.arange(GRID_W, dtype=torch.float32, device=device) + _ORIGIN_COL)
          * TILE_SIZE + TILE_SIZE / 2)
    gy = ((torch.arange(GRID_H, dtype=torch.float32, device=device) + _ORIGIN_ROW)
          * TILE_SIZE + TILE_SIZE / 2)
    grid_y, grid_x = torch.meshgrid(gy, gx, indexing="ij")   # (H, W)

    inside = torch.zeros((GRID_H, GRID_W), dtype=torch.bool, device=device)
    n      = len(points)
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[(i + 1) % n]
        # Standard ray-cast condition
        cond = (
            ((grid_y > min(yi, yj)) & (grid_y <= max(yi, yj)))
            & (grid_x <= (xj - xi) * (grid_y - yi) / (yj - yi + 1e-9) + xi)
        )
        inside ^= cond
    return inside


def _span(lo_px: float, hi_px: float, origin: int, size: int) -> tuple[int, int]:
    """Frame tile range [a, b) that can hold a tile centre in [lo_px, hi_px] (one tile of margin each side), clipped to the frame."""
    if not (math.isfinite(lo_px) and math.isfinite(hi_px)):
        return 0, size
    a = math.floor(lo_px / TILE_SIZE) - 1 - origin
    b = math.ceil(hi_px / TILE_SIZE) + 1 - origin
    return max(0, a), min(size, b)


def _box_grid(r0: int, r1: int, c0: int, c1: int, device: str, origin_col: int | None = None, origin_row: int | None = None):
    origin_col = _ORIGIN_COL if origin_col is None else origin_col
    origin_row = _ORIGIN_ROW if origin_row is None else origin_row
    gx = ((torch.arange(c0, c1, dtype=torch.float32, device=device) + origin_col) * TILE_SIZE + TILE_SIZE / 2)
    gy = ((torch.arange(r0, r1, dtype=torch.float32, device=device) + origin_row) * TILE_SIZE + TILE_SIZE / 2)
    return torch.meshgrid(gy, gx, indexing="ij")


def _entity_frame(shape: str, cx: float, cy: float, points) -> tuple:
    """The frame an area entity's tiles live in: that of its centre (a circle's) or centroid (a polygon's)."""
    if shape == "polygon" and points:
        cx, cy = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    return _frame_at(cx, cy) or _main_frame()


def _sparse_box(shape: str, cx: float, cy: float, r: float, points, device: str, frame=None):
    """(row0, col0, mask) of an entity's tiles: the same arithmetic as the dense masks, evaluated only on the bounding box (tiles outside
    it are False in the dense mask: a circle's by distance, a closed polygon's by ray parity), then clipped to the entity's space. The box is
    in the entity's frame (``frame``: the main frame, or the pocket holding its centre)."""
    frame = frame or _entity_frame(shape, cx, cy, points)
    f_col, f_row, f_w, f_h, _, _pocket = frame
    empty = (0, 0, torch.zeros((0, 0), dtype=torch.bool, device=device))
    if shape == "circle":
        (r0, r1), (c0, c1) = _span(cy - r, cy + r, f_row, f_h), _span(cx - r, cx + r, f_col, f_w)
        if r0 >= r1 or c0 >= c1:
            return empty
        grid_y, grid_x = _box_grid(r0, r1, c0, c1, device, f_col, f_row)
        mask = ((grid_x - cx) ** 2 + (grid_y - cy) ** 2).sqrt() < r
        centre = (cx, cy)
    elif shape == "polygon" and points:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        (r0, r1), (c0, c1) = _span(min(ys), max(ys), f_row, f_h), _span(min(xs), max(xs), f_col, f_w)
        if r0 >= r1 or c0 >= c1:
            return empty
        grid_y, grid_x = _box_grid(r0, r1, c0, c1, device, f_col, f_row)
        mask = torch.zeros((r1 - r0, c1 - c0), dtype=torch.bool, device=device)
        n = len(points)
        for i in range(n):
            xi, yi = points[i]
            xj, yj = points[(i + 1) % n]
            mask ^= (((grid_y > min(yi, yj)) & (grid_y <= max(yi, yj)))
                     & (grid_x <= (xj - xi) * (grid_y - yi) / (yj - yi + 1e-9) + xi))
        centre = (sum(xs) / len(xs), sum(ys) / len(ys))
    else:
        return empty
    return r0, c0, _clip_to_space(mask, centre[0], centre[1], r0, c0, frame)


def _box_tiles(box, frame=None) -> list[int]:
    """Ascending flat tile indices of a (row0, col0, mask) box in ``frame`` (default: the main frame)."""
    r0, c0, mask = box
    if mask.numel() == 0:
        return []
    _, _, width, _, base, _ = frame or _main_frame()
    hits = torch.nonzero(mask)
    return (base + (hits[:, 0] + r0) * width + hits[:, 1] + c0).tolist()


def _geo_frame(geo: dict) -> tuple:
    """The frame of a registered entity (its ``pocket`` key, None for the main frame)."""
    pocket = geo.get("pocket")
    return _main_frame() if pocket is None else _pocket_frame(pocket)


def tiles_of(eid: int) -> list[int]:
    """Ascending flat tile indices (of the frame in use) an area entity covers; [] for an unregistered id.  Works in both mask modes."""
    geo = MAP_GEO.get(eid)
    if geo is None:
        return []
    if "tile_box" in geo:
        return _box_tiles(geo["tile_box"], _geo_frame(geo))
    return torch.where(geo["tile_mask"].reshape(-1))[0].tolist()


def tile_mask(eid: int) -> torch.Tensor:
    """The entity's (GRID_H, GRID_W) boolean mask in the frame in use (rebuilt from the box in sparse mode: O(frame), not for ticks)."""
    geo = MAP_GEO[eid]
    if "tile_box" not in geo:
        return geo["tile_mask"]
    r0, c0, sub = geo["tile_box"]
    _, _, width, height, _, _pocket = _geo_frame(geo)
    full = torch.zeros((height, width), dtype=torch.bool, device=sub.device)
    if sub.numel():
        full[r0:r0 + sub.shape[0], c0:c0 + sub.shape[1]] = sub
    return full


def _add_tiles(eid: int, tiles: list[int]) -> None:
    for ti in tiles:
        TILE_TO_ENTITY[ti] = eid


def _remove_tiles(eid: int, tiles: list[int]) -> None:
    for ti in tiles:
        if TILE_TO_ENTITY.get(ti) == eid:
            del TILE_TO_ENTITY[ti]


def _add_to_tile_lookup(eid: int, mask: torch.Tensor) -> None:
    """Add all tiles in mask to TILE_TO_ENTITY mapping for eid."""
    flat    = mask.reshape(-1)
    indices = torch.where(flat)[0].tolist()
    for ti in indices:
        TILE_TO_ENTITY[ti] = eid


def _remove_from_tile_lookup(eid: int, mask: torch.Tensor) -> None:
    """Remove all tiles in mask from TILE_TO_ENTITY if they still point to eid."""
    flat    = mask.reshape(-1)
    indices = torch.where(flat)[0].tolist()
    for ti in indices:
        if TILE_TO_ENTITY.get(ti) == eid:
            del TILE_TO_ENTITY[ti]


# =============================================================================
# PUBLIC API
# =============================================================================

def register_entity(eid: int,
                    shape: str,
                    cx: float, cy: float,
                    r: float = 0.0,
                    points: list[tuple[float, float]] | None = None,
                    device: str = "cpu") -> None:
    """
    Add or fully replace an entity's geometry in MAP_GEO.
    Computes tile_mask and updates TILE_TO_ENTITY.
    Bumps geo_version.

    Call this when:
      - A new entity is born (entity_born in instincts_and_tools.py)
      - A tool changes a natural feature's position or radius (geo_mutate)
    """
    global geo_version

    if _SPARSE:
        frame = _entity_frame(shape, cx, cy, points)
        box = _sparse_box(shape, cx, cy, r, points, device, frame)
        if eid in MAP_GEO:
            _remove_tiles(eid, tiles_of(eid))
        MAP_GEO[eid] = {
            "shape":     shape,
            "cx":        cx,
            "cy":        cy,
            "r":         r,
            "points":    points or [],
            "tile_box":  box,
        }
        if frame[5] is not None:
            MAP_GEO[eid]["pocket"] = frame[5]
        _add_tiles(eid, _box_tiles(box, frame))
        geo_version += 1
        return

    if shape == "circle":
        mask = _compute_circle_mask(cx, cy, r, device)
    elif shape == "polygon" and points:
        mask = _compute_polygon_mask(points, device)
    else:
        mask = torch.zeros((GRID_H, GRID_W), dtype=torch.bool, device=device)
    if shape == "circle":
        mask = _clip_to_space(mask, cx, cy)
    elif shape == "polygon" and points:
        mask = _clip_to_space(mask, sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))

    # Remove old mapping if entity already registered
    if eid in MAP_GEO:
        _remove_from_tile_lookup(eid, MAP_GEO[eid]["tile_mask"])

    MAP_GEO[eid] = {
        "shape":     shape,
        "cx":        cx,
        "cy":        cy,
        "r":         r,
        "points":    points or [],
        "tile_mask": mask,
    }
    _add_to_tile_lookup(eid, mask)
    geo_version += 1


def unregister_entity(eid: int) -> None:
    """
    Remove entity geometry on death or destruction.
    Call this from tools that kill/remove a natural feature entity.
    Mobile entities (animals) do NOT have MAP_GEO entries — skip for them.
    """
    global geo_version
    if eid not in MAP_GEO:
        return
    if "tile_box" in MAP_GEO[eid]:
        _remove_tiles(eid, tiles_of(eid))
    else:
        _remove_from_tile_lookup(eid, MAP_GEO[eid]["tile_mask"])
    del MAP_GEO[eid]
    geo_version += 1


def restore_shapes(shapes: dict, device: str = "cpu") -> None:
    """Snapshot restore for the sparse frame: register saved shape parameters (no masks were saved) and rebuild each box.  Does NOT touch
    TILE_TO_ENTITY (the saved tile owners, including last-writer order, are restored verbatim by the caller)."""
    for eid, geo in shapes.items():
        entry = {k: v for k, v in geo.items() if k != "tile_box"}
        entry["tile_box"] = _sparse_box(entry["shape"], entry["cx"], entry["cy"], entry["r"], entry["points"], device, _geo_frame(entry))
        MAP_GEO[eid] = entry


def shift_entities(eids, dx: float, dy: float, device: str = "cpu") -> int:
    """Window re-base (sparse frame only): the local origin moved, so every listed entity moves by (dx, dy) px in the fixed tile frame. Shape
    parameters shift, each box is rebuilt, and the tiles each moved entity owned are re-keyed in their previous order (last-writer order among
    the moved entities is kept; unmoved entities keep their tiles). dx, dy must be whole tiles. Returns the number of entities moved."""
    global geo_version
    if not _SPARSE:
        raise RuntimeError("map_geo.shift_entities: only the sparse window frame re-bases")
    dcol, drow = dx / TILE_SIZE, dy / TILE_SIZE
    if dcol != int(dcol) or drow != int(drow):
        raise ValueError("map_geo.shift_entities: the shift must be a whole number of tiles")
    dcol, drow = int(dcol), int(drow)
    moved = {eid for eid in eids if eid in MAP_GEO and MAP_GEO[eid].get("pocket") is None}
    if not moved or (dx == 0 and dy == 0):
        return 0
    owned = [(ti, owner) for ti, owner in TILE_TO_ENTITY.items() if owner in moved]
    for ti, _ in owned:
        del TILE_TO_ENTITY[ti]
    for eid in moved:
        geo = MAP_GEO[eid]
        geo["cx"] = geo["cx"] + dx
        geo["cy"] = geo["cy"] + dy
        geo["points"] = [(p[0] + dx, p[1] + dy) for p in geo["points"]]
        geo["tile_box"] = _sparse_box(geo["shape"], geo["cx"], geo["cy"], geo["r"], geo["points"], device, _main_frame())
    for ti, owner in owned:
        row, col = divmod(ti, GRID_W)
        row, col = row + drow, col + dcol
        if 0 <= row < GRID_H and 0 <= col < GRID_W:
            TILE_TO_ENTITY[row * GRID_W + col] = owner
    for eid in sorted(moved):                                  # tiles that were clipped by the frame edge before and are inside now
        for ti in tiles_of(eid):
            TILE_TO_ENTITY.setdefault(ti, eid)
    geo_version += 1
    return len(moved)


def geo_mutate(eid: int,
               cx: float | None = None,
               cy: float | None = None,
               r:  float | None = None,
               points: list | None = None,
               device: str = "cpu") -> None:
    """
    Update an entity's geometry (e.g. lake shrinks after drought).
    Only mutates the fields you pass — others inherit from existing entry.
    Recomputes tile_mask atomically and bumps geo_version.
    """
    if eid not in MAP_GEO:
        return
    geo    = MAP_GEO[eid]
    new_cx = cx     if cx     is not None else geo["cx"]
    new_cy = cy     if cy     is not None else geo["cy"]
    new_r  = r      if r      is not None else geo["r"]
    new_pts = points if points is not None else geo["points"]
    register_entity(eid, geo["shape"], new_cx, new_cy, new_r, new_pts, device)


def entity_at(ax: float, ay: float) -> int:
    """
    Return entity_id of the area entity covering pixel position (ax, ay).
    Returns -1 if no entity covers that tile.
    O(1) — pure dict lookup.
    """
    frame = _frame_at(ax, ay, strict=True)
    if frame is None:
        return -1
    return TILE_TO_ENTITY.get(_px_to_tile_idx(ax, ay, frame), -1)


def _radius_candidates(cx, cy, radius, m_tensor, col_x, col_y, max_entities) -> list[int]:
    """MAP_GEO ids (in MAP_GEO order) that can possibly lie within ``radius`` of (cx, cy).

    A vectorised pre-filter in front of the exact per-row test in ``entities_in_radius``: one gather and one squared
    distance in float64 instead of four scalar tensor reads per entity. The exact test still runs on every survivor, so
    the result is identical; this only has to be a SUPERSET of the exact result. The squared distance differs from the
    Python ``((dx)**2 + (dy)**2) ** 0.5`` by a few units in the last place (about 1e-16 relative), and the limit carries a
    1e-9 relative plus 1e-9 absolute margin, so no row the exact test accepts can be dropped. Non-finite inputs skip the
    pre-filter (every id is returned) so NaN/inf semantics stay those of the exact loop.
    """
    ids = list(MAP_GEO.keys())
    if len(ids) < 8:
        return ids
    try:
        qx, qy, qr = float(cx), float(cy), float(radius)
    except (TypeError, ValueError):
        return ids
    if not (math.isfinite(qx) and math.isfinite(qy) and math.isfinite(qr)):
        return ids
    live = [eid for eid in ids if eid < max_entities]
    if not live:
        return ids
    index = torch.tensor(live, dtype=torch.long)
    rows = m_tensor.index_select(0, index.to(m_tensor.device))
    ex = rows[:, col_x].double().cpu()
    ey = rows[:, col_y].double().cpu()
    if not (bool(torch.isfinite(ex).all()) and bool(torch.isfinite(ey).all())):
        return ids
    d2 = (ex - qx) ** 2 + (ey - qy) ** 2
    limit = (max(qr, 0.0) * (1.0 + 1e-9) + 1e-9) ** 2
    keep = (d2 <= limit).tolist()
    return [eid for eid, ok in zip(live, keep) if ok]


def geo_ids_of_types(m_tensor: "torch.Tensor", types: set | None, max_entities: int) -> list[int]:
    """MAP_GEO ids below ``max_entities``, in MAP_GEO order, whose ``M_TYPE`` (as ``int``) is in ``types`` (all of them when None).

    R66-PACE-2: the candidates of ``perception.queries.nearest_geo_entity_possible``, read in one gather. A superset is safe there, so a row
    whose type is not finite is kept, and a negative id (never registered by the game) turns the type filter off.
    """
    from genesis_config import M_TYPE as _MT
    live = [eid for eid in MAP_GEO.keys() if eid < max_entities]
    if not live or types is None or min(live) < 0:
        return live
    index = torch.tensor(live, dtype=torch.long, device=m_tensor.device)
    kinds = m_tensor[:, _MT].index_select(0, index).double().cpu()
    wanted = torch.tensor(sorted(float(t) for t in types), dtype=torch.float64)
    keep = (torch.isin(torch.trunc(kinds), wanted) | ~torch.isfinite(kinds)).tolist()
    return [eid for eid, ok in zip(live, keep) if ok]


def entities_in_radius(cx: float, cy: float, radius: float,
                        m_tensor: "torch.Tensor",
                        m_type_filter: set | None = None) -> list[int]:
    """
    Return list of entity_ids (MAP_GEO area entities only) whose centre
    (CX, CY in m_tensor) is within radius px of (cx, cy).
    Optionally filter by M_TYPE set.
    Used by tools (wildfire ignition, earthquake, flood) — not the tick loop.
    """
    from genesis_config import CX as _CX, CY as _CY, M_TYPE as _MT, M_SPACE as _MS, MAX_ENTITIES
    try:
        from harness.spaces import point_space
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness.spaces import point_space
    want_space = point_space(cx, cy)          # EDEN_SPACES: only rows of the query point's space; None (no filter) otherwise
    results = []
    candidates = _radius_candidates(cx, cy, radius, m_tensor, _CX, _CY, MAX_ENTITIES)
    for eid in candidates:
        if eid >= MAX_ENTITIES:
            continue
        if want_space is not None and int(m_tensor[eid, _MS]) != want_space:
            continue
        ecx = float(m_tensor[eid, _CX])
        ecy = float(m_tensor[eid, _CY])
        dist = ((ecx - cx) ** 2 + (ecy - cy) ** 2) ** 0.5
        if dist > radius:
            continue
        if m_type_filter is not None:
            et = int(m_tensor[eid, _MT])
            if et not in m_type_filter:
                continue
        results.append(eid)
    return results


def background_tile_types(m_tensor: "torch.Tensor",
                           default_type: int = 0) -> torch.Tensor:
    """
    Build a (GRID_H, GRID_W) int tensor assigning each background tile
    the M_TYPE of the entity that covers it (or default_type = 0 for sea/void).
    Used by the viewer to colour the background and by genesis to write
    the initial map JSON.
    Runs once at snapshot time — not in the tick loop.
    """
    from genesis_config import M_TYPE as _MT
    grid = torch.full((GRID_H, GRID_W), default_type, dtype=torch.long)
    # Lower entity_ids = older / lower priority — iterate in ascending order
    # so structures (placed last, higher id) overwrite natural features
    for eid in sorted(MAP_GEO.keys()):
        if MAP_GEO[eid].get("pocket") is not None:    # a pocket entity has its own small frame, not part of the main background
            continue
        mask = tile_mask(eid)                         # (GRID_H, GRID_W) bool
        et   = int(m_tensor[eid, _MT])
        grid[mask] = et
    return grid


def get_geo_json() -> dict:
    """
    Serialise MAP_GEO to a JSON-safe dict for the /get_map endpoint.
    Viewer uses this to draw entity circles and colour the background.
    tile_mask tensors are NOT included — too large; viewer derives coloring
    from entity positions + radii itself.
    """
    entities = []
    for eid, geo in MAP_GEO.items():
        entities.append({
            "id":     eid,
            "shape":  geo["shape"],
            "cx":     round(geo["cx"], 1),
            "cy":     round(geo["cy"], 1),
            "r":      round(geo["r"],  1),
            "points": [[round(p[0], 1), round(p[1], 1)] for p in geo["points"]],
        })
    return {"geo_version": geo_version, "entities": entities}