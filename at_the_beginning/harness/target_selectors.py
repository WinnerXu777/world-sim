"""Typed JSON selectors: validated by schema, compiled to a mask by Python, resolved to *stable ids*, re-resolved at apply time.

Replaces model-written string masks (the legacy DSL in ``runtime/execution_selectors.py`` stays untouched as a legacy parser).
Example::

    {"of": "humans",
     "where": [{"field": "hunger", "op": ">", "value": 60}],
     "near": {"anchor": {"point": [120, 80]}, "radius": 30},
     "order_by": {"field": "hunger", "dir": "desc"},
     "limit": 3}

``resolve`` returns a ``Resolution`` holding the ids chosen at plan time. Between plan and apply the world can change (a
resident dies, a slot is reused, someone eats), so ``reresolve`` re-checks every plan-time id against the selector's predicate
(``where``, ``near``, ``space``, liveness) and reports who was dropped and why; it never adds new members, so a plan applies to
the entities it was made for, or fewer.

``bit_set``/``bit_clear`` test a bit of a column's integer value (only exact up to 2**24 in float32 columns; see the D0 audit,
G-D0-2).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import torch

from .schema import validate

OPS = (">", ">=", "<", "<=", "==", "!=", "in", "not_in", "bit_set", "bit_clear")
MAX_LIMIT = 10000

SELECTOR_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["of"],
    "properties": {
        "of": {"type": "string", "minLength": 1},
        "ids": {"type": "array", "items": {"type": ["string", "integer"]}},
        "space": {"type": "integer", "minimum": 0},
        "where": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["field", "op", "value"],
            "properties": {"field": {"type": "string", "minLength": 1}, "op": {"enum": list(OPS)}, "value": {}}}},
        "near": {"type": "object", "additionalProperties": False, "required": ["anchor", "radius"], "properties": {
            "anchor": {"type": "object", "additionalProperties": False, "properties": {
                "point": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "id": {"type": ["string", "integer"]}, "table": {"type": "string"}}},
            "radius": {"type": "number", "minimum": 0}}},
        "order_by": {"type": "object", "additionalProperties": False, "required": ["field"], "properties": {
            "field": {"type": "string", "minLength": 1}, "dir": {"enum": ["asc", "desc"]}}},
        "limit": {"type": "integer", "minimum": 0, "maximum": MAX_LIMIT},
    },
}


class SelectorError(ValueError):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass
class Resolution:
    selector: dict
    ids: tuple
    revision: int
    tick: int


@dataclass
class ReResolved:
    kept: tuple
    dropped: list = field(default_factory=list)        # [(id, reason)]

    @property
    def unchanged(self) -> bool:
        return not self.dropped


def check(selector: dict, world) -> list:
    """Schema and semantic errors for a selector against a world (empty list = valid)."""
    errors = validate(SELECTOR_SCHEMA, selector)
    if errors:
        return errors
    if selector["of"] not in world.tables:
        return [f"$.of: unknown table {selector['of']!r}; known: {sorted(world.tables)}"]
    table = world.table(selector["of"])
    for i, cond in enumerate(selector.get("where", [])):
        if cond["field"] not in table.columns:
            errors.append(f"$.where[{i}].field: table {table.name!r} has no field {cond['field']!r}")
        errors.extend(_check_value(i, cond))
    if "order_by" in selector and selector["order_by"]["field"] not in table.columns:
        errors.append(f"$.order_by.field: table {table.name!r} has no field {selector['order_by']['field']!r}")
    near = selector.get("near")
    if near:
        anchor = near["anchor"]
        if ("point" in anchor) == ("id" in anchor):
            errors.append("$.near.anchor: give exactly one of 'point' or 'id'")
        elif "id" in anchor:
            anchor_table = world.tables.get(anchor.get("table", selector["of"]))
            if anchor_table is None or anchor_table.slot_of(anchor["id"]) is None:
                errors.append(f"$.near.anchor.id: unknown anchor {anchor['id']!r}")
            elif not anchor_table.pos_cols:
                errors.append(f"$.near.anchor.table: table {anchor_table.name!r} has no position")
        if not table.pos_cols:
            errors.append(f"$.near: table {table.name!r} has no position columns")
    return errors


def _check_value(i, cond):
    op, value = cond["op"], cond["value"]
    path = f"$.where[{i}].value"
    if op in ("in", "not_in"):
        if not isinstance(value, list) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
            return [f"{path}: '{op}' needs a list of numbers"]
    elif op in ("bit_set", "bit_clear"):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 63:
            return [f"{path}: '{op}' needs a bit index 0..63"]
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return [f"{path}: '{op}' needs a finite number"]
    return []


def _predicate_mask(selector: dict, world) -> torch.Tensor:
    """Boolean mask over table rows for liveness, ids, space, where and near (no ordering, no limit)."""
    table = world.table(selector["of"])
    mask = table.live_mask().clone()
    if "ids" in selector:
        slots, _ = table.slots_of(selector["ids"])
        keep = torch.zeros_like(mask)
        if slots:
            keep[torch.tensor(slots, dtype=torch.long)] = True
        mask &= keep
    if "space" in selector and table.space_col:
        mask &= table.tensor[:, table.col(table.space_col)].long() == int(selector["space"])
    for cond in selector.get("where", []):
        column = table.tensor[:, table.col(cond["field"])]
        op, value = cond["op"], cond["value"]
        if op == ">":
            mask &= column > value
        elif op == ">=":
            mask &= column >= value
        elif op == "<":
            mask &= column < value
        elif op == "<=":
            mask &= column <= value
        elif op == "==":
            mask &= column == value
        elif op == "!=":
            mask &= column != value
        elif op == "in":
            mask &= torch.isin(column, torch.tensor(value, dtype=column.dtype))
        elif op == "not_in":
            mask &= ~torch.isin(column, torch.tensor(value, dtype=column.dtype))
        else:
            bits = (column.long() >> int(value)) & 1
            mask &= (bits == 1) if op == "bit_set" else (bits == 0)
    near = selector.get("near")
    if near:
        cx, cy = _anchor_point(near["anchor"], selector, world)
        xs = table.tensor[:, table.col(table.pos_cols[0])].double()
        ys = table.tensor[:, table.col(table.pos_cols[1])].double()
        mask &= ((xs - cx) ** 2 + (ys - cy) ** 2) <= float(near["radius"]) ** 2
    return mask


def _anchor_point(anchor: dict, selector: dict, world) -> tuple:
    if "point" in anchor:
        return float(anchor["point"][0]), float(anchor["point"][1])
    table = world.table(anchor.get("table", selector["of"]))
    return table.position(table.slot_of(anchor["id"]))


def resolve(selector: dict, world) -> Resolution:
    """Compile and run a selector now; returns ids in the requested order (default: by id), at most ``limit`` of them."""
    errors = check(selector, world)
    if errors:
        raise SelectorError(errors)
    table = world.table(selector["of"])
    slots = _predicate_mask(selector, world).nonzero(as_tuple=False).flatten().tolist()
    rows = [(table.ids[s], s) for s in slots if table.ids[s] is not None]
    order = selector.get("order_by")
    if order:
        col = table.col(order["field"])
        sign = -1.0 if order.get("dir", "asc") == "desc" else 1.0
        rows.sort(key=lambda r: (sign * float(table.tensor[r[1], col]), str(r[0])))
    else:
        rows.sort(key=lambda r: str(r[0]))
    if "limit" in selector:
        rows = rows[: selector["limit"]]
    return Resolution(selector=dict(selector), ids=tuple(r[0] for r in rows), revision=world.revision, tick=world.tick)


def reresolve(resolution: Resolution, world) -> ReResolved:
    """Re-check the plan-time ids against the selector's predicate in the current world (never adds members)."""
    selector = dict(resolution.selector)
    selector.pop("ids", None)
    selector.pop("limit", None)
    selector.pop("order_by", None)
    errors = check(selector, world)
    if errors:
        raise SelectorError(errors)
    table = world.table(selector["of"])
    mask = _predicate_mask(selector, world)
    kept, dropped = [], []
    for entity_id in resolution.ids:
        slot = table.slot_of(entity_id)
        if slot is None:
            dropped.append((entity_id, "gone"))
        elif not table.is_live_slot(slot):
            dropped.append((entity_id, "not_live"))
        elif not bool(mask[slot]):
            dropped.append((entity_id, "no_longer_matches"))
        else:
            kept.append(entity_id)
    return ReResolved(kept=tuple(kept), dropped=dropped)
