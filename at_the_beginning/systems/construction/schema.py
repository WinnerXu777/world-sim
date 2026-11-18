from __future__ import annotations

"""Schema helpers for construction needs and projects."""

from typing import Any

from .catalog import building_material_requirements


CONSTRUCTION_NEED_SCHEMA_VERSION = 1
CONSTRUCTION_PROJECT_SCHEMA_VERSION = 1


def build_construction_need(
    need_id: str,
    building_kind: str,
    *,
    tick: int,
    scope: str,
    priority: float = 0.5,
    source: str = "runtime",
    status: str = "queued",
    summary: str = "",
    owner_human_id: str | None = None,
    household_id: str | None = None,
    settlement_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CONSTRUCTION_NEED_SCHEMA_VERSION,
        "id": str(need_id),
        "building_kind": str(building_kind),
        "scope": str(scope),
        "priority": round(max(0.0, min(1.0, float(priority))), 3),
        "source": str(source or "runtime"),
        "status": str(status or "queued"),
        "summary": str(summary or ""),
        "owner_human_id": owner_human_id,
        "household_id": household_id,
        "settlement_id": settlement_id,
        "material_requirements": [
            {"item_kind": item_kind, "quantity": quantity}
            for item_kind, quantity in building_material_requirements(building_kind)
        ],
        "created_tick": int(tick),
        "last_update_tick": int(tick),
        "metadata": dict(metadata or {}),
    }


def build_construction_project(
    project_id: str,
    building_kind: str,
    *,
    tick: int,
    need_id: str | None = None,
    status: str = "planned",
    site: dict[str, Any] | None = None,
    progress: float = 0.0,
    assigned_human_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CONSTRUCTION_PROJECT_SCHEMA_VERSION,
        "id": str(project_id),
        "need_id": need_id,
        "building_kind": str(building_kind),
        "status": str(status or "planned"),
        "site": dict(site or {}),
        "progress": round(max(0.0, min(100.0, float(progress))), 2),
        "assigned_human_ids": [str(human_id) for human_id in list(assigned_human_ids or [])],
        "created_tick": int(tick),
        "last_update_tick": int(tick),
        "metadata": dict(metadata or {}),
    }


def construction_need_identity(need: dict[str, Any]) -> tuple[str, str]:
    return (str(need.get("building_kind", "")), str(need.get("scope", "")))


def construction_project_identity(project: dict[str, Any]) -> tuple[str, str | None]:
    return (str(project.get("building_kind", "")), project.get("need_id"))


__all__ = [
    "CONSTRUCTION_NEED_SCHEMA_VERSION",
    "CONSTRUCTION_PROJECT_SCHEMA_VERSION",
    "build_construction_need",
    "build_construction_project",
    "construction_need_identity",
    "construction_project_identity",
]
