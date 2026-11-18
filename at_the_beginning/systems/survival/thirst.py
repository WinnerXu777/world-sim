from __future__ import annotations

from typing import Any, Callable

import torch

try:
    from harness.calendar import rate_scale as _rate
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.calendar import rate_scale as _rate
try:
    from genesis_config import (
        DRINK_PROXIMITY_RADIUS,
        DRINK_RESOURCE_COST,
        DRINK_THIRST_RESTORE,
        MOOD,
        M_LAKE,
        M_RESOURCE_WATER,
        M_WELL,
        THIRST,
        THIRST_DAMAGE_RATE,
        THIRST_TICK_RATE,
        X,
        Y,
    )
    from systems.health import apply_human_damage, update_human_critical_state
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        DRINK_PROXIMITY_RADIUS,
        DRINK_RESOURCE_COST,
        DRINK_THIRST_RESTORE,
        MOOD,
        M_LAKE,
        M_RESOURCE_WATER,
        M_WELL,
        THIRST,
        THIRST_DAMAGE_RATE,
        THIRST_TICK_RATE,
        X,
        Y,
    )
    from at_the_beginning.systems.health import apply_human_damage, update_human_critical_state


DRINKABLE_TYPES = {M_LAKE, M_WELL}


def apply_thirst_tick(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> None:
    """Advance thirst, dehydration damage, and critical-health marking."""
    h_tensor[h_mask, THIRST] += THIRST_TICK_RATE * _rate("needs")
    h_tensor[h_mask, THIRST] = h_tensor[h_mask, THIRST].clamp(max=100.0)
    dehydrated = h_mask & (h_tensor[:, THIRST] >= 90.0)
    if dehydrated.any():
        apply_human_damage(dehydrated, h_tensor, THIRST_DAMAGE_RATE * _rate("damage_recovery"))
        h_tensor[dehydrated, MOOD] -= 0.4
        h_tensor[dehydrated, MOOD] = h_tensor[dehydrated, MOOD].clamp(min=0.0)
    update_human_critical_state(h_mask, h_tensor)


def drink_from_nearby_entity(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    nearest_geo_entity_fn: Callable[[torch.Tensor, float, float, set[int], float], int],
) -> dict[str, Any]:
    """Drink from nearby lakes or wells using the shared coarse-geometry lookup."""
    if not h_mask.any():
        return {}

    map_dirty = False
    for slot in torch.where(h_mask)[0].tolist():
        if h_tensor[slot, THIRST] <= 20.0:
            continue
        entity_id = nearest_geo_entity_fn(
            m_tensor,
            float(h_tensor[slot, X]),
            float(h_tensor[slot, Y]),
            DRINKABLE_TYPES,
            DRINK_PROXIMITY_RADIUS,
        )
        if entity_id == -1:
            continue
        water = float(m_tensor[entity_id, M_RESOURCE_WATER])
        if water <= 0.0:
            continue
        h_tensor[slot, THIRST] -= DRINK_THIRST_RESTORE
        h_tensor[slot, THIRST] = max(0.0, float(h_tensor[slot, THIRST]))
        h_tensor[slot, MOOD] += 0.5
        h_tensor[slot, MOOD].clamp_(max=100.0)
        m_tensor[entity_id, M_RESOURCE_WATER] = max(0.0, water - DRINK_RESOURCE_COST)
        map_dirty = True
    return {"map_dirty": map_dirty} if map_dirty else {}
