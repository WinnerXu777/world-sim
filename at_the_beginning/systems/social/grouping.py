from __future__ import annotations

from typing import Any, Callable

import torch

try:
    from harness.calendar import rate_scale as _rate
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.calendar import rate_scale as _rate
try:
    from genesis_config import (
        CROWDING_LIMIT,
        CROWDING_RADIUS,
        H_INFECTION,
        H_SHELTER,
        H_TRIBE,
        HUNGER,
        INFECTION_THRESHOLD,
        MOOD,
        MOOD_RECOVERY_RATE,
        SOCIAL_NAV_WEIGHT,
        THIRST,
        THREAT,
        THREAT_DECAY_RATE,
        TRIBE_COHESION_RADIUS,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        CROWDING_LIMIT,
        CROWDING_RADIUS,
        H_INFECTION,
        H_SHELTER,
        H_TRIBE,
        HUNGER,
        INFECTION_THRESHOLD,
        MOOD,
        MOOD_RECOVERY_RATE,
        SOCIAL_NAV_WEIGHT,
        THIRST,
        THREAT,
        THREAT_DECAY_RATE,
        TRIBE_COHESION_RADIUS,
    )


def apply_emotional_recovery(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> None:
    """Gradually calm and restore mood when humans are not in immediate distress."""
    if not h_mask.any():
        return
    safe = (
        h_mask
        & (h_tensor[:, HUNGER] < 60.0)
        & (h_tensor[:, THIRST] < 60.0)
        & (h_tensor[:, H_INFECTION] < INFECTION_THRESHOLD)
    )
    if safe.any():
        h_tensor[safe, THREAT] -= THREAT_DECAY_RATE
        h_tensor[safe, THREAT] = h_tensor[safe, THREAT].clamp(min=0.0)
        h_tensor[safe, MOOD] += MOOD_RECOVERY_RATE * _rate("damage_recovery")
        sheltered = safe & (h_tensor[:, H_SHELTER] > 0.0)
        if sheltered.any():
            h_tensor[sheltered, MOOD] += 0.2
        h_tensor[safe, MOOD] = h_tensor[safe, MOOD].clamp(max=100.0)


def build_social_navigation_bias(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    device: str,
    pairwise: dict[str, Any],
) -> dict[str, torch.Tensor]:
    """Build cohesion and crowding-avoidance bias from the shared pairwise pass."""
    bias = torch.zeros((h_tensor.shape[0], 2), dtype=h_tensor.dtype, device=device)
    live_idx = pairwise["live_idx"]
    if live_idx.numel() == 0:
        return {"nav_social_bias": bias}

    live_pos = h_tensor[live_idx, :2]
    for row, hid in enumerate(live_idx.tolist()):
        tribe = float(h_tensor[hid, H_TRIBE])
        tribe_rows = torch.ones(live_idx.shape[0], dtype=torch.bool, device=device)
        if tribe != 0.0:
            tribe_rows = h_tensor[live_idx, H_TRIBE] == tribe

        local_rows = tribe_rows & (pairwise["dists"][row] < TRIBE_COHESION_RADIUS) & pairwise["not_self"][row]
        if local_rows.any():
            centroid = live_pos[local_rows].mean(dim=0)
            direction = centroid - live_pos[row]
            norm = direction.norm().clamp(min=1e-6)
            bias[hid] += (direction / norm) * SOCIAL_NAV_WEIGHT

        crowd_rows = (pairwise["dists"][row] < CROWDING_RADIUS) & pairwise["not_self"][row]
        if int(crowd_rows.sum().item()) >= CROWDING_LIMIT:
            crowd_center = live_pos[crowd_rows].mean(dim=0)
            repel = live_pos[row] - crowd_center
            norm = repel.norm().clamp(min=1e-6)
            bias[hid] += (repel / norm) * (SOCIAL_NAV_WEIGHT * 1.5)

    return {"nav_social_bias": bias}


def build_pairwise_relations(
    h_tensor: torch.Tensor,
    h_mask: torch.Tensor,
    *,
    ctx_key: str,
    seek_mask: torch.Tensor | None,
    pairwise_builder: Callable[[torch.Tensor, torch.Tensor, torch.Tensor | None], dict[str, Any]],
) -> dict[str, Any]:
    """Materialize the shared human-human pairwise tensors for this tick stage."""
    return {ctx_key: pairwise_builder(h_tensor, h_mask, seek_mask)}
