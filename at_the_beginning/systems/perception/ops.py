from __future__ import annotations

"""
Stable, generation-friendly perception ops.

Generated code should prefer asking the world questions through this module
instead of re-implementing nearby/nearest/best-candidate logic inline.
"""

import torch

try:
    from systems.perception.context import build_human_perception_context, build_local_perception_context
    from systems.perception.queries import (
        agent_radial_mask,
        best_resource_entity,
        best_safe_entity,
        current_entity_id,
        entity_radial_ids,
        entity_unit_vector,
        nearby_entity_ids,
        nearest_entity_from_ids,
        nearest_geo_entity,
        nearest_human_from_mask,
        point_distance,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.perception.context import (
        build_human_perception_context,
        build_local_perception_context,
    )
    from at_the_beginning.systems.perception.queries import (
        agent_radial_mask,
        best_resource_entity,
        best_safe_entity,
        current_entity_id,
        entity_radial_ids,
        entity_unit_vector,
        nearby_entity_ids,
        nearest_entity_from_ids,
        nearest_geo_entity,
        nearest_human_from_mask,
        point_distance,
    )


def build_local_context(
    m_tensor: torch.Tensor,
    *,
    px: float,
    py: float,
    nearby_radius: float = 0.0,
    nearby_type_filter: set[int] | None = None,
    food_types: set[int] | None = None,
    food_radius: float = 0.0,
    water_types: set[int] | None = None,
    water_radius: float = 0.0,
    safe_radius: float = 0.0,
    hazard_entity_ids: list[int] | torch.Tensor | None = None,
    predator_entity_ids: list[int] | torch.Tensor | None = None,
):
    return build_local_perception_context(
        m_tensor,
        px,
        py,
        nearby_radius=nearby_radius,
        nearby_type_filter=nearby_type_filter,
        food_types=food_types,
        food_radius=food_radius,
        water_types=water_types,
        water_radius=water_radius,
        safe_radius=safe_radius,
        hazard_entity_ids=hazard_entity_ids,
        predator_entity_ids=predator_entity_ids,
    )


def build_human_context(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    human_slot: int,
    **kwargs,
):
    return build_human_perception_context(h_tensor, m_tensor, human_slot, **kwargs)


def find_covering_entity(*, px: float, py: float) -> int:
    return current_entity_id(px, py)


def find_nearby_entities(
    m_tensor: torch.Tensor,
    *,
    px: float,
    py: float,
    radius: float,
    type_filter: set[int] | None = None,
) -> list[int]:
    return nearby_entity_ids(m_tensor, px, py, radius, type_filter)


def find_entities_in_radius(
    m_tensor: torch.Tensor,
    *,
    cx: float,
    cy: float,
    radius: float,
) -> torch.Tensor:
    return entity_radial_ids(m_tensor, cx, cy, radius)


def humans_within_radius(
    h_tensor: torch.Tensor,
    h_mask: torch.Tensor,
    *,
    cx: float,
    cy: float,
    radius: float,
    device: str,
) -> torch.Tensor:
    return agent_radial_mask(h_tensor, h_mask, cx, cy, radius, device)


def find_nearest_geometry(
    m_tensor: torch.Tensor,
    *,
    px: float,
    py: float,
    type_filter: set[int] | None = None,
    radius: float = 0.0,
) -> int:
    return nearest_geo_entity(m_tensor, px, py, type_filter, radius)


def find_nearest_entity(
    m_tensor: torch.Tensor,
    *,
    px: float,
    py: float,
    entity_ids: list[int] | torch.Tensor,
) -> tuple[int, float]:
    return nearest_entity_from_ids(m_tensor, px, py, entity_ids)


def find_nearest_human(
    h_tensor: torch.Tensor,
    *,
    px: float,
    py: float,
    human_mask: torch.Tensor,
    max_distance: float | None = None,
) -> tuple[int, float]:
    return nearest_human_from_mask(
        h_tensor,
        px,
        py,
        human_mask,
        max_distance=max_distance,
    )


def find_best_resource_source(
    m_tensor: torch.Tensor,
    *,
    px: float,
    py: float,
    type_filter: set[int],
    resource_col: int,
    radius: float,
    min_value: float = 0.0,
) -> int:
    return best_resource_entity(
        m_tensor,
        px,
        py,
        type_filter,
        resource_col,
        radius,
        min_value=min_value,
    )


def find_best_safe_destination(
    m_tensor: torch.Tensor,
    *,
    px: float,
    py: float,
    radius: float,
    allowed_types: set[int] | None = None,
) -> int:
    return best_safe_entity(
        m_tensor,
        px,
        py,
        radius,
        allowed_types=allowed_types,
    )


def direction_to_entity(
    m_tensor: torch.Tensor,
    *,
    source_x: float,
    source_y: float,
    target_entity_id: int,
    away: bool = False,
) -> tuple[float, float]:
    return entity_unit_vector(
        m_tensor,
        source_x,
        source_y,
        target_entity_id,
        away=away,
    )


def distance_between_points(x0: float, y0: float, x1: float, y1: float) -> float:
    return point_distance(x0, y0, x1, y1)


__all__ = [
    "build_human_context",
    "build_local_context",
    "direction_to_entity",
    "distance_between_points",
    "find_best_resource_source",
    "find_best_safe_destination",
    "find_covering_entity",
    "find_entities_in_radius",
    "find_nearby_entities",
    "find_nearest_entity",
    "find_nearest_geometry",
    "find_nearest_human",
    "humans_within_radius",
]
