from __future__ import annotations

"""Station definitions for future station-gated crafting."""

from typing import Final


CRAFTING_STATION_DEFS: Final[dict[str, dict[str, object]]] = {
    "none": {
        "label": "No Station",
        "tags": (),
        "notes": "Recipe can be crafted by hand with no special station.",
    },
    "workbench": {
        "label": "Workbench",
        "tags": ("crafting_station", "woodwork"),
        "notes": "Simple bench for shaping hand tools and components.",
    },
    "firepit": {
        "label": "Firepit",
        "tags": ("crafting_station", "heat"),
        "notes": "Heat source for crude processing and cooking-adjacent work.",
    },
    "loom": {
        "label": "Loom",
        "tags": ("crafting_station", "fiberwork"),
        "notes": "Used for richer fiber and textile recipes later.",
    },
    "forge": {
        "label": "Forge",
        "tags": ("crafting_station", "metalwork"),
        "notes": "Reserved for later metalworking recipes.",
    },
}


def crafting_station_def(station_kind: str) -> dict[str, object]:
    key = str(station_kind or "none").strip() or "none"
    return dict(CRAFTING_STATION_DEFS.get(key, CRAFTING_STATION_DEFS["none"]))
