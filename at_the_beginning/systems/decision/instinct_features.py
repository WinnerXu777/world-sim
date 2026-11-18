"""Tier 1 instinct features: cold, hot, wounded, fear-of-a-remembered-danger, tired, dark, grief, tension, curious, thrifty, as an additive score block (``INSTINCT_SCHEMA_VERSION`` 3: v1 had the first four columns, v2 appended ``tired`` and ``dark``, v3 appends the four of ``EDEN_EMOTION``).

The base matrix keeps its ``F`` columns and its shipped weights (v1 prior, v2 trained): their schema, hash and the flag-off scores are untouched. This module adds a *separate*
versioned block ``E`` (N x ``len(FEATURES)``) read from 9d882a's instinct readers (``harness/temperature.py``, ``wounds.py``, ``danger.py``), each column live only while its own flag is
on (``EDEN_TEMPERATURE`` -> cold, hot; ``EDEN_WOUNDS`` -> wounded; ``EDEN_DANGER`` -> fear_memory; ``EDEN_SLEEP`` -> tired; ``EDEN_DARKNESS`` -> dark; ``EDEN_EMOTION`` -> grief, tension, curious, thrifty), and a fixed weight table ``EXT_SPEC`` (E x K, rules-style hand weights, like the v1 prior).
``MatrixTier1.decide`` adds ``E @ W_ext`` to the macro scores when ``scores`` returns a tensor; with every flag off it returns ``None`` and the scores are the ones from before, bit for bit.

A retrained v3 that folds these columns into ``W`` would change ``F`` and the weight-file schema (``matrix.FEATURE_SCHEMA_VERSION``); that is a deliberate later step (a ``matrix.py`` edit
and ``train_matrix.py`` run on data from a world with the flags on). Until then the block is the versioned extension point.
"""
from __future__ import annotations

import hashlib
import json
import math

import torch

INSTINCT_SCHEMA_VERSION = 3
FEATURES = ("cold", "hot", "wounded", "fear_memory", "tired", "dark", "grief", "tension", "curious", "thrifty")
FLAGS = {"cold": "temperature", "hot": "temperature", "wounded": "wounds", "fear_memory": "danger", "tired": "sleep", "dark": "darkness", "grief": "emotion", "tension": "emotion", "curious": "emotion", "thrifty": "emotion"}
DEFS = {
    "cold": "temperature.cold_of(engine, slot) / COLD_SPAN, clamped to [0,1] (degrees under the comfort band)",
    "hot": "temperature.hot_of(engine, slot) / COLD_SPAN, clamped to [0,1]",
    "wounded": "min(1, wounds.bleed_of(engine, uid) / BLEED_FULL) (an open wound; 0 when closed)",
    "fear_memory": "danger.danger_pressure(engine, uid, x, y): the strongest remembered threat near the resident, salience falling to 0 at READ_RADIUS",
    "tired": "sleep.debt_of(engine, uid) / 100, clamped to [0,1] (the sleep debt; the harness's own tired line is 50, exhausted 85)",
    "dark": "darkness.unease_of(engine, slot): the unease (0..1) felt on the last tick",
    "grief": "emotion.grief_level(record, tick, day): the mourning level now (0..1), fading over three game days",
    "tension": "emotion.tension(record): the strongest jealous tension (0..1)",
    "curious": "the curiosity drive of the record (0..1)",
    "thrifty": "the thrift drive of the record (0..1; 1 = hoarding, 0 = giving freely)",
}
COLD_SPAN = 20.0           # degrees of deficit at which the feature is 1
BLEED_FULL = 0.3           # a 15-hp bite bleeds 0.3 hp/tick: that is "fully wounded"

# macro -> {feature: weight}. Hand weights in the spirit of ``matrix.MACRO_SPEC`` (not trained): the cold seek shelter, the hot rest, the wounded rest and call for help, the afraid keep away.
EXT_SPEC = {
    "go_home": {"cold": 1.6, "hot": 0.8, "wounded": 1.0, "fear_memory": 0.8, "tired": 0.8, "dark": 1.4, "grief": 0.4, "curious": -0.6},
    "rest": {"cold": 0.3, "hot": 0.5, "wounded": 1.5, "tired": 1.6, "dark": 0.4, "grief": 1.0, "curious": -0.4},
    "sleep": {"cold": 0.2, "tired": 2.4, "dark": 0.6},
    "drink": {"hot": 1.0},
    "socialise": {"cold": 0.2, "wounded": -0.8, "tired": -0.6, "dark": 0.3, "grief": 0.6, "tension": -0.5, "thrifty": -0.2},
    "work_at_station": {"cold": -0.6, "wounded": -1.5, "fear_memory": -0.5, "tired": -1.2, "dark": -0.8, "grief": -0.8},
    "gather": {"cold": -0.4, "wounded": -0.5, "fear_memory": -0.8, "tired": -0.6, "dark": -0.8, "thrifty": 0.4},
    "explore": {"cold": -1.0, "hot": -0.5, "wounded": -1.5, "fear_memory": -1.5, "tired": -1.0, "dark": -1.5, "grief": -1.0, "curious": 1.6},
    "ask_for_help": {"wounded": 1.2},
    "hide": {"fear_memory": 0.5, "dark": 0.3, "grief": 0.2},
    "flee": {"fear_memory": 0.4, "wounded": 0.3},
    "help": {"wounded": -0.5, "tension": -0.4, "thrifty": -0.8},
    "trade": {"thrifty": 0.6},
    "avoid": {"fear_memory": 1.2, "tension": 0.8},
}


def active() -> tuple:
    """The columns that are live right now (their flag is on); empty with every flag off."""
    from harness import danger, darkness, sleep, temperature, wounds
    from systems import emotion
    on = {"temperature": temperature.enabled(), "wounds": wounds.enabled(), "danger": danger.enabled(), "sleep": sleep.enabled(), "darkness": darkness.enabled(), "emotion": emotion.enabled()}
    return tuple(name for name in FEATURES if on[FLAGS[name]])


def weights() -> torch.Tensor:
    """E x K float64 (K = the matrix menu); zero rows for features no macro uses."""
    from . import matrix
    W = torch.zeros((len(FEATURES), matrix.K), dtype=torch.float64)
    for macro, spec in EXT_SPEC.items():
        for feature, weight in spec.items():
            W[FEATURES.index(feature), matrix.ACTION_INDEX[macro]] = weight
    return W


def schema_hash() -> str:
    return hashlib.sha256(json.dumps({"version": INSTINCT_SCHEMA_VERSION, "features": FEATURES, "spec": EXT_SPEC, "cold_span": COLD_SPAN, "bleed_full": BLEED_FULL},
                                     sort_keys=True).encode("utf-8")).hexdigest()[:16]


def build(engine, ids: list) -> torch.Tensor:
    """N x E float64 in [0,1]; the columns whose flag is off are 0 and are never read."""
    from harness import danger, darkness, sleep, temperature, wounds
    from systems import emotion
    live = set(active())
    X = torch.zeros((len(ids), len(FEATURES)), dtype=torch.float64)
    if not live:
        return X
    import genesis_config as cfg
    from systems.actions.gameclock import day_ticks
    day = day_ticks() if "grief" in live else 0
    h = engine.state.h_tensor
    for i, uid in enumerate(ids):
        slot = engine._human_slot_for_id(uid)
        if slot is None or slot < 0:
            continue
        if "cold" in live:
            X[i, 0] = min(1.0, max(0.0, temperature.cold_of(engine, slot) / COLD_SPAN))
            X[i, 1] = min(1.0, max(0.0, temperature.hot_of(engine, slot) / COLD_SPAN))
        if "wounded" in live:
            X[i, 2] = min(1.0, max(0.0, wounds.bleed_of(engine, uid) / BLEED_FULL))
        if "fear_memory" in live:
            X[i, 3] = min(1.0, max(0.0, danger.danger_pressure(engine, uid, float(h[slot, cfg.X]), float(h[slot, cfg.Y]))))
        if "tired" in live:
            X[i, 4] = min(1.0, max(0.0, sleep.debt_of(engine, uid) / 100.0))
        if "dark" in live:
            X[i, 5] = min(1.0, max(0.0, darkness.unease_of(engine, slot)))
        if live & {"grief", "tension", "curious", "thrifty"}:
            record = engine.resident_store.get(uid) or {}
            if "grief" in live:
                X[i, 6] = min(1.0, max(0.0, emotion.grief_level(record, int(engine.tick), day)))
                X[i, 7] = min(1.0, max(0.0, emotion.tension(record)))
                X[i, 8] = min(1.0, max(0.0, emotion.drive(record, "curiosity")))
                X[i, 9] = min(1.0, max(0.0, emotion.drive(record, "thrift")))
    return X


def scores(engine, ids: list):
    """``(E, E @ W_ext)`` for the batch, or ``None`` when no instinct flag is on (the caller then changes nothing)."""
    if not active():
        return None
    X = build(engine, ids)
    return X, X @ weights()
