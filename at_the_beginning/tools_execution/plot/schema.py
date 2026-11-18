from __future__ import annotations

"""Schema helpers for resident reasoning / plot execution packets."""

from typing import Any


def normalize_plot_packet(packet: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(packet or {})
    goal_review = dict(payload.get("goal_review") or {})
    return {
        "resident_id": str(payload.get("resident_id", "")).strip(),
        "reasoning_mode": str(payload.get("reasoning_mode", "resident_reasoning")).strip() or "resident_reasoning",
        "reason": str(payload.get("reason", "")).strip(),
        "notes": str(payload.get("notes", "")).strip(),
        "goal_review": {
            "requested": bool(goal_review.get("requested", False)),
            "reason": str(goal_review.get("reason", "")).strip(),
            "force": bool(goal_review.get("force", False)),
        },
        "goal_updates": list(payload.get("goal_updates") or []),
        "plans": list(payload.get("plans") or []),
        "auto_plan": bool(payload.get("auto_plan", False)),
    }


def plot_packet_errors(packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(packet.get("resident_id", "")).strip():
        errors.append("missing_resident_id")
    for key in ("goal_updates", "plans"):
        if not isinstance(packet.get(key), list):
            errors.append(f"invalid_packet_field:{key}")
    if not isinstance(packet.get("goal_review"), dict):
        errors.append("invalid_packet_field:goal_review")
    return errors
