from __future__ import annotations

"""Social-family task helpers with live courtship and social follow-through."""

import math
from typing import Any

from ..contracts import TaskExecutionContext
from ..ops import complete_current_task

try:
    from genesis_config import (
        MATURE_AGE,
        PROXIMITY_MATE_RADIUS,
        SAFE_REPRO_HP_MIN,
        SAFE_REPRO_HUNGER_MAX,
        SAFE_REPRO_STAMINA_MIN,
        SAFE_REPRO_THIRST_MAX,
        SAFE_REPRO_THREAT_MAX,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        MATURE_AGE,
        PROXIMITY_MATE_RADIUS,
        SAFE_REPRO_HP_MIN,
        SAFE_REPRO_HUNGER_MAX,
        SAFE_REPRO_STAMINA_MIN,
        SAFE_REPRO_THIRST_MAX,
        SAFE_REPRO_THREAT_MAX,
    )


SOCIAL_TASK_KINDS = {
    "socialize",
    "approach_target",
    "follow_target",
    "talk_to_target",
    "warn_target",
    "call_for_help",
    "help_target",
    "deliver_item",
    "escort_target",
    "return_to_group",
    "thank_helper",
    "comfort_target",
    "report_crime",
    "challenge_target",
    "seek_mate",
    "mate_with_target",
}

SOCIAL_APPROACH_RADIUS = 8.0
FOLLOW_RADIUS = 10.0


def can_handle_task(task_kind: str) -> bool:
    return str(task_kind).strip() in SOCIAL_TASK_KINDS


def _signal_task_specs(signal: dict[str, Any]) -> list[dict[str, Any]]:
    signal_kind = str(signal.get("kind", "")).strip()
    if not signal_kind:
        return []
    target_human_id = str(signal.get("target_human_id") or signal.get("target_id") or "").strip()
    target_name = str(signal.get("target_name") or target_human_id or "target").strip()
    priority = float(signal.get("priority", 0.52))
    metadata = {
        key: value
        for key, value in dict(signal).items()
        if key not in {"kind", "priority", "target_id", "target_human_id", "target_name"}
    }
    if target_human_id:
        metadata.setdefault("target_human_id", target_human_id)
        metadata.setdefault("target_name", target_name)
    if signal_kind in {
        "approach_target",
        "follow_target",
        "talk_to_target",
        "warn_target",
        "help_target",
        "escort_target",
        "thank_helper",
        "comfort_target",
        "report_crime",
        "challenge_target",
    } and not target_human_id:
        return []
    if signal_kind == "deliver_item":
        item_kind = str(signal.get("item_kind", "")).strip()
        quantity = max(int(signal.get("quantity", 1)), 1)
        if not target_human_id or not item_kind:
            return []
        metadata["item_kind"] = item_kind
        metadata["quantity"] = quantity
    return [
        {
            "task_kind": signal_kind,
            "priority": priority,
            "source": "social",
            "summary": str(signal.get("summary", signal_kind.replace("_", " "))),
            "target_kind": "human" if target_human_id else "",
            "target_id": target_human_id or None,
            "requested_quantity": metadata.get("quantity"),
            "metadata": metadata,
        }
    ]


def social_task_specs(
    resident: dict[str, Any],
    *,
    age: float,
    cooldown: float,
    hunger: float,
    thirst: float,
    threat: float,
    hp: float,
    stamina: float,
    candidate: dict[str, Any] | None,
    signal: dict[str, Any] | None = None,
    help_target: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    signal_specs = _signal_task_specs(dict(signal or {}))
    if signal_specs:
        return signal_specs

    if isinstance(help_target, dict):
        target_id = str(help_target.get("human_id", "")).strip()
        if target_id:
            target_name = str(help_target.get("name", target_id)).strip() or target_id
            return [
                {
                    "task_kind": "help_target",
                    "priority": 0.52,
                    "source": "social",
                    "summary": f"help {target_name}",
                    "target_kind": "human",
                    "target_id": target_id,
                    "metadata": {
                        "target_human_id": target_id,
                        "target_name": target_name,
                        "item_kind": "bandage",
                    },
                }
            ]

    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    if routine_kind not in {"socialize", "stay_home", "wander_local"}:
        return []
    if routine_kind == "socialize" and not isinstance(candidate, dict):
        return [
            {
                "task_kind": "socialize",
                "priority": 0.28,
                "source": "social",
                "summary": "socialize nearby",
                "target_kind": "place",
                "target_id": "settlement",
                "metadata": {"routine_kind": routine_kind},
            }
        ]
    if float(age) < float(MATURE_AGE):
        if routine_kind == "socialize":
            return [
                {
                    "task_kind": "socialize",
                    "priority": 0.28,
                    "source": "social",
                    "summary": "socialize nearby",
                    "target_kind": "place",
                    "target_id": "settlement",
                    "metadata": {"routine_kind": routine_kind},
                }
            ]
        return []
    if float(cooldown) > 0.0:
        return []
    if float(hunger) > float(SAFE_REPRO_HUNGER_MAX):
        return []
    if float(thirst) > float(SAFE_REPRO_THIRST_MAX):
        return []
    if float(threat) > float(SAFE_REPRO_THREAT_MAX):
        return []
    if float(hp) < float(SAFE_REPRO_HP_MIN):
        return []
    if float(stamina) < float(SAFE_REPRO_STAMINA_MIN):
        return []
    if not isinstance(candidate, dict):
        if routine_kind == "socialize":
            return [
                {
                    "task_kind": "socialize",
                    "priority": 0.28,
                    "source": "social",
                    "summary": "socialize nearby",
                    "target_kind": "place",
                    "target_id": "settlement",
                    "metadata": {"routine_kind": routine_kind},
                }
            ]
        return []

    target_id = str(candidate.get("human_id", "")).strip()
    if not target_id:
        return []
    target_name = str(candidate.get("name", target_id)).strip() or target_id
    distance = float(candidate.get("distance", 10**9))
    metadata = {
        "target_human_id": target_id,
        "target_name": target_name,
        "target_slot": int(candidate.get("slot", -1)),
    }
    if distance <= float(PROXIMITY_MATE_RADIUS):
        return [
            {
                "task_kind": "mate_with_target",
                "priority": 0.38,
                "source": "social",
                "summary": f"court {target_name}",
                "target_kind": "human",
                "target_id": target_id,
                "metadata": dict(metadata, distance=round(distance, 2)),
            }
        ]
    return [
        {
            "task_kind": "seek_mate",
            "priority": 0.34,
            "source": "social",
            "summary": f"approach {target_name}",
            "target_kind": "human",
            "target_id": target_id,
            "metadata": dict(metadata, distance=round(distance, 2)),
        },
        {
            "task_kind": "mate_with_target",
            "priority": 0.38,
            "source": "social",
            "summary": f"court {target_name}",
            "target_kind": "human",
            "target_id": target_id,
            "metadata": dict(metadata),
        },
    ]


def _distance_to_target(context: TaskExecutionContext, target: dict[str, Any]) -> float:
    if "distance" in target:
        return float(target.get("distance", 0.0))
    return math.hypot(float(target.get("x", context.px)) - context.px, float(target.get("y", context.py)) - context.py)


def _resolve_human_target(context: TaskExecutionContext) -> dict[str, Any] | None:
    target_id = str(context.task.get("target_id") or context.metadata.get("target_human_id") or "").strip()
    if not target_id:
        return None
    return context.bridge.resolve_human(target_id)


def _self_human_id(context: TaskExecutionContext) -> str:
    return str(context.resident.get("id", "") or context.resident.get("profile", {}).get("id", "") or "").strip()


def _approach_human_target(
    context: TaskExecutionContext,
    *,
    intent: str,
    action: str,
    arrival_radius: float = SOCIAL_APPROACH_RADIUS,
    move_scale: float = 1.0,
) -> tuple[dict[str, Any] | None, bool]:
    target = _resolve_human_target(context)
    if target is None:
        context.task_state["blocked_reason"] = "social_target_missing"
        return None, False
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    if _distance_to_target(context, target) > max(float(arrival_radius), 1.0):
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * max(float(move_scale), 0.4)):
            context.task_state["last_task_action"] = str(action)
            context.set_intent(intent)
            return target, True
        return target, False
    return target, True


def _handle_seek_mate(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="seek_mate",
        action="approaching_mate",
        arrival_radius=float(PROXIMITY_MATE_RADIUS),
        move_scale=1.15,
    )
    if target is None:
        context.set_intent("search_mate")
        return False
    if _distance_to_target(context, target) <= float(PROXIMITY_MATE_RADIUS):
        complete_current_task(context.resident, context.tick, reason="mate_in_range")
    return ready


def _handle_socialize(context: TaskExecutionContext) -> bool:
    target = context.bridge.resolve_place("settlement", context.px, context.py, radius=180.0)
    if target is not None:
        tx = float(target.get("x", context.px))
        ty = float(target.get("y", context.py))
        if _distance_to_target(context, target) > context.bridge.gather_radius * 1.2:
            if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 0.9):
                context.task_state["last_task_action"] = "moving_to_social_area"
                context.set_intent("socialize")
                return True
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("socialize")
        return False
    context.bridge.on_action(
        last_action="socialized",
        intent="socialize",
        mood_delta=0.18,
        threat_delta=-4.0,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="socialized")
    return True


def _handle_approach_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="approach_target",
        action="approaching_target",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) <= SOCIAL_APPROACH_RADIUS:
        complete_current_task(context.resident, context.tick, reason="arrived")
    return ready


def _handle_follow_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="follow_target",
        action="following_target",
        arrival_radius=FOLLOW_RADIUS,
        move_scale=1.05,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) <= FOLLOW_RADIUS:
        hold_ticks = max(int(context.metadata.get("hold_ticks", 5)), 1)
        follow_until = int(context.task_state.get("follow_until_tick", 0))
        if follow_until <= 0:
            context.task_state["follow_until_tick"] = int(context.tick) + hold_ticks
            context.set_intent("follow_target")
            return True
        if int(context.tick) >= follow_until:
            context.task_state.pop("follow_until_tick", None)
            complete_current_task(context.resident, context.tick, reason="followed")
    return ready


def _handle_talk_to_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="talk_to_target",
        action="approaching_talk_target",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > SOCIAL_APPROACH_RADIUS:
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("talk_to_target")
        return False
    context.bridge.on_action(
        last_action=f"talked to {target.get('human_id', context.task.get('target_id', 'target'))}",
        intent="talk_to_target",
        mood_delta=0.05,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="talked")
    return True


def _handle_warn_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="warn_target",
        action="approaching_warn_target",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > SOCIAL_APPROACH_RADIUS:
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("warn_target")
        return False
    context.bridge.on_action(
        last_action=f"warned {target.get('human_id', context.task.get('target_id', 'target'))}",
        intent="warn_target",
        mood_delta=-0.02,
        threat_delta=4.0,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="warned")
    return True


def _handle_call_for_help(context: TaskExecutionContext) -> bool:
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("call_for_help")
        return False
    caller_id = _self_human_id(context)
    support = context.bridge.resolve_support(context.px, context.py, radius=96.0)
    if caller_id and isinstance(support, dict):
        support_id = str(support.get("human_id", "")).strip()
        if support_id and support_id != caller_id:
            context.bridge.queue_social_signal(
                support_id,
                {
                    "kind": "help_target",
                    "priority": 0.66,
                    "target_human_id": caller_id,
                    "target_name": str(context.resident.get("profile", {}).get("name", caller_id)),
                    "summary": "answer distress call",
                    "item_kind": "bandage",
                },
            )
    context.bridge.on_action(
        last_action="called for help",
        intent="call_for_help",
        mood_delta=-0.05,
        threat_delta=-6.0,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="called")
    return True


def _handle_help_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="help_target",
        action="approaching_help_target",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > SOCIAL_APPROACH_RADIUS:
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("help_target")
        return False
    item_kind = str(context.metadata.get("item_kind", "bandage")).strip() or "bandage"
    result = context.bridge.try_heal_target(str(target.get("human_id", "")), item_kind=item_kind)
    if not bool(result.get("ok", False)):
        context.task_state["blocked_reason"] = str(result.get("reason", "heal_blocked"))
        context.set_intent("help_target")
        return False
    target_id = str(target.get("human_id", context.task.get("target_id", ""))).strip()
    helper_id = _self_human_id(context)
    if target_id and helper_id:
        context.bridge.queue_social_signal(
            target_id,
            {
                "kind": "thank_helper",
                "priority": 0.34,
                "target_human_id": helper_id,
                "target_name": str(context.resident.get("profile", {}).get("name", helper_id) or helper_id),
                "summary": "thank helper",
            },
        )
    target_after = context.bridge.resolve_human(target_id) if target_id else None
    if isinstance(target_after, dict):
        if float(target_after.get("threat", 0.0)) >= 32.0:
            context.resident.setdefault("task_state", {})["pending_social_signal"] = {
                "kind": "escort_target",
                "priority": 0.58,
                "target_human_id": target_id,
                "target_name": str(target_after.get("name", target_id)),
                "summary": "escort wounded target",
            }
        elif float(target_after.get("hp", 100.0)) < 72.0:
            context.resident.setdefault("task_state", {})["pending_social_signal"] = {
                "kind": "comfort_target",
                "priority": 0.44,
                "target_human_id": target_id,
                "target_name": str(target_after.get("name", target_id)),
                "summary": "comfort helped target",
            }
    context.bridge.on_action(
        last_action=f"helped {target_id or context.task.get('target_id', 'target')}",
        intent="help_target",
        mood_delta=0.16,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="helped")
    return True


def _handle_deliver_item(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="deliver_item",
        action="approaching_delivery_target",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > SOCIAL_APPROACH_RADIUS:
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("deliver_item")
        return False
    item_kind = str(context.metadata.get("item_kind", "")).strip()
    quantity = max(int(context.metadata.get("quantity", 1)), 1)
    if not item_kind:
        complete_current_task(context.resident, context.tick, reason="missing_item_kind")
        return True
    result = context.bridge.try_deliver_item(str(target.get("human_id", "")), item_kind, quantity)
    if not bool(result.get("ok", False)):
        context.task_state["blocked_reason"] = str(result.get("reason", "delivery_blocked"))
        context.set_intent("deliver_item")
        return False
    context.bridge.on_action(
        last_action=f"delivered {item_kind}",
        intent="deliver_item",
        mood_delta=0.08,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="delivered")
    return True


def _handle_escort_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="escort_target",
        action="approaching_escort_target",
        arrival_radius=FOLLOW_RADIUS,
        move_scale=1.05,
    )
    if target is None:
        return False
    target_id = str(target.get("human_id", context.task.get("target_id", ""))).strip()
    self_id = _self_human_id(context)
    if target_id and self_id and not bool(context.task_state.get("escort_follow_signal_sent", False)):
        context.bridge.queue_social_signal(
            target_id,
            {
                "kind": "follow_target",
                "priority": 0.43,
                "target_human_id": self_id,
                "target_name": str(context.resident.get("profile", {}).get("name", self_id) or self_id),
                "summary": "follow escort",
                "hold_ticks": max(int(context.metadata.get("hold_ticks", 6)), 3),
            },
        )
        context.task_state["escort_follow_signal_sent"] = True
    if _distance_to_target(context, target) > FOLLOW_RADIUS:
        return ready
    safe_target = context.bridge.resolve_safe(context.px, context.py, radius=220.0) or context.bridge.resolve_place(
        "settlement",
        context.px,
        context.py,
        radius=220.0,
    )
    if safe_target is None:
        complete_current_task(context.resident, context.tick, reason="no_safe_anchor")
        return True
    tx = float(safe_target.get("x", context.px))
    ty = float(safe_target.get("y", context.py))
    if _distance_to_target(context, {"x": tx, "y": ty}) > context.bridge.gather_radius:
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step):
            context.task_state["last_task_action"] = "escorting_to_shelter"
            context.set_intent("escort_target")
            return True
        return False
    context.task_state.pop("escort_follow_signal_sent", None)
    context.bridge.on_action(
        last_action=f"escorted {target_id or 'target'} to safety",
        intent="escort_target",
        mood_delta=0.11,
        threat_delta=-8.0,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="escorted")
    return True


def _handle_return_to_group(context: TaskExecutionContext) -> bool:
    anchor = context.bridge.resolve_place("settlement", context.px, context.py, radius=220.0) or context.bridge.resolve_place(
        "home",
        context.px,
        context.py,
        radius=220.0,
    )
    if anchor is None:
        complete_current_task(context.resident, context.tick, reason="no_group_anchor")
        return True
    tx = float(anchor.get("x", context.px))
    ty = float(anchor.get("y", context.py))
    if _distance_to_target(context, anchor) > context.bridge.gather_radius:
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 0.9):
            context.task_state["last_task_action"] = "returning_to_group"
            context.set_intent("return_to_group")
            return True
        return False
    context.bridge.on_action(
        last_action="returned to group",
        intent="return_to_group",
        mood_delta=0.03,
        threat_delta=-3.0,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="returned")
    return True


def _handle_thank_helper(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="thank_helper",
        action="approaching_helper",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > SOCIAL_APPROACH_RADIUS:
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("thank_helper")
        return False
    context.bridge.on_action(
        last_action=f"thanked {target.get('human_id', context.task.get('target_id', 'helper'))}",
        intent="thank_helper",
        mood_delta=0.12,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="thanked")
    return True


def _handle_comfort_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="comfort_target",
        action="approaching_comfort_target",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > SOCIAL_APPROACH_RADIUS:
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("comfort_target")
        return False
    context.bridge.on_action(
        last_action=f"comforted {target.get('human_id', context.task.get('target_id', 'target'))}",
        intent="comfort_target",
        mood_delta=0.1,
        threat_delta=-6.0,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="comforted")
    return True


def _handle_report_crime(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="report_crime",
        action="approaching_guard",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > SOCIAL_APPROACH_RADIUS:
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("report_crime")
        return False
    accused_id = str(context.metadata.get("accused_human_id", "")).strip()
    if accused_id:
        context.bridge.queue_combat_signal(
            str(target.get("human_id", "")),
            {
                "kind": "intercept_target",
                "priority": 0.9,
                "target_kind": "human",
                "target_id": accused_id,
                "target_name": str(context.metadata.get("accused_name", accused_id) or accused_id),
                "reason": "reported_crime",
                "summary": "intercept reported criminal",
            },
        )
    context.bridge.on_action(
        last_action=f"reported crime to {target.get('human_id', context.task.get('target_id', 'guard'))}",
        intent="report_crime",
        mood_delta=-0.02,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="reported")
    return True


def _handle_challenge_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="challenge_target",
        action="approaching_challenge_target",
        arrival_radius=SOCIAL_APPROACH_RADIUS,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > SOCIAL_APPROACH_RADIUS:
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("challenge_target")
        return False
    if bool(context.metadata.get("escalate_to_attack", False)):
        target_id = str(target.get("human_id", context.task.get("target_id", ""))).strip()
        if target_id:
            context.resident.setdefault("task_state", {})["pending_combat_signal"] = {
                "kind": "attack_target",
                "priority": 0.91,
                "target_kind": "human",
                "target_id": target_id,
                "target_name": str(target.get("name", target_id) or target_id),
                "reason": "social_challenge",
                "summary": "attack after challenge",
            }
    context.bridge.on_action(
        last_action=f"challenged {target.get('human_id', context.task.get('target_id', 'target'))}",
        intent="challenge_target",
        mood_delta=-0.04,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="challenged")
    return True


def _handle_mate_with_target(context: TaskExecutionContext) -> bool:
    target, ready = _approach_human_target(
        context,
        intent="seek_mate",
        action="closing_for_mate",
        arrival_radius=float(PROXIMITY_MATE_RADIUS),
        move_scale=1.1,
    )
    if target is None:
        return False
    if _distance_to_target(context, target) > float(PROXIMITY_MATE_RADIUS):
        return ready
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("mate_with_target")
        return False
    result = context.bridge.try_mate_with_target(str(target.get("human_id", "")))
    if not bool(result.get("ok", False)):
        context.task_state["blocked_reason"] = str(result.get("reason", "mate_blocked"))
        context.set_intent("mate_with_target")
        return False
    context.bridge.on_action(
        last_action="mated",
        intent="mate_with_target",
        mood_delta=0.35,
        stamina_delta=-3.0,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="mated")
    return True


def execute_task_step(context: TaskExecutionContext) -> bool:
    if not can_handle_task(context.task_kind):
        return False
    if context.task_kind == "socialize":
        return _handle_socialize(context)
    if context.task_kind == "approach_target":
        return _handle_approach_target(context)
    if context.task_kind == "follow_target":
        return _handle_follow_target(context)
    if context.task_kind == "talk_to_target":
        return _handle_talk_to_target(context)
    if context.task_kind == "warn_target":
        return _handle_warn_target(context)
    if context.task_kind == "call_for_help":
        return _handle_call_for_help(context)
    if context.task_kind == "help_target":
        return _handle_help_target(context)
    if context.task_kind == "deliver_item":
        return _handle_deliver_item(context)
    if context.task_kind == "escort_target":
        return _handle_escort_target(context)
    if context.task_kind == "return_to_group":
        return _handle_return_to_group(context)
    if context.task_kind == "thank_helper":
        return _handle_thank_helper(context)
    if context.task_kind == "comfort_target":
        return _handle_comfort_target(context)
    if context.task_kind == "report_crime":
        return _handle_report_crime(context)
    if context.task_kind == "challenge_target":
        return _handle_challenge_target(context)
    if context.task_kind == "seek_mate":
        return _handle_seek_mate(context)
    if context.task_kind == "mate_with_target":
        return _handle_mate_with_target(context)
    return False


__all__ = [
    "SOCIAL_TASK_KINDS",
    "can_handle_task",
    "execute_task_step",
    "social_task_specs",
]
