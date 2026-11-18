"""Tier 1 state matrix ``X`` (N x F) and personality matrix ``P`` (N x 16) built from the real engine, perception-bounded.

``build_features(world, services, residents)`` reads, per resident: the needs/state columns of the humans table (one vectorised read
for the whole batch), the resident record (pressures, goals, plans, relationships, personality), the pack, the roster anchors and need
sites (remembered places), the time block, and a *perceived* scene: other residents within ``RADIUS["social"]`` (one batched distance
matrix), predators within ``HAZARD_RADIUS``. Nothing about a resident outside that radius, and nothing in another resident's pack or
record, enters a row: changing such state leaves ``X`` unchanged (tested). Columns are the matrix menu's ``FEATURES`` in order, so the
placeholder weights and any later trained ``W`` apply unchanged; ``FEATURE_SCHEMA_VERSION`` versions the *definitions* in ``FEATURE_DEFS``
(version 1 was the synthetic builder in ``matrix.population_features``). The builder is read-only and not called by the engine.

``shadow_compare`` (bottom of the file) is the test-harness helper that runs a seeded headless engine, builds X and the affordance mask,
asks the matrix policy, and reports agreement with the Stage 1 survival rules. It is not wired into the engine tick and has no flag.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

import torch

from . import matrix
from .matrix import FEATURE_INDEX, FEATURES, F, P_DIM, TRAITS

FEATURE_SCHEMA_VERSION = 2
COLUMNS_SCHEMA = matrix.FEATURE_SCHEMA_VERSION      # the matrix weight files are keyed by this: same columns, same order

SOCIAL_RADIUS = 96.0       # = systems.affordance.config.RADIUS["social"]
HAZARD_RADIUS = 120.0
NEAR_SITE = 60.0           # a food/water site this close counts as "near"
PLACE_TOLERANCE = 8.0      # within this of the home/sleep anchor counts as "at home"
AT_STATION_TOLERANCE = 3.0  # = AT_WORK_TOLERANCE of the commission engine
KIN_CLOSENESS = 0.25       # relationship closeness at or above which a neighbour counts as kin/friend
SATURATION = 3.0           # neighbours / hostiles at which a count feature reaches 1
RANGE = {name: (0.0, 1.0) for name in FEATURES}
RANGE["closeness"] = (-1.0, 1.0)

FEATURE_DEFS = {
    "hunger": "humans.hunger / 100, clamped to [0,1]", "thirst": "humans.thirst / 100",
    "low_stamina": "1 - humans.stamina / 100", "low_hp": "1 - humans.hp / 100", "threat": "humans.threat / 100",
    "low_mood": "1 - humans.mood / 100",
    "fear": "record.pressures.fear_pressure", "vengeance": "record.pressures.vengeance_pressure",
    "security": "record.pressures.security_pressure", "curiosity": "record.pressures.curiosity_pressure",
    "loyalty": "record.pressures.loyalty_pressure",
    "is_night": "schedule time block: night 1, dusk 0.5, else 0 (EDEN_CALENDAR=1: 1 - light)", "at_home": "within PLACE_TOLERANCE of the sleep or home anchor",
    "at_station": "within AT_STATION_TOLERANCE of the work anchor",
    "near_food": "an edible in the pack, or the roster food site within NEAR_SITE, or a tensor food source within NEAR_SITE",
    "near_water": "the roster water site within NEAR_SITE, or a tensor water source within NEAR_SITE",
    "near_danger": "min(1, predators within HAZARD_RADIUS / SATURATION)",
    "near_kin": "min(1, perceived living residents with closeness >= KIN_CLOSENESS / SATURATION)",
    "near_stranger": "min(1, perceived living residents with closeness < KIN_CLOSENESS (or unknown) / SATURATION)",
    "has_food_item": "an edible kind in the pack", "plan_active": "an active plan in the record",
    "plan_step_failed": "planning_state.review_needed", "goal_urgency": "max priority of the active goals",
    "closeness": "closeness to the nearest perceived living resident, in [-1,1] (0 if none)",
    "rival": "the nearest perceived living resident carries the 'rival' tag", "one": "constant 1",
}
assert tuple(FEATURE_DEFS) == FEATURES, "FEATURE_DEFS must list exactly the matrix FEATURES, in order"


@dataclass
class FeatureBatch:
    ids: list
    X: torch.Tensor                 # N x F float64
    P: torch.Tensor                 # N x 16 float64
    alive: torch.Tensor             # N bool (False: unknown or dead resident; its scene and record columns are 0)
    tick: int
    schema: int = FEATURE_SCHEMA_VERSION
    timing_ms: dict = field(default_factory=dict)

    def row(self, resident_id: str) -> dict:
        i = self.ids.index(resident_id)
        return {name: float(self.X[i, j]) for j, name in enumerate(FEATURES)}


def _column(table, name: str) -> torch.Tensor:
    col = table.columns.get(name)
    if col is None:
        return torch.zeros(table.tensor.shape[0], dtype=torch.float64)
    return table.tensor[:, col].to(torch.float64)


def _time_block_value(tick: int) -> float:
    from harness import calendar as _calendar
    if _calendar.calendar_enabled():          # EDEN_CALENDAR=1: the column follows the light curve (0 at noon .. ~0.95 at night); flag off: the block body below, bit-identical
        return float(min(1.0, max(0.0, 1.0 - _calendar.now(int(tick)).light)))
    from systems.schedule.resolver import tick_to_time_block
    block = tick_to_time_block(int(tick))
    return 1.0 if block == "night" else 0.5 if block == "dusk" else 0.0


def build_features(world, services, residents: list) -> FeatureBatch:
    """Build X and P for ``residents`` (stable ids), in that order. Unknown or dead residents get a row with only the constant (and
    the tensor-derived needs for a dead one), ``alive`` False."""
    from systems.affordance import config as aff
    began = time.perf_counter()
    table = world.table("humans")
    n = len(residents)
    slots = [table.slot_of(h) for h in residents]
    known = torch.tensor([s is not None for s in slots], dtype=torch.bool)
    rows = torch.tensor([s if s is not None else 0 for s in slots], dtype=torch.long)
    X = torch.zeros((n, F), dtype=torch.float64)
    P = torch.full((n, P_DIM), matrix.DEFAULT_TRAIT, dtype=torch.float64)
    if n == 0:
        return FeatureBatch([], X, P, torch.zeros(0, dtype=torch.bool), int(world.tick))

    # -- vectorised: needs, positions, who is near whom ---------------------------------------------------------------
    hp_all = _column(table, "hp")
    live_all = table.live_mask() & (hp_all > 0)
    cols = {name: _column(table, name)[rows] for name in ("hunger", "thirst", "stamina", "hp", "threat", "mood")}
    X[:, FEATURE_INDEX["hunger"]] = (cols["hunger"] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["thirst"]] = (cols["thirst"] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["low_stamina"]] = (1.0 - cols["stamina"] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["low_hp"]] = (1.0 - cols["hp"] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["threat"]] = (cols["threat"] / 100.0).clamp(0, 1)
    X[:, FEATURE_INDEX["low_mood"]] = (1.0 - cols["mood"] / 100.0).clamp(0, 1)
    X[~known] = 0.0
    alive = known & live_all[rows]
    xs, ys = _column(table, table.pos_cols[0]), _column(table, table.pos_cols[1])
    px, py = xs[rows], ys[rows]
    dist = torch.sqrt((px[:, None] - xs[None, :]) ** 2 + (py[:, None] - ys[None, :]) ** 2)            # N x all humans
    self_mask = torch.zeros_like(dist, dtype=torch.bool)
    self_mask[torch.arange(n), rows] = True
    seen = (dist <= SOCIAL_RADIUS) & live_all[None, :] & ~self_mask & alive[:, None]
    timing = {"vectorised": (time.perf_counter() - began) * 1000.0}

    # -- per resident: record, pack, places, perceived neighbours ---------------------------------------------------------
    tick = int(world.tick)
    night = _time_block_value(tick)
    traits = []
    for i, human in enumerate(residents):
        record = services.record(human) if known[i] else None
        traits.append(dict(((record or {}).get("personality") or {}).get("traits", {})))
        X[i, FEATURE_INDEX["one"]] = 1.0
        if not bool(alive[i]):
            continue
        x, y = float(px[i]), float(py[i])
        X[i, FEATURE_INDEX["is_night"]] = night
        record = record or {}
        pressures = record.get("pressures") or {}
        for feat, key in (("fear", "fear_pressure"), ("vengeance", "vengeance_pressure"), ("security", "security_pressure"),
                          ("curiosity", "curiosity_pressure"), ("loyalty", "loyalty_pressure")):
            X[i, FEATURE_INDEX[feat]] = min(1.0, max(0.0, float(pressures.get(key, 0.0))))
        anchors, sites, pack = services.anchors(human), services.sites(human), services.inventory(human)
        for key in ("sleep", "home"):
            a = anchors.get(key)
            if a is not None and math.hypot(a.x - x, a.y - y) <= PLACE_TOLERANCE:
                X[i, FEATURE_INDEX["at_home"]] = 1.0
        work = anchors.get("work")
        if work is not None and math.hypot(work.x - x, work.y - y) <= AT_STATION_TOLERANCE:
            X[i, FEATURE_INDEX["at_station"]] = 1.0
        has_food = any(pack.get(k, 0) >= 1 for k in aff.EDIBLE_ITEMS)
        X[i, FEATURE_INDEX["has_food_item"]] = 1.0 if has_food else 0.0
        near_food = has_food
        for kind, flag in (("food", "near_food"), ("water", "near_water")):
            site = sites.get(kind)
            near = (site is not None and math.hypot(site.x - x, site.y - y) <= NEAR_SITE) or \
                   bool(services.typed_resources(kind, x, y, NEAR_SITE))
            if flag == "near_food":
                near_food = near_food or near
            else:
                X[i, FEATURE_INDEX[flag]] = 1.0 if near else 0.0
        X[i, FEATURE_INDEX["near_food"]] = 1.0 if near_food else 0.0
        X[i, FEATURE_INDEX["near_danger"]] = min(1.0, services.hostile_count(x, y, HAZARD_RADIUS) / SATURATION)
        relationships = record.get("relationships") or {}
        kin = strangers = 0
        nearest, nearest_d = None, float("inf")
        for j in seen[i].nonzero(as_tuple=False).flatten().tolist():
            other = table.ids[j]
            if other is None:
                continue
            closeness = float((relationships.get(other) or {}).get("closeness", 0.0)) if other in relationships else None
            if closeness is not None and closeness >= KIN_CLOSENESS:
                kin += 1
            else:
                strangers += 1
            d = float(dist[i, j])
            if d < nearest_d or (d == nearest_d and str(other) < str(nearest)):
                nearest, nearest_d = other, d
        X[i, FEATURE_INDEX["near_kin"]] = min(1.0, kin / SATURATION)
        X[i, FEATURE_INDEX["near_stranger"]] = min(1.0, strangers / SATURATION)
        if nearest is not None:
            relation = relationships.get(nearest) or {}
            X[i, FEATURE_INDEX["closeness"]] = max(-1.0, min(1.0, float(relation.get("closeness", 0.0))))
            X[i, FEATURE_INDEX["rival"]] = 1.0 if "rival" in (relation.get("tags") or []) else 0.0
        plans = [p for p in (record.get("plans") or []) if str(p.get("status", "active")) == "active"]
        X[i, FEATURE_INDEX["plan_active"]] = 1.0 if plans else 0.0
        X[i, FEATURE_INDEX["plan_step_failed"]] = 1.0 if (record.get("planning_state") or {}).get("review_needed") else 0.0
        goals = [float(g.get("priority", 0.0)) for g in (record.get("goals") or []) if str(g.get("status", "active")) == "active"]
        X[i, FEATURE_INDEX["goal_urgency"]] = min(1.0, max(goals)) if goals else 0.0
    P = matrix.trait_matrix(traits)
    timing["total"] = (time.perf_counter() - began) * 1000.0
    return FeatureBatch(list(residents), X, P, alive, tick, timing_ms=timing)


def check_ranges(batch: FeatureBatch) -> list:
    """Problems with a batch: non-finite values or values outside ``RANGE`` (empty list = fine)."""
    problems = []
    if not bool(torch.isfinite(batch.X).all()) or not bool(torch.isfinite(batch.P).all()):
        problems.append("non-finite value")
    for name, (lo, hi) in RANGE.items():
        col = batch.X[:, FEATURE_INDEX[name]]
        if bool((col < lo - 1e-12).any()) or bool((col > hi + 1e-12).any()):
            problems.append(f"{name} outside [{lo}, {hi}]")
    if bool(((batch.P < 0) | (batch.P > 1)).any()):
        problems.append("trait outside [0, 1]")
    if bool((batch.X[:, FEATURE_INDEX["one"]] != 1.0).any()):
        problems.append("constant column is not 1")
    return problems


# -- shadow mode: matrix vs the Stage 1 rules, in a test harness ---------------------------------------------------------------------
RULES_TASK_TO_MACRO = {"flee_target": "flee", "seek_shelter": "go_home", "fetch_water": "drink", "eat_food": "eat", "sleep": "sleep"}


def rules_macro(obs_row: dict, pack: dict, sheltered: bool) -> Optional[str]:
    """What the Stage 1 survival rules (``survival_task_specs``) would do for these raw values, as a Tier 1 macro; None when the
    rules have no opinion (nothing urgent)."""
    from systems.tasks.families.survival import survival_task_specs
    inventory = {"items": [{"kind": k, "quantity": q} for k, q in pack.items()]}
    specs = survival_task_specs({}, hunger=obs_row["hunger"], thirst=obs_row["thirst"], threat=obs_row["threat"],
                                stamina=obs_row["stamina"], hp=obs_row["hp"], sheltered=sheltered, personal_inventory=inventory)
    return RULES_TASK_TO_MACRO.get(specs[0]["task_kind"]) if specs else None


def shadow_compare(engine, *, ticks: int = 600, sample_every: int = 40, perturb_seed: Optional[int] = None, policy=None,
                   gate: Optional[matrix.GateConfig] = None) -> dict:
    """Run ``ticks`` engine steps; every ``sample_every`` ticks build X, the affordance mask and the matrix decision for every resident
    and compare with the Stage 1 survival rules. ``perturb_seed`` rewrites each resident's hunger/thirst/threat/stamina/hp from a seeded
    generator before each sample (stress states; modifies the engine, so use it only on a throwaway headless engine).

    Returns a JSON-serialisable report: agreement where the rules had an opinion, a confusion table, what the matrix chose when the
    rules were silent, how many rows would escalate through the gate, and timing per stage.
    """
    import genesis_config as cfg
    import numpy as np
    from harness.adapter import EngineWorld
    from systems.affordance import AffordanceEngine, EngineServices
    world, services = EngineWorld(engine, seed=0), EngineServices(engine)
    aff = AffordanceEngine(world, services)
    policy = policy or matrix.MatrixPolicy.initial()
    gate = gate or matrix.GateConfig()
    residents = [u for u in engine._human_uid_by_slot if u]
    rng = np.random.default_rng(perturb_seed) if perturb_seed is not None else None
    samples = agree = spoke = escalate = infeasible = 0
    confusion: dict = {}
    silent: dict = {}
    timing = {"features": [], "mask": [], "policy": []}
    problems: list = []
    h = engine.state.h_tensor
    for t in range(ticks + 1):
        if t % sample_every == 0:
            if rng is not None:
                for human in residents:
                    slot = engine._human_slot_for_id(human)
                    h[slot, cfg.HUNGER], h[slot, cfg.THIRST] = float(rng.uniform(0, 100)), float(rng.uniform(0, 100))
                    h[slot, cfg.THREAT] = float(rng.uniform(0, 100)) if rng.random() < 0.3 else 0.0
                    h[slot, cfg.H_STAMINA], h[slot, cfg.HP] = float(rng.uniform(5, 100)), float(rng.uniform(20, 100))
            batch = build_features(world, services, residents)
            timing["features"].append(batch.timing_ms["total"])
            problems += check_ranges(batch)
            began = time.perf_counter()
            M = aff.mask(residents)
            timing["mask"].append((time.perf_counter() - began) * 1000.0)
            began = time.perf_counter()
            result = policy.decide(batch.X, batch.P, M)
            significant = (batch.X[:, FEATURE_INDEX["threat"]] > 0.3) | (batch.X[:, FEATURE_INDEX["low_hp"]] > 0.5)
            escalated = policy.gate(result, significant, gate)
            timing["policy"].append((time.perf_counter() - began) * 1000.0)
            for i, human in enumerate(residents):
                samples += 1
                chosen = result.names()[i]
                slot = engine._human_slot_for_id(human)
                raw = {"hunger": float(h[slot, cfg.HUNGER]), "thirst": float(h[slot, cfg.THIRST]), "threat": float(h[slot, cfg.THREAT]),
                       "stamina": float(h[slot, cfg.H_STAMINA]), "hp": float(h[slot, cfg.HP])}
                rule = rules_macro(raw, services.inventory(human), bool(h[slot, cfg.H_SHELTER] > 0))
                escalate += int(bool(escalated[i]))
                if rule is None:
                    silent[chosen] = silent.get(chosen, 0) + 1
                    continue
                spoke += 1
                if not bool(M[i, matrix.ACTION_INDEX[rule]]):
                    infeasible += 1                       # the rules' choice is illegal for this resident (no source, ...)
                key = f"{rule}->{chosen}"
                confusion[key] = confusion.get(key, 0) + 1
                agree += int(chosen == rule)
        if t < ticks:
            engine.step()

    def stat(values):
        v = sorted(values)
        return {"n": len(v), "mean": round(sum(v) / len(v), 3), "p50": round(v[len(v) // 2], 3), "max": round(v[-1], 3)} if v else {}
    return {"ticks": ticks, "sample_every": sample_every, "perturb_seed": perturb_seed, "samples": samples, "rules_spoke": spoke,
            "agree": agree, "agreement": round(agree / spoke, 4) if spoke else None, "rules_choice_illegal": infeasible,
            "confusion": dict(sorted(confusion.items())), "matrix_choice_when_rules_silent": dict(sorted(silent.items())),
            "would_escalate": escalate, "feature_problems": sorted(set(problems)), "weights_hash": policy.weights_hash,
            "timing_ms": {k: stat(v) for k, v in timing.items()}}
