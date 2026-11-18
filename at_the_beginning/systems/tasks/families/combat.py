from __future__ import annotations

"""Combat-family task helpers with live attack, chase, retreat, and guard flow."""

import math
from typing import Any

from ..contracts import TaskExecutionContext
from ..ops import complete_current_task

try:
    from genesis_config import ATTACK_RANGE
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import ATTACK_RANGE


COMBAT_TASK_KINDS = {
    "attack_target",
    "chase_target",
    "retreat_from_target",
    "guard_area",
    "guard_target",
    "hold_position",
    "finish_hunt",
    "loot_after_kill",
    "protect_target",
    "intercept_target",
}

RETREAT_DISTANCE = max(float(ATTACK_RANGE) * 3.4, 18.0)


def can_handle_task(task_kind: str) -> bool:
    return str(task_kind).strip() in COMBAT_TASK_KINDS


def _build_target_task(
    task_kind: str,
    *,
    target: dict[str, Any],
    source: str,
    priority: float,
    summary: str,
    reason: str,
) -> list[dict[str, Any]]:
    target_kind = str(target.get("target_kind", "")).strip().lower()
    target_id = str(target.get("target_id", "")).strip()
    if target_kind not in {"human", "entity"} or not target_id:
        return []
    return [
        {
            "task_kind": task_kind,
            "priority": priority,
            "source": source,
            "summary": summary,
            "target_kind": target_kind,
            "target_id": target_id,
            "metadata": {
                "target_name": str(target.get("name", target_id)),
                "distance": round(float(target.get("distance", 0.0)), 2),
                "reason": str(reason or "combat"),
            },
        }
    ]


def combat_task_specs(
    *,
    manual_target: dict[str, Any] | None = None,
    human_target: dict[str, Any] | None = None,
    entity_target: dict[str, Any] | None = None,
    protect_target: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
    guard_place: str = "",
) -> list[dict[str, Any]]:
    signal = dict(signal or {})
    signal_kind = str(signal.get("kind", "")).strip()
    if signal_kind in COMBAT_TASK_KINDS:
        signal_target = {
            "target_kind": str(signal.get("target_kind", "")),
            "target_id": str(signal.get("target_id", "")),
            "name": str(signal.get("target_name", signal.get("target_id", "target"))),
            "distance": float(signal.get("distance", 0.0)),
        }
        if signal_kind == "guard_area":
            place_tag = str(signal.get("place_tag", guard_place or "settlement")).strip() or "settlement"
            return [
                {
                    "task_kind": "guard_area",
                    "priority": float(signal.get("priority", 0.59)),
                    "source": "combat",
                    "summary": str(signal.get("summary", f"guard {place_tag}")),
                    "target_kind": "place",
                    "target_id": place_tag,
                    "metadata": {
                        "place_tag": place_tag,
                        "reason": str(signal.get("reason", "guard")),
                        "patrol_radius": float(signal.get("patrol_radius", 18.0)),
                    },
                }
            ]
        return _build_target_task(
            signal_kind,
            target=signal_target,
            source="combat",
            priority=float(signal.get("priority", 0.9)),
            summary=str(signal.get("summary", signal_kind.replace("_", " "))),
            reason=str(signal.get("reason", "combat_signal")),
        )

    if isinstance(manual_target, dict):
        return _build_target_task(
            "attack_target",
            target=manual_target,
            source="manual_control",
            priority=0.95,
            summary=f"attack {manual_target.get('name', manual_target.get('target_id', 'target'))}",
            reason="manual_attack",
        )

    if isinstance(human_target, dict):
        distance = float(human_target.get("distance", 0.0))
        if distance > float(ATTACK_RANGE) * 1.1:
            return _build_target_task(
                "chase_target",
                target=human_target,
                source="combat",
                priority=0.87,
                summary=f"chase {human_target.get('name', human_target.get('target_id', 'target'))}",
                reason="combat_chase",
            ) + _build_target_task(
                "attack_target",
                target=human_target,
                source="combat",
                priority=0.94,
                summary=f"attack {human_target.get('name', human_target.get('target_id', 'target'))}",
                reason="combat_attack",
            )
        return _build_target_task(
            "attack_target",
            target=human_target,
            source="combat",
            priority=0.94,
            summary=f"attack {human_target.get('name', human_target.get('target_id', 'target'))}",
            reason="combat_attack",
        )

    if isinstance(entity_target, dict):
        distance = float(entity_target.get("distance", 0.0))
        base_specs = []
        if distance > float(ATTACK_RANGE) * 1.1:
            base_specs.extend(_build_target_task(
                "chase_target",
                target=entity_target,
                source="combat",
                priority=0.78,
                summary=f"track {entity_target.get('name', entity_target.get('target_id', 'target'))}",
                reason="hunt_chase",
            ))
            base_specs.extend(_build_target_task(
                "attack_target",
                target=entity_target,
                source="combat",
                priority=0.82,
                summary=f"hunt {entity_target.get('name', entity_target.get('target_id', 'target'))}",
                reason="hunt_attack",
            ))
        else:
            base_specs.extend(_build_target_task(
            "attack_target",
            target=entity_target,
            source="combat",
            priority=0.82,
            summary=f"hunt {entity_target.get('name', entity_target.get('target_id', 'target'))}",
            reason="hunt_attack",
            ))
        base_specs.append(
            {
                "task_kind": "finish_hunt",
                "priority": 0.61,
                "source": "combat",
                "summary": f"finish hunt for {entity_target.get('name', entity_target.get('target_id', 'target'))}",
                "target_kind": "entity",
                "target_id": str(entity_target.get("target_id", "")),
                "requested_quantity": 2,
                "metadata": {
                    "target_name": str(entity_target.get("name", entity_target.get("target_id", "target"))),
                    "output_kind": "rations",
                    "quantity": 2,
                },
            }
        )
        return base_specs

    if isinstance(protect_target, dict):
        return _build_target_task(
            "protect_target",
            target={
                "target_kind": "human",
                "target_id": str(protect_target.get("human_id", "")),
                "name": str(protect_target.get("name", protect_target.get("human_id", "target"))),
                "distance": float(protect_target.get("distance", 0.0)),
            },
            source="combat",
            priority=0.73,
            summary=f"protect {protect_target.get('name', protect_target.get('human_id', 'target'))}",
            reason="protect_ally",
        )

    if guard_place:
        return [
            {
                "task_kind": "guard_area",
                "priority": 0.59,
                "source": "combat",
                "summary": f"guard {guard_place}",
                "target_kind": "place",
                "target_id": str(guard_place),
                "metadata": {
                    "place_tag": str(guard_place),
                    "reason": "guard",
                    "patrol_radius": 18.0,
                },
            }
        ]

    return []


def _resolve_target(context: TaskExecutionContext) -> dict[str, Any] | None:
    target_kind = str(context.task.get("target_kind") or "").strip().lower()
    target_id = str(context.task.get("target_id") or "").strip()
    if not target_kind or not target_id:
        return None
    if target_kind == "human":
        return context.bridge.resolve_human(target_id)
    if target_kind == "entity":
        return context.bridge.resolve_entity(target_id)
    return None


def _distance_to_target(context: TaskExecutionContext, target: dict[str, Any]) -> float:
    if "distance" in target:
        return float(target.get("distance", 0.0))
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    return math.hypot(tx - context.px, ty - context.py)


def _handle_attack_target(context: TaskExecutionContext) -> bool:
    target = _resolve_target(context)
    if target is None:
        context.task_state["blocked_reason"] = "combat_target_missing"
        complete_current_task(context.resident, context.tick, reason="target_missing")
        return True

    target_kind = str(context.task.get("target_kind") or "").strip().lower()
    target_id = str(context.task.get("target_id") or "").strip()
    distance = _distance_to_target(context, target)
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))

    if distance > float(ATTACK_RANGE):
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 1.15):
            context.task_state["last_task_action"] = f"closing_on_{target_kind}"
            context.set_intent("attack_target")
            return True
        return False

    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("attack_target")
        return False

    result = context.bridge.try_attack_target(target_kind, target_id)
    if not bool(result.get("ok", False)):
        reason = str(result.get("reason", "attack_blocked"))
        if reason in {"target_missing", "target_invalid"}:
            complete_current_task(context.resident, context.tick, reason=reason)
            return True
        context.task_state["blocked_reason"] = reason
        context.set_intent("attack_target")
        return False

    context.bridge.on_action(
        last_action=f"attacked {target_kind}",
        intent="attack_target",
        mood_delta=-0.05,
        review=False,
    )
    if not bool(result.get("target_alive", True)):
        complete_current_task(context.resident, context.tick, reason="target_down")
    return True


def _handle_chase_target(context: TaskExecutionContext) -> bool:
    target = _resolve_target(context)
    if target is None:
        complete_current_task(context.resident, context.tick, reason="target_missing")
        return True
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    if _distance_to_target(context, target) <= float(ATTACK_RANGE) * 1.05:
        complete_current_task(context.resident, context.tick, reason="target_in_range")
        return True
    if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 1.25):
        context.task_state["last_task_action"] = "chasing_target"
        context.set_intent("chase_target")
        return True
    return False


def _handle_intercept_target(context: TaskExecutionContext) -> bool:
    target = _resolve_target(context)
    if target is None:
        complete_current_task(context.resident, context.tick, reason="target_missing")
        return True
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    if _distance_to_target(context, target) <= float(ATTACK_RANGE) * 1.6:
        complete_current_task(context.resident, context.tick, reason="intercepted")
        return True
    if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 1.2):
        context.task_state["last_task_action"] = "intercepting_target"
        context.set_intent("intercept_target")
        return True
    return False


def _handle_retreat_from_target(context: TaskExecutionContext) -> bool:
    target = _resolve_target(context)
    if target is None:
        complete_current_task(context.resident, context.tick, reason="target_lost")
        return True
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    dx = context.px - tx
    dy = context.py - ty
    norm = max(math.hypot(dx, dy), 1.0)
    flee_x = context.px + (dx / norm) * RETREAT_DISTANCE
    flee_y = context.py + (dy / norm) * RETREAT_DISTANCE
    flee_x = max(0.0, min(context.bridge.map_width or flee_x, flee_x))
    flee_y = max(0.0, min(context.bridge.map_height or flee_y, flee_y))
    distance = _distance_to_target(context, target)
    if distance >= RETREAT_DISTANCE * 0.8:
        context.bridge.on_action(
            last_action="retreated from danger",
            intent="retreat_from_target",
            threat_delta=-10.0,
            review=False,
        )
        complete_current_task(context.resident, context.tick, reason="safe_distance")
        return True
    if context.bridge.move_toward(flee_x, flee_y, magnitude=context.bridge.move_step * 1.3):
        context.task_state["last_task_action"] = "retreating"
        context.set_intent("retreat_from_target")
        return True
    return False


def _handle_guard_area(context: TaskExecutionContext) -> bool:
    place_tag = str(context.metadata.get("place_tag") or context.task.get("target_id") or "settlement").strip() or "settlement"
    anchor = context.bridge.resolve_place(place_tag, context.px, context.py, radius=260.0)
    anchor_x = float(anchor.get("x", context.px)) if anchor else context.px
    anchor_y = float(anchor.get("y", context.py)) if anchor else context.py
    patrol_radius = max(float(context.metadata.get("patrol_radius", 18.0)), 8.0)
    patrol_phase = max(int(context.task_state.get("guard_patrol_phase", 0)), 0)
    angle = float(patrol_phase % 8) * (math.pi / 4.0)
    tx = anchor_x + math.cos(angle) * patrol_radius
    ty = anchor_y + math.sin(angle) * patrol_radius
    if context.bridge.map_width > 0.0:
        tx = max(0.0, min(context.bridge.map_width, tx))
    if context.bridge.map_height > 0.0:
        ty = max(0.0, min(context.bridge.map_height, ty))
    distance = math.hypot(tx - context.px, ty - context.py)
    if distance > max(context.bridge.gather_radius * 0.45, 8.0):
        if context.bridge.move_toward(tx, ty):
            context.task_state["last_task_action"] = "guarding_area"
            context.set_intent("guard_area")
            return True
        return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("guard_area")
        return False
    context.task_state["guard_patrol_phase"] = patrol_phase + 1
    context.bridge.on_action(
        last_action=f"guarded {place_tag}",
        intent="guard_area",
        mood_delta=0.03,
        stamina_delta=-0.4,
        review=False,
    )
    return True


def _handle_guard_target(context: TaskExecutionContext) -> bool:
    target, ready = _resolve_target(context), False
    if target is None:
        complete_current_task(context.resident, context.tick, reason="target_missing")
        return True
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    if _distance_to_target(context, target) > max(RETREAT_DISTANCE * 0.35, 10.0):
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step):
            context.task_state["last_task_action"] = "moving_to_guard_target"
            context.set_intent("guard_target")
            return True
        return False
    ready = True
    hold_ticks = max(int(context.metadata.get("hold_ticks", 6)), 2)
    hold_until = int(context.task_state.get("guard_target_until_tick", 0))
    if hold_until <= 0:
        context.task_state["guard_target_until_tick"] = int(context.tick) + hold_ticks
        context.set_intent("guard_target")
        return True
    if int(context.tick) >= hold_until:
        context.task_state.pop("guard_target_until_tick", None)
        complete_current_task(context.resident, context.tick, reason="guarded_target")
        return True
    if ready:
        context.bridge.on_action(
            last_action=f"guarded {target.get('human_id', context.task.get('target_id', 'target'))}",
            intent="guard_target",
            mood_delta=0.04,
            stamina_delta=-0.25,
            review=False,
        )
    context.set_intent("guard_target")
    return True


def _handle_hold_position(context: TaskExecutionContext) -> bool:
    hold_ticks = max(int(context.metadata.get("hold_ticks", 5)), 1)
    hold_until = int(context.task_state.get("hold_position_until_tick", 0))
    if hold_until <= 0:
        context.task_state["hold_position_until_tick"] = int(context.tick) + hold_ticks
        context.set_intent("hold_position")
        return True
    if int(context.tick) >= hold_until:
        context.task_state.pop("hold_position_until_tick", None)
        complete_current_task(context.resident, context.tick, reason="hold_complete")
        return True
    context.set_intent("hold_position")
    return True


def _handle_finish_hunt(context: TaskExecutionContext) -> bool:
    target_id = str(context.task.get("target_id") or "").strip()
    if target_id and context.bridge.resolve_entity(target_id) is not None:
        context.task_state["blocked_reason"] = "prey_still_alive"
        context.set_intent("finish_hunt")
        return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("finish_hunt")
        return False
    output_kind = str(context.metadata.get("output_kind", "rations")).strip() or "rations"
    quantity = max(int(context.metadata.get("quantity", context.task.get("requested_quantity") or 1)), 1)
    cargo_cache = context.task_state.setdefault("cargo_cache", {})
    cargo_cache[output_kind] = max(int(cargo_cache.get(output_kind, 0)), 0) + quantity
    context.bridge.on_action(
        last_action=f"finished hunt for {quantity}x {output_kind}",
        intent="finish_hunt",
        mood_delta=0.09,
        stamina_delta=-0.8,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="hunt_processed")
    return True


def _handle_loot_after_kill(context: TaskExecutionContext) -> bool:
    complete_current_task(context.resident, context.tick, reason="loot_pending_future")
    return True


def _handle_protect_target(context: TaskExecutionContext) -> bool:
    target = _resolve_target(context)
    if target is None:
        complete_current_task(context.resident, context.tick, reason="target_missing")
        return True
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    if _distance_to_target(context, target) > max(context.bridge.gather_radius * 0.75, 10.0):
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 1.05):
            context.task_state["last_task_action"] = "moving_to_protect_target"
            context.set_intent("protect_target")
            return True
        return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("protect_target")
        return False
    target_id = str(target.get("human_id", context.task.get("target_id", ""))).strip()
    if target_id:
        context.bridge.queue_social_signal(
            target_id,
            {
                "kind": "return_to_group",
                "priority": 0.35,
                "summary": "return to safety",
            },
        )
    context.bridge.on_action(
        last_action=f"protected {target_id or 'target'}",
        intent="protect_target",
        mood_delta=0.05,
        threat_delta=-5.0,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="protected")
    return True


def execute_task_step(context: TaskExecutionContext) -> bool:
    if not can_handle_task(context.task_kind):
        return False
    if context.task_kind == "attack_target":
        return _handle_attack_target(context)
    if context.task_kind == "chase_target":
        return _handle_chase_target(context)
    if context.task_kind == "intercept_target":
        return _handle_intercept_target(context)
    if context.task_kind == "retreat_from_target":
        return _handle_retreat_from_target(context)
    if context.task_kind == "guard_area":
        return _handle_guard_area(context)
    if context.task_kind == "guard_target":
        return _handle_guard_target(context)
    if context.task_kind == "hold_position":
        return _handle_hold_position(context)
    if context.task_kind == "finish_hunt":
        return _handle_finish_hunt(context)
    if context.task_kind == "loot_after_kill":
        return _handle_loot_after_kill(context)
    if context.task_kind == "protect_target":
        return _handle_protect_target(context)
    return False


__all__ = [
    "COMBAT_TASK_KINDS",
    "can_handle_task",
    "combat_task_specs",
    "execute_task_step",
]
