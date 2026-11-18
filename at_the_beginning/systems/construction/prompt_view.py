from __future__ import annotations

"""Prompt-facing summaries for construction needs and projects."""

from typing import Any

from .catalog import construction_blueprint


def summarize_construction_need(need: dict[str, Any]) -> str:
    if not isinstance(need, dict) or not need:
        return ""
    building_kind = str(need.get("building_kind", "")).strip()
    scope = str(need.get("scope", "")).strip()
    label = str(construction_blueprint(building_kind).get("label", building_kind.replace("_", " "))).strip()
    priority = float(need.get("priority", 0.0))
    return f"{label} [{scope}] ({priority:.2f})"


def summarize_construction_project(project: dict[str, Any]) -> str:
    if not isinstance(project, dict) or not project:
        return ""
    building_kind = str(project.get("building_kind", "")).strip()
    label = str(construction_blueprint(building_kind).get("label", building_kind.replace("_", " "))).strip()
    status = str(project.get("status", "")).strip()
    progress = float(project.get("progress", 0.0))
    return f"{label} {status} ({progress:.1f}%)"


def build_construction_prompt_payload(resident: dict[str, Any], *, limit: int = 3) -> dict[str, Any]:
    max_items = max(int(limit), 0)
    needs = [dict(need) for need in list(resident.get("construction_needs", []))[:max_items] if isinstance(need, dict)]
    projects = [dict(project) for project in list(resident.get("construction_projects", []))[:max_items] if isinstance(project, dict)]
    return {
        "needs": needs,
        "need_summary": [summarize_construction_need(need) for need in needs if summarize_construction_need(need)],
        "projects": projects,
        "project_summary": [summarize_construction_project(project) for project in projects if summarize_construction_project(project)],
        "active_need_id": resident.get("construction_state", {}).get("active_need_id"),
        "active_project_id": resident.get("construction_state", {}).get("active_project_id"),
    }


def construction_prompt_payload(resident: dict[str, Any], *, limit: int = 3) -> dict[str, Any]:
    return build_construction_prompt_payload(resident, limit=limit)


def construction_prompt_summary(resident: dict[str, Any], *, limit: int = 2) -> str:
    payload = build_construction_prompt_payload(resident, limit=limit)
    parts = [str(item).strip() for item in [*payload.get("need_summary", []), *payload.get("project_summary", [])] if str(item).strip()]
    return " ; ".join(parts[: max(int(limit), 0)]) if parts else "no construction pressure"


__all__ = [
    "build_construction_prompt_payload",
    "construction_prompt_payload",
    "construction_prompt_summary",
    "summarize_construction_need",
    "summarize_construction_project",
]
