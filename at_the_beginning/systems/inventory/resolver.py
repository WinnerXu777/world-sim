from __future__ import annotations

"""Pure inventory rules: stackability, slots, and capacity checks."""

from copy import deepcopy

from .schema import container_kind_def, item_kind_def


def item_def(item_kind: str) -> dict:
    return item_kind_def(item_kind)


def container_def(container_kind: str) -> dict:
    return container_kind_def(container_kind)


def item_tags(item_kind: str) -> set[str]:
    return set(item_def(item_kind).get("tags", []))


def item_slot(item_kind: str) -> str | None:
    return item_def(item_kind).get("slot")


def item_stack_limit(item_kind: str) -> int:
    item = item_def(item_kind)
    if not item:
        return 1
    return max(int(item.get("max_stack", 1)), 1)


def is_stackable(item_kind: str) -> bool:
    item = item_def(item_kind)
    return bool(item.get("stackable", False) and item_stack_limit(item_kind) > 1)


def is_currency(item_kind: str) -> bool:
    return "currency" in item_tags(item_kind)


def is_weapon(item_kind: str) -> bool:
    return "weapon" in item_tags(item_kind)


def item_unit_weight(item_kind: str) -> float:
    item = item_def(item_kind)
    return max(float(item.get("unit_weight", 0.0)), 0.0)


def inventory_capacity_slots(record: dict) -> int | None:
    raw = record.get("capacity_slots")
    if raw in (None, "", False):
        return None
    return max(int(raw), 0)


def inventory_capacity_weight(record: dict) -> float | None:
    raw = record.get("capacity_weight")
    if raw in (None, "", False):
        return None
    return max(float(raw), 0.0)


def used_slots(record: dict) -> int:
    return len(record.get("items", []))


def total_weight(record: dict) -> float:
    total = 0.0
    for item in record.get("items", []):
        total += max(float(item.get("unit_weight", 0.0)), 0.0) * max(int(item.get("quantity", 0)), 0)
    return round(total, 3)


def stack_matches(stack: dict, item_kind: str, metadata: dict | None = None) -> bool:
    if str(stack.get("kind", "")) != str(item_kind):
        return False
    if not bool(stack.get("stackable", False)):
        return False
    current_metadata = deepcopy(stack.get("metadata", {}))
    return current_metadata == deepcopy(metadata or {})


def find_merge_target(record: dict, item_kind: str, metadata: dict | None = None) -> dict | None:
    if not is_stackable(item_kind):
        return None
    max_stack = item_stack_limit(item_kind)
    for stack in record.get("items", []):
        if not stack_matches(stack, item_kind, metadata):
            continue
        if int(stack.get("quantity", 0)) < max_stack:
            return stack
    return None


def can_add_item(record: dict, item_kind: str, quantity: int = 1, metadata: dict | None = None) -> bool:
    remaining = max(int(quantity), 0)
    if remaining <= 0:
        return True

    weight_capacity = inventory_capacity_weight(record)
    if weight_capacity is not None:
        projected_weight = total_weight(record) + (item_unit_weight(item_kind) * remaining)
        if projected_weight > weight_capacity + 1e-6:
            return False

    capacity = inventory_capacity_slots(record)
    if capacity is None:
        return True

    free_slots = max(capacity - used_slots(record), 0)
    if is_stackable(item_kind):
        merge_target = find_merge_target(record, item_kind, metadata)
        if merge_target is not None:
            remaining -= max(item_stack_limit(item_kind) - int(merge_target.get("quantity", 0)), 0)
        if remaining <= 0:
            return True
        stacks_needed = (remaining + item_stack_limit(item_kind) - 1) // item_stack_limit(item_kind)
        return stacks_needed <= free_slots

    return remaining <= free_slots


__all__ = [
    "can_add_item",
    "container_def",
    "find_merge_target",
    "inventory_capacity_slots",
    "is_currency",
    "is_stackable",
    "is_weapon",
    "item_def",
    "item_slot",
    "item_stack_limit",
    "item_tags",
    "stack_matches",
    "used_slots",
]
