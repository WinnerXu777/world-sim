from __future__ import annotations

import torch

try:
    from genesis_config import M_HP, S_BUILD_PROGRESS, S_DURABILITY
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import M_HP, S_BUILD_PROGRESS, S_DURABILITY


def repair_structure_state(
    m_tensor: torch.Tensor,
    entity_id: int,
    amount: float,
    *,
    hp_col: int = M_HP,
    durability_col: int = S_DURABILITY,
    build_progress_col: int = S_BUILD_PROGRESS,
) -> None:
    """Repair a structure's hitpoints and partially restore build progress."""
    max_hp = float(m_tensor[entity_id, durability_col])
    m_tensor[entity_id, hp_col] = min(max_hp, float(m_tensor[entity_id, hp_col]) + float(amount))
    m_tensor[entity_id, build_progress_col] = min(
        100.0,
        float(m_tensor[entity_id, build_progress_col]) + float(amount) * 0.5,
    )


def damage_structure_state(
    m_tensor: torch.Tensor,
    entity_id: int,
    amount: float,
    *,
    hp_col: int = M_HP,
    build_progress_col: int = S_BUILD_PROGRESS,
) -> None:
    """Damage a structure and roll back build progress proportionally."""
    m_tensor[entity_id, hp_col] = max(0.0, float(m_tensor[entity_id, hp_col]) - float(amount))
    m_tensor[entity_id, build_progress_col] = max(
        0.0,
        float(m_tensor[entity_id, build_progress_col]) - float(amount) * 0.5,
    )


def reinforce_structure_durability(
    m_tensor: torch.Tensor,
    entity_id: int,
    amount: float,
    *,
    hp_col: int = M_HP,
    durability_col: int = S_DURABILITY,
    build_progress_col: int = S_BUILD_PROGRESS,
) -> None:
    """Boost both current HP and max durability for an existing structure."""
    m_tensor[entity_id, hp_col] += float(amount)
    m_tensor[entity_id, durability_col] += float(amount)
    m_tensor[entity_id, build_progress_col] = 100.0
