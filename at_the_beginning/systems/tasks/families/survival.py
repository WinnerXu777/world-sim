from __future__ import annotations

"""Survival-family task helpers and live task-family executor."""

import math
from typing import Any

from ...inventory import remove_item as inventory_remove_item
from ..contracts import TaskExecutionContext
from ..ops import complete_current_task

try:
    from genesis_config import (
        DRINK_THIRST_RESTORE,
        EAT_HUNGER_RESTORE,
        FOOD_SEEK_THRESHOLD,
        M_HOUSE,
        M_VILLAGE,
        SHELTER_SEEK_THREAT,
        WATER_SEEK_THRESHOLD,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        DRINK_THIRST_RESTORE,
        EAT_HUNGER_RESTORE,
        FOOD_SEEK_THRESHOLD,
        M_HOUSE,
        M_VILLAGE,
        SHELTER_SEEK_THREAT,
        WATER_SEEK_THRESHOLD,
    )


SURVIVAL_TASK_KINDS = {
    "fetch_water",
    "eat_food",
    "sleep",
    "seek_shelter",
    "flee_target",
}

EDIBLE_ITEM_KINDS = ("rations", "fish_catch", "crop_bundle", "berries", "mushrooms")
FLEE_THREAT_THRESHOLD = max(70.0, float(SHELTER_SEEK_THREAT) + 18.0)
LOW_STAMINA_THRESHOLD = 24.0
RECOVERED_STAMINA_THRESHOLD = 72.0
CRITICAL_HP_THRESHOLD = 32.0


def can_handle_task(task_kind: str) -> bool:
    return str(task_kind).strip() in SURVIVAL_TASK_KINDS


def _available_edible_quantity(record: dict[str, Any]) -> int:
    total = 0
    for item in list(record.get("items", [])):
        if str(item.get("kind", "")) in EDIBLE_ITEM_KINDS:
            total += max(int(item.get("quantity", 0)), 0)
    return total


def _remove_first_edible(record: dict[str, Any]) -> str:
    for item_kind in EDIBLE_ITEM_KINDS:
        removed = inventory_remove_item(record, item_kind=item_kind, quantity=1)
        if removed.get("ok"):
            return item_kind
    return ""


def survival_task_specs(
    resident: dict[str, Any],
    *,
    hunger: float,
    thirst: float,
    threat: float,
    stamina: float,
    hp: float,
    sheltered: bool,
    personal_inventory: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    personal_inventory = personal_inventory or {}
    has_edible = _available_edible_quantity(personal_inventory) > 0

    if float(threat) >= FLEE_THREAT_THRESHOLD or (
        float(hp) <= CRITICAL_HP_THRESHOLD and float(threat) >= (float(SHELTER_SEEK_THREAT) * 0.75)
    ):
        return [
            {
                "task_kind": "flee_target",
                "priority": 0.97,
                "source": "survival",
                "summary": "flee immediate danger",
                "metadata": {
                    "reason": "danger",
                    "threat": round(float(threat), 2),
                },
            }
        ]

    if float(threat) >= float(SHELTER_SEEK_THREAT) and not bool(sheltered):
        return [
            {
                "task_kind": "seek_shelter",
                "priority": 0.86,
                "source": "survival",
                "summary": "seek nearby shelter",
                "target_kind": "place",
                "target_id": "shelter",
                "metadata": {
                    "reason": "danger",
                    "threat": round(float(threat), 2),
                },
            }
        ]

    if float(thirst) >= float(WATER_SEEK_THRESHOLD):
        return [
            {
                "task_kind": "fetch_water",
                "priority": 0.88,
                "source": "survival",
                "summary": "drink or fetch nearby water",
                "target_kind": "resource",
                "target_id": "water",
                "metadata": {
                    "thirst": round(float(thirst), 2),
                },
            }
        ]

    if float(hunger) >= float(FOOD_SEEK_THRESHOLD):
        return [
            {
                "task_kind": "eat_food",
                "priority": 0.9,
                "source": "survival",
                "summary": "eat carried or nearby food" if has_edible else "source nearby food",
                "target_kind": "resource",
                "target_id": "food",
                "metadata": {
                    "hunger": round(float(hunger), 2),
                    "has_edible": bool(has_edible),
                },
            }
        ]

    if (
        float(stamina) <= LOW_STAMINA_THRESHOLD
        and float(threat) < float(SHELTER_SEEK_THREAT) * 0.8
        and float(hunger) < 70.0
        and float(thirst) < 70.0
    ):
        return [
            {
                "task_kind": "sleep",
                "priority": 0.52,
                "source": "survival",
                "summary": "rest and recover stamina",
                "metadata": {
                    "stamina": round(float(stamina), 2),
                    "sheltered": bool(sheltered),
                },
            }
        ]

    return []


def _target_distance(context: TaskExecutionContext, target: dict[str, Any]) -> float:
    if "distance" in target:
        return float(target.get("distance", 0.0))
    return math.hypot(float(target.get("x", context.px)) - context.px, float(target.get("y", context.py)) - context.py)


def _move_to_target(
    context: TaskExecutionContext,
    target: dict[str, Any],
    *,
    intent: str,
    action: str,
    move_scale: float = 1.0,
    arrival_radius: float | None = None,
) -> bool:
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    distance = _target_distance(context, target)
    radius = context.bridge.gather_radius if arrival_radius is None else max(float(arrival_radius), 1.0)
    if distance <= radius:
        return False
    if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * max(float(move_scale), 0.25)):
        context.task_state["last_task_action"] = str(action)
        context.set_intent(intent)
        return True
    return False


def _nearby_shelter_value(target: dict[str, Any] | None) -> float | None:
    if not isinstance(target, dict):
        return None
    entity_type = int(target.get("entity_type", -1))
    if entity_type in {M_HOUSE, M_VILLAGE}:
        return 1.0
    return 0.0


def _try_consume_edible(context: TaskExecutionContext) -> str:
    eaten = _remove_first_edible(context.personal_inventory)
    if eaten:
        return eaten
    for entry in context.accessible_records:
        record = entry.get("inventory")
        if not isinstance(record, dict):
            continue
        eaten = _remove_first_edible(record)
        if eaten:
            return eaten
    return ""


def _handle_fetch_water(context: TaskExecutionContext) -> bool:
    target = context.bridge.resolve_resource("water", context.px, context.py, radius=220.0)
    if target is None:
        context.task_state["blocked_reason"] = "water_not_found"
        context.set_intent("search_water")
        return False
    if _move_to_target(
        context,
        target,
        intent="fetch_water",
        action="moving_to_water",
    ):
        return True
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("fetch_water")
        return False
    consumed = context.bridge.consume_resource("water", int(target.get("slot", -1)), 1, uid=target.get("uid"))
    if consumed <= 0:
        context.task_state["blocked_reason"] = "water_dry"
        context.set_intent("search_water")
        return False
    context.bridge.on_action(
        last_action="drank water",
        intent="fetch_water",
        mood_delta=0.2,
        thirst_delta=-float(DRINK_THIRST_RESTORE),
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="hydrated")
    return True


def _handle_eat_food(context: TaskExecutionContext) -> bool:
    eaten_kind = _try_consume_edible(context)
    if eaten_kind:
        context.bridge.on_action(
            last_action=f"ate {eaten_kind}",
            intent="eat_food",
            mood_delta=0.25,
            stamina_delta=0.4,
            hunger_delta=-float(EAT_HUNGER_RESTORE),
            review=False,
        )
        complete_current_task(context.resident, context.tick, reason="fed")
        return True
    target = context.bridge.resolve_resource("food", context.px, context.py, radius=220.0)
    if target is None:
        context.task_state["blocked_reason"] = "food_not_found"
        context.set_intent("search_food")
        return False
    if _move_to_target(
        context,
        target,
        intent="eat_food",
        action="moving_to_food",
    ):
        return True
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("eat_food")
        return False
    consumed = context.bridge.consume_resource("food", int(target.get("slot", -1)), 1, uid=target.get("uid"))
    if consumed <= 0:
        context.task_state["blocked_reason"] = "food_depleted"
        context.set_intent("search_food")
        return False
    context.bridge.on_action(
        last_action="ate nearby food",
        intent="eat_food",
        mood_delta=0.22,
        stamina_delta=0.5,
        hunger_delta=-float(EAT_HUNGER_RESTORE),
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="fed")
    return True


def _handle_seek_shelter(context: TaskExecutionContext) -> bool:
    target = context.bridge.resolve_safe(context.px, context.py, radius=240.0)
    if target is None:
        context.task_state["blocked_reason"] = "safe_place_not_found"
        context.set_intent("search_shelter")
        return False
    if _move_to_target(
        context,
        target,
        intent="seek_shelter",
        action="moving_to_shelter",
    ):
        return True
    context.bridge.on_action(
        last_action="reached shelter",
        intent="seek_shelter",
        mood_delta=0.08,
        stamina_delta=0.6,
        threat_delta=-12.0,
        shelter_value=_nearby_shelter_value(target),
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="sheltered")
    return True


def _handle_sleep(context: TaskExecutionContext) -> bool:
    current_stamina = float(context.metadata.get("stamina", 0.0))
    if current_stamina >= RECOVERED_STAMINA_THRESHOLD:
        complete_current_task(context.resident, context.tick, reason="rested")
        return True
    sheltered = bool(context.metadata.get("sheltered", False))
    safe_target = context.bridge.resolve_safe(context.px, context.py, radius=220.0) if not sheltered else None
    if safe_target is not None and _move_to_target(
        context,
        safe_target,
        intent="sleep",
        action="moving_to_sleep",
        arrival_radius=context.bridge.gather_radius * 0.75,
    ):
        return True
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("sleep")
        return False
    context.bridge.on_action(
        last_action="rested",
        intent="sleep",
        mood_delta=0.18,
        stamina_delta=12.0,
        threat_delta=-4.0,
        shelter_value=(1.0 if sheltered else _nearby_shelter_value(safe_target)),
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="rest_cycle")
    return True


def _handle_flee_target(context: TaskExecutionContext) -> bool:
    target = context.bridge.resolve_safe(context.px, context.py, radius=260.0)
    if target is None:
        context.task_state["blocked_reason"] = "safe_place_not_found"
        context.set_intent("flee_target")
        return False
    if _move_to_target(
        context,
        target,
        intent="flee_target",
        action="fleeing_to_safety",
        move_scale=1.8,
        arrival_radius=context.bridge.gather_radius * 0.85,
    ):
        return True
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("flee_target")
        return False
    context.bridge.on_action(
        last_action="fled danger",
        intent="flee_target",
        mood_delta=-0.08,
        stamina_delta=-2.0,
        threat_delta=-20.0,
        shelter_value=_nearby_shelter_value(target),
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="escaped")
    return True


def execute_task_step(context: TaskExecutionContext) -> bool:
    if not can_handle_task(context.task_kind):
        return False
    if context.task_kind == "fetch_water":
        return _handle_fetch_water(context)
    if context.task_kind == "eat_food":
        return _handle_eat_food(context)
    if context.task_kind == "seek_shelter":
        return _handle_seek_shelter(context)
    if context.task_kind == "sleep":
        return _handle_sleep(context)
    if context.task_kind == "flee_target":
        return _handle_flee_target(context)
    return False


__all__ = [
    "SURVIVAL_TASK_KINDS",
    "can_handle_task",
    "execute_task_step",
    "survival_task_specs",
]
