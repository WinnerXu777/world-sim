from __future__ import annotations

from typing import Any

import torch

try:
    from genesis_config import CX, CY, X, Y
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import CX, CY, X, Y

try:
    from systems.movement.resolver import resolve_target_step
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.movement.resolver import resolve_target_step


def build_manual_control_context(
    h_tensor: torch.Tensor,
    player_control_runtime: Any = None,
    engine: Any = None,
) -> dict[str, Any]:
    """Build the per-tick manual control payload used by movement/combat systems."""
    if player_control_runtime is None or engine is None:
        return {}
    manual_control = player_control_runtime.build_tick_context(engine)
    controlled_mask = manual_control.get("controlled_mask")
    if not isinstance(controlled_mask, torch.Tensor):
        return {}
    if controlled_mask.shape[0] != h_tensor.shape[0] or not controlled_mask.any():
        return {}
    return {"manual_control": manual_control}


def apply_manual_control_movement(
    noise: torch.Tensor,
    h_tensor: torch.Tensor,
    h_indices: torch.Tensor,
    manual_control: dict[str, Any] | None,
    move_step: float,
    *,
    sprint_multiplier: float = 1.5,
    m_tensor: torch.Tensor | None = None,
) -> torch.Tensor:
    """Overlay direct-control movement on top of autonomous movement noise."""
    manual_by_slot = manual_control.get("by_slot", {}) if isinstance(manual_control, dict) else {}
    if not manual_by_slot:
        return noise

    for live_row, slot in enumerate(h_indices.tolist()):
        control = manual_by_slot.get(slot)
        if control is None:
            continue

        move_x = float(control.get("move_x", 0.0))
        move_y = float(control.get("move_y", 0.0))
        step = float(move_step) * (float(sprint_multiplier) if bool(control.get("sprint", False)) else 1.0)
        if abs(move_x) > 0.001 or abs(move_y) > 0.001:
            noise[live_row, 0] = move_x * step
            noise[live_row, 1] = move_y * step
            continue

        move_target = control.get("move_target")
        target_x = float(h_tensor[slot, X])
        target_y = float(h_tensor[slot, Y])
        selected_slot = int(control.get("selected_target_slot", -1))
        selected_kind = str(control.get("selected_target_kind", "")).strip().lower()
        pending_action = str(control.get("pending_action", "")).strip().lower()
        pending_semantic_action = str(control.get("pending_semantic_action", "")).strip().lower()
        if isinstance(move_target, dict):
            target_x = float(move_target.get("x", h_tensor[slot, X]))
            target_y = float(move_target.get("y", h_tensor[slot, Y]))
        elif (
            pending_action == "interact"
            or pending_semantic_action in {"interact_target", "work_on_target"}
        ) and selected_slot >= 0:
            if selected_kind == "human" and selected_slot < h_tensor.shape[0]:
                target_x = float(h_tensor[selected_slot, X])
                target_y = float(h_tensor[selected_slot, Y])
            elif selected_kind == "entity" and m_tensor is not None and selected_slot < m_tensor.shape[0]:
                target_x = float(m_tensor[selected_slot, CX])
                target_y = float(m_tensor[selected_slot, CY])
            else:
                continue
        else:
            # Player not pressing keys and no move target — stand still.
            noise[live_row, 0] = 0.0
            noise[live_row, 1] = 0.0
            continue

        step_x, step_y = resolve_target_step(
            float(h_tensor[slot, X]),
            float(h_tensor[slot, Y]),
            target_x,
            target_y,
            step,
        )
        noise[live_row, 0] = step_x
        noise[live_row, 1] = step_y
    return noise
