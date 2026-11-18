from __future__ import annotations

"""Currency helpers built on top of item stacks."""

from .ops import add_item, remove_item
from .queries import total_quantity
from .schema import DEFAULT_CURRENCY_KIND


def inventory_balance(record: dict, *, currency_kind: str = DEFAULT_CURRENCY_KIND) -> int:
    return total_quantity(record, currency_kind)


def can_afford(record: dict, amount: int, *, currency_kind: str = DEFAULT_CURRENCY_KIND) -> bool:
    return inventory_balance(record, currency_kind=currency_kind) >= max(int(amount), 0)


def grant_currency(record: dict, amount: int, *, currency_kind: str = DEFAULT_CURRENCY_KIND) -> dict:
    return add_item(record, currency_kind, max(int(amount), 0))


def spend_currency(record: dict, amount: int, *, currency_kind: str = DEFAULT_CURRENCY_KIND) -> dict:
    amount = max(int(amount), 0)
    if amount <= 0:
        return {"ok": True, "spent": 0, "remaining_balance": inventory_balance(record, currency_kind=currency_kind)}
    if not can_afford(record, amount, currency_kind=currency_kind):
        return {
            "ok": False,
            "spent": 0,
            "remaining_balance": inventory_balance(record, currency_kind=currency_kind),
        }
    removed = remove_item(record, currency_kind, amount)
    return {
        "ok": bool(removed.get("ok", False)),
        "spent": int(removed.get("removed", 0)),
        "remaining_balance": inventory_balance(record, currency_kind=currency_kind),
    }


__all__ = [
    "can_afford",
    "grant_currency",
    "inventory_balance",
    "spend_currency",
]
