"""Work-order lifecycle: offered -> accepted -> (awaiting_materials) -> reserved -> working -> ready -> delivered.

Branches: refused, canceled, failed. Every transition checks the CURRENT state and applies all its side effects in
the same synchronous call (exactly-once: state CAS, escrow by physical transfer, and committed flags).
"""
import logging

from systems.crafting.resolver import crafting_output_kind, crafting_recipe_ingredients, crafting_recipe_def
from systems.inventory.queries import total_quantity
from systems.inventory.resolver import can_add_item
from systems.inventory.schema import DEFAULT_CURRENCY_KIND

from . import escrow
from .config import OPEN_STATES, price_for, work_ticks_for
from .facts import commission_facts, default_env
from .orders import get_order, is_open, new_order_record, open_orders, require, set_state, snapshot

LOG = logging.getLogger("eden.commission")


# ── request ──────────────────────────────────────────────────────────────────

def create_order(ctx, customer_id, smith_id, recipe_id, command_id=None, env=None):
    """Open an order in state ``offered``. Idempotent for the same command id and for an already-open order."""
    env = {**default_env(), **(env or {})}
    if recipe_id not in ctx.config["prices"]:
        return {"ok": False, "reason": "unknown_recipe"}
    if customer_id == smith_id:
        return {"ok": False, "reason": "cannot_commission_yourself"}
    if not env["smith_alive"]:
        return {"ok": False, "reason": "smith_unavailable"}
    for order in open_orders(ctx, smith_id=smith_id, customer_id=customer_id):
        if order["recipe_id"] == recipe_id:
            return {"ok": True, "duplicate_open_order": True, "order_id": order["order_id"], "state": order["state"]}
    if command_id is not None:
        for existing in ctx.state.get("work_orders", {}).get("orders", {}).values():
            if existing["command_id"] == command_id:
                return {"ok": True, "duplicate_command": True, "order_id": existing["order_id"], "state": existing["state"]}
    order = new_order_record(ctx, customer_id, smith_id, recipe_id, command_id, price_for(recipe_id, ctx.config),
                             work_ticks_for(recipe_id, ctx.config),
                             [{"item_kind": i["item_kind"], "quantity": int(i["quantity"])} for i in crafting_recipe_ingredients(recipe_id)],
                             crafting_output_kind(recipe_id), int(crafting_recipe_def(recipe_id)["output_quantity"]))
    set_state(ctx, order, "offered", "requested")
    return {"ok": True, "order_id": order["order_id"], "state": order["state"]}


# ── accept / refuse / reserve ────────────────────────────────────────────────

def refuse_order(ctx, order, reason):
    problem = require(order, ("offered", "accepted", "awaiting_materials"))
    if problem:
        return problem
    order["refusal_reason"] = reason
    escrow.drop_if_empty(ctx, order)  # nothing is held before reserve
    set_state(ctx, order, "refused", reason)
    return {"ok": True, "state": "refused", "reason": reason, "order_id": order["order_id"]}


def accept_order(ctx, order):
    problem = require(order, ("offered",))
    if problem:
        return problem
    set_state(ctx, order, "accepted", "accepted")
    return {"ok": True, "state": "accepted", "order_id": order["order_id"]}


def reserve_inputs(ctx, order, *, wait_allowed=None):
    """accepted -> reserved (all-or-nothing). On a shortfall: awaiting_materials if waiting is allowed, else refused."""
    problem = require(order, ("accepted", "awaiting_materials"))
    if problem:
        return problem
    ok, reason = escrow.reserve(ctx, order)
    if ok:
        order["reserved_tick"] = ctx.tick
        order["blocked_reason"] = ""
        set_state(ctx, order, "reserved", "reserved")
        return {"ok": True, "state": "reserved", "order_id": order["order_id"]}
    wait = ctx.config["wait_for_materials"] if wait_allowed is None else wait_allowed
    if wait and reason == "no_materials":
        if order["state"] != "awaiting_materials":
            order["deadline_tick"] = ctx.tick + ctx.config["waiting_deadline_ticks"]
            order["blocked_reason"] = reason
            set_state(ctx, order, "awaiting_materials", reason)
        return {"ok": False, "state": "awaiting_materials", "reason": reason, "order_id": order["order_id"]}
    if order["state"] == "awaiting_materials":
        return fail_order(ctx, order, reason)
    result = refuse_order(ctx, order, reason)
    return {**result, "ok": False, "reason": reason}


def review_orders(ctx, envs=None):
    """Re-check awaiting_materials orders: reserve if stock arrived, fail past the deadline. Returns changed order ids."""
    changed = []
    for order in list(open_orders(ctx)):
        if order["state"] != "awaiting_materials":
            continue
        result = reserve_inputs(ctx, order, wait_allowed=True)
        if result.get("state") == "reserved":
            changed.append(order["order_id"])
        elif order["deadline_tick"] is not None and ctx.tick >= order["deadline_tick"]:
            fail_order(ctx, order, "no_materials")
            changed.append(order["order_id"])
    return changed


# ── work ─────────────────────────────────────────────────────────────────────

def start_work(ctx, order):
    problem = require(order, ("reserved",))
    if problem:
        return problem
    order["work_started_tick"] = ctx.tick
    set_state(ctx, order, "working", "work_started")
    return {"ok": True, "state": "working", "order_id": order["order_id"]}


def advance_work(ctx, order, env=None):
    """One simulation tick of work. Progress is counted in ticks, stored in the order, and only moves at the station."""
    problem = require(order, ("working",))
    if problem:
        return problem
    env = {**default_env(), **(env or {})}
    if not env["smith_alive"]:
        return fail_order(ctx, order, "smith_unavailable")
    if not env["forge_available"]:
        if order["blocked_reason"] != "forge_unavailable":
            order["blocked_reason"] = "forge_unavailable"  # set once; the guard keeps the event single
            order["blocked_since_tick"] = ctx.tick
            order["revision"] += 1
        if ctx.tick - order["blocked_since_tick"] >= ctx.config["forge_wait_ticks"]:
            return fail_order(ctx, order, "forge_unavailable")
        return {"ok": True, "progressed": False, "blocked": "forge_unavailable", "state": "working"}
    if order["blocked_reason"] == "forge_unavailable":
        order["blocked_reason"], order["blocked_since_tick"] = "", None
        order["revision"] += 1
    if not env["smith_at_work"]:
        return {"ok": True, "progressed": False, "blocked": "smith_away", "state": "working"}
    order["progress_ticks"] += 1
    if order["progress_ticks"] >= order["work_ticks"]:
        return complete_work(ctx, order)
    return {"ok": True, "progressed": True, "state": "working", "progress_ticks": order["progress_ticks"]}


def complete_work(ctx, order):
    problem = require(order, ("working",))
    if problem:
        return problem
    if order["progress_ticks"] < order["work_ticks"]:
        return {"ok": False, "reason": "work_incomplete", "state": order["state"], "order_id": order["order_id"]}
    record = escrow.escrow_record(ctx, order)
    saved = escrow.snapshots(record)
    for ingredient in order["ingredients"]:
        if total_quantity(record, ingredient["item_kind"]) < ingredient["quantity"]:
            escrow.restore(saved)
            return fail_order(ctx, order, "escrow_corrupt")
    from systems.inventory.ops import add_item, remove_item
    for ingredient in order["ingredients"]:
        remove_item(record, ingredient["item_kind"], ingredient["quantity"])
    added = add_item(record, order["output_kind"], order["output_quantity"])
    if added["added"] != order["output_quantity"]:
        escrow.restore(saved)
        order["blocked_reason"] = "capacity"
        return {"ok": False, "reason": "capacity", "state": "working", "order_id": order["order_id"]}
    order["consumed"] = True
    order["blocked_reason"] = ""
    set_state(ctx, order, "ready", "work_complete")
    return {"ok": True, "state": "ready", "order_id": order["order_id"]}


# ── delivery ─────────────────────────────────────────────────────────────────

def deliver_order(ctx, order, collector_id, env=None):
    """ready -> delivered at the counter. A repeat call returns the stored receipt and moves nothing."""
    if order["state"] == "delivered":
        return {"ok": True, "duplicate": True, "status": "already_delivered", "receipt": order["receipt"], "order_id": order["order_id"]}
    problem = require(order, ("ready",))
    if problem:
        return problem
    env = {**default_env(), **(env or {})}
    if collector_id != order["customer_id"]:
        return {"ok": False, "reason": "not_your_order", "order_id": order["order_id"]}
    if not env["customer_alive"]:
        return {"ok": False, "reason": "customer_unavailable", "order_id": order["order_id"]}
    if not env["interaction"]["ok"]:
        return {"ok": False, "reason": env["interaction"]["reason"] or "out_of_range", "order_id": order["order_id"]}
    customer, smith = escrow.human_inventory(ctx, order["customer_id"]), escrow.human_inventory(ctx, order["smith_id"])
    record = escrow.escrow_record(ctx, order)
    if not can_add_item(customer, order["output_kind"], order["output_quantity"]):
        if order["blocked_reason"] != "customer_inventory_full":
            order["blocked_reason"] = "customer_inventory_full"
            order["revision"] += 1
        return {"ok": False, "reason": "customer_inventory_full", "state": "ready", "order_id": order["order_id"]}
    saved = escrow.snapshots(customer, smith, record)
    if not (escrow.move(record, customer, order["output_kind"], order["output_quantity"])
            and escrow.move(record, smith, DEFAULT_CURRENCY_KIND, order["price"])):
        escrow.restore(saved)
        return {"ok": False, "reason": "delivery_failed", "state": "ready", "order_id": order["order_id"]}
    order["blocked_reason"] = ""
    order["settled"] = True
    order["released"] = True
    order["delivered_tick"] = ctx.tick
    order["receipt"] = {"order_id": order["order_id"], "item": order["output_kind"], "quantity": order["output_quantity"],
                        "price": order["price"], "delivered_tick": ctx.tick, "customer_id": order["customer_id"],
                        "smith_id": order["smith_id"]}
    set_state(ctx, order, "delivered", "collected")
    return {"ok": True, "state": "delivered", "receipt": order["receipt"], "order_id": order["order_id"]}


# ── cancel / fail ────────────────────────────────────────────────────────────

def cancel_order(ctx, order, by, reason="canceled"):
    """Allowed until work starts (decision D6); a full refund because nothing has been consumed."""
    if order["state"] not in ctx.config["cancel_states"]:
        return {"ok": False, "reason": "invalid_transition", "state": order["state"], "order_id": order["order_id"]}
    escrow.release(ctx, order)
    order["cancel_reason"] = f"{by}:{reason}"
    order["settled"] = True
    set_state(ctx, order, "canceled", reason)
    return {"ok": True, "state": "canceled", "refunded": True, "order_id": order["order_id"]}


def fail_order(ctx, order, reason):
    """Any open state -> failed. Escrow returns once: price to the customer (to the smith if the customer is gone)."""
    problem = require(order, OPEN_STATES)
    if problem:
        return problem
    escrow.release(ctx, order, price_to="smith" if reason == "customer_gone" else "customer")
    order["failure_reason"] = reason
    order["settled"] = True
    set_state(ctx, order, "failed", reason)
    return {"ok": False, "state": "failed", "reason": reason, "order_id": order["order_id"]}


# ── consequences ─────────────────────────────────────────────────────────────

def commit_consequences(ctx, order, new_state):
    """Tell the sink (memory events, relations, frame events) once per (order, state)."""
    if new_state in order["committed"]:
        return False
    order["committed"][new_state] = ctx.tick  # flag first: exactly-once matters more than at-least-once
    if ctx.sink is not None:
        try:
            ctx.sink(snapshot(order), new_state)
        except Exception:  # noqa: BLE001 - a broken sink must not undo a completed transition
            LOG.exception("commission sink failed for %s -> %s", order["order_id"], new_state)
    return True


def get(ctx, order_id):
    return get_order(ctx, order_id)


__all__ = ["accept_order", "advance_work", "cancel_order", "commission_facts", "commit_consequences", "complete_work",
           "create_order", "deliver_order", "fail_order", "get", "is_open", "refuse_order", "reserve_inputs",
           "review_orders", "start_work"]
