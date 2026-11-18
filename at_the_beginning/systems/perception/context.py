from __future__ import annotations

from dataclasses import dataclass, field

import torch

try:
    from genesis_config import M_RESOURCE_FOOD, M_RESOURCE_WATER, X, Y
    from systems.perception.queries import (
        best_resource_entity,
        best_safe_entity,
        current_entity_id,
        nearby_entity_ids,
        nearest_entity_from_ids,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import M_RESOURCE_FOOD, M_RESOURCE_WATER, X, Y
    from at_the_beginning.systems.perception.queries import (
        best_resource_entity,
        best_safe_entity,
        current_entity_id,
        nearby_entity_ids,
        nearest_entity_from_ids,
    )


@dataclass(slots=True)
class LocalPerceptionContext:
    current_entity_id: int = -1
    nearby_entity_ids: tuple[int, ...] = field(default_factory=tuple)
    nearest_food_entity: int = -1
    nearest_water_entity: int = -1
    nearest_safe_entity: int = -1
    nearest_hazard_entity: int = -1
    nearest_hazard_distance: float = float("inf")
    nearest_predator_entity: int = -1
    nearest_predator_distance: float = float("inf")


def build_local_perception_context(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    *,
    nearby_radius: float = 0.0,
    nearby_type_filter: set[int] | None = None,
    food_types: set[int] | None = None,
    food_radius: float = 0.0,
    water_types: set[int] | None = None,
    water_radius: float = 0.0,
    safe_radius: float = 0.0,
    hazard_entity_ids: list[int] | torch.Tensor | None = None,
    predator_entity_ids: list[int] | torch.Tensor | None = None,
) -> LocalPerceptionContext:
    """Bundle reusable local perception outputs around a world position."""
    context = LocalPerceptionContext(current_entity_id=current_entity_id(px, py))

    if nearby_radius > 0.0:
        context.nearby_entity_ids = tuple(nearby_entity_ids(m_tensor, px, py, nearby_radius, nearby_type_filter))
    if food_types and food_radius > 0.0:
        context.nearest_food_entity = best_resource_entity(
            m_tensor,
            px,
            py,
            food_types,
            M_RESOURCE_FOOD,
            food_radius,
        )
    if water_types and water_radius > 0.0:
        context.nearest_water_entity = best_resource_entity(
            m_tensor,
            px,
            py,
            water_types,
            M_RESOURCE_WATER,
            water_radius,
        )
    if safe_radius > 0.0:
        context.nearest_safe_entity = best_safe_entity(m_tensor, px, py, safe_radius)
    if hazard_entity_ids is not None:
        context.nearest_hazard_entity, context.nearest_hazard_distance = nearest_entity_from_ids(
            m_tensor,
            px,
            py,
            hazard_entity_ids,
        )
    if predator_entity_ids is not None:
        context.nearest_predator_entity, context.nearest_predator_distance = nearest_entity_from_ids(
            m_tensor,
            px,
            py,
            predator_entity_ids,
        )
    return context


def build_human_perception_context(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    human_slot: int,
    **kwargs,
) -> LocalPerceptionContext:
    """Convenience wrapper for building perception around a human row."""
    return build_local_perception_context(
        m_tensor,
        float(h_tensor[human_slot, X]),
        float(h_tensor[human_slot, Y]),
        **kwargs,
    )


__all__ = [
    "LocalPerceptionContext",
    "build_human_perception_context",
    "build_local_perception_context",
]
