from __future__ import annotations

from typing import Any

import torch
try:
    from harness.numerics import pairwise_distances, space_slice
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.numerics import pairwise_distances, space_slice

import map_geo

try:
    from genesis_config import (
        AGENT_TYPE_EMPTY,
        CX,
        CY,
        FIRE_BURN_TICKS,
        FIRE_HP_DAMAGE,
        FIRE_SPREAD_PROB,
        FIRE_SPREAD_RADIUS,
        HP,
        LAVA_HP_DAMAGE,
        M_BARREN,
        M_BURNING,
        M_FOREST,
        M_LAVA,
        M_LAVA_COOLING,
        M_RESOURCE_FOOD,
        M_TYPE,
        MAX_ENTITIES,
        SCALE,
        THREAT,
        TYPE,
        X,
        Y,
    )
    from systems.health import apply_human_damage
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        AGENT_TYPE_EMPTY,
        CX,
        CY,
        FIRE_BURN_TICKS,
        FIRE_HP_DAMAGE,
        FIRE_SPREAD_PROB,
        FIRE_SPREAD_RADIUS,
        HP,
        LAVA_HP_DAMAGE,
        M_BARREN,
        M_BURNING,
        M_FOREST,
        M_LAVA,
        M_LAVA_COOLING,
        M_RESOURCE_FOOD,
        M_TYPE,
        MAX_ENTITIES,
        SCALE,
        THREAT,
        TYPE,
        X,
        Y,
    )
    from at_the_beginning.systems.health import apply_human_damage


def _masked_positions_2d(tensor: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Return masked XY/CXCY positions as an explicit (N, 2) tensor."""
    return tensor[mask][:, [CX, CY]].reshape(-1, 2)


def apply_fire_tick(
    ctx: dict[str, Any],
    m_tensor: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    device: str = "cpu",
) -> dict[str, Any]:
    """Advance forest fires, spread them, and damage humans on burning tiles."""
    n = MAX_ENTITIES
    burning = (m_tensor[:n, M_BURNING] > 0) & (m_tensor[:n, M_TYPE] == M_FOREST)
    forest_only = (m_tensor[:n, M_TYPE] == M_FOREST) & ~burning
    dirty = False

    if not burning.any():
        return {}

    m_tensor[:n][burning, M_BURNING] += 1.0

    if forest_only.any():
        b_pos = _masked_positions_2d(m_tensor[:n], burning)
        f_pos = _masked_positions_2d(m_tensor[:n], forest_only)
        dists = pairwise_distances(f_pos, b_pos, space_a=space_slice(m_tensor[:n], forest_only, "m"),
                                   space_b=space_slice(m_tensor[:n], burning, "m"))
        close = (dists < FIRE_SPREAD_RADIUS).any(dim=1)
        if close.any():
            rolls = torch.rand(close.sum(), device=device)
            ignite = rolls < FIRE_SPREAD_PROB
            f_idx = torch.where(forest_only)[0]
            new_fire = f_idx[close][ignite]
            if new_fire.numel():
                m_tensor[new_fire, M_BURNING] = 1.0
                m_tensor[new_fire, M_RESOURCE_FOOD] = 0.0
                dirty = True

    burned_out = burning & (m_tensor[:n, M_BURNING] > FIRE_BURN_TICKS)
    if burned_out.any():
        for eid in torch.where(burned_out)[0].tolist():
            map_geo.unregister_entity(eid)
            map_geo.register_entity(
                eid,
                "circle",
                float(m_tensor[eid, CX]),
                float(m_tensor[eid, CY]),
                float(m_tensor[eid, SCALE]),
                device=device,
            )
        m_tensor[:n][burned_out, M_TYPE] = float(M_BARREN)
        m_tensor[:n][burned_out, M_BURNING] = 0.0
        m_tensor[:n][burned_out, M_RESOURCE_FOOD] = 0.0
        dirty = True

    h_mask = ctx["h_mask"]
    if h_mask.any():
        burn_ids = torch.where((m_tensor[:n, M_BURNING] > 0) & (m_tensor[:n, M_TYPE] == M_FOREST))[0].tolist()
        all_fire_tiles: set[int] = set()
        for eid in burn_ids:
            if eid in map_geo.MAP_GEO:
                all_fire_tiles.update(map_geo.tiles_of(eid))
        for slot in torch.where(h_mask)[0].tolist():
            tile_idx = map_geo._px_to_tile_idx(float(h_tensor[slot, X]), float(h_tensor[slot, Y]))
            if tile_idx in all_fire_tiles:
                damage_mask = torch.zeros(h_tensor.shape[0], dtype=torch.bool, device=h_tensor.device)
                damage_mask[slot] = True
                apply_human_damage(damage_mask, h_tensor, FIRE_HP_DAMAGE, hp_col=HP)
                h_tensor[slot, THREAT] = 100.0

    return {"h_mask": h_tensor[:, TYPE] > AGENT_TYPE_EMPTY, "map_dirty": dirty}


def apply_lava_tick(
    ctx: dict[str, Any],
    m_tensor: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    device: str = "cpu",
) -> dict[str, Any]:
    """Cool lava back to barren terrain and damage humans on lava tiles."""
    n = MAX_ENTITIES
    lava = m_tensor[:n, M_TYPE] == M_LAVA
    if not lava.any():
        return {}

    dirty = False
    m_tensor[:n][lava, M_LAVA_COOLING] -= 1.0
    cooled = lava & (m_tensor[:n, M_LAVA_COOLING] <= 0)
    if cooled.any():
        for eid in torch.where(cooled)[0].tolist():
            map_geo.geo_mutate(eid, device=device)
        m_tensor[:n][cooled, M_TYPE] = float(M_BARREN)
        m_tensor[:n][cooled, M_LAVA_COOLING] = 0.0
        dirty = True

    h_mask = ctx["h_mask"]
    if h_mask.any():
        lava_tiles: set[int] = set()
        for eid in torch.where(lava)[0].tolist():
            if eid in map_geo.MAP_GEO:
                lava_tiles.update(map_geo.tiles_of(eid))
        for slot in torch.where(h_mask)[0].tolist():
            tile_idx = map_geo._px_to_tile_idx(float(h_tensor[slot, X]), float(h_tensor[slot, Y]))
            if tile_idx in lava_tiles:
                damage_mask = torch.zeros(h_tensor.shape[0], dtype=torch.bool, device=h_tensor.device)
                damage_mask[slot] = True
                apply_human_damage(damage_mask, h_tensor, LAVA_HP_DAMAGE, hp_col=HP)

    return {"h_mask": h_tensor[:, TYPE] > AGENT_TYPE_EMPTY, "map_dirty": dirty}
