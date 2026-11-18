"""Escrow by physical transfer: reserved materials, the price and the finished item live in ``work_order:<id>``."""
from copy import deepcopy

from systems.inventory.currency import inventory_balance
from systems.inventory.ops import add_item, remove_item
from systems.inventory.queries import total_quantity
from systems.inventory.resolver import can_add_item
from systems.inventory.schema import DEFAULT_CURRENCY_KIND
from systems.inventory.store import ensure_inventory_record, ensure_owner_inventory

OWNER_KIND = "work_order"


def human_inventory(ctx, human_id):
    return ensure_owner_inventory(ctx.state, "human", human_id)


def escrow_record(ctx, order):
    return ensure_inventory_record(ctx.state, f"{OWNER_KIND}:{order['order_id']}", OWNER_KIND, order["order_id"],
                                   label=f"Work order {order['order_id']}", capacity_slots=ctx.config["escrow_slots"],
                                   capacity_weight=None)


def drop_if_empty(ctx, order):
    """Remove an unused, empty escrow record (a refused order never held anything)."""
    key = f"{OWNER_KIND}:{order['order_id']}"
    record = ctx.state.get("inventories", {}).get(key)
    if record is not None and not record["items"]:
        del ctx.state["inventories"][key]


def snapshots(*records):
    return [(record, deepcopy(record)) for record in records]


def restore(saved):
    for record, copy in saved:
        record.clear()
        record.update(copy)


def move(source, target, kind, quantity):
    """Move exactly ``quantity`` of ``kind`` or change nothing. Returns True on success."""
    if quantity <= 0:
        return True
    if total_quantity(source, kind) < quantity or not can_add_item(target, kind, quantity):
        return False
    saved = snapshots(source, target)
    removed = remove_item(source, kind, quantity)
    added = add_item(target, kind, removed["removed"]) if removed["removed"] == quantity else {"added": -1}
    if removed["removed"] != quantity or added["added"] != quantity:
        restore(saved)
        return False
    return True


def escrow_contents(ctx, order):
    record = escrow_record(ctx, order)
    out = {}
    for item in record["items"]:
        out[item["kind"]] = out.get(item["kind"], 0) + int(item["quantity"])
    return out


def reserve(ctx, order):
    """All-or-nothing: ingredients smith -> escrow and price customer -> escrow. Returns (ok, reason)."""
    smith, customer, escrow = human_inventory(ctx, order["smith_id"]), human_inventory(ctx, order["customer_id"]), escrow_record(ctx, order)
    for ingredient in order["ingredients"]:
        if total_quantity(smith, ingredient["item_kind"]) < ingredient["quantity"]:
            return False, "no_materials"
        if not can_add_item(escrow, ingredient["item_kind"], ingredient["quantity"]):
            return False, "escrow_full"
    if inventory_balance(customer) < order["price"]:
        return False, "cannot_afford"
    saved = snapshots(smith, customer, escrow)
    for ingredient in order["ingredients"]:
        if not move(smith, escrow, ingredient["item_kind"], ingredient["quantity"]):
            restore(saved)
            return False, "no_materials"
    if not move(customer, escrow, DEFAULT_CURRENCY_KIND, order["price"]):
        restore(saved)
        return False, "cannot_afford"
    return True, ""


def release(ctx, order, *, price_to="customer"):
    """Return everything left in escrow once. Ingredients go back to the smith, a finished item to the smith, the
    price to the customer (or to the smith when ``price_to == "smith"``). Anything that does not fit stays in escrow."""
    smith, customer, escrow = human_inventory(ctx, order["smith_id"]), human_inventory(ctx, order["customer_id"]), escrow_record(ctx, order)
    for kind, quantity in list(escrow_contents(ctx, order).items()):
        if kind == DEFAULT_CURRENCY_KIND:
            move(escrow, customer if price_to == "customer" else smith, kind, quantity)
        else:
            move(escrow, smith, kind, quantity)
    order["released"] = not escrow["items"]
    return order["released"]
