"""Commission options from the affordance engine's own facts (parity target: ``systems/commission/decide.legal_options``).

The facts are derived here from the world view (inventories, authored entities, the resident record) with their own code, not by
calling ``commission_facts``; only the *rule* mirrors the Stage 1 one (a refusal is legal exactly when its stated reason is true, and
the same order of options), which is what the parity test pins on a real booted engine.
"""
from __future__ import annotations

import math
from typing import Optional

from . import config

CURRENCY = "coin"        # = systems.inventory.schema.DEFAULT_CURRENCY_KIND (drift-tested)


def commission_facts(world, services, smith: str, customer: str, recipe: str, *, exclude_order: Optional[str] = None) -> dict:
    from systems.crafting.resolver import (crafting_recipe_ingredients, crafting_recipe_occupation_tags, crafting_recipe_station_kind)
    cfg = services.commission_config()
    record = services.record(smith) or {}
    occupation = str((record.get("occupation") or {}).get("kind", ""))
    pack = services.inventory(smith)
    missing = [{"item_kind": i["item_kind"], "missing": int(i.get("quantity", 1)) - pack.get(i["item_kind"], 0)}
               for i in crafting_recipe_ingredients(recipe) if pack.get(i["item_kind"], 0) < int(i.get("quantity", 1))]
    relation = (record.get("relationships") or {}).get(customer, {})
    closeness = float(relation.get("closeness", 0.0))
    rival = "rival" in (relation.get("tags") or [])
    return {
        "smith_alive": _alive(world, smith),
        "customer_alive": _alive(world, customer),
        "recipe_known": occupation in crafting_recipe_occupation_tags(recipe),
        "missing": missing,
        "forge_available": _station_available(services, smith, crafting_recipe_station_kind(recipe)),
        "can_afford": services.inventory(customer).get(CURRENCY, 0) >= int(cfg.get("prices", {}).get(recipe, 0)),
        "open_orders": len([o for o in services.orders(smith) if o["order_id"] != exclude_order]),
        "capacity": int(cfg.get("capacity_open_orders", 0)),
        "closeness": closeness,
        "rival": rival,
        "distrust": closeness <= float(cfg.get("distrust_closeness", -0.2)) or rival,
    }


def _alive(world, human: str) -> bool:
    table = world.table("humans")
    slot = table.slot_of(human)
    return slot is not None and table.is_live_slot(slot) and float(table.tensor[slot, table.col("hp")]) > 0.0


def _station_available(services, smith: str, station_kind: str) -> bool:
    """True when the station of ``station_kind`` nearest to the smith's work anchor is alive (no station needed -> True)."""
    if not station_kind or station_kind == "none":
        return True
    anchor = services.anchors(smith).get("work")
    stations = [e for e in services.entities() if e.kind == station_kind]
    if anchor is None or not stations:
        return False
    nearest = min(stations, key=lambda e: (math.hypot(e.x - anchor.x, e.y - anchor.y), e.id))
    return bool(nearest.alive)


def legal_options(facts: dict) -> list:
    """Same rule and order as ``systems.commission.decide.legal_options``."""
    refusals = []
    if not facts["forge_available"]:
        refusals.append("refuse_no_forge")
    if facts["missing"] or not facts["recipe_known"]:
        refusals.append("refuse_no_materials")
    if not facts["can_afford"]:
        refusals.append("refuse_cannot_afford")
    if facts["open_orders"] >= facts["capacity"]:
        refusals.append("refuse_busy")
    options = ["accept_commission"] if not refusals and facts["smith_alive"] else []
    if facts["distrust"]:
        refusals.append("refuse_distrust")
    options += refusals
    return options or ["refuse_busy"]


def offered_orders(services, smith: str) -> list:
    return sorted((o for o in services.orders(smith) if o["state"] == "offered"), key=lambda o: o["order_id"])
