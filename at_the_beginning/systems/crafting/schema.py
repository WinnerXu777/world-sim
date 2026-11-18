from __future__ import annotations

"""Schema helpers for declarative crafting jobs."""

from typing import Any


CRAFTING_SCHEMA_VERSION = 1


def build_crafting_job_record(
    recipe_id: str,
    *,
    job_id: str,
    owner_id: str,
    owner_kind: str = "resident",
    requested_quantity: int = 1,
    status: str = "queued",
    priority: float = 0.5,
    source: str = "manual",
    reserved_inputs: list[dict[str, Any]] | None = None,
    missing_inputs: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CRAFTING_SCHEMA_VERSION,
        "job_id": str(job_id),
        "recipe_id": str(recipe_id),
        "owner_id": str(owner_id),
        "owner_kind": str(owner_kind or "resident"),
        "requested_quantity": max(int(requested_quantity), 1),
        "status": str(status or "queued"),
        "priority": round(max(0.0, min(1.0, float(priority))), 3),
        "source": str(source or "manual"),
        "reserved_inputs": list(reserved_inputs or []),
        "missing_inputs": list(missing_inputs or []),
        "metadata": dict(metadata or {}),
    }
