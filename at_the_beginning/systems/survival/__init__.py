"""Survival system helpers."""

from .hunger import apply_heal_tick, apply_hunger_tick, eat_from_current_entity
from .navigation import build_survival_navigation_bias
from .shelter import sync_structure_occupancy, update_shelter_flags
from .thirst import apply_thirst_tick, drink_from_nearby_entity

__all__ = [
    "apply_heal_tick",
    "apply_hunger_tick",
    "apply_thirst_tick",
    "build_survival_navigation_bias",
    "drink_from_nearby_entity",
    "eat_from_current_entity",
    "sync_structure_occupancy",
    "update_shelter_flags",
]
