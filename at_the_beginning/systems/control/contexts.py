from __future__ import annotations

from .schema import normalize_control_context


ALLOWED_ACTIONS_BY_CONTEXT: dict[str, set[str]] = {
    "god_context": {
        "pan_camera",
        "zoom_camera",
        "select_target",
        "inspect_target",
        "focus_world_point",
        "switch_mode",
        "clear_selection",
        "cancel",
    },
    "human_fps": {
        "move",
        "look",
        "jump",
        "sprint",
        "select_target",
        "attack_target",
        "work_on_target",
        "interact_target",
        "pickup_target",
        "talk_command",
        "switch_mode",
        "switch_view",
        "clear_selection",
        "cancel",
    },
    "human_tps": {
        "move",
        "look",
        "jump",
        "sprint",
        "select_target",
        "attack_target",
        "work_on_target",
        "interact_target",
        "pickup_target",
        "talk_command",
        "switch_mode",
        "switch_view",
        "clear_selection",
        "cancel",
    },
    "talk_context": {
        "talk_command",
        "clear_selection",
        "cancel",
        "switch_mode",
        "switch_view",
    },
    "inventory_context": {
        "interact_target",
        "pickup_target",
        "use_item",
        "clear_selection",
        "cancel",
        "switch_mode",
    },
}


def default_view_style_for_context(context: str | None) -> str:
    normalized = normalize_control_context(context, fallback="human_tps")
    if normalized == "human_fps":
        return "first_person"
    if normalized == "god_context":
        return "god_view"
    return "third_person"


def default_context_for_target(target_kind: str | None, *, view_style: str | None = None) -> str:
    target_kind_normalized = str(target_kind or "human").strip().lower()
    view_normalized = str(view_style or "").strip().lower()
    if target_kind_normalized != "human":
        return "god_context"
    if view_normalized == "first_person":
        return "human_fps"
    return "human_tps"


def context_allows_action(context: str | None, action: str | None) -> bool:
    normalized = normalize_control_context(context, fallback="human_tps")
    allowed = ALLOWED_ACTIONS_BY_CONTEXT.get(normalized, set())
    return str(action or "").strip().lower() in allowed
