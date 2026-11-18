from __future__ import annotations

"""Occupation-facing task helpers and live task-family executor."""

import math
from typing import Any

try:
    from systems.occupation import occupation_preferred_place_tags
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.occupation import occupation_preferred_place_tags

from ...inventory import (
    add_item as inventory_add_item,
    equip_main_hand_item,
    has_item,
    remove_item as inventory_remove_item,
    total_quantity,
    transfer_item as inventory_transfer_item,
)
from ..contracts import TaskExecutionContext
from ..ops import complete_current_task


OCCUPATION_TASK_KINDS = {
    "withdraw_item",
    "gather_material",
    "craft_item",
    "equip_item",
    "move_to_place",
    "chop_wood",
    "fish_work",
    "farm_work",
    "gather_work",
    "build_work",
    "hunt_work",
    "heal_work",
    "trade_run",
    "patrol_area",
    "store_item",
}


def can_handle_task(task_kind: str) -> bool:
    return str(task_kind).strip() in OCCUPATION_TASK_KINDS


def _fallback_place_tag_for_routine(resident: dict[str, Any], routine_kind: str) -> str:
    occupation_places = occupation_preferred_place_tags(resident)
    if routine_kind in {"sleep", "stay_home", "return_home", "rest"}:
        return "home"
    if routine_kind == "visit_water":
        return "water"
    if routine_kind in {"guard", "patrol"}:
        return "settlement"
    if occupation_places:
        return str(occupation_places[0])
    if routine_kind in {"wander_local", "gather"}:
        return "forest"
    return "settlement"


def routine_task_specs(resident: dict[str, Any]) -> list[dict[str, Any]]:
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    if not routine_kind or routine_kind == "socialize":
        return []
    if routine_kind in {"guard", "patrol"}:
        return [
            {
                "task_kind": "patrol_area",
                "priority": 0.44,
                "source": "routine",
                "summary": "follow routine patrol",
                "target_kind": "place",
                "target_id": "settlement",
                "metadata": {
                    "routine_kind": routine_kind,
                    "place_tag": "settlement",
                    "patrol_radius": 16.0,
                },
            }
        ]
    place_tag = _fallback_place_tag_for_routine(resident, routine_kind)
    return [
        {
            "task_kind": "move_to_place",
            "priority": 0.34,
            "source": "routine",
            "summary": f"follow routine {routine_kind}",
            "target_kind": "place",
            "target_id": place_tag,
            "metadata": {
                "routine_kind": routine_kind,
                "place_tag": place_tag,
            },
        }
    ]


def suggested_occupation_task_kind(resident: dict[str, Any]) -> str:
    occupation_kind = str(resident.get("occupation", {}).get("kind", "")).strip()
    routine_kind = str(resident.get("schedule_state", {}).get("current_routine", {}).get("kind", "")).strip()

    if occupation_kind == "fisherman":
        return "fish_work"
    if occupation_kind == "woodcutter":
        return "chop_wood"
    if occupation_kind == "farmer":
        return "farm_work"
    if occupation_kind == "guard":
        return "patrol_area"
    if occupation_kind == "builder":
        return "build_work"
    if occupation_kind == "gatherer":
        return "gather_work"
    if occupation_kind == "hunter":
        return "hunt_work"
    if occupation_kind == "healer":
        return "heal_work"
    if occupation_kind == "trader":
        return "trade_run"
    if routine_kind in {"socialize", "wander_local"}:
        return "socialize"
    if routine_kind in {"sleep", "stay_home"}:
        return "return_home"
    return "idle"


def baseline_task_candidates(resident: dict[str, Any], tick: int) -> list[dict[str, Any]]:
    task_kind = suggested_occupation_task_kind(resident)
    source = "occupation_schedule"
    summary = f"{task_kind} baseline"
    return [
        {
            "task_kind": task_kind,
            "priority": 0.42,
            "source": source,
            "summary": summary,
            "created_tick": int(tick),
            "metadata": {
                "occupation_kind": str(resident.get("occupation", {}).get("kind", "")),
                "routine_kind": str(resident.get("schedule_state", {}).get("current_routine", {}).get("kind", "")),
            },
        }
    ]


def baseline_provisioning_task_specs(resident: dict[str, Any]) -> list[dict[str, Any]]:
    crafting_state = dict(resident.get("crafting_state", {}))
    active_need = dict(crafting_state.get("active_need") or {})
    if not active_need:
        return []

    tool_kind = str(active_need.get("tool_kind", "")).strip()
    status = str(active_need.get("status", "")).strip()
    workflow_meta = {
        "workflow": "occupation_provision",
        "occupation_kind": str(resident.get("occupation", {}).get("kind", "")),
        "tool_kind": tool_kind,
    }

    if status == "withdraw":
        return [
            {
                "task_kind": "withdraw_item",
                "priority": 0.78,
                "source": "occupation_baseline",
                "summary": f"withdraw {tool_kind}",
                "target_kind": "item",
                "target_id": tool_kind,
                "metadata": dict(workflow_meta),
            },
        ]

    if status == "craft":
        return [
            {
                "task_kind": "craft_item",
                "priority": 0.74,
                "source": "occupation_baseline",
                "summary": f"craft {tool_kind}",
                "target_kind": "item",
                "target_id": tool_kind,
                "metadata": dict(
                    workflow_meta,
                    recipe_id=str(active_need.get("recipe_id", "")),
                ),
            },
        ]

    if status == "gather_then_craft":
        missing = list(active_need.get("missing_ingredients", []))
        first_missing = dict(missing[0]) if missing else {}
        ingredient_kind = str(first_missing.get("item_kind", "")).strip()
        required_quantity = max(int(first_missing.get("required_quantity", 1)), 1)
        return [
            {
                "task_kind": "gather_material",
                "priority": 0.76,
                "source": "occupation_baseline",
                "summary": f"gather {ingredient_kind} for {tool_kind}",
                "target_kind": "item",
                "target_id": ingredient_kind,
                "requested_quantity": required_quantity,
                "metadata": dict(
                    workflow_meta,
                    ingredient_kind=ingredient_kind,
                    recipe_id=str(active_need.get("recipe_id", "")),
                ),
            },
            {
                "task_kind": "craft_item",
                "priority": 0.72,
                "source": "occupation_baseline",
                "summary": f"craft {tool_kind}",
                "target_kind": "item",
                "target_id": tool_kind,
                "metadata": dict(
                    workflow_meta,
                    recipe_id=str(active_need.get("recipe_id", "")),
                ),
            },
        ]

    if status == "acquire_external":
        return [
            {
                "task_kind": "ensure_required_tool",
                "priority": 0.6,
                "source": "occupation_baseline",
                "summary": f"acquire {tool_kind}",
                "target_kind": "item",
                "target_id": tool_kind,
                "metadata": dict(workflow_meta, mode="external_only"),
            }
        ]

    return []


def _cargo_quantity(resident: dict[str, Any], item_kind: str) -> int:
    carry_manifest = dict((resident.get("task_state", {}) or {}).get("carry_manifest", {}))
    if str(item_kind) in carry_manifest:
        return max(int(carry_manifest.get(str(item_kind), 0)), 0)
    cargo_cache = dict((resident.get("task_state", {}) or {}).get("cargo_cache", {}))
    return max(int(cargo_cache.get(str(item_kind), 0)), 0)


GATHERER_OUTPUT_SEQUENCE = ("herb_bundle", "fiber_bundle", "rations")


def _gatherer_output_kind(resident: dict[str, Any]) -> str:
    task_state = resident.setdefault("task_state", {})
    index = max(int(task_state.get("gatherer_output_index", 0)), 0)
    return str(GATHERER_OUTPUT_SEQUENCE[index % len(GATHERER_OUTPUT_SEQUENCE)])


def _occupation_harvest_task_specs(
    *,
    occupation_kind: str,
    workflow: str,
    move_summary: str,
    move_place_tag: str,
    work_kind: str,
    work_summary: str,
    output_kind: str,
    required_item: str,
    carry_quantity: int,
) -> list[dict[str, Any]]:
    requested_quantity = max(1, int(carry_quantity))
    workflow_meta = {
        "workflow": str(workflow),
        "occupation_kind": str(occupation_kind),
    }
    return [
        {
            "task_kind": "move_to_place",
            "priority": 0.54,
            "source": "occupation_work",
            "summary": str(move_summary),
            "target_kind": "place",
            "target_id": str(move_place_tag),
            "metadata": dict(workflow_meta, place_tag=str(move_place_tag)),
        },
        {
            "task_kind": str(work_kind),
            "priority": 0.53,
            "source": "occupation_work",
            "summary": str(work_summary),
            "target_kind": "item",
            "target_id": str(output_kind),
            "requested_quantity": requested_quantity,
            "required_item": str(required_item),
            "metadata": dict(workflow_meta, place_tag=str(move_place_tag)),
        },
        {
            "task_kind": "store_item",
            "priority": 0.52,
            "source": "occupation_work",
            "summary": f"store {output_kind}",
            "target_kind": "item",
            "target_id": str(output_kind),
            "requested_quantity": requested_quantity,
            "metadata": dict(workflow_meta),
        },
    ]


def woodcutter_work_task_specs(resident: dict[str, Any], *, carry_quantity: int = 2) -> list[dict[str, Any]]:
    carried_wood = _cargo_quantity(resident, "wood_bundle")
    workflow_meta = {
        "workflow": "woodcutter_work",
        "occupation_kind": "woodcutter",
    }
    has_house_storage = bool((resident.get("construction_state", {}) or {}).get("has_house_storage", False))

    if carried_wood > 0:
        if not has_house_storage:
            return []
        return [
            {
                "task_kind": "store_item",
                "priority": 0.58,
                "source": "occupation_work",
                "summary": "store gathered wood",
                "target_kind": "item",
                "target_id": "wood_bundle",
                "requested_quantity": carried_wood,
                "metadata": dict(workflow_meta),
            }
        ]

    return _occupation_harvest_task_specs(
        occupation_kind="woodcutter",
        workflow="woodcutter_work",
        move_summary="move to nearby forest",
        move_place_tag="forest",
        work_kind="chop_wood",
        work_summary="chop wood",
        output_kind="wood_bundle",
        required_item="axe",
        carry_quantity=carry_quantity,
    )


def fisherman_work_task_specs(resident: dict[str, Any], *, carry_quantity: int = 2) -> list[dict[str, Any]]:
    carried_fish = _cargo_quantity(resident, "fish_catch")
    has_house_storage = bool((resident.get("construction_state", {}) or {}).get("has_house_storage", False))
    if carried_fish > 0:
        if not has_house_storage:
            return []
        return [
            {
                "task_kind": "store_item",
                "priority": 0.58,
                "source": "occupation_work",
                "summary": "store fresh catch",
                "target_kind": "item",
                "target_id": "fish_catch",
                "requested_quantity": carried_fish,
                "metadata": {
                    "workflow": "fisherman_work",
                    "occupation_kind": "fisherman",
                },
            }
        ]

    return _occupation_harvest_task_specs(
        occupation_kind="fisherman",
        workflow="fisherman_work",
        move_summary="move to nearby shore",
        move_place_tag="water",
        work_kind="fish_work",
        work_summary="fish the nearby water",
        output_kind="fish_catch",
        required_item="fishing_rod",
        carry_quantity=carry_quantity,
    )


def farmer_work_task_specs(resident: dict[str, Any], *, carry_quantity: int = 2) -> list[dict[str, Any]]:
    carried_crop = _cargo_quantity(resident, "crop_bundle")
    has_house_storage = bool((resident.get("construction_state", {}) or {}).get("has_house_storage", False))
    if carried_crop > 0:
        if not has_house_storage:
            return []
        return [
            {
                "task_kind": "store_item",
                "priority": 0.58,
                "source": "occupation_work",
                "summary": "store gathered crops",
                "target_kind": "item",
                "target_id": "crop_bundle",
                "requested_quantity": carried_crop,
                "metadata": {
                    "workflow": "farmer_work",
                    "occupation_kind": "farmer",
                },
            }
        ]

    return _occupation_harvest_task_specs(
        occupation_kind="farmer",
        workflow="farmer_work",
        move_summary="move to nearby field",
        move_place_tag="farm",
        work_kind="farm_work",
        work_summary="work the nearby field",
        output_kind="crop_bundle",
        required_item="hoe",
        carry_quantity=carry_quantity,
    )


def guard_work_task_specs(resident: dict[str, Any], *, patrol_radius: float = 18.0) -> list[dict[str, Any]]:
    return [
        {
            "task_kind": "patrol_area",
            "priority": 0.5,
            "source": "occupation_work",
            "summary": "patrol the nearby settlement",
            "target_kind": "place",
            "target_id": "settlement",
            "metadata": {
                "workflow": "guard_work",
                "occupation_kind": "guard",
                "patrol_radius": max(float(patrol_radius), 8.0),
                "place_tag": "settlement",
            },
        }
    ]


def builder_work_task_specs(resident: dict[str, Any], *, carry_quantity: int = 2) -> list[dict[str, Any]]:
    carried_goods = _cargo_quantity(resident, "plank_bundle")
    has_house_storage = bool((resident.get("construction_state", {}) or {}).get("has_house_storage", False))
    if carried_goods > 0:
        if not has_house_storage:
            return []
        return [
            {
                "task_kind": "store_item",
                "priority": 0.58,
                "source": "occupation_work",
                "summary": "store worked planks",
                "target_kind": "item",
                "target_id": "plank_bundle",
                "requested_quantity": carried_goods,
                "metadata": {
                    "workflow": "builder_work",
                    "occupation_kind": "builder",
                },
            }
        ]
    return _occupation_harvest_task_specs(
        occupation_kind="builder",
        workflow="builder_work",
        move_summary="move to nearby worksite",
        move_place_tag="worksite",
        work_kind="build_work",
        work_summary="shape building materials",
        output_kind="plank_bundle",
        required_item="hammer",
        carry_quantity=carry_quantity,
    )


def gatherer_work_task_specs(resident: dict[str, Any], *, carry_quantity: int = 2) -> list[dict[str, Any]]:
    has_house_storage = bool((resident.get("construction_state", {}) or {}).get("has_house_storage", False))
    for carried_kind in GATHERER_OUTPUT_SEQUENCE:
        carried_goods = _cargo_quantity(resident, carried_kind)
        if carried_goods <= 0:
            continue
        if not has_house_storage:
            return []
        return [
            {
                "task_kind": "store_item",
                "priority": 0.58,
                "source": "occupation_work",
                "summary": f"store gathered {carried_kind.replace('_', ' ')}",
                "target_kind": "item",
                "target_id": carried_kind,
                "requested_quantity": carried_goods,
                "metadata": {
                    "workflow": "gatherer_work",
                    "occupation_kind": "gatherer",
                    "output_kind": carried_kind,
                },
            }
        ]
    output_kind = _gatherer_output_kind(resident)
    work_summary = {
        "herb_bundle": "gather herbs in the nearby wilds",
        "fiber_bundle": "gather fibers in the nearby wilds",
        "rations": "forage for edible supplies",
    }.get(output_kind, "gather herbs and fibers")
    return _occupation_harvest_task_specs(
        occupation_kind="gatherer",
        workflow="gatherer_work",
        move_summary="move into nearby wild growth",
        move_place_tag="wild",
        work_kind="gather_work",
        work_summary=work_summary,
        output_kind=output_kind,
        required_item="basket",
        carry_quantity=carry_quantity,
    )


def hunter_work_task_specs(resident: dict[str, Any], *, carry_quantity: int = 2) -> list[dict[str, Any]]:
    carried_goods = _cargo_quantity(resident, "rations")
    has_house_storage = bool((resident.get("construction_state", {}) or {}).get("has_house_storage", False))
    if carried_goods > 0:
        if not has_house_storage:
            return []
        return [
            {
                "task_kind": "store_item",
                "priority": 0.58,
                "source": "occupation_work",
                "summary": "store hunted rations",
                "target_kind": "item",
                "target_id": "rations",
                "requested_quantity": carried_goods,
                "metadata": {
                    "workflow": "hunter_work",
                    "occupation_kind": "hunter",
                },
            }
        ]
    return _occupation_harvest_task_specs(
        occupation_kind="hunter",
        workflow="hunter_work",
        move_summary="move along the wild trail",
        move_place_tag="wild",
        work_kind="hunt_work",
        work_summary="hunt in the nearby wilds",
        output_kind="rations",
        required_item="spear",
        carry_quantity=carry_quantity,
    )


def healer_work_task_specs(resident: dict[str, Any], *, target_human_id: str, target_name: str = "") -> list[dict[str, Any]]:
    if not str(target_human_id or "").strip():
        return []
    display_name = str(target_name or target_human_id)
    return [
        {
            "task_kind": "heal_work",
            "priority": 0.49,
            "source": "occupation_work",
            "summary": f"treat {display_name}",
            "target_kind": "human",
            "target_id": str(target_human_id),
            "metadata": {
                "workflow": "healer_work",
                "occupation_kind": "healer",
                "item_kind": "bandage",
                "target_human_id": str(target_human_id),
                "target_name": display_name,
            },
        }
    ]


def trader_work_task_specs(resident: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "task_kind": "trade_run",
            "priority": 0.47,
            "source": "occupation_work",
            "summary": "trade nearby goods",
            "target_kind": "place",
            "target_id": "market",
            "metadata": {
                "workflow": "trader_work",
                "occupation_kind": "trader",
                "place_tag": "market",
            },
        }
    ]


def should_activate_woodcutter_work(resident: dict[str, Any], *, has_required_tool: bool) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "woodcutter":
        return False
    if _cargo_quantity(resident, "wood_bundle") > 0:
        return True
    if not bool(has_required_tool):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"gather", "wander_local", "work_site"}


def should_activate_fisherman_work(resident: dict[str, Any], *, has_required_tool: bool) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "fisherman":
        return False
    if _cargo_quantity(resident, "fish_catch") > 0:
        return True
    if not bool(has_required_tool):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"visit_water", "work_site", "gather"}


def should_activate_farmer_work(resident: dict[str, Any], *, has_required_tool: bool) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "farmer":
        return False
    if _cargo_quantity(resident, "crop_bundle") > 0:
        return True
    if not bool(has_required_tool):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"work_site", "gather", "visit_water"}


def should_activate_guard_work(resident: dict[str, Any], *, has_required_tool: bool) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "guard":
        return False
    if not bool(has_required_tool):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"guard", "patrol", "visit_water", "socialize"}


def should_activate_builder_work(resident: dict[str, Any], *, has_required_tool: bool) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "builder":
        return False
    if _cargo_quantity(resident, "plank_bundle") > 0:
        return True
    if not bool(has_required_tool):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"work_site", "gather", "wander_local"}


def should_activate_gatherer_work(resident: dict[str, Any], *, has_required_tool: bool) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "gatherer":
        return False
    if any(_cargo_quantity(resident, item_kind) > 0 for item_kind in GATHERER_OUTPUT_SEQUENCE):
        return True
    if not bool(has_required_tool):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"gather", "wander_local", "visit_water"}


def should_activate_hunter_work(resident: dict[str, Any], *, has_required_tool: bool) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "hunter":
        return False
    if _cargo_quantity(resident, "rations") > 0:
        return True
    if not bool(has_required_tool):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"wander_local", "gather", "patrol"}


def should_activate_healer_work(resident: dict[str, Any], *, has_required_tool: bool, help_target: dict[str, Any] | None = None) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "healer":
        return False
    if not bool(has_required_tool):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    if not isinstance(help_target, dict):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"work_site", "stay_home", "socialize", "return_home"}


def should_activate_trader_work(resident: dict[str, Any], *, has_required_tool: bool, has_coin: bool) -> bool:
    if str(resident.get("occupation", {}).get("kind", "")).strip() != "trader":
        return False
    if not bool(has_required_tool) or not bool(has_coin):
        return False
    if dict(resident.get("crafting_state", {})).get("active_need"):
        return False
    routine_kind = str((resident.get("schedule_state", {}) or {}).get("current_routine", {}).get("kind", "")).strip()
    return routine_kind in {"socialize", "work_site", "wander_local", "return_home"}


def _equip_first_matching_tool(record: dict[str, Any], item_kind: str) -> bool:
    for item in list(record.get("items", [])):
        if str(item.get("kind", "")) != str(item_kind):
            continue
        if int(item.get("quantity", 0)) <= 0:
            continue
        if equip_main_hand_item(record, str(item.get("id", ""))) is not None:
            return True
    return False


def _handle_withdraw_item(context: TaskExecutionContext) -> bool:
    tool_kind = str(context.task.get("target_id") or context.metadata.get("tool_kind") or "").strip()
    if not tool_kind:
        return False
    if has_item(context.personal_inventory, tool_kind, 1):
        _equip_first_matching_tool(context.personal_inventory, tool_kind)
        context.task_state["last_task_action"] = f"ready {tool_kind}"
        context.set_intent(f"equip_{tool_kind}")
        complete_current_task(context.resident, context.tick, reason="already_owned")
        return True
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent(f"withdraw_{tool_kind}")
        return False
    active_need = dict(context.crafting_state.get("active_need") or {})
    if context.bridge.try_withdraw_tool(tool_kind, active_need or {"tool_kind": tool_kind}):
        context.bridge.on_action(
            last_action=f"withdrew {tool_kind}",
            intent=f"withdraw_{tool_kind}",
            mood_delta=0.2,
        )
        complete_current_task(context.resident, context.tick, reason="withdrawn")
        return True
    context.task_state["blocked_reason"] = f"withdraw_wait:{tool_kind}"
    context.set_intent(f"withdraw_{tool_kind}")
    return False


def _handle_gather_material(context: TaskExecutionContext) -> bool:
    ingredient_kind = str(context.task.get("target_id") or context.metadata.get("ingredient_kind") or "").strip()
    required_quantity = max(int(context.task.get("requested_quantity") or 1), 1)
    if context.bridge.ingredient_quantity(ingredient_kind, {}) >= required_quantity:
        context.task_state["last_task_action"] = f"ready {ingredient_kind}"
        complete_current_task(context.resident, context.tick, reason="ingredients_ready")
        return True
    changed = context.bridge.progress_to_item(ingredient_kind, required_quantity)
    if context.bridge.ingredient_quantity(ingredient_kind, {}) >= required_quantity:
        complete_current_task(context.resident, context.tick, reason="ingredients_ready")
        return True
    context.task_state["blocked_reason"] = "" if changed else f"gather_wait:{ingredient_kind}"
    context.set_intent(f"gather_{ingredient_kind}")
    return changed


def _handle_craft_item(context: TaskExecutionContext) -> bool:
    tool_kind = str(context.task.get("target_id") or context.metadata.get("tool_kind") or "").strip()
    if not tool_kind:
        return False
    if has_item(context.personal_inventory, tool_kind, 1):
        context.task_state["last_task_action"] = f"ready {tool_kind}"
        complete_current_task(context.resident, context.tick, reason="already_crafted")
        return True
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent(f"craft_{tool_kind}")
        return False
    active_need = dict(context.crafting_state.get("active_need") or {})
    if not active_need:
        active_need = {
            "tool_kind": tool_kind,
            "recipe_id": str(context.metadata.get("recipe_id", "")),
        }
    if context.bridge.try_craft_tool(tool_kind, active_need):
        context.bridge.on_action(
            last_action=f"crafted {tool_kind}",
            intent=f"craft_{tool_kind}",
            mood_delta=0.2,
            stamina_delta=-2.0,
        )
        complete_current_task(context.resident, context.tick, reason="crafted")
        return True
    context.task_state["blocked_reason"] = f"craft_wait:{tool_kind}"
    context.set_intent(f"craft_{tool_kind}")
    return False


def _handle_equip_item(context: TaskExecutionContext) -> bool:
    tool_kind = str(context.task.get("target_id") or context.metadata.get("tool_kind") or "").strip()
    if not tool_kind:
        return False
    if _equip_first_matching_tool(context.personal_inventory, tool_kind):
        context.task_state["last_task_action"] = f"equipped {tool_kind}"
        context.set_intent(f"use_{tool_kind}")
        complete_current_task(context.resident, context.tick, reason="equipped")
        return True
    if has_item(context.personal_inventory, tool_kind, 1):
        complete_current_task(context.resident, context.tick, reason="already_equipped")
        return True
    context.task_state["blocked_reason"] = f"equip_wait:{tool_kind}"
    context.set_intent(f"equip_{tool_kind}")
    return False


POINT_ARRIVE_RADIUS = 2.0      # an explicit point is reached when the resident stands this close (the place radius, gather_radius, is far too coarse)


def _point_target(task: dict):
    """``(x, y)`` of a task whose target is an explicit point (``target_kind == "point"`` with a numeric ``target_place`` x/y), else None."""
    if str(task.get("target_kind", "")) != "point":
        return None
    place = task.get("target_place") or {}
    try:
        return float(place["x"]), float(place["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _handle_move_to_place(context: TaskExecutionContext) -> bool:
    point = _point_target(context.task)
    if point is not None:       # an explicit point (explore_toward): walk there, finish on arrival
        tx, ty = point
        if math.hypot(tx - context.px, ty - context.py) > POINT_ARRIVE_RADIUS:
            if context.bridge.move_toward(tx, ty):
                context.task_state["last_task_action"] = "moving_to_point"
                context.set_intent("move_point")
                return True
            return False
        context.task_state["last_task_action"] = "arrived_at_point"
        complete_current_task(context.resident, context.tick, reason="arrived")
        return True
    place_tag = str(context.metadata.get("place_tag") or context.task.get("target_id") or "").strip()
    target = context.bridge.resolve_place(place_tag, context.px, context.py, radius=240.0)
    if target is None:
        roam_scale = max(context.bridge.gather_radius * 1.8, 18.0)
        angle = (float(context.tick % 360) / 17.0) + float(len(place_tag or "place"))
        tx = max(0.0, min(float(context.bridge.map_width or context.px), context.px + math.cos(angle) * roam_scale))
        ty = max(0.0, min(float(context.bridge.map_height or context.py), context.py + math.sin(angle) * roam_scale))
        if context.bridge.move_toward(tx, ty, magnitude=context.bridge.move_step * 0.7):
            context.task_state["last_task_action"] = f"roaming_for_{place_tag or 'place'}"
            context.set_intent(f"wander_{place_tag or 'place'}")
            return True
        context.task_state["blocked_reason"] = f"place_not_found:{place_tag or 'unknown'}"
        context.set_intent(f"search_{place_tag or 'place'}")
        return False
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    distance = math.hypot(tx - context.px, ty - context.py)
    if distance > context.bridge.gather_radius:
        if context.bridge.move_toward(tx, ty):
            context.task_state["last_task_action"] = f"moving_to_{place_tag or 'place'}"
            context.set_intent(f"move_{place_tag or 'place'}")
            return True
        return False
    context.task_state["last_task_action"] = f"arrived_at_{place_tag or 'place'}"
    complete_current_task(context.resident, context.tick, reason="arrived")
    return True


def _consume_accessible_item(context: TaskExecutionContext, item_kind: str, quantity: int) -> bool:
    remaining = max(int(quantity), 0)
    if remaining <= 0:
        return True
    removed = inventory_remove_item(context.personal_inventory, item_kind=item_kind, quantity=remaining)
    remaining -= int(removed.get("removed", 0))
    for entry in context.accessible_records:
        if remaining <= 0:
            break
        record = entry.get("inventory")
        if not isinstance(record, dict):
            continue
        removed = inventory_remove_item(record, item_kind=item_kind, quantity=remaining)
        remaining -= int(removed.get("removed", 0))
    return remaining <= 0


def _handle_harvest_like_work(context: TaskExecutionContext) -> bool:
    if context.task_kind == "chop_wood":
        required_item = "axe"
        output_kind = "wood_bundle"
        place_tag = "forest"
        blocked_reason = "forest_not_found"
        search_intent = "search_forest"
        move_action = "moving_to_forest"
        move_intent = "move_forest"
        work_intent = "chop_wood"
        work_action = "chopped wood"
        mood_delta = 0.1
        stamina_delta = -1.5
    elif context.task_kind == "fish_work":
        required_item = "fishing_rod"
        output_kind = "fish_catch"
        place_tag = "water"
        blocked_reason = "water_not_found"
        search_intent = "search_water"
        move_action = "moving_to_water"
        move_intent = "move_water"
        work_intent = "fish_work"
        work_action = "caught fish"
        mood_delta = 0.12
        stamina_delta = -1.1
        required_materials: tuple[tuple[str, int], ...] = ()
    elif context.task_kind == "farm_work":
        required_item = "hoe"
        output_kind = "crop_bundle"
        place_tag = "farm"
        blocked_reason = "field_not_found"
        search_intent = "search_field"
        move_action = "moving_to_field"
        move_intent = "move_field"
        work_intent = "farm_work"
        work_action = "harvested crops"
        mood_delta = 0.1
        stamina_delta = -1.2
        required_materials = ()
    elif context.task_kind == "gather_work":
        required_item = "basket"
        output_kind = str(context.metadata.get("output_kind", "herb_bundle")).strip() or "herb_bundle"
        place_tag = "wild"
        blocked_reason = "wilds_not_found"
        search_intent = "search_wilds"
        move_action = "moving_to_gathering_ground"
        move_intent = "move_wild"
        work_intent = "gather_work"
        work_action = f"gathered {output_kind}"
        mood_delta = 0.08
        stamina_delta = -0.9
        required_materials = ()
    elif context.task_kind == "build_work":
        required_item = "hammer"
        output_kind = "plank_bundle"
        place_tag = "worksite"
        blocked_reason = "worksite_not_found"
        search_intent = "search_worksite"
        move_action = "moving_to_worksite"
        move_intent = "move_worksite"
        work_intent = "build_work"
        work_action = "worked building materials"
        mood_delta = 0.09
        stamina_delta = -1.1
        required_materials = (("wood_bundle", 1),)
    else:
        required_item = "spear"
        output_kind = "rations"
        place_tag = "wild"
        blocked_reason = "hunt_ground_not_found"
        search_intent = "search_hunt_ground"
        move_action = "moving_to_hunt_ground"
        move_intent = "move_wild"
        work_intent = "hunt_work"
        work_action = "hunted rations"
        mood_delta = 0.11
        stamina_delta = -1.4
        required_materials = ()

    if not has_item(context.personal_inventory, required_item, 1):
        context.task_state["blocked_reason"] = f"missing_{required_item}"
        context.set_intent(f"obtain_{required_item}")
        return False
    target_quantity = max(int(context.task.get("requested_quantity") or 1), 1)
    current_cargo = total_quantity(context.personal_inventory, output_kind)
    if current_cargo >= target_quantity:
        complete_current_task(context.resident, context.tick, reason="cargo_ready")
        return True
    target = context.bridge.resolve_place(place_tag, context.px, context.py, radius=240.0)
    if target is None:
        context.task_state["blocked_reason"] = blocked_reason
        context.set_intent(search_intent)
        return False
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    distance = math.hypot(tx - context.px, ty - context.py)
    if distance > context.bridge.gather_radius:
        if context.bridge.move_toward(tx, ty):
            context.task_state["last_task_action"] = move_action
            context.set_intent(move_intent)
            return True
        return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent(work_intent)
        return False
    for item_kind, quantity in required_materials:
        if context.bridge.ingredient_quantity(item_kind, {}) < quantity:
            progressed = context.bridge.progress_to_item(item_kind, quantity)
            context.task_state["blocked_reason"] = "" if progressed else f"missing_{item_kind}"
            context.set_intent(f"gather_{item_kind}")
            return progressed
    for item_kind, quantity in required_materials:
        if not _consume_accessible_item(context, item_kind, quantity):
            context.task_state["blocked_reason"] = f"consume_wait:{item_kind}"
            context.set_intent(work_intent)
            return False
    added = inventory_add_item(
        context.personal_inventory,
        output_kind,
        1,
        metadata={"source": str(context.metadata.get("workflow", "occupation_work"))},
    )
    if int(added.get("added", 0)) <= 0:
        context.task_state["blocked_reason"] = f"carry_full:{output_kind}"
        context.set_intent(f"store_{output_kind}" if context.accessible_records else f"carry_{output_kind}")
        complete_current_task(context.resident, context.tick, reason="carry_full")
        return True
    context.bridge.on_action(
        last_action=work_action,
        intent=work_intent,
        mood_delta=mood_delta,
        stamina_delta=stamina_delta,
        review=False,
    )
    if total_quantity(context.personal_inventory, output_kind) >= target_quantity:
        complete_current_task(context.resident, context.tick, reason="cargo_ready")
    return True


def _handle_heal_work(context: TaskExecutionContext) -> bool:
    target_id = str(context.task.get("target_id") or context.metadata.get("target_human_id") or "").strip()
    if not target_id:
        complete_current_task(context.resident, context.tick, reason="no_target")
        return True
    target = context.bridge.resolve_human(target_id)
    if target is None:
        context.task_state["blocked_reason"] = "heal_target_missing"
        return False
    tx = float(target.get("x", context.px))
    ty = float(target.get("y", context.py))
    distance = math.hypot(tx - context.px, ty - context.py)
    if distance > context.bridge.gather_radius * 0.5:
        if context.bridge.move_toward(tx, ty):
            context.task_state["last_task_action"] = "moving_to_patient"
            context.set_intent("heal_work")
            return True
        return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("heal_work")
        return False
    result = context.bridge.try_heal_target(target_id, item_kind=str(context.metadata.get("item_kind", "bandage")))
    if not bool(result.get("ok", False)):
        context.task_state["blocked_reason"] = str(result.get("reason", "heal_blocked"))
        context.set_intent("heal_work")
        return False
    context.bridge.on_action(
        last_action=f"healed {target_id}",
        intent="heal_work",
        mood_delta=0.16,
        stamina_delta=-0.7,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="healed")
    return True


def _handle_trade_run(context: TaskExecutionContext) -> bool:
    place_tag = str(context.metadata.get("place_tag", "market")).strip() or "market"
    trade_candidates = ("fish_catch", "crop_bundle", "wood_bundle", "herb_bundle", "fiber_bundle", "plank_bundle", "rope", "rations")
    carrying_trade_goods = any(has_item(context.personal_inventory, candidate, 1) for candidate in trade_candidates)
    if not carrying_trade_goods:
        for entry in context.accessible_records:
            record = entry.get("inventory")
            if not isinstance(record, dict):
                continue
            for candidate in trade_candidates:
                moved = inventory_transfer_item(
                    record,
                    context.personal_inventory,
                    item_kind=candidate,
                    quantity=1,
                )
                if int(moved.get("moved", 0)) <= 0:
                    continue
                context.task_state["last_task_action"] = f"withdrew_{candidate}_for_trade"
                context.set_intent("trade_run")
                return True
    target = context.bridge.resolve_place(place_tag, context.px, context.py, radius=260.0)
    if target is not None:
        tx = float(target.get("x", context.px))
        ty = float(target.get("y", context.py))
        if math.hypot(tx - context.px, ty - context.py) > context.bridge.gather_radius:
            if context.bridge.move_toward(tx, ty):
                context.task_state["last_task_action"] = "moving_to_market"
                context.set_intent("trade_run")
                return True
            return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("trade_run")
        return False
    traded_kind = ""
    for candidate in trade_candidates:
        removed = inventory_remove_item(context.personal_inventory, item_kind=candidate, quantity=1)
        if removed.get("ok"):
            traded_kind = candidate
            break
    coin_gain = 3 if traded_kind else 1
    inventory_add_item(context.personal_inventory, "coin", coin_gain, metadata={"source": "trade_run"})
    context.bridge.on_action(
        last_action=f"traded {traded_kind or 'presence'}",
        intent="trade_run",
        mood_delta=0.12,
        stamina_delta=-0.4,
        review=False,
    )
    complete_current_task(context.resident, context.tick, reason="traded")
    return True


def _handle_patrol_area(context: TaskExecutionContext) -> bool:
    if not has_item(context.personal_inventory, "spear", 1):
        context.task_state["blocked_reason"] = "missing_spear"
        context.set_intent("obtain_spear")
        return False
    anchor = context.bridge.resolve_place("settlement", context.px, context.py, radius=260.0)
    anchor_x = float(anchor.get("x", context.px)) if anchor else context.px
    anchor_y = float(anchor.get("y", context.py)) if anchor else context.py
    patrol_radius = max(float(context.metadata.get("patrol_radius", 18.0)), 8.0)
    patrol_phase = max(int(context.task_state.get("patrol_phase", 0)), 0)
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
            context.task_state["last_task_action"] = "patrolling_settlement"
            context.set_intent("patrol_area")
            return True
        return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent("patrol_area")
        return False
    context.task_state["patrol_phase"] = patrol_phase + 1
    context.bridge.on_action(
        last_action="patrolled settlement",
        intent="patrol_area",
        mood_delta=0.04,
        stamina_delta=-0.6,
        review=False,
    )
    return True


def _handle_store_item(context: TaskExecutionContext) -> bool:
    item_kind = str(context.task.get("target_id") or "").strip()
    carried_quantity = total_quantity(context.personal_inventory, item_kind)
    if carried_quantity <= 0:
        complete_current_task(context.resident, context.tick, reason="cargo_empty")
        return True
    storage_record = context.bridge.nearest_storage(context.px, context.py, radius=0.0)
    if storage_record is None:
        complete_current_task(context.resident, context.tick, reason="no_house_storage")
        return True
    distance = float(storage_record.get("distance", 10**9))
    if distance > context.bridge.gather_radius:
        tx = float(storage_record.get("x", context.px))
        ty = float(storage_record.get("y", context.py))
        if context.bridge.move_toward(tx, ty):
            context.task_state["last_task_action"] = f"moving_to_store_{item_kind}"
            context.set_intent(f"store_{item_kind}")
            return True
        return False
    if context.tick < int(context.crafting_state.get("next_action_tick", 0)):
        context.set_intent(f"store_{item_kind}")
        return False
    moved = inventory_transfer_item(
        context.personal_inventory,
        storage_record["inventory"],
        item_kind=item_kind,
        quantity=carried_quantity,
    )
    moved_count = int(moved.get("moved", 0))
    if moved_count <= 0:
        context.task_state["blocked_reason"] = f"storage_full:{item_kind}"
        context.set_intent(f"store_{item_kind}")
        return False
    context.bridge.on_action(
        last_action=f"stored {moved_count}x {item_kind}",
        intent=f"store_{item_kind}",
        mood_delta=0.08,
        stamina_delta=-0.4,
        review=False,
    )
    if total_quantity(context.personal_inventory, item_kind) <= 0:
        if str(context.metadata.get("workflow", "")).strip() == "gatherer_work":
            index = max(int(context.task_state.get("gatherer_output_index", 0)), 0)
            context.task_state["gatherer_output_index"] = index + 1
        complete_current_task(context.resident, context.tick, reason="stored")
    return True


def execute_task_step(context: TaskExecutionContext) -> bool:
    if not can_handle_task(context.task_kind):
        return False
    if context.task_kind == "withdraw_item":
        return _handle_withdraw_item(context)
    if context.task_kind == "gather_material":
        return _handle_gather_material(context)
    if context.task_kind == "craft_item":
        return _handle_craft_item(context)
    if context.task_kind == "equip_item":
        return _handle_equip_item(context)
    if context.task_kind == "move_to_place":
        return _handle_move_to_place(context)
    if context.task_kind in {"chop_wood", "fish_work", "farm_work", "gather_work", "build_work", "hunt_work"}:
        return _handle_harvest_like_work(context)
    if context.task_kind == "heal_work":
        return _handle_heal_work(context)
    if context.task_kind == "trade_run":
        return _handle_trade_run(context)
    if context.task_kind == "patrol_area":
        return _handle_patrol_area(context)
    if context.task_kind == "store_item":
        return _handle_store_item(context)
    return False


__all__ = [
    "OCCUPATION_TASK_KINDS",
    "baseline_provisioning_task_specs",
    "baseline_task_candidates",
    "builder_work_task_specs",
    "can_handle_task",
    "execute_task_step",
    "farmer_work_task_specs",
    "fisherman_work_task_specs",
    "gatherer_work_task_specs",
    "guard_work_task_specs",
    "healer_work_task_specs",
    "hunter_work_task_specs",
    "routine_task_specs",
    "should_activate_builder_work",
    "should_activate_farmer_work",
    "should_activate_fisherman_work",
    "should_activate_gatherer_work",
    "should_activate_guard_work",
    "should_activate_healer_work",
    "should_activate_hunter_work",
    "should_activate_trader_work",
    "should_activate_woodcutter_work",
    "suggested_occupation_task_kind",
    "trader_work_task_specs",
    "woodcutter_work_task_specs",
]
