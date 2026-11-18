from __future__ import annotations

"""Inventory state store and record normalization helpers."""

from copy import deepcopy

from .schema import INVENTORY_SCHEMA_VERSION, container_kind_def, owner_inventory_defaults


def build_inventory_state() -> dict:
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "inventories": {},
    }


def ensure_inventory_state(state: dict | None) -> dict:
    if not isinstance(state, dict):
        state = build_inventory_state()
    state.setdefault("schema_version", INVENTORY_SCHEMA_VERSION)
    state.setdefault("inventories", {})
    return state


def inventory_identity(owner_kind: str, owner_id: str) -> str:
    return f"{str(owner_kind)}:{str(owner_id)}"


def build_inventory_record(
    inventory_id: str,
    owner_kind: str,
    owner_id: str,
    *,
    label: str = "",
    container_kind: str = "",
    capacity_slots: int | None = None,
    capacity_weight: float | None = None,
    metadata: dict | None = None,
) -> dict:
    container_def = container_kind_def(container_kind) if container_kind else {}
    return {
        "inventory_id": str(inventory_id),
        "owner_kind": str(owner_kind),
        "owner_id": str(owner_id),
        "container_kind": str(container_kind or ""),
        "label": str(label or container_def.get("label", inventory_id)),
        "capacity_slots": capacity_slots if capacity_slots is not None else container_def.get("capacity_slots"),
        "capacity_weight": capacity_weight if capacity_weight is not None else container_def.get("capacity_weight"),
        "items": [],
        "equipped": {"main_hand": None},
        "metadata": deepcopy(metadata or {}),
        "next_item_uid": 1,
    }


def normalize_inventory_record(record: dict) -> dict:
    record.setdefault("inventory_id", "")
    record.setdefault("owner_kind", "unknown")
    record.setdefault("owner_id", "")
    record.setdefault("container_kind", "")
    record.setdefault("label", record.get("inventory_id", "inventory"))
    record.setdefault("capacity_slots", None)
    record.setdefault("capacity_weight", None)
    record.setdefault("items", [])
    record.setdefault("equipped", {"main_hand": None})
    record.setdefault("metadata", {})
    record.setdefault("next_item_uid", 1)
    if not isinstance(record["equipped"], dict):
        record["equipped"] = {"main_hand": None}
    record["equipped"].setdefault("main_hand", None)
    if not isinstance(record["items"], list):
        record["items"] = list(record["items"])
    return record


def ensure_inventory_record(
    state: dict,
    inventory_id: str,
    owner_kind: str,
    owner_id: str,
    *,
    label: str = "",
    container_kind: str = "",
    capacity_slots: int | None = None,
    capacity_weight: float | None = None,
    metadata: dict | None = None,
) -> dict:
    state = ensure_inventory_state(state)
    inventories = state["inventories"]
    record = inventories.get(str(inventory_id))
    if record is None:
        record = build_inventory_record(
            inventory_id,
            owner_kind,
            owner_id,
            label=label,
            container_kind=container_kind,
            capacity_slots=capacity_slots,
            capacity_weight=capacity_weight,
            metadata=metadata,
        )
        inventories[str(inventory_id)] = record
    else:
        normalize_inventory_record(record)
    return record


def ensure_owner_inventory(
    state: dict,
    owner_kind: str,
    owner_id: str,
    *,
    label: str = "",
    capacity_slots: int | None = None,
    capacity_weight: float | None = None,
    metadata: dict | None = None,
) -> dict:
    defaults = owner_inventory_defaults(owner_kind)
    inventory_id = inventory_identity(owner_kind, owner_id)
    return ensure_inventory_record(
        state,
        inventory_id,
        owner_kind,
        owner_id,
        label=label or defaults.get("label", inventory_id),
        container_kind=defaults.get("container_kind", ""),
        capacity_slots=capacity_slots if capacity_slots is not None else defaults.get("capacity_slots"),
        capacity_weight=capacity_weight if capacity_weight is not None else defaults.get("capacity_weight"),
        metadata=metadata,
    )


def ensure_container_inventory(
    state: dict,
    container_id: str,
    *,
    container_kind: str = "storage_case",
    label: str = "",
    capacity_slots: int | None = None,
    capacity_weight: float | None = None,
    metadata: dict | None = None,
) -> dict:
    container_def = container_kind_def(container_kind)
    return ensure_inventory_record(
        state,
        inventory_identity("container", container_id),
        "container",
        container_id,
        label=label or container_def.get("label", container_id),
        container_kind=container_kind,
        capacity_slots=capacity_slots if capacity_slots is not None else container_def.get("capacity_slots"),
        capacity_weight=capacity_weight if capacity_weight is not None else container_def.get("capacity_weight"),
        metadata=metadata,
    )


def get_inventory(state: dict, inventory_id: str) -> dict | None:
    state = ensure_inventory_state(state)
    record = state["inventories"].get(str(inventory_id))
    return normalize_inventory_record(record) if record is not None else None


def get_owner_inventory(state: dict, owner_kind: str, owner_id: str) -> dict | None:
    return get_inventory(state, inventory_identity(owner_kind, owner_id))


def get_container_inventory(state: dict, container_id: str) -> dict | None:
    return get_inventory(state, inventory_identity("container", container_id))


def next_item_id(record: dict) -> str:
    normalize_inventory_record(record)
    next_uid = max(int(record.get("next_item_uid", 1)), 1)
    record["next_item_uid"] = next_uid + 1
    return f"item_{next_uid:06d}"


def find_item_by_id(record: dict, item_id: str) -> dict | None:
    normalize_inventory_record(record)
    for item in record["items"]:
        if str(item.get("id", "")) == str(item_id):
            return item
    return None


__all__ = [
    "build_inventory_record",
    "build_inventory_state",
    "ensure_container_inventory",
    "ensure_inventory_record",
    "ensure_inventory_state",
    "ensure_owner_inventory",
    "find_item_by_id",
    "get_container_inventory",
    "get_inventory",
    "get_owner_inventory",
    "inventory_identity",
    "next_item_id",
    "normalize_inventory_record",
]
