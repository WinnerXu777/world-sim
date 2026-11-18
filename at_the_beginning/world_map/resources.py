"""Resource declarations on authored-map entities (G-005, data only: nothing in the engine reads them yet).

An entity may say what resource it carries with flat optional keys, the same ones the chunk generator already writes
(``systems/worldgen``: ``resource``, ``amount``, ``tiles``, ``radius``), so generated chunks and hand-authored maps share one vocabulary:

    {"id": "family:bush_1", "kind": "berry_bush", "interactive": true, "position": [312, 168],
     "resource": "berries", "amount": 24, "cap": 40, "regrow": 0.02, "radius": 6}

* ``resource``  name of what the entity yields (``RESOURCE_KINDS``); it must fit the entity ``kind``;
* ``amount``    units the entity stands for (initial stock), ``cap`` its maximum, ``regrow`` units per tick, ``radius`` the geo circle in
                backend units, ``tiles`` the number of tiles an aggregate stands for (informational, written by the generator),
                ``item`` the inventory item a gather yields (default per resource, chosen by the loader), ``water`` a farm plot's water;
* ``stock``     ``{item: quantity}`` seeded into a storage entity (kinds ``storage chest storage_case crate``);
* ``capacity``  occupants of a shelter entity (kinds ``bed shelter hearth``).
All keys are optional; an entity with a resource-bearing ``kind`` and none of them gets the loader's defaults (step 2). The values are
validated here with no engine dependency; how they become tensor columns is the loader's job (``systems/map/resources.py``, step 2).
Only interactive entities may carry them. See ``1008_map_resources_design.md``.
"""
from __future__ import annotations

import math
import re

# resource name -> entity kinds that may carry it (the first kind is the default for authored maps; the rest include the generator's)
RESOURCE_KINDS = {
    "water": ("well",),
    "crops": ("farm_plot", "farm"),
    "berries": ("berry_bush", "berry_patch", "bush"),
    "wood": ("tree", "forest", "wood_pile"),
    "stone": ("stone_pile", "stone_outcrop"),
    "ore": ("iron_pile", "ore_vein", "ore_node"),
    "fish": ("fish_spot",),
    "reeds": ("reed_bed",),
    "mushrooms": ("mushroom_patch",),
}
STORAGE_KINDS = ("storage", "chest", "storage_case", "crate")
SHELTER_KINDS = ("bed", "shelter", "hearth")
KIND_RESOURCE = {kind: name for name, kinds in RESOURCE_KINDS.items() for kind in kinds}
STOCK_KEYS = ("amount", "cap", "regrow", "radius", "tiles", "item", "water")   # need a ``resource``
DECLARATION_KEYS = ("resource", "stock", "capacity") + STOCK_KEYS
AMOUNT_MAX = 1_000_000.0  # units an entity may stand for (an aggregate ore vein can exceed the 100 of a tensor column; the loader clamps)
RADIUS_MAX = 256.0        # backend units (one chunk side); aggregate features such as a forest are large, the loader clamps the geo circle
REGROW_MAX = 10.0         # per tick
CAPACITY_MAX = 32
ITEM_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def declared(item: dict) -> bool:
    return any(key in item for key in DECLARATION_KEYS)


def check_resource(item: dict, kind: str, interactive: bool, path: str, error) -> dict | None:
    """Validate the resource keys of one entity dict. ``error(path, message)`` records a problem. Returns the normalised declaration
    (a plain dict with ``name`` for the resource, plus the other declared keys) or None when nothing is declared or it is invalid."""
    if not declared(item):
        return None
    problems: list = []

    def bad(key, message):
        problems.append((f"{path}.{key}" if key else path, message))

    if not interactive:
        bad("", "resource keys need an interactive entity (interactive: true)")
    out: dict = {}
    name = item.get("resource")
    if "resource" in item:
        if not isinstance(name, str) or name not in RESOURCE_KINDS:
            bad("resource", f"must be one of {sorted(RESOURCE_KINDS)}, got {name!r}")
        elif kind not in RESOURCE_KINDS[name]:
            bad("resource", f"{name!r} does not fit entity kind {kind!r} (allowed kinds: {list(RESOURCE_KINDS[name])})")
        else:
            out["name"] = name
    else:
        for key in STOCK_KEYS:
            if key in item:
                bad(key, "needs a \"resource\" naming what the entity yields")
    for key, hi in (("amount", AMOUNT_MAX), ("cap", AMOUNT_MAX), ("regrow", REGROW_MAX), ("water", 100.0)):
        if key in item and "resource" in item:
            value = item[key]
            if not (_num(value) and 0 <= value <= hi):
                bad(key, f"must be a finite number in 0..{hi:g}, got {value!r}")
            else:
                out[key] = float(value)
    if "cap" in out and out["cap"] <= 0:
        bad("cap", "must be > 0")
    if "amount" in out and "cap" in out and out["amount"] > out["cap"]:
        bad("amount", f"{out['amount']:g} exceeds cap {out['cap']:g}")
    if "water" in item and name != "crops":
        bad("water", "only a crops entity (farm plot) has water")
    if "radius" in item and "resource" in item:
        value = item["radius"]
        if not (_num(value) and 0 < value <= RADIUS_MAX):
            bad("radius", f"must be a finite number in (0, {RADIUS_MAX:g}], got {value!r}")
        else:
            out["radius"] = float(value)
    if "tiles" in item and "resource" in item:
        value = item["tiles"]
        if not (_int(value) and value >= 0):
            bad("tiles", f"must be a non-negative integer, got {value!r}")
        else:
            out["tiles"] = int(value)
    if "item" in item and "resource" in item:
        value = item["item"]
        if not (isinstance(value, str) and ITEM_RE.match(value)):
            bad("item", f"must be a lower-case item name (letters, digits, _), got {value!r}")
        else:
            out["item"] = value
    if "capacity" in item:
        value = item["capacity"]
        if kind not in SHELTER_KINDS:
            bad("capacity", f"only for shelter kinds {list(SHELTER_KINDS)}, not {kind!r}")
        elif not (_int(value) and 1 <= value <= CAPACITY_MAX):
            bad("capacity", f"must be an integer in 1..{CAPACITY_MAX}, got {value!r}")
        else:
            out["capacity"] = int(value)
    if "stock" in item:
        value = item["stock"]
        if kind not in STORAGE_KINDS:
            bad("stock", f"only for storage kinds {list(STORAGE_KINDS)}, not {kind!r}")
        elif not isinstance(value, dict) or not value:
            bad("stock", "must be a non-empty object {item: quantity}")
        else:
            stock = {}
            for entry, quantity in value.items():
                if not (isinstance(entry, str) and ITEM_RE.match(entry)):
                    bad(f"stock.{entry}", "item names are lower-case words (letters, digits, _)")
                elif not (_int(quantity) and 1 <= quantity <= 10000):
                    bad(f"stock.{entry}", f"quantity must be an integer in 1..10000, got {quantity!r}")
                else:
                    stock[entry] = int(quantity)
            out["stock"] = stock
    for where, message in problems:
        error(where, message)
    return None if problems else out
