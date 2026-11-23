"""Opt-in read-only resident inspection power."""
import copy
import os
import math
from typing import Literal

from . import effects as fx
from .registry import power


def register_new_powers(registry):
    from .powers import Draft, PowerRefused, _humans
    if os.environ.get("EDEN_GOD_NEW_TOOLS") != "1":
        return

    @power("inspect_resident", risk="reversible", registry=registry)
    def inspect_resident(world, targets: dict) -> Draft:
        """Inspect the current records of residents matched by a selector."""
        resolution = _humans(world, targets)
        records = {uid: copy.deepcopy(world.residents.get(uid, {})) for uid in resolution.ids}
        return Draft(resolution, [], {"residents": records})

    @power("grant_item", risk="reversible", registry=registry)
    def grant_item(world, targets: dict, item: str, qty: int = 1) -> Draft:
        """Create a quantity of a catalogued item for each selected resident."""
        from systems.inventory.schema import ITEM_KIND_DEFS
        if item not in ITEM_KIND_DEFS:
            raise PowerRefused("unknown_item", item)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise PowerRefused("invalid_quantity", str(qty))
        resolution = _humans(world, targets)
        for uid in resolution.ids:
            room = world.items.room(uid, item)
            if room is not None and room < qty:
                raise PowerRefused("no_room", str(uid))
        effects = [fx.Transfer(item, qty, None, uid) for uid in resolution.ids]
        event = fx.Emit("item_granted", actors=resolution.ids, visibility="private", payload={"item": item, "qty": qty})
        return Draft(resolution, effects, {"item": item, "qty": qty}, event,
                     fx.ItemPermit(produce={item: qty * len(resolution.ids)}))

    def pair(world, owner, other):
        from .powers import _resolution
        if owner == other:
            raise PowerRefused("self_link")
        table = world.table("humans")
        for uid in (owner, other):
            slot = table.slot_of(uid)
            if uid not in world.residents or slot is None or not table.is_live_slot(slot):
                raise PowerRefused("unknown_resident", uid)
        return _resolution(world, {"of": "humans", "ids": [owner, other]}, (owner, other))

    @power("set_relationship", risk="reversible", registry=registry)
    def set_relationship(world, owner: str, other: str, value: float) -> Draft:
        """Set one resident's closeness toward another in [-1, 1]."""
        res = pair(world, owner, other)
        if isinstance(value, bool) or not math.isfinite(value) or not -1 <= value <= 1:
            raise PowerRefused("invalid_amount")
        old = world.residents[owner].get("relationships", {}).get(other, {})
        kind = old.get("kind", "known")
        return Draft(res, [fx.ResidentRelations(((owner, other, kind, float(value)),))],
                     {"value": value}, fx.Emit("relationship_changed", actors=res.ids, visibility="private"))

    @power("set_kin", risk="reversible", registry=registry)
    def set_kin(world, owner: str, other: str, kind: Literal["parent", "child", "spouse"]) -> Draft:
        """Make owner the parent, child, or spouse of other."""
        res = pair(world, owner, other)
        if kind != "spouse":
            parent, child = (owner, other) if kind == "parent" else (other, owner)
            table = world.table("humans")
            if "age" not in table.columns:
                raise PowerRefused("no_column", "age")
            if table.get(parent, "age") < table.get(child, "age") + 12:
                raise PowerRefused("parent_too_young")
            # Follow parent links from the prospective parent; reaching the child creates a cycle.
            pending, seen = [parent], set()
            while pending:
                current = pending.pop()
                if current == child:
                    raise PowerRefused("kin_cycle")
                if current in seen:
                    continue
                seen.add(current)
                pending.extend(uid for uid, rel in world.residents.get(current, {}).get("relationships", {}).items()
                               if rel.get("kind") == "parent" or "parent" in rel.get("tags", []))
            updates = ((parent, child, "child", None), (child, parent, "parent", None))
        else:
            updates = ((owner, other, "mate", None), (other, owner, "mate", None))
        return Draft(res, [fx.ResidentRelations(updates)], {"kind": kind},
                     fx.Emit("kin_changed", actors=res.ids, visibility="private", payload={"kind": kind}))

    def calendar_draft(world, field, value):
        from . import calendar
        from .powers import _resolution
        allowed = calendar.SEASONS if field == "season" else calendar.BLOCKS
        if value != "clear" and value not in allowed:
            raise PowerRefused("invalid_value")
        override = None if value == "clear" else value
        res = _resolution(world, {}, ())
        return Draft(res, [fx.CalendarOverride(field, override)], {"value": value},
                     fx.Emit("season_changed" if field == "season" else "time_changed", visibility="private", payload={"value": value}))

    @power("set_season", risk="reversible", registry=registry)
    def set_season(world, value: str) -> Draft:
        """Override the calendar season, or clear the override."""
        return calendar_draft(world, "season", value)

    @power("set_time_of_day", risk="reversible", registry=registry)
    def set_time_of_day(world, value: str) -> Draft:
        """Override the calendar time block, or clear the override."""
        return calendar_draft(world, "time", value)
