"""The three v1 powers plus time control. Each returns a plain result dict; ``dry_run`` previews without changing anything."""
import genesis_config as cfg

from systems.inventory.ops import add_item, remove_item
from systems.inventory.resolver import can_add_item
from systems.nature.weather import WEATHER_MODIFIERS, season_for_tick

from .events import commit_event
from .state import TIME_SCALES, is_paused, set_paused, store, witnesses

MAX_HP = 100.0
RESOURCES = {"iron_ingot": ("iron_ingot", 20), "wood": ("wood_bundle", 20), "food": ("rations", 20), "water": ("water_flask", 20),
             "coin": ("coin", 200)}
WEATHERS = tuple(WEATHER_MODIFIERS)  # the kinds the nature system understands
DEFAULT_WEATHER_TICKS = 600


def _resident(engine, human_id):
    slot = engine._human_slot_for_id(human_id) if isinstance(human_id, str) else -1
    if slot < 0:
        return None, None, "unknown_resident"
    row = engine.state.h_tensor[slot]
    if float(row[cfg.TYPE]) != cfg.AGENT_TYPE_HUMAN or float(row[cfg.HP]) <= 0.0:
        return slot, None, "dead_resident"  # never resurrection
    return slot, row, None


def heal(engine, payload):
    """God power: restore hit points (default: to full); the dead are never resurrected."""
    slot, row, problem = _resident(engine, payload.get("target_id"))
    if problem:
        return {"ok": False, "reason": problem}
    amount = payload.get("amount", MAX_HP)
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 < amount <= MAX_HP:
        return {"ok": False, "reason": "invalid_amount"}
    before = float(row[cfg.HP])
    after = min(MAX_HP, before + float(amount))
    result = {"ok": True, "target_id": payload["target_id"], "hp_before": round(before, 2), "hp_after": round(after, 2),
              "healed": round(after - before, 2)}
    if payload.get("dry_run"):
        return {**result, "dry_run": True}
    if after <= before:
        return {**result, "god_event_id": None}  # already at full health: nothing happened, nothing is remembered
    row[cfg.HP] = after
    point = (float(row[cfg.X]), float(row[cfg.Y]))
    event = commit_event(engine, "divine_heal", point=point, target_id=payload["target_id"],
                         witnesses=witnesses(engine, point, always=(payload["target_id"],)), extra={"healed": result["healed"]})
    return {**result, "god_event_id": event["id"], "witnesses": len(event["witnesses"])}


def _container_target(engine, entity_id):
    if not isinstance(entity_id, str) or entity_id not in engine._entity_uid_by_slot:
        return None, None, "unknown_container"
    slot = engine._entity_uid_by_slot.index(entity_id)
    if int(engine.state.m_tensor[slot, cfg.M_TYPE]) != int(cfg.M_STORAGE_CASE):
        return None, None, "not_a_container"
    point = (float(engine.state.m_tensor[slot, cfg.CX]), float(engine.state.m_tensor[slot, cfg.CY]))
    return engine._storage_case_inventory_record(entity_id), point, None


def spawn_resource(engine, payload):
    """God power: put a whitelisted resource into a resident's or a container's inventory, all or nothing."""
    resource = payload.get("resource")
    if resource not in RESOURCES:
        return {"ok": False, "reason": "resource_not_allowed", "allowed": sorted(RESOURCES)}
    item_kind, limit = RESOURCES[resource]
    quantity = payload.get("quantity", 1)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= limit:
        return {"ok": False, "reason": "invalid_quantity", "max": limit}
    target_kind, target_id = payload.get("target_kind"), payload.get("target_id")
    if target_kind == "resident":
        slot, row, problem = _resident(engine, target_id)
        if problem:
            return {"ok": False, "reason": problem}
        record = engine._human_inventory_record(target_id)
        point = (float(row[cfg.X]), float(row[cfg.Y]))
        always = (target_id,)
    elif target_kind == "container":
        record, point, problem = _container_target(engine, target_id)
        if problem:
            return {"ok": False, "reason": problem}
        always = ()
    else:
        return {"ok": False, "reason": "invalid_target_kind"}
    result = {"ok": True, "resource": resource, "item_kind": item_kind, "quantity": quantity, "target_kind": target_kind, "target_id": target_id}
    if not can_add_item(record, item_kind, quantity):
        return {"ok": False, "reason": "no_room", "target_id": target_id}
    if payload.get("dry_run"):
        return {**result, "dry_run": True}
    added = add_item(record, item_kind, quantity)
    if added["added"] != quantity:  # all or nothing
        if added["added"]:
            remove_item(record, item_kind, added["added"])
        return {"ok": False, "reason": "no_room", "target_id": target_id}
    receivers = witnesses(engine, point, always=always)
    event = commit_event(engine, "divine_gift", point=point, target_id=target_id if target_kind == "resident" else None,
                         witnesses=receivers, extra={"resource": resource, "quantity": quantity, "target_kind": target_kind,
                                                     "target": target_id})
    engine._force_frame_refresh = True
    return {**result, "god_event_id": event["id"], "witnesses": len(event["witnesses"])}


def set_weather(engine, payload):
    """God power: set the weather of every exterior map for ``duration_ticks`` (``dry_run`` only previews)."""
    kind = payload.get("weather")
    if kind not in WEATHERS:
        return {"ok": False, "reason": "weather_not_supported", "supported": list(WEATHERS)}
    duration = payload.get("duration_ticks", DEFAULT_WEATHER_TICKS)
    if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 100000:
        return {"ok": False, "reason": "invalid_duration"}
    state = engine._nature_state
    current = str(state.get("weather", "clear"))
    outdoors = witnesses(engine, (0.0, 0.0), exterior_only=True)
    preview = {"weather": kind, "previous": current, "duration_ticks": duration, "affected_residents": sorted(outdoors),
               "affected_area": "every exterior map", "reversible": True, "effects": dict(WEATHER_MODIFIERS[kind])}
    if payload.get("dry_run"):
        return {"ok": True, "dry_run": True, **preview}
    if kind == current:
        return {"ok": True, "changed": False, **preview, "god_event_id": None}
    state.setdefault("season", season_for_tick(engine.tick))
    state.update(weather=kind, weather_started_tick=engine.tick, weather_duration_ticks=duration, weather_ends_tick=engine.tick + duration)
    from systems.roster.apply import world_has_roster
    ledger = store(engine)
    if kind != "clear" and world_has_roster(engine):  # the nature cycle is off there: ``expire_weather`` ends it (see expiry.py)
        ledger["weather"] = {"kind": kind, "ends_tick": engine.tick + duration}
    else:
        ledger.pop("weather", None)
    event = commit_event(engine, "weather_changed", point=(0.0, 0.0), witnesses=outdoors, note=f"the weather turned {kind}",
                         extra={"weather": kind, "previous": current})
    return {"ok": True, "changed": True, **preview, "god_event_id": event["id"]}


def time_state(engine):
    """``{paused, time_scale, tick}`` as reported to clients."""
    return {"paused": is_paused(engine), "time_scale": engine.scheduler.time_scale, "tick": engine.tick}


def time_control(engine, payload):
    """God power: pause, resume or set the time scale."""
    action = payload.get("action")
    if action == "pause":
        set_paused(engine, True)
    elif action == "resume":
        set_paused(engine, False)
    elif action == "scale":
        scale = payload.get("scale")
        if isinstance(scale, bool) or scale not in TIME_SCALES:
            return {"ok": False, "reason": "scale_not_allowed", "allowed": list(TIME_SCALES)}
        engine.scheduler.set_time_scale(float(scale))
    else:
        return {"ok": False, "reason": "invalid_time_action"}
    return {"ok": True, **time_state(engine)}
