from __future__ import annotations

from typing import Any, Callable

import torch

try:
    from genesis_config import (
        BUILD_MATERIAL_USE,
        BUILD_MIN_STAMINA,
        BUILD_MOOD_GAIN,
        BUILD_PROGRESS_PER_HUMAN,
        BUILD_RADIUS,
        BUILD_SITE_HP_FRACTION,
        BUILD_SKILL_GAIN,
        BUILD_STAMINA_COST,
        CX,
        CY,
        H_CARRYING,
        H_SKILL,
        H_STAMINA,
        M_FARM,
        M_HP,
        M_FERTILITY,
        M_HOUSE,
        M_TYPE,
        MOOD,
        M_VILLAGE,
        M_WALL,
        M_WELL,
        S_BUILD_PROGRESS,
        S_DURABILITY,
        S_OCCUPANT_COUNT,
        S_SHELTER_CAP,
        STRUCTURE_TYPES,
    )
    from systems.construction.materials import gather_materials
    from systems.construction.sites import FARMABLE_BASE_TYPES, find_buildable_site, resolve_build_site, structure_blueprint
    from systems.perception import agent_radial_mask
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        BUILD_MATERIAL_USE,
        BUILD_MIN_STAMINA,
        BUILD_MOOD_GAIN,
        BUILD_PROGRESS_PER_HUMAN,
        BUILD_RADIUS,
        BUILD_SITE_HP_FRACTION,
        BUILD_SKILL_GAIN,
        BUILD_STAMINA_COST,
        CX,
        CY,
        H_CARRYING,
        H_SKILL,
        H_STAMINA,
        M_FARM,
        M_HP,
        M_FERTILITY,
        M_HOUSE,
        M_TYPE,
        MOOD,
        M_VILLAGE,
        M_WALL,
        M_WELL,
        S_BUILD_PROGRESS,
        S_DURABILITY,
        S_OCCUPANT_COUNT,
        S_SHELTER_CAP,
        STRUCTURE_TYPES,
    )
    from at_the_beginning.systems.construction.materials import gather_materials
    from at_the_beginning.systems.construction.sites import (
        FARMABLE_BASE_TYPES,
        find_buildable_site,
        resolve_build_site,
        structure_blueprint,
    )
    from at_the_beginning.systems.perception import agent_radial_mask


ClampPointFn = Callable[[float, float], tuple[float, float]]
CreateObjectFn = Callable[..., int]
WallPolygonFn = Callable[[float, float, float, float, float], list[tuple[float, float]]]


def designate_construction_site(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    structure_type: int,
    center_x: float,
    center_y: float,
    scale: float,
    durability: float,
    shelter_cap: float = 0.0,
    build_progress: float = 0.0,
    shape: str = "circle",
    points: list[tuple[float, float]] | None = None,
    device: str = "cpu",
    extra_cols: dict[int, float] | None = None,
    create_object_fn: CreateObjectFn | None = None,
) -> int:
    """Create a construction site entity that still needs human build progress."""
    if create_object_fn is None:
        return -1
    col_vals = {
        S_DURABILITY: durability,
        S_SHELTER_CAP: shelter_cap,
        S_OCCUPANT_COUNT: 0.0,
        S_BUILD_PROGRESS: build_progress,
    }
    if extra_cols:
        col_vals.update(extra_cols)
    starting_hp = max(1.0, durability * max(BUILD_SITE_HP_FRACTION, build_progress / 100.0))
    return create_object_fn(
        m_tensor,
        entity_count_ref,
        structure_type,
        center_x,
        center_y,
        hp=starting_hp,
        scale=scale,
        shape=shape,
        points=points,
        register_geo=True,
        device=device,
        col_vals=col_vals,
    )


def spawn_structure_entity(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    cx: float,
    cy: float,
    structure_type: int,
    scale: float,
    durability: float,
    shelter_cap: float = 0.0,
    build_progress: float = 100.0,
    device: str = "cpu",
    extra_cols: dict[int, float] | None = None,
    create_object_fn: CreateObjectFn | None = None,
) -> int:
    """Spawn a finished or partially finished structure entity."""
    return designate_construction_site(
        m_tensor,
        entity_count_ref,
        structure_type,
        cx,
        cy,
        scale=scale,
        durability=durability,
        shelter_cap=shelter_cap,
        build_progress=build_progress,
        device=device,
        extra_cols=extra_cols,
        create_object_fn=create_object_fn,
    )


def build_with_humans(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    target_entity_ids: list[int] | torch.Tensor,
    builder_mask: torch.Tensor | None = None,
    build_radius: float = BUILD_RADIUS,
    progress_per_human: float = BUILD_PROGRESS_PER_HUMAN,
    stamina_cost: float = BUILD_STAMINA_COST,
    material_use: float = BUILD_MATERIAL_USE,
    device: str = "cpu",
) -> dict[str, Any]:
    """Advance build progress on nearby designated structures."""
    h_mask = ctx["h_mask"]
    available = h_mask if builder_mask is None else (builder_mask & h_mask)
    targets = target_entity_ids.tolist() if isinstance(target_entity_ids, torch.Tensor) else list(target_entity_ids)
    if not available.any() or not targets:
        return {}

    changed = False
    assigned = torch.zeros_like(h_mask)
    for entity_id in targets:
        if int(m_tensor[entity_id, M_TYPE]) not in STRUCTURE_TYPES:
            continue
        local = agent_radial_mask(
            h_tensor,
            available & ~assigned,
            float(m_tensor[entity_id, CX]),
            float(m_tensor[entity_id, CY]),
            build_radius,
            device,
        )
        local &= h_tensor[:, H_STAMINA] >= BUILD_MIN_STAMINA
        if not local.any():
            continue

        for human_id in torch.where(local)[0].tolist():
            skill_factor = 1.0 + float(h_tensor[human_id, H_SKILL]) / 100.0
            carry_factor = 0.4 + 0.6 * min(1.0, float(h_tensor[human_id, H_CARRYING]) / max(1.0, material_use))
            progress_gain = progress_per_human * skill_factor * carry_factor
            m_tensor[entity_id, S_BUILD_PROGRESS] = min(
                100.0,
                float(m_tensor[entity_id, S_BUILD_PROGRESS]) + progress_gain,
            )
            target_hp = float(m_tensor[entity_id, S_DURABILITY]) * (float(m_tensor[entity_id, S_BUILD_PROGRESS]) / 100.0)
            m_tensor[entity_id, M_HP] = max(1.0, min(float(m_tensor[entity_id, S_DURABILITY]), target_hp))
            h_tensor[human_id, H_STAMINA] = max(0.0, float(h_tensor[human_id, H_STAMINA]) - stamina_cost)
            h_tensor[human_id, H_SKILL] += BUILD_SKILL_GAIN
            h_tensor[human_id, MOOD] = min(100.0, float(h_tensor[human_id, MOOD]) + BUILD_MOOD_GAIN)
            h_tensor[human_id, H_CARRYING] = max(0.0, float(h_tensor[human_id, H_CARRYING]) - material_use)
            assigned[human_id] = True
            changed = True
            if float(m_tensor[entity_id, S_BUILD_PROGRESS]) >= 100.0:
                m_tensor[entity_id, M_HP] = max(float(m_tensor[entity_id, M_HP]), float(m_tensor[entity_id, S_DURABILITY]))

    return {"map_dirty": changed} if changed else {}


def tool_designate_structure_site(
    ctx: dict[str, Any],
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    structure_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn: ClampPointFn,
    create_object_fn: CreateObjectFn,
    build_progress: float = 0.0,
    search_radius: float = 320.0,
    device: str = "cpu",
) -> dict[str, Any]:
    center_x, center_y = clamp_point_fn(center_x, center_y)
    site = resolve_build_site(
        m_tensor,
        center_x,
        center_y,
        float(structure_blueprint(structure_type)["scale"]),
        allowed_base_types=FARMABLE_BASE_TYPES if structure_type == M_FARM else None,
    )
    if site is None:
        site = find_buildable_site(
            m_tensor,
            center_x,
            center_y,
            structure_type=structure_type,
            search_radius=search_radius,
            allowed_base_types=FARMABLE_BASE_TYPES if structure_type == M_FARM else None,
        )
    if site is None:
        return {}

    site_x, site_y, base_entity_id = site
    blueprint = structure_blueprint(structure_type, base_fertility=float(m_tensor[base_entity_id, M_FERTILITY]))
    entity_id = designate_construction_site(
        m_tensor,
        entity_count_ref,
        structure_type,
        site_x,
        site_y,
        scale=float(blueprint["scale"]),
        durability=float(blueprint["durability"]),
        shelter_cap=float(blueprint["shelter_cap"]),
        build_progress=build_progress,
        device=device,
        extra_cols=dict(blueprint["extra_cols"]),
        create_object_fn=create_object_fn,
    )
    if entity_id == -1:
        return {}
    return {
        "map_dirty": True,
        "entity_id": entity_id,
        "site_x": round(site_x, 1),
        "site_y": round(site_y, 1),
        "base_entity_id": base_entity_id,
    }


def tool_build_structure(
    ctx: dict[str, Any],
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    structure_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn: ClampPointFn,
    create_object_fn: CreateObjectFn,
    scale: float | None = None,
    durability: float | None = None,
    shelter_cap: float | None = None,
    extra_cols: dict[int, float] | None = None,
    allowed_base_types: set[int] | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    """Directly spawn a structure using construction-domain site logic."""
    center_x, center_y = clamp_point_fn(center_x, center_y)
    initial_blueprint = structure_blueprint(structure_type)
    candidate_scale = float(initial_blueprint["scale"] if scale is None else scale)
    resolved_allowed = allowed_base_types
    if resolved_allowed is None and structure_type == M_FARM:
        resolved_allowed = FARMABLE_BASE_TYPES
    site = resolve_build_site(
        m_tensor,
        center_x,
        center_y,
        candidate_scale,
        allowed_base_types=resolved_allowed,
    )
    if site is None:
        return {}

    site_x, site_y, base_entity_id = site
    blueprint = structure_blueprint(structure_type, base_fertility=float(m_tensor[base_entity_id, M_FERTILITY]))
    final_extra_cols = dict(blueprint["extra_cols"])
    if extra_cols:
        final_extra_cols.update(extra_cols)
    entity_id = spawn_structure_entity(
        m_tensor,
        entity_count_ref,
        site_x,
        site_y,
        structure_type,
        scale=float(blueprint["scale"] if scale is None else scale),
        durability=float(blueprint["durability"] if durability is None else durability),
        shelter_cap=float(blueprint["shelter_cap"] if shelter_cap is None else shelter_cap),
        device=device,
        extra_cols=final_extra_cols,
        create_object_fn=create_object_fn,
    )
    return {"map_dirty": entity_id != -1} if entity_id != -1 else {}


def tool_find_buildable_site(
    m_tensor: torch.Tensor,
    *,
    structure_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn: ClampPointFn,
    search_radius: float = 320.0,
) -> dict[str, Any]:
    center_x, center_y = clamp_point_fn(center_x, center_y)
    site = find_buildable_site(
        m_tensor,
        center_x,
        center_y,
        structure_type=structure_type,
        search_radius=search_radius,
        allowed_base_types=FARMABLE_BASE_TYPES if structure_type == M_FARM else None,
    )
    if site is None:
        return {}
    site_x, site_y, base_entity_id = site
    return {
        "site_x": round(site_x, 1),
        "site_y": round(site_y, 1),
        "base_entity_id": base_entity_id,
        "base_type": int(m_tensor[base_entity_id, M_TYPE]),
        "distance": round(((site_x - center_x) ** 2 + (site_y - center_y) ** 2) ** 0.5, 1),
        "structure_type": structure_type,
    }


def tool_build_structure_with_humans(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    structure_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn: ClampPointFn,
    create_object_fn: CreateObjectFn,
    gather_materials_first: bool = True,
    search_radius: float = 320.0,
    device: str = "cpu",
) -> dict[str, Any]:
    designated = tool_designate_structure_site(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=structure_type,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        build_progress=0.0,
        search_radius=search_radius,
        device=device,
    )
    entity_id = int(designated.get("entity_id", -1))
    if entity_id == -1:
        return {}

    site_x = float(designated.get("site_x", center_x))
    site_y = float(designated.get("site_y", center_y))
    if gather_materials_first:
        gather_materials(ctx, h_tensor, m_tensor, center_x=site_x, center_y=site_y, radius=BUILD_RADIUS, device=device)
    built = build_with_humans(ctx, h_tensor, m_tensor, [entity_id], device=device)
    return {"map_dirty": bool(designated or built), "entity_id": entity_id}


def tool_build_settlement(
    ctx: dict[str, Any],
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    clamp_point_fn: ClampPointFn,
    create_object_fn: CreateObjectFn,
    device: str = "cpu",
) -> dict[str, Any]:
    """Direct-build a small settlement cluster using the generic structure builder."""
    dirty = False
    if tool_build_structure(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=M_VILLAGE,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    for dx, dy in [(-52.0, -12.0), (48.0, 18.0), (6.0, -56.0)]:
        if tool_build_structure(
            ctx,
            m_tensor,
            entity_count_ref,
            structure_type=M_HOUSE,
            center_x=center_x + dx,
            center_y=center_y + dy,
            clamp_point_fn=clamp_point_fn,
            create_object_fn=create_object_fn,
            device=device,
        ).get("map_dirty"):
            dirty = True

    if tool_build_structure(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=M_FARM,
        center_x=center_x + 62.0,
        center_y=center_y - 8.0,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    if tool_build_structure(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=M_WELL,
        center_x=center_x - 18.0,
        center_y=center_y + 58.0,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    return {"map_dirty": dirty} if dirty else {}


def tool_build_settlement_with_humans(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    clamp_point_fn: ClampPointFn,
    create_object_fn: CreateObjectFn,
    device: str = "cpu",
) -> dict[str, Any]:
    """Human-assisted settlement cluster built through the generic human builder."""
    dirty = False
    if gather_materials(ctx, h_tensor, m_tensor, center_x=center_x, center_y=center_y, radius=BUILD_RADIUS * 1.5, device=device).get("map_dirty"):
        dirty = True
    if tool_build_structure_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        structure_type=M_VILLAGE,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    for dx, dy in [(-48.0, -18.0), (52.0, 12.0)]:
        if tool_build_structure_with_humans(
            ctx,
            h_tensor,
            m_tensor,
            entity_count_ref,
            structure_type=M_HOUSE,
            center_x=center_x + dx,
            center_y=center_y + dy,
            clamp_point_fn=clamp_point_fn,
            create_object_fn=create_object_fn,
            device=device,
        ).get("map_dirty"):
            dirty = True

    if tool_build_structure_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        structure_type=M_FARM,
        center_x=center_x + 64.0,
        center_y=center_y - 6.0,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    if tool_build_structure_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        structure_type=M_WELL,
        center_x=center_x - 20.0,
        center_y=center_y + 56.0,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    ).get("map_dirty"):
        dirty = True

    return {"map_dirty": dirty} if dirty else {}


def tool_construct_wall_with_humans(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    clamp_point_fn: ClampPointFn,
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
    entity_id = designate_construction_site(
        m_tensor,
        entity_count_ref,
        M_WALL,
        mid_x,
        mid_y,
        scale=scale,
        durability=durability,
        shelter_cap=0.0,
        build_progress=0.0,
        shape="polygon",
        points=points,
        device=device,
        create_object_fn=create_object_fn,
    )
    if entity_id == -1:
        return {}
    gather_materials(ctx, h_tensor, m_tensor, center_x=mid_x, center_y=mid_y, radius=BUILD_RADIUS, device=device)
    built = build_with_humans(ctx, h_tensor, m_tensor, [entity_id], device=device)
    return {"map_dirty": bool(built) or entity_id != -1, "entity_id": entity_id}


__all__ = [
    "build_with_humans",
    "designate_construction_site",
    "spawn_structure_entity",
    "tool_build_settlement",
    "tool_build_settlement_with_humans",
    "tool_build_structure",
    "tool_build_structure_with_humans",
    "tool_construct_wall_with_humans",
    "tool_designate_structure_site",
    "tool_find_buildable_site",
]
