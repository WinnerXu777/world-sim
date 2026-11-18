from __future__ import annotations

from typing import Any

import torch

try:
    import map_geo
    from genesis_config import (
        BUILD_MATERIAL_USE,
        BUILD_MIN_STAMINA,
        BUILD_MOOD_GAIN,
        BUILD_RADIUS,
        BUILD_SKILL_GAIN,
        BUILD_STAMINA_COST,
        CX,
        CY,
        DEMOLISH_RATE_PER_HUMAN,
        DEMOLISH_STAMINA_COST,
        H_CARRYING,
        H_SKILL,
        H_STAMINA,
        MAX_CARRYING_MATERIAL,
        MOOD,
        M_HP,
        M_TYPE,
        SALVAGE_RETURN_FRACTION,
        S_BUILD_PROGRESS,
        S_DURABILITY,
        STRUCTURE_TYPES,
    )
    from systems.perception import agent_radial_mask, nearby_entity_ids
    from systems.health import damage_structure_state, reinforce_structure_durability, repair_structure_state
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import map_geo
    from at_the_beginning.genesis_config import (
        BUILD_MATERIAL_USE,
        BUILD_MIN_STAMINA,
        BUILD_MOOD_GAIN,
        BUILD_RADIUS,
        BUILD_SKILL_GAIN,
        BUILD_STAMINA_COST,
        CX,
        CY,
        DEMOLISH_RATE_PER_HUMAN,
        DEMOLISH_STAMINA_COST,
        H_CARRYING,
        H_SKILL,
        H_STAMINA,
        MAX_CARRYING_MATERIAL,
        MOOD,
        M_HP,
        M_TYPE,
        SALVAGE_RETURN_FRACTION,
        S_BUILD_PROGRESS,
        S_DURABILITY,
        STRUCTURE_TYPES,
    )
    from at_the_beginning.systems.perception import agent_radial_mask, nearby_entity_ids
    from at_the_beginning.systems.health import damage_structure_state, reinforce_structure_durability, repair_structure_state


def repair_with_humans(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    target_entity_ids: list[int] | torch.Tensor,
    builder_mask: torch.Tensor | None = None,
    repair_radius: float = BUILD_RADIUS,
    repair_rate: float = 8.0,
    device: str = "cpu",
) -> dict[str, Any]:
    """Repair nearby structures using local builders."""
    h_mask = ctx["h_mask"]
    available = h_mask if builder_mask is None else (builder_mask & h_mask)
    targets = target_entity_ids.tolist() if isinstance(target_entity_ids, torch.Tensor) else list(target_entity_ids)
    if not available.any() or not targets:
        return {}

    changed = False
    assigned = torch.zeros_like(h_mask)
    for entity_id in targets:
        if int(m_tensor[entity_id, M_TYPE]) not in STRUCTURE_TYPES:
            continue
        local = agent_radial_mask(
            h_tensor,
            available & ~assigned,
            float(m_tensor[entity_id, CX]),
            float(m_tensor[entity_id, CY]),
            repair_radius,
            device,
        )
        local &= h_tensor[:, H_STAMINA] >= BUILD_MIN_STAMINA
        if not local.any():
            continue
        for human_id in torch.where(local)[0].tolist():
            repair_structure_state(m_tensor, entity_id, repair_rate)
            h_tensor[human_id, H_STAMINA] = max(0.0, float(h_tensor[human_id, H_STAMINA]) - BUILD_STAMINA_COST)
            h_tensor[human_id, H_SKILL] += BUILD_SKILL_GAIN * 0.5
            h_tensor[human_id, MOOD] = min(100.0, float(h_tensor[human_id, MOOD]) + BUILD_MOOD_GAIN * 0.5)
            h_tensor[human_id, H_CARRYING] = max(0.0, float(h_tensor[human_id, H_CARRYING]) - BUILD_MATERIAL_USE * 0.5)
            assigned[human_id] = True
            changed = True
    return {"map_dirty": changed} if changed else {}


def demolish_with_humans(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    target_entity_ids: list[int] | torch.Tensor,
    builder_mask: torch.Tensor | None = None,
    demolish_radius: float = BUILD_RADIUS,
    device: str = "cpu",
) -> dict[str, Any]:
    """Damage or remove map objects and return salvage to nearby builders."""
    h_mask = ctx["h_mask"]
    available = h_mask if builder_mask is None else (builder_mask & h_mask)
    targets = target_entity_ids.tolist() if isinstance(target_entity_ids, torch.Tensor) else list(target_entity_ids)
    if not available.any() or not targets:
        return {}

    changed = False
    assigned = torch.zeros_like(h_mask)
    for entity_id in targets:
        if int(m_tensor[entity_id, M_TYPE]) == 0:
            continue
        local = agent_radial_mask(
            h_tensor,
            available & ~assigned,
            float(m_tensor[entity_id, CX]),
            float(m_tensor[entity_id, CY]),
            demolish_radius,
            device,
        )
        local &= h_tensor[:, H_STAMINA] >= DEMOLISH_STAMINA_COST
        if not local.any():
            continue
        workers = torch.where(local)[0].tolist()
        damage = DEMOLISH_RATE_PER_HUMAN * len(workers)
        damage_structure_state(m_tensor, entity_id, damage)
        for human_id in workers:
            h_tensor[human_id, H_STAMINA] = max(0.0, float(h_tensor[human_id, H_STAMINA]) - DEMOLISH_STAMINA_COST)
            h_tensor[human_id, H_CARRYING] = min(
                MAX_CARRYING_MATERIAL,
                float(h_tensor[human_id, H_CARRYING]) + damage * SALVAGE_RETURN_FRACTION / max(1, len(workers)),
            )
            h_tensor[human_id, H_SKILL] += BUILD_SKILL_GAIN * 0.25
            assigned[human_id] = True
        if float(m_tensor[entity_id, M_HP]) <= 0.0:
            if entity_id in map_geo.MAP_GEO:
                map_geo.unregister_entity(entity_id)
            m_tensor[entity_id] = 0.0
            entity_count_ref[0] -= 1
        changed = True
    return {"map_dirty": changed} if changed else {}


def tool_repair_area_with_humans(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float = BUILD_RADIUS,
    repair_rate: float = 8.0,
    device: str = "cpu",
) -> dict[str, Any]:
    target_ids = nearby_entity_ids(m_tensor, center_x, center_y, radius, STRUCTURE_TYPES)
    if not target_ids:
        return {}
    return repair_with_humans(ctx, h_tensor, m_tensor, target_ids, repair_radius=radius, repair_rate=repair_rate, device=device)


def tool_demolish_area_with_humans(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    radius: float = BUILD_RADIUS,
    device: str = "cpu",
) -> dict[str, Any]:
    target_ids = nearby_entity_ids(m_tensor, center_x, center_y, radius, STRUCTURE_TYPES)
    if not target_ids:
        return {}
    return demolish_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        target_ids,
        demolish_radius=radius,
        device=device,
    )


def tool_repair_structures(
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float = 60.0,
    amount: float = 30.0,
) -> dict[str, Any]:
    repaired = False
    for entity_id in nearby_entity_ids(m_tensor, center_x, center_y, radius, STRUCTURE_TYPES):
        reinforce_structure_durability(m_tensor, entity_id, amount)
        repaired = True
    return {"map_dirty": repaired} if repaired else {}


__all__ = [
    "demolish_with_humans",
    "repair_with_humans",
    "tool_demolish_area_with_humans",
    "tool_repair_area_with_humans",
    "tool_repair_structures",
]
