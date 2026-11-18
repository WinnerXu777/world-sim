"""Nature-domain helpers for ecology, weather, and environmental hazards."""

from .ecology import (
    animal_population_summary,
    apply_resource_regrow,
    apply_water_cycle,
    build_animal_mask,
    maybe_rebalance_ecology,
)
from .disasters import apply_earthquake, apply_flood, apply_storm, apply_volcanic_eruption, ignite_wildfire
from .hazards import apply_fire_tick, apply_lava_tick
from .weather import advance_nature_cycle, build_nature_modifiers, ensure_nature_state, season_for_tick, snapshot_nature_state

__all__ = [
    "advance_nature_cycle",
    "animal_population_summary",
    "apply_earthquake",
    "apply_fire_tick",
    "apply_flood",
    "apply_lava_tick",
    "apply_resource_regrow",
    "apply_storm",
    "apply_volcanic_eruption",
    "apply_water_cycle",
    "build_animal_mask",
    "build_nature_modifiers",
    "ensure_nature_state",
    "ignite_wildfire",
    "maybe_rebalance_ecology",
    "season_for_tick",
    "snapshot_nature_state",
]
