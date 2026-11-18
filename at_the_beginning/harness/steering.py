"""2.A1 steering wire (``EDEN_STEERING=1``, default off; ``1008_instincts_wiring_gap.md`` step 1): the six steering instincts that exist but are not in the default registry.

``instinct_pairwise_relations``, ``instinct_search``, ``instinct_reproduction_strategy``, ``instinct_survival_navigation``, ``instinct_social_navigation`` and
``instinct_schedule_navigation`` (``instincts_and_tools.py``) return the dictionaries ``instinct_move`` already reads (``seek_mask``, ``nav_survival_bias``, ``nav_social_bias``,
``nav_schedule_bias``), but nothing registered them, so a human outside a roster wandered without hunger, mates or a schedule pulling it. This module registers them, in that order, between
``instinct_structure_occupancy`` (37) and ``instinct_move`` (38). The ``TASK_OWNED_*`` filters inside them keep a resident that has an active task from being steered twice.

No edit of ``instincts_and_tools.py``: the functions are looked up on the module. In a roster world the anchor-driven residents are moved by the roster driver and ``instinct_move`` zeroes
their noise and biases, so the wire is invisible there by design (tested: strict goldens and a 600-tick tensor comparison); it matters for the humans that are not roster residents.
"""
from __future__ import annotations

import os

FLAG = "EDEN_STEERING"
ENTRIES = (("instinct_pairwise_relations", 37.1), ("instinct_search", 37.2), ("instinct_reproduction_strategy", 37.3),
           ("instinct_survival_navigation", 37.4), ("instinct_social_navigation", 37.5), ("instinct_schedule_navigation", 37.6))


def enabled() -> bool:
    return os.environ.get(FLAG, "") == "1"


def _module():
    try:
        import instincts_and_tools as iat
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import instincts_and_tools as iat
    return iat


def install(engine) -> int:
    """Register the six entries once; returns how many were added (0 when they are all there)."""
    iat = _module()
    present = {entry["fn"] for entry in engine._registry}
    added = 0
    for name, priority in ENTRIES:
        fn = getattr(iat, name)
        if fn in present:
            continue
        engine.register(fn, priority=priority)
        added += 1
    return added
