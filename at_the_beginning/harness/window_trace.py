"""1008 WS-D P5 proof: the window walk trace. A scripted resident walks a fixed route over the generated world; ``checkpoint`` reduces the window's state to
hashes that do not depend on where the window origin happens to be: the integrated set (absolute chunk coordinates and chunk hashes), the multiset of
entity ids with absolute positions, rows in use, and the number of ticks the walker stood inside a void box. Two runs with different starting origins must
agree on everything but ``origin`` and ``epoch``.
"""
from __future__ import annotations

import hashlib
import json

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg


def _digest(items) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def absolute_entities(manager) -> list:
    """Sorted (uid, abs x, abs y) of every row this window owns, positions rounded to 1e-2 units (the origin shifts by whole chunks)."""
    engine, size = manager.engine, float(manager.ring.chunk_units)
    ox, oy = manager.frame.origin
    m = engine.state.m_tensor
    rows = []
    for slot in sorted(manager.allocator.owned):
        rows.append([engine._entity_uid_by_slot[slot], round(ox * size + float(m[slot, cfg.CX]), 2), round(oy * size + float(m[slot, cfg.CY]), 2)])
    return sorted(rows)


def inside_void(manager, x: float, y: float) -> bool:
    return any(b["min"][0] <= x <= b["max"][0] and b["min"][1] <= y <= b["max"][1] for b in manager.void_boxes())


def checkpoint(manager, tick: int, void_hits: int) -> dict:
    integrated = sorted([c.x, c.y, s.sha256] for c, s in manager.chunks.items())
    return {"tick": tick, "origin": list(manager.frame.origin), "epoch": manager.epoch, "integrated": len(integrated),
            "integrated_hash": _digest(integrated), "rows": len(manager.allocator.owned), "entities_hash": _digest(absolute_entities(manager)),
            "deltas": len(manager.deltas), "void_hits": void_hits}


DISCRETE = ("tick", "integrated", "integrated_hash", "rows", "entities_hash", "deltas", "void_hits")
