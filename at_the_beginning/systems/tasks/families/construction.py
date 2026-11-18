from __future__ import annotations

"""Construction-family task helpers and executor for resident build projects."""

import math
from typing import Any

try:
    from systems.construction.catalog import construction_blueprint
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.construction.catalog import construction_blueprint

from ..contracts import TaskExecutionContext
from ..ops import complete_current_task


CONSTRUCTION_TASK_KINDS = {
    "designate_build_site",
    "build_project",
}

BUILD_ARRIVAL_RADIUS = 12.0


def can_handle_task(task_kind: str) -> bool:
    return str(task_kind).strip() in CONSTRUCTION_TASK_KINDS


def _project_record(resident: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    needle = str(project_id or "").strip()
    if not needle:
        return None
    for project in list(resident.get("construction_projects", [])):
        if isinstance(project, dict) and str(project.get("id", "")) == needle:
            return project
    return None


def _active_project(resident: dict[str, Any]) -> dict[str, Any] | None:
    state = dict(resident.get("construction_state", {}))
    active_project_id = str(state.get("active_project_id", "")).strip()
    if active_project_id:
        project = _project_record(resident, active_project_id)
        if isinstance(project, dict):
            return project
    for project in list(resident.get("construction_projects", [])):
        if not isinstance(project, dict):
            continue
        if str(project.get("status", "planned")).strip() in {"planned", "designated", "building"}:
            return project
    return None


def construction_task_specs(resident: dict[str, Any]) -> list[dict[str, Any]]:
    state = dict(resident.get("construction_state", {}))
    if not bool(state.get("auto_allowed", True)):
        return []
    project = _active_project(resident)
    if not isinstance(project, dict):
        return []
    project_id = str(project.get("id", "")).strip()
    if not project_id:
        return []

    building_kind = str(project.get("building_kind", "")).strip()
    blueprint = construction_blueprint(building_kind)
    label = str(blueprint.get("label", building_kind.replace("_", " "))).strip() or building_kind
    status = str(project.get("status", "planned")).strip()
    priority = float(project.get("metadata", {}).get("priority", 0.6))
    metadata = {
        "project_id": project_id,
        "building_kind": building_kind,
        "scope": str(project.get("metadata", {}).get("scope", "")),
        "need_id": project.get("need_id"),
        "place_tag": str(project.get("metadata", {}).get("place_tag", "")),
    }
    if status == "planned":
        return [
            {
                "task_kind": "designate_build_site",
                "priority": priority,
                "source": "construction",
                "summary": f"designate {label.lower()}",
                "target_kind": "construction_project",
                "target_id": project_id,
                "metadata": metadata,
            }
        ]
    if status in {"designated", "building"}:
        return [
            {
                "task_kind": "build_project",
                "priority": max(priority, 0.52),
                "source": "construction",
                "summary": f"build {label.lower()}",
                "target_kind": "construction_project",
                "target_id": project_id,
                "metadata": metadata,
            }
        ]
    return []


def _distance(px: float, py: float, tx: float, ty: float) -> float:
    return math.hypot(float(tx) - float(px), float(ty) - float(py))


def execute_task_step(context: TaskExecutionContext) -> bool:
    task_kind = str(context.task_kind).strip()
    if task_kind not in CONSTRUCTION_TASK_KINDS:
        return False

    project_id = str(context.task.get("target_id") or context.metadata.get("project_id") or "").strip()
    project = _project_record(context.resident, project_id)
    if not isinstance(project, dict):
        complete_current_task(context.resident, context.tick, outcome="blocked", reason="construction_project_missing")
        return True

    context.set_intent(f"construction:{task_kind}")

    if task_kind == "designate_build_site":
        result = context.bridge.designate_construction_project(project_id)
        if bool(result.get("ok", False)):
            complete_current_task(context.resident, context.tick, reason="construction_site_designated")
            return True
        if str(result.get("reason", "")).strip() in {"already_designated", "already_completed"}:
            complete_current_task(context.resident, context.tick, reason=str(result.get("reason", "")).strip())
            return True
        return False

    if task_kind == "build_project":
        site = dict(project.get("site", {}))
        if not site:
            result = context.bridge.designate_construction_project(project_id)
            if bool(result.get("ok", False)):
                complete_current_task(context.resident, context.tick, reason="construction_site_designated")
                return True
            return False

        result = context.bridge.advance_construction_project(project_id)
        if bool(result.get("completed", False)):
            complete_current_task(context.resident, context.tick, reason="construction_completed")
            return True
        if bool(result.get("progressed", False)) or bool(result.get("gathered", False)):
            return True
        if bool(result.get("ok", False)):
            return True
        if str(result.get("reason", "")).strip() in {"already_completed", "project_missing"}:
            complete_current_task(context.resident, context.tick, reason=str(result.get("reason", "")).strip())
            return True
        return False

    return False


__all__ = [
    "CONSTRUCTION_TASK_KINDS",
    "can_handle_task",
    "construction_task_specs",
    "execute_task_step",
]
