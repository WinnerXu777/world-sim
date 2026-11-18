from __future__ import annotations

"""
Stable, generation-friendly health ops.

These wrappers are intentionally narrow and boring so smaller open-source
models can compose them reliably when generating new tools or instincts.
"""

import torch

try:
    from systems.health.damage import (
        apply_entity_damage,
        apply_entity_heal,
        apply_human_damage,
        apply_human_heal,
    )
    from systems.health.durability import (
        damage_structure_state,
        reinforce_structure_durability,
        repair_structure_state,
    )
    from systems.health.effects import (
        apply_area_attack_effect,
        apply_bless_effect,
        apply_plague_effect,
        kill_humans,
    )
    from systems.health.infection import apply_infection_tick
    from systems.health.recovery import apply_heal_tick
    from systems.health.status import update_human_critical_state
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.health.damage import (
        apply_entity_damage,
        apply_entity_heal,
        apply_human_damage,
        apply_human_heal,
    )
    from at_the_beginning.systems.health.durability import (
        damage_structure_state,
        reinforce_structure_durability,
        repair_structure_state,
    )
    from at_the_beginning.systems.health.effects import (
        apply_area_attack_effect,
        apply_bless_effect,
        apply_plague_effect,
        kill_humans,
    )
    from at_the_beginning.systems.health.infection import apply_infection_tick
    from at_the_beginning.systems.health.recovery import apply_heal_tick
    from at_the_beginning.systems.health.status import update_human_critical_state


def damage_humans(mask: torch.Tensor, h_tensor: torch.Tensor, amount: float | torch.Tensor) -> bool:
    return apply_human_damage(mask, h_tensor, amount)


def heal_humans(
    mask: torch.Tensor,
    h_tensor: torch.Tensor,
    amount: float | torch.Tensor,
    *,
    max_hp: float = 100.0,
) -> bool:
    return apply_human_heal(mask, h_tensor, amount, max_hp=max_hp)


def damage_entities(mask: torch.Tensor, m_tensor: torch.Tensor, amount: float | torch.Tensor) -> bool:
    return apply_entity_damage(mask, m_tensor, amount)


def heal_entities(
    mask: torch.Tensor,
    m_tensor: torch.Tensor,
    amount: float | torch.Tensor,
    *,
    max_hp: float = 100.0,
) -> bool:
    return apply_entity_heal(mask, m_tensor, amount, max_hp=max_hp)


def refresh_human_critical_flags(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> None:
    update_human_critical_state(h_mask, h_tensor)


def run_human_recovery_tick(h_mask: torch.Tensor, h_tensor: torch.Tensor) -> None:
    apply_heal_tick(h_mask, h_tensor)


def run_infection_tick(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    pairwise: dict,
    *,
    proximity_fn,
) -> None:
    apply_infection_tick(h_mask, h_tensor, pairwise, proximity_fn=proximity_fn)


def apply_plague(
    mask: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    decay_rate: float = 2.0,
    infection_gain: float = 30.0,
    threat_gain: float = 15.0,
    mood_drop: float = 20.0,
) -> None:
    apply_plague_effect(
        mask,
        h_tensor,
        decay_rate=decay_rate,
        infection_gain=infection_gain,
        threat_gain=threat_gain,
        mood_drop=mood_drop,
    )


def apply_bless(
    mask: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    target_hp: float = 100.0,
    target_mood: float = 90.0,
) -> None:
    apply_bless_effect(mask, h_tensor, target_hp=target_hp, target_mood=target_mood)


def kill_humans_now(mask: torch.Tensor, h_tensor: torch.Tensor, pop_count_ref: list) -> bool:
    return kill_humans(mask, h_tensor, pop_count_ref)


def apply_area_attack(
    ctx: dict,
    h_tensor: torch.Tensor,
    pop_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    device: str,
    agent_radial_mask_fn,
    flee_fn,
    flee_radius_multiplier: float = 2.5,
) -> dict:
    return apply_area_attack_effect(
        ctx,
        h_tensor,
        pop_count_ref,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
        agent_radial_mask_fn=agent_radial_mask_fn,
        flee_fn=flee_fn,
        flee_radius_multiplier=flee_radius_multiplier,
    )


def repair_structure(m_tensor: torch.Tensor, entity_id: int, amount: float) -> None:
    repair_structure_state(m_tensor, entity_id, amount)


def damage_structure(m_tensor: torch.Tensor, entity_id: int, amount: float) -> None:
    damage_structure_state(m_tensor, entity_id, amount)


def reinforce_structure(m_tensor: torch.Tensor, entity_id: int, amount: float) -> None:
    reinforce_structure_durability(m_tensor, entity_id, amount)


__all__ = [
    "apply_area_attack",
    "apply_bless",
    "apply_plague",
    "damage_entities",
    "damage_humans",
    "damage_structure",
    "heal_entities",
    "heal_humans",
    "kill_humans_now",
    "refresh_human_critical_flags",
    "reinforce_structure",
    "repair_structure",
    "run_human_recovery_tick",
    "run_infection_tick",
]
