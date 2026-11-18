from __future__ import annotations

import torch

try:
    import map_geo
    from genesis_config import (
        FOOD_SEEK_THRESHOLD,
        HAZARD_AVOID_RADIUS,
        HAZARD_FLEE_WEIGHT,
        HUNGER,
        HP,
        H_STAMINA,
        M_BEACH,
        M_BURNING,
        M_FARM,
        M_RESOURCE_NODE,
        M_FLOODED,
        M_FOREST,
        M_GRASS,
        M_LAKE,
        M_LAVA,
        M_RESOURCE_FOOD,
        M_RESOURCE_WATER,
        M_SEA,
        M_TIGER,
        M_TYPE,
        M_WELL,
        M_WOLF,
        MIGRATION_SCAN_RADIUS,
        MOOD,
        PREDATOR_ALERT_RADIUS,
        SHELTER_SEEK_THREAT,
        SURVIVAL_NAV_WEIGHT,
        SURVIVAL_SCAN_RADIUS,
        THIRST,
        THREAT,
        WATER_SEEK_THRESHOLD,
        X,
        Y,
    )
    from systems.perception import build_local_perception_context, entity_unit_vector
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import map_geo
    from at_the_beginning.genesis_config import (
        FOOD_SEEK_THRESHOLD,
        HAZARD_AVOID_RADIUS,
        HAZARD_FLEE_WEIGHT,
        HUNGER,
        HP,
        H_STAMINA,
        M_BEACH,
        M_BURNING,
        M_FARM,
        M_RESOURCE_NODE,
        M_FLOODED,
        M_FOREST,
        M_GRASS,
        M_LAKE,
        M_LAVA,
        M_RESOURCE_FOOD,
        M_RESOURCE_WATER,
        M_SEA,
        M_TIGER,
        M_TYPE,
        M_WELL,
        M_WOLF,
        MIGRATION_SCAN_RADIUS,
        MOOD,
        PREDATOR_ALERT_RADIUS,
        SHELTER_SEEK_THREAT,
        SURVIVAL_NAV_WEIGHT,
        SURVIVAL_SCAN_RADIUS,
        THIRST,
        THREAT,
        WATER_SEEK_THRESHOLD,
        X,
        Y,
    )
    from at_the_beginning.systems.perception import build_local_perception_context, entity_unit_vector


DRINKABLE_TYPES = {M_LAKE, M_WELL}
FOOD_SOURCE_TYPES = {M_GRASS, M_FOREST, M_BEACH, M_LAKE, M_FARM, M_RESOURCE_NODE}


def build_survival_navigation_bias(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    device: str,
) -> dict[str, torch.Tensor]:
    """Build the shared survival navigation bias toward food/water/shelter and away from danger."""
    bias = torch.zeros((h_tensor.shape[0], 2), dtype=h_tensor.dtype, device=device)
    if not h_mask.any():
        return {"nav_survival_bias": bias}

    hazard_types = {M_LAVA, M_SEA}
    hazard_ids = [
        int(entity_id)
        for entity_id in map_geo.MAP_GEO.keys()
        if int(m_tensor[entity_id, M_TYPE]) in hazard_types
        or int(m_tensor[entity_id, M_BURNING]) > 0
        or int(m_tensor[entity_id, M_FLOODED]) > 0
    ]
    predator_ids = [
        int(entity_id)
        for entity_id in torch.where((m_tensor[:, M_TYPE] == M_TIGER) | (m_tensor[:, M_TYPE] == M_WOLF))[0].tolist()
    ]

    for human_id in torch.where(h_mask)[0].tolist():
        px = float(h_tensor[human_id, X])
        py = float(h_tensor[human_id, Y])
        steer_x = 0.0
        steer_y = 0.0
        perception = build_local_perception_context(
            m_tensor,
            px,
            py,
            food_types=FOOD_SOURCE_TYPES,
            food_radius=SURVIVAL_SCAN_RADIUS,
            water_types=DRINKABLE_TYPES,
            water_radius=SURVIVAL_SCAN_RADIUS,
            safe_radius=MIGRATION_SCAN_RADIUS,
            hazard_entity_ids=hazard_ids,
            predator_entity_ids=predator_ids,
        )

        if float(h_tensor[human_id, HUNGER]) >= FOOD_SEEK_THRESHOLD:
            ux, uy = entity_unit_vector(m_tensor, px, py, perception.nearest_food_entity)
            hunger_factor = min(1.5, float(h_tensor[human_id, HUNGER]) / 100.0 + 0.3)
            steer_x += ux * SURVIVAL_NAV_WEIGHT * hunger_factor
            steer_y += uy * SURVIVAL_NAV_WEIGHT * hunger_factor

        if float(h_tensor[human_id, THIRST]) >= WATER_SEEK_THRESHOLD:
            ux, uy = entity_unit_vector(m_tensor, px, py, perception.nearest_water_entity)
            thirst_factor = min(1.6, float(h_tensor[human_id, THIRST]) / 100.0 + 0.4)
            steer_x += ux * SURVIVAL_NAV_WEIGHT * thirst_factor
            steer_y += uy * SURVIVAL_NAV_WEIGHT * thirst_factor

        if (
            float(h_tensor[human_id, THREAT]) >= SHELTER_SEEK_THREAT
            or float(h_tensor[human_id, HP]) < 45.0
            or float(h_tensor[human_id, H_STAMINA]) < 20.0
        ):
            ux, uy = entity_unit_vector(m_tensor, px, py, perception.nearest_safe_entity)
            steer_x += ux * (SURVIVAL_NAV_WEIGHT + 1.5)
            steer_y += uy * (SURVIVAL_NAV_WEIGHT + 1.5)

        if perception.nearest_hazard_entity != -1 and perception.nearest_hazard_distance < HAZARD_AVOID_RADIUS:
            ux, uy = entity_unit_vector(m_tensor, px, py, perception.nearest_hazard_entity, away=True)
            panic = 1.0 + max(
                0.0,
                (HAZARD_AVOID_RADIUS - perception.nearest_hazard_distance) / HAZARD_AVOID_RADIUS,
            )
            steer_x += ux * HAZARD_FLEE_WEIGHT * panic
            steer_y += uy * HAZARD_FLEE_WEIGHT * panic
            h_tensor[human_id, THREAT] = min(100.0, float(h_tensor[human_id, THREAT]) + 1.2)
            h_tensor[human_id, MOOD] = max(0.0, float(h_tensor[human_id, MOOD]) - 0.4)

        if perception.nearest_predator_entity != -1 and perception.nearest_predator_distance < PREDATOR_ALERT_RADIUS:
            ux, uy = entity_unit_vector(m_tensor, px, py, perception.nearest_predator_entity, away=True)
            panic = 1.0 + max(
                0.0,
                (PREDATOR_ALERT_RADIUS - perception.nearest_predator_distance) / PREDATOR_ALERT_RADIUS,
            )
            steer_x += ux * (HAZARD_FLEE_WEIGHT + 2.0) * panic
            steer_y += uy * (HAZARD_FLEE_WEIGHT + 2.0) * panic
            h_tensor[human_id, THREAT] = min(100.0, float(h_tensor[human_id, THREAT]) + 2.0)

        if steer_x != 0.0 or steer_y != 0.0:
            bias[human_id, 0] = steer_x
            bias[human_id, 1] = steer_y

    return {"nav_survival_bias": bias}
