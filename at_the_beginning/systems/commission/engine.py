"""Engine glue for smith commissions: context, decision service, live facts, memory sink, per-tick work, executors.

Everything here is derived or stored in schema-free homes (``inventory_state["work_orders"]``, resident records);
the only engine attribute added is the non-saved ``_decision_service``.
"""
import math

from systems.decision import DecisionLog, DecisionService

from .access import DEFAULT_INTERACT_RADIUS, engine_interaction_ok, human_position
from .config import COMMISSION_CONFIG
from .decide import make_rules_provider, submit_request
from .dialogue import commission_state
from .lifecycle import (advance_work, cancel_order, deliver_order, fail_order, review_orders, start_work)
from .lines import choose_line
from .orders import CommissionContext, get_order, open_orders

AT_WORK_TOLERANCE = 3.0  # the smith counts as "at the forge" within this many units of the work anchor
EVENT_KIND = {"offered": "commission_requested", "accepted": "commission_accepted", "refused": "commission_refused",
              "ready": "commission_ready", "delivered": "commission_delivered", "failed": "commission_failed",
              "canceled": "commission_canceled"}
CLOSENESS = {"accepted": (0.04, 0.04), "delivered": (0.12, 0.12), "refused": (0.0, -0.03), "failed": (-0.05, -0.05),
             "canceled": (0.0, 0.0)}  # (smith -> customer, customer -> smith)


def decision_service(engine):
    """The engine's DecisionService (rules provider, JSONL log under the data root), created on first use."""
    found = engine.__dict__.get("_decision_service")
    if found is None:
        root = engine.__dict__.get("_decision_log_root")
        found = engine.__dict__["_decision_service"] = DecisionService(make_rules_provider(), log=DecisionLog(root))
    return found


def context(engine):
    """A CommissionContext over the engine's inventory state, clock and event sink."""
    return CommissionContext(state=engine.inventory_state, tick=engine.tick, world_epoch=engine.world_epoch, sink=_sink(engine))


def _slot(engine, human_id):
    slot = engine._human_slot_for_id(human_id)
    return slot if slot >= 0 else None


def _alive(engine, human_id):
    import genesis_config as cfg
    slot = _slot(engine, human_id)
    return slot is not None and float(engine.state.h_tensor[slot, cfg.TYPE]) == cfg.AGENT_TYPE_HUMAN and float(engine.state.h_tensor[slot, cfg.HP]) > 0.0


def find_smith(engine, smith_id=None):
    """(human id, resident record) of the smith: the named one, else the first resident whose roster role is smith."""
    for human_id in engine._human_uid_by_slot:
        if not human_id or (smith_id and human_id != smith_id):
            continue
        record = engine.resident_store.get(human_id) or {}
        if (record.get("roster") or {}).get("role") == "smith" or (record.get("occupation") or {}).get("kind") == "smith":
            return human_id, record
    return None, None


def _work_anchor(engine, record):
    from systems.roster.driver import anchor_positions
    roster = record.get("roster")
    return anchor_positions(engine, roster).get("work") if roster else None


def forge_entity_id(engine, record):
    """The forge entity next to the smith's work anchor (same map), by map data, or None."""
    from systems.movement.map_contract import placed_group
    roster = record.get("roster") or {}
    anchor_id = roster.get("anchors", {}).get("work")
    for entry in placed_group(engine._map_name):
        if any(a["id"] == anchor_id for a in entry["anchors"]):
            return next((e["id"] for e in entry["entities"] if e["kind"] == "forge"), None)
    return None


def forge_available(engine, entity_id):
    """True while the forge entity exists and still has hit points."""
    import genesis_config as cfg
    if not entity_id or entity_id not in engine._entity_uid_by_slot:
        return False
    slot = engine._entity_uid_by_slot.index(entity_id)
    return int(engine.state.m_tensor[slot, cfg.M_TYPE]) > 0 and float(engine.state.m_tensor[slot, cfg.M_HP]) > 0.0


def env_for(engine, smith_id, customer_id, *, interaction=None):
    """Live facts the lifecycle cannot read from inventories."""
    from systems.personality.ops import refresh_resident_pressures
    record = engine.resident_store.get(smith_id) or {}
    relation = (record.get("relationships") or {}).get(customer_id, {})
    work = _work_anchor(engine, record)
    slot = _slot(engine, smith_id)
    at_work = False
    if work is not None and slot is not None:
        sx, sy = human_position(engine, slot)
        at_work = math.hypot(sx - work[0], sy - work[1]) <= AT_WORK_TOLERANCE
    try:
        pressures = dict(refresh_resident_pressures(record, engine.tick))
    except Exception:  # noqa: BLE001 - pressures are an input to a score, never a reason to fail a request
        pressures = {}
    return {"forge_available": forge_available(engine, forge_entity_id(engine, record)), "smith_alive": _alive(engine, smith_id),
            "customer_alive": _alive(engine, customer_id), "smith_at_work": at_work,
            "smith_occupation": (record.get("occupation") or {}).get("kind", "smith"),
            "closeness": float(relation.get("closeness", 0.0)), "rival": "rival" in (relation.get("tags") or []),
            "traits": dict((record.get("personality") or {}).get("traits", {})), "pressures": pressures,
            "interaction": interaction or {"ok": True, "reason": ""}}


# ── consequences: permanent memory, relations, frame events ──────────────────

def _sink(engine):
    def sink(order, state):
        kind = EVENT_KIND.get(state)
        if kind is None:
            return
        store, tick = engine.resident_store, engine.tick
        extra = {"order_id": order["order_id"], "recipe": order["recipe_id"], "price": order["price"], "state": state}
        for human_id, other in ((order["smith_id"], order["customer_id"]), (order["customer_id"], order["smith_id"])):
            store.record_event(human_id, tick, kind, note=f"{kind} {order['order_id']}", other_human_id=other, extra=extra)
        smith_delta, customer_delta = CLOSENESS.get(state, (0.0, 0.0))
        if state == "refused" and order["refusal_reason"] != "distrust":
            smith_delta, customer_delta = 0.0, 0.0  # only a distrust refusal is personal
        if smith_delta:
            store.update_relationship(order["smith_id"], order["customer_id"], "customer", smith_delta, tick)
        if customer_delta:
            store.update_relationship(order["customer_id"], order["smith_id"], "customer", customer_delta, tick)
        slot = _slot(engine, order["smith_id"])
        engine._queue_event(kind, order["order_id"], slot if slot is not None else -1, state=state, recipe=order["recipe_id"],
                            customer_id=order["customer_id"], smith_id=order["smith_id"])
        engine._force_frame_refresh = True
    return sink


def _say(engine, smith_id, customer_id, code, order_id, controller_id):
    text = choose_line("smith", code, smith_id, order_id)
    if text:
        engine.talk_agent._record_runtime_line(
            engine, {"mode": "direct_talk", "speaker_id": smith_id, "listener_id": customer_id, "speech_text": text,
                     "speech_act": "commission", "tone": "neutral"}, controller_id=controller_id)
    return text


# ── per-tick work ────────────────────────────────────────────────────────────

def _ready_since(order):
    for tick, _old, new, _reason in reversed(order.get("history") or ()):
        if new == "ready":
            return tick
    return None


def commission_goal_override(engine, human_id):
    """"work" while the smith has a reserved or working order: the forge pulls him regardless of the clock.

    A *ready* order keeps pulling him until it is delivered, for at most ``ready_hold_ticks`` (then the sword simply waits
    and he follows his schedule again): a block of the clock is 600 ticks and a sword takes 900, so an order often becomes
    ready at dusk or night, and a smith who walked to his bed made the customer's collect fail (out of range / walled off).
    """
    data = engine.inventory_state.get("work_orders")
    if not data or not data.get("orders"):
        return None
    hold = int(COMMISSION_CONFIG.get("ready_hold_ticks", 0))
    for order in data["orders"].values():
        if order["smith_id"] != human_id:
            continue
        if order["state"] in ("reserved", "working"):
            return "work"
        if order["state"] == "ready":
            since = _ready_since(order)
            if hold > 0 and (since is None or engine.tick - since < hold):
                return "work"
    return None


def commission_tick(engine):
    """Advance every open order by one tick. A no-op (one dict lookup) when there are none."""
    data = engine.inventory_state.get("work_orders")
    if not data or not data.get("orders"):
        return
    ctx = context(engine)
    for order in sorted(open_orders(ctx), key=lambda o: o["order_id"]):
        env = env_for(engine, order["smith_id"], order["customer_id"])
        state = order["state"]
        if state == "reserved":
            if not env["smith_alive"]:
                fail_order(ctx, order, "smith_unavailable")
            elif env["smith_at_work"]:
                start_work(ctx, order)
        elif state == "working":
            advance_work(ctx, order, env)
        elif state == "ready" and not env["customer_alive"]:
            fail_order(ctx, order, "customer_gone")
        elif state == "awaiting_materials" and engine.tick % ctx.config["review_ticks"] == 0:
            review_orders(ctx)
        if order["state"] != state:
            engine._force_frame_refresh = True


# ── commands (executors registered on DISPATCH) ──────────────────────────────

def _session(engine, payload):
    session = engine.player_control.sessions_by_controller.get(payload.get("controller_id"))
    if session is None or session.get("target_kind") != "human":
        return None, {"ok": False, "reason": "not_controlling"}
    return session, None


def execute_commission(engine, action, payload):
    """Executor of commission_request / commission_cancel / commission_collect (runs when the inbox drains)."""
    session, problem = _session(engine, payload)
    if problem:
        return problem
    customer_id, controller = session["target_id"], payload["controller_id"]
    ctx = context(engine)
    if action == "commission_request":
        smith_id, smith = find_smith(engine, payload.get("smith_id"))
        if smith_id is None:
            return {"ok": False, "reason": "not_a_smith"}
        recipe_id = payload.get("recipe_id", ctx.config["recipe_id"])
        interaction = engine_interaction_ok(engine, session["slot"], human_position(engine, _slot(engine, smith_id)), DEFAULT_INTERACT_RADIUS)
        if not interaction["ok"]:
            return {"ok": False, "reason": interaction["reason"]}
        result = submit_request(ctx, customer_id, smith_id, recipe_id, decision_service(engine), payload.get("command_id"),
                                env_for(engine, smith_id, customer_id, interaction=interaction))
        if not result.get("ok", False) and "decision" not in result:
            return {"ok": False, "reason": result.get("reason", "rejected"), "code": result.get("code", "")}
        order_id = result["order_id"]
        text = _say(engine, smith_id, customer_id, result["code"], order_id, controller)
        engine._force_frame_refresh = True
        return {"ok": True, "order_id": order_id, "state": result["state"], "code": result["code"], "accepted": result["code"] == "accepted",
                "duplicate": bool(result.get("duplicate_open_order") or result.get("duplicate_command")), "line": text}
    order = get_order(ctx, str(payload.get("order_id", "")))
    if order is None or order["customer_id"] != customer_id:
        return {"ok": False, "reason": "unknown_order"}
    if action == "commission_cancel":
        result = cancel_order(ctx, order, "player", "canceled")
        if not result["ok"]:
            return {"ok": False, "reason": result["reason"], "state": order["state"]}
        text = _say(engine, order["smith_id"], customer_id, "canceled", order["order_id"], controller)
        engine._force_frame_refresh = True
        return {"ok": True, "order_id": order["order_id"], "state": "canceled", "line": text}
    if action == "commission_collect":
        smith_slot = _slot(engine, order["smith_id"])
        interaction = (engine_interaction_ok(engine, session["slot"], human_position(engine, smith_slot), DEFAULT_INTERACT_RADIUS)
                       if smith_slot is not None else {"ok": False, "reason": "out_of_range"})
        result = deliver_order(ctx, order, customer_id, env_for(engine, order["smith_id"], customer_id, interaction=interaction))
        if not result["ok"]:
            if result["reason"] == "customer_inventory_full":
                _say(engine, order["smith_id"], customer_id, "blocked_customer_inventory_full", order["order_id"], controller)
            return {"ok": False, "reason": result["reason"], "state": order["state"]}
        code = "already_delivered" if result.get("duplicate") else "delivered"
        text = _say(engine, order["smith_id"], customer_id, code, order["order_id"], controller)
        engine._force_frame_refresh = True
        return {"ok": True, "order_id": order["order_id"], "state": "delivered", "receipt": order["receipt"], "duplicate": bool(result.get("duplicate")), "line": text}
    return {"ok": False, "reason": "unknown_action"}


def commission_state_payload(engine, controller_id):
    """The read model behind ``GET /commission/state``."""
    session, problem = _session(engine, {"controller_id": controller_id})
    if problem:
        return problem
    smith_id, smith = find_smith(engine)
    if smith_id is None:
        return {"ok": False, "reason": "no_smith"}
    smith_slot = _slot(engine, smith_id)
    interaction = (engine_interaction_ok(engine, session["slot"], human_position(engine, smith_slot), DEFAULT_INTERACT_RADIUS)
                   if smith_slot is not None else {"ok": False, "reason": "out_of_range"})
    ctx = context(engine)
    payload = commission_state(ctx, session["target_id"], smith_id, smith["profile"]["name"], env={"interaction": interaction})
    payload.update(ok=True, world_epoch=engine.world_epoch, tick=engine.tick, greeting=greeting(engine, smith_id, session["target_id"]))
    return payload


def greeting(engine, smith_id, customer_id):
    """The smith's remembered-history greeting for this customer, or None. Deterministic; from the order ledger and
    permanent memory, never from chance: a delivered sword first, otherwise a remembered divine gift."""
    data = engine.inventory_state.get("work_orders") or {}
    if any(o["smith_id"] == smith_id and o["customer_id"] == customer_id and o["state"] == "delivered" for o in data.get("orders", {}).values()):
        code = "followup_delivered"
    elif any(e.get("kind") == "divine_gift" for e in (engine.resident_store.get(smith_id) or {}).get("memory", {}).get("recent_events", [])):
        code = "followup_gift"
    else:
        return None
    return {"code": code, "text": choose_line("smith", code, smith_id, customer_id)}


def commission_open_between(engine, resident_a, resident_b):
    """True while an open order connects the two residents (keyword talk is suppressed then, decision D9)."""
    data = engine.inventory_state.get("work_orders")
    if not data or not data.get("orders"):
        return False
    pair = {resident_a, resident_b}
    return any(o["state"] in ("offered", "accepted", "awaiting_materials", "reserved", "working", "ready")
               and {o["smith_id"], o["customer_id"]} == pair for o in data["orders"].values())
