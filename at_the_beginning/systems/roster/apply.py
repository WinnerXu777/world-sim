"""Create a map's named residents from its roster and bind them to anchors.

Runs from the post-genesis hook (``install.py``): residents are spawned at their ``spawn`` anchors (snapped to a
standable point by ``Engine.spawn``), their resident records are created, then occupation, personality, schedule and
inventory are overridden from the roster BEFORE the engine's provisioning pass runs, so nothing is provisioned for a
role the resident does not have. The binding (``resident["roster"]``) lives in the resident record, which the world
snapshot already persists: no new engine field.
"""
import json
import os
from pathlib import Path

from .load import load_roster
from .validate import anchors_from_registry, validate_roster_for_world

ROSTER_DIR = Path(__file__).resolve().parents[3] / "world_data" / "rosters"
LIFE_EXPECTANCY = 76.0
SPAWN_RING = ((0, 0), (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (-1, -1), (1, -1), (2, 0), (0, 2), (-2, 0), (0, -2))
_CACHE = {}


def roster_dir():
    """Directory holding the ``<map_id>.json`` rosters (``EDEN_ROSTER_DIR`` or ``world_data/rosters``)."""
    return Path(os.environ.get("EDEN_ROSTER_DIR", ROSTER_DIR))


def roster_path(map_id):
    """Path of the roster file of ``map_id``."""
    return roster_dir() / f"{map_id}.json"


def clear_roster_cache():
    """Forget the parsed rosters (tests, or before a new world is created from an edited file)."""
    _CACHE.clear()


def roster_for_map(map_id):
    """The parsed roster for ``map_id`` or None if there is no file. A broken file raises (never silently ignored)."""
    path = roster_path(map_id)
    key = (str(path), path.stat().st_mtime_ns if path.exists() else None)
    if key in _CACHE:
        return _CACHE[key]
    if not path.exists():
        _CACHE[key] = None
        return None
    roster, issues = load_roster(path)
    if roster is None:
        raise ValueError(f"roster {path.name} is invalid: " + "; ".join(str(i) for i in issues if i.severity == "error"))
    _CACHE[key] = roster
    return roster


def has_roster(map_id):
    """True when the map is registered, has a roster file, and every anchor the roster names is placed.

    A world that placed only part of the maps (e.g. the village without the smith interior) has no usable roster."""
    from systems.movement.map_contract import get_map_contract
    from .validate import anchors_from_registry
    if not (isinstance(map_id, str) and get_map_contract(map_id) is not None and roster_path(map_id).exists()):
        return False
    roster = roster_for_map(map_id)
    anchors = anchors_from_registry(map_id)
    return roster is not None and all(a in anchors for r in roster.residents for a in r.anchors.values())


def world_has_roster(engine):
    """True when this running world was built from a roster, judged by its own residents (their ``roster`` bindings),
    never by the roster file: editing or breaking the file while the server runs must not change a live world's rules
    (a file with new residents once switched a running world to legacy NPC behaviour and residents died).
    A True answer is remembered for the world epoch; a False one is re-checked every 100 ticks."""
    from systems.movement.map_contract import get_map_contract
    if engine is None or get_map_contract(getattr(engine, "_map_name", None)) is None:
        return False
    cached = engine.__dict__.get("_roster_world")
    tick = int(getattr(engine, "tick", 0))
    if cached is not None and cached[0] == engine.world_epoch and (cached[1] or tick - cached[2] < 100):
        return cached[1]
    found = False
    for human_id in engine._human_uid_by_slot:
        if human_id and (engine.resident_store.get(human_id) or {}).get("roster"):
            found = True
            break
    engine.__dict__["_roster_world"] = (engine.world_epoch, found, tick)
    return found


def _new_human_slots(engine, before):
    import genesis_config as cfg
    after = set(int(s) for s in (engine.state.h_tensor[:, cfg.TYPE] != 0).nonzero(as_tuple=False).flatten().tolist())
    return sorted(after - before)


def apply_roster(engine, map_name, roster=None):
    """Spawn and configure the roster's residents. Returns {roster key: human id}. Raises on an invalid roster."""
    import genesis_config as cfg
    from systems.inventory.ops import add_item
    from systems.movement.map_contract import get_map_contract
    from systems.movement.spatial import world_contract
    from systems.occupation.assign import assign_occupation
    from systems.personality.assign import assign_personality, top_traits

    roster = roster or roster_for_map(map_name)
    if roster is None:
        return {}
    problems = [i for i in validate_roster_for_world(roster, map_name, world_contract(engine)) if i.severity == "error"]
    if problems:
        raise ValueError("roster does not fit the loaded maps: " + "; ".join(str(i) for i in problems))
    anchors = anchors_from_registry(map_name)
    radius = get_map_contract(map_name)["actor_radius"]
    used_ring = {}
    spawned = {}
    for resident in roster.residents:
        spawn_id = resident.anchors["spawn"]
        ax, ay = anchors[spawn_id]["position"]
        before = set(int(s) for s in (engine.state.h_tensor[:, cfg.TYPE] != 0).nonzero(as_tuple=False).flatten().tolist())
        for attempt in range(used_ring.get(spawn_id, 0), len(SPAWN_RING)):
            dx, dy = SPAWN_RING[attempt]
            used_ring[spawn_id] = attempt + 1
            if engine.spawn(ax + dx * 2.0 * radius, ay + dy * 2.0 * radius, float(resident.sex), LIFE_EXPECTANCY + resident.age * 0.0,
                            age=resident.age, preferred_name=resident.name):
                break
        else:
            raise ValueError(f"could not place roster resident {resident.key!r} near anchor {spawn_id!r}")
        new_slots = _new_human_slots(engine, before)
        if len(new_slots) != 1:
            raise ValueError(f"spawning {resident.key!r} created {len(new_slots)} humans")
        spawned[resident.key] = new_slots[0]
    h_mask, _, entity_mask = engine._current_masks()
    engine._assign_missing_ids(h_mask, entity_mask)  # creates the resident records
    result = {}
    for resident in roster.residents:
        slot = spawned[resident.key]
        human_id = engine._human_uid_by_slot[slot]
        record = engine.resident_store.get(human_id)
        personality = assign_personality(human_id, resident.sex, preferred_archetype=resident.archetype)
        personality["traits"].update(resident.traits)
        personality["top_traits"] = top_traits(personality["traits"])
        record["personality"] = personality
        if resident.role:
            record["occupation"] = assign_occupation(human_id, personality=personality, preferred_kind=resident.role)
        record["schedule_profile"], record["schedule_state"] = {}, {}
        record["roster"] = {"key": resident.key, "role": resident.role, "work_mode": resident.work_mode, "map_id": roster.map_id,
                            "anchors": dict(resident.anchors), "needs_scale": roster.needs_scale,
                            "age_scale": roster.age_scale, "needs": json.loads(json.dumps(roster.needs)),
                            "needs_sites": resident.needs_sites}
        engine.resident_store._ensure_behavior_state(record, human_id=human_id, tick=engine.tick)
        engine.resident_store.touch_resident(human_id)
        spec = resident.inventory or {}
        inventory = engine._human_inventory_record(human_id, capacity_slots=spec.get("slots"), capacity_weight=spec.get("weight"))
        for kind, quantity in {**resident.stock, **resident.personal}.items():
            added = add_item(inventory, kind, quantity)
            if added["added"] != quantity:
                raise ValueError(f"roster resident {resident.key!r}: no room for {quantity} x {kind} ({added['added']} fit)")
        engine._inventory_seeded_humans.add(human_id)  # the roster is the whole seed: no default weapon or coin on top
        result[resident.key] = human_id
    engine.prime_protocol_state()  # ids, provisioning and payloads for the finished residents
    return result
