"""Structural parsing: JSON-shaped dict -> typed WorldMap, collecting issues.

Checks types, finiteness, bounds, and ID uniqueness. Semantic checks that
need geometry (anchors vs walls, reachability, sprite files) live in
validate.py.
"""
import json
import math
import re

from .schema import (ACCEPTED_FORMAT_VERSIONS, COORDINATE_SYSTEM, FORMAT_VERSION, GENERATED_ID_PATTERN, ID_PATTERN,
                     KNOWN_ANCHOR_KINDS, KNOWN_ANCHOR_ROLES, LAYER_KINDS, MAP_KINDS, MAX_SIZE_TILES, WALL_DEFAULT_HEIGHT, Anchor, Entity, Issue, Portal, TileLayer, Wall, WorldMap)

from .resources import check_resource, declared as resource_declared

_ID_RE = re.compile(ID_PATTERN + r"\Z")
_GENERATED_ID_RE = re.compile(GENERATED_ID_PATTERN + r"\Z")
_TOP_KEYS = {"format_version", "map_id", "revision", "tile_size_px", "units_per_tile", "size_tiles",
             "layers", "walls", "anchors", "entities", "portals", "actor_radius", "map_kind", "coordinate_system",
             "pixels_per_unit"}
_EXTRA_KEYS = ("chunk", "data", "pinned_map")  # chunk documents (1008_worldgen.md) are 0.2-draft plus these blocks
_TOP_KEYS = _TOP_KEYS | set(_EXTRA_KEYS)


def loads_strict(text):
    """json.loads that rejects NaN/Infinity constants and duplicate object keys."""
    def no_constant(name):
        raise ValueError(f"non-finite JSON constant {name}")

    def no_dupes(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key {key!r}")
            out[key] = value
        return out
    return json.loads(text, parse_constant=no_constant, object_pairs_hook=no_dupes)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class _Ctx:
    def __init__(self):
        self.issues = []

    def error(self, path, message):
        self.issues.append(Issue("error", path, message))

    def warn(self, path, message):
        self.issues.append(Issue("warning", path, message))

    def ident(self, value, path):
        if not isinstance(value, str) or not _ID_RE.match(value):
            self.error(path, f"must be an id string matching {ID_PATTERN}, got {value!r}")
            return None
        if _GENERATED_ID_RE.match(value):
            self.error(path, f"{value!r} matches the backend-generated entity id pattern {GENERATED_ID_PATTERN}")
            return None
        return value

    def radius(self, value, path):
        if not (_is_num(value) and value > 0):
            self.error(path, f"must be a finite number > 0 (backend units), got {value!r}")
            return None
        return float(value)

    def string(self, value, path):
        if not isinstance(value, str) or not value:
            self.error(path, f"must be a non-empty string, got {value!r}")
            return None
        return value

    def point(self, value, path):
        if not (isinstance(value, (list, tuple)) and len(value) == 2 and all(_is_num(v) for v in value)):
            self.error(path, f"must be [x, y] with finite numbers, got {value!r}")
            return None
        return (float(value[0]), float(value[1]))

    def obj_list(self, data, key):
        value = data.get(key, [])
        if not isinstance(value, list):
            self.error(key, f"must be a list, got {type(value).__name__}")
            return []
        out = []
        for i, item in enumerate(value):
            if isinstance(item, dict):
                out.append((i, item))
            else:
                self.error(f"{key}[{i}]", "must be an object")
        return out


def _inside(point, bounds):
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def parse_map(data):
    """Return (WorldMap | None, issues). WorldMap is None when the header is unusable."""
    ctx = _Ctx()
    if not isinstance(data, dict):
        ctx.error("$", "map file must be a JSON object")
        return None, ctx.issues
    for key in sorted(set(data) - _TOP_KEYS):
        ctx.warn(key, "unknown top-level key (ignored)")

    version = data.get("format_version")
    if version not in ACCEPTED_FORMAT_VERSIONS:
        ctx.error("format_version", f"expected one of {ACCEPTED_FORMAT_VERSIONS}, got {version!r}")
    elif version != FORMAT_VERSION:
        ctx.warn("format_version", f"{version!r} is accepted but {FORMAT_VERSION!r} is current")
    map_id = ctx.ident(data.get("map_id"), "map_id")
    revision = data.get("revision")
    legacy_string_ok = version == "0.1-draft"  # only the old draft allowed string revisions
    if not ((_is_int(revision) and revision >= 0) or (legacy_string_ok and isinstance(revision, str) and revision)):
        ctx.error("revision", "must be a non-negative integer" + (" or non-empty string" if legacy_string_ok else "")
                  + f", got {revision!r}")
        revision = None
    elif isinstance(revision, str):
        ctx.warn("revision", "string revisions are only accepted in 0.1-draft; 0.2-draft requires a non-negative integer")
    tile_px = data.get("tile_size_px")
    if not (_is_int(tile_px) and tile_px > 0):
        ctx.error("tile_size_px", f"must be a positive integer, got {tile_px!r}")
        tile_px = None
    upt = data.get("units_per_tile")
    if "units_per_tile" not in data:
        ctx.error("units_per_tile", "required; the file must declare the backend-units-per-tile factor")
        upt = None
    elif not (_is_num(upt) and upt > 0):
        ctx.error("units_per_tile", f"must be a finite number > 0, got {upt!r}")
        upt = None
    size = data.get("size_tiles")
    if not (isinstance(size, (list, tuple)) and len(size) == 2
            and all(_is_int(v) and 0 < v <= MAX_SIZE_TILES for v in size)):
        ctx.error("size_tiles", f"must be [width, height] integers in 1..{MAX_SIZE_TILES}, got {size!r}")
        size = None
    if None in (map_id, revision, tile_px, upt, size) or version not in ACCEPTED_FORMAT_VERSIONS:
        return None, ctx.issues
    size = (int(size[0]), int(size[1]))
    bounds = [0.0, 0.0, size[0] * float(upt), size[1] * float(upt)]

    actor_radius = None
    if "actor_radius" in data:
        actor_radius = ctx.radius(data["actor_radius"], "actor_radius")
    else:
        ctx.warn("actor_radius", "not set; the backend default radius will be used (recommended: declare it)")
    map_kind = data.get("map_kind", "exterior")
    if map_kind not in MAP_KINDS:
        ctx.error("map_kind", f"must be one of {MAP_KINDS}, got {map_kind!r}")
        map_kind = "exterior"
    if "coordinate_system" in data and data["coordinate_system"] != COORDINATE_SYSTEM:
        ctx.error("coordinate_system", f"must be {COORDINATE_SYSTEM!r} when present, got {data['coordinate_system']!r}")
    if "pixels_per_unit" in data:
        derived = tile_px / float(upt)
        given = data["pixels_per_unit"]
        if not (_is_num(given) and math.isclose(given, derived, rel_tol=1e-9)):
            ctx.error("pixels_per_unit", f"derived value (tile_size_px / units_per_tile = {derived}); do not store it, got {given!r}")
        else:
            ctx.warn("pixels_per_unit", "derived from tile_size_px / units_per_tile; remove it from the file (ignored)")

    layers = _parse_layers(ctx, data, size)
    walls = _parse_walls(ctx, data, bounds)
    anchors = _parse_anchors(ctx, data, bounds)
    entities = _parse_entities(ctx, data, bounds)
    portals = _parse_portals(ctx, data)

    seen = {}
    for kind, items in (("walls", walls), ("entities", entities), ("anchors", anchors), ("portals", portals)):
        for i, item in enumerate(items):
            if item.id in seen:
                ctx.error(f"{kind}[{i}].id", f"duplicate id {item.id!r} (also {seen[item.id]}); walls, entities, anchors and portals share one id namespace")
            else:
                seen[item.id] = f"{kind}[{i}]"
    entity_ids = {e.id for e in entities}
    for i, wall in enumerate(walls):
        if wall.owner_entity is not None and wall.owner_entity not in entity_ids:
            ctx.error(f"walls[{i}].owner_entity", f"unknown entity id {wall.owner_entity!r}")
    names = {}
    for i, layer in enumerate(layers):
        if layer.name in names:
            ctx.error(f"layers[{i}].name", f"duplicate layer name {layer.name!r}")
        names[layer.name] = i

    world_map = WorldMap(version, map_id, revision, tile_px, float(upt), size, tuple(layers), tuple(walls),
                         tuple(anchors), tuple(entities), tuple(portals), actor_radius, map_kind,
                         tuple(i for i in ctx.issues if i.severity == "warning"),
                         _parse_extras(ctx, data, layers, walls, anchors, entities, portals))
    return world_map, ctx.issues


def _parse_extras(ctx, data, layers, walls, anchors, entities, portals):
    """Chunk-document blocks. ``chunk`` needs integer ``cx``/``cy``, ``data`` is an object, ``pinned_map`` an id string; a document with
    ``pinned_map`` is a pointer (the engine loads the authored file): no walls, anchors, entities, portals and every tile 0."""
    extras = {}
    if "chunk" in data:
        chunk = data["chunk"]
        if not isinstance(chunk, dict) or not (_is_int(chunk.get("cx")) and _is_int(chunk.get("cy"))):
            ctx.error("chunk", "must be an object with integer cx and cy")
        else:
            extras["chunk"] = chunk
    if "data" in data:
        if not isinstance(data["data"], dict):
            ctx.error("data", "must be an object")
        else:
            extras["data"] = data["data"]
    if "pinned_map" in data:
        pinned = ctx.ident(data["pinned_map"], "pinned_map")
        if pinned is not None:
            extras["pinned_map"] = pinned
            if walls or anchors or entities or portals or any(any(any(row) for row in layer.tiles) for layer in layers):
                ctx.error("pinned_map", "a pointer document has no walls, anchors, entities or portals and only empty (0) tiles")
    return extras


def _parse_layers(ctx, data, size):
    out = []
    for i, item in ctx.obj_list(data, "layers"):
        path = f"layers[{i}]"
        name = ctx.string(item.get("name"), f"{path}.name")
        kind = item.get("kind")
        if kind not in LAYER_KINDS:
            ctx.error(f"{path}.kind", f"must be one of {LAYER_KINDS}, got {kind!r}")
        raw_palette = item.get("palette", {})
        palette = {}
        if not isinstance(raw_palette, dict):
            ctx.error(f"{path}.palette", "must be an object mapping tile index to sprite reference")
        else:
            for key, ref in raw_palette.items():
                if not (key.isdigit() and int(key) > 0):
                    ctx.error(f"{path}.palette.{key}", "key must be a positive integer (0 is empty)")
                elif ctx.string(ref, f"{path}.palette.{key}") is not None:
                    palette[int(key)] = ref
        rows = item.get("tiles")
        tiles = None
        if not (isinstance(rows, list) and len(rows) == size[1]):
            ctx.error(f"{path}.tiles", f"must be a list of {size[1]} rows")
        else:
            tiles = []
            for y, row in enumerate(rows):
                if not (isinstance(row, list) and len(row) == size[0] and all(_is_int(v) and v >= 0 for v in row)):
                    ctx.error(f"{path}.tiles[{y}]", f"must be a list of {size[0]} non-negative integers")
                    tiles = None
                    break
                missing = sorted({v for v in row if v and v not in palette})
                if missing:
                    ctx.error(f"{path}.tiles[{y}]", f"tile indices {missing} are not in the palette")
                tiles.append(tuple(row))
        if name is not None and kind in LAYER_KINDS and tiles is not None:
            out.append(TileLayer(name, kind, palette, tuple(tiles)))
    return out


def _parse_walls(ctx, data, bounds):
    out = []
    for i, item in ctx.obj_list(data, "walls"):
        path = f"walls[{i}]"
        wid = ctx.ident(item.get("id"), f"{path}.id")
        lo = ctx.point(item.get("min"), f"{path}.min")
        hi = ctx.point(item.get("max"), f"{path}.max")
        height = item.get("height", WALL_DEFAULT_HEIGHT)
        if not (_is_num(height) and height > 0):
            ctx.error(f"{path}.height", f"must be a finite number > 0, got {height!r}")
            height = None
        if lo and hi:
            if not (lo[0] < hi[0] and lo[1] < hi[1]):
                ctx.error(path, "min must be strictly less than max on both axes")
                lo = None
            elif not (_inside(lo, bounds) and _inside(hi, bounds)):
                ctx.error(path, f"box {list(lo)}..{list(hi)} extends outside map bounds {bounds}")
                lo = None
        owner = item.get("owner_entity")
        if owner is not None:
            owner = ctx.ident(owner, f"{path}.owner_entity")
            if owner is None:
                continue
        if wid and lo and hi and height is not None:
            out.append(Wall(wid, lo, hi, float(height), owner))
    return out


def _parse_anchors(ctx, data, bounds):
    out = []
    for i, item in ctx.obj_list(data, "anchors"):
        path = f"anchors[{i}]"
        aid = ctx.ident(item.get("id"), f"{path}.id")
        kind = ctx.string(item.get("kind"), f"{path}.kind")
        pos = ctx.point(item.get("position"), f"{path}.position")
        if kind and kind not in KNOWN_ANCHOR_KINDS:
            ctx.warn(f"{path}.kind", f"unrecognised anchor kind {kind!r} (known: {KNOWN_ANCHOR_KINDS})")
        if pos and not _inside(pos, bounds):
            ctx.error(f"{path}.position", f"{list(pos)} is outside map bounds {bounds}")
            pos = None
        role = item.get("for_role")
        if "for_role" in item:
            if not isinstance(role, str) or not role.strip():
                ctx.error(f"{path}.for_role", f"must be a non-empty string naming an occupation, got {role!r}")
                role = None
                pos = None
            elif _GENERATED_ID_RE.match(role):
                ctx.error(f"{path}.for_role", f"{role!r} looks like a backend entity id; for_role names an occupation, not an id")
                pos = None
            elif role not in KNOWN_ANCHOR_ROLES:
                ctx.warn(f"{path}.for_role", f"unrecognised role {role!r} (known: {KNOWN_ANCHOR_ROLES})")
        if aid and kind and pos:
            out.append(Anchor(aid, kind, pos, role))
    return out


def _parse_entities(ctx, data, bounds):
    out = []
    for i, item in ctx.obj_list(data, "entities"):
        path = f"entities[{i}]"
        eid = ctx.ident(item.get("id"), f"{path}.id")
        kind = ctx.string(item.get("kind"), f"{path}.kind")
        interactive = item.get("interactive")
        if not isinstance(interactive, bool):
            ctx.error(f"{path}.interactive", f"must be true or false (decorations are explicit), got {interactive!r}")
            interactive = None
        pos = ctx.point(item.get("position"), f"{path}.position")
        sprite = item.get("sprite")
        if sprite is not None and ctx.string(sprite, f"{path}.sprite") is None:
            sprite = None
            pos = None
        if pos and not _inside(pos, bounds):
            ctx.error(f"{path}.position", f"{list(pos)} is outside map bounds {bounds}")
            pos = None
        interact_radius = None
        if "interact_radius" in item:
            interact_radius = ctx.radius(item["interact_radius"], f"{path}.interact_radius")
            if interact_radius is None:
                continue
        resource = None
        if resource_declared(item):
            resource = check_resource(item, kind or "", bool(interactive), path, ctx.error)
            if resource is None:
                continue
        if eid and kind and interactive is not None and pos:
            out.append(Entity(eid, kind, interactive, pos, sprite, interact_radius, resource))
    return out


def _parse_portals(ctx, data):
    out = []
    for i, item in ctx.obj_list(data, "portals"):
        path = f"portals[{i}]"
        pid = ctx.ident(item.get("id"), f"{path}.id")
        src = ctx.ident(item.get("from_anchor"), f"{path}.from_anchor")
        to_map = ctx.ident(item.get("to_map"), f"{path}.to_map")
        to_anchor = ctx.ident(item.get("to_anchor"), f"{path}.to_anchor")
        if pid and src and to_map and to_anchor:
            out.append(Portal(pid, src, to_map, to_anchor))
    return out
