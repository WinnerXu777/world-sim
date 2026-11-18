"""Social system helpers."""

from .grouping import apply_emotional_recovery, build_pairwise_relations, build_social_navigation_bias
from .mating import apply_cooldown_decay, build_seek_mask, resolve_human_reproduction, restrict_reproduction_seek

try:
    from systems.health.infection import apply_infection_tick
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.health.infection import apply_infection_tick

__all__ = [
    "apply_cooldown_decay",
    "apply_emotional_recovery",
    "apply_infection_tick",
    "build_pairwise_relations",
    "build_seek_mask",
    "build_social_navigation_bias",
    "resolve_human_reproduction",
    "restrict_reproduction_seek",
]
