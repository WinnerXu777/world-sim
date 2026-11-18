from __future__ import annotations

import math

import torch

try:
    from genesis_config import CX, CY, X, Y
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import CX, CY, X, Y


def human_distance_to_human(h_tensor: torch.Tensor, attacker_slot: int, target_slot: int) -> float:
    return math.hypot(
        float(h_tensor[target_slot, X]) - float(h_tensor[attacker_slot, X]),
        float(h_tensor[target_slot, Y]) - float(h_tensor[attacker_slot, Y]),
    )


def human_distance_to_entity(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    attacker_slot: int,
    target_slot: int,
) -> float:
    return math.hypot(
        float(m_tensor[target_slot, CX]) - float(h_tensor[attacker_slot, X]),
        float(m_tensor[target_slot, CY]) - float(h_tensor[attacker_slot, Y]),
    )

