from __future__ import annotations

"""
Stable, generation-friendly combat ops.

This surface keeps attack intent collection and combat resolution on a small,
predictable API for future generated tools.
"""

from typing import Any

import torch

try:
    from systems.combat.hunting import HUNTABLE_ANIMAL_TYPES, huntable_animal_slots, nearest_huntable_animal, nearest_predator_target
    from systems.combat.manual import collect_manual_attack_intents
    from systems.combat.resolver import resolve_human_attack_intents, target_in_range
    from systems.combat.sim import collect_sim_attack_intents, collect_sim_hunt_intents
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.combat.hunting import (
        HUNTABLE_ANIMAL_TYPES,
        huntable_animal_slots,
        nearest_huntable_animal,
        nearest_predator_target,
    )
    from at_the_beginning.systems.combat.manual import collect_manual_attack_intents
    from at_the_beginning.systems.combat.resolver import resolve_human_attack_intents, target_in_range
    from at_the_beginning.systems.combat.sim import collect_sim_attack_intents, collect_sim_hunt_intents


def collect_autonomous_attacks(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    *,
    pairwise: dict,
    attack_range: float,
) -> list:
    return collect_sim_attack_intents(
        ctx,
        h_tensor,
        pairwise=pairwise,
        attack_range=attack_range,
    )


def collect_autonomous_hunts(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    hunt_range: float,
) -> list:
    return collect_sim_hunt_intents(
        ctx,
        h_tensor,
        m_tensor,
        hunt_range=hunt_range,
    )


def collect_manual_attacks_now(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    attack_range: float,
    manual_control: dict[str, Any] | None,
) -> list:
    return collect_manual_attack_intents(
        ctx,
        h_tensor,
        m_tensor,
        attack_range=attack_range,
        manual_control=manual_control,
    )


def resolve_attack_intents(
    intents: list,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    device: str,
    attack_damage: float | None = None,
    attack_range: float | None = None,
    stamina_cost: float | None = None,
    human_threat_delta: float = 40.0,
    hunt_hunger_restore: float | None = None,
    walls: list | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "attack_damage": attack_damage,
        "attack_range": attack_range,
        "stamina_cost": stamina_cost,
        "human_threat_delta": human_threat_delta,
        "hunt_hunger_restore": hunt_hunger_restore,
    }
    filtered_kwargs = {key: value for key, value in kwargs.items() if value is not None}
    return resolve_human_attack_intents(
        intents,
        h_tensor,
        m_tensor,
        device,
        walls=walls,
        **filtered_kwargs,
    )


def find_huntable_animals(m_tensor: torch.Tensor, *, type_col: int) -> torch.Tensor:
    return huntable_animal_slots(m_tensor, type_col)


def find_hunt_target(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    human_slot: int,
    max_distance: float,
) -> tuple[int, float]:
    return nearest_huntable_animal(
        h_tensor,
        m_tensor,
        human_slot,
        max_distance=max_distance,
    )


def find_predator_target(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    predator_slot: int,
    predator_type: int,
    *,
    max_distance: float,
    device: str = "cpu",
) -> tuple[str, int, float]:
    return nearest_predator_target(
        h_tensor,
        m_tensor,
        predator_slot,
        predator_type,
        max_distance=max_distance,
        device=device,
    )


def is_target_in_range_now(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    attacker_slot: int,
    target_kind: str,
    target_slot: int,
    attack_range: float,
) -> bool:
    return target_in_range(
        h_tensor,
        m_tensor,
        attacker_slot,
        target_kind,
        target_slot,
        attack_range=attack_range,
    )


__all__ = [
    "HUNTABLE_ANIMAL_TYPES",
    "collect_autonomous_attacks",
    "collect_autonomous_hunts",
    "collect_manual_attacks_now",
    "find_hunt_target",
    "find_huntable_animals",
    "find_predator_target",
    "is_target_in_range_now",
    "resolve_attack_intents",
]
