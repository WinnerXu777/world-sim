from __future__ import annotations

from typing import Any

import torch

try:
    from genesis_config import (
        CX,
        CY,
        FARM_FOOD_GROWTH_RATE,
        HABITABLE,
        INITIAL_FOOD_GRASS,
        INITIAL_WATER_FARM,
        INITIAL_WATER_WELL,
        M_BARREN,
        M_BEACH,
        M_FARM,
        M_FERTILITY,
        M_FOREST,
        M_GRASS,
        M_GROWTH_RATE,
        M_HOUSE,
        M_LAKE,
        M_LAVA,
        M_MOUNTAIN,
        M_RESOURCE_FOOD,
        M_RESOURCE_WATER,
        M_SEA,
        M_TYPE,
        M_VILLAGE,
        M_WALL,
        M_WELL,
        STRUCTURE_TYPES,
        WELL_WATER_REPLENISH_RATE,
    )
    from systems.perception import current_entity_id, nearby_entity_ids, nearest_geo_entity, pick_best_entity, point_distance
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        CX,
        CY,
        FARM_FOOD_GROWTH_RATE,
        HABITABLE,
        INITIAL_FOOD_GRASS,
        INITIAL_WATER_FARM,
        INITIAL_WATER_WELL,
        M_BARREN,
        M_BEACH,
        M_FARM,
        M_FERTILITY,
        M_FOREST,
        M_GRASS,
        M_GROWTH_RATE,
        M_HOUSE,
        M_LAKE,
        M_LAVA,
        M_MOUNTAIN,
        M_RESOURCE_FOOD,
        M_RESOURCE_WATER,
        M_SEA,
        M_TYPE,
        M_VILLAGE,
        M_WALL,
        M_WELL,
        STRUCTURE_TYPES,
        WELL_WATER_REPLENISH_RATE,
    )
    from at_the_beginning.systems.perception import (
        current_entity_id,
        nearby_entity_ids,
        nearest_geo_entity,
        pick_best_entity,
        point_distance,
    )


BUILD_BLOCKED_TYPES = {M_SEA, M_LAKE, M_MOUNTAIN, M_LAVA}
FARMABLE_BASE_TYPES = {M_GRASS, M_FOREST, M_BARREN, M_BEACH}


def structure_blueprint(structure_type: int, base_fertility: float = 60.0) -> dict[str, Any]:
    """Typed defaults for spawned or designated construction targets."""
    if structure_type == M_HOUSE:
        return {"scale": 22.0, "durability": 140.0, "shelter_cap": 4.0, "extra_cols": {}}
    if structure_type == M_VILLAGE:
        return {"scale": 42.0, "durability": 260.0, "shelter_cap": 18.0, "extra_cols": {}}
    if structure_type == M_FARM:
        return {
            "scale": 28.0,
            "durability": 110.0,
            "shelter_cap": 0.0,
            "extra_cols": {
                M_RESOURCE_FOOD: INITIAL_FOOD_GRASS,
                M_RESOURCE_WATER: INITIAL_WATER_FARM,
                M_GROWTH_RATE: FARM_FOOD_GROWTH_RATE * max(0.35, base_fertility / 100.0),
            },
        }
    if structure_type == M_WELL:
        return {
            "scale": 16.0,
            "durability": 120.0,
            "shelter_cap": 0.0,
            "extra_cols": {
                M_RESOURCE_WATER: INITIAL_WATER_WELL,
                M_GROWTH_RATE: WELL_WATER_REPLENISH_RATE,
            },
        }
    if structure_type == M_WALL:
        return {"scale": 20.0, "durability": 180.0, "shelter_cap": 0.0, "extra_cols": {}}
    return {"scale": 20.0, "durability": 100.0, "shelter_cap": 0.0, "extra_cols": {}}


def resolve_build_site(
    m_tensor: torch.Tensor,
    center_x: float,
    center_y: float,
    radius: float,
    allowed_base_types: set[int] | None = None,
) -> tuple[float, float, int] | None:
    """Nearest viable land anchor for local structure placement."""
    allowed = allowed_base_types if allowed_base_types is not None else (set(HABITABLE) | {M_BARREN})
    base_entity_id = nearest_geo_entity(m_tensor, center_x, center_y, allowed, max(radius * 2.0, 48.0))
    if base_entity_id == -1:
        return None

    site_x = float(center_x)
    site_y = float(center_y)
    if current_entity_id(center_x, center_y) == -1:
        site_x = float(m_tensor[base_entity_id, CX])
        site_y = float(m_tensor[base_entity_id, CY])

    if int(m_tensor[base_entity_id, M_TYPE]) in BUILD_BLOCKED_TYPES:
        return None
    if nearby_entity_ids(m_tensor, site_x, site_y, radius * 1.25, STRUCTURE_TYPES):
        return None
    return site_x, site_y, base_entity_id


def find_buildable_site(
    m_tensor: torch.Tensor,
    center_x: float,
    center_y: float,
    structure_type: int | None = None,
    search_radius: float = 320.0,
    allowed_base_types: set[int] | None = None,
) -> tuple[float, float, int] | None:
    """Search a local area for the best viable build site."""
    if structure_type == M_FARM:
        allowed = FARMABLE_BASE_TYPES if allowed_base_types is None else allowed_base_types
    else:
        allowed = (set(HABITABLE) | {M_BARREN}) if allowed_base_types is None else allowed_base_types

    scale = float(structure_blueprint(structure_type or M_HOUSE)["scale"])
    local = resolve_build_site(m_tensor, center_x, center_y, scale, allowed_base_types=allowed)
    if local is not None:
        site_x, site_y, _ = local
        if point_distance(center_x, center_y, site_x, site_y) <= search_radius:
            return local

    candidate_ids = nearby_entity_ids(m_tensor, center_x, center_y, search_radius, allowed)
    candidate_ids = [
        entity_id
        for entity_id in candidate_ids
        if int(m_tensor[entity_id, M_TYPE]) not in BUILD_BLOCKED_TYPES
        and int(m_tensor[entity_id, M_TYPE]) not in STRUCTURE_TYPES
    ]
    if not candidate_ids:
        return None

    viable_ids: list[int] = []
    for base_entity_id in candidate_ids:
        site_x = float(m_tensor[base_entity_id, CX])
        site_y = float(m_tensor[base_entity_id, CY])
        if nearby_entity_ids(m_tensor, site_x, site_y, scale * 1.25, STRUCTURE_TYPES):
            continue
        viable_ids.append(base_entity_id)
    if not viable_ids:
        return None

    best_entity_id = pick_best_entity(
        viable_ids,
        lambda base_entity_id: point_distance(
            center_x,
            center_y,
            float(m_tensor[base_entity_id, CX]),
            float(m_tensor[base_entity_id, CY]),
        ) - (float(m_tensor[base_entity_id, M_FERTILITY]) * 0.5 if structure_type == M_FARM else 0.0),
    )
    if best_entity_id == -1:
        return None
    return float(m_tensor[best_entity_id, CX]), float(m_tensor[best_entity_id, CY]), best_entity_id


__all__ = [
    "BUILD_BLOCKED_TYPES",
    "FARMABLE_BASE_TYPES",
    "find_buildable_site",
    "resolve_build_site",
    "structure_blueprint",
]
