from __future__ import annotations

"""Stable execution contracts for the task orchestrator."""

from dataclasses import dataclass, field
from typing import Any, Callable

from .ops import active_task_payload


CallbackAny = Callable[..., Any]


@dataclass(slots=True)
class TaskWorldBridge:
    """Stable runtime bridge exposed to task families.

    The engine remains authoritative over world state, but tasks should only
    talk to it through this small surface instead of depending on ad hoc
    engine methods directly.
    """

    gather_radius: float = 24.0
    move_step: float = 2.4
    map_width: float = 0.0
    map_height: float = 0.0
    resolve_place_target: CallbackAny | None = None
    resolve_resource_target: CallbackAny | None = None
    resolve_safe_target: CallbackAny | None = None
    resolve_human_target: CallbackAny | None = None
    resolve_entity_target: CallbackAny | None = None
    resolve_help_target: CallbackAny | None = None
    resolve_support_target: CallbackAny | None = None
    move_toward_point: CallbackAny | None = None
    commit_action: CallbackAny | None = None
    withdraw_tool: CallbackAny | None = None
    available_ingredient_quantity: CallbackAny | None = None
    progress_toward_item_kind: CallbackAny | None = None
    craft_tool: CallbackAny | None = None
    nearest_storage_case: CallbackAny | None = None
    consume_resource_amount: CallbackAny | None = None
    mate_with_target_action: CallbackAny | None = None
    attack_target_action: CallbackAny | None = None
    heal_target_action: CallbackAny | None = None
    deliver_item_action: CallbackAny | None = None
    steal_from_container_action: CallbackAny | None = None
    queue_social_signal_action: CallbackAny | None = None
    queue_combat_signal_action: CallbackAny | None = None
    designate_construction_project_action: CallbackAny | None = None
    advance_construction_project_action: CallbackAny | None = None

    def resolve_place(self, place_tag: str, px: float, py: float, *, radius: float) -> dict[str, Any] | None:
        if not callable(self.resolve_place_target):
            return None
        result = self.resolve_place_target(str(place_tag), float(px), float(py), radius=float(radius))
        return dict(result) if isinstance(result, dict) else None

    def resolve_resource(self, resource_kind: str, px: float, py: float, *, radius: float) -> dict[str, Any] | None:
        if not callable(self.resolve_resource_target):
            return None
        result = self.resolve_resource_target(str(resource_kind), float(px), float(py), radius=float(radius))
        return dict(result) if isinstance(result, dict) else None

    def resolve_safe(self, px: float, py: float, *, radius: float) -> dict[str, Any] | None:
        if not callable(self.resolve_safe_target):
            return None
        result = self.resolve_safe_target(float(px), float(py), radius=float(radius))
        return dict(result) if isinstance(result, dict) else None

    def resolve_human(self, human_id: str) -> dict[str, Any] | None:
        if not callable(self.resolve_human_target):
            return None
        result = self.resolve_human_target(str(human_id))
        return dict(result) if isinstance(result, dict) else None

    def resolve_entity(self, entity_id: str) -> dict[str, Any] | None:
        if not callable(self.resolve_entity_target):
            return None
        result = self.resolve_entity_target(str(entity_id))
        return dict(result) if isinstance(result, dict) else None

    def resolve_help(self, px: float, py: float, *, radius: float) -> dict[str, Any] | None:
        if not callable(self.resolve_help_target):
            return None
        result = self.resolve_help_target(float(px), float(py), radius=float(radius))
        return dict(result) if isinstance(result, dict) else None

    def resolve_support(self, px: float, py: float, *, radius: float) -> dict[str, Any] | None:
        if not callable(self.resolve_support_target):
            return None
        result = self.resolve_support_target(float(px), float(py), radius=float(radius))
        return dict(result) if isinstance(result, dict) else None

    def move_toward(self, tx: float, ty: float, magnitude: float | None = None) -> bool:
        if not callable(self.move_toward_point):
            return False
        self.move_toward_point(float(tx), float(ty), float(self.move_step if magnitude is None else magnitude))
        return True

    def on_action(self, **kwargs: Any) -> None:
        if callable(self.commit_action):
            self.commit_action(**kwargs)

    def try_withdraw_tool(self, tool_kind: str, need: dict[str, Any]) -> bool:
        if not callable(self.withdraw_tool):
            return False
        return bool(self.withdraw_tool(str(tool_kind), dict(need or {})))

    def ingredient_quantity(self, item_kind: str, material_cache: dict[str, Any]) -> int:
        if not callable(self.available_ingredient_quantity):
            return 0
        return int(self.available_ingredient_quantity(str(item_kind), dict(material_cache or {})))

    def progress_to_item(self, item_kind: str, required_quantity: int) -> bool:
        if not callable(self.progress_toward_item_kind):
            return False
        return bool(self.progress_toward_item_kind(str(item_kind), max(int(required_quantity), 1)))

    def try_craft_tool(self, tool_kind: str, need: dict[str, Any]) -> bool:
        if not callable(self.craft_tool):
            return False
        return bool(self.craft_tool(str(tool_kind), dict(need or {})))

    def nearest_storage(self, px: float, py: float, *, radius: float) -> dict[str, Any] | None:
        if not callable(self.nearest_storage_case):
            return None
        result = self.nearest_storage_case(float(px), float(py), radius=float(radius))
        return dict(result) if isinstance(result, dict) else None

    def consume_resource(self, resource_kind: str, entity_id: int, quantity: int = 1, uid: str | None = None) -> int:
        """``uid``: the id of the source the caller resolved; when given, nothing is taken if the row now holds another entity."""
        if not callable(self.consume_resource_amount):
            return 0
        extra = {} if uid is None else {"uid": str(uid)}
        return max(
            int(self.consume_resource_amount(str(resource_kind), int(entity_id), max(int(quantity), 1), **extra)),
            0,
        )

    def try_mate_with_target(self, target_human_id: str) -> dict[str, Any]:
        if not callable(self.mate_with_target_action):
            return {"ok": False, "reason": "unsupported"}
        result = self.mate_with_target_action(str(target_human_id))
        return dict(result) if isinstance(result, dict) else {"ok": bool(result)}

    def try_attack_target(self, target_kind: str, target_id: str) -> dict[str, Any]:
        if not callable(self.attack_target_action):
            return {"ok": False, "reason": "unsupported"}
        result = self.attack_target_action(str(target_kind), str(target_id))
        return dict(result) if isinstance(result, dict) else {"ok": bool(result)}

    def try_heal_target(self, target_human_id: str, *, item_kind: str = "bandage") -> dict[str, Any]:
        if not callable(self.heal_target_action):
            return {"ok": False, "reason": "unsupported"}
        result = self.heal_target_action(str(target_human_id), str(item_kind))
        return dict(result) if isinstance(result, dict) else {"ok": bool(result)}

    def try_deliver_item(self, target_human_id: str, item_kind: str, quantity: int = 1) -> dict[str, Any]:
        if not callable(self.deliver_item_action):
            return {"ok": False, "reason": "unsupported"}
        result = self.deliver_item_action(str(target_human_id), str(item_kind), max(int(quantity), 1))
        return dict(result) if isinstance(result, dict) else {"ok": bool(result)}

    def try_steal_from_container(self, container_id: str, item_kind: str = "", quantity: int = 1) -> dict[str, Any]:
        if not callable(self.steal_from_container_action):
            return {"ok": False, "reason": "unsupported"}
        result = self.steal_from_container_action(str(container_id), str(item_kind), max(int(quantity), 1))
        return dict(result) if isinstance(result, dict) else {"ok": bool(result)}

    def queue_social_signal(self, target_human_id: str, signal: dict[str, Any]) -> bool:
        if not callable(self.queue_social_signal_action):
            return False
        return bool(self.queue_social_signal_action(str(target_human_id), dict(signal or {})))

    def queue_combat_signal(self, target_human_id: str, signal: dict[str, Any]) -> bool:
        if not callable(self.queue_combat_signal_action):
            return False
        return bool(self.queue_combat_signal_action(str(target_human_id), dict(signal or {})))

    def designate_construction_project(self, project_id: str) -> dict[str, Any]:
        if not callable(self.designate_construction_project_action):
            return {"ok": False, "reason": "unsupported"}
        result = self.designate_construction_project_action(str(project_id))
        return dict(result) if isinstance(result, dict) else {"ok": bool(result)}

    def advance_construction_project(self, project_id: str) -> dict[str, Any]:
        if not callable(self.advance_construction_project_action):
            return {"ok": False, "reason": "unsupported"}
        result = self.advance_construction_project_action(str(project_id))
        return dict(result) if isinstance(result, dict) else {"ok": bool(result)}


@dataclass(slots=True)
class TaskExecutionContext:
    """Context object passed through the task dispatcher and family handlers."""

    resident: dict[str, Any]
    tick: int
    px: float
    py: float
    personal_inventory: dict[str, Any]
    accessible_records: list[dict[str, Any]]
    bridge: TaskWorldBridge
    task: dict[str, Any] = field(default_factory=dict)

    @property
    def task_kind(self) -> str:
        return str(self.task.get("task_kind", "")).strip()

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.task.get("metadata", {}))

    @property
    def task_state(self) -> dict[str, Any]:
        state = self.resident.setdefault("task_state", {})
        state.setdefault("cargo_cache", {})
        state.setdefault("carry_manifest", {})
        return state

    @property
    def crafting_state(self) -> dict[str, Any]:
        return self.resident.setdefault("crafting_state", {})

    def set_intent(self, intent: str) -> None:
        self.resident.setdefault("status", {})["current_intent"] = str(intent)


def build_task_execution_context(
    resident: dict[str, Any],
    *,
    tick: int,
    px: float,
    py: float,
    personal_inventory: dict[str, Any],
    accessible_records: list[dict[str, Any]],
    bridge: TaskWorldBridge,
) -> TaskExecutionContext:
    return TaskExecutionContext(
        resident=resident,
        tick=int(tick),
        px=float(px),
        py=float(py),
        personal_inventory=personal_inventory,
        accessible_records=list(accessible_records),
        bridge=bridge,
        task=active_task_payload(resident),
    )


__all__ = [
    "TaskExecutionContext",
    "TaskWorldBridge",
    "build_task_execution_context",
]
