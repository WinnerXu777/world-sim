from __future__ import annotations

import math
import random
from typing import Any, Callable

import torch
try:
    from harness.numerics import pairwise_distances, space_slice
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.numerics import pairwise_distances, space_slice

try:
    import genesis_config as cfg
    import map_geo
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import map_geo


PointClampFn = Callable[[float, float], tuple[float, float]]
CreateObjectFn = Callable[..., int]
CreateScatteredObjectsFn = Callable[..., list[int]]
CreateLineObjectsFn = Callable[..., list[int]]
ResolveBuildSiteFn = Callable[..., tuple[float, float, int] | None]
RetypeObjectsFn = Callable[..., int]
AreaIdsFn = Callable[[torch.Tensor, float, float, float], torch.Tensor]
BuildToolFn = Callable[..., dict[str, Any]]
BuildStructureFn = Callable[..., dict[str, Any]]
BuildSettlementFn = Callable[..., dict[str, Any]]
WallPolygonFn = Callable[[float, float, float, float, float], list[tuple[float, float]]]


DEFAULT_NATURAL_SCALES = {
    cfg.M_LAKE: 48.0,
    cfg.M_FOREST: 72.0,
    cfg.M_MOUNTAIN: 36.0,
    cfg.M_BEACH: 60.0,
    cfg.M_GRASS: 78.0,
    cfg.M_BARREN: 58.0,
}


def _float_cols(col_vals: dict[int, float] | None) -> dict[int, float]:
    if not col_vals:
        return {}
    return {int(col): float(value) for col, value in col_vals.items()}


def natural_feature_defaults(
    feature_type: int,
    *,
    fish_stock: float | None = None,
    water_stock: float | None = None,
    food_stock: float | None = None,
    fertility: float | None = None,
    elevation: float | None = None,
) -> dict[int, float]:
    """Default typed columns for a natural feature spawned as a circle entity."""
    if feature_type == cfg.M_LAKE:
        return {
            cfg.M_FERTILITY: 55.0 if fertility is None else float(fertility),
            cfg.M_ELEVATION: 0.0 if elevation is None else float(elevation),
            cfg.M_BURNING: 0.0,
            cfg.M_FLOODED: 0.0,
            cfg.M_RESOURCE_FOOD: min(cfg.MAX_ENTITY_FOOD, float(cfg.INITIAL_FOOD_LAKE if fish_stock is None else fish_stock)),
            cfg.M_RESOURCE_WATER: min(cfg.MAX_ENTITY_WATER, float(cfg.INITIAL_WATER_LAKE if water_stock is None else water_stock)),
            cfg.M_GROWTH_RATE: float(cfg.LAKE_WATER_REPLENISH_RATE),
        }
    if feature_type == cfg.M_FOREST:
        return {
            cfg.M_FERTILITY: 85.0 if fertility is None else float(fertility),
            cfg.M_ELEVATION: 0.0 if elevation is None else float(elevation),
            cfg.M_BURNING: 0.0,
            cfg.M_FLOODED: 0.0,
            cfg.M_RESOURCE_FOOD: min(cfg.MAX_ENTITY_FOOD, float(cfg.INITIAL_FOOD_FOREST if food_stock is None else food_stock)),
            cfg.M_RESOURCE_WATER: 0.0,
        }
    if feature_type == cfg.M_GRASS:
        return {
            cfg.M_FERTILITY: 60.0 if fertility is None else float(fertility),
            cfg.M_RESOURCE_FOOD: min(cfg.MAX_ENTITY_FOOD, float(cfg.INITIAL_FOOD_GRASS if food_stock is None else food_stock)),
            cfg.M_RESOURCE_WATER: 0.0,
            cfg.M_BURNING: 0.0,
            cfg.M_FLOODED: 0.0,
        }
    if feature_type == cfg.M_BEACH:
        return {
            cfg.M_RESOURCE_FOOD: min(cfg.MAX_ENTITY_FOOD, float(getattr(cfg, "INITIAL_FOOD_BEACH", 12.0) if food_stock is None else food_stock)),
            cfg.M_RESOURCE_WATER: 0.0,
            cfg.M_BURNING: 0.0,
            cfg.M_FLOODED: 0.0,
        }
    if feature_type == cfg.M_MOUNTAIN:
        return {
            cfg.M_ELEVATION: 1.0 if elevation is None else float(elevation),
            cfg.M_RESOURCE_FOOD: 0.0,
            cfg.M_RESOURCE_WATER: 0.0,
            cfg.M_BURNING: 0.0,
            cfg.M_FLOODED: 0.0,
        }
    if feature_type == cfg.M_BARREN:
        return {
            cfg.M_FERTILITY: 0.0 if fertility is None else float(fertility),
            cfg.M_RESOURCE_FOOD: 0.0,
            cfg.M_RESOURCE_WATER: 0.0,
            cfg.M_BURNING: 0.0,
            cfg.M_FLOODED: 0.0,
        }
    return {}


def create_natural_feature_at(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    feature_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn: PointClampFn,
    create_object_fn: CreateObjectFn,
    scale: float | None = None,
    hp: float = 100.0,
    fish_stock: float | None = None,
    water_stock: float | None = None,
    food_stock: float | None = None,
    fertility: float | None = None,
    elevation: float | None = None,
    col_vals: dict[int, float] | None = None,
    device: str = "cpu",
) -> int:
    """Spawn one natural feature circle with sane typed defaults."""
    if int(feature_type) not in cfg.NATURAL_TYPES:
        return -1
    center_x, center_y = clamp_point_fn(center_x, center_y)
    feature_scale = float(scale if scale is not None else DEFAULT_NATURAL_SCALES.get(int(feature_type), 50.0))
    final_cols = natural_feature_defaults(
        int(feature_type),
        fish_stock=fish_stock,
        water_stock=water_stock,
        food_stock=food_stock,
        fertility=fertility,
        elevation=elevation,
    )
    final_cols.update(_float_cols(col_vals))
    return create_object_fn(
        m_tensor,
        entity_count_ref,
        int(feature_type),
        center_x,
        center_y,
        hp=hp,
        scale=feature_scale,
        shape="circle",
        register_geo=True,
        device=device,
        col_vals=final_cols,
    )


def create_lake_feature(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    clamp_point_fn: PointClampFn,
    resolve_build_site_fn: ResolveBuildSiteFn,
    create_object_fn: CreateObjectFn,
    scale: float = 48.0,
    water_stock: float = cfg.INITIAL_WATER_LAKE,
    fish_stock: float = cfg.INITIAL_FOOD_LAKE,
    device: str = "cpu",
) -> dict[str, Any]:
    center_x, center_y = clamp_point_fn(center_x, center_y)
    site = resolve_build_site_fn(
        m_tensor,
        center_x,
        center_y,
        scale,
        allowed_base_types=set(cfg.HABITABLE) | {cfg.M_BARREN},
    )
    if site is None:
        return {}
    center_x, center_y, base_eid = site
    base_type = int(m_tensor[base_eid, cfg.M_TYPE])
    if base_type in cfg.STRUCTURE_TYPES or base_type in {cfg.M_SEA, cfg.M_MOUNTAIN, cfg.M_LAVA, cfg.M_LAKE}:
        return {}
    nearby_water = map_geo.entities_in_radius(center_x, center_y, scale * 0.75, m_tensor, {cfg.M_LAKE, cfg.M_SEA})
    if nearby_water:
        return {}
    eid = create_natural_feature_at(
        m_tensor,
        entity_count_ref,
        feature_type=cfg.M_LAKE,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        scale=scale,
        hp=100.0,
        fish_stock=fish_stock,
        water_stock=water_stock,
        device=device,
    )
    return {"map_dirty": eid != -1}


def create_settlement_area(
    ctx: dict,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    clamp_point_fn: PointClampFn,
    create_object_fn: CreateObjectFn,
    build_structure_fn: BuildStructureFn,
    device: str = "cpu",
) -> dict[str, Any]:
    """Build a small settlement cluster using the construction-domain structure builder."""
    dirty = False
    if build_structure_fn(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=cfg.M_VILLAGE,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    for dx, dy in [(-52.0, -12.0), (48.0, 18.0), (6.0, -56.0)]:
        hx, hy = clamp_point_fn(center_x + dx, center_y + dy)
        if build_structure_fn(
            ctx,
            m_tensor,
            entity_count_ref,
            structure_type=cfg.M_HOUSE,
            center_x=hx,
            center_y=hy,
            clamp_point_fn=clamp_point_fn,
            create_object_fn=create_object_fn,
            device=device,
        ).get("map_dirty"):
            dirty = True

    fx, fy = clamp_point_fn(center_x + 62.0, center_y - 8.0)
    if build_structure_fn(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=cfg.M_FARM,
        center_x=fx,
        center_y=fy,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    wx, wy = clamp_point_fn(center_x - 18.0, center_y + 58.0)
    if build_structure_fn(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=cfg.M_WELL,
        center_x=wx,
        center_y=wy,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    return {"map_dirty": dirty} if dirty else {}


def create_wall_feature(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    clamp_point_fn: PointClampFn,
    make_wall_polygon_fn: WallPolygonFn,
    create_object_fn: CreateObjectFn,
    thickness: float = 12.0,
    durability: float = 180.0,
    device: str = "cpu",
) -> dict[str, Any]:
    start_x, start_y = clamp_point_fn(start_x, start_y)
    end_x, end_y = clamp_point_fn(end_x, end_y)
    mid_x = (start_x + end_x) / 2.0
    mid_y = (start_y + end_y) / 2.0
    points = make_wall_polygon_fn(start_x, start_y, end_x, end_y, thickness)
    scale = max((((end_x - start_x) ** 2 + (end_y - start_y) ** 2) ** 0.5) / 2.0, thickness)
    eid = create_object_fn(
        m_tensor,
        entity_count_ref,
        cfg.M_WALL,
        mid_x,
        mid_y,
        hp=durability,
        scale=scale,
        shape="polygon",
        points=points,
        register_geo=True,
        device=device,
        col_vals={
            cfg.S_DURABILITY: durability,
            cfg.S_SHELTER_CAP: 0.0,
            cfg.S_OCCUPANT_COUNT: 0.0,
            cfg.S_BUILD_PROGRESS: 100.0,
        },
    )
    return {"map_dirty": eid != -1}


def transform_map_area(
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    target_type: int,
    area_entity_ids_fn: AreaIdsFn,
    retype_objects_fn: RetypeObjectsFn,
    device: str = "cpu",
) -> dict[str, Any]:
    """Retype a local area of natural entities into a target biome."""
    candidates: list[int] = []
    for eid in area_entity_ids_fn(m_tensor, center_x, center_y, radius).tolist():
        entity_type = int(m_tensor[eid, cfg.M_TYPE])
        if entity_type == 0 or entity_type in cfg.STRUCTURE_TYPES or entity_type in cfg.ANIMAL_TYPES:
            continue
        candidates.append(eid)
    if not candidates:
        return {}

    defaults: dict[int, float] = natural_feature_defaults(int(target_type))
    if int(target_type) == cfg.M_LAKE:
        defaults[cfg.M_RESOURCE_WATER] = cfg.INITIAL_WATER_LAKE
        defaults[cfg.M_GROWTH_RATE] = cfg.LAKE_WATER_REPLENISH_RATE
    changed = retype_objects_fn(m_tensor, candidates, target_type, device=device, col_vals=defaults)
    return {"map_dirty": changed > 0} if changed else {}


def create_forest_patch_feature(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    create_scattered_objects_fn: CreateScatteredObjectsFn,
    radius: float = 120.0,
    count: int = 3,
    device: str = "cpu",
) -> dict[str, Any]:
    created = create_scattered_objects_fn(
        m_tensor,
        entity_count_ref,
        cfg.M_FOREST,
        count=count,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        scale_min=40.0,
        scale_max=95.0,
        hp=100.0,
        device=device,
        col_vals_factory=lambda *_: {
            cfg.M_FERTILITY: 85.0,
            cfg.M_ELEVATION: 0.0,
            cfg.M_BURNING: 0.0,
            cfg.M_FLOODED: 0.0,
            cfg.M_RESOURCE_FOOD: cfg.INITIAL_FOOD_FOREST,
            cfg.M_RESOURCE_WATER: 0.0,
        },
    )
    return {"map_dirty": len(created) > 0} if created else {}


def create_mountain_chain_feature(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    create_line_objects_fn: CreateLineObjectsFn,
    segments: int = 4,
    scale: float = 34.0,
    device: str = "cpu",
) -> dict[str, Any]:
    created = create_line_objects_fn(
        m_tensor,
        entity_count_ref,
        cfg.M_MOUNTAIN,
        start_x,
        start_y,
        end_x,
        end_y,
        segments=segments,
        scale=scale,
        hp=140.0,
        device=device,
        col_vals_factory=lambda *_: {
            cfg.M_ELEVATION: 1.0,
            cfg.M_RESOURCE_FOOD: 0.0,
            cfg.M_RESOURCE_WATER: 0.0,
            cfg.M_BURNING: 0.0,
            cfg.M_FLOODED: 0.0,
        },
    )
    return {"map_dirty": len(created) > 0} if created else {}


def _nearest_matching_entity(
    m_tensor: torch.Tensor,
    *,
    near_type: int,
    search_x: float,
    search_y: float,
    search_space: int | None = None,
) -> int:
    live = m_tensor[: cfg.MAX_ENTITIES, cfg.M_TYPE] == float(near_type)
    if not live.any():
        return -1
    candidate_ids = torch.where(live)[0]
    candidate_pos = m_tensor[candidate_ids][:, [cfg.CX, cfg.CY]]
    origin = torch.tensor([[float(search_x), float(search_y)]], dtype=torch.float32, device=m_tensor.device)
    candidate_space = space_slice(m_tensor, candidate_ids, "m") if search_space is not None else None
    origin_space = torch.tensor([float(search_space)], dtype=torch.float32, device=m_tensor.device) if candidate_space is not None else None
    dists = pairwise_distances(candidate_pos, origin, space_a=candidate_space, space_b=origin_space).squeeze(1)
    return int(candidate_ids[int(torch.argmin(dists).item())].item())


def _resolve_anchor_entity(
    m_tensor: torch.Tensor,
    *,
    anchor_entity_id: int | None,
    near_type: int | None,
    search_x: float | None,
    search_y: float | None,
) -> int:
    if anchor_entity_id is not None:
        entity_id = int(anchor_entity_id)
        if 0 <= entity_id < m_tensor.shape[0] and int(m_tensor[entity_id, cfg.M_TYPE]) > 0:
            return entity_id
    if near_type is None:
        return -1
    return _nearest_matching_entity(
        m_tensor,
        near_type=int(near_type),
        search_x=float(cfg.MAP_WIDTH / 2.0 if search_x is None else search_x),
        search_y=float(cfg.MAP_HEIGHT / 2.0 if search_y is None else search_y),
    )


def _relative_target_point(
    m_tensor: torch.Tensor,
    anchor_entity_id: int,
    *,
    offset_distance: float,
    bearing_deg: float | None,
    clamp_point_fn: PointClampFn,
) -> tuple[float, float, float]:
    anchor_x = float(m_tensor[anchor_entity_id, cfg.CX])
    anchor_y = float(m_tensor[anchor_entity_id, cfg.CY])
    anchor_scale = max(8.0, float(m_tensor[anchor_entity_id, cfg.SCALE]))
    angle_deg = float(random.uniform(0.0, 360.0) if bearing_deg is None else bearing_deg)
    angle = math.radians(angle_deg)
    distance = anchor_scale + max(12.0, float(offset_distance))
    target_x, target_y = clamp_point_fn(
        anchor_x + math.cos(angle) * distance,
        anchor_y + math.sin(angle) * distance,
    )
    return target_x, target_y, angle_deg


def create_feature_near_feature(
    ctx: dict,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    feature_type: int,
    clamp_point_fn: PointClampFn,
    create_object_fn: CreateObjectFn,
    create_scattered_objects_fn: CreateScatteredObjectsFn,
    create_line_objects_fn: CreateLineObjectsFn,
    resolve_build_site_fn: ResolveBuildSiteFn,
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
    build_structure_fn: BuildStructureFn | None = None,
    build_settlement_fn: BuildSettlementFn | None = None,
    make_wall_polygon_fn: WallPolygonFn | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    """
    Create a new feature relative to an anchor feature.

    This is the reusable backend primitive for decrees like:
      "create a mountain next to the lake"
      "place a forest near the village"
      "settle an area near the lake"
    """
    anchor_id = _resolve_anchor_entity(
        m_tensor,
        anchor_entity_id=anchor_entity_id,
        near_type=near_type,
        search_x=search_x,
        search_y=search_y,
    )
    if anchor_id == -1 and search_x is None and search_y is None:
        return {}

    if anchor_id != -1:
        target_x, target_y, resolved_bearing = _relative_target_point(
            m_tensor,
            anchor_id,
            offset_distance=offset_distance,
            bearing_deg=bearing_deg,
            clamp_point_fn=clamp_point_fn,
        )
    else:
        target_x, target_y = clamp_point_fn(
            float(cfg.MAP_WIDTH / 2.0 if search_x is None else search_x),
            float(cfg.MAP_HEIGHT / 2.0 if search_y is None else search_y),
        )
        resolved_bearing = float(random.uniform(0.0, 360.0) if bearing_deg is None else bearing_deg)

    feature_type = int(feature_type)
    if feature_type == cfg.M_LAKE:
        return create_lake_feature(
            m_tensor,
            entity_count_ref,
            center_x=target_x,
            center_y=target_y,
            clamp_point_fn=clamp_point_fn,
            resolve_build_site_fn=resolve_build_site_fn,
            create_object_fn=create_object_fn,
            scale=48.0 if scale is None else float(scale),
            device=device,
        )
    if feature_type == cfg.M_FOREST:
        if count <= 1:
            created = create_natural_feature_at(
                m_tensor,
                entity_count_ref,
                feature_type=cfg.M_FOREST,
                center_x=target_x,
                center_y=target_y,
                clamp_point_fn=clamp_point_fn,
                create_object_fn=create_object_fn,
                scale=scale,
                device=device,
            )
            return {"map_dirty": created != -1} if created != -1 else {}
        return create_forest_patch_feature(
            m_tensor,
            entity_count_ref,
            center_x=target_x,
            center_y=target_y,
            create_scattered_objects_fn=create_scattered_objects_fn,
            radius=radius,
            count=count,
            device=device,
        )
    if feature_type == cfg.M_MOUNTAIN:
        if segments <= 1:
            created = create_natural_feature_at(
                m_tensor,
                entity_count_ref,
                feature_type=cfg.M_MOUNTAIN,
                center_x=target_x,
                center_y=target_y,
                clamp_point_fn=clamp_point_fn,
                create_object_fn=create_object_fn,
                scale=scale,
                hp=140.0,
                device=device,
            )
            return {"map_dirty": created != -1} if created != -1 else {}
        angle = math.radians(resolved_bearing)
        half_len = max(20.0, float(scale if scale is not None else 34.0) * max(1.0, (segments - 1) * 0.9))
        start_x, start_y = clamp_point_fn(
            target_x - math.cos(angle) * half_len,
            target_y - math.sin(angle) * half_len,
        )
        end_x, end_y = clamp_point_fn(
            target_x + math.cos(angle) * half_len,
            target_y + math.sin(angle) * half_len,
        )
        return create_mountain_chain_feature(
            m_tensor,
            entity_count_ref,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            create_line_objects_fn=create_line_objects_fn,
            segments=segments,
            scale=34.0 if scale is None else float(scale),
            device=device,
        )
    if feature_type in {cfg.M_GRASS, cfg.M_BEACH, cfg.M_BARREN}:
        created = create_natural_feature_at(
            m_tensor,
            entity_count_ref,
            feature_type=feature_type,
            center_x=target_x,
            center_y=target_y,
            clamp_point_fn=clamp_point_fn,
            create_object_fn=create_object_fn,
            scale=scale,
            device=device,
        )
        return {"map_dirty": created != -1} if created != -1 else {}
    if feature_type == cfg.M_VILLAGE:
        if build_settlement_fn is not None:
            return build_settlement_fn(
                ctx,
                m_tensor,
                entity_count_ref,
                center_x=target_x,
                center_y=target_y,
                clamp_point_fn=clamp_point_fn,
                create_object_fn=create_object_fn,
                device=device,
            )
        if build_structure_fn is not None:
            return create_settlement_area(
                ctx,
                m_tensor,
                entity_count_ref,
                center_x=target_x,
                center_y=target_y,
                clamp_point_fn=clamp_point_fn,
                create_object_fn=create_object_fn,
                build_structure_fn=build_structure_fn,
                device=device,
            )
    if feature_type in {cfg.M_HOUSE, cfg.M_FARM, cfg.M_WELL} and build_structure_fn is not None:
        return build_structure_fn(
            ctx,
            m_tensor,
            entity_count_ref,
            structure_type=feature_type,
            center_x=target_x,
            center_y=target_y,
            clamp_point_fn=clamp_point_fn,
            create_object_fn=create_object_fn,
            device=device,
        )
    if feature_type == cfg.M_WALL and make_wall_polygon_fn is not None:
        angle = math.radians(resolved_bearing + 90.0)
        wall_half = max(18.0, float(scale if scale is not None else 30.0))
        start_x, start_y = clamp_point_fn(
            target_x - math.cos(angle) * wall_half,
            target_y - math.sin(angle) * wall_half,
        )
        end_x, end_y = clamp_point_fn(
            target_x + math.cos(angle) * wall_half,
            target_y + math.sin(angle) * wall_half,
        )
        return create_wall_feature(
            m_tensor,
            entity_count_ref,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            clamp_point_fn=clamp_point_fn,
            make_wall_polygon_fn=make_wall_polygon_fn,
            create_object_fn=create_object_fn,
            thickness=max(8.0, float(scale if scale is not None else 12.0) * 0.35),
            durability=180.0,
            device=device,
        )
    return {}
