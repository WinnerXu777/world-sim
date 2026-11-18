"""Health-domain helpers for humans, animals, and structural durability."""

from .damage import apply_entity_damage, apply_entity_heal, apply_human_damage, apply_human_heal
from .durability import damage_structure_state, reinforce_structure_durability, repair_structure_state
from .effects import apply_area_attack_effect, apply_bless_effect, apply_plague_effect, kill_humans
from .infection import apply_infection_tick
from .recovery import apply_heal_tick
from .status import update_human_critical_state

__all__ = [
    "apply_entity_damage",
    "apply_entity_heal",
    "apply_area_attack_effect",
    "apply_bless_effect",
    "apply_human_damage",
    "apply_human_heal",
    "apply_heal_tick",
    "apply_infection_tick",
    "apply_plague_effect",
    "kill_humans",
    "damage_structure_state",
    "reinforce_structure_durability",
    "repair_structure_state",
    "update_human_critical_state",
]
