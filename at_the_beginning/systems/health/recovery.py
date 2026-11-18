from __future__ import annotations

import torch

try:
    from harness.calendar import rate_scale as _rate
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.calendar import rate_scale as _rate
try:
    from genesis_config import HEAL_RATE, HP, HUNGER, H_INFECTION, INFECTION_THRESHOLD
    from systems.health.damage import apply_human_heal
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import HEAL_RATE, HP, HUNGER, H_INFECTION, INFECTION_THRESHOLD
    from at_the_beginning.systems.health.damage import apply_human_heal


def apply_heal_tick(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> None:
    """Heal humans who are fed, safe, and not critically infected."""
    eligible = (
        h_mask
        & (h_tensor[:, HUNGER] < 70.0)
        & (h_tensor[:, H_INFECTION] < INFECTION_THRESHOLD)
        & (h_tensor[:, HP] < 100.0)
    )
    apply_human_heal(eligible, h_tensor, HEAL_RATE * _rate("damage_recovery"))
