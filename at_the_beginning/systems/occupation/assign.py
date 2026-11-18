from __future__ import annotations

"""Stable assignment entry points for resident occupations."""

import hashlib
import random

from .catalog import OCCUPATION_DEFS
from .inheritance import sample_occupation_kind
from .schema import build_occupation_record


def _rng_for_human(human_id: str) -> random.Random:
    seed = int(hashlib.sha256(f"{human_id}|occupation_profile".encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def assign_occupation(
    human_id: str,
    *,
    personality: dict | None = None,
    parent_occupations: list[str] | tuple[str, ...] | None = None,
    preferred_kind: str | None = None,
) -> dict:
    sampled = sample_occupation_kind(
        human_id,
        parent_occupations=parent_occupations,
        personality=personality,
        preferred_kind=preferred_kind,
    )
    kind = str(sampled["kind"])
    rng = _rng_for_human(human_id)
    skill = 0.42 + rng.random() * 0.34
    if sampled.get("parent_bias") == kind:
        skill += 0.08
    stability = 0.64 + rng.random() * 0.22
    if sampled.get("mutation", False):
        stability -= 0.06
    notes = str(OCCUPATION_DEFS.get(kind, {}).get("notes", ""))
    return build_occupation_record(
        kind,
        origin=str(sampled.get("origin", "assigned")),
        parent_bias=str(sampled.get("parent_bias", "")),
        skill=skill,
        stability=stability,
        mutation=bool(sampled.get("mutation", False)),
        notes=notes,
        metadata={"weights": dict(sampled.get("weights", {}))},
    )
