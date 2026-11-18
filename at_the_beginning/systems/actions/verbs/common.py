"""Helpers shared by the verbs: bounded deltas on the humans table, the actor's position, the event builder."""
from __future__ import annotations

from typing import Optional

from harness import effects as fx
from harness.powers import bounded_amounts

# Column ranges for the provision deltas (the legacy ``_commit_provision_action`` clamps to 0..100).
RANGE = (0.0, 100.0)


def bounded_delta(world, actor: str, field_name: str, amount: float) -> fx.Delta:
    """A Delta on one humans field that cannot leave 0..100 (the table has no FieldSpec for it)."""
    current = world.table("humans").get(actor, field_name)
    return fx.delta("humans", actor, field_name, bounded_amounts([current], float(amount), RANGE[0], RANGE[1])[0])


def read(world, actor: str, field_name: str, default: float = 0.0) -> float:
    """A humans field, or ``default`` when the table has no such column (synthetic worlds carry fewer columns than the engine)."""
    try:
        return world.table("humans").get(actor, field_name)
    except KeyError:
        return default


def position(world, actor: str) -> Optional[tuple]:
    table = world.table("humans")
    return table.position(table.slot_of(actor))


def emit(world, actor: str, type_: str, payload: dict, *, others=(), visibility: str = "local", radius: float = 80.0) -> fx.Emit:
    return fx.Emit(type_, actors=(actor, *others), place=position(world, actor), visibility=visibility, radius=radius, payload=dict(payload))
