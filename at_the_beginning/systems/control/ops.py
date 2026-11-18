from __future__ import annotations

from typing import Any, Callable

from .router import (
    apply_semantic_event_to_command_state as _apply_semantic_event_to_command_state,
    empty_command_state as _empty_command_state,
    normalize_control_event as _normalize_control_event,
)


def empty_command_state() -> dict[str, Any]:
    return _empty_command_state()


def normalize_control_event(
    payload: dict[str, Any],
    *,
    session_target_kind: str | None = None,
    session_context: str | None = None,
    session_view_style: str | None = None,
    resolve_target_name: Callable[[str, str | None], str | None] | None = None,
) -> dict[str, Any]:
    return _normalize_control_event(
        payload,
        session_target_kind=session_target_kind,
        session_context=session_context,
        session_view_style=session_view_style,
        resolve_target_name=resolve_target_name,
    )


def apply_semantic_event_to_command_state(
    command_state: dict[str, Any] | None,
    normalized_event: dict[str, Any],
) -> dict[str, Any]:
    return _apply_semantic_event_to_command_state(command_state, normalized_event)


def build_control_debug_summary(session: dict[str, Any]) -> dict[str, Any]:
    command_state = dict(session.get("command_state", {}))
    return {
        "controller_id": session.get("controller_id"),
        "target_kind": session.get("target_kind"),
        "target_id": session.get("target_id"),
        "control_context": session.get("control_context"),
        "view_style": session.get("view_style"),
        "selected_target_kind": command_state.get("selected_target_kind"),
        "selected_target_id": command_state.get("selected_target_id"),
        "pending_action": command_state.get("pending_action"),
        "pending_semantic_action": command_state.get("pending_semantic_action"),
        "pending_action_family": command_state.get("pending_action_family"),
    }
