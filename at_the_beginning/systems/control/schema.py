from __future__ import annotations

from typing import Final


SESSION_MODES: Final[set[str]] = {"observe", "possess", "assist", "incarnate"}
TARGET_KINDS: Final[set[str]] = {"human", "entity"}
CONTROL_CONTEXTS: Final[set[str]] = {
    "god_context",
    "human_fps",
    "human_tps",
    "talk_context",
    "inventory_context",
}
VIEW_STYLES: Final[set[str]] = {"first_person", "third_person", "god_view"}
SEMANTIC_ACTIONS: Final[set[str]] = {
    "move",
    "look",
    "jump",
    "sprint",
    "pan_camera",
    "zoom_camera",
    "switch_mode",
    "switch_view",
    "toggle_cursor_capture",
    "select_target",
    "clear_selection",
    "focus_world_point",
    "inspect_target",
    "attack_target",
    "work_on_target",
    "interact_target",
    "pickup_target",
    "use_item",
    "talk_command",
    "cancel",
}

SEMANTIC_ALIASES: Final[dict[str, str]] = {
    "attack": "attack_target",
    "attack_target": "attack_target",
    "cancel": "cancel",
    "clear_selection": "clear_selection",
    "focus_world_point": "focus_world_point",
    "inspect": "inspect_target",
    "inspect_target": "inspect_target",
    "interact": "interact_target",
    "interact_target": "interact_target",
    "jump": "jump",
    "look": "look",
    "move": "move",
    "pan_camera": "pan_camera",
    "pickup": "pickup_target",
    "pickup_target": "pickup_target",
    "select": "select_target",
    "select_target": "select_target",
    "sprint": "sprint",
    "switch_mode": "switch_mode",
    "switch_view": "switch_view",
    "talk": "talk_command",
    "talk_command": "talk_command",
    "toggle_cursor_capture": "toggle_cursor_capture",
    "use_item": "use_item",
    "work": "work_on_target",
    "work_on_target": "work_on_target",
    "zoom_camera": "zoom_camera",
}

LEGACY_ACTION_BY_SEMANTIC: Final[dict[str, str | None]] = {
    "attack_target": "attack",
    "cancel": "cancel",
    "clear_selection": "cancel",
    "focus_world_point": "select",
    "inspect_target": "select",
    "interact_target": "interact",
    "look": None,
    "move": "move",
    "pan_camera": "move",
    "pickup_target": "interact",
    "select_target": "select",
    "sprint": None,
    "switch_mode": None,
    "switch_view": None,
    "talk_command": "talk",
    "toggle_cursor_capture": None,
    "use_item": "interact",
    "work_on_target": "work",
    "zoom_camera": None,
    "jump": None,
}

ACTION_FAMILY_BY_SEMANTIC: Final[dict[str, str]] = {
    "attack_target": "embodied_interaction",
    "cancel": "state_change",
    "clear_selection": "state_change",
    "focus_world_point": "targeting",
    "inspect_target": "targeting",
    "interact_target": "embodied_interaction",
    "jump": "immediate",
    "look": "immediate",
    "move": "immediate",
    "pan_camera": "immediate",
    "pickup_target": "embodied_interaction",
    "select_target": "targeting",
    "sprint": "immediate",
    "switch_mode": "mode",
    "switch_view": "mode",
    "talk_command": "talk",
    "toggle_cursor_capture": "mode",
    "use_item": "embodied_interaction",
    "work_on_target": "embodied_interaction",
    "zoom_camera": "immediate",
}


def normalize_session_mode(mode: str | None, *, fallback: str = "possess") -> str:
    normalized = str(mode or fallback).strip().lower()
    if normalized in SESSION_MODES:
        return normalized
    return fallback


def normalize_target_kind(target_kind: str | None, *, fallback: str = "human") -> str:
    normalized = str(target_kind or fallback).strip().lower()
    if normalized in TARGET_KINDS:
        return normalized
    return fallback


def normalize_control_context(context: str | None, *, fallback: str = "human_tps") -> str:
    normalized = str(context or fallback).strip().lower()
    if normalized in CONTROL_CONTEXTS:
        return normalized
    return fallback


def normalize_view_style(view_style: str | None, *, fallback: str = "third_person") -> str:
    normalized = str(view_style or fallback).strip().lower()
    if normalized in VIEW_STYLES:
        return normalized
    return fallback


def normalize_semantic_action(action: str | None, *, fallback: str = "select_target") -> str:
    normalized = str(action or "").strip().lower()
    mapped = SEMANTIC_ALIASES.get(normalized)
    if mapped in SEMANTIC_ACTIONS:
        return mapped
    return fallback


def legacy_action_for_semantic(action: str | None) -> str | None:
    normalized = normalize_semantic_action(action, fallback="select_target")
    return LEGACY_ACTION_BY_SEMANTIC.get(normalized)


def semantic_action_family(action: str | None) -> str:
    normalized = normalize_semantic_action(action, fallback="select_target")
    return ACTION_FAMILY_BY_SEMANTIC.get(normalized, "targeting")
