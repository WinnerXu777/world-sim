"""2.A2 sleep pressure (``EDEN_SLEEP=1``, default off; USER-DEC-6 unblocked it): sleep debt that builds while awake, clears while asleep, and costs stamina and mood when high.

One registry instinct, ``instinct_sleep_pressure``, installed from ``engine_hooks`` at priority 34.2 (after ``instinct_temperature``, before ``instinct_heal``). The debt is a slow value:

    awake    debt += GAIN       per tick   (a rested resident reaches 100 after AWAKE_DAYS of a game day awake)
    asleep   debt -= RECOVER    per tick   (a night of sleep clears it: SLEEP_DAYS of a game day from 100)

``GAIN`` and ``RECOVER`` are measured against the calendar's day (``calendar.active().day_ticks``), so the same constants make a 12000-tick day and a 2400-tick day both feel like a
day; a resident who stays up all night under either calendar is tired the next morning. The debt is updated on a cadence of ``CADENCE`` ticks in closed form (elapsed ticks times
the rate, clamped to 0..100): a dormant resident keeps its tick, and the next update covers the time away as one stretch (asleep or awake as it is when it wakes, which is the
resident's own choice of rest; a dormant resident is never penalised for the time it was out of the window).

Asleep means: a roster resident standing at its ``sleep`` anchor (``systems.roster.driver.runtime(engine).at_anchor``), else a resident indoors (``H_SHELTER`` or ``H_SPACE``) during the
night block. Above ``TIRED`` (50) the debt drags stamina and mood every tick, in proportion to how far it is above ``TIRED``; asleep rows regain a little stamina and mood. Every rate is
multiplied by ``calendar.rate_scale("needs")`` and the roster's ``needs_scale`` of the resident, like the temperature instinct: the effect acts on residents through the vitals the
model plane already reads (stamina, mood); the Tier 1 feature ``tired`` reads ``tired_of`` / ``debt_of``.

State: ``engine._sleep[uid] = {"debt", "tick"}``, mirrored to the resident record as ``resident["sleep"]`` when the debt moved by a unit or more (so a save carries it: the resident
records are in the snapshot). All numbers are proposals; the survival scenario tunes them.
"""
from __future__ import annotations

import os
from typing import Optional

import torch

FLAG = "EDEN_SLEEP"
NAME = "instinct_sleep_pressure"
PRIORITY = 34.2

AWAKE_DAYS = 0.75                 # fraction of a game day awake until the debt is 100
SLEEP_DAYS = 0.30                 # fraction of a game day asleep to clear a debt of 100
TIRED = 50.0                      # debt above which stamina and mood suffer
EXHAUSTED = 85.0                  # debt above which the resident counts as exhausted (a reader's threshold)
RATE_STAMINA, RATE_MOOD = 0.03, 0.015       # per tick at a debt of 100 (proportional to debt over TIRED), before the scales
REST_STAMINA, REST_MOOD = 0.05, 0.01        # per tick regained while asleep, before the scales
CADENCE = 20
MAX_ELAPSED = 48000
MIRROR_STEP = 1.0


def enabled() -> bool:
    return os.environ.get(FLAG, "") == "1"


def _calendar():
    try:
        from . import calendar
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar
    return calendar


# ---- pure ----------------------------------------------------------------------------------------------------------------------------------------------------
def rates(day_ticks: float) -> tuple:
    """(gain, recover) per tick for a game day of ``day_ticks`` ticks."""
    return 100.0 / (AWAKE_DAYS * day_ticks), 100.0 / (SLEEP_DAYS * day_ticks)


def advance(debt: float, ticks: float, asleep: bool, day_ticks: float) -> float:
    """The debt after ``ticks`` ticks awake or asleep (closed form, clamped to 0..100)."""
    gain, recover = rates(day_ticks)
    return min(100.0, max(0.0, debt + ticks * (-recover if asleep else gain)))


def pressure(debt) -> torch.Tensor:
    """0..1: how far above ``TIRED`` the debt is."""
    return ((torch.as_tensor(debt, dtype=torch.float32) - TIRED) / (100.0 - TIRED)).clamp(0.0, 1.0)


# ---- state ---------------------------------------------------------------------------------------------------------------------------------------------------
def _records(engine) -> dict:
    return engine.__dict__.setdefault("_sleep", {})


def _resident(engine, uid):
    store = getattr(engine, "resident_store", None)
    try:
        return None if store is None else store.get(uid)
    except Exception:  # noqa: BLE001 - a store without this resident keeps the engine-side record only
        return None


def record_of(engine, uid, create: bool = False) -> Optional[dict]:
    """The sleep record of ``uid`` (``{"debt", "tick"}``). Reads the resident record once for a uid the engine has not seen (a loaded world)."""
    records = _records(engine)
    if uid in records:
        return records[uid]
    resident = _resident(engine, uid)
    saved = None if resident is None else resident.get("sleep")
    if isinstance(saved, dict):
        records[uid] = {"debt": float(saved.get("debt", 0.0)), "tick": int(saved.get("tick", engine.tick)), "mirrored": float(saved.get("debt", 0.0))}
        return records[uid]
    if create:
        records[uid] = {"debt": 0.0, "tick": int(engine.tick), "mirrored": 0.0}
        return records[uid]
    return None


def _mirror(engine, uid, record: dict) -> None:
    if abs(record["debt"] - record.get("mirrored", 0.0)) < MIRROR_STEP:
        return
    resident = _resident(engine, uid)
    if resident is None:
        return
    resident["sleep"] = {"debt": round(record["debt"], 2), "tick": int(record["tick"])}
    record["mirrored"] = record["debt"]
    store = getattr(engine, "resident_store", None)
    if store is not None:
        store._mark_dirty(uid)


def debt_of(engine, uid) -> float:
    """The sleep debt (0..100) of resident ``uid`` as of the last update (0.0 with the flag off or before the first tick)."""
    record = record_of(engine, uid)
    return 0.0 if record is None else float(record["debt"])


def tired_of(engine, uid) -> bool:
    return debt_of(engine, uid) > TIRED


def exhausted_of(engine, uid) -> bool:
    return debt_of(engine, uid) >= EXHAUSTED


def asleep_rows(engine, h_tensor: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """bool [H]: rows of ``mask`` that are asleep this tick (see the module docstring)."""
    import genesis_config as cfg
    calendar = _calendar()
    night = calendar.tick_to_time_block(int(engine.tick)) == "night"
    indoors = (h_tensor[:, cfg.H_SHELTER] > 0) | (h_tensor[:, cfg.H_SPACE] != 0)
    asleep = indoors & mask if night else torch.zeros_like(mask)
    try:
        try:
            from systems.roster.driver import runtime
        except ImportError:  # pragma: no cover - package import fallback
            from at_the_beginning.systems.roster.driver import runtime
        at_anchor = runtime(engine).at_anchor
    except Exception:  # noqa: BLE001 - a world without a roster has no anchors
        at_anchor = {}
    for uid, key in at_anchor.items():
        if key == "sleep":
            slot = _slot_of(engine, uid)
            if slot is not None and bool(mask[slot]):
                asleep[slot] = True
    return asleep


def _slot_of(engine, uid) -> Optional[int]:
    try:
        return engine._human_uid_by_slot.index(uid)
    except ValueError:
        return None


# ---- the instinct --------------------------------------------------------------------------------------------------------------------------------------------
def _scales(engine, h_tensor: torch.Tensor) -> torch.Tensor:
    try:
        from systems.roster.driver import needs_scale_vector
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.systems.roster.driver import needs_scale_vector
    scale = torch.full((h_tensor.shape[0],), float(_calendar().rate_scale("needs")), dtype=torch.float32, device=h_tensor.device)
    per_resident = needs_scale_vector(engine, h_tensor)
    return scale if per_resident is None else scale * per_resident.to(scale.device).float()


def update(engine, h_tensor: torch.Tensor, mask: torch.Tensor) -> int:
    """The cadence step: move every live, non-dormant resident's debt to now and refresh the per-slot vector the per-tick effects read. Returns the residents updated."""
    now = int(engine.tick)
    day_ticks = float(_calendar().active().day_ticks)
    asleep = asleep_rows(engine, h_tensor, mask)
    vector = engine.__dict__.get("_sleep_debt_vec")
    if vector is None or vector.shape[0] != h_tensor.shape[0]:
        vector = torch.zeros(h_tensor.shape[0], dtype=torch.float32, device=h_tensor.device)
        engine._sleep_debt_vec = vector
    count = 0
    for slot in mask.nonzero(as_tuple=False).flatten().tolist():
        uid = engine._human_uid_by_slot[slot]
        if not uid:
            continue
        record = record_of(engine, uid, create=True)
        elapsed = min(MAX_ELAPSED, max(0, now - int(record["tick"])))
        if elapsed > 0:
            record["debt"] = advance(record["debt"], elapsed, bool(asleep[slot]), day_ticks)
            record["tick"] = now
            _mirror(engine, uid, record)
        vector[slot] = record["debt"]
        count += 1
    engine._sleep_asleep = asleep
    return count


def apply(engine, h_tensor: torch.Tensor, mask: torch.Tensor) -> dict:
    """One tick of effects on the rows of ``mask``: the drag of the debt, the small recovery of sleep."""
    import genesis_config as cfg
    if int(engine.tick) % CADENCE == 0 or "_sleep_debt_vec" not in engine.__dict__:
        update(engine, h_tensor, mask)
    debt = engine._sleep_debt_vec
    scale = _scales(engine, h_tensor)
    asleep = engine.__dict__.get("_sleep_asleep")
    drag = torch.where(mask, pressure(debt), torch.zeros_like(debt))
    if bool((drag > 0).any()):
        h_tensor[:, cfg.H_STAMINA] = (h_tensor[:, cfg.H_STAMINA] - RATE_STAMINA * drag * scale).clamp(0.0, 100.0)
        h_tensor[:, cfg.MOOD] = (h_tensor[:, cfg.MOOD] - RATE_MOOD * drag * scale).clamp(0.0, 100.0)
    if asleep is not None and asleep.shape == mask.shape and bool((asleep & mask).any()):
        resting = (asleep & mask).float()
        h_tensor[:, cfg.H_STAMINA] = (h_tensor[:, cfg.H_STAMINA] + REST_STAMINA * resting * scale).clamp(0.0, 100.0)
        h_tensor[:, cfg.MOOD] = (h_tensor[:, cfg.MOOD] + REST_MOOD * resting * scale).clamp(0.0, 100.0)
    state = {"tick": int(engine.tick), "drag": drag}
    engine._sleep_state = state
    return state


def instinct_sleep_pressure(ctx: dict, h_tensor: torch.Tensor, **kwargs) -> None:
    engine = ctx.get("engine")
    if engine is None or not ctx["h_mask"].any():
        return
    apply(engine, h_tensor, ctx["h_mask"])


def install(engine) -> bool:
    """Register ``instinct_sleep_pressure`` once (idempotent; a new world re-registers because ``reset_world`` rebuilds the registry from the defaults)."""
    if any(entry["fn"] is instinct_sleep_pressure for entry in engine._registry):
        return False
    engine.register(instinct_sleep_pressure, priority=PRIORITY)
    return True
