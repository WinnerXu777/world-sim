"""1008 interim dormancy (P6 step 1; design: ``1008_dormancy_gap.md``): residents and animals whose chunk is not integrated do nothing.

Flag ``EDEN_WINDOW_DORMANCY=1`` (default off, needs ``EDEN_WINDOW=1``). A row is **dormant** when it is a live human (or an animal row), in
space 0, and the window-local chunk holding it is not in ``WindowManager.chunks``. ``refresh`` computes the two masks once per tick; ``Engine.step``
keeps dormant rows out of the registry's ``h_mask`` / ``a_mask`` (and ORs them back for the id sync), the escalation sweep skips them, and ``freeze`` /
``thaw`` write their rows back at the end of the tick so a dormant row is bit-identical from tick to tick whatever else touched it. When a row stops
being dormant ``wake`` applies the closed-form catch-up (``CATCH_UP``): needs advance by the elapsed ticks capped under the damage thresholds, age
advances exactly, stamina is full, threat is gone. Pure functions of the engine's tensors and the integrated set: nothing is saved but ``since``.
"""
from __future__ import annotations

import os
from typing import Optional

import torch

try:
    import genesis_config as cfg
    from . import calendar as _calendar
    from .numerics import window_enabled
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.harness import calendar as _calendar
    from at_the_beginning.harness.numerics import window_enabled

FLAG = "EDEN_WINDOW_DORMANCY"
CHUNK_UNITS = 256.0
KEY_SPAN = 8192
KEY_BIAS = 4096

# The wake rule, in one place (design section 4). Caps sit under the damage thresholds (hunger 90, thirst 100 in systems/survival).
GRACE_TICKS = 40            # outside the integrated chunks for this long before a row goes dormant (a new world integrates one chunk per tick)

CATCH_UP = {"hunger_cap": 80.0, "thirst_cap": 75.0, "stamina": 100.0, "threat": 0.0}


def enabled() -> bool:
    """Read at call time. Needs the window: dormancy is defined by the integrated set."""
    return os.environ.get(FLAG, "") == "1" and window_enabled()


def _key(cx, cy):
    return (cx + KEY_BIAS) * KEY_SPAN + (cy + KEY_BIAS)


def _integrated_keys(manager, device):
    ox, oy = manager.frame.origin
    return torch.tensor([_key(c.x - ox, c.y - oy) for c in manager.chunks], dtype=torch.long, device=device)


def _outside(manager, tensor, live, x_col, y_col):
    """Mask of ``live`` rows whose local chunk is not integrated."""
    if not bool(live.any()):
        return live
    cx = torch.floor(tensor[:, x_col].double() / CHUNK_UNITS).long().clamp(-KEY_BIAS + 1, KEY_BIAS - 1)
    cy = torch.floor(tensor[:, y_col].double() / CHUNK_UNITS).long().clamp(-KEY_BIAS + 1, KEY_BIAS - 1)
    inside = torch.isin(_key(cx, cy), _integrated_keys(manager, tensor.device))
    return live & ~inside


def refresh(engine) -> tuple:
    """``(dormant_h, dormant_a)`` for this tick, or ``(None, None)`` with the flag off or before the window exists. Also keeps
    ``engine._dormant_h`` / ``_dormant_a`` for the model plane, runs ``wake`` for rows that stopped being dormant and logs sleep/wake."""
    manager = getattr(engine, "_window", None)
    if not enabled() or manager is None:
        engine._dormant_h = engine._dormant_a = None
        return None, None
    h, m = engine.state.h_tensor, engine.state.m_tensor
    h_live = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.H_SPACE] == 0)
    a_live = torch.zeros(m.shape[0], dtype=torch.bool, device=m.device)
    for animal_type in cfg.ANIMAL_TYPES:
        a_live |= m[:, cfg.M_TYPE] == animal_type
    a_live &= m[:, cfg.M_SPACE] == 0
    for slot in manager.controlled_slots():
        h_live[slot] = False                                              # a player's own human is never dormant
    dormant_h = _outside(manager, h, h_live, cfg.X, cfg.Y)
    dormant_a = _outside(manager, m, a_live, cfg.CX, cfg.CY)
    since = engine.__dict__.setdefault("_dormant_since", {})            # uid -> tick the row went dormant
    log = engine.__dict__.setdefault("_dormancy_log", [])
    uids = engine._human_uid_by_slot
    outside = engine.__dict__.setdefault("_outside_since", {})           # uid -> tick the row was first seen outside (the grace period)
    seen = {uids[s]: s for s in dormant_h.nonzero(as_tuple=False).flatten().tolist() if uids[s]}
    for uid in [u for u in outside if u not in seen]:
        outside.pop(uid)
    for uid, slot in seen.items():
        if int(engine.tick) - outside.setdefault(uid, int(engine.tick)) < GRACE_TICKS and uid not in since:
            dormant_h[slot] = False
    now = {uids[s]: s for s in dormant_h.nonzero(as_tuple=False).flatten().tolist() if uids[s]}
    for uid, slot in now.items():
        if uid not in since:
            since[uid] = int(engine.tick)
            log.append((int(engine.tick), "sleep", uid))
    for uid in [u for u in since if u not in now]:
        started = since.pop(uid)
        slot = _slot_of(engine, uid)
        if slot is not None:
            wake(engine, slot, int(engine.tick) - started)
        log.append((int(engine.tick), "wake", uid))
    del log[:-256]
    engine._dormant_h, engine._dormant_a = dormant_h, dormant_a
    return dormant_h, dormant_a


def _slot_of(engine, uid) -> Optional[int]:
    try:
        return engine._human_uid_by_slot.index(uid)
    except ValueError:
        return None


def is_dormant(engine, slot: int) -> bool:
    """The predicate for other planes (the model plane's driver): True while the human in ``slot`` is dormant."""
    dormant = getattr(engine, "_dormant_h", None)
    return bool(dormant is not None and 0 <= int(slot) < dormant.shape[0] and dormant[int(slot)])


def dormant_animal(engine, slot: int) -> bool:
    dormant = getattr(engine, "_dormant_a", None)
    return bool(dormant is not None and 0 <= int(slot) < dormant.shape[0] and dormant[int(slot)])


def freeze(engine, dormant_h, dormant_a):
    """Copy the dormant rows (a handful) so ``thaw`` can put them back bit for bit at the end of the tick."""
    if dormant_h is None:
        return None
    h_rows, m_rows = dormant_h.nonzero(as_tuple=False).flatten(), dormant_a.nonzero(as_tuple=False).flatten()
    if not h_rows.numel() and not m_rows.numel():
        return None
    manager = getattr(engine, "_window", None)
    return (h_rows, engine.state.h_tensor[h_rows].clone(), [engine._human_uid_by_slot[s] for s in h_rows.tolist()],
            m_rows, engine.state.m_tensor[m_rows].clone(), [engine._entity_uid_by_slot[s] for s in m_rows.tolist()],
            tuple(manager.frame.origin) if manager is not None else (0, 0))


def thaw(engine, frozen) -> None:
    """Write the frozen rows back unless the row was legitimately removed or replaced during the tick (a death, a removal)."""
    if frozen is None:
        return
    h_rows, h_vals, h_uids, m_rows, m_vals, m_uids, origin = frozen
    h, m = engine.state.h_tensor, engine.state.m_tensor
    manager = getattr(engine, "_window", None)
    if manager is not None and tuple(manager.frame.origin) != origin:      # a re-base ran during the tick: the saved rows are in the old frame
        dx, dy = (origin[0] - manager.frame.origin[0]) * CHUNK_UNITS, (origin[1] - manager.frame.origin[1]) * CHUNK_UNITS
        h_vals[:, cfg.X] += dx
        h_vals[:, cfg.Y] += dy
        m_vals[:, cfg.CX] += dx
        m_vals[:, cfg.CY] += dy
    for i, slot in enumerate(h_rows.tolist()):
        if engine._human_uid_by_slot[slot] == h_uids[i] and float(h[slot, cfg.TYPE]) == float(cfg.AGENT_TYPE_HUMAN):
            h[slot] = h_vals[i]
    for i, slot in enumerate(m_rows.tolist()):
        if engine._entity_uid_by_slot[slot] == m_uids[i] and float(m[slot, cfg.M_TYPE]) > 0.0:
            m[slot] = m_vals[i]


def wake(engine, slot: int, elapsed: int) -> dict:
    """The catch-up for a human that was away ``elapsed`` ticks. Returns what changed (for tests and the log)."""
    h = engine.state.h_tensor
    elapsed = max(0, int(elapsed))
    before = {"hunger": float(h[slot, cfg.HUNGER]), "thirst": float(h[slot, cfg.THIRST]), "age": float(h[slot, cfg.H_AGE])}
    needs = _calendar.rate_scale("needs")
    hunger = before["hunger"] + cfg.HUNGER_TICK_RATE * needs * elapsed
    thirst = before["thirst"] + cfg.THIRST_TICK_RATE * needs * elapsed
    h[slot, cfg.HUNGER] = max(before["hunger"], min(hunger, CATCH_UP["hunger_cap"]))      # never lowered, never past the cap
    h[slot, cfg.THIRST] = max(before["thirst"], min(thirst, CATCH_UP["thirst_cap"]))
    h[slot, cfg.H_AGE] = before["age"] + _calendar.age_step() * elapsed
    h[slot, cfg.H_STAMINA] = max(float(h[slot, cfg.H_STAMINA]), CATCH_UP["stamina"])
    h[slot, cfg.THREAT] = CATCH_UP["threat"]
    return {"elapsed": elapsed, "hunger": float(h[slot, cfg.HUNGER]), "thirst": float(h[slot, cfg.THIRST]), "age": float(h[slot, cfg.H_AGE])}
