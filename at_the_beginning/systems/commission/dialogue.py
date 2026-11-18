"""Read model for the commission dialogue: choices with enablement from facts, plus the order list."""
from .config import price_for
from .lines import choose_line
from .orders import all_orders, open_orders

REQUEST_CHOICE = "request_commission"
COLLECT_CHOICE = "collect_commission"
CANCEL_CHOICE = "cancel_commission"


def order_view(order):
    return {"order_id": order["order_id"], "state": order["state"], "recipe": order["recipe_id"], "price": order["price"],
            "blocked_reason": order["blocked_reason"], "progress": round(order["progress_ticks"] / max(order["work_ticks"], 1), 3),
            "progress_ticks": order["progress_ticks"], "work_ticks": order["work_ticks"], "revision": order["revision"],
            "refusal_reason": order["refusal_reason"], "failure_reason": order["failure_reason"],
            "ready": order["state"] == "ready", "delivered": order["state"] == "delivered"}


def build_choices(ctx, customer_id, smith_id, recipe_id, env=None):
    """Choices the player can pick right now. ``enabled`` and ``reason`` come from facts, never from guesses."""
    env = env or {}
    price = price_for(recipe_id, ctx.config)
    interaction = env.get("interaction", {"ok": True, "reason": ""})
    mine = open_orders(ctx, smith_id=smith_id, customer_id=customer_id)
    choices = []
    request = {"id": REQUEST_CHOICE, "label": f"Commission a sword ({price} coin)", "recipe": recipe_id, "enabled": True, "reason": ""}
    from .escrow import human_inventory
    from systems.inventory.currency import inventory_balance
    if not interaction["ok"]:
        request.update(enabled=False, reason=interaction["reason"] or "out_of_range")
    elif any(o["recipe_id"] == recipe_id for o in mine):
        request.update(enabled=False, reason="duplicate_open_order")
    elif inventory_balance(human_inventory(ctx, customer_id)) < price:
        request.update(enabled=False, reason="no_funds")
    choices.append(request)
    for order in mine:
        if order["state"] == "ready":
            collect = {"id": COLLECT_CHOICE, "label": "Collect the sword", "order_id": order["order_id"], "enabled": interaction["ok"],
                       "reason": "" if interaction["ok"] else (interaction["reason"] or "out_of_range")}
            if order["blocked_reason"] == "customer_inventory_full":
                collect.update(reason="customer_inventory_full")
            choices.append(collect)
        if order["state"] in ctx.config["cancel_states"]:
            choices.append({"id": CANCEL_CHOICE, "label": "Cancel the order", "order_id": order["order_id"], "enabled": True, "reason": ""})
        elif order["state"] == "working":
            choices.append({"id": CANCEL_CHOICE, "label": "Cancel the order", "order_id": order["order_id"], "enabled": False,
                            "reason": "work_started"})
    return choices


def commission_state(ctx, customer_id, smith_id, smith_name="", recipe_id=None, env=None, last_code=None):
    """Payload for ``GET /commission/state``."""
    recipe_id = recipe_id or ctx.config["recipe_id"]
    orders = all_orders(ctx, smith_id=smith_id, customer_id=customer_id)
    latest = orders[-1] if orders else None
    code = last_code or (latest and {"ready": "ready", "delivered": "delivered", "canceled": "canceled"}.get(latest["state"]))
    if latest and not last_code:
        if latest["state"] == "refused":
            code = f"refused_{latest['refusal_reason']}"
        elif latest["state"] == "failed":
            code = f"failed_{latest['failure_reason']}"
        elif latest["state"] == "ready" and latest["blocked_reason"] == "customer_inventory_full":
            code = "blocked_customer_inventory_full"
        elif latest["state"] in ("reserved", "working"):
            code = "accepted"
        elif latest["state"] == "delivered" and ctx.tick - int(latest.get("delivered_tick") or 0) >= ctx.config["followup_after_ticks"]:
            code = "followup_delivered"  # seen again after a later visit (persisted delivered_tick: survives Save/Continue)
    line = {"code": code, "text": choose_line("smith", code, smith_id, latest["order_id"] if latest else "")} if code else None
    return {"npc": {"id": smith_id, "name": smith_name, "role": "smith"}, "choices": build_choices(ctx, customer_id, smith_id, recipe_id, env),
            "orders": [order_view(o) for o in orders], "line": line}
