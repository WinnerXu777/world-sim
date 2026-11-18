"""Portal command: teleport the controlled resident to the target anchor of an authored map (same epochs)."""
import math

try:
    import genesis_config as cfg
    from systems.movement.map_contract import find_portal
    from systems.movement.spatial import is_standable_point, world_contract
    from harness.numerics import spaces_enabled
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.systems.movement.map_contract import find_portal
    from at_the_beginning.systems.movement.spatial import is_standable_point, world_contract
    from at_the_beginning.harness.numerics import spaces_enabled

PORTAL_REACH = 16.0  # units from the portal's from-anchor (2 tiles at 8 units per tile)


def execute(engine, action, payload):
    """Runs at drain time; CommandInbox.authorize has already checked epochs and direct human control."""
    portal_id = payload.get("portal_id")
    if not isinstance(portal_id, str) or not portal_id or len(portal_id) > 128:
        return {"ok": False, "reason": "unknown_portal"}
    found = find_portal(getattr(engine, "_map_name", None), portal_id)
    if found is None:
        return {"ok": False, "reason": "unknown_portal"}
    if not found["to_loaded"]:
        return {"ok": False, "reason": "target_not_loaded"}
    session = engine.player_control.sessions_by_controller.get(payload.get("controller_id"))
    if session is None or session.get("target_kind") != "human":
        return {"ok": False, "reason": "not_controlling"}
    slot = int(session["slot"])
    row = engine.state.h_tensor[slot]
    x, y = float(row[cfg.X]), float(row[cfg.Y])
    if math.hypot(x - found["from"][0], y - found["from"][1]) > PORTAL_REACH:
        return {"ok": False, "reason": "out_of_range"}
    target = (found["to"][0], found["to"][1])
    if not is_standable_point(target, world_contract(engine)):
        return {"ok": False, "reason": "blocked_target"}
    row[cfg.X], row[cfg.Y] = target[0], target[1]
    if spaces_enabled():                                      # EDEN_SPACES: the actor is in the target map's space from this tick on
        try:
            from harness.spaces import space_at
        except ImportError:  # pragma: no cover - package import fallback
            from at_the_beginning.harness.spaces import space_at
        row[cfg.H_SPACE] = float(space_at(engine, target[0], target[1]))
    human_id = engine._human_uid_by_slot[slot]
    engine._teleport_seq[human_id] = engine._teleport_seq.get(human_id, 0) + 1
    engine._tick_teleports.append((slot, target[0], target[1]))
    engine._force_frame_refresh = True
    return {"ok": True, "to_map": found["portal"]["to_map"], "to_anchor": found["portal"]["to_anchor"],
            "position": [target[0], target[1]], "teleport_seq": engine._teleport_seq[human_id]}
