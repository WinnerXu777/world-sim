from __future__ import annotations

"""Strategic-family execution for plan-driven resident task chains."""

import math
from typing import Any

from ...inventory import add_item as inventory_add_item, equip_main_hand_item, has_item, transfer_item as inventory_transfer_item
from ..contracts import TaskExecutionContext
from ..ops import complete_current_task


STRATEGIC_TASK_KINDS = {
    "acquire_weapon",
    "move_to_ambush_point",
    "wait_in_hiding",
    "recruit_ally",
    "steal_from_container",
    "escape_area",
    "scout_area",
    "protect_home",
    "gather_food_buffer",
}

WEAPON_PRIORITY = ("spear", "axe", "club", "knife")


def can_handle_task(task_kind: str) -> bool:
    return str(task_kind).strip() in STRATEGIC_TASK_KINDS


def _active_plan(resident: dict[str, Any]) -> dict[str, Any] | None:
    plans = [
        dict(plan)
        for plan in list(resident.get("plans", []))
        if isinstance(plan, dict) and str(plan.get("status", "queued")) in {"queued", "active"}
    ]
    if not plans:
        return None
    plans.sort(
        key=lambda plan: (
            float(plan.get("priority", 0.0)),
            float(plan.get("confidence", 0.0)),
            int(plan.get("last_update_tick", plan.get("created_tick", 0))),
        ),
        reverse=True,
    )
    return plans[0]


def _plan_record_ref(resident: dict[str, Any], plan_id: str) -> dict[str, Any] | None:
    needle = str(plan_id or "").strip()
    if not needle:
        return None
    for plan in list(resident.get("plans", [])):
        if str(plan.get("id", "")) == needle:
            return plan
    return None


def _sync_plan_progress_from_last_task(resident: dict[str, Any], tick: int) -> None:
    state = resident.setdefault("task_state", {})
    last_completed = state.get("last_completed_task")
    if not isinstance(last_completed, dict) or not last_completed:
        return
    metadata = dict(last_completed.get("metadata", {}))
    if not bool(metadata.get("advance_plan_on_complete", False)):
        return
    if bool(metadata.get("plan_progress_applied", False)):
        return
    plan_id = str(last_completed.get("plan_id") or metadata.get("plan_id") or "").strip()
    if not plan_id:
        state["last_completed_task"] = {}
        return
    plan = _plan_record_ref(resident, plan_id)
    if plan is None:
        state["last_completed_task"] = {}
        return
    completed_step_index = int(metadata.get("step_index", -1))
    current_index = int(plan.get("current_step_index", 0))
    if completed_step_index != current_index:
        metadata["plan_progress_applied"] = True
        last_completed["metadata"] = metadata
        state["last_completed_task"] = last_completed
        return
    step_count = len(list(plan.get("steps", [])))
    if step_count <= 0 or completed_step_index + 1 >= step_count:
        plan["status"] = "completed"
        plan["current_step_index"] = max(step_count, 0)
    else:
        plan["status"] = "active"
        plan["current_step_index"] = completed_step_index + 1
    plan["last_update_tick"] = int(tick)
    metadata["plan_progress_applied"] = True
    last_completed["metadata"] = metadata
    state["last_completed_task"] = last_completed


def _decorate_plan_specs(plan: dict[str, Any], step_index: int, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for spec in specs:
        record = dict(spec)
        metadata = dict(record.get("metadata", {}))
        metadata.setdefault("plan_id", str(plan.get("id", "")))
        metadata.setdefault("plan_kind", str(plan.get("plan_kind", "")))
        metadata.setdefault("step_index", int(step_index))
        metadata.setdefault("advance_plan_on_complete", True)
        record["metadata"] = metadata
        record["plan_id"] = str(plan.get("id", ""))
        record["goal_id"] = plan.get("goal_id")
        record.setdefault("source", "strategic")
        decorated.append(record)
    return decorated


def _has_weapon(record: dict[str, Any]) -> bool:
    return any(has_item(record, item_kind, 1) for item_kind in WEAPON_PRIORITY)


def _plan_step_specs(plan: dict[str, Any], resident: dict[str, Any], *, personal_inventory: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    personal_inventory = personal_inventory or {}
    steps = list(plan.get("steps", []))
    if not steps:
        return []
    step_index = max(min(int(plan.get("current_step_index", 0)), len(steps) - 1), 0)
    step = dict(steps[step_index])
    op = str(step.get("op", "")).strip()
    target_id = str(step.get("target_id", "") or "").strip()
    place_hint = str(step.get("place_hint", "") or "").strip()
    threshold = step.get("threshold")
    target_tick = step.get("target_tick")
    metadata = dict(step.get("metadata", {}))

    specs: list[dict[str, Any]] = []
    if op in {"move_to_place", "return_home"}:
        specs = [
            {
                "task_kind": "move_to_ambush_point",
                "priority": 0.62,
                "source": "strategic",
                "summary": f"move to {place_hint or 'home'}",
                "target_kind": "place",
                "target_id": place_hint or "home",
                "metadata": {"place_tag": place_hint or "home"},
            }
        ]
    elif op in {"move_to_target", "observe_target"} and target_id:
        specs = [
            {
                "task_kind": "move_to_ambush_point",
                "priority": 0.63,
                "source": "strategic",
                "summary": f"shadow {target_id}",
                "target_kind": "human",
                "target_id": target_id,
                "metadata": {
                    "target_human_id": target_id,
                    "arrival_radius": 14.0 if op == "observe_target" else 9.0,
                },
            }
        ]
        if op == "observe_target":
            specs.append(
                {
                    "task_kind": "wait_in_hiding",
                    "priority": 0.47,
                    "source": "strategic",
                    "summary": f"observe {target_id}",
                    "target_kind": "human",
                    "target_id": target_id,
                    "metadata": {
                        "target_human_id": target_id,
                        "hold_ticks": 8,
                    },
                }
            )
    elif op == "wait_until_tick":
        specs = [
            {
                "task_kind": "wait_in_hiding",
                "priority": 0.44,
                "source": "strategic",
                "summary": "wait in hiding",
                "metadata": {
                    "target_tick": int(target_tick) if target_tick is not None else None,
                    "hold_ticks": 8,
                },
            }
        ]
    elif op in {"recover_until_hp", "rest_until_safe"}:
        specs = [
            {
                "task_kind": "wait_in_hiding",
                "priority": 0.46,
                "source": "strategic",
                "summary": "recover quietly",
                "target_kind": "place",
                "target_id": "home",
                "metadata": {
                    "place_tag": "home",
                    "hp_threshold": float(threshold) if threshold is not None else 60.0,
                    "hold_ticks": 10,
                },
            }
        ]
    elif op == "recruit_allies":
        ally_target = str(metadata.get("target_human_id", target_id)).strip()
        if ally_target:
            specs = [
                {
                    "task_kind": "recruit_ally",
                    "priority": 0.5,
                    "source": "strategic",
                    "summary": f"recruit {ally_target}",
                    "target_kind": "human",
                    "target_id": ally_target,
                    "metadata": {"target_human_id": ally_target},
                }
            ]
    elif op == "steal_from_target_when_safe":
        specs = [
            {
                "task_kind": "steal_from_container",
                "priority": 0.57,
                "source": "strategic",
                "summary": "steal valuable goods",
                "target_kind": "container",
                "target_id": target_id or str(metadata.get("target_container_id", "")) or None,
                "metadata": {
                    "item_kind": str(metadata.get("item_kind", "coin") or "coin"),
                    "quantity": max(int(metadata.get("quantity", 1)), 1),
                },
            }
        ]
    elif op == "avoid_target" and target_id:
        specs = [
            {
                "task_kind": "escape_area",
                "priority": 0.72,
                "source": "strategic",
                "summary": f"escape {target_id}",
                "target_kind": "human",
                "target_id": target_id,
                "metadata": {
                    "target_human_id": target_id,
                    "escape_radius": 26.0,
                },
            }
        ]
    elif op == "guard_place":
        guard_place = place_hint or "home"
        specs = [
            {
                "task_kind": "guard_area",
                "priority": 0.61,
                "source": "strategic",
                "summary": f"guard {guard_place}",
                "target_kind": "place",
                "target_id": guard_place,
                "metadata": {
                    "place_tag": guard_place,
                    "patrol_radius": 14.0 if guard_place == "home" else 18.0,
                    "reason": "strategic_guard_place",
                },
            }
        ]
    elif op == "gather_food_buffer":
        specs = [
            {
                "task_kind": "gather_food_buffer",
                "priority": 0.58,
                "source": "strategic",
                "summary": "gather a food buffer",
                "metadata": {
                    "desired_quantity": max(int(metadata.get("desired_quantity", 2)), 1),
                },
            }
        ]
    elif op == "attack_target_when_close" and target_id:
        specs = []
        if not _has_weapon(personal_inventory):
            specs.append(
                {
                    "task_kind": "acquire_weapon",
                    "priority": 0.66,
                    "source": "strategic",
                    "summary": "arm for plan",
                    "metadata": {"preferred_weapon": "spear"},
                }
            )
        specs.append(
            {
                "task_kind": "attack_target",
                "priority": 0.9,
                "source": "strategic",
                "summary": f"attack {target_id}",
                "target_kind": "human",
                "target_id": target_id,
                "metadata": {"target_human_id": target_id},
            }
        )

    if not specs:
        plan_kind = str(plan.get("plan_kind", "")).strip()
        if plan_kind in {"ambush", "revenge"}:
            fallback_target = str(metadata.get("target_human_id", target_id)).strip()
            if not _has_weapon(personal_inventory):
                specs = [
                    {
                        "task_kind": "acquire_weapon",
                        "priority": 0.64,
                        "source": "strategic",
                        "summary": "acquire weapon",
                        "metadata": {"preferred_weapon": "spear"},
                    }
                ]
            elif fallback_target:
                specs = [
                    {
                        "task_kind": "move_to_ambush_point",
                        "priority": 0.6,
                        "source": "strategic",
                        "summary": f"move near {fallback_target}",
                        "target_kind": "human",
                        "target_id": fallback_target,
                        "metadata": {"target_human_id": fallback_target, "arrival_radius": 10.0},
                    },
                    {
                        "task_kind": "wait_in_hiding",
                        "priority": 0.44,
                        "source": "strategic",
                        "summary": "hold in hiding",
                        "target_kind": "human",
                        "target_id": fallback_target,
                        "metadata": {"target_human_id": fallback_target, "hold_ticks": 8},
                    },
                    {
                        "task_kind": "attack_target",
                        "priority": 0.9,
                        "source": "strategic",
                        "summary": f"attack {fallback_target}",
                        "target_kind": "human",
                        "target_id": fallback_target,
                        "metadata": {"target_human_id": fallback_target},
                    },
                ]
        elif plan_kind == "fortify_home":
            specs = [
                {
                    "task_kind": "protect_home",
                    "priority": 0.6,
                    "source": "strategic",
                    "summary": "protect home",
                    "target_kind": "place",
                    "target_id": "home",
                    "metadata": {"place_tag": "home"},
                }
            ]
        elif plan_kind == "avoid_target" and (fallback_target := str(metadata.get("target_human_id", target_id)).strip()):
            specs = [
                {
                    "task_kind": "escape_area",
                    "priority": 0.72,
                    "source": "strategic",
                    "summary": f"escape {fallback_target}",
                    "target_kind": "human",
                    "target_id": fallback_target,
                    "metadata": {"target_human_id": fallback_target, "escape_radius": 26.0},
                }
            ]

    return _decorate_plan_specs(plan, step_index, specs)


def strategic_task_specs(
    resident: dict[str, Any],
    *,
    tick: int,
    personal_inventory: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    _sync_plan_progress_from_last_task(resident, tick)
    plan = _active_plan(resident)
    if plan is None:
        return []
    return _plan_step_specs(plan, resident, personal_inventory=personal_inventory)


def _equip_first_weapon(record: dict[str, Any]) -> bool:
    for item_kind in WEAPON_PRIORITY:
        for item in list(record.get("items", [])):
            if str(item.get("kind", "")) != item_kind:
                continue
            if int(item.get("quantity", 0)) <= 0:
                continue
            if equip_main_hand_item(record, str(item.get("id", ""))) is not None:
                return True
    return False


def _preferred_weapon(context: TaskExecutionContext) -> str:
    return str(context.metadata.get("preferred_weapon", "spear")).strip() or "spear"


def _advance_and_complete(context: TaskExecutionContext, reason: str) -> bool:
    complete_current_task(context.resident, context.tick, reason=reason)
    return True


def _handle_acquire_weapon(context: TaskExecutionContext) -> bool:
    if _has_weapon(context.personal_inventory):
        _equip_first_weapon(context.personal_inventory)
        context.bridge.on_action(last_action="armed self", intent="acquire_weapon", mood_delta=0.04, review=False)
        return _advance_and_complete(context, "weapon_ready")

    preferred_weapon = _preferred_weapon(context)
    for entry in context.accessible_records:
        record = entry.get("inventory")
        if not isinstance(record, dict) or not has_item(record, preferred_weapon, 1):
            continue
        moved = inventory_transfer_item(record, context.personal_inventory, item_kind=preferred_weapon, quantity=1)
        if moved.get("ok"):
            _equip_first_weapon(context.personal_inventory)
            context.bridge.on_action(last_action=f"withdrew {preferred_weapon}", intent="acquire_weapon", mood_delta=0.04, review=False)
            return _advance_and_complete(context, "weapon_ready")

    requirements = {
        "spear": (("wood_bundle", 2), ("stone_blade", 1), ("fiber_bundle", 1)),
        "club": (("wood_bundle", 2),),
    }.get(preferred_weapon, (("wood_bundle", 2), ("stone_blade", 1), ("fiber_bundle", 1)))
    material_cache = context.crafting_state.setdefault("material_cache", {})
    for item_kind, quantity in requirements:
        if context.bridge.ingredient_quantity(item_kind, material_cache) >= quantity:
            continue
        progressed = context.bridge.progress_to_item(item_kind, quantity)
        context.set_intent(f"acquire_{preferred_weapon}")
        if progressed:
            context.task_state["last_task_action"] = f"gathering_{item_kind}"
        else:
            context.task_state["blocked_reason"] = f"missing_{item_kind}"
        return progressed

    need = {"tool_kind": preferred_weapon, "recipe_id": preferred_weapon}
    if context.bridge.try_craft_tool(preferred_weapon, need):
        _equip_first_weapon(context.personal_inventory)
        context.bridge.on_action(last_action=f"crafted {preferred_weapon}", intent="acquire_weapon", mood_delta=0.05, review=False)
        return _advance_and_complete(context, "weapon_ready")
    context.task_state["blocked_reason"] = f"craft_wait:{preferred_weapon}"
    context.set_intent(f"acquire_{preferred_weapon}")
    return False


def _resolve_move_target(context: TaskExecutionContext) -> dict[str, Any] | None:
    target_kind = str(context.task.get("target_kind") or "").strip().lower()
    target_id = str(context.task.get("target_id") or context.metadata.get("target_human_id") or "").strip()
    if target_kind == "human" and target_id:
        return context.bridge.resolve_human(target_id)
    if target_kind == "entity" and target_id:
        return context.bridge.resolve_entity(target_id)
    place_tag = str(context.metadata.get("place_tag") or target_id or "home").strip() or "home"
    return context.bridge.resolve_place(place_tag, context.px, context.py, radius=260.0)


def _target_distance(context: TaskExecutionContext, target: dict[str, Any]) -> float:
    if "distance" in target:
        return float(target.get("distance", 0.0))
    return math.hypot(float(target.get("x", context.px)) - context.px, float(target.get("y", context.py)) - context.py)


def _handle_move_to_ambush_point(context: TaskExecutionContext) -> bool:
    target = _resolve_move_target(context)
    if target is None:
        context.task_state["blocked_reason"] = "strategic_target_missing"
        return False
    arrival_radius = max(float(context.metadata.get("arrival_radius", 10.0)), 2.0)
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    if _target_distance(context, target) > arrival_radius:
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 0.95):
            context.task_state["last_task_action"] = "moving_to_ambush_point"
            context.set_intent("move_to_ambush_point")
            return True
        return False
    context.task_state["ambush_anchor"] = {"x": round(tx, 2), "y": round(ty, 2)}
    context.bridge.on_action(last_action="reached hidden position", intent="move_to_ambush_point", mood_delta=-0.01, review=False)
    return _advance_and_complete(context, "position_reached")


def _handle_wait_in_hiding(context: TaskExecutionContext) -> bool:
    hp_threshold = context.metadata.get("hp_threshold")
    if hp_threshold is not None and float(context.resident.get("snapshot", {}).get("hp", 100.0)) >= float(hp_threshold):
        return _advance_and_complete(context, "recovered")
    target_tick = context.metadata.get("target_tick")
    if target_tick is not None:
        if int(context.tick) >= int(target_tick):
            return _advance_and_complete(context, "wait_complete")
        context.set_intent("wait_in_hiding")
        return False
    hide_until = int(context.task_state.get("hide_until_tick", 0))
    if hide_until <= 0:
        hold_ticks = max(int(context.metadata.get("hold_ticks", 8)), 1)
        context.task_state["hide_until_tick"] = int(context.tick) + hold_ticks
        context.set_intent("wait_in_hiding")
        return True
    if int(context.tick) >= hide_until:
        context.task_state.pop("hide_until_tick", None)
        return _advance_and_complete(context, "wait_complete")
    context.set_intent("wait_in_hiding")
    return False


def _handle_recruit_ally(context: TaskExecutionContext) -> bool:
    target_id = str(context.task.get("target_id") or context.metadata.get("target_human_id") or "").strip()
    if not target_id:
        return _advance_and_complete(context, "no_target")
    target = context.bridge.resolve_human(target_id)
    if target is None:
        context.task_state["blocked_reason"] = "ally_missing"
        return False
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    if _target_distance(context, target) > 8.0:
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 0.95):
            context.task_state["last_task_action"] = "approaching_ally"
            context.set_intent("recruit_ally")
            return True
        return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("recruit_ally")
        return False
    context.bridge.on_action(last_action=f"recruited {target_id}", intent="recruit_ally", mood_delta=0.06, review=False)
    return _advance_and_complete(context, "ally_recruited")


def _handle_steal_from_container(context: TaskExecutionContext) -> bool:
    item_kind = str(context.metadata.get("item_kind", "coin")).strip() or "coin"
    quantity = max(int(context.metadata.get("quantity", 1)), 1)
    target_container_id = str(context.task.get("target_id") or "").strip()
    storage = context.bridge.nearest_storage(context.px, context.py, radius=200.0)
    if storage is None:
        context.task_state["blocked_reason"] = "no_storage_target"
        return False
    tx = float(storage.get("x", context.px))
    ty = float(storage.get("y", context.py))
    if float(storage.get("distance", 9999.0)) > context.bridge.gather_radius:
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step):
            context.task_state["last_task_action"] = "moving_to_theft_target"
            context.set_intent("steal_from_container")
            return True
        return False
    if not target_container_id:
        target_container_id = str(storage.get("container_id", "")).strip()
    result = context.bridge.try_steal_from_container(target_container_id, item_kind, quantity)
    if not bool(result.get("ok", False)):
        context.task_state["blocked_reason"] = str(result.get("reason", "steal_blocked"))
        context.set_intent("steal_from_container")
        return False
    context.bridge.on_action(last_action=f"stole {item_kind}", intent="steal_from_container", mood_delta=0.02, review=False)
    return _advance_and_complete(context, "stole_goods")


def _handle_escape_area(context: TaskExecutionContext) -> bool:
    target = _resolve_move_target(context)
    distance = _target_distance(context, target) if isinstance(target, dict) else 0.0
    escape_radius = max(float(context.metadata.get("escape_radius", 26.0)), 12.0)
    if isinstance(target, dict) and distance < escape_radius:
        tx = float(target.get("x", context.px))
        ty = float(target.get("y", context.py))
        dx = context.px - tx
        dy = context.py - ty
        norm = max(math.hypot(dx, dy), 1.0)
        flee_x = max(0.0, min(context.bridge.map_width or context.px, context.px + (dx / norm) * escape_radius))
        flee_y = max(0.0, min(context.bridge.map_height or context.py, context.py + (dy / norm) * escape_radius))
        if context.bridge.move_toward(flee_x, flee_y, magnitude=context.bridge.move_step * 1.2):
            context.task_state["last_task_action"] = "escaping_area"
            context.set_intent("escape_area")
            return True
        return False
    safe_target = context.bridge.resolve_safe(context.px, context.py, radius=260.0) or context.bridge.resolve_place(
        "home",
        context.px,
        context.py,
        radius=260.0,
    )
    if isinstance(safe_target, dict):
        if _target_distance(context, safe_target) > context.bridge.gather_radius:
            if context.bridge.move_toward(float(safe_target.get("x", context.px)), float(safe_target.get("y", context.py)), magnitude=context.bridge.move_step * 1.05):
                context.task_state["last_task_action"] = "moving_to_safe_area"
                context.set_intent("escape_area")
                return True
            return False
    context.bridge.on_action(last_action="escaped danger zone", intent="escape_area", threat_delta=-8.0, review=False)
    return _advance_and_complete(context, "escaped")


def _handle_scout_area(context: TaskExecutionContext) -> bool:
    place_tag = str(context.metadata.get("place_tag") or context.task.get("target_id") or "wild").strip() or "wild"
    target = context.bridge.resolve_place(place_tag, context.px, context.py, radius=260.0)
    if target is not None and _target_distance(context, target) > context.bridge.gather_radius:
        if context.bridge.move_toward(float(target.get("x", context.px)), float(target.get("y", context.py)), magnitude=context.bridge.move_step):
            context.task_state["last_task_action"] = f"scouting_{place_tag}"
            context.set_intent("scout_area")
            return True
        return False
    hold_until = int(context.task_state.get("scout_until_tick", 0))
    if hold_until <= 0:
        context.task_state["scout_until_tick"] = int(context.tick) + max(int(context.metadata.get("hold_ticks", 6)), 3)
        context.set_intent("scout_area")
        return True
    if int(context.tick) >= hold_until:
        context.task_state.pop("scout_until_tick", None)
        context.bridge.on_action(last_action=f"scouted {place_tag}", intent="scout_area", mood_delta=0.02, review=False)
        return _advance_and_complete(context, "scouted")
    context.set_intent("scout_area")
    return True


def _handle_protect_home(context: TaskExecutionContext) -> bool:
    target = context.bridge.resolve_place("home", context.px, context.py, radius=260.0)
    if target is not None and _target_distance(context, target) > context.bridge.gather_radius:
        if context.bridge.move_toward(float(target.get("x", context.px)), float(target.get("y", context.py)), magnitude=context.bridge.move_step):
            context.task_state["last_task_action"] = "moving_to_home_defense"
            context.set_intent("protect_home")
            return True
        return False
    context.bridge.on_action(last_action="took up home defense", intent="protect_home", mood_delta=0.03, review=False)
    return _advance_and_complete(context, "protecting_home")


def _handle_gather_food_buffer(context: TaskExecutionContext) -> bool:
    desired_quantity = max(int(context.metadata.get("desired_quantity", 2)), 1)
    existing_quantity = 0
    for item in list(context.personal_inventory.get("items", [])):
        if str(item.get("kind", "")) == "rations":
            existing_quantity += max(int(item.get("quantity", 0)), 0)
    if existing_quantity >= desired_quantity:
        return _advance_and_complete(context, "food_buffer_ready")
    resource = context.bridge.resolve_resource("food", context.px, context.py, radius=220.0)
    if resource is None:
        context.task_state["blocked_reason"] = "food_source_missing"
        context.set_intent("gather_food_buffer")
        return False
    if _target_distance(context, resource) > context.bridge.gather_radius:
        if context.bridge.move_toward(float(resource.get("x", context.px)), float(resource.get("y", context.py)), magnitude=context.bridge.move_step):
            context.task_state["last_task_action"] = "moving_to_food_source"
            context.set_intent("gather_food_buffer")
            return True
        return False
    consumed = context.bridge.consume_resource("food", int(resource.get("slot", -1)), 1, uid=resource.get("uid"))
    if consumed <= 0:
        context.task_state["blocked_reason"] = "food_source_empty"
        context.set_intent("gather_food_buffer")
        return False
    inventory_add_item(context.personal_inventory, "rations", consumed, metadata={"source": "strategic_food_buffer"})
    context.bridge.on_action(last_action="gathered ration buffer", intent="gather_food_buffer", mood_delta=0.04, stamina_delta=-0.6, review=False)
    if existing_quantity + consumed >= desired_quantity:
        return _advance_and_complete(context, "food_buffer_ready")
    context.set_intent("gather_food_buffer")
    return True


def execute_task_step(context: TaskExecutionContext) -> bool:
    if not can_handle_task(context.task_kind):
        return False
    if context.task_kind == "acquire_weapon":
        return _handle_acquire_weapon(context)
    if context.task_kind == "move_to_ambush_point":
        return _handle_move_to_ambush_point(context)
    if context.task_kind == "wait_in_hiding":
        return _handle_wait_in_hiding(context)
    if context.task_kind == "recruit_ally":
        return _handle_recruit_ally(context)
    if context.task_kind == "steal_from_container":
        return _handle_steal_from_container(context)
    if context.task_kind == "escape_area":
        return _handle_escape_area(context)
    if context.task_kind == "scout_area":
        return _handle_scout_area(context)
    if context.task_kind == "protect_home":
        return _handle_protect_home(context)
    if context.task_kind == "gather_food_buffer":
        return _handle_gather_food_buffer(context)
    return False


__all__ = [
    "STRATEGIC_TASK_KINDS",
    "can_handle_task",
    "execute_task_step",
    "strategic_task_specs",
]
