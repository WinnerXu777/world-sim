from __future__ import annotations

"""Trait helpers for personality assignment and summaries."""

from typing import Iterable

from .catalog import BALANCED_BASE, TRAIT_NAMES


def clamp_trait(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 3)


_NORMALIZED: dict = {}
_NORMALIZED_LIMIT = 4096


def normalize_traits(traits: dict[str, float] | None) -> dict[str, float]:
    # Pure function of the trait values, called ~100 times per resident per tick with unchanged input: memoised, and every
    # call still returns a fresh dict (callers mutate or store the result).
    key = None
    if traits is not None:
        try:
            key = tuple(traits.items())
            hit = _NORMALIZED.get(key)
        except TypeError:  # an unhashable trait value: compute directly
            key = hit = None
        if hit is not None:
            return dict(hit)
    normalized = dict(BALANCED_BASE)
    for name in TRAIT_NAMES:
        if traits is not None and name in traits:
            normalized[name] = clamp_trait(float(traits[name]))
    if key is not None and len(_NORMALIZED) < _NORMALIZED_LIMIT:
        _NORMALIZED[key] = dict(normalized)
    return normalized


def jitter_traits(
    base_traits: dict[str, float],
    rng,
    *,
    amplitude: float = 0.08,
) -> dict[str, float]:
    jittered = {}
    for name, value in normalize_traits(base_traits).items():
        jittered[name] = clamp_trait(float(value) + rng.uniform(-amplitude, amplitude))
    return jittered


def top_traits(
    traits: dict[str, float],
    *,
    count: int = 3,
    minimum: float = 0.58,
) -> list[str]:
    ranked = sorted(
        ((name, clamp_trait(value)) for name, value in normalize_traits(traits).items()),
        key=lambda item: item[1],
        reverse=True,
    )
    chosen = [name for name, value in ranked if value >= minimum][: max(count, 0)]
    if chosen:
        return chosen
    return [name for name, _ in ranked[: max(count, 1)]]


def average_traits(traits: dict[str, float], names: Iterable[str]) -> float:
    values = [float(normalize_traits(traits).get(name, 0.5)) for name in names]
    if not values:
        return 0.5
    return clamp_trait(sum(values) / float(len(values)))
