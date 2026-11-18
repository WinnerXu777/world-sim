"""Combat system helpers and shared resolver types."""

from .hunting import HUNTABLE_ANIMAL_TYPES, huntable_animal_slots, nearest_huntable_animal, nearest_predator_target
from .intents import CombatIntent
from .manual import collect_manual_attack_intents
from .resolver import resolve_human_attack_intents, target_in_range
from .sim import collect_sim_attack_intents, collect_sim_hunt_intents

__all__ = [
    "CombatIntent",
    "HUNTABLE_ANIMAL_TYPES",
    "collect_manual_attack_intents",
    "collect_sim_attack_intents",
    "collect_sim_hunt_intents",
    "huntable_animal_slots",
    "nearest_huntable_animal",
    "nearest_predator_target",
    "resolve_human_attack_intents",
    "target_in_range",
]
