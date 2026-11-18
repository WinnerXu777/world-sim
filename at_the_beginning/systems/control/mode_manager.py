from __future__ import annotations

from .contexts import default_context_for_target, default_view_style_for_context
from .schema import normalize_control_context, normalize_target_kind, normalize_view_style


def merge_control_semantic_state(
    *,
    target_kind: str | None,
    current_context: str | None = None,
    current_view_style: str | None = None,
    incoming_context: str | None = None,
    incoming_view_style: str | None = None,
) -> tuple[str, str]:
    normalized_target_kind = normalize_target_kind(target_kind, fallback="human")

    base_view_style = incoming_view_style or current_view_style
    if not base_view_style:
        base_view_style = default_view_style_for_context(
            incoming_context
            or current_context
            or default_context_for_target(normalized_target_kind)
        )
    view_style = normalize_view_style(base_view_style, fallback="third_person")

    fallback_context = default_context_for_target(normalized_target_kind, view_style=view_style)
    context = normalize_control_context(
        incoming_context or current_context or fallback_context,
        fallback=fallback_context,
    )

    if context == "human_fps":
        view_style = "first_person"
    elif context in {"human_tps", "talk_context", "inventory_context"} and view_style == "god_view":
        view_style = "third_person"
    elif context == "god_context":
        view_style = "god_view"

    return context, view_style
