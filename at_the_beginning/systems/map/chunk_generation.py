from __future__ import annotations

from dataclasses import dataclass
import random

import torch

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg


CREATABLE_FRONTIER_TYPES = (
    cfg.M_LAKE,
    cfg.M_FOREST,
    cfg.M_MOUNTAIN,
    cfg.M_BEACH,
    cfg.M_GRASS,
    cfg.M_BARREN,
)


EDGE_COMPATIBILITY: dict[int, dict[int, float]] = {
    cfg.M_LAKE: {
        cfg.M_LAKE: 0.85,
        cfg.M_BEACH: 1.35,
        cfg.M_GRASS: 1.0,
        cfg.M_FOREST: 0.7,
        cfg.M_MOUNTAIN: 0.2,
        cfg.M_BARREN: 0.18,
    },
    cfg.M_FOREST: {
        cfg.M_LAKE: 0.45,
        cfg.M_BEACH: 0.2,
        cfg.M_GRASS: 1.15,
        cfg.M_FOREST: 1.2,
        cfg.M_MOUNTAIN: 0.55,
        cfg.M_BARREN: 0.25,
    },
    cfg.M_MOUNTAIN: {
        cfg.M_LAKE: 0.1,
        cfg.M_BEACH: 0.08,
        cfg.M_GRASS: 0.55,
        cfg.M_FOREST: 0.45,
        cfg.M_MOUNTAIN: 1.05,
        cfg.M_BARREN: 1.25,
    },
    cfg.M_BEACH: {
        cfg.M_LAKE: 0.95,
        cfg.M_BEACH: 1.1,
        cfg.M_GRASS: 1.15,
        cfg.M_FOREST: 0.5,
        cfg.M_MOUNTAIN: 0.2,
        cfg.M_BARREN: 0.35,
    },
    cfg.M_GRASS: {
        cfg.M_LAKE: 0.8,
        cfg.M_BEACH: 0.6,
        cfg.M_GRASS: 1.25,
        cfg.M_FOREST: 1.05,
        cfg.M_MOUNTAIN: 0.48,
        cfg.M_BARREN: 0.32,
    },
    cfg.M_BARREN: {
        cfg.M_LAKE: 0.18,
        cfg.M_BEACH: 0.3,
        cfg.M_GRASS: 0.85,
        cfg.M_FOREST: 0.3,
        cfg.M_MOUNTAIN: 1.0,
        cfg.M_BARREN: 1.15,
    },
    cfg.M_SEA: {
        cfg.M_LAKE: 0.55,
        cfg.M_BEACH: 1.5,
        cfg.M_GRASS: 0.55,
        cfg.M_FOREST: 0.2,
        cfg.M_MOUNTAIN: 0.08,
        cfg.M_BARREN: 0.18,
    },
}


@dataclass(frozen=True)
class FrontierProfile:
    """Observed terrain mix along a world edge, used to smooth expansion."""

    edge: str
    weights: dict[int, float]
    dominant_type: int
    sample_count: int

    def normalized_weights(self) -> dict[int, float]:
        total = sum(self.weights.values())
        if total <= 0.0:
            return {cfg.M_GRASS: 1.0}
        return {type_id: weight / total for type_id, weight in self.weights.items()}


@dataclass(frozen=True)
class FrontierFeatureSpec:
    """One reusable terrain instruction for a frontier expansion or future chunk generator."""

    feature_type: int
    spawn_mode: str
    scale: float | None = None
    radius: float | None = None
    count: int = 1
    segments: int = 1


def _edge_distance_factor(edge: str, x: float, y: float, sample_depth: float) -> float:
    depth = max(1.0, float(sample_depth))
    if edge == "west":
        proximity = max(0.0, (depth - x) / depth)
    elif edge == "east":
        proximity = max(0.0, (x - (cfg.MAP_WIDTH - depth)) / depth)
    elif edge == "north":
        proximity = max(0.0, (depth - y) / depth)
    else:
        proximity = max(0.0, (y - (cfg.MAP_HEIGHT - depth)) / depth)
    return 0.35 + proximity * 1.65


def _in_edge_sample_region(edge: str, x: float, y: float, sample_depth: float) -> bool:
    if edge == "west":
        return x <= sample_depth
    if edge == "east":
        return x >= cfg.MAP_WIDTH - sample_depth
    if edge == "north":
        return y <= sample_depth
    return y >= cfg.MAP_HEIGHT - sample_depth


def _contribute_weight(weights: dict[int, float], source_type: int, amount: float) -> None:
    if source_type in CREATABLE_FRONTIER_TYPES:
        weights[source_type] = weights.get(source_type, 0.0) + amount
        return
    aliases = EDGE_COMPATIBILITY.get(source_type)
    if not aliases:
        return
    for type_id, factor in aliases.items():
        weights[type_id] = weights.get(type_id, 0.0) + amount * float(factor)


def build_frontier_profile(
    m_tensor: torch.Tensor,
    *,
    edge: str,
    sample_depth: float = 220.0,
) -> FrontierProfile:
    """Read nearby edge terrain and convert it into weighted biome preferences."""
    weights: dict[int, float] = {}
    sample_count = 0
    for slot in range(min(cfg.MAX_ENTITIES, m_tensor.shape[0])):
        type_id = int(m_tensor[slot, cfg.M_TYPE])
        if type_id <= 0 or type_id in cfg.STRUCTURE_TYPES or type_id in cfg.ANIMAL_TYPES:
            continue
        x = float(m_tensor[slot, cfg.CX])
        y = float(m_tensor[slot, cfg.CY])
        if not _in_edge_sample_region(edge, x, y, sample_depth):
            continue
        weight = _edge_distance_factor(edge, x, y, sample_depth)
        _contribute_weight(weights, type_id, weight)
        sample_count += 1

    if not weights:
        weights = {
            cfg.M_GRASS: 1.0,
            cfg.M_FOREST: 0.55,
            cfg.M_BEACH: 0.35,
            cfg.M_LAKE: 0.2,
            cfg.M_MOUNTAIN: 0.18,
            cfg.M_BARREN: 0.12,
        }
    dominant_type = max(weights.items(), key=lambda item: item[1])[0]
    return FrontierProfile(edge=edge, weights=weights, dominant_type=int(dominant_type), sample_count=sample_count)


def _transition_multiplier(previous_type: int | None, candidate_type: int, streak: int) -> float:
    if previous_type is None:
        return 1.0
    base = EDGE_COMPATIBILITY.get(previous_type, {}).get(candidate_type, 0.45)
    if candidate_type == previous_type:
        return base * (0.9 if streak == 1 else 0.72 if streak >= 2 else 1.0)
    return base


def _feature_spec_for_type(type_id: int, rng: random.Random) -> FrontierFeatureSpec:
    if type_id == cfg.M_LAKE:
        return FrontierFeatureSpec(feature_type=type_id, spawn_mode="lake", scale=rng.uniform(38.0, 60.0))
    if type_id == cfg.M_FOREST:
        return FrontierFeatureSpec(
            feature_type=type_id,
            spawn_mode="forest_patch",
            radius=rng.uniform(58.0, 102.0),
            count=rng.randint(2, 4),
        )
    if type_id == cfg.M_MOUNTAIN:
        return FrontierFeatureSpec(
            feature_type=type_id,
            spawn_mode="mountain_chain",
            scale=rng.uniform(28.0, 42.0),
            segments=rng.randint(2, 4),
        )
    if type_id == cfg.M_BEACH:
        return FrontierFeatureSpec(feature_type=type_id, spawn_mode="single", scale=rng.uniform(42.0, 74.0))
    if type_id == cfg.M_BARREN:
        return FrontierFeatureSpec(feature_type=type_id, spawn_mode="single", scale=rng.uniform(34.0, 68.0))
    return FrontierFeatureSpec(feature_type=cfg.M_GRASS, spawn_mode="single", scale=rng.uniform(54.0, 94.0))


def generate_frontier_feature_plan(
    profile: FrontierProfile,
    *,
    feature_budget: int,
    rng_seed: int | None = None,
) -> tuple[FrontierFeatureSpec, ...]:
    """
    Generate a smoothed terrain plan for current edge expansion and future chunk generation.

    The plan is biased by:
    - observed edge biome weights
    - terrain-transition compatibility
    - mild anti-streak logic so one type can cluster without taking over completely
    """
    if feature_budget <= 0:
        return ()

    rng = random.Random(rng_seed)
    previous_type: int | None = None
    streak = 0
    plan: list[FrontierFeatureSpec] = []

    candidates = list(profile.normalized_weights().keys())
    if not candidates:
        candidates = [cfg.M_GRASS]

    for _ in range(int(feature_budget)):
        weighted_choices: list[tuple[int, float]] = []
        for type_id in candidates:
            base_weight = float(profile.weights.get(type_id, 0.05))
            transition = _transition_multiplier(previous_type, type_id, streak)
            weighted_choices.append((type_id, max(0.001, base_weight * transition)))

        total = sum(weight for _, weight in weighted_choices)
        pick = rng.uniform(0.0, total)
        chosen_type = candidates[0]
        running = 0.0
        for type_id, weight in weighted_choices:
            running += weight
            if pick <= running:
                chosen_type = type_id
                break

        plan.append(_feature_spec_for_type(chosen_type, rng))
        if chosen_type == previous_type:
            streak += 1
        else:
            previous_type = chosen_type
            streak = 1

    return tuple(plan)
