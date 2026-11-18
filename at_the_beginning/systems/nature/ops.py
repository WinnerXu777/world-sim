from __future__ import annotations

"""
Stable, generation-friendly nature ops.

Generated tools should prefer importing from here rather than stitching
directly across multiple nature submodules.
"""

import torch

try:
    from systems.nature.disasters import (
        apply_earthquake,
        apply_flood,
        apply_storm,
        apply_volcanic_eruption,
        ignite_wildfire,
    )
    from systems.nature.ecology import (
        apply_resource_regrow,
        apply_water_cycle,
        maybe_rebalance_ecology,
    )
    from systems.nature.hazards import apply_fire_tick, apply_lava_tick
    from systems.nature.weather import advance_nature_cycle
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.nature.disasters import (
        apply_earthquake,
        apply_flood,
        apply_storm,
        apply_volcanic_eruption,
        ignite_wildfire,
    )
    from at_the_beginning.systems.nature.ecology import (
        apply_resource_regrow,
        apply_water_cycle,
        maybe_rebalance_ecology,
    )
    from at_the_beginning.systems.nature.hazards import apply_fire_tick, apply_lava_tick
    from at_the_beginning.systems.nature.weather import advance_nature_cycle


def trigger_wildfire(
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    entity_radial_ids_fn,
) -> dict:
    return ignite_wildfire(
        m_tensor,
        center_x,
        center_y,
        radius,
        entity_radial_ids_fn=entity_radial_ids_fn,
    )


def trigger_earthquake(
    ctx: dict,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    device: str,
    entity_radial_ids_fn,
    agent_radial_mask_fn,
    flee_fn=None,
) -> dict:
    return apply_earthquake(
        ctx,
        h_tensor,
        m_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
        entity_radial_ids_fn=entity_radial_ids_fn,
        agent_radial_mask_fn=agent_radial_mask_fn,
        flee_fn=flee_fn,
    )


def trigger_storm(
    ctx: dict,
    h_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    device: str,
    agent_radial_mask_fn,
) -> dict:
    return apply_storm(
        ctx,
        h_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
        agent_radial_mask_fn=agent_radial_mask_fn,
    )


def trigger_flood(
    ctx: dict,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    device: str,
    expand_radius: float = 100.0,
) -> dict:
    return apply_flood(
        ctx,
        h_tensor,
        m_tensor,
        device=device,
        expand_radius=expand_radius,
    )


def trigger_volcanic_eruption(
    ctx: dict,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    pop_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    device: str,
    entity_radial_ids_fn,
    agent_radial_mask_fn,
    flee_fn=None,
) -> dict:
    return apply_volcanic_eruption(
        ctx,
        h_tensor,
        m_tensor,
        pop_count_ref,
        center_x=center_x,
        center_y=center_y,
        device=device,
        entity_radial_ids_fn=entity_radial_ids_fn,
        agent_radial_mask_fn=agent_radial_mask_fn,
        flee_fn=flee_fn,
    )


def advance_fire(ctx: dict, m_tensor: torch.Tensor, h_tensor: torch.Tensor, *, device: str) -> dict:
    return apply_fire_tick(ctx, m_tensor, h_tensor, device=device)


def advance_lava(ctx: dict, m_tensor: torch.Tensor, h_tensor: torch.Tensor, *, device: str) -> dict:
    return apply_lava_tick(ctx, m_tensor, h_tensor, device=device)


def advance_regrowth(m_tensor: torch.Tensor, *, food_multiplier: float = 1.0) -> None:
    apply_resource_regrow(m_tensor, food_multiplier=food_multiplier)


def advance_water(m_tensor: torch.Tensor, *, water_multiplier: float = 1.0, farm_food_multiplier: float = 1.0) -> None:
    apply_water_cycle(
        m_tensor,
        water_multiplier=water_multiplier,
        farm_food_multiplier=farm_food_multiplier,
    )


def run_weather_cycle(
    ctx: dict,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    engine,
    device: str,
    flood_tool_fn=None,
    storm_tool_fn=None,
    wildfire_tool_fn=None,
    drought_tool_fn=None,
) -> dict:
    return advance_nature_cycle(
        ctx,
        h_tensor,
        m_tensor,
        engine=engine,
        device=device,
        flood_tool_fn=flood_tool_fn,
        storm_tool_fn=storm_tool_fn,
        wildfire_tool_fn=wildfire_tool_fn,
        drought_tool_fn=drought_tool_fn,
    )


def rebalance_ecology(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    tick: int,
    nature_state: dict,
    device: str,
    spawn_animal_group_fn=None,
) -> dict:
    return maybe_rebalance_ecology(
        m_tensor,
        entity_count_ref,
        tick=tick,
        nature_state=nature_state,
        device=device,
        spawn_animal_group_fn=spawn_animal_group_fn,
    )


__all__ = [
    "advance_fire",
    "advance_lava",
    "advance_regrowth",
    "advance_water",
    "rebalance_ecology",
    "run_weather_cycle",
    "trigger_earthquake",
    "trigger_flood",
    "trigger_storm",
    "trigger_volcanic_eruption",
    "trigger_wildfire",
]
