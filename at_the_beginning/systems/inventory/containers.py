from __future__ import annotations

"""Container-oriented inventory helpers."""

from .ops import transfer_item
from .queries import inventory_prompt_payload
from .store import ensure_container_inventory


def ensure_storage_case_inventory(
    state: dict,
    container_id: str,
    *,
    label: str = "Storage Case",
    capacity_slots: int = 16,
    metadata: dict | None = None,
) -> dict:
    return ensure_container_inventory(
        state,
        container_id,
        container_kind="storage_case",
        label=label,
        capacity_slots=capacity_slots,
        metadata=metadata,
    )


def ensure_house_storage_inventory(
    state: dict,
    container_id: str,
    *,
    label: str = "House Storage",
    capacity_slots: int = 24,
    capacity_weight: float = 120.0,
    metadata: dict | None = None,
) -> dict:
    return ensure_container_inventory(
        state,
        container_id,
        container_kind="house_storage",
        label=label,
        capacity_slots=capacity_slots,
        capacity_weight=capacity_weight,
        metadata=metadata,
    )


def ensure_stockpile_inventory(
    state: dict,
    container_id: str,
    *,
    label: str = "Stockpile",
    capacity_slots: int = 48,
    metadata: dict | None = None,
) -> dict:
    return ensure_container_inventory(
        state,
        container_id,
        container_kind="stockpile",
        label=label,
        capacity_slots=capacity_slots,
        capacity_weight=None,
        metadata=metadata,
    )


def deposit_to_container(
    source_record: dict,
    container_record: dict,
    *,
    item_kind: str | None = None,
    quantity: int = 1,
    item_id: str = "",
) -> dict:
    return transfer_item(
        source_record,
        container_record,
        item_kind=item_kind,
        quantity=quantity,
        item_id=item_id,
    )


def withdraw_from_container(
    container_record: dict,
    target_record: dict,
    *,
    item_kind: str | None = None,
    quantity: int = 1,
    item_id: str = "",
) -> dict:
    return transfer_item(
        container_record,
        target_record,
        item_kind=item_kind,
        quantity=quantity,
        item_id=item_id,
    )


def container_prompt_payload(container_record: dict, *, limit: int = 6) -> dict:
    payload = inventory_prompt_payload(container_record, limit=limit)
    payload["container_kind"] = str(container_record.get("container_kind", ""))
    payload["owner_kind"] = str(container_record.get("owner_kind", "container"))
    return payload


__all__ = [
    "container_prompt_payload",
    "deposit_to_container",
    "ensure_house_storage_inventory",
    "ensure_storage_case_inventory",
    "ensure_stockpile_inventory",
    "withdraw_from_container",
]
