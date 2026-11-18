from __future__ import annotations

from collections.abc import Iterable
from typing import Callable


def pick_best_entity(
    entity_ids: Iterable[int],
    score_fn: Callable[[int], float],
) -> int:
    """Return the entity id with the lowest score, or ``-1`` when empty."""
    best_entity_id = -1
    best_score = float("inf")
    for raw_entity_id in entity_ids:
        entity_id = int(raw_entity_id)
        score = float(score_fn(entity_id))
        if score < best_score:
            best_score = score
            best_entity_id = entity_id
    return best_entity_id


def rank_entity_ids(
    entity_ids: Iterable[int],
    score_fn: Callable[[int], float],
) -> list[int]:
    """Return entity ids sorted by ascending score."""
    return sorted((int(entity_id) for entity_id in entity_ids), key=lambda entity_id: float(score_fn(entity_id)))


__all__ = ["pick_best_entity", "rank_entity_ids"]
