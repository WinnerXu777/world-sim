"""Clothing as an item class: what a resident carries keeps it warmer (``EDEN_TEMPERATURE``; the felt-temperature hook is 9d882a's ``harness/temperature.py``).

``INSULATION`` maps an item kind to the degrees it adds to the felt temperature; ``insulation_of(items)`` is the best single garment in a pack (garments do not stack: nobody wears two coats), 0.0 for
a pack with none. The harness reads it per resident (a pack lookup) where it now adds the constant ``CLOTHING_BONUS``; until it does, the class is data plus this helper and the trade /
craft / loot paths that can produce the items (``hide`` is the raw material of a ``fur_coat``).
"""
from __future__ import annotations

INSULATION = {"cloak": 4.0, "fur_coat": 9.0}


def insulation_of(items: dict) -> float:
    """``items`` is ``{kind: quantity}`` (a pack); the best garment held, else 0.0."""
    return max((INSULATION[k] for k, q in (items or {}).items() if k in INSULATION and q > 0), default=0.0)
