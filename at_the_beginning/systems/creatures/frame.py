"""The creature keys of a frame animal (``1008_client_contract.md``, additive, ``EDEN_CREATURES=1`` only): what the client needs to draw a creature that is not one of the legacy five.

``keys(row)`` is pure (a tensor row in, a dict out) and is called by ``map_test._export_animal`` only with the flag on, so a flag-off frame is byte-identical. The dict is nested under
``"creature"`` because ``"state"`` is already the schema attribute dict of the animal.
"""
from __future__ import annotations

from typing import Optional

import genesis_config as cfg

from . import table as T

STATE_NAMES = {value: name for name, value in T.STATES.items()}


def keys(row) -> Optional[dict]:
    """``{species, sprite, footprint, state, variant}`` for a creature row, None for any other row. ``sprite`` is the static asset path or None (no art yet: the client draws the
    footprint placeholder). ``state`` is the kernel's last state name (idle, wander, flee, chase, rest, return, attack), None for the species that still run the legacy loops
    (sheep, deer, tiger, wolf, fish). ``variant`` is the variant's name, None for the base form."""
    spec = T.by_type(row[cfg.M_TYPE])
    if spec is None:
        return None
    name = T.name_of(row[cfg.M_TYPE])
    variant = int(row[T.C_VARIANT])
    names = spec["variants"]
    return {"species": name, "sprite": T._sprite_for(name), "footprint": list(spec["footprint"]),
            "state": STATE_NAMES.get(int(row[T.C_STATE]), "idle") if spec["brain"] == "table" else None,
            "variant": names[variant - 1] if 1 <= variant <= len(names) else None}
