from __future__ import annotations

"""Schema helpers for the event-driven inventory system."""

from copy import deepcopy

INVENTORY_SCHEMA_VERSION = 1
DEFAULT_CURRENCY_KIND = "coin"
DEFAULT_MAIN_HAND_SLOT = "main_hand"

ITEM_KIND_DEFS: dict[str, dict] = {
    "wood_bundle": {
        "label": "Wood Bundle",
        "stackable": True,
        "max_stack": 20,
        "tags": ["material", "wood"],
        "slot": None,
        "unit_weight": 1.2,
        "value": 1.5,
    },
    "wood_log": {
        "label": "Wood Log",
        "stackable": True,
        "max_stack": 10,
        "tags": ["material", "wood", "log"],
        "slot": None,
        "unit_weight": 2.5,
        "value": 2.2,
    },
    "fiber_bundle": {
        "label": "Fiber Bundle",
        "stackable": True,
        "max_stack": 24,
        "tags": ["material", "fiber"],
        "slot": None,
        "unit_weight": 0.4,
        "value": 1.8,
    },
    "stone_chunk": {
        "label": "Stone Chunk",
        "stackable": True,
        "max_stack": 18,
        "tags": ["material", "stone"],
        "slot": None,
        "unit_weight": 1.8,
        "value": 1.6,
    },
    "herb_bundle": {
        "label": "Herb Bundle",
        "stackable": True,
        "max_stack": 12,
        "tags": ["material", "herb", "medical"],
        "slot": None,
        "unit_weight": 0.2,
        "value": 2.8,
    },
    "fish_catch": {
        "label": "Fresh Catch",
        "stackable": True,
        "max_stack": 12,
        "tags": ["food", "fish", "perishable"],
        "slot": None,
        "unit_weight": 0.7,
        "value": 3.6,
    },
    "crop_bundle": {
        "label": "Crop Bundle",
        "stackable": True,
        "max_stack": 16,
        "tags": ["food", "crop", "material"],
        "slot": None,
        "unit_weight": 0.8,
        "value": 2.8,
    },
    "berries": {
        "label": "Wild Berries",
        "stackable": True,
        "max_stack": 24,
        "tags": ["food", "berries", "perishable"],
        "slot": None,
        "unit_weight": 0.2,
        "value": 1.6,
    },
    "mushrooms": {
        "label": "Mushrooms",
        "stackable": True,
        "max_stack": 20,
        "tags": ["food", "mushroom", "perishable"],
        "slot": None,
        "unit_weight": 0.15,
        "value": 1.8,
    },
    "reed_bundle": {
        "label": "Reed Bundle",
        "stackable": True,
        "max_stack": 24,
        "tags": ["material", "fiber", "reed"],
        "slot": None,
        "unit_weight": 0.6,
        "value": 0.9,
    },
    "iron_ore": {
        "label": "Iron Ore",
        "stackable": True,
        "max_stack": 20,
        "tags": ["material", "metal", "ore"],
        "slot": None,
        "unit_weight": 2.4,
        "value": 1.8,
    },
    "coin": {
        "label": "Coins",
        "stackable": True,
        "max_stack": 999_999,
        "tags": ["currency"],
        "slot": None,
        "unit_weight": 0.0,
        "value": 1.0,
    },
    "water_flask": {
        "label": "Water Flask",
        "stackable": True,
        "max_stack": 8,
        "tags": ["food", "water", "consumable"],
        "slot": None,
        "unit_weight": 1.0,
        "value": 1.0,
    },
    "iron_ingot": {
        "label": "Iron Ingot",
        "stackable": True,
        "max_stack": 20,
        "tags": ["material", "metal", "iron"],
        "slot": None,
        "unit_weight": 2.0,
        "value": 4.0,
    },
    "sword": {
        "label": "Sword",
        "stackable": False,
        "max_stack": 1,
        "tags": ["weapon", "blade", "sword"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 2.2,
        "value": 30.0,
    },
    "club": {
        "label": "Club",
        "stackable": False,
        "max_stack": 1,
        "tags": ["weapon", "blunt"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 2.4,
        "value": 4.0,
    },
    "knife": {
        "label": "Knife",
        "stackable": False,
        "max_stack": 1,
        "tags": ["weapon", "blade"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 0.9,
        "value": 7.0,
    },
    "spear": {
        "label": "Spear",
        "stackable": False,
        "max_stack": 1,
        "tags": ["weapon", "polearm"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 2.1,
        "value": 9.0,
    },
    "axe": {
        "label": "Axe",
        "stackable": False,
        "max_stack": 1,
        "tags": ["tool", "weapon", "axe", "woodcutting"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 2.4,
        "value": 8.5,
    },
    "hammer": {
        "label": "Hammer",
        "stackable": False,
        "max_stack": 1,
        "tags": ["tool", "builder"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 2.0,
        "value": 7.5,
    },
    "hoe": {
        "label": "Hoe",
        "stackable": False,
        "max_stack": 1,
        "tags": ["tool", "farming"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 2.2,
        "value": 7.0,
    },
    "basket": {
        "label": "Basket",
        "stackable": False,
        "max_stack": 1,
        "tags": ["tool", "container_tool", "gathering"],
        "slot": None,
        "unit_weight": 1.0,
        "value": 4.5,
    },
    "pack": {
        "label": "Pack",
        "stackable": False,
        "max_stack": 1,
        "tags": ["tool", "trade", "storage"],
        "slot": None,
        "unit_weight": 1.3,
        "value": 6.0,
    },
    "fishing_rod": {
        "label": "Fishing Rod",
        "stackable": False,
        "max_stack": 1,
        "tags": ["tool", "fishing"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 1.1,
        "value": 7.0,
    },
    "simple_net": {
        "label": "Simple Net",
        "stackable": False,
        "max_stack": 1,
        "tags": ["tool", "fishing", "net"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 1.4,
        "value": 8.0,
    },
    "stone_blade": {
        "label": "Stone Blade",
        "stackable": False,
        "max_stack": 1,
        "tags": ["component", "blade", "tool_component"],
        "slot": None,
        "unit_weight": 0.5,
        "value": 2.0,
    },
    "rope": {
        "label": "Rope",
        "stackable": True,
        "max_stack": 10,
        "tags": ["component", "fiber"],
        "slot": None,
        "unit_weight": 0.6,
        "value": 3.0,
    },
    "plank_bundle": {
        "label": "Plank Bundle",
        "stackable": True,
        "max_stack": 10,
        "tags": ["component", "wood"],
        "slot": None,
        "unit_weight": 1.6,
        "value": 4.0,
    },
    # animal products (1008 creatures: a kill's ``loot``, an egg or a fleece from a domestic animal); raw materials, not "food" yet (nothing cooks them), so no verb eats them
    "meat": {"label": "Meat", "stackable": True, "max_stack": 12, "tags": ["material", "animal", "meat"], "slot": None, "unit_weight": 1.0, "value": 2.5},
    "hide": {"label": "Hide", "stackable": True, "max_stack": 10, "tags": ["material", "animal", "hide"], "slot": None, "unit_weight": 1.5, "value": 3.0},
    "bone": {"label": "Bone", "stackable": True, "max_stack": 20, "tags": ["material", "animal", "bone"], "slot": None, "unit_weight": 0.6, "value": 1.0},
    "feather": {"label": "Feather", "stackable": True, "max_stack": 40, "tags": ["material", "animal", "feather"], "slot": None, "unit_weight": 0.02, "value": 0.8},
    "egg": {"label": "Egg", "stackable": True, "max_stack": 12, "tags": ["material", "animal", "egg"], "slot": None, "unit_weight": 0.1, "value": 1.5},
    "silk": {"label": "Silk", "stackable": True, "max_stack": 20, "tags": ["material", "animal", "fiber", "silk"], "slot": None, "unit_weight": 0.1, "value": 4.0},
    "scrap": {"label": "Scrap", "stackable": True, "max_stack": 20, "tags": ["material", "scrap"], "slot": None, "unit_weight": 0.8, "value": 0.8},
    "wool": {"label": "Wool", "stackable": True, "max_stack": 20, "tags": ["material", "animal", "fiber", "wool"], "slot": None, "unit_weight": 0.3, "value": 2.0},
    "rations": {
        "label": "Rations",
        "stackable": True,
        "max_stack": 20,
        "tags": ["food", "consumable"],
        "slot": None,
        "unit_weight": 0.5,
        "value": 3.0,
    },
    # clothing (1008 temperature): the felt-temperature bonus per kind is ``systems/clothing.INSULATION``; a garment in the pack counts, the best one only
    "cloak": {"label": "Cloak", "stackable": False, "max_stack": 1, "tags": ["clothing", "cloth"], "slot": None, "unit_weight": 0.9, "value": 12.0},
    "fur_coat": {"label": "Fur Coat", "stackable": False, "max_stack": 1, "tags": ["clothing", "fur"], "slot": None, "unit_weight": 2.2, "value": 30.0},
    "bandage": {
        "label": "Bandage",
        "stackable": True,
        "max_stack": 12,
        "tags": ["medical", "consumable"],
        "slot": None,
        "unit_weight": 0.1,
        "value": 5.0,
    },
    "torch": {
        "label": "Torch",
        "stackable": False,
        "max_stack": 1,
        "tags": ["tool", "light"],
        "slot": DEFAULT_MAIN_HAND_SLOT,
        "unit_weight": 0.8,
        "value": 3.5,
    },
}

CONTAINER_KIND_DEFS: dict[str, dict] = {
    "resident_loadout": {
        "label": "Resident Loadout",
        "capacity_slots": 4,
        "capacity_weight": 8.0,
        "tags": ["owner_inventory", "resident"],
    },
    "incarnation_pack": {
        "label": "Incarnation Pack",
        "capacity_slots": 14,
        "capacity_weight": 28.0,
        "tags": ["owner_inventory", "player"],
    },
    "house_storage": {
        "label": "House Storage",
        "capacity_slots": 24,
        "capacity_weight": 120.0,
        "tags": ["container", "household_storage", "house"],
    },
    "storage_case": {
        "label": "Storage Case",
        "capacity_slots": 16,
        "capacity_weight": 96.0,
        "tags": ["container", "storage"],
    },
    "stockpile": {
        "label": "Stockpile",
        "capacity_slots": 48,
        "capacity_weight": 360.0,
        "tags": ["container", "bulk_storage"],
    },
    "corpse_loot": {
        "label": "Corpse Loot",
        "capacity_slots": 6,
        "capacity_weight": 18.0,
        "tags": ["container", "loot"],
    },
}

OWNER_INVENTORY_DEFAULTS: dict[str, dict] = {
    "resident": {
        "container_kind": "resident_loadout",
        "capacity_slots": 4,
        "capacity_weight": 8.0,
        "label": "Resident Loadout",
    },
    "human": {
        "container_kind": "resident_loadout",
        "capacity_slots": 4,
        "capacity_weight": 8.0,
        "label": "Resident Loadout",
    },
    "incarnation": {
        "container_kind": "incarnation_pack",
        "capacity_slots": 14,
        "capacity_weight": 28.0,
        "label": "Incarnation Pack",
    },
    "player": {
        "container_kind": "incarnation_pack",
        "capacity_slots": 14,
        "capacity_weight": 28.0,
        "label": "Player Pack",
    },
}


def item_kind_def(item_kind: str) -> dict:
    return dict(ITEM_KIND_DEFS.get(str(item_kind), {}))


def container_kind_def(container_kind: str) -> dict:
    return dict(CONTAINER_KIND_DEFS.get(str(container_kind), {}))


def owner_inventory_defaults(owner_kind: str) -> dict:
    return dict(OWNER_INVENTORY_DEFAULTS.get(str(owner_kind), {}))


def build_item_stack(
    item_kind: str,
    *,
    item_id: str,
    quantity: int = 1,
    metadata: dict | None = None,
) -> dict:
    item_def = item_kind_def(item_kind)
    if not item_def:
        raise KeyError(f"unknown inventory item kind: {item_kind}")
    return {
        "id": str(item_id),
        "kind": str(item_kind),
        "label": str(item_def.get("label", item_kind)),
        "quantity": max(int(quantity), 1),
        "stackable": bool(item_def.get("stackable", False)),
        "slot": item_def.get("slot"),
        "tags": list(item_def.get("tags", [])),
        "unit_weight": float(item_def.get("unit_weight", 0.0)),
        "value": float(item_def.get("value", 0.0)),
        "metadata": deepcopy(metadata or {}),
    }


__all__ = [
    "CONTAINER_KIND_DEFS",
    "DEFAULT_CURRENCY_KIND",
    "DEFAULT_MAIN_HAND_SLOT",
    "INVENTORY_SCHEMA_VERSION",
    "ITEM_KIND_DEFS",
    "OWNER_INVENTORY_DEFAULTS",
    "build_item_stack",
    "container_kind_def",
    "item_kind_def",
    "owner_inventory_defaults",
]
