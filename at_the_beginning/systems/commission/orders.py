"""Work-order store: plain data inside ``engine.inventory_state["work_orders"]`` (never an ENGINE_FIELDS member).

The store, the order records and the escrow inventories all live in the same dict that the world snapshot already
persists, so a checkpoint captures them together at a tick boundary.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .config import COMMISSION_CONFIG, OPEN_STATES, TERMINAL_STATES

STORE_KEY = "work_orders"


@dataclass
class CommissionContext:
    """Everything a lifecycle function needs besides the order itself. ``state`` is ``engine.inventory_state``."""
    state: dict
    tick: int = 0
    world_epoch: str = ""
    sink: Optional[Callable[[dict, str], Any]] = None  # called once per (order, state) with a snapshot and the new state
    config: dict = field(default_factory=lambda: COMMISSION_CONFIG)


def store(ctx):
    found = ctx.state.setdefault(STORE_KEY, {"next_order_uid": 1, "orders": {}})
    found.setdefault("next_order_uid", 1)
    found.setdefault("orders", {})
    return found


def get_order(ctx, order_id):
    return store(ctx)["orders"].get(order_id)


def snapshot(order):
    return deepcopy(order)


def open_orders(ctx, smith_id=None, customer_id=None):
    return [o for o in store(ctx)["orders"].values() if o["state"] in OPEN_STATES
            and (smith_id is None or o["smith_id"] == smith_id) and (customer_id is None or o["customer_id"] == customer_id)]


def all_orders(ctx, *, smith_id=None, customer_id=None):
    return [o for o in store(ctx)["orders"].values()
            if (smith_id is None or o["smith_id"] == smith_id) and (customer_id is None or o["customer_id"] == customer_id)]


def new_order_record(ctx, customer_id, smith_id, recipe_id, command_id, price, work_ticks, ingredients, output_kind, output_quantity):
    data = store(ctx)
    order_id = f"o_{data['next_order_uid']:06d}"
    data["next_order_uid"] += 1  # persisted counter: never a process-global
    order = {"order_id": order_id, "state": "offered", "revision": 0, "customer_id": customer_id, "smith_id": smith_id,
             "recipe_id": recipe_id, "command_id": command_id, "price": int(price), "work_ticks": int(work_ticks),
             "ingredients": [dict(i) for i in ingredients], "output_kind": output_kind, "output_quantity": int(output_quantity),
             "created_tick": ctx.tick, "progress_ticks": 0, "blocked_reason": "", "blocked_since_tick": None,
             "deadline_tick": None, "refusal_reason": "", "failure_reason": "", "cancel_reason": "",
             "consumed": False, "settled": False, "released": False, "receipt": None, "committed": {}, "history": []}
    data["orders"][order_id] = order
    return order


def set_state(ctx, order, new_state, reason=""):
    """Apply a state change atomically (state, revision, history). Callers have already checked the old state."""
    order["history"].append([ctx.tick, order["state"], new_state, reason])
    order["state"] = new_state
    order["revision"] += 1
    from .lifecycle import commit_consequences
    commit_consequences(ctx, order, new_state)


def require(order, expected):
    if order["state"] in expected:
        return None
    return {"ok": False, "reason": "invalid_transition", "state": order["state"], "order_id": order["order_id"]}


def is_open(order):
    return order["state"] in OPEN_STATES


def is_terminal(order):
    return order["state"] in TERMINAL_STATES
