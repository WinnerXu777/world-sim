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
PREFILTER_MIN = 8               # R66-PACE-2: below this many candidates the exact scan alone is cheaper than the prefilter
PREFILTER_MARGIN = 1e-9         # relative and absolute slack of the float64 prefilters; their own error is about 1e-16 relative


def point_distance(x0: float, y0: float, x1: float, y1: float) -> float:
    """Euclidean distance between two world positions."""
    return math.hypot(x1 - x0, y1 - y0)


def _plain_coordinate(value) -> bool:
    """A finite query coordinate whose arithmetic in the exact scan is plain float64: a float, or an int that converts exactly."""
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, int) and abs(value) < 2 ** 53


def _nearest_candidates(tensor: torch.Tensor, col_x: int, col_y: int, px, py, ids: list) -> list | None:
    """R66-PACE-2: the ids, in the caller's order, that can be nearest to (px, py); the exact scan then runs on these only.

    One float64 gather and distance for all candidates instead of four scalar tensor reads each. The subtraction is the exact scan's own
    float64 one and the square root differs from ``math.hypot`` by a few units in the last place, so with ``PREFILTER_MARGIN`` every id at
    the exact minimum, ties included, survives and every id dropped is strictly farther: the strict ``<`` scan over the survivors (in the
    caller's order) picks the same id. None means scan every candidate, as before: few candidates, a coordinate that is not a finite plain
    float, an id outside the tensor, or a non-finite candidate position.
    """
    if len(ids) < PREFILTER_MIN or not (_plain_coordinate(px) and _plain_coordinate(py)):
        return None
    try:
        index = torch.tensor([int(v) for v in ids], dtype=torch.long)
    except (TypeError, ValueError, OverflowError, RuntimeError):
        return None
    if int(index.min()) < 0 or int(index.max()) >= tensor.shape[0]:
        return None
    index = index.to(tensor.device)
    xs = tensor[:, col_x].index_select(0, index).double().cpu()
    ys = tensor[:, col_y].index_select(0, index).double().cpu()
    if not (bool(torch.isfinite(xs).all()) and bool(torch.isfinite(ys).all())):
        return None
    distances = torch.sqrt((xs - float(px)) ** 2 + (ys - float(py)) ** 2)
    limit = float(distances.min()) * (1.0 + PREFILTER_MARGIN) + PREFILTER_MARGIN
    return [ids[k] for k in torch.nonzero(distances <= limit, as_tuple=False).flatten().tolist()]


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


def nearest_geo_entity_possible(
    m_tensor: torch.Tensor,
    points,
    type_filter: set[int] | None = None,
    radius: float = 0.0,
) -> list[bool]:
    """R66-PACE-2: for each (px, py), False only where ``nearest_geo_entity(m_tensor, px, py, type_filter, radius)`` returns -1 for certain.

    True where an entity of a filtered type covers the point, or where a MAP_GEO entity of a filtered type lies within the radius (float64,
    with ``PREFILTER_MARGIN``; spaces are not checked), so it is a superset of what the exact query finds. One gather for the whole batch
    instead of one per point; the caller still runs the exact query wherever the answer is True. Non-finite input answers True.
    """
    points = [(px, py) for px, py in points]
    answers = []
    for px, py in points:
        try:
            entity_id = current_entity_id(px, py)
            answers.append(entity_id != -1 and (type_filter is None or int(m_tensor[entity_id, M_TYPE]) in type_filter))
        except (IndexError, ValueError, TypeError, OverflowError, RuntimeError):
            answers.append(True)                          # the exact query meets the same input: let it decide (or raise) as before
    try:
        reach = float(radius)
    except (TypeError, ValueError):
        return [True] * len(points)
    if not math.isfinite(reach):
        return [True] * len(points)
    if reach <= 0.0 or not points:
        return answers
    ids = map_geo.geo_ids_of_types(m_tensor, type_filter, MAX_ENTITIES)
    if not ids:
        return answers
    index = torch.tensor(ids, dtype=torch.long, device=m_tensor.device)
    ex = m_tensor[:, CX].index_select(0, index).double().cpu()
    ey = m_tensor[:, CY].index_select(0, index).double().cpu()
    if not (bool(torch.isfinite(ex).all()) and bool(torch.isfinite(ey).all())):
        return [True] * len(points)
    try:
        qx = torch.tensor([float(px) for px, _ in points], dtype=torch.float64)
        qy = torch.tensor([float(py) for _, py in points], dtype=torch.float64)
    except (TypeError, ValueError):
        return [True] * len(points)
    finite = (torch.isfinite(qx) & torch.isfinite(qy)).tolist()
    limit = (reach * (1.0 + PREFILTER_MARGIN) + PREFILTER_MARGIN) ** 2
    near = (((ex.unsqueeze(0) - qx.unsqueeze(1)) ** 2 + (ey.unsqueeze(0) - qy.unsqueeze(1)) ** 2) <= limit).any(dim=1).tolist()
    return [covered or not ok or bool(hit) for covered, ok, hit in zip(answers, finite, near)]


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

    survivors = _nearest_candidates(m_tensor, CX, CY, px, py, ids)      # R66-PACE-2: None = scan them all, as before
    best_entity_id = pick_best_entity(ids if survivors is None else survivors, _distance)
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

    slots = human_slots.tolist()
    survivors = _nearest_candidates(h_tensor, X, Y, px, py, slots)      # R66-PACE-2: None = scan them all, as before
    best_slot = pick_best_entity(slots if survivors is None else survivors, _distance)
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
    "nearest_geo_entity_possible",
    "nearest_human_from_mask",
    "point_distance",
]
