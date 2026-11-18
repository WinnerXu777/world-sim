from __future__ import annotations

from typing import Any, Callable

import torch
try:
    from harness.clamp import clamp_rows_
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.clamp import clamp_rows_
try:
    from harness.calendar import rate_scale as _rate
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.calendar import rate_scale as _rate

try:
    from genesis_config import (
        H_INFECTION,
        HP,
        INFECTION_DAMAGE_RATE,
        INFECTION_NATURAL_DECAY,
        INFECTION_SPREAD_RATE,
        INFECTION_SPREAD_RADIUS,
        INFECTION_THRESHOLD,
    )
    from systems.health.damage import apply_human_damage
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        H_INFECTION,
        HP,
        INFECTION_DAMAGE_RATE,
        INFECTION_NATURAL_DECAY,
        INFECTION_SPREAD_RATE,
        INFECTION_SPREAD_RADIUS,
        INFECTION_THRESHOLD,
    )
    from at_the_beginning.systems.health.damage import apply_human_damage


def apply_infection_tick(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    pairwise: dict[str, Any],
    *,
    proximity_fn: Callable[[torch.Tensor, torch.Tensor, torch.Tensor, float], torch.Tensor],
) -> None:
    """Apply infection spread, decay, and infection damage using the shared pairwise pass when available."""
    infected = h_mask & (h_tensor[:, H_INFECTION] > 0.0)

    if pairwise["live_idx"].numel() and pairwise["infected"].any():
        exposure = (
            pairwise["within_infection"]
            & pairwise["below_inf_thresh"][:, None]
            & pairwise["infected"][None, :]
        )
        spreads_to_rows = exposure.any(dim=1)
        if spreads_to_rows.any():
            spreads_to = pairwise["live_idx"][spreads_to_rows]
            h_tensor[spreads_to, H_INFECTION] += INFECTION_SPREAD_RATE * _rate("damage_recovery")
            clamp_rows_(h_tensor, spreads_to, H_INFECTION, hi=100.0)

        near_infected = (pairwise["within_infection"] & pairwise["infected"][None, :]).any(dim=1)
        isolated = pairwise["live_idx"][~near_infected]
        if isolated.numel():
            h_tensor[isolated, H_INFECTION] -= INFECTION_NATURAL_DECAY * _rate("damage_recovery")
            clamp_rows_(h_tensor, isolated, H_INFECTION, lo=0.0)
    elif infected.any():
        healthy = h_mask & (h_tensor[:, H_INFECTION] < INFECTION_THRESHOLD)
        if healthy.any():
            near = proximity_fn(h_tensor, healthy, infected, INFECTION_SPREAD_RADIUS)
            spreads_to = torch.where(healthy)[0][near]
            if spreads_to.numel():
                h_tensor[spreads_to, H_INFECTION] += INFECTION_SPREAD_RATE * _rate("damage_recovery")
                clamp_rows_(h_tensor, spreads_to, H_INFECTION, hi=100.0)
        near_inf = proximity_fn(h_tensor, h_mask, infected, INFECTION_SPREAD_RADIUS)
        isolated = torch.where(h_mask)[0][~near_inf]
        if isolated.numel():
            h_tensor[isolated, H_INFECTION] -= INFECTION_NATURAL_DECAY * _rate("damage_recovery")
            clamp_rows_(h_tensor, isolated, H_INFECTION, lo=0.0)

    critical_inf = h_mask & (h_tensor[:, H_INFECTION] >= INFECTION_THRESHOLD)
    apply_human_damage(critical_inf, h_tensor, INFECTION_DAMAGE_RATE * _rate("damage_recovery"), hp_col=HP)
