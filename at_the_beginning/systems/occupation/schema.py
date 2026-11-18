from __future__ import annotations

"""Builders for resident occupation records."""

from typing import Any


OCCUPATION_SCHEMA_VERSION = 1


def build_occupation_record(
    kind: str,
    *,
    origin: str = "assigned",
    parent_bias: str = "",
    skill: float = 0.5,
    stability: float = 0.7,
    mutation: bool = False,
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": OCCUPATION_SCHEMA_VERSION,
        "kind": str(kind),
        "origin": str(origin or "assigned"),
        "parent_bias": str(parent_bias or ""),
        "skill": round(max(0.0, min(1.0, float(skill))), 3),
        "stability": round(max(0.0, min(1.0, float(stability))), 3),
        "mutation": bool(mutation),
        "notes": str(notes or ""),
        "metadata": dict(metadata or {}),
    }
