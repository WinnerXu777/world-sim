"""1008 defend Phase 1 (design: ``1008_defend_phase1_gap.md``): the one optional hook into human-vs-human damage.

``COMBAT_MODIFIER`` is ``None`` (today's behaviour, bit for bit) or a callable set by the model plane's installer::

    modifier(h_tensor, attacker_slot, target_slot, damage) -> (target_slot, damage)

``resolve_human_attack_intents`` calls it for a human target after the range and wall checks and before the damage is accumulated. The answer is
accepted only if the returned slot is a live human and the damage is a finite number >= 0; anything else is ignored and the original pair stands. The
threat the attack causes still lands on the ORIGINAL target. The modifier must be a pure function of the tensors and its own books (no randomness that
is not derived from the tick, no writes to the tensors: the resolver applies the damage) and is never chained for one intent. Entity targets are not
offered to it. Tests that set it restore it (``set_modifier(None)`` in ``addCleanup``).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

COMBAT_MODIFIER: Optional[Callable] = None
RESTRAINT_FLAG = "EDEN_RESTRAINT"


def set_modifier(modifier: Optional[Callable]) -> None:
    global COMBAT_MODIFIER
    COMBAT_MODIFIER = modifier


def restraint_enabled() -> bool:
    """Read at call time. The flag lives here so the resolver does not import the harness."""
    return os.environ.get(RESTRAINT_FLAG, "") == "1"
