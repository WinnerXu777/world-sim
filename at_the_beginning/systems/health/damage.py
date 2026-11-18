from __future__ import annotations

import torch

try:
    from genesis_config import HP, M_HP
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import HP, M_HP


def apply_human_damage(
    mask: torch.Tensor,
    h_tensor: torch.Tensor,
    amount: float | torch.Tensor,
    *,
    hp_col: int = HP,
) -> bool:
    """Apply clamped damage to human HP."""
    if not mask.any():
        return False
    h_tensor[mask, hp_col] = torch.clamp(h_tensor[mask, hp_col] - amount, min=0.0)
    return True


def apply_entity_damage(
    mask: torch.Tensor,
    m_tensor: torch.Tensor,
    amount: float | torch.Tensor,
    *,
    hp_col: int = M_HP,
) -> bool:
    """Apply clamped damage to entity HP, including animals and structures."""
    if not mask.any():
        return False
    m_tensor[mask, hp_col] = torch.clamp(m_tensor[mask, hp_col] - amount, min=0.0)
    return True


def apply_human_heal(
    mask: torch.Tensor,
    h_tensor: torch.Tensor,
    amount: float | torch.Tensor,
    *,
    hp_col: int = HP,
    max_hp: float = 100.0,
) -> bool:
    """Apply clamped healing to human HP."""
    if not mask.any():
        return False
    h_tensor[mask, hp_col] = torch.clamp(h_tensor[mask, hp_col] + amount, max=max_hp)
    return True


def apply_entity_heal(
    mask: torch.Tensor,
    m_tensor: torch.Tensor,
    amount: float | torch.Tensor,
    *,
    hp_col: int = M_HP,
    max_hp: float = 100.0,
) -> bool:
    """Apply clamped healing to entity HP."""
    if not mask.any():
        return False
    m_tensor[mask, hp_col] = torch.clamp(m_tensor[mask, hp_col] + amount, max=max_hp)
    return True
