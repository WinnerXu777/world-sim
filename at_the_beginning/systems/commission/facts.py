"""Feasibility facts for a commission: a pure read of inventories plus facts the engine injects as ``env``."""
from systems.crafting.ops import crafting_missing_ingredients
from systems.crafting.resolver import crafting_recipe_occupation_tags
from systems.inventory.currency import inventory_balance
from systems.inventory.queries import list_items, total_quantity

from .escrow import human_inventory
from .orders import open_orders


def default_env():
    return {"forge_available": True, "smith_alive": True, "customer_alive": True, "smith_at_work": True,
            "smith_occupation": "smith", "closeness": 0.0, "rival": False, "traits": {}, "pressures": {},
            "interaction": {"ok": True, "reason": ""}}


def commission_facts(ctx, order, env=None):
    """Everything the decision needs, from committed state. ``env`` supplies live facts the lifecycle cannot read."""
    env = {**default_env(), **(env or {})}
    smith = human_inventory(ctx, order["smith_id"])
    customer = human_inventory(ctx, order["customer_id"])
    missing = crafting_missing_ingredients(order["recipe_id"], list_items(smith))
    others = [o for o in open_orders(ctx, smith_id=order["smith_id"]) if o["order_id"] != order["order_id"]]
    return {
        "recipe_known": env["smith_occupation"] in crafting_recipe_occupation_tags(order["recipe_id"]),
        "missing": missing,
        "forge_available": bool(env["forge_available"]),
        "smith_alive": bool(env["smith_alive"]),
        "price": order["price"],
        "customer_balance": inventory_balance(customer),
        "can_afford": inventory_balance(customer) >= order["price"],
        "open_orders": len(others),
        "capacity": ctx.config["capacity_open_orders"],
        "has_hammer": total_quantity(smith, "hammer") >= 1,
        "closeness": float(env["closeness"]),
        "rival": bool(env["rival"]),
        "traits": dict(env["traits"]),
        "pressures": dict(env["pressures"]),
        "distrust": float(env["closeness"]) <= ctx.config["distrust_closeness"] or bool(env["rival"]),
    }
