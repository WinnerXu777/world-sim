from __future__ import annotations

import torch


def apply_navigation_bias(
    noise: torch.Tensor,
    h_indices: torch.Tensor,
    nav_survival: torch.Tensor | None = None,
    nav_social: torch.Tensor | None = None,
    nav_schedule: torch.Tensor | None = None,
) -> torch.Tensor:
    """Apply shared autonomous navigation biases to the live movement buffer."""
    if nav_survival is not None:
        noise += nav_survival[h_indices]
    if nav_social is not None:
        noise += nav_social[h_indices]
    if nav_schedule is not None:
        noise += nav_schedule[h_indices]
    return noise
