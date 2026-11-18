"""In-place clamping of selected tensor rows that actually writes the result back.

``t[mask, col].clamp_(lo, hi)`` is a silent no-op when ``mask`` is a boolean mask or an index tensor: advanced indexing returns a
copy, the copy is clamped and thrown away (1008 audit G-D0-4, 31 legacy call sites). ``clamp_rows_`` does the intended thing for
bool masks, index tensors, integers, slices and tuples of them, keeps the dtype, and accepts ``None`` for an open end.
"""
from __future__ import annotations

from typing import Optional

import torch


def clamp_rows_(tensor: torch.Tensor, rows, col, lo: Optional[float] = None, hi: Optional[float] = None) -> torch.Tensor:
    """Clamp ``tensor[rows, col]`` to ``[lo, hi]`` in place; returns ``tensor``. ``rows`` is a bool mask, index tensor, int or slice."""
    if lo is None and hi is None:
        return tensor
    selected = tensor[rows, col]
    if selected.numel() == 0:
        return tensor
    tensor[rows, col] = torch.clamp(selected, min=lo, max=hi)
    return tensor
