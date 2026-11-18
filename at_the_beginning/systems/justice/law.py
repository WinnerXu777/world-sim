"""The law, pure: who holds authority, what a theft costs the thief, and what can actually be levied from a pack."""
from __future__ import annotations

import math
from typing import Callable

AUTHORITY_OCCUPATIONS = ("guard", "elder")
COMPENSATION = 1.5          # the thief owes the value of what was taken plus half again to the victim
KEEP_FOOD = 1               # a levy never takes a resident's last unit of food


def is_authority(record: dict) -> bool:
    """A resident whose roster record says ``authority`` or whose occupation is a guard or an elder."""
    record = record or {}
    if (record.get("roster") or {}).get("authority"):
        return True
    return str((record.get("occupation") or {}).get("kind", "")) in AUTHORITY_OCCUPATIONS


def damages(value: float) -> float:
    return round(float(value) * COMPENSATION, 6)


def levy(pack: dict, item: str, owed: float, value: Callable[[str], float], edible: tuple) -> list:
    """``[(kind, qty), ...]`` taken from ``pack`` toward ``owed`` (value): the stolen item first, then coin, then other goods by value; edibles stop short of the last unit of food."""
    food_free = max(0, sum(int(pack.get(k, 0)) for k in edible) - KEEP_FOOD)
    order = [item, "coin"] + sorted((k for k, n in pack.items() if n > 0 and k not in (item, "coin")), key=lambda k: -value(k))
    taken, remaining, seen = [], float(owed), set()
    for kind in order:
        if kind in seen or remaining <= 1e-9:
            continue
        seen.add(kind)
        have = int(pack.get(kind, 0))
        if kind in edible:
            have = min(have, food_free)
        if have <= 0:
            continue
        qty = min(have, max(1, math.ceil(remaining / max(value(kind), 1e-9) - 1e-9)))
        taken.append((kind, qty))
        remaining -= qty * value(kind)
        if kind in edible:
            food_free -= qty
    return taken
