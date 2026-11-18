from __future__ import annotations

from typing import Callable

import torch

try:
    from genesis_config import (
        H_SHELTER,
        M_TYPE,
        MAX_ENTITIES,
        S_BUILD_PROGRESS,
        S_OCCUPANT_COUNT,
        S_SHELTER_CAP,
        STRUCTURE_TYPES,
        X,
        Y,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        H_SHELTER,
        M_TYPE,
        MAX_ENTITIES,
        S_BUILD_PROGRESS,
        S_OCCUPANT_COUNT,
        S_SHELTER_CAP,
        STRUCTURE_TYPES,
        X,
        Y,
    )


def update_shelter_flags(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_at_fn: Callable[[float, float], int],
) -> None:
    """Mark whether each human is currently inside a completed structure."""
    if not h_mask.any():
        return
    for slot in torch.where(h_mask)[0].tolist():
        entity_id = entity_at_fn(float(h_tensor[slot, X]), float(h_tensor[slot, Y]))
        if (
            entity_id != -1
            and int(m_tensor[entity_id, M_TYPE]) in STRUCTURE_TYPES
            and float(m_tensor[entity_id, S_BUILD_PROGRESS]) >= 100.0
            and float(m_tensor[entity_id, S_SHELTER_CAP]) > 0.0
        ):
            h_tensor[slot, H_SHELTER] = 1.0
        else:
            h_tensor[slot, H_SHELTER] = 0.0


def sync_structure_occupancy(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_at_fn: Callable[[float, float], int],
) -> None:
    """Keep structure occupancy counters aligned with the humans currently inside."""
    structure_mask = torch.zeros(MAX_ENTITIES, dtype=torch.bool, device=m_tensor.device)
    for structure_type in STRUCTURE_TYPES:
        structure_mask |= m_tensor[:, M_TYPE] == structure_type
    if not structure_mask.any():
        return

    m_tensor[structure_mask, S_OCCUPANT_COUNT] = 0.0
    if not h_mask.any():
        return

    for slot in torch.where(h_mask)[0].tolist():
        entity_id = entity_at_fn(float(h_tensor[slot, X]), float(h_tensor[slot, Y]))
        if entity_id == -1:
            continue
        if int(m_tensor[entity_id, M_TYPE]) not in STRUCTURE_TYPES:
            continue
        if float(m_tensor[entity_id, S_BUILD_PROGRESS]) < 100.0:
            continue
        if float(m_tensor[entity_id, S_SHELTER_CAP]) <= 0.0:
            continue
        m_tensor[entity_id, S_OCCUPANT_COUNT] += 1.0
