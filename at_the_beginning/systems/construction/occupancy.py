from __future__ import annotations

import torch

try:
    from genesis_config import M_TYPE, S_BUILD_PROGRESS, S_SHELTER_CAP, STRUCTURE_TYPES
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import M_TYPE, S_BUILD_PROGRESS, S_SHELTER_CAP, STRUCTURE_TYPES


def occupiable_structure_mask(m_tensor: torch.Tensor) -> torch.Tensor:
    """Finished structures that can shelter humans."""
    structure_ids = torch.tensor(sorted(int(value) for value in STRUCTURE_TYPES), dtype=torch.int64, device=m_tensor.device)
    return (
        torch.isin(m_tensor[:, M_TYPE].to(dtype=torch.int64), structure_ids)
        & (m_tensor[:, S_BUILD_PROGRESS] >= 100.0)
        & (m_tensor[:, S_SHELTER_CAP] > 0.0)
    )


__all__ = ["occupiable_structure_mask"]
