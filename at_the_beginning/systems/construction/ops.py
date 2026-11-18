from __future__ import annotations

"""
Stable, generation-friendly construction ops.

Generated tools should prefer importing from here instead of composing
construction behavior from many low-level modules directly.
"""

from typing import Any

import torch

try:
    from systems.construction.building import (
        build_with_humans,
        designate_construction_site,
        spawn_structure_entity,
        tool_build_settlement,
        tool_build_settlement_with_humans,
        tool_build_structure,
        tool_build_structure_with_humans,
        tool_construct_wall_with_humans,
        tool_designate_structure_site,
        tool_find_buildable_site,
    )
    from systems.construction.materials import gather_materials
    from systems.construction.repair import (
        demolish_with_humans,
        repair_with_humans,
        tool_demolish_area_with_humans,
        tool_repair_area_with_humans,
        tool_repair_structures,
    )
    from systems.construction.sites import find_buildable_site, resolve_build_site, structure_blueprint
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.construction.building import (
        build_with_humans,
        designate_construction_site,
        spawn_structure_entity,
        tool_build_settlement,
        tool_build_settlement_with_humans,
        tool_build_structure,
        tool_build_structure_with_humans,
        tool_construct_wall_with_humans,
        tool_designate_structure_site,
        tool_find_buildable_site,
    )
    from at_the_beginning.systems.construction.materials import gather_materials
    from at_the_beginning.systems.construction.repair import (
        demolish_with_humans,
        repair_with_humans,
        tool_demolish_area_with_humans,
        tool_repair_area_with_humans,
        tool_repair_structures,
    )
    from at_the_beginning.systems.construction.sites import find_buildable_site, resolve_build_site, structure_blueprint


def build_blueprint(structure_type: int, *, base_fertility: float = 60.0) -> dict[str, Any]:
    return structure_blueprint(structure_type, base_fertility=base_fertility)


def resolve_site(
    m_tensor: torch.Tensor,
    center_x: float,
    center_y: float,
    radius: float,
    *,
    allowed_base_types: set[int] | None = None,
) -> tuple[float, float, int] | None:
    return resolve_build_site(
        m_tensor,
        center_x,
        center_y,
        radius,
        allowed_base_types=allowed_base_types,
    )


def find_site(
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    structure_type: int | None = None,
    search_radius: float = 320.0,
    allowed_base_types: set[int] | None = None,
) -> tuple[float, float, int] | None:
    return find_buildable_site(
        m_tensor,
        center_x,
        center_y,
        structure_type=structure_type,
        search_radius=search_radius,
        allowed_base_types=allowed_base_types,
    )


def gather_construction_materials(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    amount: float = 8.0,
    builder_mask: torch.Tensor | None = None,
    source_types: set[int] | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    return gather_materials(
        ctx,
        h_tensor,
        m_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        amount=amount,
        builder_mask=builder_mask,
        source_types=source_types,
        device=device,
    )


def designate_site(
    ctx: dict[str, Any],
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    structure_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn,
    create_object_fn,
    build_progress: float = 0.0,
    search_radius: float = 320.0,
    device: str = "cpu",
) -> dict[str, Any]:
    return tool_designate_structure_site(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=structure_type,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        build_progress=build_progress,
        search_radius=search_radius,
        device=device,
    )


def spawn_structure(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    structure_type: int,
    scale: float,
    durability: float,
    shelter_cap: float = 0.0,
    build_progress: float = 100.0,
    device: str = "cpu",
    extra_cols: dict[int, float] | None = None,
    create_object_fn=None,
) -> int:
    return spawn_structure_entity(
        m_tensor,
        entity_count_ref,
        center_x,
        center_y,
        structure_type,
        scale=scale,
        durability=durability,
        shelter_cap=shelter_cap,
        build_progress=build_progress,
        device=device,
        extra_cols=extra_cols,
        create_object_fn=create_object_fn,
    )


def advance_build(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    target_entity_ids: list[int] | torch.Tensor,
    builder_mask: torch.Tensor | None = None,
    build_radius: float,
    progress_per_human: float,
    stamina_cost: float,
    material_use: float,
    device: str = "cpu",
) -> dict[str, Any]:
    return build_with_humans(
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


def build_structure_now(
    ctx: dict[str, Any],
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    structure_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn,
    create_object_fn,
    scale: float | None = None,
    durability: float | None = None,
    shelter_cap: float | None = None,
    extra_cols: dict[int, float] | None = None,
    allowed_base_types: set[int] | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    return tool_build_structure(
        ctx,
        m_tensor,
        entity_count_ref,
        structure_type=structure_type,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        scale=scale,
        durability=durability,
        shelter_cap=shelter_cap,
        extra_cols=extra_cols,
        allowed_base_types=allowed_base_types,
        device=device,
    )


def find_build_site(
    m_tensor: torch.Tensor,
    *,
    structure_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn,
    search_radius: float = 320.0,
) -> dict[str, Any]:
    return tool_find_buildable_site(
        m_tensor,
        structure_type=structure_type,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        search_radius=search_radius,
    )


def build_structure_with_workers(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    structure_type: int,
    center_x: float,
    center_y: float,
    clamp_point_fn,
    create_object_fn,
    gather_materials_first: bool = True,
    search_radius: float = 320.0,
    device: str = "cpu",
) -> dict[str, Any]:
    return tool_build_structure_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        structure_type=structure_type,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        gather_materials_first=gather_materials_first,
        search_radius=search_radius,
        device=device,
    )


def build_settlement_now(
    ctx: dict[str, Any],
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    clamp_point_fn,
    create_object_fn,
    device: str = "cpu",
) -> dict[str, Any]:
    return tool_build_settlement(
        ctx,
        m_tensor,
        entity_count_ref,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    )


def build_settlement_with_workers(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    clamp_point_fn,
    create_object_fn,
    device: str = "cpu",
) -> dict[str, Any]:
    return tool_build_settlement_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        center_x=center_x,
        center_y=center_y,
        clamp_point_fn=clamp_point_fn,
        create_object_fn=create_object_fn,
        device=device,
    )


def construct_wall_with_workers(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    clamp_point_fn,
    make_wall_polygon_fn,
    create_object_fn,
    thickness: float = 12.0,
    durability: float = 180.0,
    device: str = "cpu",
) -> dict[str, Any]:
    return tool_construct_wall_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        start_x=start_x,
        start_y=start_y,
        end_x=end_x,
        end_y=end_y,
        clamp_point_fn=clamp_point_fn,
        make_wall_polygon_fn=make_wall_polygon_fn,
        create_object_fn=create_object_fn,
        thickness=thickness,
        durability=durability,
        device=device,
    )


def repair_targets_with_workers(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    target_entity_ids: list[int] | torch.Tensor,
    builder_mask: torch.Tensor | None = None,
    repair_radius: float,
    repair_rate: float,
    device: str = "cpu",
) -> dict[str, Any]:
    return repair_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        target_entity_ids,
        builder_mask=builder_mask,
        repair_radius=repair_radius,
        repair_rate=repair_rate,
        device=device,
    )


def repair_area_with_workers(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    repair_rate: float = 8.0,
    device: str = "cpu",
) -> dict[str, Any]:
    return tool_repair_area_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        repair_rate=repair_rate,
        device=device,
    )


def repair_structures_now(
    m_tensor: torch.Tensor,
    *,
    center_x: float,
    center_y: float,
    radius: float = 60.0,
    amount: float = 30.0,
) -> dict[str, Any]:
    return tool_repair_structures(
        m_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        amount=amount,
    )


def demolish_targets_with_workers(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    target_entity_ids: list[int] | torch.Tensor,
    builder_mask: torch.Tensor | None = None,
    demolish_radius: float,
    device: str = "cpu",
) -> dict[str, Any]:
    return demolish_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        target_entity_ids,
        builder_mask=builder_mask,
        demolish_radius=demolish_radius,
        device=device,
    )


def demolish_area_with_workers(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    device: str = "cpu",
) -> dict[str, Any]:
    return tool_demolish_area_with_humans(
        ctx,
        h_tensor,
        m_tensor,
        entity_count_ref,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
    )


__all__ = [
    "advance_build",
    "build_blueprint",
    "build_settlement_now",
    "build_settlement_with_workers",
    "build_structure_now",
    "build_structure_with_workers",
    "construct_wall_with_workers",
    "demolish_area_with_workers",
    "demolish_targets_with_workers",
    "designate_site",
    "find_build_site",
    "find_site",
    "gather_construction_materials",
    "repair_area_with_workers",
    "repair_structures_now",
    "repair_targets_with_workers",
    "resolve_site",
    "spawn_structure",
]
