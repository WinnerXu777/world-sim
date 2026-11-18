"""Creatures (``EDEN_CREATURES=1``, default off, needs ``EDEN_WINDOW=1``): the species table, the spawn plan, the behaviour kernel and the chunk store.
Design: ``1008_creatures_gap.md``. ``table`` is data only and always importable; nothing else is read unless the flag is on."""
from __future__ import annotations

import os

ENV = "EDEN_CREATURES"


def enabled() -> bool:
    """Read at call time."""
    return os.environ.get(ENV, "") == "1"


def kernel_ready() -> bool:
    """True when the behaviour kernel exists (``kernel.step``, installed as a step hook by ``harness.engine_hooks`` when the flag is on)."""
    return True
