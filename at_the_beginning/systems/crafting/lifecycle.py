from __future__ import annotations

"""Resident crafting state and baseline provisioning helpers."""

from copy import deepcopy
from typing import Any, Iterable

try:
    import genesis_config as cfg
    from systems.inventory import list_items, total_quantity
    from systems.occupation.ops import occupation_core_tools, occupation_prompt_summary, occupation_upgrade_tools
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.systems.inventory import list_items, total_quantity
    from at_the_beginning.systems.occupation.ops import (
        occupation_core_tools,
        occupation_prompt_summary,
        occupation_upgrade_tools,
    )

from .catalog import CRAFTING_RECIPE_IDS
from .resolver import crafting_output_kind


CRAFTING_STATE_SCHEMA_VERSION = 1
BASELINE_PROVISION_REVIEW_TICKS = max(1, int(round(cfg.TICK_RATE_HZ * 4.0)))


def _default_crafting_state(tick: int) -> dict[str, Any]:
    return {
        "schema_version": CRAFTING_STATE_SCHEMA_VERSION,
        "last_review_tick": max(0, int(tick) - BASELINE_PROVISION_REVIEW_TICKS),
        "review_reason": "",
        "maturity_ready": False,
        "survival_clear": False,
        "auto_allowed": False,
        "baseline_ready": False,
        "required_tools": [],
        "optional_tools": [],
        "baseline_needs": [],
        "active_need": None,
        "material_cache": {},
        "accessible_storage_count": 0,
        "last_action_tick": -1,
        "next_action_tick": 0,
        "last_action": "",
        "summary": "crafting not reviewed",
    }


def ensure_crafting_state(resident: dict[str, Any], tick: int) -> dict[str, Any]:
    state = resident.get("crafting_state")
    if not isinstance(state, dict) or not state:
        resident["crafting_state"] = _default_crafting_state(tick)
    else:
        defaults = _default_crafting_state(tick)
        for key, value in defaults.items():
            if key not in resident["crafting_state"]:  # setdefault(key, deepcopy(value)) copied the default on every call
                resident["crafting_state"][key] = deepcopy(value)
    return resident["crafting_state"]


def baseline_provisioning_due(
    resident: dict[str, Any],
    tick: int,
    *,
    review_ticks: int = BASELINE_PROVISION_REVIEW_TICKS,
) -> bool:
    state = ensure_crafting_state(resident, tick)
    last_review_tick = int(state.get("last_review_tick", 0))
    return int(tick) - last_review_tick >= int(review_ticks)


def _survival_clear(snapshot: dict[str, Any]) -> bool:
    if not snapshot:
        return False
    hunger = float(snapshot.get("hunger", 100.0))
    thirst = float(snapshot.get("thirst", 100.0))
    threat = float(snapshot.get("threat", 100.0))
    hp = float(snapshot.get("hp", 0.0))
    stamina = float(snapshot.get("stamina", 0.0))
    escalated = bool(snapshot.get("escalated", False))
    return (
        hunger < (cfg.FOOD_SEEK_THRESHOLD * 0.72)
        and thirst < (cfg.WATER_SEEK_THRESHOLD * 0.72)
        and threat < (cfg.SHELTER_SEEK_THREAT * 0.5)
        and hp >= max(cfg.CRITICAL_HEALTH_THRESHOLD + 20.0, 45.0)
        and stamina >= 34.0
        and not escalated
    )


def _maturity_ready(snapshot: dict[str, Any]) -> bool:
    return float(snapshot.get("age", 0.0)) >= float(cfg.MATURE_AGE)


def _recipe_id_for_output(item_kind: str) -> str:
    needle = str(item_kind or "").strip()
    if not needle:
        return ""
    for recipe_id in CRAFTING_RECIPE_IDS:
        if crafting_output_kind(recipe_id) == needle:
            return recipe_id
    return ""


def _inventory_stacks(record: dict | None) -> list[dict[str, Any]]:
    if not isinstance(record, dict):
        return []
    return [dict(item) for item in list_items(record, limit=None)]


def _combined_stacks(
    personal_inventory: dict | None,
    accessible_inventories: Iterable[dict[str, Any]] | None,
    material_cache: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    stacks: list[dict[str, Any]] = []
    stacks.extend(_inventory_stacks(personal_inventory))
    for entry in list(accessible_inventories or []):
        record = entry.get("inventory") if isinstance(entry, dict) else None
        stacks.extend(_inventory_stacks(record))
    for item_kind, quantity in dict(material_cache or {}).items():
        qty = max(int(quantity), 0)
        if not str(item_kind).strip() or qty <= 0:
            continue
        stacks.append({"kind": str(item_kind), "quantity": qty})
    return stacks


def _need_sort_key(need: dict[str, Any]) -> tuple[int, float, str]:
    status = str(need.get("status", "")).strip()
    rank = {
        "withdraw": 0,
        "craft": 1,
        "gather_then_craft": 2,
        "acquire_external": 3,
        "satisfied": 4,
    }.get(status, 5)
    return (rank, -float(need.get("priority", 0.0)), str(need.get("tool_kind", "")))


def _summary_for_need(need: dict[str, Any]) -> str:
    tool_kind = str(need.get("tool_kind", "")).strip()
    status = str(need.get("status", "")).strip()
    if status == "satisfied":
        return f"{tool_kind} already available"
    if status == "withdraw":
        return f"withdraw {tool_kind} from nearby storage"
    if status == "craft":
        return f"craft {tool_kind} from available materials"
    if status == "gather_then_craft":
        missing = list(need.get("missing_ingredients", []))
        if missing:
            first = missing[0]
            return (
                f"gather {int(first.get('missing_quantity', 0))}x "
                f"{first.get('item_kind', '')} for {tool_kind}"
            )
        return f"gather materials for {tool_kind}"
    if status == "acquire_external":
        return f"needs {tool_kind}; no local recipe available"
    return tool_kind or "baseline need"


def sync_baseline_provisioning(
    resident: dict[str, Any],
    tick: int,
    *,
    personal_inventory: dict | None = None,
    accessible_inventories: Iterable[dict[str, Any]] | None = None,
    allow_auto: bool = True,
    force: bool = False,
    build_job: Any | None = None,
    missing_ingredients_fn: Any | None = None,
) -> bool:
    state = ensure_crafting_state(resident, tick)
    previous = deepcopy(state)

    if not force and not baseline_provisioning_due(resident, tick):
        return False

    snapshot = dict(resident.get("snapshot", {}))
    maturity_ready = _maturity_ready(snapshot)
    survival_clear = _survival_clear(snapshot)
    required_tools = [tool for tool in occupation_core_tools(resident) if str(tool).strip()]
    optional_tools = [tool for tool in occupation_upgrade_tools(resident) if str(tool).strip()]
    accessible_entries = [dict(entry) for entry in list(accessible_inventories or [])]

    auto_allowed = bool(allow_auto and maturity_ready and survival_clear and required_tools)
    state["last_review_tick"] = int(tick)
    state["maturity_ready"] = maturity_ready
    state["survival_clear"] = survival_clear
    state["auto_allowed"] = auto_allowed
    state["required_tools"] = list(required_tools)
    state["optional_tools"] = list(optional_tools)
    state["material_cache"] = {
        str(item_kind): max(int(quantity), 0)
        for item_kind, quantity in dict(state.get("material_cache", {})).items()
        if str(item_kind).strip() and max(int(quantity), 0) > 0
    }
    state["accessible_storage_count"] = len(accessible_entries)
    state["review_reason"] = ""

    if not required_tools:
        state["baseline_ready"] = False
        state["baseline_needs"] = []
        state["active_need"] = None
        state["summary"] = "no baseline occupation tools required"
        state["review_reason"] = "no_required_tools"
        return previous != state

    if not maturity_ready:
        state["baseline_ready"] = False
        state["baseline_needs"] = []
        state["active_need"] = None
        state["summary"] = "not mature for baseline occupation provisioning"
        state["review_reason"] = "not_mature"
        return previous != state

    if not allow_auto:
        state["baseline_ready"] = False
        state["baseline_needs"] = []
        state["active_need"] = None
        state["summary"] = "manual control pauses automatic occupation provisioning"
        state["review_reason"] = "manual_controlled"
        return previous != state

    if not survival_clear:
        state["baseline_ready"] = False
        state["baseline_needs"] = []
        state["active_need"] = None
        state["summary"] = "survival stress delays occupation provisioning"
        state["review_reason"] = "survival_not_clear"
        return previous != state

    state["baseline_ready"] = True
    combined_stacks = _combined_stacks(
        personal_inventory,
        accessible_entries,
        state.get("material_cache", {}),
    )
    needs: list[dict[str, Any]] = []

    for index, tool_kind in enumerate(required_tools):
        personal_quantity = total_quantity(personal_inventory, tool_kind) if isinstance(personal_inventory, dict) else 0
        accessible_quantity = 0
        source_container_id = ""
        source_inventory_id = ""
        for entry in accessible_entries:
            record = entry.get("inventory") if isinstance(entry, dict) else None
            quantity = total_quantity(record, tool_kind) if isinstance(record, dict) else 0
            if quantity <= 0:
                continue
            accessible_quantity += quantity
            if not source_container_id:
                source_container_id = str(entry.get("container_id", ""))
                source_inventory_id = str((record or {}).get("inventory_id", ""))

        need: dict[str, Any] = {
            "tool_kind": tool_kind,
            "required_quantity": 1,
            "available_personal": int(personal_quantity),
            "available_accessible": int(accessible_quantity),
            "priority": round(max(0.15, 0.82 - (index * 0.08)), 3),
        }

        if personal_quantity > 0:
            need["status"] = "satisfied"
            need["summary"] = _summary_for_need(need)
            needs.append(need)
            continue

        if accessible_quantity > 0:
            need["status"] = "withdraw"
            need["source_container_id"] = source_container_id
            need["source_inventory_id"] = source_inventory_id
            need["summary"] = _summary_for_need(need)
            needs.append(need)
            continue

        recipe_id = _recipe_id_for_output(tool_kind)
        if recipe_id:
            missing_ingredients = (
                missing_ingredients_fn(recipe_id, combined_stacks)
                if callable(missing_ingredients_fn)
                else []
            )
            need["recipe_id"] = recipe_id
            need["missing_ingredients"] = missing_ingredients
            if callable(build_job):
                need["job"] = build_job(
                    recipe_id,
                    owner_id=str(resident.get("id", "")),
                    owner_kind="resident",
                    source="occupation_baseline",
                    priority=float(need["priority"]),
                    metadata={
                        "tool_kind": tool_kind,
                        "occupation_kind": str(resident.get("occupation", {}).get("kind", "")),
                        "occupation_summary": occupation_prompt_summary(resident),
                    },
                )
            need["status"] = "craft" if not missing_ingredients else "gather_then_craft"
            need["summary"] = _summary_for_need(need)
        else:
            need["status"] = "acquire_external"
            need["recipe_id"] = ""
            need["missing_ingredients"] = []
            need["summary"] = _summary_for_need(need)
        needs.append(need)

    needs.sort(key=_need_sort_key)
    active_need = next((deepcopy(need) for need in needs if str(need.get("status", "")) != "satisfied"), None)
    state["baseline_needs"] = needs
    state["active_need"] = active_need
    if active_need is None:
        state["summary"] = "baseline occupation tools satisfied"
        state["review_reason"] = "baseline_satisfied"
    else:
        state["summary"] = str(active_need.get("summary", "")) or "baseline tool provisioning pending"
        state["review_reason"] = f"baseline_need:{active_need.get('status', 'pending')}"
    return previous != state
