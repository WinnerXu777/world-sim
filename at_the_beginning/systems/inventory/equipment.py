from __future__ import annotations

"""Equip / unequip helpers for simple resident and incarnation loadouts."""

from .resolver import item_slot
from .store import find_item_by_id, normalize_inventory_record


def ensure_equipment(record: dict) -> dict:
    normalize_inventory_record(record)
    record["equipped"].setdefault("main_hand", None)
    return record["equipped"]


def equipped_item(record: dict, slot: str = "main_hand") -> dict | None:
    equipment = ensure_equipment(record)
    item_id = equipment.get(str(slot))
    if not item_id:
        return None
    return find_item_by_id(record, str(item_id))


def equip_item(record: dict, item_id: str, *, slot: str | None = None) -> dict | None:
    ensure_equipment(record)
    item = find_item_by_id(record, item_id)
    if item is None:
        return None
    resolved_slot = str(slot or item_slot(str(item.get("kind", ""))) or "")
    if not resolved_slot:
        return None
    record["equipped"][resolved_slot] = str(item_id)
    return item


def equip_main_hand_item(record: dict, item_id: str) -> dict | None:
    return equip_item(record, item_id, slot="main_hand")


def unequip_slot(record: dict, slot: str = "main_hand") -> str | None:
    equipment = ensure_equipment(record)
    previous = equipment.get(str(slot))
    equipment[str(slot)] = None
    return previous


def clear_equipment_references(record: dict, item_id: str) -> None:
    equipment = ensure_equipment(record)
    for slot_name, equipped_id in list(equipment.items()):
        if str(equipped_id or "") == str(item_id):
            equipment[slot_name] = None


__all__ = [
    "clear_equipment_references",
    "ensure_equipment",
    "equip_item",
    "equip_main_hand_item",
    "equipped_item",
    "unequip_slot",
]
