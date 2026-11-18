from __future__ import annotations

import math

import torch
try:
    from harness.numerics import pairwise_distances, space_slice
    from harness.spaces import point_space
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.numerics import pairwise_distances, space_slice
    from at_the_beginning.harness.spaces import point_space

try:
    import map_geo
    from genesis_config import (
        CX,
        CY,
        M_BEACH,
        M_BURNING,
        M_FARM,
        M_FERTILITY,
        M_FLOODED,
        M_FOREST,
        M_GRASS,
        M_HOUSE,
        M_RESOURCE_FOOD,
        M_RESOURCE_WATER,
        M_TYPE,
        M_VILLAGE,
        M_WELL,
        MAX_ENTITIES,
        SCALE,
        S_BUILD_PROGRESS,
        X,
        Y,
    )
    from systems.perception.resolver import pick_best_entity
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import map_geo
    from at_the_beginning.genesis_config import (
        CX,
        CY,
        M_BEACH,
        M_BURNING,
        M_FARM,
        M_FERTILITY,
        M_FLOODED,
        M_FOREST,
        M_GRASS,
        M_HOUSE,
        M_RESOURCE_FOOD,
        M_RESOURCE_WATER,
        M_TYPE,
        M_VILLAGE,
        M_WELL,
        MAX_ENTITIES,
        SCALE,
        S_BUILD_PROGRESS,
        X,
        Y,
    )
    from at_the_beginning.systems.perception.resolver import pick_best_entity


DEFAULT_SAFE_TYPES = {M_GRASS, M_FOREST, M_BEACH, M_HOUSE, M_VILLAGE, M_FARM, M_WELL}


def point_distance(x0: float, y0: float, x1: float, y1: float) -> float:
    """Euclidean distance between two world positions."""
    return math.hypot(x1 - x0, y1 - y0)


def current_entity_id(px: float, py: float) -> int:
    """Entity covering a world point, or ``-1`` when empty."""
    return int(map_geo.entity_at(px, py))


def nearby_entity_ids(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    radius: float,
    type_filter: set[int] | None = None,
) -> list[int]:
    """List nearby map entities around a world point."""
    return [int(entity_id) for entity_id in map_geo.entities_in_radius(px, py, radius, m_tensor, type_filter)]


def agent_radial_mask(
    h_tensor: torch.Tensor,
    h_mask: torch.Tensor,
    cx: float,
    cy: float,
    radius: float,
    device: str,
    space: int | None = None,
) -> torch.Tensor:
    """Bool mask over human rows within radius of a world point (and, with EDEN_SPACES and ``space`` given, in that space)."""
    center = torch.tensor([[cx, cy]], dtype=torch.float32, device=device)
    pos = h_tensor[h_mask, :2]
    if space is None:
        space = point_space(cx, cy)               # EDEN_SPACES: the query point's own space (None, no filter, with the flag off)
    row_space = space_slice(h_tensor, h_mask, "h") if space is not None else None
    center_space = torch.tensor([float(space)], dtype=torch.float32, device=device) if row_space is not None else None
    dists = pairwise_distances(pos, center, space_a=row_space, space_b=center_space).squeeze(1)
    h_idx = torch.where(h_mask)[0]
    result = torch.zeros(h_tensor.shape[0], dtype=torch.bool, device=device)
    result[h_idx[dists < radius]] = True
    return result


def entity_radial_ids(
    m_tensor: torch.Tensor,
    cx: float,
    cy: float,
    radius: float,
    space: int | None = None,
) -> torch.Tensor:
    """Entity row indices within radius of a world point (and, with EDEN_SPACES and ``space`` given, in that space)."""
    pos = m_tensor[:MAX_ENTITIES, [CX, CY]]
    live = m_tensor[:MAX_ENTITIES, M_TYPE] > 0
    center = torch.tensor([[cx, cy]], dtype=torch.float32, device=m_tensor.device)
    if space is None:
        space = point_space(cx, cy)               # EDEN_SPACES: the query point's own space (None, no filter, with the flag off)
    row_space = space_slice(m_tensor[:MAX_ENTITIES], slice(None), "m") if space is not None else None
    center_space = torch.tensor([float(space)], dtype=torch.float32, device=m_tensor.device) if row_space is not None else None
    dists = pairwise_distances(pos, center, space_a=row_space, space_b=center_space).squeeze(1)
    return torch.where(live & (dists < radius))[0]


def nearest_geo_entity(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    type_filter: set[int] | None = None,
    radius: float = 0.0,
) -> int:
    """
    Return the covering entity first, then fall back to nearby geometry ranked by
    approximate edge distance.
    """
    entity_id = current_entity_id(px, py)
    if entity_id != -1:
        entity_type = int(m_tensor[entity_id, M_TYPE])
        if type_filter is None or entity_type in type_filter:
            return entity_id

    if radius <= 0.0:
        return -1

    candidates = nearby_entity_ids(m_tensor, px, py, radius, type_filter)
    if not candidates:
        return -1

    def _edge_distance(candidate_id: int) -> float:
        cx = float(m_tensor[candidate_id, CX])
        cy = float(m_tensor[candidate_id, CY])
        return max(0.0, point_distance(px, py, cx, cy) - max(1.0, float(m_tensor[candidate_id, SCALE])))

    return pick_best_entity(candidates, _edge_distance)


def nearest_entity_from_ids(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    entity_ids: list[int] | torch.Tensor,
) -> tuple[int, float]:
    """Nearest entity from an explicit candidate list."""
    ids = entity_ids.tolist() if isinstance(entity_ids, torch.Tensor) else list(entity_ids)
    if not ids:
        return -1, float("inf")

    def _distance(entity_id: int) -> float:
        return point_distance(px, py, float(m_tensor[entity_id, CX]), float(m_tensor[entity_id, CY]))

    best_entity_id = pick_best_entity(ids, _distance)
    if best_entity_id == -1:
        return -1, float("inf")
    return best_entity_id, _distance(best_entity_id)


def nearest_human_from_mask(
    h_tensor: torch.Tensor,
    px: float,
    py: float,
    human_mask: torch.Tensor,
    *,
    max_distance: float | None = None,
) -> tuple[int, float]:
    """Nearest human slot from a boolean mask."""
    if human_mask.numel() == 0 or not human_mask.any():
        return -1, float("inf")

    human_slots = torch.where(human_mask)[0]

    def _distance(slot: int) -> float:
        return point_distance(px, py, float(h_tensor[slot, X]), float(h_tensor[slot, Y]))

    best_slot = pick_best_entity(human_slots.tolist(), _distance)
    if best_slot == -1:
        return -1, float("inf")
    best_distance = _distance(best_slot)
    if max_distance is not None and best_distance > float(max_distance):
        return -1, float("inf")
    return best_slot, best_distance


def entity_unit_vector(
    m_tensor: torch.Tensor,
    source_x: float,
    source_y: float,
    target_entity_id: int,
    away: bool = False,
) -> tuple[float, float]:
    """Unit vector from a point toward or away from a map entity center."""
    if target_entity_id == -1:
        return 0.0, 0.0
    dx = float(m_tensor[target_entity_id, CX]) - source_x
    dy = float(m_tensor[target_entity_id, CY]) - source_y
    if away:
        dx *= -1.0
        dy *= -1.0
    norm = max(math.hypot(dx, dy), 1e-6)
    return dx / norm, dy / norm


def best_resource_entity(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    type_filter: set[int],
    resource_col: int,
    radius: float,
    min_value: float = 0.0,
) -> int:
    """Best nearby resource source balancing distance and abundance."""
    candidates = nearby_entity_ids(m_tensor, px, py, radius, type_filter)
    if not candidates:
        return -1

    viable_candidates = [
        entity_id
        for entity_id in candidates
        if float(m_tensor[entity_id, resource_col]) > min_value
        and int(m_tensor[entity_id, M_BURNING]) <= 0
        and int(m_tensor[entity_id, M_FLOODED]) <= 0
    ]
    if not viable_candidates:
        return -1

    def _score(entity_id: int) -> float:
        distance = point_distance(px, py, float(m_tensor[entity_id, CX]), float(m_tensor[entity_id, CY]))
        richness = float(m_tensor[entity_id, resource_col]) * 0.1
        fertility = float(m_tensor[entity_id, M_FERTILITY]) * 0.03
        return distance - richness - fertility

    return pick_best_entity(viable_candidates, _score)


def best_safe_entity(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    radius: float,
    allowed_types: set[int] | None = None,
) -> int:
    """Best nearby safe destination balancing shelter, resources, and distance."""
    allowed = DEFAULT_SAFE_TYPES if allowed_types is None else allowed_types
    candidates = nearby_entity_ids(m_tensor, px, py, radius, allowed)
    if not candidates:
        return -1

    viable_candidates = [
        entity_id
        for entity_id in candidates
        if int(m_tensor[entity_id, M_BURNING]) <= 0
        and int(m_tensor[entity_id, M_FLOODED]) <= 0
    ]
    if not viable_candidates:
        return -1

    def _score(entity_id: int) -> float:
        distance = point_distance(px, py, float(m_tensor[entity_id, CX]), float(m_tensor[entity_id, CY]))
        shelter_bonus = 25.0 if (
            int(m_tensor[entity_id, M_TYPE]) in {M_HOUSE, M_VILLAGE}
            and float(m_tensor[entity_id, S_BUILD_PROGRESS]) >= 100.0
        ) else 0.0
        fertility_bonus = float(m_tensor[entity_id, M_FERTILITY]) * 0.05
        resource_bonus = float(m_tensor[entity_id, M_RESOURCE_FOOD]) * 0.04
        water_bonus = float(m_tensor[entity_id, M_RESOURCE_WATER]) * 0.04
        return distance - shelter_bonus - fertility_bonus - resource_bonus - water_bonus

    return pick_best_entity(viable_candidates, _score)


__all__ = [
    "DEFAULT_SAFE_TYPES",
    "agent_radial_mask",
    "best_resource_entity",
    "best_safe_entity",
    "current_entity_id",
    "entity_radial_ids",
    "entity_unit_vector",
    "nearby_entity_ids",
    "nearest_entity_from_ids",
    "nearest_geo_entity",
    "nearest_human_from_mask",
    "point_distance",
]
