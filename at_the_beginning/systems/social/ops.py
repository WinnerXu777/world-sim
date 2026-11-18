from __future__ import annotations

"""
Stable, generation-friendly social ops.

These wrappers keep social recovery, grouping, and reproduction helpers on a
single predictable import surface for future generated code.
"""

from typing import Any

import torch

try:
    from systems.social.grouping import apply_emotional_recovery, build_pairwise_relations, build_social_navigation_bias
    from systems.social.mating import (
        apply_cooldown_decay,
        build_seek_mask,
        resolve_human_reproduction,
        restrict_reproduction_seek,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.social.grouping import (
        apply_emotional_recovery,
        build_pairwise_relations,
        build_social_navigation_bias,
    )
    from at_the_beginning.systems.social.mating import (
        apply_cooldown_decay,
        build_seek_mask,
        resolve_human_reproduction,
        restrict_reproduction_seek,
    )


def run_emotional_recovery(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> None:
    apply_emotional_recovery(h_mask, h_tensor)


def build_social_bias(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    *,
    seek_mask: torch.Tensor | None = None,
    device: str = "cpu",
) -> torch.Tensor:
    return build_social_navigation_bias(
        ctx,
        h_tensor,
        seek_mask=seek_mask,
        device=device,
    )


def build_social_relations(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    *,
    pairwise: dict,
) -> None:
    build_pairwise_relations(ctx, h_tensor, pairwise=pairwise)


def build_reproduction_seek(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> dict[str, torch.Tensor]:
    return build_seek_mask(h_mask, h_tensor)


def restrict_reproduction_targets(
    seek_mask: torch.Tensor | None,
    h_tensor: torch.Tensor,
) -> dict[str, torch.Tensor]:
    return restrict_reproduction_seek(seek_mask, h_tensor)


def resolve_reproduction(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    pop_count_ref: list,
    *,
    pairwise: dict,
    find_free_cell_fn,
    create_human_fn,
    device: str = "cpu",
) -> dict[str, Any]:
    return resolve_human_reproduction(
        ctx,
        h_tensor,
        m_tensor,
        pop_count_ref,
        pairwise=pairwise,
        find_free_cell_fn=find_free_cell_fn,
        create_human_fn=create_human_fn,
        device=device,
    )


def decay_social_cooldown(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    col: int,
    rate: float,
) -> None:
    apply_cooldown_decay(h_mask, h_tensor, col=col, rate=rate)


__all__ = [
    "build_reproduction_seek",
    "build_social_bias",
    "build_social_relations",
    "decay_social_cooldown",
    "resolve_reproduction",
    "restrict_reproduction_targets",
    "run_emotional_recovery",
]
