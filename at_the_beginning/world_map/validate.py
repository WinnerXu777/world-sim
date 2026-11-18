"""Semantic validation of a parsed WorldMap (geometry, reachability, sprites, portals).

Standability mirrors ``systems.movement.spatial.slide``: the actor is a square of
half-width ``actor_radius``, each wall is inflated by that radius, a point is
blocked when strictly inside an inflated box, and positions are clamped to
``[radius, size - radius]``.
"""
import math
from bisect import bisect_left, bisect_right
from pathlib import Path, PurePosixPath, PureWindowsPath

from .schema import Issue

_EPS = 0.0001  # same tolerance spatial.slide uses for "embedded"
CLEARANCE_MARGIN = 1.0  # anchors should keep radius + 1 from walls; passages should be at least 2*radius + 1 wide


def default_actor_radius():
    """The backend contract radius. Imported lazily: spatial pulls in the sim stack."""
    from systems.movement.spatial import RADIUS
    return RADIUS


def effective_radius(world_map, override=None):
    """Radius precedence: explicit override, then the file's actor_radius, then the backend default."""
    if override is not None:
        return float(override)
    if world_map.actor_radius is not None:
        return float(world_map.actor_radius)
    return default_actor_radius()


def inflated_boxes(world_map, radius):
    return [(w.min[0] - radius, w.min[1] - radius, w.max[0] + radius, w.max[1] + radius) for w in world_map.walls]


def is_standable(point, boxes, bounds, radius):
    x, y = point
    if not (bounds[0] + radius - 1e-9 <= x <= bounds[2] - radius + 1e-9
            and bounds[1] + radius - 1e-9 <= y <= bounds[3] - radius + 1e-9):
        return False
    return not any(a + _EPS < x < c - _EPS and b + _EPS < y < d - _EPS for a, b, c, d in boxes)


def walkable_grid(world_map, radius, resolution=None):
    """Rasterise standable space. Returns (grid, cols, rows, cell) with grid[row*cols+col] truthy when walkable.

    Cells are at most ``radius`` wide and tile-aligned. Inflated walls are at least
    ``2*radius`` thick, so a 4-neighbour walk cannot hop over one.
    """
    bounds = world_map.bounds
    if resolution is None:
        resolution = max(1, math.ceil(world_map.units_per_tile / radius))
    cell = world_map.units_per_tile / resolution
    cols, rows = world_map.size_tiles[0] * resolution, world_map.size_tiles[1] * resolution
    grid = bytearray(b"\x01") * (cols * rows)
    # Outside [radius, size - radius] is blocked.
    for row in range(rows):
        cy = (row + 0.5) * cell
        for col in range(cols):
            cx = (col + 0.5) * cell
            if not (bounds[0] + radius <= cx <= bounds[2] - radius and bounds[1] + radius <= cy <= bounds[3] - radius):
                grid[row * cols + col] = 0
    for a, b, c, d in inflated_boxes(world_map, radius):
        for row in range(max(0, int(b / cell) - 1), min(rows, int(d / cell) + 2)):
            cy = (row + 0.5) * cell
            if not b + _EPS < cy < d - _EPS:
                continue
            for col in range(max(0, int(a / cell) - 1), min(cols, int(c / cell) + 2)):
                if a + _EPS < (col + 0.5) * cell < c - _EPS:
                    grid[row * cols + col] = 0
    return grid, cols, rows, cell


def _flood(grid, cols, rows, seeds):
    seen = bytearray(len(grid))
    stack = [s for s in seeds if grid[s]]
    for s in stack:
        seen[s] = 1
    while stack:
        i = stack.pop()
        row, col = divmod(i, cols)
        for n, ok in ((i - 1, col > 0), (i + 1, col < cols - 1), (i - cols, row > 0), (i + cols, row < rows - 1)):
            if ok and grid[n] and not seen[n]:
                seen[n] = 1
                stack.append(n)
    return seen


def _near_cells(point, cell, cols, rows):
    col, row = int(point[0] / cell), int(point[1] / cell)
    for r in range(max(0, row - 1), min(rows, row + 2)):
        for c in range(max(0, col - 1), min(cols, col + 2)):
            yield r * cols + c


def _sprite_problem(ref, base_dir):
    if PurePosixPath(ref).is_absolute() or PureWindowsPath(ref).is_absolute() or PureWindowsPath(ref).drive:
        return "sprite reference must be relative, not absolute"
    if ".." in PurePosixPath(ref.replace("\\", "/")).parts:
        return "sprite reference must not contain '..'"
    if base_dir is not None:
        base = Path(base_dir)
        target = base / ref
        if not target.is_file():
            return f"sprite file not found under {base}: {ref}"
        try:
            target.resolve().relative_to(base.resolve())
        except ValueError:
            return "sprite reference resolves outside the base directory"
    return None


def validate_map(world_map, base_dir=None, actor_radius=None):
    """Return a list of Issues. Sprite files are only checked when base_dir is given."""
    issues = []
    radius = effective_radius(world_map, actor_radius)
    if not (math.isfinite(radius) and radius > 0):
        raise ValueError(f"actor_radius must be finite and > 0, got {actor_radius!r}")
    bounds = world_map.bounds
    boxes = inflated_boxes(world_map, radius)

    for i, anchor in enumerate(world_map.anchors):
        if not is_standable(anchor.position, boxes, bounds, radius):
            issues.append(Issue("error", f"anchors[{i}]", f"anchor {anchor.id!r} at {list(anchor.position)} is not standable: "
                                f"inside a wall (inflated by actor radius {radius}) or closer than {radius} to the map edge"))

    near = inflated_boxes(world_map, radius + CLEARANCE_MARGIN)
    for i, anchor in enumerate(world_map.anchors):
        x, y = anchor.position
        if is_standable(anchor.position, boxes, bounds, radius) and any(
                a + _EPS < x < c - _EPS and b + _EPS < y < d - _EPS for a, b, c, d in near):
            issues.append(Issue("warning", f"anchors[{i}]", f"anchor {anchor.id!r} is within actor radius + {CLEARANCE_MARGIN:g} "
                                f"({radius + CLEARANCE_MARGIN:g}) of a wall; an actor spawned or teleported here sits close "
                                f"to being embedded (an embedded actor never moves)"))

    _check_reachability(world_map, issues, radius)
    if world_map.map_kind == "interior":
        _check_interior_sealed(world_map, issues, radius)
    _check_blocking_entity_access(world_map, issues, radius)

    for path, ref in world_map.sprite_references():
        problem = _sprite_problem(ref, base_dir)
        if problem:
            issues.append(Issue("error", path, problem))
    if base_dir is None and any(True for _ in world_map.sprite_references()):
        issues.append(Issue("warning", "$", "no base directory given; sprite file existence not checked"))

    anchors = {a.id: a for a in world_map.anchors}
    for i, portal in enumerate(world_map.portals):
        source = anchors.get(portal.from_anchor)
        if source is None:
            issues.append(Issue("error", f"portals[{i}].from_anchor", f"unknown anchor {portal.from_anchor!r}"))
        elif source.kind != "door":
            issues.append(Issue("warning", f"portals[{i}].from_anchor", f"anchor {source.id!r} has kind {source.kind!r}, expected 'door'"))
        if portal.to_map == world_map.map_id and portal.to_anchor not in anchors:
            issues.append(Issue("error", f"portals[{i}].to_anchor", f"unknown anchor {portal.to_anchor!r} in this map"))
    if not world_map.anchors:
        issues.append(Issue("warning", "anchors", "map has no anchors"))
    elif not any(a.kind == "spawn" for a in world_map.anchors):
        issues.append(Issue("warning", "anchors", "map has no 'spawn' anchor"))
    return issues


class FreeSpace:
    """Exact free space of the actor's centre point: the rectangle [r, size - r] minus the inflated wall boxes.

    Coordinates are compressed to the box edges, so every cell is wholly free or wholly blocked and
    connectivity is exact for axis-aligned walls (no grid-resolution artefacts). A gap of exactly 2r has no
    free cell (it only admits a zero-width path) and counts as blocked.
    """

    def __init__(self, world_map, radius):
        bounds = world_map.bounds
        self.lo = (bounds[0] + radius, bounds[1] + radius)
        self.hi = (bounds[2] - radius, bounds[3] - radius)
        self.empty = not (self.lo[0] < self.hi[0] and self.lo[1] < self.hi[1])
        if self.empty:
            self.xs = self.ys = []
            self.nx = self.ny = 0
            self.blocked = bytearray()
            return
        boxes = [(max(a, self.lo[0]), max(b, self.lo[1]), min(c, self.hi[0]), min(d, self.hi[1]))
                 for a, b, c, d in inflated_boxes(world_map, radius)]
        boxes = [box for box in boxes if box[0] < box[2] and box[1] < box[3]]
        self.xs = sorted({self.lo[0], self.hi[0], *(v for box in boxes for v in (box[0], box[2]))})
        self.ys = sorted({self.lo[1], self.hi[1], *(v for box in boxes for v in (box[1], box[3]))})
        self.nx, self.ny = len(self.xs) - 1, len(self.ys) - 1
        self.blocked = bytearray(self.nx * self.ny)
        for a, b, c, d in boxes:
            for j in range(bisect_left(self.ys, b), bisect_left(self.ys, d)):
                base = j * self.nx
                for i in range(bisect_left(self.xs, a), bisect_left(self.xs, c)):
                    self.blocked[base + i] = 1

    def cells_at(self, point):
        """Free cells whose closed rectangle contains ``point`` (up to four when it lies on a corner)."""
        if self.empty:
            return []
        out = []
        xi = bisect_right(self.xs, point[0]) - 1
        yj = bisect_right(self.ys, point[1]) - 1
        for i in {xi, xi - 1 if point[0] == self.xs[max(xi, 0)] else xi}:
            for j in {yj, yj - 1 if point[1] == self.ys[max(yj, 0)] else yj}:
                if 0 <= i < self.nx and 0 <= j < self.ny and not self.blocked[j * self.nx + i]:
                    out.append((i, j))
        return out

    def flood(self, seeds):
        seen = bytearray(self.nx * self.ny)
        stack = []
        for i, j in seeds:
            if not seen[j * self.nx + i]:
                seen[j * self.nx + i] = 1
                stack.append((i, j))
        while stack:
            i, j = stack.pop()
            for ni, nj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
                if 0 <= ni < self.nx and 0 <= nj < self.ny:
                    k = nj * self.nx + ni
                    if not self.blocked[k] and not seen[k]:
                        seen[k] = 1
                        stack.append((ni, nj))
        return seen

    def touches_limit(self, seen):
        """True if any reached cell borders the clamp limit (the map edge, where the actor can leave)."""
        for j in range(self.ny):
            for i in range(self.nx):
                if seen[j * self.nx + i] and (i == 0 or j == 0 or i == self.nx - 1 or j == self.ny - 1):
                    return (self.xs[i], self.ys[j])
        return None


def _check_reachability(world_map, issues, radius):
    if len(world_map.anchors) < 2:
        return
    bounds = world_map.bounds
    boxes = inflated_boxes(world_map, radius)
    standable = [(i, a) for i, a in enumerate(world_map.anchors) if is_standable(a.position, boxes, bounds, radius)]
    if len(standable) < 2:
        return
    reference = next(((i, a) for i, a in standable if a.kind == "spawn"), standable[0])
    space = FreeSpace(world_map, radius)
    seeds = space.cells_at(reference[1].position)
    if not seeds:
        issues.append(Issue("error", f"anchors[{reference[0]}]", f"reference anchor {reference[1].id!r} lies in no free space "
                            f"(only a zero-width passage, or radius {radius} leaves no room)"))
        return
    seen = space.flood(seeds)
    for i, anchor in standable:
        if not any(seen[j * space.nx + k] for k, j in space.cells_at(anchor.position)):
            issues.append(Issue("error", f"anchors[{i}]", f"anchor {anchor.id!r} is unreachable from {reference[1].id!r} "
                                f"(exact free-space flood fill, actor radius {radius})"))
    # Marginal passages: reachable with the real radius but not with a radius that leaves CLEARANCE_MARGIN spare.
    wide = FreeSpace(world_map, radius + CLEARANCE_MARGIN / 2 - 1e-6)
    wide_seeds = wide.cells_at(reference[1].position)
    if not wide_seeds:
        return
    wide_seen = wide.flood(wide_seeds)
    for i, anchor in standable:
        cells = wide.cells_at(anchor.position)
        reached = any(seen[j * space.nx + k] for k, j in space.cells_at(anchor.position))
        if reached and cells and not any(wide_seen[j * wide.nx + k] for k, j in cells):
            issues.append(Issue("warning", f"anchors[{i}]", f"the route to anchor {anchor.id!r} passes a gap between 2*radius "
                                f"({2 * radius:g}) and 2*radius + {CLEARANCE_MARGIN:g}: passable only with almost no lateral tolerance"))


def _check_interior_sealed(world_map, issues, radius):
    """Warn when space reachable from an anchor touches the map-edge clamp (no wall ring)."""
    bounds = world_map.bounds
    boxes = inflated_boxes(world_map, radius)
    space = FreeSpace(world_map, radius)
    seeds = [cell for a in world_map.anchors if is_standable(a.position, boxes, bounds, radius)
             for cell in space.cells_at(a.position)]
    if not seeds:
        return
    spot = space.touches_limit(space.flood(seeds))
    if spot is not None:
        issues.append(Issue("warning", "walls", f"interior map is not sealed: walkable space near ({spot[0]:.1f}, {spot[1]:.1f}) "
                            f"is open to the map bounds; add walls along the edge"))


def _check_blocking_entity_access(world_map, issues, radius):
    """Warn when an interactive entity with a wall (owner_entity) has no usable work/talk anchor.

    Usable = a work or talk anchor outside the wall's box inflated by the actor radius and, when the
    entity declares interact_radius, within that distance of the entity.
    """
    entities = {e.id: e for e in world_map.entities}
    for i, wall in enumerate(world_map.walls):
        entity = entities.get(wall.owner_entity)
        if entity is None or not entity.interactive:
            continue
        a, b, c, d = wall.min[0] - radius, wall.min[1] - radius, wall.max[0] + radius, wall.max[1] + radius
        usable = False
        for anchor in world_map.anchors:
            if anchor.kind not in ("work", "talk"):
                continue
            x, y = anchor.position
            if a + _EPS < x < c - _EPS and b + _EPS < y < d - _EPS:
                continue
            if entity.interact_radius is not None and math.hypot(x - entity.position[0], y - entity.position[1]) > entity.interact_radius:
                continue
            usable = True
            break
        if not usable:
            issues.append(Issue("warning", f"walls[{i}]", f"interactive entity {entity.id!r} is blocked by wall {wall.id!r} but has no "
                                f"work or talk anchor outside the wall inflated by actor radius {radius}"
                                + (f" within interact_radius {entity.interact_radius}" if entity.interact_radius is not None else "")))


def check_portal_targets(maps):
    """Cross-map check. ``maps`` is an iterable of WorldMap; returns Issues for portals into loaded maps.

    Portals targeting a map that is not in the set are reported as warnings.
    """
    by_id = {m.map_id: m for m in maps}
    issues = []
    for m in by_id.values():
        for i, portal in enumerate(m.portals):
            target = by_id.get(portal.to_map)
            where = f"{m.map_id}:portals[{i}]"
            if target is None:
                issues.append(Issue("warning", where, f"target map {portal.to_map!r} was not loaded; to_anchor unchecked"))
            elif portal.to_anchor not in {a.id for a in target.anchors}:
                issues.append(Issue("error", where, f"target map {portal.to_map!r} has no anchor {portal.to_anchor!r}"))
    return issues
