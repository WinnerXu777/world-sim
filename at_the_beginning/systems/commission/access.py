"""Wall-aware interaction check: in range AND a clear line, ignoring the target's own footprint.

The check is pure (``interaction_ok``) so it works with a plain box list; ``engine_interaction_ok`` adds the engine
lookups (positions, interact_radius, the target's own wall via ``spatial.map_wall_boxes_ignoring``).
"""
import math

from systems.movement.spatial import segment_blocked

DEFAULT_INTERACT_RADIUS = 16.0  # 2 tiles at 8 units per tile (scale audit); a map entity may declare its own


def interaction_ok(actor_xy, target_xy, radius, boxes, ignore_ids=()):
    """{"ok", "reason", "distance"}. Reasons: "out_of_range", "blocked". Contact with a box counts as blocked."""
    distance = math.hypot(target_xy[0] - actor_xy[0], target_xy[1] - actor_xy[1])
    if not (math.isfinite(distance) and math.isfinite(radius)):
        return {"ok": False, "reason": "out_of_range", "distance": distance}
    if distance > radius:
        return {"ok": False, "reason": "out_of_range", "distance": distance}
    relevant = [b for b in boxes if b.get("id") not in set(ignore_ids)]
    if segment_blocked(tuple(actor_xy), tuple(target_xy), relevant):
        return {"ok": False, "reason": "blocked", "distance": distance}
    return {"ok": True, "reason": "", "distance": distance}


def human_position(engine, slot):
    import genesis_config as cfg
    row = engine.state.h_tensor[slot]
    return float(row[cfg.X]), float(row[cfg.Y])


def engine_interaction_ok(engine, actor_slot, target_xy, radius=None, target_entity_id=None):
    """Interaction check against the live world. On legacy maps (no registered contract) only the range applies,
    which is what every existing range check does today.

    ``target_entity_id`` names a map entity: its own footprint wall is ignored and its ``interact_radius`` (when the
    map declares one) is the default radius.
    """
    from systems.movement.map_contract import map_entity
    from systems.movement.spatial import map_wall_boxes, map_wall_boxes_ignoring
    entity = map_entity(getattr(engine, "_map_name", None), target_entity_id) if target_entity_id else None
    if radius is None:
        radius = (entity or {}).get("interact_radius") or DEFAULT_INTERACT_RADIUS
    actor_xy = human_position(engine, actor_slot)
    boxes = map_wall_boxes_ignoring(engine, target_entity_id) if target_entity_id else map_wall_boxes(engine)
    if boxes is None:  # legacy map
        boxes = []
    return interaction_ok(actor_xy, target_xy, radius, boxes)
