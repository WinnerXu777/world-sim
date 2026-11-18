from __future__ import annotations

"""Core inventory mutation ops."""

from copy import deepcopy

from .equipment import clear_equipment_references
from .resolver import can_add_item, find_merge_target, is_stackable, item_stack_limit
from .schema import build_item_stack
from .store import normalize_inventory_record, next_item_id


def add_item(
    record: dict,
    item_kind: str,
    quantity: int = 1,
    *,
    metadata: dict | None = None,
) -> dict:
    normalize_inventory_record(record)
    remaining = max(int(quantity), 0)
    added = 0
    created_item_ids: list[str] = []

    while remaining > 0:
        merge_target = find_merge_target(record, item_kind, metadata)
        if merge_target is not None:
            room = max(item_stack_limit(item_kind) - int(merge_target.get("quantity", 0)), 0)
            if room > 0:
                step = min(room, remaining)
                merge_target["quantity"] = int(merge_target.get("quantity", 0)) + step
                remaining -= step
                added += step
                continue

        if not can_add_item(record, item_kind, remaining, metadata):
            break

        step = min(remaining, item_stack_limit(item_kind)) if is_stackable(item_kind) else 1
        stack = build_item_stack(
            item_kind,
            item_id=next_item_id(record),
            quantity=step,
            metadata=deepcopy(metadata or {}),
        )
        record["items"].append(stack)
        created_item_ids.append(stack["id"])
        added += step
        remaining -= step

    return {
        "ok": added > 0,
        "added": added,
        "remaining": remaining,
        "inventory_id": str(record.get("inventory_id", "")),
        "item_kind": str(item_kind),
        "created_item_ids": created_item_ids,
    }


def remove_item(
    record: dict,
    item_kind: str | None = None,
    quantity: int = 1,
    *,
    item_id: str = "",
) -> dict:
    normalize_inventory_record(record)
    remaining = max(int(quantity), 0)
    removed = 0
    removed_fragments: list[dict] = []

    for item in list(record["items"]):
        if remaining <= 0:
            break
        if item_id:
            if str(item.get("id", "")) != str(item_id):
                continue
        elif item_kind is not None and str(item.get("kind", "")) != str(item_kind):
            continue

        current_qty = max(int(item.get("quantity", 0)), 0)
        if current_qty <= 0:
            continue

        step = min(current_qty, remaining)
        item["quantity"] = current_qty - step
        removed += step
        remaining -= step
        removed_fragments.append(
            {
                "item_id": str(item.get("id", "")),
                "kind": str(item.get("kind", "")),
                "quantity": step,
                "metadata": deepcopy(item.get("metadata", {})),
            }
        )
        if int(item.get("quantity", 0)) <= 0:
            clear_equipment_references(record, str(item.get("id", "")))
            record["items"].remove(item)

    return {
        "ok": removed > 0,
        "removed": removed,
        "remaining": remaining,
        "inventory_id": str(record.get("inventory_id", "")),
        "item_kind": str(item_kind or ""),
        "item_id": str(item_id),
        "fragments": removed_fragments,
    }


def transfer_item(
    source_record: dict,
    target_record: dict,
    *,
    item_kind: str | None = None,
    quantity: int = 1,
    item_id: str = "",
) -> dict:
    removed = remove_item(source_record, item_kind, quantity, item_id=item_id)
    if not removed["ok"]:
        return {
            "ok": False,
            "moved": 0,
            "source_inventory_id": str(source_record.get("inventory_id", "")),
            "target_inventory_id": str(target_record.get("inventory_id", "")),
            "reason": "source_missing_item",
        }

    moved = 0
    rollback_fragments: list[dict] = []
    for fragment in removed["fragments"]:
        added = add_item(
            target_record,
            fragment["kind"],
            fragment["quantity"],
            metadata=fragment["metadata"],
        )
        moved += int(added["added"])
        if int(added["added"]) < int(fragment["quantity"]):
            rollback_fragments.append(
                {
                    "kind": fragment["kind"],
                    "quantity": int(fragment["quantity"]) - int(added["added"]),
                    "metadata": fragment["metadata"],
                }
            )

    for fragment in rollback_fragments:
        add_item(
            source_record,
            fragment["kind"],
            fragment["quantity"],
            metadata=fragment["metadata"],
        )

    return {
        "ok": moved > 0,
        "moved": moved,
        "requested": max(int(quantity), 0),
        "source_inventory_id": str(source_record.get("inventory_id", "")),
        "target_inventory_id": str(target_record.get("inventory_id", "")),
        "item_kind": str(item_kind or ""),
        "item_id": str(item_id),
        "rolled_back": sum(int(fragment["quantity"]) for fragment in rollback_fragments),
    }


def drop_item(
    record: dict,
    *,
    item_kind: str | None = None,
    quantity: int = 1,
    item_id: str = "",
) -> dict:
    removed = remove_item(record, item_kind, quantity, item_id=item_id)
    if not removed["ok"]:
        return {
            "ok": False,
            "dropped": 0,
            "inventory_id": str(record.get("inventory_id", "")),
            "reason": "item_missing",
        }
    return {
        "ok": True,
        "dropped": removed["removed"],
        "inventory_id": str(record.get("inventory_id", "")),
        "world_drop": {
            "source_inventory_id": str(record.get("inventory_id", "")),
            "fragments": removed["fragments"],
        },
    }


def loot_item(
    source_record: dict,
    target_record: dict,
    *,
    item_kind: str | None = None,
    quantity: int = 1,
    item_id: str = "",
) -> dict:
    return transfer_item(
        source_record,
        target_record,
        item_kind=item_kind,
        quantity=quantity,
        item_id=item_id,
    )


__all__ = [
    "add_item",
    "drop_item",
    "loot_item",
    "remove_item",
    "transfer_item",
]
