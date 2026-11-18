"""Convert a WorldMap's walls into the shapes systems/movement/spatial.py consumes."""


def to_wall_boxes(world_map):
    """Same shape as ``spatial.wall_boxes``: {"id", "min": [x, y], "max": [x, y], "height"}."""
    return [{"id": w.id, "min": [w.min[0], w.min[1]], "max": [w.max[0], w.max[1]], "height": w.height}
            for w in world_map.walls]


def to_anchor_list(world_map):
    """Anchors as plain dicts: {"id", "kind", "position": [x, y]} plus "for_role" when the file sets it."""
    out = []
    for a in world_map.anchors:
        item = {"id": a.id, "kind": a.kind, "position": [a.position[0], a.position[1]]}
        if a.for_role is not None:
            item["for_role"] = a.for_role
        out.append(item)
    return out


def to_movement_contract(world_map, actor_radius=None):
    """The subset of ``spatial.world_contract`` that ``spatial.slide`` reads.

    Bounds come from the map's declared size and units_per_tile, not from
    genesis_config. Radius precedence: argument, then the file's actor_radius,
    then the backend default (spatial.RADIUS).
    """
    from .validate import effective_radius
    return {"actor_radius": effective_radius(world_map, actor_radius), "bounds": world_map.bounds, "boxes": to_wall_boxes(world_map)}
