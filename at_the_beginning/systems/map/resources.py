"""G-005 step 2: authored-map resources -> ``m_tensor`` rows (behind ``EDEN_MAP_RESOURCES=1``, default off).

``spec_for(entity)`` turns a registered map entity (``systems.movement.map_contract`` dict: ``kind`` plus the optional validated
declaration under ``"resource"``, see ``world_map/resources.py``) into the tensor row the legacy resolvers already understand:

* ``water`` (kind ``well``)   -> ``M_WELL`` (23): water, replenish rate, build 100 (the water cycle ignores wells below 100);
* ``crops`` (``farm_plot``)   -> ``M_FARM`` (22): food, water, growth rate, build 100;
* ``berries mushrooms fish``  -> ``M_RESOURCE_NODE`` (27), edible: the stock is the food column (so eating, scoring, scarcity work);
* ``wood stone ore reeds``    -> ``M_RESOURCE_NODE`` (27), material: the stock is ``M_NODE_STOCK``;
* kind ``shelter``            -> ``M_HOUSE`` (20) with ``S_SHELTER_CAP`` = ``capacity`` (default 4), build 100;
* storage kinds with ``stock``-> stay ``M_STORAGE_CASE``; the stock is added to the container once (``seed_stock``).
``bed`` and ``hearth`` stay inert ``M_MAP_OBJECT`` rows (kind-based, as the affordance layer reads them); ``capacity`` on them is data only.
An entity whose kind is resource-bearing and which declares nothing gets the defaults below, so the shipped maps need no file change.
Units above a tensor column's range are clamped to the column (food/water 100); the material stock keeps the full amount.
"""
from __future__ import annotations

import os
from typing import Optional

try:
    import genesis_config as cfg
    from world_map.resources import KIND_RESOURCE, SHELTER_KINDS, STORAGE_KINDS
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.world_map.resources import KIND_RESOURCE, SHELTER_KINDS, STORAGE_KINDS

FLAG = "EDEN_MAP_RESOURCES"

NODE_KIND_IDS = {"berries": 1, "wood": 2, "stone": 3, "ore": 4, "fish": 5, "reeds": 6, "mushrooms": 7}
EDIBLE = frozenset({"berries", "mushrooms", "fish"})
# inventory kinds (systems/inventory/schema.py). Nothing here yields crop_bundle: that is the farmers' cargo in tasks/families/occupation.py.
# Ore yields iron_ore, not iron_ingot: the recipes (commission, smith loop) consume ingots and no smelting step exists yet.
ITEM = {"berries": "berries", "wood": "wood_bundle", "stone": "stone_chunk", "ore": "iron_ore", "fish": "fish_catch",
        "reeds": "reed_bundle", "mushrooms": "mushrooms"}
# per resource: (amount, regrow per tick, geo radius in backend units)
DEFAULTS = {
    "water": (cfg.INITIAL_WATER_WELL, cfg.WELL_WATER_REPLENISH_RATE, 8.0),
    "crops": (0.0, cfg.FARM_FOOD_GROWTH_RATE, 10.0),
    "berries": (40.0, 0.02, 6.0), "mushrooms": (30.0, 0.02, 6.0), "fish": (30.0, 0.03, 8.0),
    "wood": (30.0, 0.0, 6.0), "stone": (30.0, 0.0, 6.0), "ore": (20.0, 0.0, 6.0), "reeds": (30.0, 0.01, 6.0),
}
KIND_OVERRIDES = {"tree": {"amount": 60.0, "regrow": 0.005}, "forest": {"amount": 60.0, "regrow": 0.005, "radius": 12.0}}
FARM_WATER = cfg.INITIAL_WATER_FARM
SHELTER_CAPACITY = 4
STORAGE_RADIUS = 4.0
OBJECT_SCALE = 2.0


def enabled() -> bool:
    return os.environ.get(FLAG, "") == "1"


def spec_for(entity: dict) -> Optional[dict]:
    """``{"m_type", "scale", "col_vals", "name"}`` for a resource-bearing map entity, else None (inert object / storage / decoration)."""
    kind = entity.get("kind", "")
    decl = entity.get("resource") or {}
    if kind == "shelter":
        cap = decl.get("capacity", SHELTER_CAPACITY)
        return {"name": "shelter", "m_type": cfg.M_HOUSE, "scale": decl.get("radius", 8.0),
                "col_vals": {cfg.S_DURABILITY: 100.0, cfg.S_SHELTER_CAP: float(cap), cfg.S_BUILD_PROGRESS: 100.0}}
    name = decl.get("name") or KIND_RESOURCE.get(kind)
    if name is None:
        return None
    amount, regrow, radius = DEFAULTS[name]
    over = KIND_OVERRIDES.get(kind, {})
    amount = float(decl.get("amount", over.get("amount", amount)))
    regrow = float(decl.get("regrow", over.get("regrow", regrow)))
    radius = float(decl.get("radius", over.get("radius", radius)))
    if name == "water":
        return {"name": name, "m_type": cfg.M_WELL, "scale": radius,
                "col_vals": {cfg.S_DURABILITY: 100.0, cfg.S_BUILD_PROGRESS: 100.0,
                             cfg.M_RESOURCE_WATER: min(cfg.MAX_ENTITY_WATER, amount), cfg.M_GROWTH_RATE: regrow}}
    if name == "crops":
        return {"name": name, "m_type": cfg.M_FARM, "scale": radius,
                "col_vals": {cfg.S_DURABILITY: 100.0, cfg.S_BUILD_PROGRESS: 100.0,
                             cfg.M_RESOURCE_FOOD: min(cfg.MAX_ENTITY_FOOD, amount),
                             cfg.M_RESOURCE_WATER: min(cfg.MAX_ENTITY_WATER, float(decl.get("water", FARM_WATER))),
                             cfg.M_GROWTH_RATE: regrow}}
    cap = float(decl.get("cap", max(amount, DEFAULTS[name][0])))
    cols = {cfg.M_NODE_KIND: float(NODE_KIND_IDS[name]), cfg.M_DEPLETED_TICK: -1.0, cfg.M_GROWTH_RATE: regrow}
    if name in EDIBLE:
        cols[cfg.M_RESOURCE_FOOD] = min(cfg.MAX_ENTITY_FOOD, amount)
        cols[cfg.M_NODE_CAP] = min(cfg.MAX_ENTITY_FOOD, cap)
    else:
        cols[cfg.M_NODE_STOCK] = amount
        cols[cfg.M_NODE_CAP] = cap
    return {"name": name, "m_type": cfg.M_RESOURCE_NODE, "scale": radius, "col_vals": cols}


def stock_of(entity: dict) -> dict:
    """``{item: qty}`` a storage entity declares (empty when none)."""
    if entity.get("kind") not in STORAGE_KINDS:
        return {}
    return dict((entity.get("resource") or {}).get("stock") or {})


def item_for(name: str, override: Optional[str] = None) -> str:
    return override or ITEM[name]
