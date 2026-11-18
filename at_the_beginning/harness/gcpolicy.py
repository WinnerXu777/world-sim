"""Garbage-collector policy for a long-lived world: freeze the loaded world out of the collector's scans, thaw it before it is dropped.

Why: after boot the engine holds about 230,000 tracked objects (maps, tensors' Python wrappers, residents, registries). A full
(generation 2) collection scans all of them: about 42 ms here, a whole tick's budget, and one fell inside a tick (57 ms pause in the
Gate A models-on run). ``gc.freeze()`` moves every live object into a permanent generation the collector ignores, so a later full
collection only scans what was allocated after the freeze (0.0 ms for the boot heap).

The catch (orchestrator decision R2-H1abc-D): frozen objects are never collected. The server can create a new world in the same
process (New Game, load a save), so freezing after every load without a thaw would keep every old world alive. Hence the pair:

* ``freeze_after_load(token)``: ``gc.collect()`` (so garbage is not frozen), then ``gc.freeze()``. ``token`` identifies the world
  (``engine.world_epoch``).
* ``thaw_before_reset()``: ``gc.unfreeze()`` then ``gc.collect()``, called before the old world's objects are dropped, so they are
  reclaimed. Safe to call when nothing is frozen.
* ``ensure_frozen(token)``: cheap per-tick check; freezes once per world when a load path did not call ``freeze_after_load``
  (``world_snapshot.restore`` sets ``world_loaded`` itself).

Behaviour-preserving: collection timing changes, object lifetimes do not (a frozen object is simply not scanned; nothing the
engine uses is a weak-reference or finalizer target). ``EDEN_GC_FREEZE=0`` turns the whole policy off.
"""
from __future__ import annotations

import gc
import os

_state = {"token": None}


def enabled() -> bool:
    return os.environ.get("EDEN_GC_FREEZE", "1") != "0"


def freeze_after_load(token=None) -> bool:
    """Collect, then freeze everything alive into the permanent generation. Returns False when the policy is disabled."""
    if not enabled():
        return False
    if gc.get_freeze_count():
        gc.unfreeze()           # a previous world was never thawed: do not stack frozen worlds
    gc.collect()
    gc.freeze()
    _state["token"] = token
    return True


def thaw_before_reset() -> bool:
    """Unfreeze and collect so the world about to be discarded can be reclaimed. Returns True when something was frozen."""
    was_frozen = bool(gc.get_freeze_count())
    if was_frozen:
        gc.unfreeze()
        gc.collect()
    _state["token"] = None
    return was_frozen


def ensure_frozen(token) -> None:
    """Per-tick guard: freeze once for this world token if no load path did it."""
    if _state["token"] != token:
        freeze_after_load(token)
        _state["token"] = token         # also when disabled, so the check stays one comparison per tick


def frozen_token():
    return _state["token"]
