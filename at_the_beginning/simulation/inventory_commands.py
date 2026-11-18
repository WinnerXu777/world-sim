"""Validated gameplay inventory operations using the existing inventory domain."""
import math
import genesis_config as cfg
from systems.inventory import (get_inventory, get_owner_inventory, get_container_inventory,
                               transfer_item, equip_main_hand_item, inventory_prompt_payload)


def resolve(engine, payload, prefix):
    if payload.get(f"{prefix}_inventory_id"):
        return get_inventory(engine.inventory_state, payload[f"{prefix}_inventory_id"])
    if payload.get(f"{prefix}_container_id"):
        return get_container_inventory(engine.inventory_state, payload[f"{prefix}_container_id"])
    return get_owner_inventory(engine.inventory_state, payload.get(f"{prefix}_owner_kind", ""),
                               payload.get(f"{prefix}_owner_id", ""))


def execute(engine, action, payload):
    session = engine.player_control.sessions_by_controller[payload["controller_id"]]
    own = get_owner_inventory(engine.inventory_state, "human", session["target_id"])
    if own is None:
        return {"ok": False, "reason": "inventory_not_found"}
    if action == "equip":
        if payload.get("owner_kind", "human") != "human" or payload.get("owner_id") != session["target_id"]:
            return {"ok": False, "reason": "inventory_not_controlled"}
        item = equip_main_hand_item(own, str(payload.get("item_id", "")))
        if item is None:
            return {"ok": False, "reason": "item_not_equippable"}
        result = {"ok": True, "equipped": item, "inventory": inventory_prompt_payload(own, limit=12)}
    elif action == "transfer":
        quantity = payload.get("quantity", 1)
        if type(quantity) is not int or not 1 <= quantity <= 10000:
            return {"ok": False, "reason": "invalid_quantity"}
        source, target = resolve(engine, payload, "source"), resolve(engine, payload, "target")
        if source is None or target is None:
            return {"ok": False, "reason": "inventory_not_found"}
        if source is target or (source is not own and target is not own):
            return {"ok": False, "reason": "inventory_not_controlled"}
        other = target if source is own else source
        entity_id = other.get("owner_id")
        if other.get("owner_kind") != "container" or entity_id not in engine._entity_uid_by_slot:
            return {"ok": False, "reason": "container_required"}
        slot = engine._entity_uid_by_slot.index(entity_id)
        h, m = engine.state.h_tensor[session["slot"]], engine.state.m_tensor[slot]
        if m[cfg.M_TYPE] <= 0 or math.hypot(float(h[cfg.X] - m[cfg.CX]), float(h[cfg.Y] - m[cfg.CY])) > 30:
            return {"ok": False, "reason": "container_out_of_reach"}
        result = transfer_item(source, target, item_kind=payload.get("item_kind") or None,
                               item_id=str(payload.get("item_id", "")), quantity=quantity)
        result.update(source_inventory=inventory_prompt_payload(source, limit=12),
                      target_inventory=inventory_prompt_payload(target, limit=12))
    else:
        return {"ok": False, "reason": "invalid_inventory_action"}
    engine._force_frame_refresh = True
    engine._force_map_refresh = True
    return result
