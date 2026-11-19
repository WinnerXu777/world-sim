"""
instincts_and_tools.py
======================
All Tier 0 instincts, Tier 1 tools, animal instincts, and primitives.

Key architectural change vs tile-grid version
─────────────────────────────────────────────
m_tensor is now an ENTITY REGISTRY (1024 rows), not a tile grid.
Spatial queries use two strategies:

  1. "Which entity is this agent standing in?"
     → map_geo.entity_at(ax, ay)  — O(1) TILE_TO_ENTITY dict lookup
     Used by: instinct_eat, instinct_shelter_check, lava/fire damage

  2. "Which entities are near this point?"
     → map_geo.entities_in_radius(cx, cy, r, m_tensor)  — iterates MAP_GEO
     Used by: tools (wildfire, earthquake, flood) — not the hot loop

  3. "Are two agents near each other?"
     → instinct_proximity — cdist on h_tensor[:, :2]  — unchanged

Fire/flood spread uses entity-to-entity cdist (entity CX/CY positions),
not the grid max-pool that the tile version used.

Mobile entities (animals) have CX/CY updated each tick.
Area entities (lakes, forests) have static CX/CY unless geo_mutate is called.

Map-mutation contract
─────────────────────
Any function that changes m_tensor M_TYPE or geometry must:
  1. Mutate m_tensor attributes directly.
  2. Call map_geo.unregister_entity / geo_mutate if shape changed.
  3. Return {"map_dirty": True} so Engine rebuilds the JSON snapshot.
"""

import math
import random
from typing import Any, Callable
import torch
try:
    from harness.clamp import clamp_rows_
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.clamp import clamp_rows_
try:
    from harness import calendar as _calendar
    from harness import instinct_bits
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness import calendar as _calendar
    from at_the_beginning.harness import instinct_bits
_rate = _calendar.rate_scale
try:
    from systems.creatures import enabled as _creatures_enabled
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.creatures import enabled as _creatures_enabled
try:
    from harness.numerics import pairwise_distances, space_slice
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.numerics import pairwise_distances, space_slice

import map_geo
try:
    from systems.combat.hunting import huntable_animal_slots, nearest_predator_target
    from systems.combat.manual import collect_manual_attack_intents
    from systems.combat.resolver import resolve_human_attack_intents
    from systems.movement.spatial import map_wall_boxes
    from systems.combat.sim import collect_sim_attack_intents, collect_sim_hunt_intents
    from systems.construction import (
        build_with_humans as construction_build_with_humans,
        designate_construction_site as construction_designate_construction_site,
        demolish_with_humans as construction_demolish_with_humans,
        find_buildable_site as construction_find_buildable_site,
        gather_materials as construction_gather_materials,
        repair_with_humans as construction_repair_with_humans,
        resolve_build_site as construction_resolve_build_site,
        spawn_structure_entity as construction_spawn_structure_entity,
        structure_blueprint as construction_structure_blueprint,
        tool_build_structure_with_humans as construction_tool_build_structure_with_humans,
        tool_build_structure as construction_tool_build_structure,
        tool_build_settlement as construction_tool_build_settlement,
        tool_build_settlement_with_humans as construction_tool_build_settlement_with_humans,
        tool_construct_wall_with_humans as construction_tool_construct_wall_with_humans,
        tool_demolish_area_with_humans as construction_tool_demolish_area_with_humans,
        tool_designate_structure_site as construction_tool_designate_structure_site,
        tool_find_buildable_site as construction_tool_find_buildable_site,
        tool_repair_area_with_humans as construction_tool_repair_area_with_humans,
        tool_repair_structures as construction_tool_repair_structures,
    )
    from systems.perception import (
        agent_radial_mask as _agent_radial_mask,
        best_resource_entity as _best_resource_entity,
        best_safe_entity as _best_safe_entity,
        entity_radial_ids as _entity_radial_ids,
        entity_unit_vector as _entity_unit_vector,
        nearest_entity_from_ids as _nearest_entity_from_ids,
        nearest_geo_entity as _nearest_geo_entity,
    )
    from systems.movement.manual import (
        apply_manual_control_movement,
        build_manual_control_context,
    )
    from systems.movement.sim import apply_navigation_bias
    from systems.health import (
        apply_area_attack_effect,
        apply_bless_effect,
        apply_entity_damage,
        apply_heal_tick,
        apply_human_damage,
        apply_infection_tick,
        kill_humans,
        apply_plague_effect,
    )
    from systems.survival.hunger import (
        apply_hunger_tick,
        eat_from_current_entity,
    )
    from systems.survival.navigation import build_survival_navigation_bias
    from systems.survival.shelter import (
        sync_structure_occupancy,
        update_shelter_flags,
    )
    from systems.survival.thirst import (
        apply_thirst_tick,
        drink_from_nearby_entity,
    )
    from systems.social.grouping import (
        apply_emotional_recovery,
        build_pairwise_relations,
        build_social_navigation_bias,
    )
    from systems.social.mating import (
        apply_cooldown_decay,
        build_seek_mask,
        resolve_human_reproduction,
        restrict_reproduction_seek,
    )
    from systems.schedule import build_schedule_navigation_bias
    from systems.map import (
        create_feature_near_feature as map_create_feature_near_feature,
        create_forest_patch_feature,
        create_lake_feature,
        create_mountain_chain_feature,
        create_settlement_area,
        create_wall_feature,
        expand_world_edge as map_expand_world_edge,
        maybe_expand_frontier,
        transform_map_area,
    )
    from systems.nature import (
        apply_earthquake as nature_apply_earthquake,
        apply_flood as nature_apply_flood,
        advance_nature_cycle as nature_advance_cycle,
        apply_fire_tick as nature_apply_fire_tick,
        apply_lava_tick as nature_apply_lava_tick,
        apply_resource_regrow as nature_apply_resource_regrow,
        apply_storm as nature_apply_storm,
        apply_volcanic_eruption as nature_apply_volcanic_eruption,
        apply_water_cycle as nature_apply_water_cycle,
        ignite_wildfire as nature_ignite_wildfire,
        maybe_rebalance_ecology as nature_maybe_rebalance_ecology,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.combat.hunting import huntable_animal_slots, nearest_predator_target
    from at_the_beginning.systems.combat.manual import collect_manual_attack_intents
    from at_the_beginning.systems.combat.resolver import resolve_human_attack_intents
    from at_the_beginning.systems.movement.spatial import map_wall_boxes
    from at_the_beginning.systems.combat.sim import collect_sim_attack_intents, collect_sim_hunt_intents
    from at_the_beginning.systems.construction import (
        build_with_humans as construction_build_with_humans,
        designate_construction_site as construction_designate_construction_site,
        demolish_with_humans as construction_demolish_with_humans,
        find_buildable_site as construction_find_buildable_site,
        gather_materials as construction_gather_materials,
        repair_with_humans as construction_repair_with_humans,
        resolve_build_site as construction_resolve_build_site,
        spawn_structure_entity as construction_spawn_structure_entity,
        structure_blueprint as construction_structure_blueprint,
        tool_build_structure_with_humans as construction_tool_build_structure_with_humans,
        tool_build_structure as construction_tool_build_structure,
        tool_build_settlement as construction_tool_build_settlement,
        tool_build_settlement_with_humans as construction_tool_build_settlement_with_humans,
        tool_construct_wall_with_humans as construction_tool_construct_wall_with_humans,
        tool_demolish_area_with_humans as construction_tool_demolish_area_with_humans,
        tool_designate_structure_site as construction_tool_designate_structure_site,
        tool_find_buildable_site as construction_tool_find_buildable_site,
        tool_repair_area_with_humans as construction_tool_repair_area_with_humans,
        tool_repair_structures as construction_tool_repair_structures,
    )
    from at_the_beginning.systems.perception import (
        agent_radial_mask as _agent_radial_mask,
        best_resource_entity as _best_resource_entity,
        best_safe_entity as _best_safe_entity,
        entity_radial_ids as _entity_radial_ids,
        entity_unit_vector as _entity_unit_vector,
        nearest_entity_from_ids as _nearest_entity_from_ids,
        nearest_geo_entity as _nearest_geo_entity,
    )
    from at_the_beginning.systems.movement.manual import (
        apply_manual_control_movement,
        build_manual_control_context,
    )
    from at_the_beginning.systems.movement.sim import apply_navigation_bias
    from at_the_beginning.systems.health import (
        apply_area_attack_effect,
        apply_bless_effect,
        apply_entity_damage,
        apply_heal_tick,
        apply_human_damage,
        apply_infection_tick,
        kill_humans,
        apply_plague_effect,
    )
    from at_the_beginning.systems.survival.hunger import (
        apply_hunger_tick,
        eat_from_current_entity,
    )
    from at_the_beginning.systems.survival.navigation import build_survival_navigation_bias
    from at_the_beginning.systems.survival.shelter import (
        sync_structure_occupancy,
        update_shelter_flags,
    )
    from at_the_beginning.systems.survival.thirst import (
        apply_thirst_tick,
        drink_from_nearby_entity,
    )
    from at_the_beginning.systems.social.grouping import (
        apply_emotional_recovery,
        build_pairwise_relations,
        build_social_navigation_bias,
    )
    from at_the_beginning.systems.social.mating import (
        apply_cooldown_decay,
        build_seek_mask,
        resolve_human_reproduction,
        restrict_reproduction_seek,
    )
    from at_the_beginning.systems.schedule import build_schedule_navigation_bias
    from at_the_beginning.systems.map import (
        create_feature_near_feature as map_create_feature_near_feature,
        create_forest_patch_feature,
        create_lake_feature,
        create_mountain_chain_feature,
        create_settlement_area,
        create_wall_feature,
        expand_world_edge as map_expand_world_edge,
        maybe_expand_frontier,
        transform_map_area,
    )
    from at_the_beginning.systems.nature import (
        apply_earthquake as nature_apply_earthquake,
        apply_flood as nature_apply_flood,
        advance_nature_cycle as nature_advance_cycle,
        apply_fire_tick as nature_apply_fire_tick,
        apply_lava_tick as nature_apply_lava_tick,
        apply_resource_regrow as nature_apply_resource_regrow,
        apply_storm as nature_apply_storm,
        apply_volcanic_eruption as nature_apply_volcanic_eruption,
        apply_water_cycle as nature_apply_water_cycle,
        ignite_wildfire as nature_ignite_wildfire,
        maybe_rebalance_ecology as nature_maybe_rebalance_ecology,
    )
from genesis_config import (
    # grid geometry (for background tile lookups)
    MAP_WIDTH, MAP_HEIGHT, TILE_SIZE, GRID_W, GRID_H,
    MAX_BG_TILES, MAX_ENTITIES, MAX_HUMANS,
    # timing
    TICKS_PER_YEAR,
    # movement
    MOVE_STEP, ATTRACTION_FORCE,
    # h_tensor cols
    X, Y, TYPE, HP,
    H_STRENGTH, H_FERTILITY, H_AGGRESSION, H_STAMINA, H_INFECTION, H_SHELTER,
    H_SEX, H_AGE, H_LIFE_EXP, H_COOLDOWN,
    HUNGER, THREAT, MOOD, CRITICAL_HEALTH, ESCALATION_FLAG,
    ACQUIRED_INSTINCT_MASK,
    H_CARRYING, H_SKILL, H_TRIBE, H_PARENT_INSTINCTS, THIRST,
    # m_tensor cols – shared
    CX, CY, M_TYPE, M_HP, SCALE, SPRITE_ID, M_GEN,
    # m_tensor cols – natural feature state
    M_FERTILITY, M_ELEVATION, M_BURNING, M_FLOODED,
    # m_tensor cols – animal life
    A_AGE, A_LIFE_EXP, A_SEX, A_COOLDOWN, A_HUNGER, A_AGGRESSION, A_THIRST,
    # m_tensor cols – structure state
    S_DURABILITY, S_SHELTER_CAP, S_OCCUPANT_COUNT, S_BUILD_PROGRESS,
    # resource col
    M_RESOURCE_FOOD, M_LAVA_COOLING, M_RESOURCE_WATER, M_GROWTH_RATE,
    # M_TYPE constants
    M_LAKE, M_FOREST, M_SEA, M_MOUNTAIN, M_BEACH, M_GRASS,
    M_LAVA, M_BARREN, M_HOUSE, M_VILLAGE, M_FARM, M_WELL, M_WALL, M_RESOURCE_NODE,
    M_SHEEP, M_DEER, M_TIGER, M_WOLF, M_FISH,
    NATURAL_TYPES, STRUCTURE_TYPES, ANIMAL_TYPES, IMPASSABLE, HABITABLE,
    # agent type
    AGENT_TYPE_EMPTY, AGENT_TYPE_HUMAN,
    # human thresholds
    ESCALATION_THRESHOLD, MATURE_AGE,
    PROXIMITY_MATE_RADIUS, PROXIMITY_THREAT_RADIUS,
    COOLDOWN_DECAY_RATE, HUNGER_TICK_RATE, THIRST_TICK_RATE,
    THIRST_DAMAGE_RATE, CRITICAL_HEALTH_THRESHOLD,
    AGGRESSION_THRESHOLD, ATTACK_RANGE, ATTACK_DAMAGE, ATTACK_STAMINA_COST,
    HEAL_RATE, STAMINA_RECOVER_RATE, STAMINA_DRAIN_MOVE,
    SAFE_REPRO_HUNGER_MAX, SAFE_REPRO_THIRST_MAX, SAFE_REPRO_THREAT_MAX,
    SAFE_REPRO_HP_MIN, SAFE_REPRO_STAMINA_MIN,
    SURVIVAL_SCAN_RADIUS, MIGRATION_SCAN_RADIUS, HAZARD_AVOID_RADIUS,
    PREDATOR_ALERT_RADIUS, FOOD_SEEK_THRESHOLD, WATER_SEEK_THRESHOLD,
    SHELTER_SEEK_THREAT, SURVIVAL_NAV_WEIGHT, HAZARD_FLEE_WEIGHT,
    SOCIAL_NAV_WEIGHT, TRIBE_COHESION_RADIUS, CROWDING_RADIUS,
    CROWDING_LIMIT, THREAT_DECAY_RATE, MOOD_RECOVERY_RATE,
    INFECTION_SPREAD_RADIUS, INFECTION_SPREAD_RATE,
    INFECTION_DAMAGE_RATE, INFECTION_THRESHOLD, INFECTION_NATURAL_DECAY,
    QUARANTINE_COOLDOWN_YRS,
    # resource
    EAT_HUNGER_RESTORE, EAT_RESOURCE_COST,
    RESOURCE_REGROW_RATE, MAX_ENTITY_FOOD,
    INITIAL_FOOD_GRASS, INITIAL_FOOD_FOREST, INITIAL_FOOD_BEACH, INITIAL_FOOD_LAKE,
    DRINK_THIRST_RESTORE, DRINK_RESOURCE_COST, DRINK_PROXIMITY_RADIUS,
    MAX_ENTITY_WATER, LAKE_WATER_REPLENISH_RATE, WELL_WATER_REPLENISH_RATE,
    FARM_FOOD_GROWTH_RATE, FARM_WATER_USE_RATE,
    INITIAL_WATER_LAKE, INITIAL_WATER_WELL, INITIAL_WATER_FARM,
    BUILD_SITE_HP_FRACTION, BUILD_PROGRESS_PER_HUMAN, BUILD_STAMINA_COST,
    BUILD_SKILL_GAIN, BUILD_MOOD_GAIN, BUILD_RADIUS, BUILD_MIN_STAMINA,
    BUILD_MATERIAL_USE, GATHER_MATERIAL_AMOUNT, GATHER_STAMINA_COST,
    MAX_CARRYING_MATERIAL, REPAIR_RATE_PER_HUMAN, DEMOLISH_RATE_PER_HUMAN,
    DEMOLISH_STAMINA_COST, SALVAGE_RETURN_FRACTION,
    # fire
    FIRE_SPREAD_RADIUS, FIRE_SPREAD_PROB, FIRE_HP_DAMAGE, FIRE_BURN_TICKS,
    # flood
    FLOOD_HP_DAMAGE, FLOOD_EXPAND_PROB,
    # storm / quake / volcano
    STORM_DISPLACEMENT, STORM_HP_DAMAGE, STORM_MOOD_PENALTY, STORM_THREAT_RAISE,
    QUAKE_ENTITY_DAMAGE, QUAKE_AGENT_DAMAGE, QUAKE_RUBBLE_PROB,
    VOLCANO_INNER_RADIUS, VOLCANO_OUTER_RADIUS, VOLCANO_LAVA_COOLING, LAVA_HP_DAMAGE,
    # animal params
    ANIMAL_LIFE_EXP, ANIMAL_SCALE, ANIMAL_BASE_AGGRESSION,
    ANIMAL_MOVE_STEP, ANIMAL_PREY,
    ANIMAL_PREDATOR_ATTACK_DAMAGE, ANIMAL_PREDATOR_RANGE,
    ANIMAL_HUNGER_TICK_RATE, ANIMAL_THIRST_TICK_RATE,
    ANIMAL_MATE_RADIUS, ANIMAL_MATURE_TICKS,
    # genesis
    LIFE_EXP_MIN, LIFE_EXP_MAX,
    # natural feature scale
    NATURAL_SCALE,
)


DRINKABLE_TYPES = {M_LAKE, M_WELL}
BUILD_BLOCKED_TYPES = {M_SEA, M_LAKE, M_MOUNTAIN, M_LAVA}
FARMABLE_BASE_TYPES = {M_GRASS, M_FOREST, M_BARREN, M_BEACH}
FOOD_SOURCE_TYPES = {M_GRASS, M_FOREST, M_BEACH, M_LAKE, M_FARM, M_RESOURCE_NODE}


try:
    from harness.limits import world_limits as _world_limits
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.limits import world_limits as _world_limits


def _clamp_point(x: float, y: float) -> tuple[float, float]:
    x0, y0, x1, y1 = _world_limits()
    return (
        max(x0, min(x1, x)),
        max(y0, min(y1, y)),
    )


def _make_wall_polygon(start_x: float, start_y: float,
                       end_x: float, end_y: float,
                       thickness: float) -> list[tuple[float, float]]:
    dx = end_x - start_x
    dy = end_y - start_y
    norm = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    px = -dy / norm
    py = dx / norm
    half = thickness / 2.0
    p1 = _clamp_point(start_x + px * half, start_y + py * half)
    p2 = _clamp_point(start_x - px * half, start_y - py * half)
    p3 = _clamp_point(end_x - px * half, end_y - py * half)
    p4 = _clamp_point(end_x + px * half, end_y + py * half)
    return [p1, p2, p3, p4]


def instinct_create_object(m_tensor: torch.Tensor,
                           entity_count_ref: list,
                           object_type: int,
                           center_x: float, center_y: float,
                           hp: float = 100.0,
                           scale: float = 20.0,
                           shape: str = "circle",
                           points: list[tuple[float, float]] | None = None,
                           register_geo: bool = True,
                           device: str = "cpu",
                           col_vals: dict[int, float] | None = None) -> int:
    """
    Low-level object creation primitive used by higher-level build/mutate tools.
    Supports both circle and polygon geometry.
    """
    eid = entity_born(
        m_tensor, entity_count_ref, center_x, center_y, object_type,
        hp=hp, scale=scale, register_geo=False, device=device, col_vals=col_vals,
    )
    if eid == -1:
        return -1
    if register_geo:
        if shape == "polygon" and points:
            map_geo.register_entity(
                eid, "polygon", center_x, center_y, scale,
                points=points, device=device,
            )
        else:
            map_geo.register_entity(
                eid, "circle", center_x, center_y, scale, device=device
            )
    return eid


def instinct_populate_animals(m_tensor: torch.Tensor,
                              entity_count_ref: list,
                              species: int,
                              count: int,
                              center_x: float | None = None,
                              center_y: float | None = None,
                              radius: float | None = None,
                              candidate_entity_ids: list[int] | None = None,
                              allowed_types: set[int] | None = None,
                              scatter: float = 30.0,
                              device: str = "cpu") -> list[int]:
    """
    Low-level animal population primitive.
    Tools can drive it via a point/radius, explicit candidate entities,
    or a biome-type filter.
    """
    if count <= 0:
        return []

    if candidate_entity_ids is None:
        candidate_entity_ids = []
        if allowed_types is not None:
            for eid in map_geo.MAP_GEO.keys():
                if int(m_tensor[eid, M_TYPE]) in allowed_types:
                    candidate_entity_ids.append(int(eid))

    spawn_points: list[tuple[float, float]] = []
    if candidate_entity_ids:
        for _ in range(count):
            anchor = random.choice(candidate_entity_ids)
            ex = float(m_tensor[anchor, CX])
            ey = float(m_tensor[anchor, CY])
            er = max(6.0, float(m_tensor[anchor, SCALE]) * 0.6)
            angle = random.random() * math.tau
            dist = random.random() * min(scatter, er)
            spawn_points.append(_clamp_point(
                ex + math.cos(angle) * dist,
                ey + math.sin(angle) * dist,
            ))
    elif center_x is not None and center_y is not None:
        span = scatter if radius is None else radius
        for _ in range(count):
            angle = random.random() * math.tau
            dist = random.random() * max(1.0, span)
            spawn_points.append(_clamp_point(
                center_x + math.cos(angle) * dist,
                center_y + math.sin(angle) * dist,
            ))
    else:
        return []

    spawned: list[int] = []
    for ax, ay in spawn_points:
        eid = animal_born(
            m_tensor, entity_count_ref, ax, ay, species, device=device
        )
        if eid != -1:
            spawned.append(eid)
    return spawned


def instinct_update_objects(m_tensor: torch.Tensor,
                            entity_ids: list[int] | torch.Tensor,
                            set_cols: dict[int, float] | None = None,
                            add_cols: dict[int, float] | None = None,
                            clamp_cols: dict[int, tuple[float | None, float | None]] | None = None
                            ) -> int:
    """
    Generic low-level object state mutator.
    """
    if isinstance(entity_ids, torch.Tensor):
        ids = entity_ids.tolist()
    else:
        ids = list(entity_ids)
    if not ids:
        return 0

    changed = 0
    for eid in ids:
        if int(m_tensor[eid, M_TYPE]) == 0:
            continue
        if set_cols:
            for col, value in set_cols.items():
                m_tensor[eid, int(col)] = float(value)
        if add_cols:
            for col, value in add_cols.items():
                m_tensor[eid, int(col)] += float(value)
        if clamp_cols:
            for col, (min_v, max_v) in clamp_cols.items():
                if min_v is not None:
                    m_tensor[eid, int(col)] = max(float(min_v), float(m_tensor[eid, int(col)]))
                if max_v is not None:
                    m_tensor[eid, int(col)] = min(float(max_v), float(m_tensor[eid, int(col)]))
        changed += 1
    return changed


def instinct_retype_objects(m_tensor: torch.Tensor,
                            entity_ids: list[int] | torch.Tensor,
                            new_type: int,
                            device: str = "cpu",
                            col_vals: dict[int, float] | None = None) -> int:
    """
    Generic low-level object type transform while preserving geometry.
    """
    if isinstance(entity_ids, torch.Tensor):
        ids = entity_ids.tolist()
    else:
        ids = list(entity_ids)
    if not ids:
        return 0

    changed = 0
    for eid in ids:
        if int(m_tensor[eid, M_TYPE]) == 0:
            continue
        m_tensor[eid, M_TYPE] = float(new_type)
        if col_vals:
            for col, value in col_vals.items():
                m_tensor[eid, int(col)] = float(value)
        if eid in map_geo.MAP_GEO:
            map_geo.geo_mutate(eid, device=device)
        changed += 1
    return changed


def instinct_create_scattered_objects(m_tensor: torch.Tensor,
                                      entity_count_ref: list,
                                      object_type: int,
                                      count: int,
                                      center_x: float, center_y: float,
                                      radius: float,
                                      scale_min: float,
                                      scale_max: float,
                                      hp: float = 100.0,
                                      device: str = "cpu",
                                      col_vals_factory: Callable | None = None
                                      ) -> list[int]:
    """
    Generic low-level scatter creator for circular objects.
    """
    created: list[int] = []
    if count <= 0:
        return created

    for _ in range(count):
        angle = random.random() * math.tau
        dist = random.random() * max(1.0, radius)
        cx, cy = _clamp_point(
            center_x + math.cos(angle) * dist,
            center_y + math.sin(angle) * dist,
        )
        scale = random.uniform(scale_min, scale_max)
        col_vals = col_vals_factory(cx, cy, scale) if col_vals_factory else None
        eid = instinct_create_object(
            m_tensor, entity_count_ref, object_type,
            cx, cy,
            hp=hp, scale=scale,
            shape="circle", register_geo=True,
            device=device, col_vals=col_vals,
        )
        if eid != -1:
            created.append(eid)
    return created


def instinct_create_line_objects(m_tensor: torch.Tensor,
                                 entity_count_ref: list,
                                 object_type: int,
                                 start_x: float, start_y: float,
                                 end_x: float, end_y: float,
                                 segments: int,
                                 scale: float,
                                 hp: float = 100.0,
                                 device: str = "cpu",
                                 col_vals_factory: Callable | None = None
                                 ) -> list[int]:
    """
    Generic low-level line creator for repeated circular objects.
    """
    created: list[int] = []
    segments = max(1, int(segments))
    for idx in range(segments):
        t = 0.0 if segments == 1 else idx / (segments - 1)
        cx, cy = _clamp_point(
            start_x + (end_x - start_x) * t,
            start_y + (end_y - start_y) * t,
        )
        col_vals = col_vals_factory(idx, cx, cy) if col_vals_factory else None
        eid = instinct_create_object(
            m_tensor, entity_count_ref, object_type,
            cx, cy,
            hp=hp, scale=scale,
            shape="circle", register_geo=True,
            device=device, col_vals=col_vals,
        )
        if eid != -1:
            created.append(eid)
    return created


def instinct_relocate_animals(m_tensor: torch.Tensor,
                              entity_ids: list[int] | torch.Tensor,
                              target_x: float, target_y: float,
                              force: float = 20.0,
                              toward: bool = True) -> int:
    """
    Generic low-level animal relocation primitive.
    """
    if isinstance(entity_ids, torch.Tensor):
        ids = entity_ids.tolist()
    else:
        ids = list(entity_ids)
    if not ids:
        return 0

    moved = 0
    for eid in ids:
        if int(m_tensor[eid, M_TYPE]) not in ANIMAL_TYPES:
            continue
        dx = target_x - float(m_tensor[eid, CX])
        dy = target_y - float(m_tensor[eid, CY])
        if not toward:
            dx *= -1.0
            dy *= -1.0
        norm = max((dx * dx + dy * dy) ** 0.5, 1e-6)
        nx = float(m_tensor[eid, CX]) + (dx / norm) * force
        ny = float(m_tensor[eid, CY]) + (dy / norm) * force
        m_tensor[eid, CX], m_tensor[eid, CY] = _clamp_point(nx, ny)
        moved += 1
    return moved


def instinct_designate_construction_site(m_tensor: torch.Tensor,
                                         entity_count_ref: list,
                                         structure_type: int,
                                         center_x: float, center_y: float,
                                         scale: float,
                                         durability: float,
                                         shelter_cap: float = 0.0,
                                         build_progress: float = 0.0,
                                         shape: str = "circle",
                                         points: list[tuple[float, float]] | None = None,
                                         device: str = "cpu",
                                         extra_cols: dict[int, float] | None = None) -> int:
    """
    Low-level construction-site primitive. The entity exists on the map
    immediately, but humans still need to raise build_progress to finish it.
    """
    return construction_designate_construction_site(
        m_tensor,
        entity_count_ref,
        structure_type,
        center_x,
        center_y,
        scale=scale,
        durability=durability,
        shelter_cap=shelter_cap,
        build_progress=build_progress,
        shape=shape,
        points=points,
        device=device,
        extra_cols=extra_cols,
        create_object_fn=instinct_create_object,
    )


def instinct_gather_materials(ctx: dict, h_tensor: torch.Tensor,
                              m_tensor: torch.Tensor,
                              center_x: float, center_y: float,
                              radius: float = BUILD_RADIUS,
                              amount: float = GATHER_MATERIAL_AMOUNT,
                              builder_mask: torch.Tensor | None = None,
                              source_types: set[int] | None = None,
                              device: str = "cpu", **_) -> dict:
    """
    Low-level human + map primitive for collecting abstract build materials.
    """
    return construction_gather_materials(
        ctx,
        h_tensor,
        m_tensor,
        center_x,
        center_y,
        radius=radius,
        amount=amount,
        builder_mask=builder_mask,
        source_types=source_types,
        device=device,
    )


def instinct_build_with_humans(ctx: dict, h_tensor: torch.Tensor,
                               m_tensor: torch.Tensor,
                               target_entity_ids: list[int] | torch.Tensor,
                               builder_mask: torch.Tensor | None = None,
                               build_radius: float = BUILD_RADIUS,
                               progress_per_human: float = BUILD_PROGRESS_PER_HUMAN,
                               stamina_cost: float = BUILD_STAMINA_COST,
                               material_use: float = BUILD_MATERIAL_USE,
                               device: str = "cpu", **_) -> dict:
    """
    Low-level construction primitive that changes both human state and map state.
    """
    return construction_build_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        target_entity_ids,
        builder_mask=builder_mask,
        build_radius=build_radius,
        progress_per_human=progress_per_human,
        stamina_cost=stamina_cost,
        material_use=material_use,
        device=device,
    )


def instinct_repair_with_humans(ctx: dict, h_tensor: torch.Tensor,
                                m_tensor: torch.Tensor,
                                target_entity_ids: list[int] | torch.Tensor,
                                builder_mask: torch.Tensor | None = None,
                                repair_radius: float = BUILD_RADIUS,
                                repair_rate: float = REPAIR_RATE_PER_HUMAN,
                                device: str = "cpu", **_) -> dict:
    """
    Low-level structure repair primitive.
    """
    return construction_repair_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        target_entity_ids,
        builder_mask=builder_mask,
        repair_radius=repair_radius,
        repair_rate=repair_rate,
        device=device,
    )


def instinct_demolish_with_humans(ctx: dict, h_tensor: torch.Tensor,
                                  m_tensor: torch.Tensor,
                                  entity_count_ref: list,
                                  target_entity_ids: list[int] | torch.Tensor,
                                  builder_mask: torch.Tensor | None = None,
                                  demolish_radius: float = BUILD_RADIUS,
                                  device: str = "cpu", **_) -> dict:
    """
    Low-level demolition primitive that damages/removes map objects and
    returns salvage to nearby humans.
    """
    return construction_demolish_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        target_entity_ids,
        builder_mask=builder_mask,
        demolish_radius=demolish_radius,
        device=device,
    )


def _spawn_structure_entity(m_tensor: torch.Tensor,
                            entity_count_ref: list,
                            cx: float, cy: float,
                            structure_type: int,
                            scale: float,
                            durability: float,
                            shelter_cap: float = 0.0,
                            build_progress: float = 100.0,
                            device: str = "cpu",
                            extra_cols: dict[int, float] | None = None) -> int:
    return construction_spawn_structure_entity(
        m_tensor,
        entity_count_ref,
        cx,
        cy,
        structure_type,
        scale,
        durability,
        shelter_cap=shelter_cap,
        build_progress=build_progress,
        device=device,
        extra_cols=extra_cols,
        create_object_fn=instinct_create_object,
    )


def _resolve_build_site(m_tensor: torch.Tensor,
                        center_x: float, center_y: float,
                        radius: float,
                        allowed_base_types: set[int] | None = None
                        ) -> tuple[float, float, int] | None:
    return construction_resolve_build_site(
        m_tensor,
        center_x,
        center_y,
        radius,
        allowed_base_types=allowed_base_types,
    )


def instinct_find_buildable_site(m_tensor: torch.Tensor,
                                 center_x: float, center_y: float,
                                 structure_type: int | None = None,
                                 search_radius: float = 320.0,
                                 allowed_base_types: set[int] | None = None
                                 ) -> tuple[float, float, int] | None:
    """
    Low-level build-site search primitive.
    Finds the nearest valid land anchor for a requested structure type.
    """
    return construction_find_buildable_site(
        m_tensor,
        center_x,
        center_y,
        structure_type=structure_type,
        search_radius=search_radius,
        allowed_base_types=allowed_base_types,
    )


def _structure_blueprint(structure_type: int, base_fertility: float = 60.0) -> dict:
    blueprint = construction_structure_blueprint(structure_type, base_fertility=base_fertility)
    if structure_type == M_WALL:
        blueprint = dict(blueprint)
        blueprint["durability"] = 180.0
    return blueprint


def _build_human_pairwise(h_tensor: torch.Tensor,
                           h_mask: torch.Tensor,
                           seek_mask: torch.Tensor | None = None) -> dict:
    """
    Build dense live-only human-human relation tensors for the current tick.

    This is the shared pairwise pass: later instincts reuse the same distance
    matrix and directional masks instead of re-running separate cdist calls.
    """
    device   = h_tensor.device
    live_idx = torch.where(h_mask)[0]
    live_n   = int(live_idx.numel())

    if seek_mask is None:
        seek_mask = torch.zeros_like(h_mask)

    if live_n == 0:
        empty_bool  = torch.zeros((0, 0), dtype=torch.bool, device=device)
        empty_float = torch.zeros((0, 0), dtype=torch.float32, device=device)
        empty_vec   = torch.zeros(0, dtype=torch.bool, device=device)
        empty_sex   = torch.zeros(0, dtype=h_tensor.dtype, device=device)
        return {
            "live_idx":          live_idx,
            "dists":             empty_float,
            "not_self":          empty_bool,
            "sex":               empty_sex,
            "seek_ready":        empty_vec,
            "male":              empty_vec,
            "female":            empty_vec,
            "aggressive":        empty_vec,
            "peaceful":          empty_vec,
            "infected":          empty_vec,
            "below_inf_thresh":  empty_vec,
            "within_mate":       empty_bool,
            "within_attack":     empty_bool,
            # Intentional self-inclusion for infection checks so an already
            # infected agent still counts as "near infection".
            "within_infection":  empty_bool,
        }

    pos        = h_tensor[live_idx, :2]
    space      = space_slice(h_tensor, live_idx, "h")           # None unless EDEN_SPACES: rows of different spaces are FAR apart
    dists      = pairwise_distances(pos, pos, space_a=space, space_b=space)
    not_self   = ~torch.eye(live_n, dtype=torch.bool, device=device)
    sex        = h_tensor[live_idx, H_SEX]
    aggression = h_tensor[live_idx, H_AGGRESSION]
    stamina    = h_tensor[live_idx, H_STAMINA]
    infection  = h_tensor[live_idx, H_INFECTION]
    seek_ready = seek_mask[live_idx]

    return {
        "live_idx":          live_idx,
        "dists":             dists,
        "not_self":          not_self,
        "sex":               sex,
        "seek_ready":        seek_ready,
        "male":              sex == 0.0,
        "female":            sex == 1.0,
        "aggressive":        (aggression >= AGGRESSION_THRESHOLD)
                             & (stamina >= ATTACK_STAMINA_COST),
        "peaceful":          aggression < AGGRESSION_THRESHOLD,
        "infected":          infection > 0.0,
        "below_inf_thresh":  infection < INFECTION_THRESHOLD,
        "within_mate":       (dists < PROXIMITY_MATE_RADIUS) & not_self,
        "within_attack":     (dists < ATTACK_RANGE) & not_self,
        "within_infection":  dists < INFECTION_SPREAD_RADIUS,
    }


def _get_human_pairwise(ctx: dict, h_tensor: torch.Tensor,
                         ctx_key: str) -> dict:
    """Return cached pairwise relations or build them on demand."""
    pairwise = ctx.get(ctx_key)
    if pairwise is not None:
        return pairwise
    return _build_human_pairwise(
        h_tensor, ctx["h_mask"], ctx.get("seek_mask")
    )


# =============================================================================
# PRIMITIVES — called by tools, NOT registered in the engine loop
# =============================================================================

def instinct_proximity(h_tensor: torch.Tensor,
                        source_mask: torch.Tensor,
                        target_mask: torch.Tensor,
                        radius: float) -> torch.Tensor:
    """
    Bool tensor (source_count,): True if that source agent has ≥1 target
    within radius.  Pure function — no side effects.
    """
    if not source_mask.any() or not target_mask.any():
        return torch.zeros(source_mask.sum(), dtype=torch.bool,
                           device=h_tensor.device)
    s_pos = h_tensor[source_mask, :2]
    t_pos = h_tensor[target_mask, :2]
    return torch.any(pairwise_distances(s_pos, t_pos, space_a=space_slice(h_tensor, source_mask, "h"),
                                        space_b=space_slice(h_tensor, target_mask, "h")) < radius, dim=1)


def instinct_flee(ctx: dict, h_tensor: torch.Tensor,
                   threat_pos: tuple[float, float],
                   flee_mask: torch.Tensor | None = None,
                   device: str = "cpu", **_) -> None:
    """Push agents in flee_mask away from threat_pos."""
    h_mask = ctx["h_mask"]
    active = (flee_mask if flee_mask is not None else h_mask) & h_mask
    if not active.any():
        return
    pos       = h_tensor[active, :2]
    threat    = torch.tensor(threat_pos, dtype=torch.float32, device=device)
    direction = pos - threat
    norm      = direction.norm(dim=1, keepdim=True).clamp(min=1e-6)
    repulsion = (direction / norm) * MOVE_STEP * 3.0
    x0, y0, x1, y1 = _world_limits()
    h_tensor[active, X] = (h_tensor[active, X] + repulsion[:, 0]).clamp(x0, x1)
    h_tensor[active, Y] = (h_tensor[active, Y] + repulsion[:, 1]).clamp(y0, y1)


def instinct_cooldown(ctx: dict, h_tensor: torch.Tensor,
                       col: int = H_COOLDOWN,
                       rate: float | None = None, **_) -> None:
    """Decay any timer column toward zero."""
    if rate is None:
        rate = _calendar.cooldown_decay_rate()
    h_mask = ctx["h_mask"]
    h_tensor[h_mask, col] -= rate
    clamp_rows_(h_tensor, h_mask, col, lo=0.0)


# =============================================================================
# SPAWN PRIMITIVES
# =============================================================================

def instinct_born(h_tensor: torch.Tensor, pop_count_ref: list,
                  x: float, y: float, sex: float,
                  life_exp: float, age: float = 0.0,
                  hunger: float = 0.0, mood: float = 80.0,
                  parent_instincts: float = 0.0,
                  tribe: float = 0.0) -> bool:
    """Spawn one human into first free h_tensor slot. Returns False if at cap."""
    if pop_count_ref[0] >= MAX_HUMANS:
        return False
    free = torch.where(h_tensor[:, TYPE] == AGENT_TYPE_EMPTY)[0]
    if not len(free):
        return False
    idx = free[0].item()
    h_tensor[idx] = 0.0   # zero before write — prevents stale col bleed
    r = h_tensor[idx]
    r[X] = x;              r[Y] = y
    r[TYPE] = float(AGENT_TYPE_HUMAN)
    r[HP]   = 100.0
    r[H_STRENGTH]   = random.uniform(30, 80)
    r[H_FERTILITY]  = 1.0
    r[H_AGGRESSION] = 0.0
    r[H_STAMINA]    = 100.0
    r[H_INFECTION]  = 0.0
    r[H_SHELTER]    = 0.0
    r[H_SEX]        = sex
    r[H_AGE]        = age
    r[H_LIFE_EXP]   = life_exp
    r[H_COOLDOWN]   = 0.0
    r[HUNGER]       = hunger
    r[THREAT]       = 0.0
    r[MOOD]         = mood
    r[CRITICAL_HEALTH]        = 0.0
    r[ESCALATION_FLAG]        = 0.0
    r[ACQUIRED_INSTINCT_MASK] = 0.0
    r[H_CARRYING]        = 0.0
    r[H_SKILL]           = 0.0
    r[H_TRIBE]           = tribe
    r[H_PARENT_INSTINCTS] = parent_instincts
    r[THIRST]            = 0.0
    pop_count_ref[0] += 1
    return True


def entity_born(m_tensor: torch.Tensor, entity_count_ref: list,
                cx: float, cy: float, m_type: int,
                hp: float = 100.0, scale: float = 50.0,
                register_geo: bool = False,
                device: str = "cpu",
                col_vals: dict[int, float] | None = None) -> int:
    """
    Spawn one entity into first free m_tensor slot (M_TYPE == 0).
    Returns entity_id (row index), or -1 if at cap.

    col_vals: {column_index: value} for any typed columns.

    register_geo: if True and m_type is a natural feature, registers a
    circle in MAP_GEO using (cx, cy, scale) as geometry. Set False for
    animals — they are point-mobile and don't need tile_mask tracking.
    """
    if entity_count_ref[0] >= MAX_ENTITIES:
        return -1
    free = torch.where(m_tensor[:MAX_ENTITIES, M_TYPE] == 0)[0]
    if not len(free):
        return -1
    idx = free[0].item()
    generation = float(m_tensor[idx, M_GEN])   # 1008 P5: the generation of a released slot survives reuse (always 0 with EDEN_WINDOW off)
    m_tensor[idx] = 0.0   # full zero before write
    m_tensor[idx, M_GEN] = generation
    m_tensor[idx, CX]    = cx
    m_tensor[idx, CY]    = cy
    m_tensor[idx, M_TYPE] = float(m_type)
    m_tensor[idx, M_HP]   = hp
    m_tensor[idx, SCALE]  = scale
    if col_vals is None:
        col_vals = {}
    for col, val in col_vals.items():
        m_tensor[idx, int(col)] = float(val)
    entity_count_ref[0] += 1

    if register_geo:
        map_geo.register_entity(idx, "circle", cx, cy, scale, device=device)

    return idx


def animal_born(m_tensor: torch.Tensor, entity_count_ref: list,
                cx: float, cy: float, species: int,
                sex: float | None = None,
                life_exp: float | None = None,
                device: str = "cpu") -> int:
    """
    Spawn one animal.  Life expectancy and scale default from
    ANIMAL_LIFE_EXP / ANIMAL_SCALE in genesis_config if not provided.
    Animals are NOT registered in MAP_GEO — they are point-mobile.
    Returns entity_id, or -1 if at cap.
    """
    if sex is None:
        sex = 0.0 if random.random() < 0.5 else 1.0
    le_range = ANIMAL_LIFE_EXP.get(species, (5.0, 15.0))
    if life_exp is None:
        life_exp = random.uniform(*le_range)
    scale = ANIMAL_SCALE.get(species, 6.0)
    agg   = ANIMAL_BASE_AGGRESSION.get(species, 0.0)
    return entity_born(
        m_tensor, entity_count_ref, cx, cy, species,
        hp=100.0, scale=scale,
        register_geo=False,   # animals: no tile_mask
        device=device,
        col_vals={
            A_AGE:        0.0,
            A_LIFE_EXP:   life_exp,
            A_SEX:        sex,
            A_COOLDOWN:   0.0,
            A_HUNGER:     0.0,
            A_AGGRESSION: agg,
            A_THIRST:     0.0,
        },
    )


# =============================================================================
# TIER 0 — HUMAN INSTINCTS  (registered, run every tick)
# =============================================================================

def instinct_age(ctx: dict, h_tensor: torch.Tensor, **_) -> None:
    from systems.roster.driver import age_scale_vector
    scales = age_scale_vector(ctx.get("engine"), h_tensor)  # None on every legacy map
    step = _calendar.age_step()
    if scales is None:
        h_tensor[ctx["h_mask"], H_AGE] += step
    else:
        h_tensor[:, H_AGE] += torch.where(ctx["h_mask"], scales * step, torch.zeros_like(scales))


def instinct_hunger(ctx: dict, h_tensor: torch.Tensor, **_) -> None:
    from systems.roster.driver import needs_scale_vector
    scales = needs_scale_vector(ctx.get("engine"), h_tensor)  # None on every legacy map
    before = h_tensor[:, HUNGER].clone() if scales is not None else None
    apply_hunger_tick(ctx["h_mask"], h_tensor)
    if scales is not None:
        h_tensor[:, HUNGER] = before + (h_tensor[:, HUNGER] - before) * scales


def instinct_thirst(ctx: dict, h_tensor: torch.Tensor, **_) -> None:
    from systems.roster.driver import needs_scale_vector
    scales = needs_scale_vector(ctx.get("engine"), h_tensor)  # None on every legacy map
    before = h_tensor[:, THIRST].clone() if scales is not None else None
    apply_thirst_tick(ctx["h_mask"], h_tensor)
    if scales is not None:
        h_tensor[:, THIRST] = before + (h_tensor[:, THIRST] - before) * scales


def instinct_stamina_tick(ctx: dict, h_tensor: torch.Tensor, **_) -> None:
    h_mask = ctx["h_mask"]
    h_tensor[h_mask, H_STAMINA] += STAMINA_RECOVER_RATE - STAMINA_DRAIN_MOVE
    h_tensor[h_mask, H_STAMINA] = h_tensor[h_mask, H_STAMINA].clamp(0.0, 100.0)


def instinct_emotional_recovery(ctx: dict, h_tensor: torch.Tensor, **_) -> None:
    apply_emotional_recovery(ctx["h_mask"], h_tensor)


def instinct_die(ctx: dict, h_tensor: torch.Tensor,
                 pop_count_ref: list, **_) -> dict:
    h_mask = ctx["h_mask"]
    dead   = h_mask & (h_tensor[:, H_AGE] > h_tensor[:, H_LIFE_EXP])
    if dead.any():
        pop_count_ref[0] -= int(dead.sum().item())
        h_tensor[dead] = 0.0
    return {"h_mask": h_tensor[:, TYPE] > AGENT_TYPE_EMPTY}


def instinct_hp_death(ctx: dict, h_tensor: torch.Tensor,
                      pop_count_ref: list, **_) -> dict:
    h_mask = ctx["h_mask"]
    dead   = h_mask & (h_tensor[:, HP] <= 0.0)
    if dead.any():
        pop_count_ref[0] -= int(dead.sum().item())
        h_tensor[dead] = 0.0
    return {"h_mask": h_tensor[:, TYPE] > AGENT_TYPE_EMPTY}


def instinct_search(ctx: dict, h_tensor: torch.Tensor, **_) -> dict:
    result = build_seek_mask(ctx["h_mask"], h_tensor)
    seek_mask = result.get("seek_mask")
    if seek_mask is None:
        return result
    result["seek_mask"] = _mask_without_active_task_kinds(ctx, seek_mask, TASK_OWNED_SOCIAL_KINDS)
    return result


def instinct_reproduction_strategy(ctx: dict, h_tensor: torch.Tensor, **_) -> dict:
    restricted = restrict_reproduction_seek(ctx.get("seek_mask"), h_tensor)
    seek_mask = restricted.get("seek_mask")
    if seek_mask is None:
        return restricted
    restricted["seek_mask"] = _mask_without_active_task_kinds(ctx, seek_mask, TASK_OWNED_SOCIAL_KINDS)
    return restricted


TASK_OWNED_SURVIVAL_KINDS = {
    "fetch_water",
    "eat_food",
    "sleep",
    "seek_shelter",
    "flee_target",
}

TASK_OWNED_SOCIAL_KINDS = {
    "seek_mate",
    "mate_with_target",
}


def _mask_without_active_task_kinds(
    ctx: dict,
    h_mask: torch.Tensor,
    task_kinds: set[str],
) -> torch.Tensor:
    engine = ctx.get("engine")
    resident_store = getattr(engine, "resident_store", None) if engine is not None else None
    human_ids = getattr(engine, "_human_uid_by_slot", None) if engine is not None else None
    if resident_store is None or human_ids is None or not bool(task_kinds):
        return h_mask
    filtered = h_mask.clone()
    for slot in torch.where(h_mask)[0].tolist():
        if not (0 <= slot < len(human_ids)):
            continue
        human_id = human_ids[slot]
        if not human_id:
            continue
        resident = resident_store.get(human_id)
        if not isinstance(resident, dict):
            continue
        current_task = dict((resident.get("task_state", {}) or {}).get("current_task", {}))
        if str(current_task.get("task_kind", "")).strip() in task_kinds:
            filtered[slot] = False
    return filtered


def instinct_survival_navigation(ctx: dict, h_tensor: torch.Tensor,
                                 m_tensor: torch.Tensor,
                                 device: str = "cpu", **_) -> dict:
    filtered_mask = _mask_without_active_task_kinds(ctx, ctx["h_mask"], TASK_OWNED_SURVIVAL_KINDS)
    if not filtered_mask.any():
        return {}
    return build_survival_navigation_bias(
        filtered_mask,
        h_tensor,
        m_tensor,
        device=device,
    )


def instinct_social_navigation(ctx: dict, h_tensor: torch.Tensor,
                               device: str = "cpu", **_) -> dict:
    return build_social_navigation_bias(
        ctx["h_mask"],
        h_tensor,
        device=device,
        pairwise=_get_human_pairwise(ctx, h_tensor, "pairwise_pre"),
    )


def instinct_schedule_navigation(
    ctx: dict,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    engine: Any | None = None,
    player_control_runtime: Any | None = None,
    device: str = "cpu",
    **_,
) -> dict:
    if engine is None:
        return {}
    return build_schedule_navigation_bias(
        ctx["h_mask"],
        h_tensor,
        m_tensor,
        resident_store=getattr(engine, "resident_store", None),
        human_ids_by_slot=getattr(engine, "_human_uid_by_slot", []),
        tick=int(getattr(engine, "tick", 0)),
        device=device,
        player_control_runtime=player_control_runtime,
    )


def instinct_pairwise_relations(ctx: dict, h_tensor: torch.Tensor,
                                 ctx_key: str = "pairwise_pre", **_) -> dict:
    return build_pairwise_relations(
        h_tensor,
        ctx["h_mask"],
        ctx_key=ctx_key,
        seek_mask=ctx.get("seek_mask"),
        pairwise_builder=_build_human_pairwise,
    )


def instinct_eat(ctx: dict, h_tensor: torch.Tensor,
                 m_tensor: torch.Tensor, **_) -> dict:
    filtered_mask = _mask_without_active_task_kinds(ctx, ctx["h_mask"], {"eat_food"})
    if not filtered_mask.any():
        return {}
    return eat_from_current_entity(filtered_mask, h_tensor, m_tensor, map_geo.entity_at)


def instinct_drink(ctx: dict, h_tensor: torch.Tensor,
                   m_tensor: torch.Tensor, **_) -> dict:
    filtered_mask = _mask_without_active_task_kinds(ctx, ctx["h_mask"], {"fetch_water"})
    if not filtered_mask.any():
        return {}
    return drink_from_nearby_entity(filtered_mask, h_tensor, m_tensor, _nearest_geo_entity)


def instinct_heal(ctx: dict, h_tensor: torch.Tensor, **_) -> None:
    apply_heal_tick(ctx["h_mask"], h_tensor)


def instinct_shelter_check(ctx: dict, h_tensor: torch.Tensor,
                            m_tensor: torch.Tensor, **_) -> None:
    update_shelter_flags(ctx["h_mask"], h_tensor, m_tensor, map_geo.entity_at)


def instinct_structure_occupancy(ctx: dict, h_tensor: torch.Tensor,
                                 m_tensor: torch.Tensor, **_) -> None:
    sync_structure_occupancy(ctx["h_mask"], h_tensor, m_tensor, map_geo.entity_at)


def engine_has_roster(engine) -> bool:
    from systems.roster.apply import world_has_roster
    return world_has_roster(engine)  # the running world's own residents, not the roster file on disk


def instinct_attack(ctx: dict, h_tensor: torch.Tensor,
                    m_tensor: torch.Tensor,
                    pop_count_ref: list, device: str,
                    engine: Any | None = None, **_) -> dict:
    pairwise = _get_human_pairwise(ctx, h_tensor, "pairwise_pre")
    manual_control = ctx.get("manual_control")
    pre_h_hp = h_tensor[:, HP].clone()
    pre_m_hp = m_tensor[:, M_HP].clone()
    attack_intents = collect_sim_attack_intents(pairwise, manual_control=manual_control)
    if engine is not None and engine_has_roster(engine):
        attack_intents = []  # a roster village has no NPC-initiated violence (Stage 1)
    hunt_intents = collect_sim_hunt_intents(
        h_tensor,
        m_tensor,
        ctx["h_mask"],
        huntable_animal_slots(m_tensor, M_TYPE),
        hunger_col=HUNGER,
        aggression_col=H_AGGRESSION,
        stamina_col=H_STAMINA,
        food_seek_threshold=FOOD_SEEK_THRESHOLD,
        aggression_threshold=AGGRESSION_THRESHOLD,
        manual_control=manual_control,
        attack_range=ATTACK_RANGE,
    )
    claimed_attackers = {intent.attacker_slot for intent in attack_intents}
    if claimed_attackers:
        hunt_intents = [intent for intent in hunt_intents if intent.attacker_slot not in claimed_attackers]
    manual_intents = collect_manual_attack_intents(manual_control, h_tensor, m_tensor)
    combat_outcome = resolve_human_attack_intents(
        attack_intents + hunt_intents + manual_intents,
        h_tensor,
        m_tensor,
        device,
        attack_damage=ATTACK_DAMAGE,
        attack_range=ATTACK_RANGE,
        stamina_cost=ATTACK_STAMINA_COST,
        walls=map_wall_boxes(engine) if engine is not None else None,
    )
    if engine is not None and combat_outcome.get("resolved", 0) > 0:
        resident_store = getattr(engine, "resident_store", None)
        human_ids = getattr(engine, "_human_uid_by_slot", [])
        entity_ids = getattr(engine, "_entity_uid_by_slot", [])
        if resident_store is not None:
            for outcome in combat_outcome.get("outcomes", []):
                attacker_slot = int(outcome["attacker_slot"])
                target_slot = int(outcome["target_slot"])
                target_kind = str(outcome["target_kind"]).strip().lower()
                attacker_id = human_ids[attacker_slot] if 0 <= attacker_slot < len(human_ids) else None
                if not attacker_id:
                    continue
                if target_kind == "human":
                    target_id = human_ids[target_slot] if 0 <= target_slot < len(human_ids) else None
                    if not target_id:
                        continue
                    damage = max(0.0, float(pre_h_hp[target_slot]) - float(h_tensor[target_slot, HP]))
                    killed = float(pre_h_hp[target_slot]) > 0.0 and float(h_tensor[target_slot, HP]) <= 0.0
                    resident_store.record_event(
                        attacker_id,
                        engine.tick,
                        "attack",
                        note=f"attacked {target_id} for {round(damage, 1)} damage",
                        other_human_id=target_id,
                    )
                    resident_store.record_event(
                        target_id,
                        engine.tick,
                        "attacked",
                        note=f"attacked by {attacker_id} for {round(damage, 1)} damage",
                        other_human_id=attacker_id,
                    )
                    resident_store.update_relationship(attacker_id, target_id, "rival", -0.12, engine.tick)
                    resident_store.update_relationship(target_id, attacker_id, "rival", -0.18, engine.tick)
                    if killed:
                        resident_store.record_event(
                            attacker_id,
                            engine.tick,
                            "killed_human",
                            note=f"killed {target_id}",
                            other_human_id=target_id,
                        )
                        resident_store.record_event(
                            target_id,
                            engine.tick,
                            "killed_by",
                            note=f"killed by {attacker_id}",
                            other_human_id=attacker_id,
                        )
                elif target_kind == "entity":
                    target_uid = entity_ids[target_slot] if 0 <= target_slot < len(entity_ids) else None
                    damage = max(0.0, float(pre_m_hp[target_slot]) - float(m_tensor[target_slot, M_HP]))
                    killed = float(pre_m_hp[target_slot]) > 0.0 and float(m_tensor[target_slot, M_HP]) <= 0.0
                    event_kind = "hunt_kill" if killed else "hunt_attack"
                    note = f"{event_kind.replace('_', ' ')} on {target_uid or ('entity_slot_' + str(target_slot))} for {round(damage, 1)} damage"
                    resident_store.record_event(
                        attacker_id,
                        engine.tick,
                        event_kind,
                        note=note,
                        other_entity_id=target_slot,
                    )
    if combat_outcome.get("resolved", 0) <= 0:
        return {}
    return {"h_mask": h_tensor[:, TYPE] > AGENT_TYPE_EMPTY}


def instinct_incarnation_stabilize(
    ctx: dict,
    h_tensor: torch.Tensor,
    player_control_runtime: Any = None,
    engine: Any = None,
    **_,
) -> dict:
    """Exempt player-controlled incarnations from all survival systems.

    Runs at priority 5 (before everything else).  Identifies controlled human
    slots, freezes their vitals, and removes them from ``h_mask`` so that
    subsequent instincts (hunger, thirst, death, etc.) skip them entirely.
    The controlled slots are stashed in ``ctx["incarnation_slots"]`` so that
    ``instinct_move`` can re-include them for player-directed movement.
    """
    if player_control_runtime is None or engine is None:
        return {}
    controlled_mask = None
    try:
        tick_ctx = player_control_runtime.build_tick_context(engine)
        controlled_mask = tick_ctx.get("controlled_mask")
    except Exception:
        return {}
    if not isinstance(controlled_mask, torch.Tensor) or not controlled_mask.any():
        return {}
    # Freeze vitals — the incarnation is immortal and self-sufficient.
    h_tensor[controlled_mask, HP]          = 100.0
    h_tensor[controlled_mask, HUNGER]      = 0.0
    h_tensor[controlled_mask, THIRST]      = 0.0
    h_tensor[controlled_mask, H_STAMINA]   = 100.0
    h_tensor[controlled_mask, MOOD]        = 80.0
    h_tensor[controlled_mask, THREAT]      = 0.0
    h_tensor[controlled_mask, H_INFECTION] = 0.0
    # Remove from h_mask so survival instincts skip this slot.
    h_mask = ctx["h_mask"]
    incarnation_slots = torch.where(controlled_mask)[0].tolist()
    new_h_mask = h_mask & ~controlled_mask
    return {"h_mask": new_h_mask, "incarnation_slots": incarnation_slots}


def instinct_player_control_override(
    ctx: dict,
    h_tensor: torch.Tensor,
    player_control_runtime: Any = None,
    engine: Any = None,
    **_,
) -> dict:
    return build_manual_control_context(
        h_tensor,
        player_control_runtime=player_control_runtime,
        engine=engine,
    )


def instinct_move(
    ctx: dict,
    h_tensor: torch.Tensor,
    device: str,
    m_tensor: torch.Tensor | None = None,
    **_,
) -> None:
    h_mask    = ctx["h_mask"]
    # Re-include incarnation slots that were excluded from survival systems.
    incarnation_slots = ctx.get("incarnation_slots", [])
    if incarnation_slots:
        for slot in incarnation_slots:
            if 0 <= slot < h_mask.shape[0]:
                h_mask = h_mask.clone()
                h_mask[slot] = True
    seek_mask = ctx.get("seek_mask", torch.zeros_like(h_mask))
    pairwise  = _get_human_pairwise(ctx, h_tensor, "pairwise_pre")
    h_indices = pairwise["live_idx"] if pairwise["live_idx"].numel() else torch.where(h_mask)[0]
    n         = int(h_indices.numel())
    if n == 0:
        return
    noise     = (torch.rand((n, 2), device=device) - 0.5) * (MOVE_STEP * 2)
    nav_survival = ctx.get("nav_survival_bias")
    nav_social   = ctx.get("nav_social_bias")
    nav_schedule = ctx.get("nav_schedule_bias")
    noise = apply_navigation_bias(
        noise,
        h_indices,
        nav_survival=nav_survival,
        nav_social=nav_social,
        nav_schedule=nav_schedule,
    )

    # Fatigue halves movement
    fatigue = h_tensor[h_indices, H_STAMINA] < 10.0
    noise[fatigue] *= 0.5
    # Mate-attraction bias
    if pairwise["live_idx"].numel() and pairwise["seek_ready"].any():
        dists = pairwise["dists"]
        for seeker_sex, target_sex in [(0.0, 1.0), (1.0, 0.0)]:
            seeker_rows = pairwise["seek_ready"] & (pairwise["sex"] == seeker_sex)
            target_rows = pairwise["seek_ready"] & (pairwise["sex"] == target_sex)
            if not seeker_rows.any() or not target_rows.any():
                continue
            live_seeker_rows = torch.where(seeker_rows)[0]
            live_target_rows = torch.where(target_rows)[0]
            nearest_rows     = dists[seeker_rows][:, target_rows].argmin(dim=1)
            seeker_idx       = pairwise["live_idx"][live_seeker_rows]
            target_idx       = pairwise["live_idx"][live_target_rows[nearest_rows]]
            s_pos            = h_tensor[seeker_idx, :2]
            nearest          = h_tensor[target_idx, :2]
            unit             = nearest - s_pos
            unit   /= unit.norm(dim=1, keepdim=True).clamp(min=1e-6)
            seeker_space = space_slice(h_tensor, seeker_idx, "h")
            if seeker_space is not None:                              # EDEN_SPACES: the nearest target may be in another space
                unit *= (seeker_space == space_slice(h_tensor, target_idx, "h")).unsqueeze(1).to(unit.dtype)
            noise[live_seeker_rows] += unit * ATTRACTION_FORCE
    elif seek_mask[h_indices].any():
        # Fallback path if the shared pairwise pass is unavailable.
        for seeker_sex, target_sex in [(0.0, 1.0), (1.0, 0.0)]:
            s_mask = seek_mask & (h_tensor[:, H_SEX] == seeker_sex)
            t_mask = seek_mask & (h_tensor[:, H_SEX] == target_sex)
            if not s_mask.any() or not t_mask.any():
                continue
            s_pos   = h_tensor[s_mask, :2]
            t_pos   = h_tensor[t_mask, :2]
            s_space = space_slice(h_tensor, s_mask, "h")
            t_space = space_slice(h_tensor, t_mask, "h")
            nearest_at = pairwise_distances(s_pos, t_pos, space_a=s_space, space_b=t_space).argmin(dim=1)
            nearest = t_pos[nearest_at]
            unit    = nearest - s_pos
            unit   /= unit.norm(dim=1, keepdim=True).clamp(min=1e-6)
            if s_space is not None:                                   # EDEN_SPACES: the nearest target may be in another space
                unit *= (s_space == t_space[nearest_at]).unsqueeze(1).to(unit.dtype)
            noise[s_mask[h_indices]] += unit * ATTRACTION_FORCE
    manual_control = ctx.get("manual_control")
    noise = apply_manual_control_movement(
        noise,
        h_tensor,
        h_indices,
        manual_control,
        MOVE_STEP,
        m_tensor=m_tensor,
    )
    from systems.roster.driver import anchor_driven_rows
    anchored = anchor_driven_rows(ctx.get("engine"), h_indices)  # roster residents move only via their anchor mover
    if anchored is not None:
        noise[anchored] = 0.0
    x0, y0, x1, y1 = _world_limits()
    h_tensor[h_mask, X] = (h_tensor[h_mask, X] + noise[:, 0]).clamp(x0, x1)
    h_tensor[h_mask, Y] = (h_tensor[h_mask, Y] + noise[:, 1]).clamp(y0, y1)


def instinct_infection_tick(ctx: dict, h_tensor: torch.Tensor,
                              device: str, **_) -> None:
    apply_infection_tick(
        ctx["h_mask"],
        h_tensor,
        _get_human_pairwise(ctx, h_tensor, "pairwise_post"),
        proximity_fn=instinct_proximity,
    )


def instinct_nature_cycle(
    ctx: dict,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    engine: Any = None,
    entity_count_ref: list | None = None,
    device: str = "cpu",
    **_,
) -> dict:
    if engine is None:
        return {}
    if engine_has_roster(engine):
        return {}  # no random floods, storms or fires in a roster village (disasters are a god power, P5)
    outcome = nature_advance_cycle(
        ctx,
        h_tensor,
        m_tensor,
        engine=engine,
        device=device,
        flood_tool_fn=tool_flood,
        storm_tool_fn=tool_storm,
        wildfire_tool_fn=tool_wildfire,
        drought_tool_fn=tool_drought,
    )
    ecology_outcome = nature_maybe_rebalance_ecology(
        m_tensor,
        entity_count_ref or [0],
        tick=int(getattr(engine, "tick", 0)),
        nature_state=getattr(engine, "_nature_state", {}),
        device=device,
        spawn_animal_group_fn=tool_spawn_animal_group,
    )
    merged: dict[str, Any] = {}
    if outcome:
        merged.update(outcome)
    if ecology_outcome:
        merged.update(ecology_outcome)
    if merged.get("frame_dirty"):
        engine._force_frame_refresh = True
    if merged.get("map_dirty"):
        engine._force_map_refresh = True
    merged.pop("frame_dirty", None)
    return merged


def instinct_fire_tick(ctx: dict, m_tensor: torch.Tensor,
                        h_tensor: torch.Tensor,
                        pop_count_ref: list,
                        entity_count_ref: list,
                        device: str, **_) -> dict:
    return nature_apply_fire_tick(ctx, m_tensor, h_tensor, device=device)


def instinct_lava_tick(ctx: dict, m_tensor: torch.Tensor,
                        h_tensor: torch.Tensor,
                        pop_count_ref: list, device: str, **_) -> dict:
    return nature_apply_lava_tick(ctx, m_tensor, h_tensor, device=device)


def instinct_resource_regrow(ctx: dict, m_tensor: torch.Tensor, engine: Any = None, **_) -> None:
    modifiers = getattr(engine, "_nature_state", {}).get("modifiers", {}) if engine is not None else {}
    nature_apply_resource_regrow(
        m_tensor,
        food_multiplier=float(modifiers.get("food_growth", 1.0)),
        include_nodes=not getattr(engine, "node_regrow_external", False),   # G-005: harness/resources.py regrows nodes when installed
    )


def instinct_water_cycle(ctx: dict, m_tensor: torch.Tensor, engine: Any = None, **_) -> None:
    modifiers = getattr(engine, "_nature_state", {}).get("modifiers", {}) if engine is not None else {}
    nature_apply_water_cycle(
        m_tensor,
        water_multiplier=float(modifiers.get("water_growth", 1.0)),
        farm_food_multiplier=float(modifiers.get("farm_growth", 1.0)),
    )


def check_escalation(ctx: dict, h_tensor: torch.Tensor, **_) -> None:
    h_mask   = ctx["h_mask"]
    distress = (
        h_tensor[:, HUNGER]           / 100.0
        + h_tensor[:, THREAT]         / 100.0
        + (100.0 - h_tensor[:, MOOD]) / 100.0
        + h_tensor[:, CRITICAL_HEALTH]
    )
    flagged = h_mask & (distress >= ESCALATION_THRESHOLD)
    h_tensor[:, ESCALATION_FLAG]        = 0.0
    h_tensor[flagged, ESCALATION_FLAG]  = 1.0


# =============================================================================
# TIER 0 — ANIMAL INSTINCTS  (registered separately, run every tick)
# =============================================================================

def _legacy_animal_rows(a_mask: torch.Tensor, m_tensor: torch.Tensor) -> torch.Tensor:
    """EDEN_CREATURES (1008_creatures_gap.md section 5): the rows the creature kernel owns are not moved or fought by the two legacy loops below. ``a_mask`` itself, untouched, with the flag off."""
    if not _creatures_enabled():
        return a_mask
    try:
        from systems.creatures.kernel import legacy_rows
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.systems.creatures.kernel import legacy_rows
    return legacy_rows(a_mask, m_tensor)


def animal_instinct_age(ctx: dict, m_tensor: torch.Tensor, **_) -> None:
    """Increment A_AGE for all live animal entities."""
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return
    m_tensor[a_mask, A_AGE] += _calendar.age_step()


def animal_instinct_hunger(ctx: dict, m_tensor: torch.Tensor, **_) -> None:
    """Animals accumulate hunger and lose HP when starving."""
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return
    m_tensor[a_mask, A_HUNGER] += ANIMAL_HUNGER_TICK_RATE * _rate("needs")
    clamp_rows_(m_tensor, a_mask, A_HUNGER, hi=100.0)
    starving = a_mask & (m_tensor[:, A_HUNGER] >= 90.0)
    apply_entity_damage(starving, m_tensor, 1.5 * _rate("starvation"), hp_col=M_HP)


def animal_instinct_thirst(ctx: dict, m_tensor: torch.Tensor, **_) -> None:
    """Animals accumulate thirst and lose HP when dehydrated."""
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return
    m_tensor[a_mask, A_THIRST] += ANIMAL_THIRST_TICK_RATE * _rate("needs")
    clamp_rows_(m_tensor, a_mask, A_THIRST, hi=100.0)
    dehydrated = a_mask & (m_tensor[:, A_THIRST] >= 90.0)
    apply_entity_damage(dehydrated, m_tensor, THIRST_DAMAGE_RATE * _rate("damage_recovery"), hp_col=M_HP)


def animal_instinct_die(ctx: dict, m_tensor: torch.Tensor,
                         entity_count_ref: list, **_) -> dict:
    """Kill animals that exceed life expectancy or reach HP == 0."""
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    # Age death
    age_dead = a_mask & (m_tensor[:, A_AGE] > m_tensor[:, A_LIFE_EXP])
    # HP death
    hp_dead  = a_mask & (m_tensor[:, M_HP] <= 0.0)
    dead     = age_dead | hp_dead
    if dead.any():
        entity_count_ref[0] -= int(dead.sum().item())
        m_tensor[dead] = 0.0   # free the slot
    # Recompute a_mask — alive animals have M_TYPE in ANIMAL_TYPES
    new_a_mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool,
                              device=m_tensor.device)
    for t in ANIMAL_TYPES:
        new_a_mask |= (m_tensor[:, M_TYPE] == t)
    return {"a_mask": new_a_mask}


def animal_instinct_move(ctx: dict, m_tensor: torch.Tensor,
                          device: str, **_) -> None:
    """
    Brownian motion for all live animals.
    Each species uses its own ANIMAL_MOVE_STEP from genesis_config.
    Predators bias toward nearest prey within detection range.
    """
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return
    a_mask = _legacy_animal_rows(a_mask, m_tensor)
    if not a_mask.any():
        return
    h_tensor = ctx.get("h_tensor_ref")   # passed via engine kwargs

    a_idx = torch.where(a_mask)[0]
    for i in a_idx.tolist():
        species = int(m_tensor[i, M_TYPE])
        step    = ANIMAL_MOVE_STEP.get(species, 2.0)
        dx = (random.random() - 0.5) * step * 2
        dy = (random.random() - 0.5) * step * 2
        lake_home_eid = -1

        # Predator attraction toward nearest prey (human or prey animal)
        prey_types = ANIMAL_PREY.get(species, set())
        if prey_types:
            pos = m_tensor[i, [CX, CY]]
            target_kind, target_slot, target_dist = nearest_predator_target(
                h_tensor,
                m_tensor,
                float(pos[0]),
                float(pos[1]),
                prey_types,
                max_distance=float(ANIMAL_PREDATOR_RANGE * 3),
                exclude_entity_slot=i,
            )
            if target_slot != -1 and target_dist < ANIMAL_PREDATOR_RANGE * 3:
                if target_kind == "human" and h_tensor is not None:
                    target_pos = h_tensor[target_slot, :2]
                else:
                    target_pos = m_tensor[target_slot, [CX, CY]]
                d = target_pos - pos
                n = d.norm().clamp(min=1e-6)
                dx += float(d[0] / n) * step
                dy += float(d[1] / n) * step

        if species == M_FISH:
            lake_mask = m_tensor[:, M_TYPE] == M_LAKE
            if lake_mask.any():
                lake_idx = torch.where(lake_mask)[0]
                lake_pos = m_tensor[lake_idx][:, [CX, CY]]
                pos      = m_tensor[i, [CX, CY]]
                nearest  = (((lake_pos - pos).pow(2)).sum(dim=1)).sqrt().argmin()
                lake_home_eid = int(lake_idx[nearest])
                center = m_tensor[lake_home_eid, [CX, CY]]
                home_r = max(4.0, float(m_tensor[lake_home_eid, SCALE]) * 0.8)
                delta  = center - pos
                dist   = float(delta.norm())
                if dist > home_r:
                    unit = delta / delta.norm().clamp(min=1e-6)
                    dx += float(unit[0]) * step * 2.5
                    dy += float(unit[1]) * step * 2.5

        m_tensor[i, CX] = float(m_tensor[i, CX]) + dx
        m_tensor[i, CY] = float(m_tensor[i, CY]) + dy
        x0, y0, x1, y1 = _world_limits()
        m_tensor[i, CX] = max(x0, min(x1, float(m_tensor[i, CX])))
        m_tensor[i, CY] = max(y0, min(y1, float(m_tensor[i, CY])))
        if species == M_FISH and lake_home_eid != -1:
            pos    = m_tensor[i, [CX, CY]]
            center = m_tensor[lake_home_eid, [CX, CY]]
            delta  = pos - center
            dist   = float(delta.norm())
            max_r  = max(4.0, float(m_tensor[lake_home_eid, SCALE]) * 0.95)
            if dist > max_r:
                unit = delta / delta.norm().clamp(min=1e-6)
                clamped = center + unit * max_r
                m_tensor[i, CX] = float(clamped[0].clamp(x0, x1))
                m_tensor[i, CY] = float(clamped[1].clamp(y0, y1))


def animal_instinct_eat(ctx: dict, m_tensor: torch.Tensor, **_) -> dict:
    """
    Animals eat from the entity they're standing in (same as humans).
    Uses entity_at O(1) lookup.
    """
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    map_dirty = False
    for i in torch.where(a_mask)[0].tolist():
        if m_tensor[i, A_HUNGER] <= 20.0:
            continue
        ax  = float(m_tensor[i, CX])
        ay  = float(m_tensor[i, CY])
        eid = map_geo.entity_at(ax, ay)
        if eid == -1 or eid == i:   # can't eat itself
            continue
        food = float(m_tensor[eid, M_RESOURCE_FOOD])
        if food <= 0:
            continue
        m_tensor[i, A_HUNGER]            -= 20.0
        m_tensor[i, A_HUNGER]             = max(0.0, float(m_tensor[i, A_HUNGER]))
        m_tensor[eid, M_RESOURCE_FOOD]    = max(0.0, food - EAT_RESOURCE_COST)
        map_dirty = True
    return {"map_dirty": map_dirty} if map_dirty else {}


def animal_instinct_drink(ctx: dict, m_tensor: torch.Tensor, **_) -> dict:
    """
    Animals drink from nearby lakes or wells.
    """
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    map_dirty = False
    for i in torch.where(a_mask)[0].tolist():
        if m_tensor[i, A_THIRST] <= 20.0:
            continue
        ax = float(m_tensor[i, CX])
        ay = float(m_tensor[i, CY])
        eid = _nearest_geo_entity(
            m_tensor, ax, ay, DRINKABLE_TYPES, DRINK_PROXIMITY_RADIUS
        )
        if eid == -1 or eid == i:
            continue
        water = float(m_tensor[eid, M_RESOURCE_WATER])
        if water <= 0.0:
            continue
        m_tensor[i, A_THIRST] -= DRINK_THIRST_RESTORE
        m_tensor[i, A_THIRST] = max(0.0, float(m_tensor[i, A_THIRST]))
        m_tensor[eid, M_RESOURCE_WATER] = max(
            0.0, water - DRINK_RESOURCE_COST
        )
        map_dirty = True
    return {"map_dirty": map_dirty} if map_dirty else {}


def animal_instinct_predator_attack(ctx: dict, m_tensor: torch.Tensor,
                                     h_tensor: torch.Tensor,
                                     pop_count_ref: list,
                                     entity_count_ref: list,
                                     device: str, **_) -> dict:
    """
    Predator animals (tiger, wolf) attack nearby humans or prey animals.
    Humans lose HP. Prey animals lose M_HP.
    """
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    a_mask = _legacy_animal_rows(a_mask, m_tensor)
    if not a_mask.any():
        return {}

    h_mask = ctx["h_mask"]
    dirty  = False

    for i in torch.where(a_mask)[0].tolist():
        species    = int(m_tensor[i, M_TYPE])
        prey_types = ANIMAL_PREY.get(species, set())
        if not prey_types:
            continue
        px = float(m_tensor[i, CX])
        py = float(m_tensor[i, CY])

        # Attack humans
        if AGENT_TYPE_HUMAN in prey_types and h_mask.any():
            h_pos  = h_tensor[h_mask, :2]
            center = torch.tensor([[px, py]], dtype=torch.float32,
                                   device=device)
            dists  = pairwise_distances(h_pos, center, space_a=space_slice(h_tensor, h_mask, "h"),
                                        space_b=space_slice(m_tensor, i, "m")).squeeze(1)
            near   = torch.where(h_mask)[0][dists < ANIMAL_PREDATOR_RANGE]
            if near.numel():
                victim = near[0]
                victim_mask = torch.zeros(h_tensor.shape[0], dtype=torch.bool, device=h_tensor.device)
                victim_mask[int(victim)] = True
                apply_human_damage(victim_mask, h_tensor, ANIMAL_PREDATOR_ATTACK_DAMAGE, hp_col=HP)
                h_tensor[victim, THREAT] = 100.0

        # Attack prey animals
        for prey_t in prey_types - {AGENT_TYPE_HUMAN}:
            prey_mask = a_mask & (m_tensor[:, M_TYPE] == prey_t)
            if not prey_mask.any():
                continue
            p_pos  = m_tensor[prey_mask][:, [CX, CY]].reshape(-1, 2)
            center = torch.tensor([[px, py]], dtype=torch.float32, device=device)
            dists  = pairwise_distances(p_pos, center, space_a=space_slice(m_tensor, prey_mask, "m"),
                                        space_b=space_slice(m_tensor, i, "m")).squeeze(1)
            hits   = torch.where(prey_mask)[0][dists < ANIMAL_PREDATOR_RANGE]
            if hits.numel():
                target_mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
                target_mask[int(hits[0])] = True
                apply_entity_damage(target_mask, m_tensor, ANIMAL_PREDATOR_ATTACK_DAMAGE, hp_col=M_HP)

    return {"h_mask": h_tensor[:, TYPE] > AGENT_TYPE_EMPTY}


def animal_tool_reproduce(ctx: dict, m_tensor: torch.Tensor,
                           entity_count_ref: list, device: str, **_) -> None:
    """
    Mature opposite-sex animals of the same species reproduce when close.
    Child spawns near mother with sex chosen at random.
    Mother gains A_COOLDOWN of 1 year (one calendar year under EDEN_CALENDAR, with the table's litter: F3).
    Same logic as tool_reproduce for humans — just simpler stat inheritance.
    """
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return

    # Process per species
    species_present = set(int(m_tensor[i, M_TYPE])
                          for i in torch.where(a_mask)[0].tolist())
    for species in species_present:
        sp_mask = a_mask & (m_tensor[:, M_TYPE] == species)
        if not sp_mask.any():
            continue
        mature_mask = sp_mask & (m_tensor[:, A_AGE] >= ANIMAL_MATURE_TICKS) \
                               & (m_tensor[:, A_COOLDOWN] <= 0.0)
        m_mask = mature_mask & (m_tensor[:, A_SEX] == 0.0)
        f_mask = mature_mask & (m_tensor[:, A_SEX] == 1.0)
        if not m_mask.any() or not f_mask.any():
            continue

        # Keep position tensors explicitly 2D even when only one animal matches.
        f_pos = m_tensor[f_mask][:, [CX, CY]].reshape(-1, 2)
        m_pos = m_tensor[m_mask][:, [CX, CY]].reshape(-1, 2)
        dists  = pairwise_distances(f_pos, m_pos, space_a=space_slice(m_tensor, f_mask, "m"),
                                    space_b=space_slice(m_tensor, m_mask, "m"))   # (F, M)
        close  = (dists < ANIMAL_MATE_RADIUS).any(dim=1)
        f_idx  = torch.where(f_mask)[0]

        litter = 1
        if _calendar.active() is not _calendar.LEGACY:   # F3: the long calendar bears the table's litter; the legacy calendar always one, no lookup
            try:
                from systems.creatures.table import by_type as _creature_row
            except ImportError:  # pragma: no cover - package import fallback
                from at_the_beginning.systems.creatures.table import by_type as _creature_row
            litter = int((_creature_row(species) or {}).get("litter", 1))

        for fi in f_idx[close].tolist():
            for _ in range(litter):
                cx  = float(m_tensor[fi, CX]) + random.uniform(-5, 5)
                cy  = float(m_tensor[fi, CY]) + random.uniform(-5, 5)
                animal_born(m_tensor, entity_count_ref, cx, cy, species,
                            device=device)
            m_tensor[fi, A_COOLDOWN] = _calendar.active().year_ticks / _calendar.active().life_year_ticks   # one calendar year of recovery (legacy: 600/600 = 1.0)

    # Decay cooldowns
    if a_mask.any():
        m_tensor[a_mask, A_COOLDOWN] -= _calendar.cooldown_decay_rate()
        clamp_rows_(m_tensor, a_mask, A_COOLDOWN, lo=0.0)


# =============================================================================
# TIER 1 — HUMAN TOOLS  (world-agent callable)
# =============================================================================

def tool_reproduce(ctx: dict, h_tensor: torch.Tensor,
                   pop_count_ref: list, engine: Any | None = None, **_) -> None:
    births = resolve_human_reproduction(
        h_tensor,
        pop_count_ref,
        _get_human_pairwise(ctx, h_tensor, "pairwise_post"),
        birth_fn=instinct_born,
    )
    if engine is not None and births:
        for birth in births:
            child_slot = int(birth.get("child_slot", -1))
            mother_slot = int(birth.get("mother_slot", -1))
            father_slot = int(birth.get("father_slot", -1))
            if child_slot < 0:
                continue
            parent_ids: list[str] = []
            if 0 <= mother_slot < len(engine._human_uid_by_slot):
                mother_id = engine._human_uid_by_slot[mother_slot]
                if mother_id:
                    parent_ids.append(mother_id)
            if 0 <= father_slot < len(engine._human_uid_by_slot):
                father_id = engine._human_uid_by_slot[father_slot]
                if father_id and father_id not in parent_ids:
                    parent_ids.append(father_id)
            engine._pending_birth_links_by_slot[child_slot] = {
                "tick": engine.tick,
                "parent_ids": parent_ids,
            }
    apply_cooldown_decay(ctx["h_mask"], h_tensor, col=H_COOLDOWN, rate=_calendar.cooldown_decay_rate())


def tool_harvest_food(ctx: dict, h_tensor: torch.Tensor,
                      m_tensor: torch.Tensor,
                      center_x: float, center_y: float,
                      radius: float = 24.0,
                      hunger_restore: float = EAT_HUNGER_RESTORE,
                      device: str = "cpu", **_) -> dict:
    """
    Feed nearby humans from the nearest food-bearing entity.
    """
    source_eid = _nearest_geo_entity(
        m_tensor, center_x, center_y, FOOD_SOURCE_TYPES, radius
    )
    if source_eid == -1:
        return {}

    affected = _agent_radial_mask(
        h_tensor, ctx["h_mask"], center_x, center_y, radius, device
    )
    if not affected.any():
        return {}

    fed = 0
    for i in torch.where(affected)[0].tolist():
        food = float(m_tensor[source_eid, M_RESOURCE_FOOD])
        if food <= 0.0:
            break
        h_tensor[i, HUNGER] -= hunger_restore
        h_tensor[i, HUNGER] = max(0.0, float(h_tensor[i, HUNGER]))
        m_tensor[source_eid, M_RESOURCE_FOOD] = max(
            0.0, food - EAT_RESOURCE_COST
        )
        fed += 1
    return {"map_dirty": fed > 0}


def tool_draw_water(ctx: dict, h_tensor: torch.Tensor,
                    m_tensor: torch.Tensor,
                    center_x: float, center_y: float,
                    radius: float = DRINK_PROXIMITY_RADIUS,
                    thirst_restore: float = DRINK_THIRST_RESTORE,
                    device: str = "cpu", **_) -> dict:
    """
    Hydrate nearby humans from the nearest lake or well.
    """
    source_eid = _nearest_geo_entity(
        m_tensor, center_x, center_y, DRINKABLE_TYPES, radius
    )
    if source_eid == -1:
        return {}

    affected = _agent_radial_mask(
        h_tensor, ctx["h_mask"], center_x, center_y, radius, device
    )
    if not affected.any():
        return {}

    hydrated = 0
    for i in torch.where(affected)[0].tolist():
        water = float(m_tensor[source_eid, M_RESOURCE_WATER])
        if water <= 0.0:
            break
        h_tensor[i, THIRST] -= thirst_restore
        h_tensor[i, THIRST] = max(0.0, float(h_tensor[i, THIRST]))
        m_tensor[source_eid, M_RESOURCE_WATER] = max(
            0.0, water - DRINK_RESOURCE_COST
        )
        hydrated += 1
    return {"map_dirty": hydrated > 0}


def tool_build_house(ctx: dict, m_tensor: torch.Tensor,
                     entity_count_ref: list,
                     center_x: float, center_y: float,
                     scale: float = 22.0,
                     durability: float = 140.0,
                     shelter_cap: float = 4.0,
                     device: str = "cpu", **_) -> dict:
    return construction_tool_build_structure(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=M_HOUSE,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        scale=scale,
        durability=durability,
        shelter_cap=shelter_cap,
        device=device,
    )


def tool_build_village(ctx: dict, m_tensor: torch.Tensor,
                       entity_count_ref: list,
                       center_x: float, center_y: float,
                       scale: float = 42.0,
                       durability: float = 260.0,
                       shelter_cap: float = 18.0,
                       device: str = "cpu", **_) -> dict:
    return construction_tool_build_structure(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=M_VILLAGE,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        scale=scale,
        durability=durability,
        shelter_cap=shelter_cap,
        device=device,
    )


def tool_build_farm(ctx: dict, m_tensor: torch.Tensor,
                    entity_count_ref: list,
                    center_x: float, center_y: float,
                    scale: float = 28.0,
                    durability: float = 110.0,
                    food_stock: float = INITIAL_FOOD_GRASS,
                    water_stock: float = INITIAL_WATER_FARM,
                    growth_rate: float | None = None,
                    device: str = "cpu", **_) -> dict:
    return construction_tool_build_structure(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=M_FARM,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        scale=scale,
        durability=durability,
        shelter_cap=0.0,
        extra_cols={
            M_RESOURCE_FOOD: min(MAX_ENTITY_FOOD, food_stock),
            M_RESOURCE_WATER: min(MAX_ENTITY_WATER, water_stock),
            M_GROWTH_RATE: growth_rate,
        } if growth_rate is not None else {
            M_RESOURCE_FOOD: min(MAX_ENTITY_FOOD, food_stock),
            M_RESOURCE_WATER: min(MAX_ENTITY_WATER, water_stock),
        },
        allowed_base_types=FARMABLE_BASE_TYPES,
        device=device,
    )


def tool_build_well(ctx: dict, m_tensor: torch.Tensor,
                    entity_count_ref: list,
                    center_x: float, center_y: float,
                    scale: float = 16.0,
                    durability: float = 120.0,
                    water_stock: float = INITIAL_WATER_WELL,
                    replenish_rate: float = WELL_WATER_REPLENISH_RATE,
                    device: str = "cpu", **_) -> dict:
    return construction_tool_build_structure(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=M_WELL,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        scale=scale,
        durability=durability,
        shelter_cap=0.0,
        extra_cols={
            M_RESOURCE_WATER: min(MAX_ENTITY_WATER, water_stock),
            M_GROWTH_RATE: replenish_rate,
        },
        device=device,
    )


def tool_designate_structure_site(ctx: dict, m_tensor: torch.Tensor,
                                  entity_count_ref: list,
                                  structure_type: int,
                                  center_x: float, center_y: float,
                                  build_progress: float = 0.0,
                                  search_radius: float = 320.0,
                                  device: str = "cpu", **_) -> dict:
    return construction_tool_designate_structure_site(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=structure_type,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        build_progress=build_progress,
        search_radius=search_radius,
        device=device,
    )


def tool_find_buildable_site(ctx: dict, m_tensor: torch.Tensor,
                             structure_type: int,
                             center_x: float, center_y: float,
                             search_radius: float = 320.0,
                             **_) -> dict:
    """
    Generator-friendly site finder: returns the nearest viable build site
    without mutating the world.
    """
    return construction_tool_find_buildable_site(
        m_tensor,
        structure_type=structure_type,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        search_radius=search_radius,
    )


def tool_gather_building_materials(ctx: dict, h_tensor: torch.Tensor,
                                   m_tensor: torch.Tensor,
                                   center_x: float, center_y: float,
                                   radius: float = BUILD_RADIUS,
                                   amount: float = GATHER_MATERIAL_AMOUNT,
                                   device: str = "cpu", **_) -> dict:
    return instinct_gather_materials(
        ctx, h_tensor, m_tensor,
        center_x=center_x, center_y=center_y,
        radius=radius, amount=amount, device=device,
    )


def tool_build_structure_with_humans(ctx: dict, h_tensor: torch.Tensor,
                                     m_tensor: torch.Tensor,
                                     entity_count_ref: list,
                                     structure_type: int,
                                     center_x: float, center_y: float,
                                     gather_materials: bool = True,
                                     search_radius: float = 320.0,
                                     device: str = "cpu", **_) -> dict:
    return construction_tool_build_structure_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        structure_type=structure_type,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        gather_materials_first=gather_materials,
        search_radius=search_radius,
        device=device,
    )


def tool_construct_house(ctx: dict, h_tensor: torch.Tensor,
                         m_tensor: torch.Tensor,
                         entity_count_ref: list,
                         center_x: float, center_y: float,
                         device: str = "cpu", **_) -> dict:
    return tool_build_structure_with_humans(
        ctx, h_tensor, m_tensor, entity_count_ref,
        structure_type=M_HOUSE,
        center_x=center_x, center_y=center_y,
        device=device,
    )


def tool_construct_village(ctx: dict, h_tensor: torch.Tensor,
                           m_tensor: torch.Tensor,
                           entity_count_ref: list,
                           center_x: float, center_y: float,
                           device: str = "cpu", **_) -> dict:
    return tool_build_structure_with_humans(
        ctx, h_tensor, m_tensor, entity_count_ref,
        structure_type=M_VILLAGE,
        center_x=center_x, center_y=center_y,
        device=device,
    )


def tool_construct_farm(ctx: dict, h_tensor: torch.Tensor,
                        m_tensor: torch.Tensor,
                        entity_count_ref: list,
                        center_x: float, center_y: float,
                        device: str = "cpu", **_) -> dict:
    return tool_build_structure_with_humans(
        ctx, h_tensor, m_tensor, entity_count_ref,
        structure_type=M_FARM,
        center_x=center_x, center_y=center_y,
        device=device,
    )


def tool_construct_well(ctx: dict, h_tensor: torch.Tensor,
                        m_tensor: torch.Tensor,
                        entity_count_ref: list,
                        center_x: float, center_y: float,
                        device: str = "cpu", **_) -> dict:
    return tool_build_structure_with_humans(
        ctx, h_tensor, m_tensor, entity_count_ref,
        structure_type=M_WELL,
        center_x=center_x, center_y=center_y,
        device=device,
    )


def tool_construct_wall_with_humans(ctx: dict, h_tensor: torch.Tensor,
                                    m_tensor: torch.Tensor,
                                    entity_count_ref: list,
                                    start_x: float, start_y: float,
                                    end_x: float, end_y: float,
                                    thickness: float = 12.0,
                                    durability: float = 180.0,
                                    device: str = "cpu", **_) -> dict:
    return construction_tool_construct_wall_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        start_x=start_x,
        start_y=start_y,
        end_x=end_x,
        end_y=end_y,
        clamp_point_fn=_clamp_point,
        make_wall_polygon_fn=_make_wall_polygon,
        create_object_fn=instinct_create_object,
        thickness=thickness,
        durability=durability,
        device=device,
    )


def tool_repair_area_with_humans(ctx: dict, h_tensor: torch.Tensor,
                                 m_tensor: torch.Tensor,
                                 center_x: float, center_y: float,
                                 radius: float = BUILD_RADIUS,
                                 device: str = "cpu", **_) -> dict:
    return construction_tool_repair_area_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        repair_rate=REPAIR_RATE_PER_HUMAN,
        device=device,
    )


def tool_demolish_area_with_humans(ctx: dict, h_tensor: torch.Tensor,
                                   m_tensor: torch.Tensor,
                                   entity_count_ref: list,
                                   center_x: float, center_y: float,
                                   radius: float = BUILD_RADIUS,
                                   device: str = "cpu", **_) -> dict:
    return construction_tool_demolish_area_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
    )


def tool_build_settlement_with_humans(ctx: dict, h_tensor: torch.Tensor,
                                      m_tensor: torch.Tensor,
                                      entity_count_ref: list,
                                      center_x: float, center_y: float,
                                      device: str = "cpu", **_) -> dict:
    return construction_tool_build_settlement_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        device=device,
    )


def tool_repair_structures(ctx: dict, m_tensor: torch.Tensor,
                           center_x: float, center_y: float,
                           radius: float = 60.0,
                           amount: float = 30.0, **_) -> dict:
    return construction_tool_repair_structures(
        m_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        amount=amount,
    )


def tool_irrigate_area(ctx: dict, m_tensor: torch.Tensor,
                       center_x: float, center_y: float,
                       radius: float = 70.0,
                       amount: float = 20.0, **_) -> dict:
    dirty = False
    for eid in _entity_radial_ids(m_tensor, center_x, center_y, radius).tolist():
        et = int(m_tensor[eid, M_TYPE])
        if et in {M_LAKE, M_WELL, M_FARM}:
            m_tensor[eid, M_RESOURCE_WATER] = min(
                MAX_ENTITY_WATER,
                float(m_tensor[eid, M_RESOURCE_WATER]) + amount,
            )
            dirty = True
        elif et in {M_GRASS, M_FOREST, M_BEACH}:
            m_tensor[eid, M_FERTILITY] = min(
                100.0, float(m_tensor[eid, M_FERTILITY]) + amount * 0.5
            )
            dirty = True
    return {"map_dirty": dirty} if dirty else {}


def tool_fertilize_area(ctx: dict, m_tensor: torch.Tensor,
                        center_x: float, center_y: float,
                        radius: float = 70.0,
                        amount: float = 15.0, **_) -> dict:
    dirty = False
    for eid in _entity_radial_ids(m_tensor, center_x, center_y, radius).tolist():
        et = int(m_tensor[eid, M_TYPE])
        if et in {M_GRASS, M_FOREST, M_LAKE, M_BEACH}:
            m_tensor[eid, M_FERTILITY] = min(
                100.0, float(m_tensor[eid, M_FERTILITY]) + amount
            )
            dirty = True
        elif et == M_FARM:
            m_tensor[eid, M_GROWTH_RATE] = min(
                FARM_FOOD_GROWTH_RATE * 2.0,
                float(m_tensor[eid, M_GROWTH_RATE]) + amount / 100.0,
            )
            dirty = True
    return {"map_dirty": dirty} if dirty else {}


def tool_clear_land(ctx: dict, m_tensor: torch.Tensor,
                    center_x: float, center_y: float,
                    radius: float = 70.0,
                    target_type: int = M_GRASS,
                    device: str = "cpu", **_) -> dict:
    if target_type not in NATURAL_TYPES:
        return {}
    dirty = False
    for eid in _entity_radial_ids(m_tensor, center_x, center_y, radius).tolist():
        et = int(m_tensor[eid, M_TYPE])
        if et in {M_SEA, M_LAKE, M_MOUNTAIN} or et in STRUCTURE_TYPES or et in ANIMAL_TYPES:
            continue
        if et == target_type:
            continue
        m_tensor[eid, M_TYPE] = float(target_type)
        m_tensor[eid, M_BURNING] = 0.0
        m_tensor[eid, M_FLOODED] = 0.0
        if target_type == M_GRASS:
            m_tensor[eid, M_RESOURCE_FOOD] = INITIAL_FOOD_GRASS
            m_tensor[eid, M_FERTILITY] = max(40.0, float(m_tensor[eid, M_FERTILITY]))
        elif target_type == M_BARREN:
            m_tensor[eid, M_RESOURCE_FOOD] = 0.0
            m_tensor[eid, M_FERTILITY] = 0.0
            m_tensor[eid, M_RESOURCE_WATER] = 0.0
        map_geo.geo_mutate(eid, device=device)
        dirty = True
    return {"map_dirty": dirty} if dirty else {}


def tool_create_lake(ctx: dict, m_tensor: torch.Tensor,
                     entity_count_ref: list,
                     center_x: float, center_y: float,
                     scale: float = 48.0,
                     water_stock: float = INITIAL_WATER_LAKE,
                     fish_stock: float = INITIAL_FOOD_LAKE,
                     device: str = "cpu", **_) -> dict:
    return create_lake_feature(
        m_tensor,
        entity_count_ref,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        resolve_build_site_fn=_resolve_build_site,
        create_object_fn=instinct_create_object,
        scale=scale,
        water_stock=water_stock,
        fish_stock=fish_stock,
        device=device,
    )


def tool_settle_area(ctx: dict, m_tensor: torch.Tensor,
                     entity_count_ref: list,
                     center_x: float, center_y: float,
                     device: str = "cpu", **_) -> dict:
    return create_settlement_area(
        ctx,
        m_tensor,
        entity_count_ref,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        build_structure_fn=construction_tool_build_structure,
        device=device,
    )


def tool_area_attack(ctx: dict, h_tensor: torch.Tensor,
                      m_tensor: torch.Tensor, pop_count_ref: list,
                      center_x: float, center_y: float,
                      radius: float, device: str = "cpu", **_) -> dict:
    return apply_area_attack_effect(
        ctx,
        h_tensor,
        pop_count_ref,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
        agent_radial_mask_fn=_agent_radial_mask,
        flee_fn=instinct_flee,
    )


def tool_wildfire(ctx: dict, m_tensor: torch.Tensor,
                   center_x: float, center_y: float, radius: float,
                   device: str = "cpu", **_) -> dict:
    """Ignite all forest entities within radius. instinct_fire_tick handles spread."""
    return nature_ignite_wildfire(
        m_tensor,
        center_x,
        center_y,
        radius,
        entity_radial_ids_fn=_entity_radial_ids,
    )


def tool_earthquake(ctx: dict, m_tensor: torch.Tensor,
                     h_tensor: torch.Tensor, pop_count_ref: list,
                     center_x: float, center_y: float,
                     radius: float, device: str = "cpu", **_) -> dict:
    return nature_apply_earthquake(
        ctx,
        h_tensor,
        m_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
        entity_radial_ids_fn=_entity_radial_ids,
        agent_radial_mask_fn=_agent_radial_mask,
        flee_fn=instinct_flee,
    )


def tool_storm(ctx: dict, h_tensor: torch.Tensor,
               center_x: float, center_y: float, radius: float,
               device: str = "cpu", **_) -> dict:
    return nature_apply_storm(
        ctx,
        h_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
        agent_radial_mask_fn=_agent_radial_mask,
    )


def tool_volcanic_eruption(ctx: dict, m_tensor: torch.Tensor,
                            h_tensor: torch.Tensor, pop_count_ref: list,
                            center_x: float, center_y: float,
                            entity_count_ref: list,
                            device: str = "cpu", **_) -> dict:
    return nature_apply_volcanic_eruption(
        ctx,
        h_tensor,
        m_tensor,
        pop_count_ref,
        center_x=center_x,
        center_y=center_y,
        device=device,
        entity_radial_ids_fn=_entity_radial_ids,
        agent_radial_mask_fn=_agent_radial_mask,
        flee_fn=instinct_flee,
    )


def tool_drought(ctx: dict, m_tensor: torch.Tensor,
                  entity_mask: torch.Tensor | None = None, **_) -> dict:
    n = MAX_ENTITIES
    if entity_mask is None:
        entity_mask = m_tensor[:n, M_TYPE] == M_LAKE
    lake_tgt = entity_mask & (m_tensor[:n, M_TYPE] == M_LAKE)
    if lake_tgt.any():
        m_tensor[:n][lake_tgt, M_RESOURCE_FOOD] = 0.0
        m_tensor[:n][lake_tgt, M_RESOURCE_WATER] = 0.0
        m_tensor[:n][lake_tgt, M_FERTILITY]     = 0.0
    return {"map_dirty": bool(lake_tgt.any())}


def tool_flood(ctx: dict, m_tensor: torch.Tensor, h_tensor: torch.Tensor,
               pop_count_ref: list, device: str = "cpu", **_) -> dict:
    return nature_apply_flood(ctx, h_tensor, m_tensor, device=device)


def tool_regrow_forest(ctx: dict, m_tensor: torch.Tensor,
                        entity_mask: torch.Tensor | None = None,
                        device: str = "cpu", **_) -> dict:
    n    = MAX_ENTITIES
    base = (m_tensor[:n, M_TYPE] == M_GRASS) | (m_tensor[:n, M_TYPE] == M_BARREN)
    tgt  = (base & entity_mask) if entity_mask is not None else base
    if tgt.any():
        m_tensor[:n][tgt, M_TYPE]          = float(M_FOREST)
        m_tensor[:n][tgt, M_RESOURCE_FOOD] = INITIAL_FOOD_FOREST
        m_tensor[:n][tgt, M_FERTILITY]     = 80.0
        m_tensor[:n][tgt, M_BURNING]       = 0.0
        for eid in torch.where(tgt)[0].tolist():
            map_geo.geo_mutate(eid, device=device)
    return {"map_dirty": bool(tgt.any())}


def tool_seed_world(ctx: dict, m_tensor: torch.Tensor, **_) -> dict:
    """One-shot: seed food and fertility on all habitable entities."""
    n = MAX_ENTITIES
    food_map = {
        M_GRASS:  (INITIAL_FOOD_GRASS,  60.0),
        M_FOREST: (INITIAL_FOOD_FOREST, 90.0),
        M_BEACH:  (INITIAL_FOOD_BEACH,  30.0),
        M_LAKE:   (INITIAL_FOOD_LAKE,   50.0),
    }
    for biome, (food, fert) in food_map.items():
        mask = m_tensor[:n, M_TYPE] == biome
        if mask.any():
            m_tensor[:n][mask, M_RESOURCE_FOOD] = food
            m_tensor[:n][mask, M_FERTILITY]     = fert
    lake_mask = m_tensor[:n, M_TYPE] == M_LAKE
    if lake_mask.any():
        m_tensor[:n][lake_mask, M_RESOURCE_WATER] = INITIAL_WATER_LAKE
        m_tensor[:n][lake_mask, M_GROWTH_RATE] = LAKE_WATER_REPLENISH_RATE
    return {"map_dirty": True}


def geo_mutate(ctx: dict, m_tensor: torch.Tensor,
               entity_id: int, new_type: int,
               device: str = "cpu", **_) -> dict:
    """Change M_TYPE of a single entity and recompute its MAP_GEO entry."""
    m_tensor[entity_id, M_TYPE] = float(new_type)
    map_geo.geo_mutate(entity_id, device=device)
    return {"map_dirty": True}


# ── Remaining Tier B tools (unchanged logic, updated imports) ─────────────────

def tool_plague(ctx, h_tensor, decay_rate=2.0, mask=None, **_):
    h_mask   = ctx["h_mask"]
    affected = (mask & h_mask) if mask is not None else h_mask
    if not affected.any(): return
    apply_plague_effect(affected, h_tensor, decay_rate=decay_rate)

def tool_bless(ctx, h_tensor, mask=None, **_):
    h_mask   = ctx["h_mask"]
    affected = (mask & h_mask) if mask is not None else h_mask
    if not affected.any(): return
    apply_bless_effect(affected, h_tensor)

def tool_set_mood(ctx, h_tensor, mask, value, mode="set", **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return
    if mode == "set": h_tensor[affected, MOOD]  = value
    elif mode == "add": h_tensor[affected, MOOD] += value
    elif mode == "multiply": h_tensor[affected, MOOD] *= value
    clamp_rows_(h_tensor, affected, MOOD, lo=0.0, hi=100.0)

def tool_set_threat(ctx, h_tensor, mask, value, mode="set", **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return
    if mode == "set": h_tensor[affected, THREAT]  = value
    elif mode == "add": h_tensor[affected, THREAT] += value
    elif mode == "multiply": h_tensor[affected, THREAT] *= value
    clamp_rows_(h_tensor, affected, THREAT, lo=0.0, hi=100.0)


def tool_calm_area(ctx: dict, h_tensor: torch.Tensor,
                   center_x: float, center_y: float,
                   radius: float = 90.0,
                   mood_gain: float = 20.0,
                   threat_drop: float = 25.0,
                   device: str = "cpu", **_) -> dict:
    affected = _agent_radial_mask(h_tensor, ctx["h_mask"], center_x, center_y, radius, device)
    if not affected.any():
        return {}
    h_tensor[affected, THREAT] -= threat_drop
    h_tensor[affected, THREAT] = h_tensor[affected, THREAT].clamp(min=0.0)
    h_tensor[affected, MOOD] += mood_gain
    h_tensor[affected, MOOD] = h_tensor[affected, MOOD].clamp(max=100.0)
    return {}


def tool_panic_area(ctx: dict, h_tensor: torch.Tensor,
                    center_x: float, center_y: float,
                    radius: float = 90.0,
                    mood_drop: float = 20.0,
                    threat_gain: float = 30.0,
                    device: str = "cpu", **_) -> dict:
    affected = _agent_radial_mask(h_tensor, ctx["h_mask"], center_x, center_y, radius, device)
    if not affected.any():
        return {}
    h_tensor[affected, THREAT] += threat_gain
    h_tensor[affected, THREAT] = h_tensor[affected, THREAT].clamp(max=100.0)
    h_tensor[affected, MOOD] -= mood_drop
    h_tensor[affected, MOOD] = h_tensor[affected, MOOD].clamp(min=0.0)
    instinct_flee(ctx, h_tensor, (center_x, center_y), flee_mask=affected, device=device)
    return {}


def tool_bounty_area(ctx: dict, m_tensor: torch.Tensor,
                     center_x: float, center_y: float,
                     radius: float = 90.0,
                     food_gain: float = 20.0,
                     water_gain: float = 20.0,
                     fertility_gain: float = 10.0, **_) -> dict:
    eids = _entity_radial_ids(m_tensor, center_x, center_y, radius)
    if not eids.numel():
        return {}
    touched = False
    for eid in eids.tolist():
        et = int(m_tensor[eid, M_TYPE])
        if et == 0:
            continue
        if et in NATURAL_TYPES or et in {M_FARM, M_WELL, M_RESOURCE_NODE}:
            m_tensor[eid, M_RESOURCE_FOOD] = min(MAX_ENTITY_FOOD, float(m_tensor[eid, M_RESOURCE_FOOD]) + food_gain)
            m_tensor[eid, M_RESOURCE_WATER] = min(MAX_ENTITY_WATER, float(m_tensor[eid, M_RESOURCE_WATER]) + water_gain)
            if et in NATURAL_TYPES:
                m_tensor[eid, M_FERTILITY] = min(100.0, float(m_tensor[eid, M_FERTILITY]) + fertility_gain)
            touched = True
    return {"map_dirty": touched} if touched else {}


def tool_scarcity_area(ctx: dict, m_tensor: torch.Tensor,
                       center_x: float, center_y: float,
                       radius: float = 90.0,
                       food_loss: float = 20.0,
                       water_loss: float = 20.0,
                       fertility_loss: float = 10.0, **_) -> dict:
    eids = _entity_radial_ids(m_tensor, center_x, center_y, radius)
    if not eids.numel():
        return {}
    touched = False
    for eid in eids.tolist():
        et = int(m_tensor[eid, M_TYPE])
        if et == 0:
            continue
        if et in NATURAL_TYPES or et in {M_FARM, M_WELL, M_RESOURCE_NODE}:
            m_tensor[eid, M_RESOURCE_FOOD] = max(0.0, float(m_tensor[eid, M_RESOURCE_FOOD]) - food_loss)
            m_tensor[eid, M_RESOURCE_WATER] = max(0.0, float(m_tensor[eid, M_RESOURCE_WATER]) - water_loss)
            if et in NATURAL_TYPES:
                m_tensor[eid, M_FERTILITY] = max(0.0, float(m_tensor[eid, M_FERTILITY]) - fertility_loss)
            touched = True
    return {"map_dirty": touched} if touched else {}

def tool_baby_boom(ctx, h_tensor, pop_count_ref, mask=None, **_):
    h_mask = ctx["h_mask"]; affected = (mask & h_mask) if mask is not None else h_mask
    females = affected & (h_tensor[:, H_SEX] == 1.0)
    if females.any():
        h_tensor[females, H_COOLDOWN] = 0.0
        h_tensor[females, H_FERTILITY] += 0.5
        clamp_rows_(h_tensor, females, H_FERTILITY, hi=2.0)
    if affected.any(): h_tensor[affected, MOOD] = 90.0

def tool_cull(ctx, h_tensor, pop_count_ref, target_population, **_):
    h_mask = ctx["h_mask"]
    while pop_count_ref[0] > target_population and h_mask.any():
        live_idx = torch.where(h_mask)[0]
        weakest  = live_idx[h_tensor[live_idx, HP].argmin()]
        h_tensor[weakest] = 0.0; pop_count_ref[0] -= 1
        h_mask = h_tensor[:, TYPE] > AGENT_TYPE_EMPTY
    return {"h_mask": h_mask}

def tool_grant_instinct(ctx, h_tensor, mask, bit, **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return
    instinct_bits.grant(h_tensor, affected, int(bit))   # 64-bit mask in three exact 24-bit words (G-D0-2)

def tool_revoke_instinct(ctx, h_tensor, mask, bit, **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return
    instinct_bits.revoke(h_tensor, affected, int(bit))

def tool_inherit_instinct(ctx, h_tensor, **_):
    h_mask = ctx["h_mask"]
    young  = h_mask & (h_tensor[:, H_AGE] < 1.0) & instinct_bits.has_parent_bits(h_tensor)
    if not young.any(): return
    instinct_bits.write_mask(h_tensor, young,
                             instinct_bits.read_mask(h_tensor, young) | instinct_bits.read_parent_mask(h_tensor, young))

def tool_age_shift(ctx, h_tensor, mask, years, **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return
    h_tensor[affected, H_AGE] += years
    clamp_rows_(h_tensor, affected, H_AGE, lo=0.0)

def tool_life_exp_modify(ctx, h_tensor, mask, value, mode="multiply", **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return
    if mode == "set": h_tensor[affected, H_LIFE_EXP]  = value
    elif mode == "add": h_tensor[affected, H_LIFE_EXP] += value
    elif mode == "multiply": h_tensor[affected, H_LIFE_EXP] *= value
    clamp_rows_(h_tensor, affected, H_LIFE_EXP, lo=1.0)

def tool_set_aggression(ctx, h_tensor, mask, value=1.0, mode="set", **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return
    if mode == "set": h_tensor[affected, H_AGGRESSION]  = value
    elif mode == "add": h_tensor[affected, H_AGGRESSION] += value
    elif mode == "multiply": h_tensor[affected, H_AGGRESSION] *= value
    clamp_rows_(h_tensor, affected, H_AGGRESSION, lo=0.0, hi=1.0)

def tool_smite(ctx, h_tensor, pop_count_ref, mask, **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return {}
    kill_humans(affected, h_tensor, pop_count_ref)
    return {"h_mask": h_tensor[:, TYPE] > AGENT_TYPE_EMPTY}

def tool_migration(ctx, h_tensor, mask, target_x, target_y,
                   force=10.0, device="cpu", **_):
    h_mask = ctx["h_mask"]; affected = mask & h_mask
    if not affected.any(): return
    pos    = h_tensor[affected, :2]
    target = torch.tensor([[target_x, target_y]], dtype=torch.float32, device=device)
    d = target - pos; n = d.norm(dim=1, keepdim=True).clamp(min=1e-6)
    push = (d / n) * force
    x0, y0, x1, y1 = _world_limits()
    h_tensor[affected, X] = (h_tensor[affected, X] + push[:, 0]).clamp(x0, x1)
    h_tensor[affected, Y] = (h_tensor[affected, Y] + push[:, 1]).clamp(y0, y1)

def tool_quarantine(ctx, h_tensor, **_):
    h_mask   = ctx["h_mask"]
    infected = h_mask & (h_tensor[:, H_INFECTION] >= INFECTION_THRESHOLD)
    if not infected.any(): return
    h_tensor[infected, H_COOLDOWN] = QUARANTINE_COOLDOWN_YRS
    h_tensor[infected, H_STAMINA]  = 0.0
    h_tensor[infected, THREAT]    += 30.0
    clamp_rows_(h_tensor, infected, THREAT, hi=100.0)

def tool_reset_cooldown(ctx, h_tensor, mask=None, **_):
    h_mask = ctx["h_mask"]; affected = (mask & h_mask) if mask is not None else h_mask
    h_tensor[affected, H_COOLDOWN] = 0.0

def tool_enlighten(ctx, h_tensor, bit, mask=None, **_):
    h_mask = ctx["h_mask"]; affected = (mask & h_mask) if mask is not None else h_mask
    if not affected.any(): return
    instinct_bits.grant(h_tensor, affected, int(bit))

def tool_spawn_animal_group(ctx: dict, m_tensor: torch.Tensor,
                             entity_count_ref: list,
                             species: int, count: int,
                             cx: float, cy: float, scatter: float = 30.0,
                             device: str = "cpu", **_) -> dict:
    """
    Spawn a group of animals of the given species near (cx, cy).
    scatter: max offset radius in px.
    """
    spawned = instinct_populate_animals(
        m_tensor, entity_count_ref, species, count,
        center_x=cx, center_y=cy, radius=scatter,
        scatter=scatter, device=device,
    )
    return {"spawned": len(spawned)}


def tool_populate_area_with_animals(ctx: dict, m_tensor: torch.Tensor,
                                    entity_count_ref: list,
                                    species: int,
                                    center_x: float, center_y: float,
                                    radius: float = 120.0,
                                    count: int = 12,
                                    device: str = "cpu", **_) -> dict:
    if species == M_FISH:
        allowed = {M_LAKE}
    else:
        allowed = {M_GRASS, M_FOREST, M_BEACH, M_BARREN}
    candidates = map_geo.entities_in_radius(
        center_x, center_y, radius, m_tensor, allowed
    )
    spawned = instinct_populate_animals(
        m_tensor, entity_count_ref, species, count,
        candidate_entity_ids=candidates,
        allowed_types=allowed,
        scatter=max(12.0, radius * 0.35),
        device=device,
    )
    return {"spawned": len(spawned)}


def tool_fill_land_with_animals(ctx: dict, m_tensor: torch.Tensor,
                                entity_count_ref: list,
                                species: int,
                                density: float = 0.35,
                                max_new: int | None = None,
                                device: str = "cpu", **_) -> dict:
    if species == M_FISH:
        allowed = {M_LAKE}
    else:
        allowed = {M_GRASS, M_FOREST, M_BEACH, M_BARREN}

    candidates = [
        int(eid) for eid in map_geo.MAP_GEO.keys()
        if int(m_tensor[eid, M_TYPE]) in allowed
    ]
    if not candidates:
        return {"spawned": 0}

    count = max(1, int(len(candidates) * max(0.0, density)))
    if max_new is not None:
        count = min(count, max_new)
    spawned = instinct_populate_animals(
        m_tensor, entity_count_ref, species, count,
        candidate_entity_ids=candidates,
        scatter=24.0,
        device=device,
    )
    return {"spawned": len(spawned)}


def tool_restock_lakes_with_fish(ctx: dict, m_tensor: torch.Tensor,
                                 entity_count_ref: list,
                                 count_per_lake: int = 6,
                                 device: str = "cpu", **_) -> dict:
    lake_ids = [
        int(eid) for eid in map_geo.MAP_GEO.keys()
        if int(m_tensor[eid, M_TYPE]) == M_LAKE
    ]
    if not lake_ids:
        return {"spawned": 0}
    spawned = instinct_populate_animals(
        m_tensor, entity_count_ref, M_FISH,
        count=max(1, len(lake_ids) * max(1, count_per_lake)),
        candidate_entity_ids=lake_ids,
        scatter=18.0,
        device=device,
    )
    return {"spawned": len(spawned)}


def tool_create_wall(ctx: dict, m_tensor: torch.Tensor,
                     entity_count_ref: list,
                     start_x: float, start_y: float,
                     end_x: float, end_y: float,
                     thickness: float = 12.0,
                     durability: float = 180.0,
                     device: str = "cpu", **_) -> dict:
    return create_wall_feature(
        m_tensor,
        entity_count_ref,
        start_x=start_x,
        start_y=start_y,
        end_x=end_x,
        end_y=end_y,
        clamp_point_fn=_clamp_point,
        make_wall_polygon_fn=_make_wall_polygon,
        create_object_fn=instinct_create_object,
        thickness=thickness,
        durability=durability,
        device=device,
    )


def tool_transform_area(ctx: dict, m_tensor: torch.Tensor,
                        center_x: float, center_y: float,
                        radius: float = 80.0,
                        target_type: int = M_GRASS,
                        device: str = "cpu", **_) -> dict:
    return transform_map_area(
        m_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        target_type=target_type,
        area_entity_ids_fn=_entity_radial_ids,
        retype_objects_fn=instinct_retype_objects,
        device=device,
    )


def tool_create_forest_patch(ctx: dict, m_tensor: torch.Tensor,
                             entity_count_ref: list,
                             center_x: float, center_y: float,
                             radius: float = 120.0,
                             count: int = 3,
                             device: str = "cpu", **_) -> dict:
    return create_forest_patch_feature(
        m_tensor,
        entity_count_ref,
        center_x=center_x,
        center_y=center_y,
        create_scattered_objects_fn=instinct_create_scattered_objects,
        radius=radius,
        count=count,
        device=device,
    )


def tool_create_mountain_chain(ctx: dict, m_tensor: torch.Tensor,
                               entity_count_ref: list,
                               start_x: float, start_y: float,
                               end_x: float, end_y: float,
                               segments: int = 4,
                               scale: float = 34.0,
                               device: str = "cpu", **_) -> dict:
    return create_mountain_chain_feature(
        m_tensor,
        entity_count_ref,
        start_x=start_x,
        start_y=start_y,
        end_x=end_x,
        end_y=end_y,
        create_line_objects_fn=instinct_create_line_objects,
        segments=segments,
        scale=scale,
        device=device,
    )


def tool_create_feature_near_feature(ctx: dict, m_tensor: torch.Tensor,
                                     entity_count_ref: list,
                                     feature_type: int,
                                     anchor_entity_id: int | None = None,
                                     near_type: int | None = None,
                                     search_x: float | None = None,
                                     search_y: float | None = None,
                                     offset_distance: float = 48.0,
                                     bearing_deg: float | None = None,
                                     scale: float | None = None,
                                     radius: float = 120.0,
                                     count: int = 3,
                                     segments: int = 4,
                                     device: str = "cpu", **_) -> dict:
    return map_create_feature_near_feature(
        ctx,
        m_tensor,
        entity_count_ref,
        feature_type=feature_type,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        create_scattered_objects_fn=instinct_create_scattered_objects,
        create_line_objects_fn=instinct_create_line_objects,
        resolve_build_site_fn=_resolve_build_site,
        anchor_entity_id=anchor_entity_id,
        near_type=near_type,
        search_x=search_x,
        search_y=search_y,
        offset_distance=offset_distance,
        bearing_deg=bearing_deg,
        scale=scale,
        radius=radius,
        count=count,
        segments=segments,
        build_structure_fn=construction_tool_build_structure,
        build_settlement_fn=construction_tool_build_settlement,
        make_wall_polygon_fn=_make_wall_polygon,
        device=device,
    )


def frontier_frozen() -> bool:
    """D-005: True while ``genesis_config.FREEZE_LEGACY_FRONTIER`` is set (read at call time, so tests can flip it)."""
    try:
        import genesis_config as _cfg
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import genesis_config as _cfg
    return bool(getattr(_cfg, "FREEZE_LEGACY_FRONTIER", True))


FROZEN_REFUSAL = {"ok": False, "reason": "legacy_frozen", "error": "legacy_frozen"}


def tool_expand_world_edge(ctx: dict, h_tensor: torch.Tensor,
                           m_tensor: torch.Tensor,
                           entity_count_ref: list,
                           edge: str = "auto",
                           trigger_margin: float = 96.0,
                           band_depth: float = 170.0,
                           device: str = "cpu", **_) -> dict:
    if frontier_frozen():                       # D-005: refused by name, nothing touched
        return dict(FROZEN_REFUSAL)
    selected_edge = edge
    if str(edge).strip().lower() == "auto":
        try:
            from systems.map.expand import frontier_edges_for_humans as _frontier_edges
        except ImportError:  # pragma: no cover - package import fallback
            from at_the_beginning.systems.map.expand import frontier_edges_for_humans as _frontier_edges
        triggered = _frontier_edges(ctx["h_mask"], h_tensor, trigger_margin=trigger_margin)
        if triggered:
            selected_edge = triggered[0]
    return map_expand_world_edge(
        m_tensor,
        entity_count_ref,
        edge=selected_edge,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        create_scattered_objects_fn=instinct_create_scattered_objects,
        create_line_objects_fn=instinct_create_line_objects,
        resolve_build_site_fn=_resolve_build_site,
        band_depth=band_depth,
        device=device,
    )


def instinct_frontier_expand(ctx: dict, h_tensor: torch.Tensor,
                             m_tensor: torch.Tensor,
                             entity_count_ref: list,
                             engine: Any,
                             trigger_margin: float = 96.0,
                             cooldown_ticks: int = 120,
                             band_depth: float = 170.0,
                             device: str = "cpu", **_) -> dict:
    if frontier_frozen():                       # D-005: also not registered while frozen (default_registry_entries)
        return {}
    return maybe_expand_frontier(
        ctx["h_mask"],
        h_tensor,
        m_tensor,
        entity_count_ref,
        engine=engine,
        clamp_point_fn=_clamp_point,
        create_object_fn=instinct_create_object,
        create_scattered_objects_fn=instinct_create_scattered_objects,
        create_line_objects_fn=instinct_create_line_objects,
        resolve_build_site_fn=_resolve_build_site,
        trigger_margin=trigger_margin,
        cooldown_ticks=cooldown_ticks,
        band_depth=band_depth,
        device=device,
    )


def tool_upgrade_houses_to_village(ctx: dict, m_tensor: torch.Tensor,
                                   center_x: float, center_y: float,
                                   radius: float = 90.0,
                                   device: str = "cpu", **_) -> dict:
    houses = [
        eid for eid in map_geo.entities_in_radius(
            center_x, center_y, radius, m_tensor, {M_HOUSE}
        )
    ]
    if not houses:
        return {}
    changed = instinct_retype_objects(
        m_tensor, houses, M_VILLAGE, device=device,
        col_vals={
            S_DURABILITY: 260.0,
            S_SHELTER_CAP: 18.0,
            S_OCCUPANT_COUNT: 0.0,
            S_BUILD_PROGRESS: 100.0,
        },
    )
    return {"map_dirty": changed > 0} if changed else {}


def tool_populate_biome_with_animals(ctx: dict, m_tensor: torch.Tensor,
                                     entity_count_ref: list,
                                     species: int,
                                     biome_types: list[int] | None = None,
                                     density: float = 0.4,
                                     max_new: int | None = None,
                                     device: str = "cpu", **_) -> dict:
    if biome_types is None:
        if species == M_FISH:
            biome_types = [M_LAKE]
        else:
            biome_types = [M_GRASS, M_FOREST, M_BEACH, M_BARREN]
    allowed = set(int(t) for t in biome_types)
    candidates = [
        int(eid) for eid in map_geo.MAP_GEO.keys()
        if int(m_tensor[eid, M_TYPE]) in allowed
    ]
    if not candidates:
        return {"spawned": 0}
    count = max(1, int(len(candidates) * max(0.0, density)))
    if max_new is not None:
        count = min(count, max_new)
    spawned = instinct_populate_animals(
        m_tensor, entity_count_ref, species, count,
        candidate_entity_ids=candidates,
        scatter=24.0,
        device=device,
    )
    return {"spawned": len(spawned)}


def tool_herd_animals_to_area(ctx: dict, m_tensor: torch.Tensor,
                              center_x: float, center_y: float,
                              radius: float = 120.0,
                              species: int | None = None,
                              force: float = 20.0, **_) -> dict:
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    nearby = _entity_radial_ids(m_tensor, center_x, center_y, radius)
    ids = [
        int(eid) for eid in nearby.tolist()
        if a_mask[eid] and (species is None or int(m_tensor[eid, M_TYPE]) == species)
    ]
    moved = instinct_relocate_animals(
        m_tensor, ids, center_x, center_y, force=force, toward=True
    )
    return {"moved": moved}


def tool_scatter_animals_from_area(ctx: dict, m_tensor: torch.Tensor,
                                   center_x: float, center_y: float,
                                   radius: float = 120.0,
                                   species: int | None = None,
                                   force: float = 20.0, **_) -> dict:
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    nearby = _entity_radial_ids(m_tensor, center_x, center_y, radius)
    ids = [
        int(eid) for eid in nearby.tolist()
        if a_mask[eid] and (species is None or int(m_tensor[eid, M_TYPE]) == species)
    ]
    moved = instinct_relocate_animals(
        m_tensor, ids, center_x, center_y, force=force, toward=False
    )
    return {"moved": moved}


def tool_feed_animals(ctx: dict, m_tensor: torch.Tensor,
                      center_x: float, center_y: float,
                      radius: float = 45.0,
                      amount: float = 25.0, **_) -> dict:
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    nearby = torch.zeros_like(a_mask)
    nearby[_entity_radial_ids(m_tensor, center_x, center_y, radius)] = True
    affected = nearby & a_mask
    if not affected.any():
        return {}
    m_tensor[affected, A_HUNGER] -= amount
    clamp_rows_(m_tensor, affected, A_HUNGER, lo=0.0)
    return {}


def tool_heal_animals(ctx: dict, m_tensor: torch.Tensor,
                      center_x: float, center_y: float,
                      radius: float = 45.0,
                      amount: float = 20.0, **_) -> dict:
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    nearby = torch.zeros_like(a_mask)
    nearby[_entity_radial_ids(m_tensor, center_x, center_y, radius)] = True
    affected = nearby & a_mask
    if not affected.any():
        return {}
    m_tensor[affected, M_HP] += amount
    clamp_rows_(m_tensor, affected, M_HP, hi=100.0)
    return {}


def tool_make_animals_flee(ctx: dict, m_tensor: torch.Tensor,
                           center_x: float, center_y: float,
                           radius: float = 120.0,
                           species: int | None = None,
                           force: float = 24.0, **_) -> dict:
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    ids = [
        int(eid) for eid in _entity_radial_ids(m_tensor, center_x, center_y, radius).tolist()
        if a_mask[eid] and (species is None or int(m_tensor[eid, M_TYPE]) == species)
    ]
    moved = instinct_relocate_animals(
        m_tensor, ids, center_x, center_y, force=force, toward=False
    )
    return {"moved": moved}


def tool_draw_animals_to_area(ctx: dict, m_tensor: torch.Tensor,
                              center_x: float, center_y: float,
                              radius: float = 120.0,
                              species: int | None = None,
                              force: float = 20.0, **_) -> dict:
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    ids = [
        int(eid) for eid in _entity_radial_ids(m_tensor, center_x, center_y, radius).tolist()
        if a_mask[eid] and (species is None or int(m_tensor[eid, M_TYPE]) == species)
    ]
    moved = instinct_relocate_animals(
        m_tensor, ids, center_x, center_y, force=force, toward=True
    )
    return {"moved": moved}


def tool_stampede(ctx: dict, m_tensor: torch.Tensor,
                  center_x: float, center_y: float,
                  radius: float = 80.0,
                  force: float = 20.0,
                  device: str = "cpu", **_) -> dict:
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    nearby = torch.zeros_like(a_mask)
    nearby[_entity_radial_ids(m_tensor, center_x, center_y, radius)] = True
    affected = nearby & a_mask
    if not affected.any():
        return {}
    moved = instinct_relocate_animals(
        m_tensor, torch.where(affected)[0], center_x, center_y,
        force=force, toward=False,
    )
    return {"moved": moved}


# =============================================================================
# ACQUIRED INSTINCT DISPATCHER
# =============================================================================

ACQUIRED_INSTINCTS: dict[int, callable] = {}

def dispatch_acquired_instincts(ctx: dict, h_tensor: torch.Tensor, **kwargs) -> None:
    h_mask = ctx["h_mask"]
    for bit, fn in ACQUIRED_INSTINCTS.items():
        bit_mask = instinct_bits.test_bit(h_tensor, bit)
        active   = bit_mask & h_mask
        if active.any():
            fn({**ctx, "h_mask": active}, h_tensor=h_tensor, **kwargs)


# =============================================================================
# REGISTRY
# =============================================================================

def default_registry_entries() -> list[tuple[callable, int, dict]]:
    """
    Priority bands:
      10–19  human vital signs
      20–29  human death checks
      30–49  human cognition + action
      50–59  human social
      60–79  animal tick loop
      80–89  world environment
      90+    meta
    """
    entries = [
        # Player incarnation — exempt from survival, runs first.
        (instinct_incarnation_stabilize,  5, {}),
        # Human vital signs
        (instinct_age,                   10, {}),
        (instinct_hunger,                15, {}),
        (instinct_thirst,                16, {}),
        (instinct_stamina_tick,          17, {}),
        (instinct_emotional_recovery,    18, {}),
        (instinct_cooldown,              19, {}),
        # Human death
        (instinct_die,                   20, {}),
        (instinct_hp_death,              25, {}),
        # Human ticking + sync
        (instinct_heal,                  35, {}),
        (instinct_shelter_check,         36, {}),
        (instinct_structure_occupancy,   37, {}),
        (instinct_player_control_override, 37.75, {}),
        (instinct_move,                  38, {}),
        (instinct_infection_tick,        46, {}),
        (check_escalation,               49, {}),
        (tool_inherit_instinct,          51, {}),
        # Animal tick loop
        (animal_instinct_age,            60, {}),
        (animal_instinct_hunger,         61, {}),
        (animal_instinct_thirst,         62, {}),
        (animal_instinct_eat,            63, {}),
        (animal_instinct_drink,          64, {}),
        (animal_instinct_die,            65, {}),
        (animal_instinct_move,           66, {}),
        (animal_instinct_predator_attack,67, {}),
        (animal_tool_reproduce,          68, {}),
        # World environment
        (instinct_nature_cycle,          79, {}),
        (instinct_fire_tick,             80, {}),
        (instinct_lava_tick,             81, {}),
        (instinct_resource_regrow,       82, {}),
        (instinct_water_cycle,           83, {}),
        (instinct_frontier_expand,       84, {}),
        # Meta
        (dispatch_acquired_instincts,    90, {}),
    ]
    if frontier_frozen():                       # D-005: not registered while frozen
        entries = [e for e in entries if e[0] is not instinct_frontier_expand]
    return entries
