"""2.A3 danger ledger, harness half (``EDEN_DANGER=1``, default off; ``1008_instincts_wiring_gap.md`` step 4).

A resident that is hit remembers where it happened. The ledger is the resident record's own ``memory.last_threats`` (``ResidentAgentStore.remember_threat``): entries with a position, a
kind and a time-to-live in life-years, which the model plane's pressures, goal review and reasoning already read, and which a re-base already shifts
(``systems.actions.rebase.rebase_model_plane``: the entries keep their absolute place when the window origin moves; tested here). This module only adds the writer and the readers:

* the writer is a ``wounds.on_hit`` callback: the source of a hit is the nearest live hostile creature within ``SOURCE_RADIUS`` (the creature table's ``hostile`` set; the legacy tiger and
  wolf with ``EDEN_CREATURES`` off) and the kind is ``predator``; with no creature near (a fall, a fire, a hand) the resident's own position is remembered as a ``hazard``;
  ``remember_threat`` also asks the model plane for a goal review, so a bitten resident reconsiders what it is doing;
* the readers are ``places(engine, uid)`` (the active entries), ``near_danger`` and ``danger_pressure`` (0..1: the strongest entry's salience falling linearly with distance), which are what the
  Tier 1 features ``fear`` / ``near_danger`` / ``avoid_places`` need.

The detector is ``wounds.step``: ``EDEN_DANGER`` without ``EDEN_WOUNDS`` records places and queues ``human_wounded`` but keeps no bleed.
"""
from __future__ import annotations

import math
import os
from typing import Optional

import torch

FLAG = "EDEN_DANGER"
SOURCE_RADIUS = 120.0         # a hostile creature this near is the one that hit
READ_RADIUS = 60.0
_INSTALLED = {"callback": None}


def enabled() -> bool:
    return os.environ.get(FLAG, "") == "1"


def _hostile_ids() -> torch.Tensor:
    try:
        from systems.creatures import table
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.systems.creatures import table
    return torch.tensor(sorted(float(i) for i in table.hostile_types()), dtype=torch.float32)


def source_of(engine, slot: int) -> Optional[tuple]:
    """``(x, y, distance)`` of the nearest live hostile creature within ``SOURCE_RADIUS`` of resident ``slot`` (in its space), else None."""
    import genesis_config as cfg
    h, m = engine.state.h_tensor, engine.state.m_tensor
    n = cfg.MAX_ENTITIES
    hostile = torch.isin(m[:n, cfg.M_TYPE], _hostile_ids().to(m.device)) & (m[:n, cfg.M_HP] > 0) & (m[:n, cfg.M_SPACE] == float(h[slot, cfg.H_SPACE]))
    rows = hostile.nonzero(as_tuple=False).flatten()
    if rows.numel() == 0:
        return None
    here = h[slot, [cfg.X, cfg.Y]]
    distance = torch.cdist(here.unsqueeze(0), m[rows][:, [cfg.CX, cfg.CY]])[0]
    best = int(distance.argmin())
    if float(distance[best]) > SOURCE_RADIUS:
        return None
    row = int(rows[best])
    return float(m[row, cfg.CX]), float(m[row, cfg.CY]), float(distance[best])


def remember(engine, slot: int, uid: str, damage: float) -> Optional[str]:
    """Write the hit into the resident's threat memory; returns the kind written, or None (no store, or no record for this resident)."""
    import genesis_config as cfg
    store = getattr(engine, "resident_store", None)
    if store is None or store.get(uid) is None:
        return None
    found = source_of(engine, slot)
    if found is not None:
        x, y, distance = found
        kind = "predator"
    else:
        h = engine.state.h_tensor
        x, y, distance, kind = float(h[slot, cfg.X]), float(h[slot, cfg.Y]), 0.0, "hazard"
    store.remember_threat(uid, kind, (x, y), int(engine.tick), distance)
    return kind


def _on_hit(engine, slot: int, uid: str, damage: float) -> None:
    remember(engine, slot, uid, damage)


def install() -> bool:
    """Subscribe the writer to the wounds detector (idempotent)."""
    from . import wounds
    if _INSTALLED["callback"] is not None:
        return False
    _INSTALLED["callback"] = _on_hit
    wounds.on_hit(_on_hit)
    return True


def uninstall() -> None:
    from . import wounds
    if _INSTALLED["callback"] is not None:
        wounds.off_hit(_INSTALLED["callback"])
        _INSTALLED["callback"] = None


# ---- readers -------------------------------------------------------------------------------------------------------------------------------------------------
def places(engine, uid: str) -> list:
    """The active threat entries of resident ``uid`` (dicts with kind, x, y, tick, distance, salience...)."""
    store = getattr(engine, "resident_store", None)
    record = None if store is None else store.get(uid)
    if record is None:
        return []
    try:
        from runtime.resident_store import _is_entry_active
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.runtime.resident_store import _is_entry_active
    tick = int(engine.tick)
    return [dict(entry) for entry in (record.get("memory") or {}).get("last_threats", []) if isinstance(entry, dict) and _is_entry_active(entry, tick)]


def near_danger(engine, uid: str, x: float, y: float, radius: float = READ_RADIUS) -> bool:
    return any(math.hypot(float(e["x"]) - x, float(e["y"]) - y) <= radius for e in places(engine, uid))


def danger_pressure(engine, uid: str, x: float, y: float, radius: float = READ_RADIUS) -> float:
    """0..1: the strongest remembered threat's salience, falling linearly to 0 at ``radius``."""
    best = 0.0
    for entry in places(engine, uid):
        d = math.hypot(float(entry["x"]) - x, float(entry["y"]) - y)
        if d <= radius:
            best = max(best, float(entry.get("salience", 0.65)) * (1.0 - d / radius))
    return best
