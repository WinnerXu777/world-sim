"""World memento: format 1 (schema 1) by default; format 2 (schema 2, 1008 P3) under EDEN_SPACES=1; format 3 (schema 3, 1008 P5) under EDEN_WINDOW=1; format 4
(schema 4) is format 3 plus the dormant structure store, written only while built structures are stored away (EDEN_STRUCTURE_STORE=1). Under EDEN_CALENDAR=1 the
world format carries ``calendar = {profile, day_ticks, year_ticks}`` (an optional key: absent means the original short calendar; no format number changes).
Explicit state, no executable objects or model handles."""
from __future__ import annotations

import random
import uuid

import numpy as np
import torch

from . import codec, map_guard

REFUSAL_FORMAT_1_WITH_SPACES = (
    "This save was made by an earlier version of the game (world format 1), in which interiors shared the overworld's coordinate frame. This version keeps interiors as separate spaces (world format 2), so the save cannot be continued. Start a new world; the old save file has not been changed or deleted."
)
REFUSAL_FORMAT_2_WITHOUT_SPACES = (
    'This save was made with separate interior spaces (world format 2, EDEN_SPACES=1), but this session runs without them, so it cannot be continued. Start the game with EDEN_SPACES=1 to continue it. The save file has not been changed.'
)
REFUSAL_FORMAT_12_WITH_WINDOW = (
    "This save was made before the streaming world existed (world format 1 or 2), in which the whole map was one fixed area. This session runs the streaming world (world format 3, EDEN_WINDOW=1), so the save cannot be continued. Start a new world, or start the game without EDEN_WINDOW=1 to continue the save. The save file has not been changed."
)
REFUSAL_FORMAT_3_WITHOUT_WINDOW = (
    "This save was made with the streaming world (world format 3, EDEN_WINDOW=1), but this session runs without it, so it cannot be continued. Start the game with EDEN_WINDOW=1 and EDEN_SPACES=1 to continue it. The save file has not been changed."
)


REFUSAL_FORMAT_4_UNSUPPORTED = (
    "This save contains buildings stored away from the player (the dormant structure store), which this build cannot load, so it cannot be continued. Use a build with EDEN_STRUCTURE_STORE support, or start a new world. The save file has not been changed."
)
REFUSAL_CALENDAR_LONG_WITHOUT = (
    "This save was made with the long calendar (a game day is 12000 ticks, EDEN_CALENDAR=1), but this session runs without it, so it cannot be continued. Start the game with EDEN_CALENDAR=1 to continue it. The save file has not been changed."
)
REFUSAL_CALENDAR_SHORT_WITH = (
    "This save was made with the original short calendar (a game day is 2400 ticks), whose hunger, growth, weather and ageing rates differ from the long calendar (EDEN_CALENDAR=1), so it cannot be continued in this session. Start a new world, or start the game without EDEN_CALENDAR=1 to continue the save. The save file has not been changed."
)
REFUSAL_CALENDAR_DIFFERENT = (
    "This save was made with a long calendar whose game day is {saved_day} ticks and whose year is {saved_year} ticks, "
    "but this session's long calendar has a game day of {now_day} ticks and a year of {now_year} ticks, so hunger, growth, weather and ageing "
    "would run at different rates and the save cannot be continued. Use the build the save was made with, or start a new world. "
    "The save file has not been changed."
)


REFUSAL_OFFSCREEN_WITHOUT = (
    "This save has children born in a village while the player was away who are still waiting to be placed (offscreen villages, EDEN_OFFSCREEN=1), "
    "but this session runs without it, so they would be lost and the save cannot be continued. Start the game with EDEN_OFFSCREEN=1 (and "
    "EDEN_WINDOW_DORMANCY=1) to continue it. The save file has not been changed."
)


class SaveFormatError(ValueError):
    """The save's world format does not match this session's (flag EDEN_SPACES); raised by ``validate`` before anything is changed."""


def current_format() -> int:
    """World format this session writes and reads: 3 with EDEN_WINDOW=1 (the streaming world), 2 with EDEN_SPACES=1 (interiors are separate
    spaces), else 1 (unchanged)."""
    try:
        from harness.numerics import spaces_enabled, window_enabled
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness.numerics import spaces_enabled, window_enabled
    if window_enabled():
        return 3
    return 2 if spaces_enabled() else 1


def _calendar_section() -> dict:
    """What a save needs of the active calendar (``harness.calendar.describe``): the three numbers that decide every rate."""
    try:
        from harness import calendar
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar
    facts = calendar.describe()
    return {"profile": facts["profile"], "day_ticks": facts["day_ticks"], "year_ticks": facts["year_ticks"]}


def _calendar_enabled() -> bool:
    try:
        from harness import calendar
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar
    return calendar.calendar_enabled()


def _check_calendar(payload) -> None:
    """The save's calendar must be this session's: a save without the key was made with the short calendar, a save with it needs EDEN_CALENDAR=1."""
    world_format = payload.get("world_format")
    saved = world_format.get("calendar") if isinstance(world_format, dict) else None
    if saved is None and _calendar_enabled():
        raise SaveFormatError(REFUSAL_CALENDAR_SHORT_WITH)
    if saved is not None and not _calendar_enabled():
        raise SaveFormatError(REFUSAL_CALENDAR_LONG_WITHOUT)
    if saved is not None:
        current = _calendar_section()
        if saved != current:
            raise SaveFormatError(REFUSAL_CALENDAR_DIFFERENT.format(
                saved_day=saved["day_ticks"], saved_year=saved["year_ticks"],
                now_day=current["day_ticks"], now_year=current["year_ticks"],
            ))


def _space_layout(map_name) -> list:
    """[{"space", "map_id", "origin"}, ...] of the registered authored world ``map_name`` (the part of the registry a format-2 save depends on)."""
    import types
    try:
        from harness.spaces import space_table
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness.spaces import space_table
    return [{"space": row["space"], "map_id": row["map_id"], "origin": row["origin"]}
            for row in space_table(types.SimpleNamespace(_map_name=map_name))]


ENGINE_FIELDS = (
    "tick", "_pop_count", "_entity_count_ref", "_map_name", "inventory_state",
    "_next_human_uid", "_next_entity_uid", "_event_seq", "_human_uid_by_slot", "_entity_uid_by_slot",
    "_pending_human_names_by_slot", "_pending_birth_links_by_slot", "_incarnated_human_by_controller",
    "_pending_events", "_pending_despawns", "_frontier_state", "_nature_state",
    "_inventory_seeded_humans", "_inventory_seeded_containers", "_starter_storage_case_entity_id",
    "_actor_prev_positions", "_actor_prev_facing_yaw", "_actor_render_hints", "_actor_render_actions",
    "_prev_h_mask", "_prev_a_mask", "_prev_entity_mask", "_map_state_version", "_frame_id",
)
RUNTIMES = ("world_agent", "human_agent", "talk_agent", "orchestrator", "tiny_model_runtime")


def capture(engine, geometry) -> bytes:
    """Serialize the whole world (tensors, residents, runtimes, RNG, map manifest) into one byte string."""
    map_guard.record(engine)  # which authored map files this world runs on (schema-free, inside inventory_state)
    # All authoritative resident records, including dead/offscreen residents.
    residents = {path.stem: engine.resident_store.get(path.stem)
                 for path in engine.resident_store.root_dir.glob("*.json")}
    residents.update(engine.resident_store._cache)
    payload = {"schema": current_format(), "engine": {name: getattr(engine, name) for name in ENGINE_FIELDS},
        "humans": engine.state.h_tensor, "entities": engine.state.m_tensor,
        "geometry": _geometry_section(geometry),
        "residents": residents,
        "runtimes": {name: {k: v for k, v in vars(getattr(engine, name)).items() if k != "resident_store"}
                     for name in RUNTIMES},
        "instinct_bits": engine.execution_agent._instinct_bits,
        "registry": [entry["fn"].__name__ for entry in engine._registry],
        "rng": {"python": random.getstate(), "numpy": np.random.get_state(),
                "torch": torch.random.get_rng_state(),
                "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []}}
    if payload["schema"] == 2:  # EDEN_SPACES: which spaces the M_SPACE / H_SPACE columns refer to
        payload["world_format"] = {"format": 2, "spaces": _space_layout(engine._map_name)}
    if payload["schema"] == 3:  # EDEN_WINDOW: the streaming window (origin, integrated chunks, deltas) and what the chunks were generated from
        from harness import window_manager
        from systems.worldgen import GENERATOR_VERSION
        manager = getattr(engine, "_window", None)
        window = manager.snapshot() if manager is not None else dict(origin=[0, 0], epoch=0, chunks=[], deltas=[], owned=[], log=[])
        payload["world_format"] = {"format": 3, "spaces": _space_layout(engine._map_name), "generator_version": GENERATOR_VERSION,
                                   "world_seed": str(window_manager.world_seed_of(engine)), "origin": window["origin"], "epoch": window["epoch"]}
        payload["window"] = window
        offscreen_section = _offscreen().export(engine) if _offscreen().enabled() else None
        if offscreen_section:                       # EDEN_OFFSCREEN with births still to place: an optional key, so every other save is unchanged
            window["offscreen"] = offscreen_section
        if "structures" in window:                  # EDEN_STRUCTURE_STORE with structures stored away: world format 4 (an empty store stays format 3)
            payload["schema"] = 4
            payload["world_format"]["format"] = 4
    if _calendar_enabled():                         # EDEN_CALENDAR: an optional key, so every flag-off save is byte-identical to today
        payload.setdefault("world_format", {"format": payload["schema"]})["calendar"] = _calendar_section()
    # Encoding copies tensors and mutable dictionaries before the first await/worker handoff.
    return codec.dumps(payload)


def _geometry_section(geometry) -> dict:
    """Dense frame (today's format): the shapes with their full masks.  Sparse frame (EDEN_WINDOW): shape parameters only plus the frame;
    ``restore`` rebuilds the boxes, the tile owners (last-writer order) are saved as they are."""
    if not geometry.sparse_enabled():
        return {"shapes": geometry.MAP_GEO, "tiles": geometry.TILE_TO_ENTITY, "version": geometry.geo_version}
    return {"shapes": {eid: {k: v for k, v in geo.items() if k != "tile_box"} for eid, geo in geometry.MAP_GEO.items()},
            "tiles": geometry.TILE_TO_ENTITY, "version": geometry.geo_version, "frame": geometry.window_frame()}


def _require_known_map(name) -> None:
    """Refuse worlds whose map has neither a built-in generator nor a registered authored contract.

    The authored contract (radius, bounds, walls) is configuration, not save data; without it the world would
    silently load with the legacy 0.35 radius and 1200x900 bounds.
    """
    from initial_map_design import MAP_REGISTRY
    from systems.movement.map_contract import get_map_contract
    if isinstance(name, str) and (name in MAP_REGISTRY or get_map_contract(name) is not None):
        return
    raise ValueError(f"Saved world uses map {name!r}, which is not a built-in map and has no registered authored map "
                     f"contract; register its map file (EDEN_MAP_FILES) and try again")


def validate(payload, engine) -> None:
    """Refuse a payload that does not fit this engine (schema, map, map manifest, registry, tensors, RNG); changes nothing."""
    schema, expected = payload.get("schema"), current_format()
    if expected == 3 and schema in (1, 2):
        raise SaveFormatError(REFUSAL_FORMAT_12_WITH_WINDOW)
    if schema in (3, 4) and expected != 3:
        raise SaveFormatError(REFUSAL_FORMAT_3_WITHOUT_WINDOW)
    if schema == 4 and not _structure_store_enabled():
        raise SaveFormatError(REFUSAL_FORMAT_4_UNSUPPORTED)
    if schema == 1 and expected == 2:
        raise SaveFormatError(REFUSAL_FORMAT_1_WITH_SPACES)
    if schema == 2 and expected == 1:
        raise SaveFormatError(REFUSAL_FORMAT_2_WITHOUT_SPACES)
    if schema != expected and not (schema == 4 and expected == 3):
        raise ValueError("Unsupported world schema; migration required")
    _check_calendar(payload)
    window_section = payload.get("window")
    if isinstance(window_section, dict) and "offscreen" in window_section and not _offscreen().enabled():
        raise SaveFormatError(REFUSAL_OFFSCREEN_WITHOUT)
    if set(payload["engine"]) != set(ENGINE_FIELDS) or set(payload["runtimes"]) != set(RUNTIMES):
        raise ValueError("World state schema mismatch")
    _require_known_map(payload["engine"].get("_map_name"))
    map_guard.check(payload)  # refuses a save made with a different map file (gameplay profile)
    if schema == 2:
        saved = payload.get("world_format")
        if not isinstance(saved, dict) or saved.get("format") != 2 or saved.get("spaces") != _space_layout(payload["engine"].get("_map_name")):
            raise ValueError("This save's interior spaces (world format 2) do not match the maps registered in this session; "
                             "register the same map files and origins (EDEN_MAP_FILES, EDEN_MAP_ORIGINS) and try again")
    if schema in (3, 4):
        _validate_window(payload, engine)
    for name, expected in (("humans", engine.state.h_tensor), ("entities", engine.state.m_tensor)):
        value = payload[name]
        if not isinstance(value, torch.Tensor) or value.shape != expected.shape or value.dtype != expected.dtype:
            raise ValueError("Tensor schema mismatch; migration required")
    try:
        import map_geo as geometry
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import map_geo as geometry
    saved_frame = payload["geometry"].get("frame")
    if saved_frame != (geometry.window_frame() if geometry.sparse_enabled() else None):
        raise ValueError("This save's map geometry frame (sparse window) does not match this session's; start the same window configuration")
    if payload["registry"] != [entry["fn"].__name__ for entry in engine._registry]:
        raise ValueError("Simulation registry differs; migration required")
    for name, attributes in payload["runtimes"].items():
        allowed = set(vars(getattr(engine, name))) - {"resident_store"}
        if set(attributes) != allowed:
            raise ValueError(f"Runtime schema mismatch: {name}")
    if not isinstance(payload["residents"], dict) or any(not isinstance(v, dict) for v in payload["residents"].values()):
        raise ValueError("Invalid resident records")
    if len(payload["engine"]["_human_uid_by_slot"]) != len(engine._human_uid_by_slot):
        raise ValueError("Human ID capacity mismatch")
    if len(payload["engine"]["_entity_uid_by_slot"]) != len(engine._entity_uid_by_slot):
        raise ValueError("Entity ID capacity mismatch")
    random.Random().setstate(payload["rng"]["python"])
    np.random.RandomState().set_state(payload["rng"]["numpy"])
    torch.Generator().set_state(payload["rng"]["torch"])
    if len(payload["rng"]["cuda"]) != torch.cuda.device_count():
        raise ValueError("CUDA RNG device count differs; save migration required")


def _offscreen():
    try:
        from harness import offscreen
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import offscreen
    return offscreen


def _structure_store_enabled() -> bool:
    try:
        from harness import structure_store
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import structure_store
    return structure_store.enabled()


def _validate_window(payload, engine) -> None:
    """World format 3 (or 4, with the dormant structure store): same interiors in the same pockets, same generator and seed, and a window section that matches the saved rows."""
    from harness import window_manager
    from systems.worldgen import GENERATOR_VERSION
    saved = payload.get("world_format")
    if not isinstance(saved, dict) or saved.get("format") != payload["schema"] or saved.get("spaces") != _space_layout(payload["engine"].get("_map_name")):
        raise ValueError("This save's interior spaces (world format 3) do not match the maps registered in this session; "
                         "register the same map files (EDEN_MAP_FILES) and try again")
    if saved.get("generator_version") != GENERATOR_VERSION:
        raise ValueError(f"This save's world was generated by generator version {saved.get('generator_version')!r}; this session runs "
                         f"{GENERATOR_VERSION!r}, which would generate a different world. Use the version the save was made with.")
    seed = str(window_manager.world_seed_of(engine))
    if saved.get("world_seed") != seed:
        raise ValueError(f"This save's world seed is {saved.get('world_seed')!r}; this session's is {seed!r} (EDEN_WORLD_SEED). Start with the seed the save was made with.")
    window = payload.get("window")
    keys = {"origin", "epoch", "chunks", "deltas", "owned", "log"}
    optional = {"dormant_since", "structures", "offscreen"} if payload["schema"] == 4 else {"dormant_since", "offscreen"}
    if isinstance(window, dict) and "offscreen" in window:
        _offscreen().validate_section(window["offscreen"])
    if payload["schema"] == 4:
        try:
            from harness.structure_store import StructureStore
        except ImportError:  # pragma: no cover - package import fallback
            from at_the_beginning.harness.structure_store import StructureStore
        StructureStore.validate(window.get("structures") if isinstance(window, dict) else None)
    if not isinstance(window, dict) or set(window) - optional != keys or window["origin"] != saved.get("origin") or window["epoch"] != saved.get("epoch"):
        raise ValueError("Invalid streaming window section")
    uids = payload["engine"]["_entity_uid_by_slot"]
    owned = set(window["owned"])
    claimed = set()
    for chunk in window["chunks"]:
        if len(chunk["slots"]) != len(chunk["uids"]) or len(chunk["baseline"]) != len(chunk["slots"]):
            raise ValueError("Invalid streaming window chunk record")
        for slot, uid in zip(chunk["slots"], chunk["uids"]):
            if not (isinstance(slot, int) and 0 <= slot < len(uids)) or uids[slot] != uid or slot not in owned:
                raise ValueError("The streaming window's rows do not match the saved entities")
            claimed.add(slot)
    if not claimed <= owned or any(not (isinstance(s, int) and 0 <= s < len(uids)) for s in owned):
        raise ValueError("The streaming window's rows do not match the saved entities")


def restore(payload, engine, geometry, control_factory) -> None:
    """Replace the running world with the payload (validated first)."""
    validate(payload, engine)
    # Decoding/validation must finish before mutating the current world.
    engine.reset_world()
    device = engine.state.device
    engine.state.h_tensor.copy_(payload["humans"].to(device))
    engine.state.m_tensor.copy_(payload["entities"].to(device))
    for name, value in payload["engine"].items():
        setattr(engine, name, value.to(device) if isinstance(value, torch.Tensor) else value)
    if "frame" in payload["geometry"]:
        geometry.restore_shapes(payload["geometry"]["shapes"], device)
    else:
        geometry.MAP_GEO.update(payload["geometry"]["shapes"])
        for shape in geometry.MAP_GEO.values():
            shape["tile_mask"] = shape["tile_mask"].to(device)
    geometry.TILE_TO_ENTITY.update(payload["geometry"]["tiles"])
    geometry.geo_version = payload["geometry"]["version"]
    engine.resident_store._cache.update(payload["residents"])
    engine.resident_store._dirty.update(payload["residents"])
    engine.resident_store._memory_dirty.update(payload["residents"])
    for name, attributes in payload["runtimes"].items():
        vars(getattr(engine, name)).update(attributes)
    # G-005: a save made before EDEN_MAP_RESOURCES (inert map objects) gets its resource rows once; a no-op with the flag off
    try:
        from systems.map.authored import upgrade_authored_entities
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.systems.map.authored import upgrade_authored_entities
    upgrade_authored_entities(engine, engine._map_name)
    engine.execution_agent._instinct_bits = payload["instinct_bits"]
    engine.player_control = control_factory()
    # Old key holds and in-flight conversation requests belong to the old epoch.
    engine.talk_agent._pending_direct.clear()
    engine.talk_agent._pending_ambient.clear()
    engine.talk_agent._pending_npc.clear()
    engine.world_epoch = str(uuid.uuid4())
    if payload["schema"] in (3, 4):                 # after the new epoch: a manager is rebuilt whenever its epoch differs from the engine's
        from harness import window_manager
        window_manager.restore_manager(engine, payload["window"])
        if _offscreen().enabled():                  # EDEN_OFFSCREEN: births counted while away and not placed yet (none: an empty list)
            _offscreen().load(engine, payload["window"].get("offscreen"))
    engine.world_loaded = True
    engine._runtime_profile = "full"
    engine._map_geo_version_sent = geometry.geo_version
    engine._last_exported_map_entities = engine._export_map_entities()
    engine._build_bootstrap_payload(engine._last_exported_map_entities)
    h_mask, a_mask, _ = engine._current_masks()
    engine._build_frame_payload(h_mask, a_mask)
    engine._force_frame_refresh = True
    engine._force_map_refresh = True
    random.setstate(payload["rng"]["python"])
    np.random.set_state(payload["rng"]["numpy"])
    torch.random.set_rng_state(payload["rng"]["torch"])
    if payload["rng"]["cuda"]:
        torch.cuda.set_rng_state_all(payload["rng"]["cuda"])
