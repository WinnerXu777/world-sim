"""Per-map movement-contract overrides, keyed by ``engine._map_name``, with multi-map placement.

Legacy maps are never registered, so ``spatial.world_contract`` keeps its original output for them. An authored
map registers its actor radius, bounds, wall boxes and anchors here; ``world_contract`` merges them into the
contract. The registry is configuration, not save data: ``world_snapshot.ENGINE_FIELDS`` is unaffected, and a
restored world re-derives its contract from the persisted ``_map_name`` (restore refuses a map that is not
registered, see ``persistence.world_snapshot``).

Placement: the *primary* map (named by ``engine._map_name``) plus any *secondary* maps registered with
``world=<primary name>`` share one world. Each map sits at a backend-assigned origin (world = origin + local).
Placed rectangles must fit the tensor world (``cfg.MAP_WIDTH x MAP_HEIGHT``), must not overlap, must be more
than ``ISOLATION_DISTANCE`` apart (residents perceive entities within 220 units), and must share one actor
radius and one id namespace. The contract's bounds are the union rectangle; generated blocking *slabs* fill the
space between rectangles so an actor can never slide out of the map it is in.

Configuration: ``EDEN_MAP_FILES`` holds map JSON paths separated by ``os.pathsep``; the first is the primary,
registered under its ``map_id``. ``EDEN_MAP_ORIGINS`` is a JSON object (or a path to a JSON file) mapping
``map_id`` to ``[x, y]``; the primary defaults to ``[0, 0]`` and every other map must be listed. Unset or empty
``EDEN_MAP_FILES`` means no overrides. Each file is read once in binary mode; the bytes are hashed and served
unchanged by ``GET /map_file/{map_id}``.
"""
import hashlib
import json
import math
import os
from copy import deepcopy

ENV_MAP_FILES = "EDEN_MAP_FILES"
ENV_MAP_ORIGINS = "EDEN_MAP_ORIGINS"
ISOLATION_DISTANCE = 220.0
MAP_CONTRACTS = {}


def _finite(values):
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def register_map_contract(name, actor_radius, bounds, boxes, *, anchors=(), origin=(0.0, 0.0), info=None, raw=None,
                          world=None, ids=(), entities=(), wall_owners=None, portals=()):
    """Register (or replace) the override for ``name``. Inputs are validated and copied.

    ``bounds``, ``boxes`` and ``anchors`` are in world units (already shifted by ``origin``). ``info`` (map
    metadata for the wire block) and ``raw`` (exact file bytes) are optional; without ``raw`` the map is not
    served. ``world`` names the primary map a secondary map is placed with (None for a primary). ``ids`` are the
    backend ids the map defines, used to check that placed maps do not collide.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("map name must be a non-empty string")
    if not (_finite([actor_radius]) and actor_radius > 0):
        raise ValueError("actor_radius must be a finite number > 0")
    if not (len(bounds) == 4 and _finite(bounds) and bounds[0] < bounds[2] and bounds[1] < bounds[3]):
        raise ValueError("bounds must be finite [min_x, min_y, max_x, max_y] with min < max")
    if not (len(origin) == 2 and _finite(origin)):
        raise ValueError("origin must be a finite [x, y]")
    copied = []
    for box in boxes:
        if not (isinstance(box.get("id"), str) and len(box["min"]) == 2 and len(box["max"]) == 2
                and _finite([*box["min"], *box["max"]])):
            raise ValueError(f"invalid wall box {box!r}")
        copied.append({"id": box["id"], "min": [float(v) for v in box["min"]], "max": [float(v) for v in box["max"]],
                       "height": float(box.get("height", 2.4))})
    copied_anchors = []
    for anchor in anchors:
        if not (isinstance(anchor.get("id"), str) and len(anchor["position"]) == 2 and _finite(anchor["position"])):
            raise ValueError(f"invalid anchor {anchor!r}")
        item = {"id": anchor["id"], "kind": anchor["kind"], "position": [float(v) for v in anchor["position"]]}
        if anchor.get("for_role") is not None:
            item["for_role"] = anchor["for_role"]
        copied_anchors.append(item)
    copied_entities = []
    for entity in entities:
        if not (isinstance(entity.get("id"), str) and len(entity["position"]) == 2 and _finite(entity["position"])):
            raise ValueError(f"invalid entity {entity!r}")
        item = {"id": entity["id"], "kind": entity["kind"], "interactive": bool(entity["interactive"]),
                "position": [float(v) for v in entity["position"]]}
        if entity.get("interact_radius") is not None:
            item["interact_radius"] = float(entity["interact_radius"])
        if entity.get("resource") is not None:                          # G-005: validated by world_map.resources
            item["resource"] = deepcopy(entity["resource"])
        copied_entities.append(item)
    MAP_CONTRACTS[name] = {"actor_radius": float(actor_radius), "bounds": [float(v) for v in bounds], "boxes": copied,
                           "anchors": copied_anchors, "origin": [float(v) for v in origin],
                           "info": deepcopy(info), "raw": None if raw is None else bytes(raw),
                           "world": world, "ids": sorted(set(ids)), "entities": copied_entities,
                           "wall_owners": dict(wall_owners or {}),
                           "portals": [dict(p) for p in portals]}


def unregister_map_contract(name):
    """Remove one registered map and nothing else."""
    MAP_CONTRACTS.pop(name, None)


def clear_map_contracts():
    """Remove every registered map (tests and re-registration)."""
    MAP_CONTRACTS.clear()


def get_map_contract(name):
    """The registered override for ``name`` (read-only by convention), or None for legacy/unknown maps."""
    return MAP_CONTRACTS.get(name) if isinstance(name, str) else None


def wall_owners(name):
    """{wall id: owner entity id} for the walls of the world whose primary map is ``name`` ({} on legacy maps).

    A wall with an owner is the footprint of that entity; reach and line-of-sight checks toward the entity should
    ignore its own footprint (see ``spatial.map_wall_boxes_ignoring``).
    """
    return {wall_id: owner for entry in placed_group(name) for wall_id, owner in entry.get("wall_owners", {}).items()}


def map_entity(name, entity_id):
    """The registered entity dict (world coordinates; kind, interactive, interact_radius) or None."""
    for entry in placed_group(name):
        for entity in entry.get("entities", ()):
            if entity["id"] == entity_id:
                return deepcopy(entity)
    return None


def find_portal(name, portal_id):
    """Resolve a portal of the world whose primary map is ``name``, in world coordinates, or None.

    Returns ``{"portal", "from", "to", "to_loaded"}``: ``to_loaded`` is False when the target map is not placed in
    this world or lacks the target anchor.
    """
    group = placed_group(name)
    maps = {e["info"]["map_id"]: e for e in group if e.get("info")}
    for entry in group:
        for portal in entry.get("portals", ()):
            if portal["id"] != portal_id:
                continue
            source = next((a for a in entry["anchors"] if a["id"] == portal["from_anchor"]), None)
            if source is None:
                return None
            target_entry = maps.get(portal["to_map"])
            target = None if target_entry is None else next(
                (a for a in target_entry["anchors"] if a["id"] == portal["to_anchor"]), None)
            return {"portal": dict(portal), "from": list(source["position"]),
                    "to": None if target is None else list(target["position"]), "to_loaded": target is not None}
    return None


def _copy_box(box):
    """Fresh copy equal to ``deepcopy(box)``: scalars are shared (immutable), every list/dict value is copied."""
    return {key: (list(value) if type(value) is list and all(type(v) in _SCALARS for v in value) else deepcopy(value))
            if type(value) not in _SCALARS else value for key, value in box.items()}


_SCALARS = (int, float, str, bool, type(None))


def copy_boxes(override):
    return [_copy_box(box) if type(box) is dict else deepcopy(box) for box in override["boxes"]]


STORAGE_ENTITY_KINDS = ("storage", "chest", "storage_case", "crate")


def copy_entities(override):
    return deepcopy(override["entities"])


def copy_anchors(override):
    return deepcopy(override["anchors"])


# ── placement ────────────────────────────────────────────────────────────────

def placed_group(name):
    """[primary entry, *secondary entries] for primary ``name``; just [entry] for anything else; [] if unknown."""
    entry = get_map_contract(name)
    if entry is None:
        return []
    if entry.get("world") is not None:
        return [entry]
    secondaries = [e for key, e in MAP_CONTRACTS.items() if e.get("world") == name]
    return [entry, *secondaries]


def _rect_gap(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def validate_placement(entries, world_width=None, world_height=None):
    """Raise ValueError unless the placed maps fit, do not overlap, are isolated and agree on radius and ids."""
    import genesis_config as cfg
    width = float(cfg.MAP_WIDTH if world_width is None else world_width)
    height = float(cfg.MAP_HEIGHT if world_height is None else world_height)
    unbounded = os.environ.get("EDEN_WINDOW", "") == "1"      # P5: the window world has no edge; interiors sit in pockets outside any fixed rectangle
    rects = [(e["info"]["map_id"] if e.get("info") else "?", e["bounds"]) for e in entries]
    seen_ids = {}
    for entry in entries:
        label = entry["info"]["map_id"] if entry.get("info") else "?"
        x0, y0, x1, y1 = entry["bounds"]
        if not unbounded and (x0 < 0 or y0 < 0 or x1 > width or y1 > height):
            raise ValueError(f"map {label!r} at {x0:g},{y0:g}..{x1:g},{y1:g} does not fit the {width:g}x{height:g} world")
        if abs(entry["actor_radius"] - entries[0]["actor_radius"]) > 1e-12:
            raise ValueError(f"map {label!r} has actor_radius {entry['actor_radius']:g}; placed maps must share one radius "
                             f"({entries[0]['actor_radius']:g})")
        for backend_id in entry["ids"]:
            if backend_id in seen_ids:
                raise ValueError(f"id {backend_id!r} is defined by both {seen_ids[backend_id]!r} and {label!r}")
            seen_ids[backend_id] = label
    for i, (name_a, a) in enumerate(rects):
        for name_b, b in rects[i + 1:]:
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                raise ValueError(f"maps {name_a!r} and {name_b!r} overlap")
            gap = _rect_gap(a, b)
            if gap <= ISOLATION_DISTANCE and not unbounded:     # EDEN_WINDOW: the space masks isolate interiors; pockets may be neighbours
                raise ValueError(f"maps {name_a!r} and {name_b!r} are {gap:g} units apart; "
                                 f"they must be more than {ISOLATION_DISTANCE:g} apart")


def union_bounds(entries):
    """The rectangle ``[x0, y0, x1, y1]`` that covers every placed map."""
    return [min(e["bounds"][0] for e in entries), min(e["bounds"][1] for e in entries),
            max(e["bounds"][2] for e in entries), max(e["bounds"][3] for e in entries)]


def containment_slabs(rects, height=2.4):
    """Blocking boxes that fill the union rectangle outside every placed rectangle.

    The plane is cut along every rectangle edge; each cell not inside a rectangle is blocked, and blocked cells
    that are neighbours along a row are merged. Ids are ``map_slab_<n>`` in reading order (deterministic).
    """
    if len(rects) < 2:
        return []
    xs = sorted({v for r in rects for v in (r[0], r[2])})
    ys = sorted({v for r in rects for v in (r[1], r[3])})
    slabs = []
    for j in range(len(ys) - 1):
        start = None
        for i in range(len(xs)):
            blocked = False
            if i < len(xs) - 1:
                cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
                blocked = not any(r[0] < cx < r[2] and r[1] < cy < r[3] for r in rects)
            if blocked and start is None:
                start = i
            elif not blocked and start is not None:
                slabs.append({"id": f"map_slab_{len(slabs)}", "min": [xs[start], ys[j]], "max": [xs[i], ys[j + 1]],
                              "height": height})
                start = None
    return slabs


def compose_group(name):
    """Contract pieces for the world whose primary map is ``name``, or None for legacy maps.

    Returns ``{"entries", "primary", "actor_radius", "bounds", "boxes"}`` where boxes are the placed maps' walls
    (primary first) followed by the containment slabs, all in world units and freshly copied.
    """
    group = placed_group(name)
    if not group:
        return None
    boxes = [box for entry in group for box in copy_boxes(entry)]
    boxes += containment_slabs([entry["bounds"] for entry in group])
    bounds = union_bounds(group) if len(group) > 1 else list(group[0]["bounds"])
    return {"entries": group, "primary": group[0], "actor_radius": group[0]["actor_radius"], "bounds": bounds, "boxes": boxes}


def position_in_placed_maps(name, x, y):
    """True on legacy maps (no placement) and when (x, y) lies inside any placed rectangle (closed)."""
    group = placed_group(name)
    if not group:
        return True
    return any(e["bounds"][0] <= x <= e["bounds"][2] and e["bounds"][1] <= y <= e["bounds"][3] for e in group)


def outside_placed_maps(engine, session):
    """True when a controlled human's position is outside every placed rectangle of an authored world. Never under EDEN_WINDOW=1: that world
    has no edge (the wall and void boxes are the boundary) and the placed rectangles do not follow a re-base."""
    if os.environ.get("EDEN_WINDOW", "") == "1":
        return False
    if getattr(session, "get", None) is None or session.get("target_kind") != "human":
        return False
    slot = session.get("slot")
    if not isinstance(slot, int) or not 0 <= slot < engine.state.h_tensor.shape[0]:
        return False
    if not placed_group(getattr(engine, "_map_name", None)):
        return False
    import genesis_config as cfg
    row = engine.state.h_tensor[slot]
    return not position_in_placed_maps(engine._map_name, float(row[cfg.X]), float(row[cfg.Y]))


# ── registration from loaded maps ───────────────────────────────────────────

def register_world_map(world_map, name=None, actor_radius=None, *, origin=(0.0, 0.0), raw=None, primary=True, world=None):
    """Register a loaded ``world_map.WorldMap`` under ``name`` (default: its map_id).

    ``origin`` places the map in the world (world = origin + local). ``raw`` is the exact file bytes.
    A secondary map (``primary=False``) must name its primary with ``world=``; the placement is validated and the
    registration is rolled back if it is invalid.
    """
    from world_map import to_anchor_list, to_movement_contract
    if not primary and world is None:
        raise ValueError("a secondary map must name the primary map it is placed with (world=...)")
    contract = to_movement_contract(world_map, actor_radius)
    ox, oy = float(origin[0]), float(origin[1])
    boxes = [{**box, "min": [box["min"][0] + ox, box["min"][1] + oy], "max": [box["max"][0] + ox, box["max"][1] + oy]}
             for box in contract["boxes"]]
    bounds = [contract["bounds"][0] + ox, contract["bounds"][1] + oy, contract["bounds"][2] + ox, contract["bounds"][3] + oy]
    anchors = [{**anchor, "position": [anchor["position"][0] + ox, anchor["position"][1] + oy]}
               for anchor in to_anchor_list(world_map)]
    entities = [{"id": e.id, "kind": e.kind, "interactive": e.interactive, "position": [e.position[0] + ox, e.position[1] + oy],
                 "interact_radius": e.interact_radius} for e in world_map.entities]
    for registered, e in zip(entities, world_map.entities):      # G-005: only entities that declare one carry a resource object
        if e.resource is not None:
            registered["resource"] = dict(e.resource)
    ids = [*(w.id for w in world_map.walls), *(e.id for e in world_map.entities),
           *(a.id for a in world_map.anchors), *(p.id for p in world_map.portals)]
    info = {"map_id": world_map.map_id, "format_version": world_map.format_version, "revision": world_map.revision}
    if raw is not None:
        info["sha256"] = hashlib.sha256(raw).hexdigest()
        info["size_bytes"] = len(raw)
    info.update({"url": f"/map_file/{world_map.map_id}", "map_kind": world_map.map_kind,
                 "units_per_tile": world_map.units_per_tile, "tile_size_px": world_map.tile_size_px,
                 "size_tiles": list(world_map.size_tiles), "actor_radius": contract["actor_radius"],
                 "origin": [ox, oy], "primary": bool(primary)})
    key = name or world_map.map_id
    previous = MAP_CONTRACTS.get(key)
    register_map_contract(key, contract["actor_radius"], bounds, boxes, anchors=anchors, origin=(ox, oy), info=info,
                          raw=raw, world=None if primary else world, ids=ids, entities=entities,
                          wall_owners={w.id: w.owner_entity for w in world_map.walls if w.owner_entity},
                          portals=[{"id": p.id, "from_anchor": p.from_anchor, "to_map": p.to_map, "to_anchor": p.to_anchor}
                                   for p in world_map.portals])
    try:
        if not primary and get_map_contract(world) is None:
            raise ValueError(f"primary map {world!r} is not registered")
        validate_placement(placed_group(world if not primary else key))
    except ValueError:
        if previous is None:
            unregister_map_contract(key)
        else:
            MAP_CONTRACTS[key] = previous
        raise


def register_map_file(path, name=None, actor_radius=None, *, origin=(0.0, 0.0), base_dir=None, primary=True, world=None):
    """Read ``path`` once as bytes, validate it, and register it. The same bytes are hashed and served."""
    from world_map import load_map_bytes
    with open(path, "rb") as handle:
        raw = handle.read()
    world_map = load_map_bytes(raw, base_dir=base_dir, actor_radius=actor_radius)
    register_world_map(world_map, name=name, actor_radius=actor_radius, origin=origin, raw=raw, primary=primary, world=world)
    return world_map


def _read_origins(environ):
    value = environ.get(ENV_MAP_ORIGINS, "").strip()
    if not value:
        return {}
    if value.startswith("{"):
        text = value
    else:
        try:
            with open(value, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise ValueError(f"{ENV_MAP_ORIGINS} must be a JSON object or the path of a JSON file: {exc}") from exc
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{ENV_MAP_ORIGINS} must be a JSON object mapping map_id to [x, y]")
    for key, origin in data.items():
        if not (isinstance(origin, list) and len(origin) == 2 and _finite(origin)):
            raise ValueError(f"{ENV_MAP_ORIGINS}[{key!r}] must be a finite [x, y]")
    return data


def load_from_environment(environ=None):
    """Load and register every map in EDEN_MAP_FILES (first = primary). Returns the registered map ids.

    Invalid maps or an invalid placement raise; nothing from a failed load stays registered.
    """
    env = os.environ if environ is None else environ
    paths = [p.strip() for p in env.get(ENV_MAP_FILES, "").split(os.pathsep) if p.strip()]
    if not paths:
        return []
    origins = _read_origins(env)
    from world_map import load_map_bytes
    names = []
    primary_name = None
    try:
        for path in paths:
            with open(path, "rb") as handle:
                raw = handle.read()
            world_map = load_map_bytes(raw)
            if primary_name is None:
                primary_name = world_map.map_id
                register_world_map(world_map, origin=origins.get(primary_name, (0.0, 0.0)), raw=raw)
            elif "1" in (env.get("EDEN_WINDOW", ""), os.environ.get("EDEN_WINDOW", "")):      # P5 (e): interiors sit in the pocket pool, not at EDEN_MAP_ORIGINS
                from harness.window import POCKET_ORIGINS, POCKET_UNITS, authored_pocket
                size = [world_map.size_tiles[0] * world_map.units_per_tile, world_map.size_tiles[1] * world_map.units_per_tile]
                if max(size) > POCKET_UNITS:
                    raise ValueError(f"interior {world_map.map_id!r} is {size[0]:g} x {size[1]:g} units; a pocket holds {POCKET_UNITS:g} x {POCKET_UNITS:g}")
                register_world_map(world_map, origin=POCKET_ORIGINS[authored_pocket(len(names) - 1)], raw=raw, primary=False, world=primary_name)
            else:
                if world_map.map_id not in origins:
                    raise ValueError(f"{ENV_MAP_ORIGINS} has no origin for secondary map {world_map.map_id!r}")
                register_world_map(world_map, origin=origins[world_map.map_id], raw=raw, primary=False, world=primary_name)
            names.append(world_map.map_id)
    except Exception:
        for name in names:
            unregister_map_contract(name)
        raise
    return names


def maps_block(engine):
    """The wire ``maps`` list (primary first) for the active authored world, or None for legacy maps."""
    group = placed_group(getattr(engine, "_map_name", None))
    if not group or any(e.get("raw") is None or e.get("info") is None for e in group):
        return None
    maps = [deepcopy(e["info"]) for e in group]
    if os.environ.get("EDEN_WINDOW", "") == "1":  # P5: where the map is now in window-local coordinates is origin + window_shift (a re-base moves the primary)
        for entry, source in zip(maps, group):
            entry["window_shift"] = list(source.get("window_shift", [0.0, 0.0]))
    if os.environ.get("EDEN_SPACES", "") == "1":  # 1008 P3: every map entry names its space (registration order, primary 0)
        for index, entry in enumerate(maps):
            entry["space"] = index
    return maps


def get_map_file(map_id):
    """(raw bytes, sha256 hex) of a registered map file by its map_id, or None."""
    for entry in MAP_CONTRACTS.values():
        info = entry.get("info")
        if info is not None and entry.get("raw") is not None and info["map_id"] == map_id:
            return entry["raw"], info["sha256"]
    return None
