"""Version-one ground-plane contract; coordinates map to Godot X/Z metres."""
import hashlib
import json

import torch
import genesis_config as cfg
from .map_contract import compose_group, get_map_contract, wall_owners

RADIUS = 0.35


def wall_boxes(m_tensor, entity_ids=None):
    """One wall definition for replication, movement and combat queries."""
    walls = []
    active = (m_tensor[:, cfg.M_TYPE] == cfg.M_WALL) & (m_tensor[:, cfg.M_HP] > 0)
    for slot in active.nonzero(as_tuple=False).flatten().tolist():
        uid = entity_ids[slot] if entity_ids is not None else str(slot)
        if entity_ids is not None and not uid:
            continue
        row = m_tensor[slot]
        if int(row[cfg.M_TYPE]) != cfg.M_WALL or float(row[cfg.M_HP]) <= 0:
            continue
        x, y, radius = float(row[cfg.CX]), float(row[cfg.CY]), max(float(row[cfg.SCALE]), 2.0)
        walls.append({"id": uid, "min": [x-radius, y-.6], "max": [x+radius, y+.6], "height": 2.4})
    return walls


def segment_blocked(start, end, boxes):
    """Closed segment against ground-plane wall boxes, including contact/embedding."""
    for box in boxes:
        enter, leave = 0.0, 1.0
        for axis in range(2):
            delta = end[axis] - start[axis]
            lo, hi = box["min"][axis], box["max"][axis]
            if abs(delta) < 1e-9:
                if not lo <= start[axis] <= hi:
                    break
                continue
            first, last = sorted(((lo - start[axis]) / delta, (hi - start[axis]) / delta))
            enter, leave = max(enter, first), min(leave, last)
            if enter > leave:
                break
        else:
            return True
    return False


def _window_part(engine):
    """EDEN_WINDOW=1: the streaming window's wall boxes (integrated chunks plus void boxes), bounds and cached revision, else None."""
    from harness.numerics import window_enabled
    if window_enabled() or getattr(engine, "_window", None) is not None:
        return getattr(engine, "_window_contract", None)
    return None


def _with_window(window, boxes, bounds, hashed, extras=None):
    """Append the window's boxes, widen the bounds to cover its chunks, and hash (static part, window revision): the big box list is not re-hashed per call."""
    if window is None:
        return boxes, bounds, hashed
    if window["bounds"] is not None:
        bounds = [min(bounds[0], window["bounds"][0]), min(bounds[1], window["bounds"][1]),
                  max(bounds[2], window["bounds"][2]), max(bounds[3], window["bounds"][3])]
    return boxes + window["boxes"], bounds, {"static": hashed, "window": window["revision"], "bounds": bounds}


def _compose(engine):
    """(boxes, actor_radius, bounds, hash_input, override). override is None for every legacy map."""
    walls = wall_boxes(engine.state.m_tensor, engine._entity_uid_by_slot)
    bounds = [0.0, 0.0, float(cfg.MAP_WIDTH), float(cfg.MAP_HEIGHT)]
    group = compose_group(getattr(engine, "_map_name", None))
    window = _window_part(engine)
    if group is None:
        boxes, bounds, hashed = _with_window(window, walls, bounds, walls)
        return boxes, RADIUS, bounds, hashed, None
    override = group["primary"]
    radius, map_bounds = group["actor_radius"], list(group["bounds"])  # bounds = union of the placed maps
    # Radius and bounds enter the hash only when they differ from the legacy values.
    extras = {}
    if radius != RADIUS:
        extras["actor_radius"] = radius
    if map_bounds != bounds:
        extras["bounds"] = map_bounds
    boxes = group["boxes"] + walls  # placed maps' walls, containment slabs, then live tensor walls
    hashed = {"boxes": boxes, **extras} if extras else boxes
    boxes, map_bounds, hashed = _with_window(window, boxes, map_bounds, hashed)
    return boxes, radius, map_bounds, hashed, override


def map_wall_boxes(engine):
    """All live wall boxes when a registered map applies, else None (callers keep their legacy path)."""
    boxes, _, _, _, override = _compose(engine)
    return None if override is None else boxes


def map_wall_boxes_ignoring(engine, entity_id):
    """``map_wall_boxes`` without the footprint box(es) owned by ``entity_id``; None on legacy maps.

    For reach/interaction checks toward a map entity, whose own wall must not block the actor from touching it.
    """
    boxes = map_wall_boxes(engine)
    if boxes is None:
        return None
    owners = wall_owners(getattr(engine, "_map_name", None))
    return [box for box in boxes if owners.get(box["id"]) != entity_id]


def world_contract(engine):
    walls, radius, bounds, hashed, override = _compose(engine)
    windowed = isinstance(hashed, dict) and "window" in hashed   # EDEN_WINDOW: (static part, window revision, bounds), see _with_window
    if windowed:                                                  # the static part is hashed once; the revision stamps it with the window's
        static = hashlib.sha256(json.dumps(hashed["static"], sort_keys=True).encode()).hexdigest()[:16]
        revision = hashlib.sha256(json.dumps({**hashed, "static": static}, sort_keys=True).encode()).hexdigest()[:16]
    else:
        revision = hashlib.sha256(json.dumps(hashed, sort_keys=True).encode()).hexdigest()[:16]
    contract = {"version": 1, "revision": revision, "world_epoch": engine.world_epoch,
                "units_per_meter": 1.0, "surface_id": "ground", "height": 0.0,
                "actor_radius": radius, "bounds": bounds,
                "walk_speed": float(cfg.MOVE_STEP * cfg.TICK_RATE_HZ), "sprint_multiplier": 1.5,
                "boxes": walls}
    if windowed:          # additive keys, window mode only: what a mover needs to tell "a chunk was integrated" from "the walls changed"
        contract.update(static_revision=static, window_revision=hashed["window"])
    info = None if override is None else override.get("info")
    if info is not None:  # additive keys, authored maps only; "revision" above stays the wall-hash string
        contract.update(map_id=info["map_id"], map_revision=info["revision"], units_per_tile=info["units_per_tile"])
    return contract


def is_standable_point(point, contract):
    """True if an actor centre at ``point`` is inside the bounds clamp and not embedded in any inflated box.

    Mirrors ``slide``: an embedded start never moves, so a spawn or teleport target must pass this.
    """
    radius = contract["actor_radius"]
    x, y = point
    bounds = contract["bounds"]
    if not (bounds[0] + radius <= x <= bounds[2] - radius and bounds[1] + radius <= y <= bounds[3] - radius):
        return False
    return not any(b["min"][0] - radius + 0.0001 < x < b["max"][0] + radius - 0.0001
                   and b["min"][1] - radius + 0.0001 < y < b["max"][1] + radius - 0.0001 for b in contract["boxes"])


def snap_to_standable(point, contract, max_steps=16):
    """Nearest standable point to ``point`` (returned unchanged if already standable), or None to reject.

    Clamps into the bounds, then repeatedly pushes the point out of the inflated box that contains it through
    the nearest face (plus a 0.001 margin). Gives up after ``max_steps`` pushes (walled-in pockets).
    """
    radius = contract["actor_radius"]
    bounds = contract["bounds"]
    margin = 0.001
    x = min(max(float(point[0]), bounds[0] + radius), bounds[2] - radius)
    y = min(max(float(point[1]), bounds[1] + radius), bounds[3] - radius)
    for _ in range(max_steps):
        if is_standable_point((x, y), contract):
            return (point[0], point[1]) if (x, y) == (float(point[0]), float(point[1])) else (x, y)
        container = next((b for b in contract["boxes"]
                          if b["min"][0] - radius + 0.0001 < x < b["max"][0] + radius - 0.0001
                          and b["min"][1] - radius + 0.0001 < y < b["max"][1] + radius - 0.0001), None)
        if container is None:  # the bounds clamp is the only problem and cannot be fixed by a push
            return None
        lo_x, hi_x = container["min"][0] - radius - margin, container["max"][0] + radius + margin
        lo_y, hi_y = container["min"][1] - radius - margin, container["max"][1] + radius + margin
        exits = sorted(((abs(x - lo_x), (lo_x, y)), (abs(hi_x - x), (hi_x, y)), (abs(y - lo_y), (x, lo_y)),
                        (abs(hi_y - y), (x, hi_y))), key=lambda item: item[0])
        in_bounds = [e for _, e in exits if bounds[0] + radius <= e[0] <= bounds[2] - radius
                     and bounds[1] + radius <= e[1] <= bounds[3] - radius]
        if not in_bounds:
            return None
        # Prefer an exit that is standable right away; otherwise take the nearest and keep pushing.
        x, y = next((e for e in in_bounds if is_standable_point(e, contract)), in_bounds[0])
    return None


def standable_spawn_point(engine, x, y):
    """Where a spawned or teleported actor may start: (x, y) unchanged on legacy maps; on an authored map the
    nearest standable point, or None if there is none (the caller must reject the spawn)."""
    override = get_map_contract(getattr(engine, "_map_name", None))
    if override is None:
        return (x, y)
    return snap_to_standable((x, y), world_contract(engine))


def starter_storage_spot(engine):
    """Where the engine's starter storage case goes on an authored map: a standable point at the first
    map-provided storage entity, or None (skip the case). Only call when a map contract is registered."""
    from .map_contract import STORAGE_ENTITY_KINDS
    override = get_map_contract(getattr(engine, "_map_name", None))
    storage = next((e for e in override["entities"] if e["interactive"] and e["kind"] in STORAGE_ENTITY_KINDS), None)
    if storage is None:
        return None
    return snap_to_standable(tuple(storage["position"]), world_contract(engine))


_SWEEP_CACHE = [None, 0, None, None]       # [boxes list, its length, radius, tensor of inflated boxes]: one entry, keyed by list identity
_SWEEP_MARGIN = 1e-3                        # the comparisons in slide use 1e-4; ten times more cannot drop a box that matters
_SWEEP_MIN_BOXES = 48                       # below this the plain comprehension is as fast as the gather


def _inflated(box, radius):
    return (box["min"][0]-radius, box["min"][1]-radius, box["max"][0]+radius, box["max"][1]+radius)


def is_void_box(box):
    """True if ``box`` represents a streaming window void barrier."""
    return bool(str((box or {}).get("id", "")).startswith("void:"))


def _boxes_near_sweep_with_raw(contract, radius, x, y, nx, ny):
    """The inflated ``(a, b, c, d)`` boxes paired with original contract box dicts, in contract order."""
    raw = contract["boxes"]
    count = len(raw)
    if count < _SWEEP_MIN_BOXES or not all(v - v == 0.0 for v in (x, y, nx, ny, radius)):
        return [(_inflated(b, radius), b) for b in raw]
    cache = _SWEEP_CACHE
    if cache[0] is not raw or cache[1] != count or cache[2] != radius:
        table = torch.tensor([_inflated(b, radius) for b in raw], dtype=torch.float64)
        cache[0], cache[1], cache[2], cache[3] = raw, count, radius, table
    table = cache[3]
    lo_x, hi_x = min(x, nx) - _SWEEP_MARGIN, max(x, nx) + _SWEEP_MARGIN
    lo_y, hi_y = min(y, ny) - _SWEEP_MARGIN, max(y, ny) + _SWEEP_MARGIN
    keep = (table[:, 0] <= hi_x) & (table[:, 2] >= lo_x) & (table[:, 1] <= hi_y) & (table[:, 3] >= lo_y)
    if not bool(torch.isfinite(table).all()):
        return [(_inflated(b, radius), b) for b in raw]
    indices = keep.nonzero(as_tuple=False).flatten().tolist()
    return [(_inflated(raw[i], radius), raw[i]) for i in indices]


def _boxes_near_sweep(contract, radius, x, y, nx, ny):
    """The inflated ``(a, b, c, d)`` boxes of the contract, in contract order, that ``slide`` can possibly touch.

    ``slide`` only reads a box that contains the start, or one whose edge lies between the start and the clamped target on the
    axis it is moving along (and whose other extent contains the start/current coordinate). Every such box therefore overlaps the
    rectangle spanned by the start and the clamped target, and the running ``nx``/``ny`` never leave that rectangle by more than the
    1e-4 tolerances. Boxes that do not overlap it (widened by 1e-3) cannot change a result, so they are dropped here. With many
    boxes (a streaming window) that is a few comparisons in one tensor pass instead of four passes over every box in Python; the
    kept boxes carry exactly the values the plain comprehension produced. Non-finite input, or few boxes, keeps all of them.
    """
    return [inf for inf, _ in _boxes_near_sweep_with_raw(contract, radius, x, y, nx, ny)]


def slide(start, desired, contract, *, diagnostics=False):
    """Sweep a square actor footprint X then Y, preserving tangent movement.

    Each axis sweeps the entire segment; a large displacement cannot tunnel.
    A point already embedded is held for an explicit spawn/depenetration policy.
    Optional diagnostics=True returns ((nx, ny), info_dict) detailing collision selection.
    """
    radius = contract["actor_radius"]
    x, y = start
    bounds = contract["bounds"]
    nx = max(bounds[0]+radius, min(bounds[2]-radius, desired[0]))
    ny = max(bounds[1]+radius, min(bounds[3]-radius, desired[1]))
    pairs = _boxes_near_sweep_with_raw(contract, radius, x, y, nx, ny)
    if any(a+0.0001 < x < c-0.0001 and b+0.0001 < y < d-0.0001 for (a, b, c, d), _ in pairs):
        if diagnostics:
            return (x, y), {
                "blocked": False,
                "void_hit": False,
                "wall_hit": False,
                "embedded": True,
                "blocked_axes": [],
                "void_boxes": [],
                "wall_boxes": [],
            }
        return (x, y)

    # Stationary / non-movement: if desired target equals start position, no displacement was attempted.
    if abs(nx - x) < 1e-9 and abs(ny - y) < 1e-9 and abs(desired[0] - x) < 1e-9 and abs(desired[1] - y) < 1e-9:
        if diagnostics:
            return (nx, ny), {
                "blocked": False,
                "void_hit": False,
                "wall_hit": False,
                "embedded": False,
                "blocked_axes": [],
                "void_boxes": [],
                "wall_boxes": [],
            }
        return (nx, ny)

    orig_nx = nx
    clamped_x_boxes = []
    for (a, b, c, d), _ in pairs:
        if b < y < d:
            if x <= a+0.0001 and nx > a:
                nx = min(nx, a)
            elif x >= c-0.0001 and nx < c:
                nx = max(nx, c)

    if abs(nx - orig_nx) > 1e-9:
        for (a, b, c, d), raw_box in pairs:
            if b < y < d:
                if x <= a+0.0001 and abs(nx - a) < 1e-7:
                    clamped_x_boxes.append(raw_box)
                elif x >= c-0.0001 and abs(nx - c) < 1e-7:
                    clamped_x_boxes.append(raw_box)

    orig_ny = ny
    clamped_y_boxes = []
    for (a, b, c, d), _ in pairs:
        if a < nx < c:
            if y <= b+0.0001 and ny > b:
                ny = min(ny, b)
            elif y >= d-0.0001 and ny < d:
                ny = max(ny, d)

    if abs(ny - orig_ny) > 1e-9:
        for (a, b, c, d), raw_box in pairs:
            if a < nx < c:
                if y <= b+0.0001 and abs(ny - b) < 1e-7:
                    clamped_y_boxes.append(raw_box)
                elif y >= d-0.0001 and abs(ny - d) < 1e-7:
                    clamped_y_boxes.append(raw_box)

    if diagnostics:
        all_contact_boxes = clamped_x_boxes + clamped_y_boxes
        void_contact = [b for b in all_contact_boxes if is_void_box(b)]
        wall_contact = [b for b in all_contact_boxes if not is_void_box(b)]
        blocked_axes = []
        if clamped_x_boxes:
            blocked_axes.append("x")
        if clamped_y_boxes:
            blocked_axes.append("y")
        void_ids = list(dict.fromkeys(b.get("id", "") for b in void_contact))
        wall_ids = list(dict.fromkeys(b.get("id", "") for b in wall_contact))
        info = {
            "blocked": bool(clamped_x_boxes or clamped_y_boxes),
            "void_hit": bool(void_contact),
            "wall_hit": bool(wall_contact),
            "embedded": False,
            "blocked_axes": blocked_axes,
            "void_boxes": void_ids,
            "wall_boxes": wall_ids,
        }
        return (nx, ny), info

    return (nx, ny)


def slide_with_diagnostics(start, desired, contract):
    """Scoped helper returning ((nx, ny), diagnostics_dict) for authoritative telemetry."""
    return slide(start, desired, contract, diagnostics=True)
