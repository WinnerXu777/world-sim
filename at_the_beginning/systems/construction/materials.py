from __future__ import annotations

from typing import Any

import torch

try:
    from genesis_config import (
        BUILD_RADIUS,
        BUILD_SKILL_GAIN,
        CX,
        CY,
        GATHER_MATERIAL_AMOUNT,
        GATHER_STAMINA_COST,
        H_CARRYING,
        H_SKILL,
        H_STAMINA,
        M_BARREN,
        M_BEACH,
        M_FERTILITY,
        M_FOREST,
        M_GRASS,
        M_HP,
        M_MOUNTAIN,
        M_RESOURCE_FOOD,
        M_TYPE,
        MAX_CARRYING_MATERIAL,
        X,
        Y,
    )
    from systems.perception import agent_radial_mask, nearby_entity_ids, pick_best_entity, point_distance
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        BUILD_RADIUS,
        BUILD_SKILL_GAIN,
        CX,
        CY,
        GATHER_MATERIAL_AMOUNT,
        GATHER_STAMINA_COST,
        H_CARRYING,
        H_SKILL,
        H_STAMINA,
        M_BARREN,
        M_BEACH,
        M_FERTILITY,
        M_FOREST,
        M_GRASS,
        M_HP,
        M_MOUNTAIN,
        M_RESOURCE_FOOD,
        M_TYPE,
        MAX_CARRYING_MATERIAL,
        X,
        Y,
    )
    from at_the_beginning.systems.perception import (
        agent_radial_mask,
        nearby_entity_ids,
        pick_best_entity,
        point_distance,
    )


DEFAULT_MATERIAL_SOURCE_TYPES = {M_FOREST, M_GRASS, M_BEACH, M_BARREN, M_MOUNTAIN}


def gather_materials(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    center_x: float,
    center_y: float,
    radius: float = BUILD_RADIUS,
    amount: float = GATHER_MATERIAL_AMOUNT,
    builder_mask: torch.Tensor | None = None,
    source_types: set[int] | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    """Collect abstract construction materials from nearby natural features."""
    h_mask = ctx["h_mask"]
    active = h_mask if builder_mask is None else (builder_mask & h_mask)
    if not active.any():
        return {}

    allowed_types = DEFAULT_MATERIAL_SOURCE_TYPES if source_types is None else source_types
    source_ids = nearby_entity_ids(m_tensor, center_x, center_y, radius, allowed_types)
    if not source_ids:
        return {}

    workers = agent_radial_mask(h_tensor, active, center_x, center_y, radius, device)
    workers &= h_tensor[:, H_STAMINA] >= GATHER_STAMINA_COST
    if not workers.any():
        return {}

    gathered = 0
    for human_id in torch.where(workers)[0].tolist():
        source_entity_id = pick_best_entity(
            source_ids,
            lambda entity_id: point_distance(
                float(h_tensor[human_id, X]),
                float(h_tensor[human_id, Y]),
                float(m_tensor[entity_id, CX]),
                float(m_tensor[entity_id, CY]),
            ),
        )
        if source_entity_id == -1:
            continue

        if int(m_tensor[source_entity_id, M_TYPE]) == M_MOUNTAIN:
            m_tensor[source_entity_id, M_HP] = max(1.0, float(m_tensor[source_entity_id, M_HP]) - amount * 0.4)
        else:
            m_tensor[source_entity_id, M_RESOURCE_FOOD] = max(
                0.0,
                float(m_tensor[source_entity_id, M_RESOURCE_FOOD]) - amount * 0.5,
            )
            m_tensor[source_entity_id, M_FERTILITY] = max(
                0.0,
                float(m_tensor[source_entity_id, M_FERTILITY]) - amount * 0.1,
            )
        h_tensor[human_id, H_CARRYING] = min(MAX_CARRYING_MATERIAL, float(h_tensor[human_id, H_CARRYING]) + amount)
        h_tensor[human_id, H_STAMINA] = max(0.0, float(h_tensor[human_id, H_STAMINA]) - GATHER_STAMINA_COST)
        h_tensor[human_id, H_SKILL] += BUILD_SKILL_GAIN * 0.25
        gathered += 1

    return {"map_dirty": gathered > 0} if gathered else {}


__all__ = ["DEFAULT_MATERIAL_SOURCE_TYPES", "gather_materials"]
