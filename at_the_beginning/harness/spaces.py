"""1008 WS-D P3 (D1, Option L): spaces as identities over the one layout frame.

A *space* is one registered map of the active authored world: the primary map is space 0 (the overworld), every secondary map is
space 1, 2, ... in registration order (``map_contract.placed_group`` order, which follows ``EDEN_MAP_FILES``). The engine keeps each
interior at its own disjoint region of the tensor coordinate frame (its layout origin, ``EDEN_MAP_ORIGINS``); the space adds an
identity, a column on every row (``M_SPACE`` / ``H_SPACE``), and the proximity masks of P2 turn the isolation distance into a guarantee.
Everything here is derived from the registered maps; nothing is stored, so a restart gives the same ids for the same registration order.

``space_at(engine, x, y)`` is the pure resolver: the space whose registered rectangle contains the point (closed rectangles; the
lowest id wins at a shared edge, which ``validate_placement`` makes impossible anyway), else 0. A legacy world (no authored maps) is
space 0 everywhere and has an empty table. See ``1008_spaces_p3_gap.md``.
"""
from __future__ import annotations

import os
from typing import Optional

try:
    from systems.movement.map_contract import placed_group
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.movement.map_contract import placed_group

OVERWORLD = 0
FLAG_REQUIRES = "EDEN_PERCEPTION_BOUNDED"


class SpaceConfigError(RuntimeError):
    """EDEN_SPACES is on but a flag it depends on is not."""


def check_flags() -> None:
    """Raise ``SpaceConfigError`` naming the missing flag when EDEN_SPACES=1 without EDEN_PERCEPTION_BOUNDED=1 (design section 2)."""
    from .numerics import SPACES_FLAG, spaces_enabled
    if not spaces_enabled():
        return
    try:
        from runtime.common import perception_bounded
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.runtime.common import perception_bounded
    if not perception_bounded():
        raise SpaceConfigError(f"{SPACES_FLAG}=1 requires {FLAG_REQUIRES}=1: without bounded perception a resident in an interior "
                               f"would still scan the whole world. Set {FLAG_REQUIRES}=1 or unset {SPACES_FLAG}.")


def check_window_flags() -> None:
    """Raise ``SpaceConfigError`` naming the first missing flag when EDEN_WINDOW=1: it needs EDEN_SPACES (and through it EDEN_PERCEPTION_BOUNDED)
    and EDEN_MAP_RESOURCES (generated chunk entities become rows through the map-resource loader)."""
    from .numerics import WINDOW_FLAG, spaces_enabled, window_enabled
    if not window_enabled():
        return
    if not spaces_enabled():
        raise SpaceConfigError(f"{WINDOW_FLAG}=1 requires EDEN_SPACES=1 (and EDEN_PERCEPTION_BOUNDED=1): interiors cannot live in the sliding frame "
                               f"as plain map regions. Set them or unset {WINDOW_FLAG}.")
    if os.environ.get("EDEN_MAP_RESOURCES", "") != "1":
        raise SpaceConfigError(f"{WINDOW_FLAG}=1 requires EDEN_MAP_RESOURCES=1: generated chunk entities become rows through the map-resource loader. "
                               f"Set it or unset {WINDOW_FLAG}.")


def _group(engine):
    return placed_group(getattr(engine, "_map_name", None))


def space_table(engine) -> list:
    """[{"space", "map_id", "kind", "bounds", "origin", "revision", "sha256"}, ...] in space-id order; [] for a legacy world.
    ``bounds`` and ``origin`` are in the layout frame (world units). ``revision`` / ``sha256`` are None when the map file is not served."""
    rows = []
    for index, entry in enumerate(_group(engine)):
        info = entry.get("info") or {}
        rows.append({"space": index, "map_id": info.get("map_id"), "kind": "overworld" if index == OVERWORLD else "interior",
                     "bounds": list(entry["bounds"]), "origin": list(entry["origin"]),
                     "revision": info.get("revision"), "sha256": info.get("sha256")})
        if os.environ.get("EDEN_WINDOW", "") == "1":      # P5: the registration origin stays; window-local position = origin + window_shift
            rows[-1]["window_shift"] = list(entry.get("window_shift", [0.0, 0.0]))
    return rows


def space_of_map(engine, map_id: str) -> Optional[int]:
    """The space id of a registered map id, or None."""
    for row in space_table(engine):
        if row["map_id"] == map_id:
            return row["space"]
    return None


def map_of_space(engine, space: int) -> Optional[str]:
    """The map id of a space id, or None."""
    table = space_table(engine)
    return table[space]["map_id"] if isinstance(space, int) and 0 <= space < len(table) else None


def rectangles(engine) -> list:
    """[(space, min_x, min_y, max_x, max_y), ...] for the interiors only (the overworld is the fallback). One list per tick is enough."""
    return [(i, *entry["bounds"]) for i, entry in enumerate(_group(engine)) if i != OVERWORLD]


def resolve(rects, x: float, y: float) -> int:
    """``space_at`` against a precomputed ``rectangles`` list (the per-tick refresh uses this so the group is read once)."""
    for space, x0, y0, x1, y1 in rects:
        if x0 <= x <= x1 and y0 <= y <= y1:
            return space
    return OVERWORLD


def space_at(engine, x: float, y: float) -> int:
    """The space containing the layout point (x, y): an interior whose rectangle contains it (closed), else the overworld (0)."""
    return resolve(rectangles(engine), float(x), float(y))


# -- keeping the columns current ---------------------------------------------------------------------------------------------
def _refresh_column(tensor, rects, space_col: int, x_col: int, y_col: int) -> int:
    """Set ``tensor[:, space_col]`` to the space of each row's position; returns the number of rows changed. Compared in float64 so the
    result equals ``space_at`` on ``float(x)`` of the stored float32 values, boundary points included."""
    import torch
    x, y = tensor[:, x_col].double(), tensor[:, y_col].double()
    new = torch.zeros_like(x)
    for space, x0, y0, x1, y1 in reversed(rects):             # highest id first, so the lowest id wins an overlap
        new = torch.where((x >= x0) & (x <= x1) & (y >= y0) & (y <= y1), float(space), new)
    new = new.to(tensor.dtype)
    changed = int((tensor[:, space_col] != new).sum())
    if changed:
        tensor[:, space_col] = new
    return changed


FULL_REFRESH_EVERY = 20       # ticks between unconditional refreshes of the entity column in gated mode


def _entity_signature(engine) -> tuple:
    """What changes when an entity row appears, disappears or its geometry changes (the same events that force a map refresh)."""
    try:
        import map_geo
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import map_geo
    return (int(engine._entity_count_ref[0]), int(map_geo.geo_version), bool(getattr(engine, "_force_map_refresh", False)))


def refresh(engine, gated: bool = False) -> int:
    """Recompute ``H_SPACE`` and ``M_SPACE`` of every row from its position (no-op, returns 0, with EDEN_SPACES off). It makes both
    columns correct for every mover (teleport powers, god commands, spawns, rows created inside an interior). Returns the rows changed.

    ``gated=True`` (the per-tick hook): the human column is refreshed every call; the entity column only when ``(entity count, geo_version,
    _force_map_refresh)`` differs from the previous gated call, and unconditionally every ``FULL_REFRESH_EVERY`` ticks as a safety net.
    Entity rows do not move into an interior (walls), so between those events their space cannot change. ``gated=False`` refreshes both."""
    from .numerics import spaces_enabled
    if not spaces_enabled():
        return 0
    try:
        import genesis_config as cfg
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import genesis_config as cfg
    bind(engine)
    rects = rectangles(engine)
    state = engine.state
    changed = _refresh_column(state.h_tensor, rects, cfg.H_SPACE, cfg.X, cfg.Y)
    if gated:
        signature = _entity_signature(engine)
        if signature == getattr(engine, "_spaces_entity_signature", None) and int(engine.tick) % FULL_REFRESH_EVERY != 0:
            return changed
        engine._spaces_entity_signature = signature
    return changed + _refresh_column(state.m_tensor, rects, cfg.M_SPACE, cfg.CX, cfg.CY)


# -- the space of a query point (Option L) -----------------------------------------------------------------------------------
# Interiors sit at disjoint layout coordinates, but a large query radius or a large area entity still reaches across the gap between
# two maps (the leak test shows both). Geometry code therefore asks which space a *point* is in and drops rows and tiles of other spaces.
_bound_name: Optional[str] = None


def bind(engine) -> None:
    """Remember which authored world the point lookups use (set at genesis and by every refresh); without it the sole registered primary map is used."""
    global _bound_name
    _bound_name = getattr(engine, "_map_name", None)


def _active_rectangles() -> list:
    if _bound_name is not None:
        group = placed_group(_bound_name)
        if group:
            return [(i, *entry["bounds"]) for i, entry in enumerate(group) if i != OVERWORLD]
    try:
        from systems.movement.map_contract import MAP_CONTRACTS
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.systems.movement.map_contract import MAP_CONTRACTS
    primaries = [name for name, entry in MAP_CONTRACTS.items() if entry.get("world") is None]
    if len(primaries) != 1:
        return []
    return [(i, *entry["bounds"]) for i, entry in enumerate(placed_group(primaries[0])) if i != OVERWORLD]


def point_space(x: float, y: float) -> Optional[int]:
    """The space of a layout point for geometry code, or None when EDEN_SPACES is off or no authored world is registered
    (None means: do not filter, the legacy behaviour; also None when the world has no interior)."""
    from .numerics import spaces_enabled
    if not spaces_enabled():
        return None
    rects = _active_rectangles()
    return resolve(rects, float(x), float(y)) if rects else None


def clip_tile_mask(mask, x: float, y: float, tile_size: float, row0: int = 0, col0: int = 0):
    """Restrict a boolean (rows, cols) tile mask of an area entity centred at (x, y) to the tiles of that point's space: an interior
    entity keeps only tiles inside its rectangle, an overworld entity loses the tiles inside every interior rectangle. Returns the mask
    unchanged when spaces are off or no interior is registered.  ``row0`` / ``col0`` are the world tile coordinates of the mask's
    top-left tile (a sparse bounding box; 0, 0 for a full-world mask)."""
    space = point_space(x, y)
    if space is None:
        return mask
    rects = _active_rectangles()
    if not rects:
        return mask
    import torch
    rows, cols = mask.shape
    gx = ((torch.arange(cols, dtype=torch.float64, device=mask.device) + col0) * tile_size + tile_size / 2).reshape(1, cols)
    gy = ((torch.arange(rows, dtype=torch.float64, device=mask.device) + row0) * tile_size + tile_size / 2).reshape(rows, 1)
    allowed = torch.zeros((rows, cols), dtype=torch.bool, device=mask.device)
    for rect_space, x0, y0, x1, y1 in rects:
        if rect_space == space:
            allowed |= (gx >= x0) & (gx <= x1) & (gy >= y0) & (gy <= y1)
    if space == OVERWORLD:
        inside_any = torch.zeros((rows, cols), dtype=torch.bool, device=mask.device)
        for _, x0, y0, x1, y1 in rects:
            inside_any |= (gx >= x0) & (gx <= x1) & (gy >= y0) & (gy <= y1)
        allowed = ~inside_any
    return mask & allowed
