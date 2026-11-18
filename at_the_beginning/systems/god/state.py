"""God-mode state: persisted ledger in ``inventory_state["god"]`` (never an ENGINE_FIELDS member) and the non-saved pause flag."""
import math

STORE_KEY = "god"
WITNESS_RADIUS = 80.0   # units; a witness must also stand in the same placed map as the event
TIME_SCALES = (0.5, 1.0, 2.0)  # conservative steps; pause is separate


def store(engine):
    """The persisted god ledger in ``inventory_state['god']``, created on first use."""
    data = engine.inventory_state.setdefault(STORE_KEY, {"next_event_uid": 1, "events": {}})
    data.setdefault("next_event_uid", 1)
    data.setdefault("events", {})
    return data


def is_paused(engine):
    """True while the god has paused time (runtime flag, cleared by ``Engine.reset_world``)."""
    return bool(engine.__dict__.get("_god_paused", False))


def set_paused(engine, value):
    """Set or clear the pause flag."""
    engine.__dict__["_god_paused"] = bool(value)


def new_event_id(engine):
    """Next god event id (``g_000001``, ...); the counter is persisted, so ids never repeat after a reload."""
    data = store(engine)
    event_id = f"g_{data['next_event_uid']:06d}"
    data["next_event_uid"] += 1  # persisted counter: ids never repeat across reloads
    return event_id


def live_residents(engine):
    """[(human id, slot, (x, y))] of living humans."""
    import genesis_config as cfg
    out = []
    for slot, human_id in enumerate(engine._human_uid_by_slot):
        if human_id and float(engine.state.h_tensor[slot, cfg.TYPE]) == cfg.AGENT_TYPE_HUMAN and float(engine.state.h_tensor[slot, cfg.HP]) > 0.0:
            out.append((human_id, slot, (float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))))
    return out


def map_id_at(engine, point):
    """map_id of the placed map whose rectangle contains ``point``; None on legacy maps or outside every map."""
    from systems.movement.map_contract import placed_group
    for entry in placed_group(getattr(engine, "_map_name", None)):
        b = entry["bounds"]
        if b[0] <= point[0] <= b[2] and b[1] <= point[1] <= b[3]:
            return (entry.get("info") or {}).get("map_id", "?")
    return None


def witnesses(engine, point, *, radius=WITNESS_RADIUS, always=(), exterior_only=False):
    """Residents who can perceive an event at ``point``: same placed map AND within ``radius`` (legacy maps: radius only).

    ``always`` ids are included (the target). ``exterior_only`` limits to residents standing in exterior maps (weather).
    """
    from systems.movement.map_contract import placed_group
    here = map_id_at(engine, point)
    kinds = {(e.get("info") or {}).get("map_id"): (e.get("info") or {}).get("map_kind", "exterior") for e in placed_group(engine._map_name)}
    found = []
    for human_id, _, pos in live_residents(engine):
        if human_id in always:
            found.append(human_id)
            continue
        there = map_id_at(engine, pos)
        if exterior_only:  # weather: everyone standing outdoors (legacy maps have no interiors)
            if there is None or kinds.get(there, "exterior") == "exterior":
                found.append(human_id)
            continue
        if there != here:
            continue
        if math.hypot(pos[0] - point[0], pos[1] - point[1]) <= radius:
            found.append(human_id)
    return found
