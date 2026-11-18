"""2.A2 wound recovery (``EDEN_WOUNDS=1``, default off; ``1008_instincts_wiring_gap.md`` step 3): a blow leaves a bleed that keeps costing health until it clots or is treated.

A post-step hook (``harness_wounds``) watches the human HP column. A drop of ``HIT_MIN`` or more in one tick is a hit (an animal's bite, a blow, a fall; the vitals - hunger, thirst,
cold - never take that much in a tick), so it needs no event from the code that dealt it. A hit adds ``BLEED_PER_HP`` per HP lost to the resident's ``bleed`` (HP per tick, capped at
``BLEED_CAP``) and queues ``human_wounded {damage, bleed}``; callbacks registered with ``on_hit`` (the danger ledger) see ``(engine, slot, uid, damage)``.

The bleed is advanced **in closed form on a cadence** (every ``CADENCE`` ticks, for the ticks since the record was last advanced; exact for any window, so a resident that was dormant
catches up on waking): it decays by half every ``HALF_LIFE`` ticks (half that indoors: rest and shelter clot a wound), costs ``b (1 - q^n) / (1 - q)`` HP over ``n`` ticks
(``q`` the per-tick decay) and raises infection by ``INFECTION_PER_HP`` of what it cost. ``n`` is scaled by the calendar's ``damage_recovery`` rate and the roster's ``needs_scale``
(a village whose needs run at 1.5 % bleeds in the same slow motion). ``instinct_heal`` keeps healing 0.3 HP a tick while fed, so a small wound is a scratch and only a bleed above that
rate, a starving resident, or a second blow is dangerous; an untreated deep wound can kill.

State lives in the resident record (``resident["wound"] = {"bleed", "tick"}``, saved with it) when the resident has one, and always in ``engine._wounds[uid]``; no column. ``treat``
clears the bleed (the model plane's ``treat_wound`` verb calls it); ``bleed_of`` / ``wounded_of`` are the readers for the Tier 1 feature ``wounded``. Dormant rows are skipped
(their record keeps its ``tick``, so the closed form covers the sleep when they wake, capped at ``MAX_ELAPSED``).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

import torch

FLAG = "EDEN_WOUNDS"
HIT_MIN = 4.0                 # HP lost in one tick that counts as a hit
BLEED_PER_HP = 0.02           # bleed (HP/tick) added per HP of the hit: a 15-HP bite bleeds 0.3/tick, which natural healing (0.3/tick) just cancels
BLEED_CAP = 3.0
HALF_LIFE = 100.0             # ticks for the bleed to halve (outdoors); an untreated bleed costs about 144 ticks of its initial rate in all
INDOOR_FACTOR = 2.0           # decay runs this many times faster indoors (shelter / interior space)
INFECTION_PER_HP = 0.5        # H_INFECTION points per HP the bleed cost
CADENCE = 20
MIN_BLEED = 0.01              # below this the wound is closed and the record is dropped
MAX_ELAPSED = 48000           # ticks of closed-form catch-up (two user-calendar days)
_HITS: list = []              # callbacks (engine, slot, uid, damage)


def enabled() -> bool:
    return os.environ.get(FLAG, "") == "1"


def on_hit(callback: Callable) -> None:
    if callback not in _HITS:
        _HITS.append(callback)


def off_hit(callback: Callable) -> None:
    if callback in _HITS:
        _HITS.remove(callback)


# ---- pure ----------------------------------------------------------------------------------------------------------------------------------------------------
def decay(half_life: float) -> float:
    """Per-tick multiplier for a bleed that halves every ``half_life`` ticks."""
    return 0.5 ** (1.0 / half_life)


def advance(bleed: float, ticks: float, half_life: float = HALF_LIFE) -> tuple:
    """(HP lost, new bleed) over ``ticks`` ticks, closed form: the sum of ``b q^k`` for k = 0..n-1 and ``b q^n``."""
    if bleed <= 0.0 or ticks <= 0.0:
        return 0.0, max(bleed, 0.0)
    q = decay(half_life)
    return bleed * (1.0 - q ** ticks) / (1.0 - q), bleed * q ** ticks


# ---- state ---------------------------------------------------------------------------------------------------------------------------------------------------
def _records(engine) -> dict:
    return engine.__dict__.setdefault("_wounds", {})


def _resident(engine, uid):
    store = getattr(engine, "resident_store", None)
    try:
        return None if store is None else store.get(uid)
    except Exception:  # noqa: BLE001 - a store without this resident keeps the engine-side record only
        return None


def record_of(engine, uid) -> Optional[dict]:
    """The wound record of ``uid`` (``{"bleed", "tick"}``) or None. Reads the resident record once for a uid the engine has not seen (a loaded world)."""
    records = _records(engine)
    if uid in records:
        return records[uid]
    resident = _resident(engine, uid)
    saved = None if resident is None else resident.get("wound")
    if isinstance(saved, dict) and float(saved.get("bleed", 0.0)) > MIN_BLEED:
        records[uid] = {"bleed": float(saved["bleed"]), "tick": int(saved.get("tick", engine.tick))}
        return records[uid]
    return None


def _mirror(engine, uid, record: Optional[dict]) -> None:
    resident = _resident(engine, uid)
    if resident is None:
        return
    if record is None:
        if "wound" in resident:
            del resident["wound"]
    else:
        resident["wound"] = {"bleed": round(record["bleed"], 4), "tick": int(record["tick"])}
    store = getattr(engine, "resident_store", None)
    if store is not None:
        store._mark_dirty(uid)


def bleed_of(engine, uid) -> float:
    record = record_of(engine, uid)
    return 0.0 if record is None else float(record["bleed"])


def wounded_of(engine, uid) -> bool:
    return bleed_of(engine, uid) > MIN_BLEED


def treat(engine, uid, strength: float = 1.0) -> bool:
    """Stop (``strength`` 1.0) or reduce the bleed of ``uid``; True when there was a wound. The record stays in the resident file only while the wound is open."""
    record = record_of(engine, uid)
    if record is None:
        return False
    record["bleed"] *= max(0.0, 1.0 - float(strength))
    if record["bleed"] <= MIN_BLEED:
        _records(engine).pop(uid, None)
        _mirror(engine, uid, None)
    else:
        _mirror(engine, uid, record)
    return True


def hit(engine, slot: int, uid, damage: float) -> float:
    """Register a hit of ``damage`` HP on resident ``uid`` (called by the detector, and by tests / other systems that know better); returns the new bleed."""
    bleed = 0.0
    if enabled():                                                           # EDEN_DANGER alone sees hits (callbacks) without the bleed
        record = record_of(engine, uid) or {"bleed": 0.0, "tick": int(engine.tick)}
        if record["bleed"] <= MIN_BLEED:
            record["tick"] = int(engine.tick)
        record["bleed"] = bleed = min(BLEED_CAP, record["bleed"] + BLEED_PER_HP * float(damage))
        _records(engine)[uid] = record
        _mirror(engine, uid, record)
    engine._queue_event("human_wounded", uid, slot, damage=round(float(damage), 1), bleed=round(bleed, 3))
    for callback in list(_HITS):
        callback(engine, slot, uid, float(damage))
    return bleed


# ---- the hook ------------------------------------------------------------------------------------------------------------------------------------------------
def _scale(engine, h_tensor, slot: int) -> float:
    try:
        from . import calendar as _calendar
        from systems.roster.driver import needs_scale_vector
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar as _calendar
        from at_the_beginning.systems.roster.driver import needs_scale_vector
    scales = needs_scale_vector(engine, h_tensor)
    return float(_calendar.rate_scale("damage_recovery")) * (1.0 if scales is None else float(scales[slot]))


def _indoors(h_tensor, slot: int) -> bool:
    import genesis_config as cfg
    return bool(h_tensor[slot, cfg.H_SHELTER] > 0) or bool(h_tensor[slot, cfg.H_SPACE] != 0)


def step(engine) -> int:
    """One tick of the post-step hook: detect hits, then (on the cadence) advance the open wounds. Returns the number of hits seen."""
    import genesis_config as cfg
    h = engine.state.h_tensor
    alive = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.HP] > 0)
    dormant = getattr(engine, "_dormant_h", None)
    if dormant is not None:
        alive = alive & ~dormant[: h.shape[0]]
    hp = h[:, cfg.HP]
    previous = engine.__dict__.get("_wound_hp")
    hits = 0
    if previous is not None and previous.shape == hp.shape:
        for slot in ((previous - hp >= HIT_MIN) & alive & (previous > 0)).nonzero(as_tuple=False).flatten().tolist():
            uid = engine._human_uid_by_slot[slot]
            if uid:
                hit(engine, slot, uid, float(previous[slot] - hp[slot]))
                hits += 1
    if int(engine.tick) % CADENCE == 0 and _records(engine):
        _advance_all(engine, h, alive)
    engine._wound_hp = h[:, cfg.HP].clone()
    return hits


def _advance_all(engine, h_tensor, alive) -> None:
    import genesis_config as cfg
    now = int(engine.tick)
    slot_of = {uid: slot for slot, uid in enumerate(engine._human_uid_by_slot) if uid}
    for uid, record in list(_records(engine).items()):
        slot = slot_of.get(uid)
        if slot is None or float(h_tensor[slot, cfg.HP]) <= 0.0:
            _records(engine).pop(uid, None)                                  # dead or gone: the wound dies with the resident
            _mirror(engine, uid, None)
            continue
        if not bool(alive[slot]):
            continue                                                         # dormant: the record keeps its tick; the closed form covers the sleep
        elapsed = min(MAX_ELAPSED, max(0, now - int(record["tick"])))
        if elapsed <= 0:
            continue
        scale = _scale(engine, h_tensor, slot)
        half_life = HALF_LIFE / (INDOOR_FACTOR if _indoors(h_tensor, slot) else 1.0)
        lost, bleed = advance(record["bleed"], elapsed * scale, half_life)
        h_tensor[slot, cfg.HP] = max(0.0, float(h_tensor[slot, cfg.HP]) - lost)
        h_tensor[slot, cfg.H_INFECTION] = min(100.0, float(h_tensor[slot, cfg.H_INFECTION]) + INFECTION_PER_HP * lost)
        record["tick"] = now
        record["bleed"] = bleed
        if bleed <= MIN_BLEED:
            _records(engine).pop(uid, None)
            _mirror(engine, uid, None)
        else:
            _mirror(engine, uid, record)


def hook(engine) -> None:
    step(engine)
