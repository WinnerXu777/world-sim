from __future__ import annotations

from collections import defaultdict
from typing import Any

import torch
try:
    from harness.clamp import clamp_rows_
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.clamp import clamp_rows_

try:
    from systems.movement.spatial import segment_blocked, wall_boxes
    from genesis_config import X, Y, CX, CY
    from genesis_config import (
        AGENT_TYPE_HUMAN,
        ANIMAL_TYPES,
        ATTACK_DAMAGE,
        ATTACK_RANGE,
        ATTACK_STAMINA_COST,
        EAT_HUNGER_RESTORE,
        HP,
        HUNGER,
        H_RESTRAINED,
        H_STAMINA,
        M_HP,
        M_TYPE,
        THREAT,
        TYPE,
    )
    from systems.combat.hunting import HUNTABLE_ANIMAL_TYPES
    from systems.combat.intents import CombatIntent
    from systems.combat import modifiers as _modifiers
    from systems.combat.queries import human_distance_to_entity, human_distance_to_human
    from systems.health import apply_entity_damage, apply_human_damage
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.movement.spatial import segment_blocked, wall_boxes
    from at_the_beginning.genesis_config import X, Y, CX, CY
    from at_the_beginning.genesis_config import (
        AGENT_TYPE_HUMAN,
        ANIMAL_TYPES,
        ATTACK_DAMAGE,
        ATTACK_RANGE,
        ATTACK_STAMINA_COST,
        EAT_HUNGER_RESTORE,
        HP,
        HUNGER,
        H_RESTRAINED,
        H_STAMINA,
        M_HP,
        M_TYPE,
        THREAT,
        TYPE,
    )
    from at_the_beginning.systems.combat.hunting import HUNTABLE_ANIMAL_TYPES
    from at_the_beginning.systems.combat.intents import CombatIntent
    from at_the_beginning.systems.combat import modifiers as _modifiers
    from at_the_beginning.systems.combat.queries import human_distance_to_entity, human_distance_to_human
    from at_the_beginning.systems.health import apply_entity_damage, apply_human_damage

from ..creatures import enabled as creatures_enabled


def target_in_range(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    attacker_slot: int,
    target_kind: str,
    target_slot: int,
    attack_range: float = ATTACK_RANGE,
) -> bool:
    """Shared range check for human attacks against humans or entities."""
    if target_kind == "entity":
        return human_distance_to_entity(h_tensor, m_tensor, attacker_slot, target_slot) <= float(attack_range)
    return human_distance_to_human(h_tensor, attacker_slot, target_slot) <= float(attack_range)


def _valid_human_slot(h_tensor: torch.Tensor, slot: int) -> bool:
    return 0 <= slot < h_tensor.shape[0] and int(h_tensor[slot, TYPE]) == AGENT_TYPE_HUMAN and float(h_tensor[slot, HP]) > 0.0


def _valid_entity_slot(m_tensor: torch.Tensor, slot: int) -> bool:
    return 0 <= slot < m_tensor.shape[0] and int(m_tensor[slot, M_TYPE]) in ANIMAL_TYPES and float(m_tensor[slot, M_HP]) > 0.0


def resolve_human_attack_intents(
    intents: list[CombatIntent],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    device: str,
    *,
    attack_damage: float = ATTACK_DAMAGE,
    attack_range: float = ATTACK_RANGE,
    stamina_cost: float = ATTACK_STAMINA_COST,
    human_threat_delta: float = 40.0,
    hunt_hunger_restore: float = EAT_HUNGER_RESTORE,
    walls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply shared human combat intents against humans or animal entities.

    ``walls`` overrides the wall boxes used for line-of-attack tests (default: boxes derived from ``m_tensor``).
    """
    if not intents:
        return {"resolved": 0, "human_hits": 0, "entity_hits": 0}

    human_damage = torch.zeros(h_tensor.shape[0], dtype=h_tensor.dtype, device=device)
    entity_damage = torch.zeros(m_tensor.shape[0], dtype=m_tensor.dtype, device=device)
    threat_delta = torch.zeros(h_tensor.shape[0], dtype=h_tensor.dtype, device=device)
    stamina_spent: list[int] = []
    entity_attackers: dict[int, list[int]] = defaultdict(list)
    outcomes: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    walls = wall_boxes(m_tensor) if walls is None else walls
    entity_targets: set[int] = set()
    restraint_on = _modifiers.restraint_enabled()
    modifier = _modifiers.COMBAT_MODIFIER
    threat_only = torch.zeros(h_tensor.shape[0], dtype=torch.bool, device=device)  # redirected attacks: the original target is still threatened

    for intent in intents:
        if intent.attacker_kind != "human":
            continue
        attacker_slot = int(intent.attacker_slot)
        if not _valid_human_slot(h_tensor, attacker_slot):
            continue
        if float(h_tensor[attacker_slot, H_STAMINA]) < float(stamina_cost):
            continue
        if restraint_on and float(h_tensor[attacker_slot, H_RESTRAINED]) > 0.0:  # EDEN_RESTRAINT: a restrained human cannot attack
            continue

        target_kind = str(intent.target_kind).strip().lower()
        target_slot = int(intent.target_slot)
        if target_kind == "human":
            if target_slot == attacker_slot or not _valid_human_slot(h_tensor, target_slot):
                continue
        elif target_kind == "entity":
            if not _valid_entity_slot(m_tensor, target_slot):
                continue
        else:
            continue

        if not target_in_range(h_tensor, m_tensor, attacker_slot, target_kind, target_slot, attack_range=attack_range):
            continue

        start = (float(h_tensor[attacker_slot, X]), float(h_tensor[attacker_slot, Y]))
        target_tensor, x_col, y_col = (m_tensor, CX, CY) if target_kind == "entity" else (h_tensor, X, Y)
        end = (float(target_tensor[target_slot, x_col]), float(target_tensor[target_slot, y_col]))
        if segment_blocked(start, end, walls):
            rejections.append({"attacker_slot": attacker_slot, "target_id": intent.target_id, "reason": "blocked"})
            continue

        stamina_spent.append(attacker_slot)
        modified = None
        if target_kind == "human":
            damage_slot, damage = target_slot, float(attack_damage)
            if modifier is not None:
                try:
                    answer = modifier(h_tensor, attacker_slot, target_slot, damage)
                    new_slot, new_damage = int(answer[0]), float(answer[1])
                except Exception:  # noqa: BLE001 - a faulty modifier must not stop the tick: the original pair stands
                    new_slot, new_damage = damage_slot, damage
                if new_damage == new_damage and 0.0 <= new_damage < float("inf") and _valid_human_slot(h_tensor, new_slot) and (new_slot, new_damage) != (damage_slot, damage):
                    modified = {"target_slot": target_slot, "damage": damage}
                    damage_slot, damage = new_slot, new_damage
            human_damage[damage_slot] += damage
            threat_delta[target_slot] += float(human_threat_delta)
            if modified is not None:
                threat_only[target_slot] = True
        else:
            entity_damage[target_slot] += float(attack_damage)
            entity_attackers[target_slot].append(attacker_slot)
            entity_targets.add(target_slot)
        outcome = {
            "source": intent.source,
            "action": intent.action,
            "attacker_slot": attacker_slot,
            "target_kind": target_kind,
            "target_slot": target_slot,
            "target_id": intent.target_id,
        }
        if modified is not None:
            outcome["modified"] = modified
            outcome["damage_slot"] = damage_slot
            outcome["damage"] = damage
        outcomes.append(outcome)

    if not outcomes:
        return {"resolved": 0, "human_hits": 0, "entity_hits": 0, "rejections": rejections}

    human_hit_mask = human_damage > 0
    if human_hit_mask.any():
        apply_human_damage(human_hit_mask, h_tensor, human_damage[human_hit_mask], hp_col=HP)
    threat_mask = human_hit_mask | threat_only
    if threat_mask.any():
        h_tensor[threat_mask, THREAT] += threat_delta[threat_mask]
        clamp_rows_(h_tensor, threat_mask, THREAT, hi=100.0)

    entity_hit_mask = entity_damage > 0
    previous_entity_hp = {}
    if entity_hit_mask.any():
        for slot in torch.where(entity_hit_mask)[0].tolist():
            previous_entity_hp[slot] = float(m_tensor[slot, M_HP])
        apply_entity_damage(entity_hit_mask, m_tensor, entity_damage[entity_hit_mask], hp_col=M_HP)

    if stamina_spent:
        attacker_idx = torch.tensor(stamina_spent, dtype=torch.long, device=h_tensor.device)
        h_tensor[attacker_idx, H_STAMINA] -= float(stamina_cost)
        clamp_rows_(h_tensor, attacker_idx, H_STAMINA, lo=0.0)

    hunts_completed = 0
    creatures_on = creatures_enabled()
    if creatures_on:
        from ..creatures.kernel import queue_human_kill

    for slot in entity_targets:
        huntable = int(m_tensor[slot, M_TYPE]) in HUNTABLE_ANIMAL_TYPES
        if not huntable and not creatures_on:
            continue
        if previous_entity_hp.get(slot, 0.0) <= 0.0 or float(m_tensor[slot, M_HP]) > 0.0:
            continue
        attackers = entity_attackers.get(slot, [])
        if not attackers:
            continue
        hunter_slot = attackers[0]
        if creatures_on:
            queue_human_kill(m_tensor, slot, hunter_slot)
        if not huntable:
            continue
        h_tensor[hunter_slot, HUNGER] -= float(hunt_hunger_restore)
        h_tensor[hunter_slot, HUNGER].clamp_(min=0.0)
        hunts_completed += 1

    return {
        "resolved": len(outcomes),
        "human_hits": int(human_hit_mask.sum().item()),
        "entity_hits": int(entity_hit_mask.sum().item()),
        "hunts_completed": hunts_completed,
        "outcomes": outcomes,
        "rejections": rejections,
    }
