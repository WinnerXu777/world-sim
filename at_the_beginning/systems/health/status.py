from __future__ import annotations

import torch

try:
    from genesis_config import CRITICAL_HEALTH, HUNGER, THIRST
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import CRITICAL_HEALTH, HUNGER, THIRST


def update_human_critical_state(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    hunger_threshold: float = 90.0,
    thirst_threshold: float = 90.0,
) -> None:
    """Refresh the shared critical-health flag from survival vitals."""
    if not h_mask.any():
        return
    h_tensor[h_mask, CRITICAL_HEALTH] = 0.0
    critical = h_mask & (
        (h_tensor[:, HUNGER] >= float(hunger_threshold))
        | (h_tensor[:, THIRST] >= float(thirst_threshold))
    )
    h_tensor[critical, CRITICAL_HEALTH] = 1.0
