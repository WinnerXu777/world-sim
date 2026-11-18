from __future__ import annotations

import torch

try:
    from genesis_config import AGENT_TYPE_HUMAN, HP, M_DEER, M_FISH, M_HP, M_SHEEP, M_TYPE, TYPE
    from systems.perception import nearest_entity_from_ids, nearest_human_from_mask
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import AGENT_TYPE_HUMAN, HP, M_DEER, M_FISH, M_HP, M_SHEEP, M_TYPE, TYPE
    from at_the_beginning.systems.perception import nearest_entity_from_ids, nearest_human_from_mask


HUNTABLE_ANIMAL_TYPES = {M_SHEEP, M_DEER, M_FISH}


def huntable_animal_slots(m_tensor: torch.Tensor, type_col: int) -> torch.Tensor:
    """Return live prey-animal slots that humans can hunt for food."""
    mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
    for animal_type in HUNTABLE_ANIMAL_TYPES:
        mask |= m_tensor[:, type_col] == float(animal_type)
    return torch.where(mask)[0]


def nearest_huntable_animal(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    animal_slots: torch.Tensor,
    *,
    max_distance: float | None = None,
) -> tuple[int, float]:
    """Nearest huntable animal entity slot from a prepared candidate list."""
    entity_id, distance = nearest_entity_from_ids(m_tensor, px, py, animal_slots)
    if max_distance is not None and distance > float(max_distance):
        return -1, float("inf")
    return entity_id, distance


def nearest_predator_target(
    h_tensor: torch.Tensor | None,
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    prey_types: set[int],
    *,
    max_distance: float,
    exclude_entity_slot: int | None = None,
) -> tuple[str, int, float]:
    """Nearest valid predator target across human and prey-animal candidates."""
    best_kind = ""
    best_slot = -1
    best_distance = float("inf")

    if h_tensor is not None and AGENT_TYPE_HUMAN in prey_types:
        human_mask = (h_tensor[:, TYPE] == AGENT_TYPE_HUMAN) & (h_tensor[:, HP] > 0.0)
        human_slot, human_distance = nearest_human_from_mask(
            h_tensor,
            px,
            py,
            human_mask,
            max_distance=max_distance,
        )
        if human_slot != -1 and human_distance < best_distance:
            best_kind = "human"
            best_slot = human_slot
            best_distance = human_distance

    animal_prey_types = {int(prey_type) for prey_type in prey_types if int(prey_type) != AGENT_TYPE_HUMAN}
    if animal_prey_types:
        prey_mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
        for prey_type in animal_prey_types:
            prey_mask |= m_tensor[:, M_TYPE] == float(prey_type)
        prey_mask &= m_tensor[:, M_HP] > 0.0
        if exclude_entity_slot is not None and 0 <= int(exclude_entity_slot) < prey_mask.shape[0]:
            prey_mask[int(exclude_entity_slot)] = False
        prey_slots = torch.where(prey_mask)[0]
        if prey_slots.numel():
            prey_slot, prey_distance = nearest_entity_from_ids(m_tensor, px, py, prey_slots)
            if prey_slot != -1 and prey_distance <= float(max_distance) and prey_distance < best_distance:
                best_kind = "entity"
                best_slot = prey_slot
                best_distance = prey_distance

    return best_kind, best_slot, best_distance


__all__ = [
    "HUNTABLE_ANIMAL_TYPES",
    "huntable_animal_slots",
    "nearest_huntable_animal",
    "nearest_predator_target",
]
