from __future__ import annotations

from typing import Any, Callable

from .click_resolver import infer_target_tag, resolve_click_semantic_action
from .contexts import context_allows_action
from .mode_manager import merge_control_semantic_state
from .schema import (
    legacy_action_for_semantic,
    normalize_control_context,
    normalize_semantic_action,
    normalize_target_kind,
    semantic_action_family,
)


def empty_command_state() -> dict[str, Any]:
    return {
        "move_target": None,
        "selected_target_kind": None,
        "selected_target_id": None,
        "selected_target_name": None,
        "selected_target_tag": None,
        "selected_world": None,
        "pending_action": None,
        "pending_semantic_action": None,
        "pending_action_family": None,
        "talk_target_kind": None,
        "talk_target_id": None,
        "talk_target_name": None,
        "talk_target_tag": None,
    }


def normalize_control_event(
    payload: dict[str, Any],
    *,
    session_target_kind: str | None = None,
    session_context: str | None = None,
    session_view_style: str | None = None,
    resolve_target_name: Callable[[str, str | None], str | None] | None = None,
) -> dict[str, Any]:
    event_name = str(payload.get("event", "")).strip().lower() or "click_command"
    raw_action = str(payload.get("action", "")).strip().lower()
    explicit_semantic = str(payload.get("semantic_action", "")).strip().lower()
    button = str(payload.get("button", "")).strip().lower() or "left"
    world = payload.get("world") if isinstance(payload.get("world"), dict) else None
    text = str(payload.get("text", "")).strip()

    raw_target_kind = str(payload.get("target_kind", "")).strip().lower()
    target_id = str(payload.get("target_id", "")).strip() or None
    target_name = str(payload.get("target_name", "")).strip() or None
    target_kind = (
        normalize_target_kind(raw_target_kind or ("entity" if target_id else session_target_kind or "human"))
        if raw_target_kind or target_id or target_name or session_target_kind
        else "human"
    )
    if target_name is None and target_id is not None and resolve_target_name is not None:
        target_name = resolve_target_name(target_kind, target_id)

    context, view_style = merge_control_semantic_state(
        target_kind=target_kind or session_target_kind,
        current_context=session_context,
        current_view_style=session_view_style,
        incoming_context=payload.get("context"),
        incoming_view_style=payload.get("view_style"),
    )
    context = normalize_control_context(context, fallback="human_tps")

    if explicit_semantic:
        semantic_action = normalize_semantic_action(explicit_semantic, fallback="select_target")
        legacy_action = legacy_action_for_semantic(semantic_action)
        metadata = {
            "target_tag": infer_target_tag(target_kind if target_id or target_name else None, target_name),
            "explicit_semantic_action": semantic_action,
        }
    else:
        semantic_action, legacy_action, metadata = resolve_click_semantic_action(
            event_name=event_name,
            raw_action=raw_action,
            button=button,
            target_kind=target_kind if target_id or target_name else None,
            target_name=target_name,
        )

    if not context_allows_action(context, semantic_action):
        semantic_action = "select_target"
        legacy_action = legacy_action_for_semantic(semantic_action)
        metadata = {
            "target_tag": infer_target_tag(target_kind if target_id or target_name else None, target_name),
            "coerced_from": normalize_semantic_action(raw_action, fallback=semantic_action),
        }

    target_tag = str(metadata.get("target_tag") or infer_target_tag(target_kind, target_name))
    talk_mode = str(payload.get("talk_mode", "")).strip().lower()
    if semantic_action == "talk_command":
        if not talk_mode:
            talk_mode = "direct_talk" if target_id else "ambient_talk"
    else:
        talk_mode = ""

    return {
        "event": event_name,
        "action": legacy_action or "",
        "semantic_action": semantic_action,
        "action_family": semantic_action_family(semantic_action),
        "button": button,
        "context": context,
        "view_style": view_style,
        "world": {
            "x": round(float(world.get("x", 0.0)), 2),
            "y": round(float(world.get("y", 0.0)), 2),
        } if world is not None else None,
        "target_kind": target_kind if target_id or target_name else "",
        "target_id": target_id,
        "target_name": target_name,
        "target_tag": target_tag if target_id or target_name else "",
        "text": text,
        "talk_mode": talk_mode,
        "metadata": metadata,
    }


def apply_semantic_event_to_command_state(
    command_state: dict[str, Any] | None,
    normalized_event: dict[str, Any],
) -> dict[str, Any]:
    next_state = dict(command_state or empty_command_state())
    action = str(normalized_event.get("action", "")).strip().lower()
    semantic_action = str(normalized_event.get("semantic_action", "")).strip().lower()
    action_family = str(normalized_event.get("action_family", "")).strip().lower()
    world = normalized_event.get("world")

    if semantic_action in {"cancel", "clear_selection"}:
        return empty_command_state()

    if semantic_action == "move":
        next_state["move_target"] = world
        next_state["selected_target_kind"] = normalized_event.get("target_kind")
        next_state["selected_target_id"] = normalized_event.get("target_id")
        next_state["selected_target_name"] = normalized_event.get("target_name")
        next_state["selected_target_tag"] = normalized_event.get("target_tag")
        next_state["selected_world"] = world
        next_state["pending_action"] = action or "move"
        next_state["pending_semantic_action"] = "move"
        next_state["pending_action_family"] = action_family or "immediate"
        return next_state

    if semantic_action == "talk_command":
        next_state["talk_target_kind"] = normalized_event.get("target_kind")
        next_state["talk_target_id"] = normalized_event.get("target_id")
        next_state["talk_target_name"] = normalized_event.get("target_name")
        next_state["talk_target_tag"] = normalized_event.get("target_tag")
        next_state["pending_action"] = action or "talk"
        next_state["pending_semantic_action"] = "talk_command"
        next_state["pending_action_family"] = action_family or "talk"
        return next_state

    next_state["selected_target_kind"] = normalized_event.get("target_kind")
    next_state["selected_target_id"] = normalized_event.get("target_id")
    next_state["selected_target_name"] = normalized_event.get("target_name")
    next_state["selected_target_tag"] = normalized_event.get("target_tag")
    next_state["selected_world"] = world
    next_state["pending_action"] = action
    next_state["pending_semantic_action"] = semantic_action
    next_state["pending_action_family"] = action_family
    if semantic_action in {"attack_target", "interact_target", "work_on_target", "pickup_target"}:
        next_state["move_target"] = None
    return next_state
