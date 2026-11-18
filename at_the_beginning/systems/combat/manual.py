from __future__ import annotations

from typing import Any

import torch

try:
    from genesis_config import AGENT_TYPE_HUMAN, ANIMAL_TYPES, HP, M_HP, M_TYPE, TYPE
    from systems.combat.intents import CombatIntent
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import AGENT_TYPE_HUMAN, ANIMAL_TYPES, HP, M_HP, M_TYPE, TYPE
    from at_the_beginning.systems.combat.intents import CombatIntent


def collect_manual_attack_intents(
    manual_control: dict[str, Any] | None,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
) -> list[CombatIntent]:
    """Collect click-driven human attack intents against humans or animal entities."""
    manual_by_slot = manual_control.get("by_slot", {}) if isinstance(manual_control, dict) else {}
    if not manual_by_slot:
        return []

    intents: list[CombatIntent] = []
    for attacker_slot, control in manual_by_slot.items():
        slot = int(attacker_slot)
        if not (0 <= slot < h_tensor.shape[0]):
            continue
        if int(h_tensor[slot, TYPE]) != AGENT_TYPE_HUMAN or float(h_tensor[slot, HP]) <= 0.0:
            continue
        pending_action = str(control.get("pending_action", "")).strip().lower()
        pending_semantic_action = str(control.get("pending_semantic_action", "")).strip().lower()
        if pending_action != "attack" and pending_semantic_action != "attack_target":
            continue

        target_kind = str(control.get("selected_target_kind", "")).strip().lower()
        target_slot = int(control.get("selected_target_slot", -1))
        target_id = str(control.get("selected_target_id", "")).strip() or None
        if target_kind == "human":
            if target_slot == slot or not (0 <= target_slot < h_tensor.shape[0]):
                continue
            if int(h_tensor[target_slot, TYPE]) != AGENT_TYPE_HUMAN or float(h_tensor[target_slot, HP]) <= 0.0:
                continue
        elif target_kind == "entity":
            if not (0 <= target_slot < m_tensor.shape[0]):
                continue
            if int(m_tensor[target_slot, M_TYPE]) not in ANIMAL_TYPES or float(m_tensor[target_slot, M_HP]) <= 0.0:
                continue
        else:
            continue

        intents.append(
            CombatIntent(
                source="manual",
                action="attack",
                attacker_kind="human",
                attacker_slot=slot,
                target_kind=target_kind,
                target_slot=target_slot,
                target_id=target_id,
            )
        )
    return intents
