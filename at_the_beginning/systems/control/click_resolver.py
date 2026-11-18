from __future__ import annotations

from .schema import legacy_action_for_semantic, normalize_semantic_action, normalize_target_kind


def infer_target_tag(target_kind: str | None, target_name: str | None = None) -> str:
    kind = normalize_target_kind(target_kind, fallback="human")
    if kind == "human":
        return "human"

    name = str(target_name or "").strip().lower()
    if not name:
        return "entity"
    if any(token in name for token in ("tree", "oak", "pine", "wood")):
        return "tree"
    if any(token in name for token in ("rock", "stone", "ore")):
        return "stone"
    if any(token in name for token in ("case", "chest", "storage", "stockpile", "container")):
        return "container"
    if any(token in name for token in ("house", "hut", "shop", "market", "wall", "well", "shelter", "farm")):
        return "structure"
    if any(token in name for token in ("wolf", "boar", "deer", "bear", "fox", "animal")):
        return "animal"
    return "entity"


def resolve_click_semantic_action(
    *,
    event_name: str,
    raw_action: str | None,
    button: str | None,
    target_kind: str | None,
    target_name: str | None,
) -> tuple[str, str | None, dict[str, object]]:
    button_normalized = str(button or "").strip().lower()
    event_normalized = str(event_name or "").strip().lower()
    target_tag = infer_target_tag(target_kind, target_name)
    metadata: dict[str, object] = {"target_tag": target_tag}

    if event_normalized == "cancel_action":
        semantic_action = "cancel"
    elif event_normalized == "talk_command":
        semantic_action = "talk_command"
    elif event_normalized == "ground_right_click":
        semantic_action = "move"
    else:
        semantic_action = normalize_semantic_action(raw_action, fallback="select_target")

    if semantic_action == "work_on_target":
        if target_tag == "tree":
            metadata["work_kind"] = "lumber"
        elif target_tag == "stone":
            metadata["work_kind"] = "mine"
    elif semantic_action == "attack_target":
        if target_tag in {"animal", "human"}:
            metadata["tool_mode"] = "weapon"
    elif semantic_action == "interact_target" and target_tag == "container":
        metadata["interaction_kind"] = "open_container"
    elif semantic_action == "select_target" and button_normalized == "right":
        semantic_action = "focus_world_point"

    legacy_action = legacy_action_for_semantic(semantic_action)
    return semantic_action, legacy_action, metadata
