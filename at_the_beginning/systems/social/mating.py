from __future__ import annotations

import random
from typing import Any, Callable

import torch
try:
    from harness.limits import world_limits as _world_limits
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.limits import world_limits as _world_limits
try:
    from harness.clamp import clamp_rows_
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.clamp import clamp_rows_
try:
    from harness import instinct_bits
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness import instinct_bits

try:
    from genesis_config import (
        ACQUIRED_INSTINCT_MASK,
        HUNGER,
        H_AGE,
        H_COOLDOWN,
        H_STAMINA,
        H_TRIBE,
        HP,
        MATURE_AGE,
        MAP_HEIGHT,
        MAP_WIDTH,
        SAFE_REPRO_HP_MIN,
        SAFE_REPRO_HUNGER_MAX,
        SAFE_REPRO_STAMINA_MIN,
        SAFE_REPRO_THIRST_MAX,
        SAFE_REPRO_THREAT_MAX,
        THIRST,
        THREAT,
        TYPE,
        AGENT_TYPE_EMPTY,
        LIFE_EXP_MIN,
        LIFE_EXP_MAX,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        ACQUIRED_INSTINCT_MASK,
        HUNGER,
        H_AGE,
        H_COOLDOWN,
        H_STAMINA,
        H_TRIBE,
        HP,
        MATURE_AGE,
        MAP_HEIGHT,
        MAP_WIDTH,
        SAFE_REPRO_HP_MIN,
        SAFE_REPRO_HUNGER_MAX,
        SAFE_REPRO_STAMINA_MIN,
        SAFE_REPRO_THIRST_MAX,
        SAFE_REPRO_THREAT_MAX,
        THIRST,
        THREAT,
        TYPE,
        AGENT_TYPE_EMPTY,
        LIFE_EXP_MIN,
        LIFE_EXP_MAX,
    )


def build_seek_mask(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> dict[str, torch.Tensor]:
    """Build the initial reproduction-seeking mask for mature humans off cooldown."""
    seek_mask = h_mask & (h_tensor[:, H_AGE] >= MATURE_AGE) & (h_tensor[:, H_COOLDOWN] <= 0.0)
    return {"seek_mask": seek_mask}


def restrict_reproduction_seek(seek_mask: torch.Tensor | None, h_tensor: torch.Tensor) -> dict[str, torch.Tensor]:
    """Restrict reproduction to humans who are in sufficiently safe condition."""
    if seek_mask is None:
        return {}
    safe_seek = (
        seek_mask
        & (h_tensor[:, HUNGER] <= SAFE_REPRO_HUNGER_MAX)
        & (h_tensor[:, THIRST] <= SAFE_REPRO_THIRST_MAX)
        & (h_tensor[:, THREAT] <= SAFE_REPRO_THREAT_MAX)
        & (h_tensor[:, HP] >= SAFE_REPRO_HP_MIN)
        & (h_tensor[:, H_STAMINA] >= SAFE_REPRO_STAMINA_MIN)
    )
    return {"seek_mask": safe_seek}


def resolve_human_reproduction(
    h_tensor: torch.Tensor,
    pop_count_ref: list,
    pairwise: dict[str, Any],
    *,
    birth_fn: Callable[..., bool],
) -> list[dict[str, int]]:
    """Spawn children for close, ready, opposite-sex human pairs and set maternal cooldown."""
    if not pairwise["live_idx"].numel():
        return []
    mate_pairs = (
        pairwise["within_mate"]
        & pairwise["seek_ready"][:, None]
        & pairwise["seek_ready"][None, :]
        & pairwise["female"][:, None]
        & pairwise["male"][None, :]
    )
    mothers = pairwise["live_idx"][torch.where(mate_pairs.any(dim=1))[0]]
    births: list[dict[str, int]] = []
    for idx in mothers.tolist():
        live_row = int((pairwise["live_idx"] == idx).nonzero(as_tuple=False)[0].item())
        father_candidates = pairwise["live_idx"][torch.where(mate_pairs[live_row])[0]]
        father_slot = int(father_candidates[0].item()) if father_candidates.numel() else -1
        _limits = _world_limits()
        free = torch.where(h_tensor[:, TYPE] == AGENT_TYPE_EMPTY)[0]
        child_slot = int(free[0].item()) if len(free) else -1
        px = float(h_tensor[idx, 0]) + random.uniform(-4, 4)
        py = float(h_tensor[idx, 1]) + random.uniform(-4, 4)
        spawned = birth_fn(
            h_tensor,
            pop_count_ref,
            max(_limits[0], min(_limits[2], px)),
            max(_limits[1], min(_limits[3], py)),
            sex=0.0 if random.random() < 0.5 else 1.0,
            life_exp=random.uniform(LIFE_EXP_MIN, LIFE_EXP_MAX),
            parent_instincts=float(h_tensor[idx, ACQUIRED_INSTINCT_MASK]),
            tribe=float(h_tensor[idx, H_TRIBE]),
        )
        if spawned:
            instinct_bits.inherit_words(h_tensor, child_slot, int(idx))   # bits 24..63 of the mother's mask (G-D0-2)
            h_tensor[idx, H_COOLDOWN] = 1.0
            births.append(
                {
                    "child_slot": child_slot,
                    "mother_slot": int(idx),
                    "father_slot": father_slot,
                }
            )
    return births


def apply_cooldown_decay(h_mask: torch.Tensor, h_tensor: torch.Tensor, *, col: int, rate: float) -> None:
    """Decay a timer-like column toward zero for live humans."""
    h_tensor[h_mask, col] -= rate
    clamp_rows_(h_tensor, h_mask, col, lo=0.0)
