"""Exact distance helpers (1008 D0 finding G-D0-1).

``torch.cdist`` switches to ``||a||^2 + ||b||^2 - 2 a.b`` (a matmul) whenever either operand has more than 25 rows. In
float32 that cancels catastrophically for coordinates far from the origin: measured max error 0.78 units at x ~ 1000 with
1024 rows, 62 units at x ~ 100,000. ``pairwise_distances`` always uses the direct ``|a - b|`` formulation, whose error is
only the rounding of the (already float32) inputs, independent of their offset.
"""
from __future__ import annotations

import os
from typing import Optional

import torch

EXACT_MODE = "donot_use_mm_for_euclid_dist"
SPACES_FLAG = "EDEN_SPACES"
WINDOW_FLAG = "EDEN_WINDOW"
FAR = 1.0e30      # distance reported between rows of different spaces: finite (no inf*0 NaNs), beyond every radius in the game


def spaces_enabled() -> bool:
    """1008 D1: proximity code separates rows by space. Read at call time (bare and package imports share the environment); default off."""
    return os.environ.get(SPACES_FLAG, "") == "1"


def window_enabled() -> bool:
    """1008 P5: the world is a streaming window; entity rows come and go, so rows are named by uid, never by slot. Read at call time; default off."""
    return os.environ.get(WINDOW_FLAG, "") == "1"


def space_slice(tensor: torch.Tensor, rows, kind: str) -> Optional[torch.Tensor]:
    """The space column of ``tensor[rows]`` (``kind`` "h" for h_tensor, "m" for m_tensor) when spaces are enabled, else None, which
    makes ``pairwise_distances`` ignore spaces. The column constants are imported lazily so the flag-off path costs one dict lookup."""
    if not spaces_enabled():
        return None
    try:
        import genesis_config as cfg
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import genesis_config as cfg
    return tensor[rows, cfg.H_SPACE if kind == "h" else cfg.M_SPACE]


def pairwise_distances(a: torch.Tensor, b: torch.Tensor, *, space_a: Optional[torch.Tensor] = None,
                       space_b: Optional[torch.Tensor] = None) -> torch.Tensor:
    """Euclidean distance matrix ``(len(a), len(b))`` without the matmul shortcut. Drop-in for ``torch.cdist(a, b)``.

    With both ``space_a`` (len(a) values) and ``space_b`` (len(b) values, or one value for a single point) given, entries whose
    spaces differ are ``FAR``; equal-space entries are the plain distances, bit for bit. With either omitted the result is the
    unchanged legacy matrix.
    """
    distances = torch.cdist(a, b, compute_mode=EXACT_MODE)
    if space_a is None or space_b is None:
        return distances
    same = space_a.reshape(-1, 1) == space_b.reshape(1, -1)
    return torch.where(same, distances, torch.full_like(distances, FAR))
