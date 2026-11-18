from __future__ import annotations

"""Read-only inventory query helpers for UI, prompts, and gameplay checks."""

from copy import deepcopy

from .equipment import equipped_item
from .schema import DEFAULT_CURRENCY_KIND
from .resolver import inventory_capacity_weight, total_weight
from .store import normalize_inventory_record


def list_items(record: dict, *, limit: int | None = None) -> list[dict]:
    normalize_inventory_record(record)
    items = [deepcopy(item) for item in record["items"]]
    if limit is not None:
        return items[: max(int(limit), 0)]
    return items


def total_quantity(record: dict, item_kind: str) -> int:
    normalize_inventory_record(record)
    return sum(int(item.get("quantity", 0)) for item in record["items"] if str(item.get("kind", "")) == str(item_kind))


def has_item(record: dict, item_kind: str, quantity: int = 1) -> bool:
    return total_quantity(record, item_kind) >= max(int(quantity), 0)


def equipped_item_payload(record: dict, slot: str = "main_hand") -> dict | None:
    item = equipped_item(record, slot=slot)
    return deepcopy(item) if item is not None else None


def inventory_prompt_payload(record: dict, *, limit: int = 6) -> dict:
    normalize_inventory_record(record)
    capacity = record.get("capacity_slots")
    return {
        "inventory_id": str(record.get("inventory_id", "")),
        "owner_kind": str(record.get("owner_kind", "")),
        "owner_id": str(record.get("owner_id", "")),
        "label": str(record.get("label", "inventory")),
        "capacity_slots": capacity,
        "capacity_weight": inventory_capacity_weight(record),
        "used_slots": len(record.get("items", [])),
        "used_weight": total_weight(record),
        "currency": total_quantity(record, DEFAULT_CURRENCY_KIND),
        "equipped_main_hand": equipped_item_payload(record, "main_hand"),
        "items": list_items(record, limit=limit),
    }


def summarize_inventory(record: dict, *, limit: int = 4) -> str:
    normalize_inventory_record(record)
    parts: list[str] = []
    for item in record["items"][: max(int(limit), 0)]:
        label = str(item.get("label", item.get("kind", "item")))
        qty = int(item.get("quantity", 0))
        if qty > 1:
            parts.append(f"{label} x{qty}")
        else:
            parts.append(label)
    if len(record["items"]) > max(int(limit), 0):
        parts.append("...")
    if not parts:
        parts.append("empty")
    return ", ".join(parts)


__all__ = [
    "equipped_item_payload",
    "has_item",
    "inventory_prompt_payload",
    "list_items",
    "summarize_inventory",
    "total_quantity",
]
