"""1008 defend Phase 1 (design: ``1008_defend_phase1_gap.md``): restraint, the engine half of ``arrest_or_restrain``.

Flag ``EDEN_RESTRAINT=1`` (default off). ``H_RESTRAINED`` (human column 30) holds the ticks a human still stays restrained; 0 = free, which every row
written before this existed reads. While it is positive the human's position does not change: ``capture`` (start of ``Engine.step``) records the
positions of restrained humans and ``pin`` (after the id sync, before the post-step hooks, so ``apply_motion_limits`` records the pinned position and
never walks the human back) writes them back, shifted by the origin difference when a re-base ran mid-tick, and counts the column down by one. Needs,
damage, ageing, infection and death keep running. A dormant row is frozen whole by the dormancy thaw, counter included: restraint pauses while the chunk
is away. A controlled (player) human cannot be restrained; if one is claimed while restrained, it is freed.

The model plane (justice, guards) decides who and for how long through ``restrain`` / ``release``; the resolver skips the attacks of a restrained human.
"""
from __future__ import annotations

import os

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

FLAG = "EDEN_RESTRAINT"
CHUNK_UNITS = 256.0


def enabled() -> bool:
    """Read at call time."""
    return os.environ.get(FLAG, "") == "1"


def _controlled(engine, slot: int) -> bool:
    control = getattr(engine, "player_control", None)
    return control is not None and control.describe_human_slot(int(slot)) is not None


def _live_human(engine, slot: int) -> bool:
    h = engine.state.h_tensor
    return 0 <= int(slot) < h.shape[0] and float(h[int(slot), cfg.TYPE]) == float(cfg.AGENT_TYPE_HUMAN) and float(h[int(slot), cfg.HP]) > 0.0


def restrain(engine, slot: int, ticks: int) -> bool:
    """Hold the human in ``slot`` in place for ``ticks`` ticks (the longer of the current and the new value). False when the flag is off, the human is
    not alive, is a player's body, or ``ticks`` is not positive."""
    if not enabled() or int(ticks) <= 0 or not _live_human(engine, slot) or _controlled(engine, slot):
        return False
    h = engine.state.h_tensor
    h[int(slot), cfg.H_RESTRAINED] = max(float(h[int(slot), cfg.H_RESTRAINED]), float(int(ticks)))
    return True


def release(engine, slot: int) -> None:
    engine.state.h_tensor[int(slot), cfg.H_RESTRAINED] = 0.0


def is_restrained(engine, slot: int) -> bool:
    return enabled() and float(engine.state.h_tensor[int(slot), cfg.H_RESTRAINED]) > 0.0


def capture(engine):
    """Start of the tick: the restrained humans' rows and positions, or None when nothing is restrained or the flag is off."""
    if not enabled():
        return None
    h = engine.state.h_tensor
    rows = ((h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.H_RESTRAINED] > 0.0)).nonzero(as_tuple=False).flatten().tolist()
    rows = [s for s in rows if engine._human_uid_by_slot[s]]
    kept = []
    for slot in rows:
        if _controlled(engine, slot):
            h[slot, cfg.H_RESTRAINED] = 0.0                      # a player's body is never held
        else:
            kept.append(slot)
    if not kept:
        return None
    manager = getattr(engine, "_window", None)
    return {"slots": kept, "uids": [engine._human_uid_by_slot[s] for s in kept], "xy": h[kept][:, [cfg.X, cfg.Y]].clone(),
            "space": h[kept][:, cfg.H_SPACE].clone(), "origin": tuple(manager.frame.origin) if manager is not None else (0, 0)}


def pin(engine, captured) -> int:
    """Put the captured humans back where they stood at the start of the tick and count their restraint down. Returns how many were held."""
    if captured is None:
        return 0
    h = engine.state.h_tensor
    manager = getattr(engine, "_window", None)
    dx = dy = 0.0
    if manager is not None and tuple(manager.frame.origin) != captured["origin"]:       # a re-base ran during the tick: the saved positions are in the old frame
        dx = (captured["origin"][0] - manager.frame.origin[0]) * CHUNK_UNITS
        dy = (captured["origin"][1] - manager.frame.origin[1]) * CHUNK_UNITS
    held = 0
    for index, slot in enumerate(captured["slots"]):
        if engine._human_uid_by_slot[slot] != captured["uids"][index] or float(h[slot, cfg.TYPE]) != float(cfg.AGENT_TYPE_HUMAN):
            continue                                              # died, removed or replaced during the tick
        x, y = captured["xy"][index].tolist()
        if float(captured["space"][index]) == 0.0:
            x, y = x + dx, y + dy
        h[slot, cfg.X], h[slot, cfg.Y] = x, y
        h[slot, cfg.H_RESTRAINED] = max(0.0, float(h[slot, cfg.H_RESTRAINED]) - 1.0)
        held += 1
    return held
