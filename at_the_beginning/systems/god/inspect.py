"""GET /god/inspect/{resident_id}: a read-only view of one resident with a plain-language explanation of what they are doing."""
from systems.roster.driver import roster_of, runtime

from .state import map_id_at


def _needs(row, cfg):
    return {"hp": round(float(row[cfg.HP]), 1), "hunger": round(float(row[cfg.HUNGER]), 1), "thirst": round(float(row[cfg.THIRST]), 1),
            "stamina": round(float(row[cfg.H_STAMINA]), 1)}


def inspect_resident(engine, human_id):
    """Read model behind ``GET /god/inspect/{id}``: needs, place, routine, relationships, recent events, open orders and an explanation sentence."""
    import genesis_config as cfg
    slot = engine._human_slot_for_id(human_id) if isinstance(human_id, str) else -1
    resident = engine.resident_store.get(human_id) if slot >= 0 else None
    if resident is None:
        return {"ok": False, "reason": "unknown_resident"}
    row = engine.state.h_tensor[slot]
    alive = float(row[cfg.TYPE]) == cfg.AGENT_TYPE_HUMAN and float(row[cfg.HP]) > 0.0
    name = resident["profile"]["name"]
    roster, _ = roster_of(engine, human_id)
    role = (roster or {}).get("role") or (resident.get("occupation") or {}).get("kind") or "villager"
    position = (round(float(row[cfg.X]), 1), round(float(row[cfg.Y]), 1))
    state = runtime(engine)
    routine = (resident.get("schedule_state", {}).get("current_routine") or {}).get("kind", "")
    goal, at = state.goal_key.get(human_id), state.at_anchor.get(human_id)
    controlled = engine.player_control.describe_human_slot(slot) is not None
    relationships = []
    for other, relation in sorted((resident.get("relationships") or {}).items()):
        other_record = engine.resident_store.get(other) or {}
        relationships.append({"id": other, "name": (other_record.get("profile") or {}).get("name", other), "kind": relation.get("kind"),
                              "closeness": relation.get("closeness"), "tags": list(relation.get("tags", []))})
    events = [{"tick": e.get("tick"), "kind": e.get("kind"), "note": e.get("note", ""), "event_id": e.get("event_id")}
              for e in resident.get("memory", {}).get("recent_events", [])][-8:]
    orders = [o for o in engine.inventory_state.get("work_orders", {}).get("orders", {}).values() if human_id in (o["smith_id"], o["customer_id"])]
    open_orders = [{"order_id": o["order_id"], "state": o["state"], "role": "smith" if o["smith_id"] == human_id else "customer",
                    "progress": round(o["progress_ticks"] / max(o["work_ticks"], 1), 2), "blocked_reason": o["blocked_reason"]}
                   for o in orders if o["state"] in ("offered", "accepted", "awaiting_materials", "reserved", "working", "ready")]
    where = map_id_at(engine, position) or "the open"
    parts = [f"{name} ({role}) is {'alive' if alive else 'dead'}, at {position} in {where}."]
    if alive and controlled:
        parts.append("Currently possessed by the player.")
    elif alive and roster:
        if at:
            parts.append(f"Standing at the {at} anchor ({routine or 'no routine'} routine).")
        elif goal:
            parts.append(f"Walking to the {goal} anchor because the {routine or 'current'} routine asks for it.")
        else:
            parts.append("Idle: no anchor to go to.")
    needs = _needs(row, cfg)
    if alive and (needs["hunger"] >= 50 or needs["thirst"] >= 50):
        parts.append(f"Needs: hunger {needs['hunger']}, thirst {needs['thirst']}.")
    for order in open_orders:
        verb = "is working on" if order["state"] == "working" and order["role"] == "smith" else "has"
        blocked = f", blocked: {order['blocked_reason']}" if order["blocked_reason"] else ""
        parts.append(f"{name} {verb} order {order['order_id']} ({order['state']}, {int(order['progress'] * 100)}% done{blocked}).")
    if any(e["kind"] == "divine_gift" for e in events):
        parts.append("Remembers an unexplained gift.")
    return {"ok": True, "id": human_id, "name": name, "role": role, "alive": alive, "controlled": controlled, "position": list(position),
            "map_id": map_id_at(engine, position), "needs": needs, "routine": routine, "goal_anchor": goal, "at_anchor": at,
            "anchors": dict((roster or {}).get("anchors", {})), "relationships": relationships, "recent_events": events,
            "commission_orders": open_orders, "explanation": " ".join(parts), "tick": engine.tick}
