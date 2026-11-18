from __future__ import annotations

import os

import torch

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg


try:
    from harness.limits import world_limits as _world_limits
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.limits import world_limits as _world_limits

PERCEPTION_FLAG = "EDEN_PERCEPTION_BOUNDED"
WINDOW_FLAG = "EDEN_WINDOW"


def perception_bounded() -> bool:
    """1008 WS-D: resident case building only sees rows inside a perception radius (and its own space). Read at call time; default off."""
    return os.environ.get(PERCEPTION_FLAG, "") == "1"


def window_mode() -> bool:
    """1008 P5: EDEN_WINDOW=1 (entity rows are streamed in and out; resident memory names sources by uid). Read at call time; default off."""
    return os.environ.get(WINDOW_FLAG, "") == "1"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def live_human_mask(h_tensor: torch.Tensor) -> torch.Tensor:
    return h_tensor[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN


def animal_mask(m_tensor: torch.Tensor, species: set[int] | None = None) -> torch.Tensor:
    mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
    for animal_type in cfg.ANIMAL_TYPES:
        if species is not None and animal_type not in species:
            continue
        mask |= m_tensor[:, cfg.M_TYPE] == animal_type
    return mask


def nearest_entity(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    type_ids: set[int] | None = None,
    resource_col: int | None = None,
    min_resource: float = 0.0,
    require_complete: bool = False,
    max_distance: float | None = None,
    space: int | None = None,
    space_col: int | None = None,
) -> tuple[int, float]:
    """Nearest live row matching the filters, as ``(row, distance)`` or ``(-1, inf)``.

    ``max_distance`` (inclusive) drops rows farther than the perception radius; ``space`` with ``space_col`` drops rows whose
    space column differs. Both default to None, which is the unbounded legacy behaviour.
    """
    best_eid = -1
    best_dist = float("inf")
    for eid in torch.where(m_tensor[:, cfg.M_TYPE] > 0)[0].tolist():
        if space is not None and space_col is not None and int(m_tensor[eid, space_col]) != int(space):
            continue
        type_id = int(m_tensor[eid, cfg.M_TYPE])
        if type_ids is not None and type_id not in type_ids:
            continue
        if resource_col is not None and float(m_tensor[eid, resource_col]) <= min_resource:
            continue
        if require_complete and float(m_tensor[eid, cfg.S_BUILD_PROGRESS]) < 100.0:
            continue
        distance = dist(px, py, float(m_tensor[eid, cfg.CX]), float(m_tensor[eid, cfg.CY]))
        if max_distance is not None and distance > max_distance:
            continue
        if distance < best_dist:
            best_dist = distance
            best_eid = eid
    return best_eid, best_dist


def nearest_human(
    h_tensor: torch.Tensor,
    slot: int,
    h_mask: torch.Tensor,
    tribe: float | None = None,
) -> tuple[int, float]:
    px = float(h_tensor[slot, cfg.X])
    py = float(h_tensor[slot, cfg.Y])
    best_slot = -1
    best_dist = float("inf")
    for other in torch.where(h_mask)[0].tolist():
        if other == slot:
            continue
        if tribe is not None and tribe != 0.0 and float(h_tensor[other, cfg.H_TRIBE]) != tribe:
            continue
        distance = dist(px, py, float(h_tensor[other, cfg.X]), float(h_tensor[other, cfg.Y]))
        if distance < best_dist:
            best_dist = distance
            best_slot = other
    return best_slot, best_dist


def move_toward(h_tensor: torch.Tensor, slot: int, tx: float, ty: float, magnitude: float) -> None:
    px = float(h_tensor[slot, cfg.X])
    py = float(h_tensor[slot, cfg.Y])
    dx = tx - px
    dy = ty - py
    norm = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    x0, y0, x1, y1 = _world_limits()
    h_tensor[slot, cfg.X] = clamp(px + (dx / norm) * magnitude, x0, x1)
    h_tensor[slot, cfg.Y] = clamp(py + (dy / norm) * magnitude, y0, y1)


def move_away(h_tensor: torch.Tensor, slot: int, tx: float, ty: float, magnitude: float) -> None:
    px = float(h_tensor[slot, cfg.X])
    py = float(h_tensor[slot, cfg.Y])
    dx = px - tx
    dy = py - ty
    norm = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    x0, y0, x1, y1 = _world_limits()
    h_tensor[slot, cfg.X] = clamp(px + (dx / norm) * magnitude, x0, x1)
    h_tensor[slot, cfg.Y] = clamp(py + (dy / norm) * magnitude, y0, y1)
