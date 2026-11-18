from __future__ import annotations

from typing import Any, Callable

import torch

try:
    from harness.calendar import rate_scale as _rate
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.calendar import rate_scale as _rate
try:
    from genesis_config import (
        EAT_HUNGER_RESTORE,
        EAT_RESOURCE_COST,
        HUNGER,
        HUNGER_TICK_RATE,
        M_RESOURCE_FOOD,
        X,
        Y,
    )
    from systems.health import apply_heal_tick as apply_shared_heal_tick, apply_human_damage, update_human_critical_state
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        EAT_HUNGER_RESTORE,
        EAT_RESOURCE_COST,
        HUNGER,
        HUNGER_TICK_RATE,
        M_RESOURCE_FOOD,
        X,
        Y,
    )
    from at_the_beginning.systems.health import apply_heal_tick as apply_shared_heal_tick, apply_human_damage, update_human_critical_state


def apply_hunger_tick(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> None:
    """Advance hunger and starvation damage for live humans."""
    h_tensor[h_mask, HUNGER] += HUNGER_TICK_RATE * _rate("needs")
    h_tensor[h_mask, HUNGER] = h_tensor[h_mask, HUNGER].clamp(max=100.0)
    starving = h_mask & (h_tensor[:, HUNGER] >= 90.0)
    apply_human_damage(starving, h_tensor, 2.0 * _rate("starvation"))
    update_human_critical_state(h_mask, h_tensor)


def eat_from_current_entity(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_at_fn: Callable[[float, float], int],
) -> dict[str, Any]:
    """Consume food from the entity currently covering each hungry human."""
    if not h_mask.any():
        return {}

    map_dirty = False
    for slot in torch.where(h_mask)[0].tolist():
        if h_tensor[slot, HUNGER] <= 20.0:
            continue
        entity_id = entity_at_fn(float(h_tensor[slot, X]), float(h_tensor[slot, Y]))
        if entity_id == -1:
            continue
        food = float(m_tensor[entity_id, M_RESOURCE_FOOD])
        if food <= 0.0:
            continue
        h_tensor[slot, HUNGER] -= EAT_HUNGER_RESTORE
        if h_tensor[slot, HUNGER] < 0:
            h_tensor[slot, HUNGER] = 0.0
        m_tensor[entity_id, M_RESOURCE_FOOD] = max(0.0, food - EAT_RESOURCE_COST)
        map_dirty = True
    return {"map_dirty": map_dirty} if map_dirty else {}


def apply_heal_tick(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> None:
    """Compatibility wrapper for the shared health recovery helper."""
    apply_shared_heal_tick(h_mask, h_tensor)
