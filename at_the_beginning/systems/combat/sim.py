from __future__ import annotations

from typing import Any

import torch

try:
    from genesis_config import ATTACK_STAMINA_COST, X, Y
    from systems.combat.hunting import nearest_huntable_animal
    from systems.combat.intents import CombatIntent
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import ATTACK_STAMINA_COST, X, Y
    from at_the_beginning.systems.combat.hunting import nearest_huntable_animal
    from at_the_beginning.systems.combat.intents import CombatIntent


def collect_sim_attack_intents(
    pairwise: dict[str, Any] | None,
    manual_control: dict[str, Any] | None = None,
) -> list[CombatIntent]:
    """Collect autonomous human-vs-human combat intents from the pairwise pass."""
    if not isinstance(pairwise, dict):
        return []
    live_idx = pairwise.get("live_idx")
    if not isinstance(live_idx, torch.Tensor) or live_idx.numel() < 2:
        return []

    attack_pairs = (
        pairwise["within_attack"]
        & pairwise["aggressive"][:, None]
        & pairwise["peaceful"][None, :]
    )
    if isinstance(manual_control, dict):
        controlled_mask = manual_control.get("controlled_mask")
        if isinstance(controlled_mask, torch.Tensor) and controlled_mask.shape[0] > int(live_idx.max().item()):
            attack_pairs &= ~controlled_mask[live_idx][:, None]
    if not attack_pairs.any():
        return []

    dists = pairwise["dists"]
    inf = torch.finfo(dists.dtype).max
    candidate_dist = dists.masked_fill(~attack_pairs, inf)
    attacker_rows = torch.where(attack_pairs.any(dim=1))[0]
    if attacker_rows.numel() == 0:
        return []
    target_rows = candidate_dist[attacker_rows].argmin(dim=1)

    intents: list[CombatIntent] = []
    for attacker_row, target_row in zip(attacker_rows.tolist(), target_rows.tolist()):
        intents.append(
            CombatIntent(
                source="sim",
                action="attack",
                attacker_kind="human",
                attacker_slot=int(live_idx[attacker_row].item()),
                target_kind="human",
                target_slot=int(live_idx[target_row].item()),
            )
        )
    return intents


def collect_sim_hunt_intents(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    h_mask: torch.Tensor,
    animal_slots: torch.Tensor,
    *,
    hunger_col: int,
    aggression_col: int,
    stamina_col: int,
    food_seek_threshold: float,
    aggression_threshold: float,
    manual_control: dict[str, Any] | None = None,
    attack_range: float,
) -> list[CombatIntent]:
    """Collect simple autonomous hunt intents when hungry/aggressive humans are already in range."""
    if animal_slots.numel() == 0 or not h_mask.any():
        return []

    eligible = (
        h_mask
        & (h_tensor[:, hunger_col] >= float(food_seek_threshold))
        & (h_tensor[:, aggression_col] >= float(aggression_threshold))
        & (h_tensor[:, stamina_col] >= float(ATTACK_STAMINA_COST))
    )
    if isinstance(manual_control, dict):
        controlled_mask = manual_control.get("controlled_mask")
        if isinstance(controlled_mask, torch.Tensor) and controlled_mask.shape[0] == h_tensor.shape[0]:
            eligible &= ~controlled_mask
    if not eligible.any():
        return []

    intents: list[CombatIntent] = []
    for attacker_slot in torch.where(eligible)[0].tolist():
        target_slot, target_distance = nearest_huntable_animal(
            m_tensor,
            float(h_tensor[attacker_slot, X]),
            float(h_tensor[attacker_slot, Y]),
            animal_slots,
            max_distance=float(attack_range),
        )
        if target_slot == -1 or target_distance > float(attack_range):
            continue
        intents.append(
            CombatIntent(
                source="sim",
                action="hunt",
                attacker_kind="human",
                attacker_slot=int(attacker_slot),
                target_kind="entity",
                target_slot=int(target_slot),
            )
        )
    return intents
