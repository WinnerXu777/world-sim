from __future__ import annotations

"""Weighted inheritance and mutation helpers for occupations."""

import hashlib
import random

from .catalog import ALL_OCCUPATION_NAMES, OCCUPATION_NAMES


def derive_occupation_weights(
    *,
    parent_occupations: list[str] | tuple[str, ...] | None = None,
    personality: dict | None = None,
) -> dict[str, float]:
    weights = {kind: 1.0 for kind in OCCUPATION_NAMES}
    parent_occupations = [str(item) for item in list(parent_occupations or []) if str(item) in weights]
    traits = dict((personality or {}).get("traits", {}))

    if parent_occupations:
        share = 2.4 / max(1, len(parent_occupations))
        for kind in parent_occupations:
            weights[kind] += share

    aggression = float(traits.get("aggression", 0.5))
    caution = float(traits.get("caution", 0.5))
    greed = float(traits.get("greed", 0.5))
    mercy = float(traits.get("mercy", 0.5))
    curiosity = float(traits.get("curiosity", 0.5))
    sociability = float(traits.get("sociability", 0.5))
    discipline = float(traits.get("discipline", 0.5))
    resourcefulness = float(traits.get("resourcefulness", 0.5))
    protectiveness = float(traits.get("protectiveness", 0.5))

    weights["guard"] += aggression * 0.9 + protectiveness * 0.7 + discipline * 0.3
    weights["hunter"] += aggression * 0.55 + curiosity * 0.45 + resourcefulness * 0.45
    weights["fisherman"] += caution * 0.2 + discipline * 0.25 + resourcefulness * 0.35
    weights["farmer"] += discipline * 0.5 + caution * 0.25
    weights["builder"] += discipline * 0.45 + resourcefulness * 0.55
    weights["woodcutter"] += resourcefulness * 0.45 + aggression * 0.15
    weights["gatherer"] += curiosity * 0.5 + resourcefulness * 0.35
    weights["trader"] += greed * 0.6 + sociability * 0.7 + curiosity * 0.2
    weights["healer"] += mercy * 0.75 + protectiveness * 0.45 + caution * 0.2

    return {key: max(0.05, round(value, 4)) for key, value in weights.items()}


def _stable_rng(seed_text: str) -> random.Random:
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def sample_occupation_kind(
    human_id: str,
    *,
    parent_occupations: list[str] | tuple[str, ...] | None = None,
    personality: dict | None = None,
    preferred_kind: str | None = None,
) -> dict[str, object]:
    if preferred_kind in ALL_OCCUPATION_NAMES:
        return {
            "kind": str(preferred_kind),
            "weights": {kind: (1.0 if kind == preferred_kind else 0.0) for kind in ALL_OCCUPATION_NAMES},
            "mutation": False,
            "parent_bias": str(preferred_kind),
            "origin": "preferred",
        }

    weights = derive_occupation_weights(parent_occupations=parent_occupations, personality=personality)
    rng = _stable_rng(f"{human_id}|occupation")
    total = sum(weights.values())
    roll = rng.random() * max(total, 0.0001)
    cursor = 0.0
    chosen = OCCUPATION_NAMES[0]
    for kind in OCCUPATION_NAMES:
        cursor += float(weights[kind])
        if roll <= cursor:
            chosen = kind
            break

    parent_set = {str(item) for item in list(parent_occupations or []) if str(item)}
    mutation = bool(parent_set) and chosen not in parent_set
    parent_bias = ""
    if chosen in parent_set:
        parent_bias = chosen
    elif parent_set:
        parent_bias = "mixed"

    return {
        "kind": chosen,
        "weights": weights,
        "mutation": mutation,
        "parent_bias": parent_bias,
        "origin": "inherited" if parent_set else "assigned",
    }
