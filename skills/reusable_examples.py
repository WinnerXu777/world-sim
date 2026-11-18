"""
Reusable examples for future LLM-guided work in Eden.

This file is not part of the hot runtime.
It is a reference module showing the intended design logic:

- semantic tools at the planning layer
- deterministic validation/execution in Python
- generic control channels for live input
- new instincts only after registry-gap verification
- generated tools should prefer domain ops helpers over raw tensor writes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LOCAL_CONTROLLER_ID = "local_player"


def decree_possess_adam() -> dict[str, Any]:
    """
    World-model packet for possession.

    Good:
    - semantic tool name
    - no raw keypresses in the tool layer
    """
    return {
        "thought": "Assign local player control to Adam.",
        "map_actions": [],
        "human_actions": [
            {
                "tool_name": "tool_assign_control_target",
                "parameters": {
                    "controller_id": LOCAL_CONTROLLER_ID,
                    "target_kind": "human",
                    "target_name": "Adam",
                    "mode": "possess",
                },
            }
        ],
        "new_entities": [],
        "new_instincts": [],
    }


def godot_control_snapshot(move_x: float, move_y: float, sprint: bool = False) -> dict[str, Any]:
    """
    Runtime control payload sent by the client.

    Good:
    - generic move/buttons structure
    - reusable for humans now, cars later
    """
    return {
        "controller_id": LOCAL_CONTROLLER_ID,
        "seq": 42,
        "move": {"x": move_x, "y": move_y},
        "buttons": {
            "attack": False,
            "interact": False,
            "sprint": sprint,
        },
    }


def click_move_command(world_x: float, world_y: float, target_id: str | None = None) -> dict[str, Any]:
    """
    Generic right-click style move command.

    Good:
    - explicit semantic action
    - can target raw world space or a clicked entity
    - stays in the runtime event channel, not the tool layer
    """
    payload = {
        "controller_id": LOCAL_CONTROLLER_ID,
        "seq": 43,
        "event": "click_command",
        "action": "move",
        "button": "right",
        "world": {"x": world_x, "y": world_y},
    }
    if target_id:
        payload["target_kind"] = "entity"
        payload["target_id"] = target_id
    return payload


def click_attack_command(target_id: str, target_kind: str = "human") -> dict[str, Any]:
    """
    Generic left-click attack intent.
    """
    return {
        "controller_id": LOCAL_CONTROLLER_ID,
        "seq": 44,
        "event": "click_command",
        "action": "attack",
        "button": "left",
        "target_kind": target_kind,
        "target_id": target_id,
    }


def click_interact_command(target_id: str, world_x: float, world_y: float) -> dict[str, Any]:
    """
    Generic left-click interaction intent for entities such as wells, doors, or vehicles.
    """
    return {
        "controller_id": LOCAL_CONTROLLER_ID,
        "seq": 45,
        "event": "click_command",
        "action": "interact",
        "button": "left",
        "target_kind": "entity",
        "target_id": target_id,
        "world": {"x": world_x, "y": world_y},
    }


def propose_new_instinct_drive_vehicle() -> dict[str, Any]:
    """
    Example of proposing a new instinct only after existing tools are insufficient.

    This is the right kind of output when the requested behavior truly needs
    a new reusable simulation behavior.
    """
    return {
        "thought": "No current instinct supports vehicle-specific acceleration and steering. Propose one.",
        "map_actions": [],
        "human_actions": [],
        "new_entities": [],
        "new_instincts": [
            {
                "name": "instinct_drive_vehicle",
                "description": (
                    "Read a controlled human's mounted vehicle state and runtime control input. "
                    "Convert move/throttle/steer into vehicle acceleration, heading, and speed updates. "
                    "When no vehicle is mounted, do nothing."
                ),
                "heritable": False,
                "mask": {
                    "kind": "and",
                    "terms": [
                        {"kind": "compare", "col": "TYPE", "op": "==", "value": 1},
                        {"kind": "compare", "col": "H_SHELTER", "op": ">=", "value": 0},
                    ],
                },
            }
        ],
    }


def grant_loaded_instinct(instinct_name: str, bit: int, human_name: str = "Adam") -> dict[str, Any]:
    """
    After the generated instinct exists and is loaded, grant it through a normal tool.
    """
    return {
        "thought": f"Grant loaded instinct {instinct_name} to {human_name}.",
        "map_actions": [],
        "human_actions": [
            {
                "tool_name": "tool_grant_instinct",
                "parameters": {
                    "mask": {"kind": "name_in", "names": [human_name]},
                    "bit": bit,
                    "instinct_name": instinct_name,
                    "heritable": False,
                },
            }
        ],
        "new_entities": [],
        "new_instincts": [],
    }


def enter_vehicle(human_name: str, vehicle_id: str) -> dict[str, Any]:
    """
    Example of the *kind* of semantic tool we should add later.

    The world model should say:
    - enter the car
    not:
    - press W for 3 ticks
    """
    return {
        "thought": f"{human_name} should enter vehicle {vehicle_id}.",
        "map_actions": [],
        "human_actions": [
            {
                "tool_name": "tool_enter_vehicle",
                "parameters": {
                    "human_name": human_name,
                    "vehicle_id": vehicle_id,
                },
            }
        ],
        "new_entities": [],
        "new_instincts": [],
    }


def car_control_snapshot(throttle: float, steer: float, brake: bool = False) -> dict[str, Any]:
    """
    Same runtime channel idea, richer fields.

    This is why we do NOT want a hardcoded 'tool_wasd_move'.
    The control protocol should be able to grow.
    """
    return {
        "controller_id": LOCAL_CONTROLLER_ID,
        "seq": 77,
        "move": {"x": steer, "y": throttle},
        "buttons": {
            "attack": False,
            "interact": False,
            "sprint": False,
            "brake": brake,
        },
        "throttle": throttle,
        "steer": steer,
    }


@dataclass(slots=True)
class DesignDecision:
    feature: str
    recommended_layer: str
    reason: str


EXAMPLE_DECISIONS = [
    DesignDecision(
        feature="possess Adam",
        recommended_layer="semantic tool",
        reason="This is a high-level world state change, not a device event.",
    ),
    DesignDecision(
        feature="WASD movement",
        recommended_layer="runtime control channel",
        reason="This is fast local input and should stay device-shaped.",
    ),
    DesignDecision(
        feature="drive a car",
        recommended_layer="target-specific control adapter",
        reason="The same input can map differently for humans and vehicles.",
    ),
    DesignDecision(
        feature="click-to-move / click-to-attack / click-to-interact",
        recommended_layer="runtime click event channel",
        reason="Clicks should stay generic and semantic so multiple targets can reuse them.",
    ),
    DesignDecision(
        feature="new long-lived behavior not covered by registry",
        recommended_layer="generated instinct/tool after validation",
        reason="Only generate new code when existing deterministic options are insufficient.",
    ),
    DesignDecision(
        feature="new health or disaster tool body",
        recommended_layer="domain ops composition",
        reason="Smaller models are more reliable when they import stable ops helpers instead of writing raw tensor logic.",
    ),
]


def generated_tool_prefers_ops() -> dict[str, Any]:
    """
    A reminder packet describing the intended codegen shape for future tool generation.
    """
    return {
        "preferred_imports": [
            "systems.health.ops",
            "systems.nature.ops",
        ],
        "avoid": [
            "raw tensor column writes when an ops helper exists",
            "copying large chunks from instincts_and_tools.py",
        ],
        "pattern": [
            "choose domain",
            "build mask or target set",
            "call ops helper",
            "return minimal semantic payload",
        ],
    }


def print_examples() -> None:
    print("=== Possession tool ===")
    print(decree_possess_adam())
    print()

    print("=== Human control snapshot ===")
    print(godot_control_snapshot(1.0, 0.0, sprint=False))
    print()

    print("=== Proposed new instinct ===")
    print(propose_new_instinct_drive_vehicle())
    print()

    print("=== Click move command ===")
    print(click_move_command(420.0, 180.0, target_id="e_000042"))
    print()

    print("=== Click attack command ===")
    print(click_attack_command("h_000002"))
    print()

    print("=== Click interact command ===")
    print(click_interact_command("e_000051", world_x=390.0, world_y=240.0))
    print()

    print("=== Grant loaded instinct ===")
    print(grant_loaded_instinct("instinct_drive_vehicle", bit=6))
    print()

    print("=== Car control snapshot ===")
    print(car_control_snapshot(throttle=1.0, steer=0.25, brake=False))
    print()

    print("=== Design decisions ===")
    for item in EXAMPLE_DECISIONS:
        print(f"- {item.feature}: {item.recommended_layer} ({item.reason})")


if __name__ == "__main__":
    print_examples()
