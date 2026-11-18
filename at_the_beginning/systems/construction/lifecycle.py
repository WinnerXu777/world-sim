from __future__ import annotations

"""Lifecycle helpers for resident-facing construction state."""

from typing import Any


CONSTRUCTION_STATE_SCHEMA_VERSION = 1


def build_construction_state(*, tick: int) -> dict[str, Any]:
    return {
        "schema_version": CONSTRUCTION_STATE_SCHEMA_VERSION,
        "active_need_id": None,
        "active_project_id": None,
        "last_need_review_tick": int(tick),
        "last_project_review_tick": int(tick),
        "auto_allowed": True,
        "review_reason": "",
    }


def ensure_construction_state(resident: dict[str, Any], tick: int) -> dict[str, Any]:
    state = resident.setdefault("construction_state", {})
    if not isinstance(state, dict):
        state = {}
        resident["construction_state"] = state
    state.setdefault("schema_version", CONSTRUCTION_STATE_SCHEMA_VERSION)
    state.setdefault("active_need_id", None)
    state.setdefault("active_project_id", None)
    state.setdefault("last_need_review_tick", int(tick))
    state.setdefault("last_project_review_tick", int(tick))
    state.setdefault("auto_allowed", True)
    state.setdefault("review_reason", "")
    return state


def ensure_construction_profile(resident: dict[str, Any]) -> dict[str, Any]:
    profile = resident.setdefault("construction_profile", {})
    if not isinstance(profile, dict):
        profile = {}
        resident["construction_profile"] = profile
    profile.setdefault("preferred_building_kinds", [])
    profile.setdefault("building_scope_bias", {})
    profile.setdefault("known_sites", [])
    return profile


def ensure_construction_records(resident: dict[str, Any]) -> None:
    resident.setdefault("construction_needs", [])
    resident.setdefault("construction_projects", [])


def ensure_construction_behavior_state(resident: dict[str, Any], *, tick: int) -> bool:
    before = {
        "construction_state": dict(resident.get("construction_state", {})),
        "construction_profile": dict(resident.get("construction_profile", {})),
        "construction_needs": list(resident.get("construction_needs", [])),
        "construction_projects": list(resident.get("construction_projects", [])),
    }
    ensure_construction_state(resident, tick)
    ensure_construction_profile(resident)
    ensure_construction_records(resident)
    after = {
        "construction_state": dict(resident.get("construction_state", {})),
        "construction_profile": dict(resident.get("construction_profile", {})),
        "construction_needs": list(resident.get("construction_needs", [])),
        "construction_projects": list(resident.get("construction_projects", [])),
    }
    return before != after


__all__ = [
    "CONSTRUCTION_STATE_SCHEMA_VERSION",
    "build_construction_state",
    "ensure_construction_behavior_state",
    "ensure_construction_profile",
    "ensure_construction_records",
    "ensure_construction_state",
]
