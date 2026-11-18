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
    from harness.numerics import pairwise_distances, space_slice
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.numerics import pairwise_distances, space_slice

import map_geo

try:
    from genesis_config import (
        CX,
        CY,
        FLOOD_HP_DAMAGE,
        H_SHELTER,
        HP,
        MAP_HEIGHT,
        MAP_WIDTH,
        MOOD,
        M_BARREN,
        M_BURNING,
        M_FLOODED,
        M_FOREST,
        M_HP,
        M_LAKE,
        M_LAVA,
        M_LAVA_COOLING,
        M_MOUNTAIN,
        M_RESOURCE_FOOD,
        M_SEA,
        M_TYPE,
        QUAKE_AGENT_DAMAGE,
        QUAKE_ENTITY_DAMAGE,
        QUAKE_RUBBLE_PROB,
        STORM_DISPLACEMENT,
        STORM_HP_DAMAGE,
        STORM_MOOD_PENALTY,
        STORM_THREAT_RAISE,
        THREAT,
        TYPE,
        VOLCANO_INNER_RADIUS,
        VOLCANO_LAVA_COOLING,
        VOLCANO_OUTER_RADIUS,
        X,
        Y,
    )
    from systems.health import apply_entity_damage, apply_human_damage, kill_humans
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        CX,
        CY,
        FLOOD_HP_DAMAGE,
        H_SHELTER,
        HP,
        MAP_HEIGHT,
        MAP_WIDTH,
        MOOD,
        M_BARREN,
        M_BURNING,
        M_FLOODED,
        M_FOREST,
        M_HP,
        M_LAKE,
        M_LAVA,
        M_LAVA_COOLING,
        M_MOUNTAIN,
        M_RESOURCE_FOOD,
        M_SEA,
        M_TYPE,
        QUAKE_AGENT_DAMAGE,
        QUAKE_ENTITY_DAMAGE,
        QUAKE_RUBBLE_PROB,
        STORM_DISPLACEMENT,
        STORM_HP_DAMAGE,
        STORM_MOOD_PENALTY,
        STORM_THREAT_RAISE,
        THREAT,
        TYPE,
        VOLCANO_INNER_RADIUS,
        VOLCANO_LAVA_COOLING,
        VOLCANO_OUTER_RADIUS,
        X,
        Y,
    )
    from at_the_beginning.systems.health import apply_entity_damage, apply_human_damage, kill_humans


AgentRadialMaskFn = Callable[[torch.Tensor, torch.Tensor, float, float, float, str], torch.Tensor]
EntityRadialIdsFn = Callable[[torch.Tensor, float, float, float], torch.Tensor]
FleeFn = Callable[..., Any]


def ignite_wildfire(
    m_tensor: torch.Tensor,
    center_x: float,
    center_y: float,
    radius: float,
    *,
    entity_radial_ids_fn: EntityRadialIdsFn,
) -> dict[str, Any]:
    """Ignite all forest entities within radius."""
    eids = entity_radial_ids_fn(m_tensor, center_x, center_y, radius)
    ignited = False
    for eid in eids.tolist():
        if int(m_tensor[eid, M_TYPE]) == M_FOREST:
            m_tensor[eid, M_BURNING] = 1.0
            m_tensor[eid, M_RESOURCE_FOOD] = 0.0
            ignited = True
    return {"map_dirty": ignited}


def apply_earthquake(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    device: str = "cpu",
    entity_radial_ids_fn: EntityRadialIdsFn,
    agent_radial_mask_fn: AgentRadialMaskFn,
    flee_fn: FleeFn | None = None,
) -> dict[str, Any]:
    """Damage nearby entities and humans, and convert some terrain to barren."""
    eids = entity_radial_ids_fn(m_tensor, center_x, center_y, radius)
    dirty = False
    if eids.numel():
        entity_mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
        entity_mask[eids] = True
        apply_entity_damage(entity_mask, m_tensor, QUAKE_ENTITY_DAMAGE, hp_col=M_HP)
        for eid in eids.tolist():
            et = int(m_tensor[eid, M_TYPE])
            if random.random() < QUAKE_RUBBLE_PROB and et not in {M_SEA, M_LAVA}:
                m_tensor[eid, M_TYPE] = float(M_BARREN)
                m_tensor[eid, M_RESOURCE_FOOD] = 0.0
                map_geo.geo_mutate(eid, device=device)
                dirty = True

    h_mask = ctx["h_mask"]
    quake_agents = agent_radial_mask_fn(h_tensor, h_mask, center_x, center_y, radius, device)
    if quake_agents.any():
        apply_human_damage(quake_agents, h_tensor, QUAKE_AGENT_DAMAGE, hp_col=HP)
        h_tensor[quake_agents, THREAT] = 100.0
        if flee_fn is not None:
            flee_fn(ctx, h_tensor, (center_x, center_y), flee_mask=quake_agents, device=device)
    return {"h_mask": h_tensor[:, TYPE] > 0, "map_dirty": dirty}


def apply_storm(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    device: str = "cpu",
    agent_radial_mask_fn: AgentRadialMaskFn,
) -> dict[str, Any]:
    """Displace humans in radius and damage unsheltered ones."""
    h_mask = ctx["h_mask"]
    storm_agents = agent_radial_mask_fn(h_tensor, h_mask, center_x, center_y, radius, device)
    if not storm_agents.any():
        return {}
    n = int(storm_agents.sum().item())
    dp = (torch.rand((n, 2), device=device) - 0.5) * STORM_DISPLACEMENT
    x0, y0, x1, y1 = _world_limits()
    h_tensor[storm_agents, X] = (h_tensor[storm_agents, X] + dp[:, 0]).clamp(x0, x1)
    h_tensor[storm_agents, Y] = (h_tensor[storm_agents, Y] + dp[:, 1]).clamp(y0, y1)
    unsheltered = storm_agents & (h_tensor[:, H_SHELTER] == 0.0)
    apply_human_damage(unsheltered, h_tensor, STORM_HP_DAMAGE, hp_col=HP)
    h_tensor[storm_agents, MOOD] -= STORM_MOOD_PENALTY
    clamp_rows_(h_tensor, storm_agents, MOOD, lo=0.0)
    h_tensor[storm_agents, THREAT] += STORM_THREAT_RAISE
    clamp_rows_(h_tensor, storm_agents, THREAT, hi=100.0)
    return {"h_mask": h_tensor[:, TYPE] > 0}


def apply_flood(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    device: str = "cpu",
    expand_radius: float = 100.0,
) -> dict[str, Any]:
    """Expand sea/lakes into adjacent land and damage humans on flooded tiles."""
    water = (m_tensor[:, M_TYPE] == M_SEA) | (m_tensor[:, M_TYPE] == M_LAKE)
    expandable = (
        (m_tensor[:, M_TYPE] != 0)
        & ~water
        & (m_tensor[:, M_TYPE] != M_MOUNTAIN)
        & (m_tensor[:, M_TYPE] != M_LAVA)
    )
    if not water.any() or not expandable.any():
        return {}
    w_pos = m_tensor[water][:, [CX, CY]]
    e_pos = m_tensor[expandable][:, [CX, CY]]
    dists = pairwise_distances(e_pos, w_pos, space_a=space_slice(m_tensor, expandable, "m"), space_b=space_slice(m_tensor, water, "m"))
    near = (dists < float(expand_radius)).any(dim=1)
    if not near.any():
        return {}
    e_idx = torch.where(expandable)[0]
    flood_tgt = e_idx[near]
    m_tensor[flood_tgt, M_TYPE] = float(M_SEA)
    m_tensor[flood_tgt, M_RESOURCE_FOOD] = 0.0
    m_tensor[flood_tgt, M_FLOODED] = 1.0
    for eid in flood_tgt.tolist():
        map_geo.geo_mutate(eid, device=device)

    h_mask = ctx["h_mask"]
    if h_mask.any():
        flooded_tiles: set[int] = set()
        for eid in flood_tgt.tolist():
            if eid in map_geo.MAP_GEO:
                flooded_tiles.update(map_geo.tiles_of(eid))
        if flooded_tiles:
            damage_mask = torch.zeros(h_tensor.shape[0], dtype=torch.bool, device=h_tensor.device)
            for slot in torch.where(h_mask)[0].tolist():
                tile_idx = map_geo._px_to_tile_idx(float(h_tensor[slot, X]), float(h_tensor[slot, Y]))
                if tile_idx in flooded_tiles:
                    damage_mask[slot] = True
            apply_human_damage(damage_mask, h_tensor, FLOOD_HP_DAMAGE * 10, hp_col=HP)
            h_tensor[damage_mask, THREAT] = 100.0
    return {"h_mask": h_tensor[:, TYPE] > 0, "map_dirty": True}


def apply_volcanic_eruption(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    pop_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    device: str = "cpu",
    entity_radial_ids_fn: EntityRadialIdsFn,
    agent_radial_mask_fn: AgentRadialMaskFn,
    flee_fn: FleeFn | None = None,
) -> dict[str, Any]:
    """Convert inner terrain to lava, ignite outer forests, kill inner humans, and flee outer humans."""
    inner_eids = entity_radial_ids_fn(m_tensor, center_x, center_y, VOLCANO_INNER_RADIUS)
    for eid in inner_eids.tolist():
        if int(m_tensor[eid, M_TYPE]) not in {M_SEA}:
            m_tensor[eid, M_TYPE] = float(M_LAVA)
            m_tensor[eid, M_RESOURCE_FOOD] = 0.0
            m_tensor[eid, M_LAVA_COOLING] = float(VOLCANO_LAVA_COOLING)
            map_geo.geo_mutate(eid, device=device)

    outer_eids = entity_radial_ids_fn(m_tensor, center_x, center_y, VOLCANO_OUTER_RADIUS)
    inner_set = set(inner_eids.tolist())
    for eid in outer_eids.tolist():
        if eid not in inner_set and int(m_tensor[eid, M_TYPE]) == M_FOREST:
            m_tensor[eid, M_BURNING] = 1.0

    h_mask = ctx["h_mask"]
    inner_agents = agent_radial_mask_fn(h_tensor, h_mask, center_x, center_y, VOLCANO_INNER_RADIUS, device)
    kill_humans(inner_agents, h_tensor, pop_count_ref)

    outer_agents = agent_radial_mask_fn(
        h_tensor,
        h_mask & ~inner_agents,
        center_x,
        center_y,
        VOLCANO_OUTER_RADIUS,
        device,
    )
    if outer_agents.any():
        h_tensor[outer_agents, THREAT] = 100.0
        if flee_fn is not None:
            flee_fn(ctx, h_tensor, (center_x, center_y), flee_mask=outer_agents, device=device)
    return {"h_mask": h_tensor[:, TYPE] > 0, "map_dirty": True}
