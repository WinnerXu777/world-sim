from __future__ import annotations

import random
from typing import Any, Callable

import torch
try:
    from harness.clamp import clamp_rows_
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.clamp import clamp_rows_
try:
    from harness.calendar import rate_scale as _rate
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.calendar import rate_scale as _rate

try:
    from genesis_config import (
        ANIMAL_TYPES,
        CX,
        CY,
        FARM_FOOD_GROWTH_RATE,
        FARM_WATER_USE_RATE,
        LAKE_WATER_REPLENISH_RATE,
        M_BEACH,
        M_BURNING,
        M_DEER,
        M_FARM,
        M_FERTILITY,
        M_FISH,
        M_FOREST,
        M_GRASS,
        M_GROWTH_RATE,
        M_LAKE,
        M_DEPLETED_TICK,
        M_NODE_CAP,
        M_NODE_KIND,
        M_NODE_STOCK,
        M_RESOURCE_FOOD,
        M_RESOURCE_NODE,
        M_RESOURCE_WATER,
        M_SHEEP,
        M_TIGER,
        M_TYPE,
        M_WELL,
        M_WOLF,
        MAX_ENTITIES,
        MAX_ENTITY_FOOD,
        MAX_ENTITY_WATER,
        NATURAL_TYPES,
        RESOURCE_REGROW_RATE,
        S_BUILD_PROGRESS,
        WELL_WATER_REPLENISH_RATE,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        ANIMAL_TYPES,
        CX,
        CY,
        FARM_FOOD_GROWTH_RATE,
        FARM_WATER_USE_RATE,
        LAKE_WATER_REPLENISH_RATE,
        M_BEACH,
        M_BURNING,
        M_DEER,
        M_FARM,
        M_FERTILITY,
        M_FISH,
        M_FOREST,
        M_GRASS,
        M_GROWTH_RATE,
        M_LAKE,
        M_DEPLETED_TICK,
        M_NODE_CAP,
        M_NODE_KIND,
        M_NODE_STOCK,
        M_RESOURCE_FOOD,
        M_RESOURCE_NODE,
        M_RESOURCE_WATER,
        M_SHEEP,
        M_TIGER,
        M_TYPE,
        M_WELL,
        M_WOLF,
        MAX_ENTITIES,
        MAX_ENTITY_FOOD,
        MAX_ENTITY_WATER,
        NATURAL_TYPES,
        RESOURCE_REGROW_RATE,
        S_BUILD_PROGRESS,
        WELL_WATER_REPLENISH_RATE,
    )


EDIBLE_NODE_KINDS = torch.tensor([1, 5, 7])   # berries, fish, mushrooms (systems/map/resources.py NODE_KIND_IDS)

SpawnAnimalGroupFn = Callable[..., dict[str, Any] | None]


def apply_resource_regrow(
    m_tensor: torch.Tensor,
    *,
    food_multiplier: float = 1.0,
    include_nodes: bool = True,
) -> None:
    """Fertile habitable entities slowly regenerate food. ``include_nodes=False``: resource nodes (G-005) are regrown elsewhere."""
    n = MAX_ENTITIES
    habitable = torch.zeros(n, dtype=torch.bool, device=m_tensor.device)
    for terrain_type in NATURAL_TYPES | {M_FARM, M_WELL}:
        habitable |= m_tensor[:n, M_TYPE] == float(terrain_type)
    fertile = habitable & (m_tensor[:n, M_FERTILITY] > 0)
    not_full = fertile & (m_tensor[:n, M_RESOURCE_FOOD] < MAX_ENTITY_FOOD)
    not_fire = not_full & (m_tensor[:n, M_BURNING] == 0)
    if not_fire.any():
        rate = (m_tensor[:n][not_fire, M_FERTILITY] / 100.0) * RESOURCE_REGROW_RATE * max(0.0, float(food_multiplier))
        m_tensor[:n][not_fire, M_RESOURCE_FOOD] += rate
        clamp_rows_(m_tensor[:n], not_fire, M_RESOURCE_FOOD, hi=MAX_ENTITY_FOOD)
    if include_nodes:
        apply_node_regrow(m_tensor, food_multiplier=food_multiplier)


def apply_water_cycle(
    m_tensor: torch.Tensor,
    *,
    water_multiplier: float = 1.0,
    farm_food_multiplier: float = 1.0,
) -> None:
    """Regenerate lakes/wells and grow irrigated farms."""
    n = MAX_ENTITIES
    water_scale = max(0.0, float(water_multiplier))
    farm_scale = max(0.0, float(farm_food_multiplier))

    lake_mask = m_tensor[:n, M_TYPE] == M_LAKE
    if lake_mask.any():
        empty_growth = lake_mask & (m_tensor[:n, M_GROWTH_RATE] <= 0.0)
        if empty_growth.any():
            m_tensor[:n][empty_growth, M_GROWTH_RATE] = LAKE_WATER_REPLENISH_RATE
        lake_gain = (
            m_tensor[:n][lake_mask, M_GROWTH_RATE]
            * m_tensor[:n][lake_mask, M_FERTILITY].clamp(min=25.0)
            / 100.0
            * water_scale
        )
        m_tensor[:n][lake_mask, M_RESOURCE_WATER] += lake_gain
        clamp_rows_(m_tensor[:n], lake_mask, M_RESOURCE_WATER, hi=MAX_ENTITY_WATER)

    well_mask = (m_tensor[:n, M_TYPE] == M_WELL) & (m_tensor[:n, S_BUILD_PROGRESS] >= 100.0)
    if well_mask.any():
        empty_growth = well_mask & (m_tensor[:n, M_GROWTH_RATE] <= 0.0)
        if empty_growth.any():
            m_tensor[:n][empty_growth, M_GROWTH_RATE] = WELL_WATER_REPLENISH_RATE
        m_tensor[:n][well_mask, M_RESOURCE_WATER] += m_tensor[:n][well_mask, M_GROWTH_RATE] * water_scale
        clamp_rows_(m_tensor[:n], well_mask, M_RESOURCE_WATER, hi=MAX_ENTITY_WATER)

    farm_mask = (m_tensor[:n, M_TYPE] == M_FARM) & (m_tensor[:n, S_BUILD_PROGRESS] >= 100.0)
    if farm_mask.any():
        empty_growth = farm_mask & (m_tensor[:n, M_GROWTH_RATE] <= 0.0)
        if empty_growth.any():
            m_tensor[:n][empty_growth, M_GROWTH_RATE] = FARM_FOOD_GROWTH_RATE
        irrigated = farm_mask & (m_tensor[:n, M_RESOURCE_WATER] > FARM_WATER_USE_RATE * _rate("regrow"))
        if irrigated.any():
            growth = (
                m_tensor[:n][irrigated, M_GROWTH_RATE]
                * (m_tensor[:n][irrigated, M_RESOURCE_WATER] / MAX_ENTITY_WATER).clamp(min=0.25)
                * farm_scale
            )
            m_tensor[:n][irrigated, M_RESOURCE_FOOD] += growth
            clamp_rows_(m_tensor[:n], irrigated, M_RESOURCE_FOOD, hi=MAX_ENTITY_FOOD)
            m_tensor[:n][irrigated, M_RESOURCE_WATER] -= FARM_WATER_USE_RATE * _rate("regrow")
            clamp_rows_(m_tensor[:n], irrigated, M_RESOURCE_WATER, lo=0.0)


def apply_node_regrow(m_tensor: torch.Tensor, *, food_multiplier: float = 1.0) -> None:
    """Resource nodes from authored maps (G-005) regrow ``growth_rate`` per tick up to their cap: edible nodes in the food
    column, material nodes in ``M_NODE_STOCK``. A node that was empty and recovers clears its depleted tick."""
    n = MAX_ENTITIES
    nodes = m_tensor[:n, M_TYPE] == float(M_RESOURCE_NODE)
    if not nodes.any():
        return
    live = nodes & (m_tensor[:n, M_BURNING] == 0) & (m_tensor[:n, M_GROWTH_RATE] > 0)
    if not live.any():
        return
    gain = m_tensor[:n][live, M_GROWTH_RATE] * max(0.0, float(food_multiplier))
    edible = torch.isin(m_tensor[:n][live, M_NODE_KIND].long(), EDIBLE_NODE_KINDS)
    rows = live.nonzero(as_tuple=False).flatten()
    cap = m_tensor[:n][live, M_NODE_CAP]
    for column, pick in ((M_RESOURCE_FOOD, edible), (M_NODE_STOCK, ~edible)):
        if pick.any():
            r = rows[pick]
            m_tensor[r, column] = torch.minimum(m_tensor[r, column] + gain[pick], cap[pick].clamp(min=0.0))
    recovered = live & (m_tensor[:n, M_DEPLETED_TICK] >= 0) & ((m_tensor[:n, M_RESOURCE_FOOD] > 0) | (m_tensor[:n, M_NODE_STOCK] > 0))
    m_tensor[:n][recovered, M_DEPLETED_TICK] = -1.0


def animal_population_summary(m_tensor: torch.Tensor) -> dict[str, int]:
    """Small ecology snapshot for prey/predator balancing."""
    n = MAX_ENTITIES
    return {
        "sheep": int((m_tensor[:n, M_TYPE] == M_SHEEP).sum().item()),
        "deer": int((m_tensor[:n, M_TYPE] == M_DEER).sum().item()),
        "fish": int((m_tensor[:n, M_TYPE] == M_FISH).sum().item()),
        "wolf": int((m_tensor[:n, M_TYPE] == M_WOLF).sum().item()),
        "tiger": int((m_tensor[:n, M_TYPE] == M_TIGER).sum().item()),
    }


def build_animal_mask(m_tensor: torch.Tensor) -> torch.Tensor:
    mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
    for animal_type in ANIMAL_TYPES:
        mask |= m_tensor[:, M_TYPE] == float(animal_type)
    return mask


def maybe_rebalance_ecology(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    tick: int,
    nature_state: dict[str, Any],
    device: str = "cpu",
    spawn_animal_group_fn: SpawnAnimalGroupFn | None = None,
) -> dict[str, Any]:
    """
    Lightweight ecology maintenance.

    First slice:
    - replenish land prey when predator pressure or overhunting empties them out
    - replenish fish in lakes when weather allows
    """
    if spawn_animal_group_fn is None:
        return {}

    next_tick = int(nature_state.get("next_ecology_tick", 0))
    if tick < next_tick:
        return {}

    nature_state["next_ecology_tick"] = tick + 120
    weather = str(nature_state.get("weather", "clear"))
    season = str(nature_state.get("season", "spring"))
    summary = animal_population_summary(m_tensor)

    spawned_records: list[dict[str, Any]] = []
    harsh_weather = weather in {"storm", "dry"}
    land_prey_total = summary["sheep"] + summary["deer"]
    predator_total = summary["wolf"] + summary["tiger"]
    prey_target = max(4, predator_total * 3)

    if not harsh_weather and land_prey_total < prey_target:
        land_slots = _candidate_entity_slots(m_tensor, {M_GRASS, M_FOREST, M_BEACH})
        if land_slots:
            anchor = random.choice(land_slots)
            species = M_DEER if season in {"spring", "summer"} else M_SHEEP
            count = 3 if season == "spring" else 2
            result = spawn_animal_group_fn(
                {},
                m_tensor,
                entity_count_ref,
                species=species,
                count=count,
                cx=float(m_tensor[anchor, CX]),
                cy=float(m_tensor[anchor, CY]),
                scatter=42.0,
                device=device,
            ) or {}
            spawned = int(result.get("spawned", 0))
            if spawned > 0:
                spawned_records.append({"species": int(species), "count": spawned, "biome_slot": int(anchor)})

    if weather not in {"dry", "heat"} and summary["fish"] < 4:
        lake_slots = _candidate_entity_slots(m_tensor, {M_LAKE})
        if lake_slots:
            anchor = random.choice(lake_slots)
            count = 5 if season == "spring" else 3
            result = spawn_animal_group_fn(
                {},
                m_tensor,
                entity_count_ref,
                species=M_FISH,
                count=count,
                cx=float(m_tensor[anchor, CX]),
                cy=float(m_tensor[anchor, CY]),
                scatter=24.0,
                device=device,
            ) or {}
            spawned = int(result.get("spawned", 0))
            if spawned > 0:
                spawned_records.append({"species": int(M_FISH), "count": spawned, "biome_slot": int(anchor)})

    if not spawned_records:
        return {}

    nature_state["last_ecology"] = {"tick": tick, "spawned": spawned_records}
    _append_history(
        nature_state,
        {
            "tick": tick,
            "kind": "ecology",
            "spawned": spawned_records,
        },
    )
    return {"a_mask": build_animal_mask(m_tensor), "frame_dirty": True}


def _candidate_entity_slots(m_tensor: torch.Tensor, allowed_types: set[int]) -> list[int]:
    mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
    for entity_type in allowed_types:
        mask |= m_tensor[:, M_TYPE] == float(entity_type)
    return torch.where(mask)[0].tolist()


def _append_history(nature_state: dict[str, Any], record: dict[str, Any]) -> None:
    history = list(nature_state.get("history", []))
    history.append(record)
    nature_state["history"] = history[-8:]
