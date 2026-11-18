from __future__ import annotations

"""Structured goal ontology for resident long-term wants."""

from typing import Final


GOAL_DEFS: Final[dict[str, dict[str, object]]] = {
    "retaliate": {"horizon": "medium", "stickiness": 0.82, "label": "Retaliate"},
    "avoid_target": {"horizon": "medium", "stickiness": 0.76, "label": "Avoid target"},
    "protect_kin": {"horizon": "long", "stickiness": 0.84, "label": "Protect kin"},
    "accumulate_wealth": {"horizon": "long", "stickiness": 0.8, "label": "Accumulate wealth"},
    "steal_when_safe": {"horizon": "medium", "stickiness": 0.64, "label": "Steal when safe"},
    "gain_status": {"horizon": "long", "stickiness": 0.72, "label": "Gain status"},
    "guard_home": {"horizon": "medium", "stickiness": 0.7, "label": "Guard home"},
    "seek_mate": {"horizon": "long", "stickiness": 0.62, "label": "Seek mate"},
    "recruit_allies": {"horizon": "medium", "stickiness": 0.66, "label": "Recruit allies"},
    "explore_region": {"horizon": "medium", "stickiness": 0.58, "label": "Explore region"},
    "hoard_food": {"horizon": "medium", "stickiness": 0.68, "label": "Hoard food"},
    "settle_near_resource": {"horizon": "long", "stickiness": 0.7, "label": "Settle near resource"},
    "expand_territory": {"horizon": "long", "stickiness": 0.74, "label": "Expand territory"},
}
