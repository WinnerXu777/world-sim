from __future__ import annotations

"""Deterministic candidate generation with probabilistic routine selection."""

import hashlib
import random

from typing import Any

from .catalog import DEFAULT_BLOCK_ROUTINES, ROUTINE_DEFS, TIME_BLOCKS, TRAIT_ROUTINE_WEIGHTS
from .lifecycle import ensure_schedule_state
from .schema import build_routine_record
from ..occupation.ops import occupation_routine_score_adjustment, occupation_schedule_block_preferences


DEFAULT_DAY_LENGTH_TICKS = 2400


def tick_to_time_block(tick: int, *, day_length_ticks: int = DEFAULT_DAY_LENGTH_TICKS, world=None) -> str:
    try:
        from harness import calendar as _calendar
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar as _calendar
    if world is not None and getattr(getattr(world, "engine", world), "_god_calendar_overrides", None):
        cal = _calendar.for_world(world)
        if cal is not _calendar.active():
            length = None if cal.name == "user" and day_length_ticks == DEFAULT_DAY_LENGTH_TICKS else day_length_ticks
            return cal.block_for_tick(tick, length)
    if _calendar.calendar_enabled():          # EDEN_CALENDAR=1: the long calendar answers when the caller asks for the default day length
        return _calendar.tick_to_time_block(tick, day_length_ticks=day_length_ticks)
    day_length = max(4, int(day_length_ticks))
    quarter = max(1, day_length // 4)
    local_tick = int(tick) % day_length
    index = min(len(TIME_BLOCKS) - 1, local_tick // quarter)
    return TIME_BLOCKS[index]


def _routine_score(kind: str, resident: dict[str, Any], *, context: dict[str, Any] | None = None) -> float:
    context = dict(context or {})
    time_block = str(context.get("time_block", ""))
    base = float(ROUTINE_DEFS.get(kind, {}).get("default_priority", 0.4))
    traits = dict((resident.get("personality", {}) or {}).get("traits", {}))
    for trait_name, weights in TRAIT_ROUTINE_WEIGHTS.items():
        base += float(traits.get(trait_name, 0.5)) * float(weights.get(kind, 0.0))

    if time_block:
        base += occupation_routine_score_adjustment(resident, kind, time_block=time_block)

    if not context.get("has_home", True) and kind in {"sleep", "stay_home", "return_home", "guard"}:
        base -= 0.18
    if bool(context.get("needs_water_hint", False)) and kind == "visit_water":
        base += 0.12
    if bool(context.get("settlement_present", False)) and kind in {"work_site", "socialize", "guard"}:
        base += 0.06
    if bool(context.get("night_watch", False)) and kind == "guard":
        base += 0.08
    return round(base, 4)


def _resident_schedule_bias(resident: dict[str, Any]) -> tuple[float, float, int]:
    profile = dict(resident.get("schedule_profile", {}))
    traits = dict((resident.get("personality", {}) or {}).get("traits", {}))

    stability = float(profile.get("stability", 0.82))
    novelty_bias = float(profile.get("novelty_bias", 0.1))

    discipline = float(traits.get("discipline", 0.5))
    caution = float(traits.get("caution", 0.5))
    curiosity = float(traits.get("curiosity", 0.5))
    sociability = float(traits.get("sociability", 0.5))

    stability += (discipline - 0.5) * 0.24
    stability += (caution - 0.5) * 0.12
    stability -= (curiosity - 0.5) * 0.16
    stability -= (sociability - 0.5) * 0.08

    novelty_bias += (curiosity - 0.5) * 0.18
    novelty_bias += (sociability - 0.5) * 0.08
    novelty_bias -= (discipline - 0.5) * 0.12
    novelty_bias -= (caution - 0.5) * 0.08

    commitment_window_ticks = max(30, int(profile.get("commitment_window_ticks", 240)))
    return (
        round(max(0.6, min(0.96, stability)), 3),
        round(max(0.02, min(0.28, novelty_bias)), 3),
        commitment_window_ticks,
    )


def _schedule_rng(resident: dict[str, Any], tick: int, *, time_block: str, commitment_window_ticks: int) -> random.Random:
    resident_id = str(
        resident.get("human_id")
        or resident.get("id")
        or resident.get("profile", {}).get("name")
        or resident.get("snapshot", {}).get("name")
        or "resident"
    )
    bucket = int(tick) // max(1, int(commitment_window_ticks))
    seed_material = f"{resident_id}|{bucket}|{time_block}|schedule"
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def _weighted_pick(
    candidates: list[dict[str, Any]],
    rng: random.Random,
    *,
    novelty_bias: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    weighted: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        priority = max(0.01, float(candidate.get("priority", 0.0)))
        if index == 0:
            weight = max(0.01, priority * (0.42 + novelty_bias))
        else:
            weight = max(0.01, priority * (1.0 + novelty_bias * (0.8 + index * 0.15)))
        enriched = dict(candidate)
        enriched["selection_weight"] = round(weight, 4)
        weighted.append(enriched)

    total_weight = sum(float(item["selection_weight"]) for item in weighted)
    roll = rng.random() * max(total_weight, 0.0001)
    cursor = 0.0
    chosen = weighted[0]
    for candidate in weighted:
        cursor += float(candidate["selection_weight"])
        if roll <= cursor:
            chosen = candidate
            break
    return chosen, weighted


def routine_candidates_for_tick(
    resident: dict[str, Any],
    tick: int,
    *,
    context: dict[str, Any] | None = None,
    day_length_ticks: int = DEFAULT_DAY_LENGTH_TICKS,
    world=None,
) -> list[dict[str, Any]]:
    ensure_schedule_state(resident, tick)
    time_block = tick_to_time_block(tick, day_length_ticks=day_length_ticks, world=world)
    context = dict(context or {})
    context["time_block"] = time_block
    profile = dict(resident.get("schedule_profile", {}))
    block_preferences = dict(profile.get("block_preferences", {}))
    occupation_kinds = occupation_schedule_block_preferences(resident, time_block=time_block)
    kinds = list(occupation_kinds or block_preferences.get(time_block) or DEFAULT_BLOCK_ROUTINES.get(time_block, ()))
    candidates: list[dict[str, Any]] = []
    for kind in kinds:
        candidates.append(
            {
                "kind": str(kind),
                "time_block": time_block,
                "priority": _routine_score(str(kind), resident, context=context),
                "label": str(ROUTINE_DEFS.get(str(kind), {}).get("label", kind)),
                "source": "occupation" if occupation_kinds else "schedule_default",
            }
        )
    candidates.sort(key=lambda item: float(item.get("priority", 0.0)), reverse=True)
    return candidates


def choose_schedule_routine(
    resident: dict[str, Any],
    tick: int,
    *,
    context: dict[str, Any] | None = None,
    day_length_ticks: int = DEFAULT_DAY_LENGTH_TICKS,
    world=None,
) -> dict[str, Any]:
    context = dict(context or {})
    if bool(context.get("survival_override", False)):
        return {"ok": False, "reason": "survival_override", "routine": None}
    if bool(context.get("active_plan_override", False)):
        return {"ok": False, "reason": "active_plan_override", "routine": None}
    if bool(context.get("urgent_override", False)):
        return {"ok": False, "reason": "urgent_override", "routine": None}

    candidates = routine_candidates_for_tick(resident, tick, context=context, day_length_ticks=day_length_ticks, world=world)
    if not candidates:
        return {"ok": False, "reason": "no_candidates", "routine": None}

    time_block = str(candidates[0]["time_block"])
    stability, novelty_bias, commitment_window_ticks = _resident_schedule_bias(resident)
    rng = _schedule_rng(resident, tick, time_block=time_block, commitment_window_ticks=commitment_window_ticks)
    consistency_probability = max(0.55, min(0.97, stability - novelty_bias * 0.35))
    selection_roll = rng.random()

    if len(candidates) == 1 or selection_roll <= consistency_probability:
        chosen = dict(candidates[0])
        weighted_candidates = [dict(candidate, selection_weight=round(float(candidate.get("priority", 0.0)), 4)) for candidate in candidates]
        selection_mode = "expected_routine"
    else:
        chosen, weighted_candidates = _weighted_pick(candidates, rng, novelty_bias=novelty_bias)
        selection_mode = "weighted_variation"

    routine = build_routine_record(
        str(chosen["kind"]),
        tick=tick,
        time_block=time_block,
        reason=str(context.get("reason", "schedule_default")),
        priority=float(chosen["priority"]),
        metadata={
            "selection_mode": selection_mode,
            "consistency_probability": round(consistency_probability, 3),
            "selection_roll": round(selection_roll, 4),
            "stability": stability,
            "novelty_bias": novelty_bias,
        },
    )
    return {
        "ok": True,
        "reason": "schedule_selected",
        "routine": routine,
        "candidates": weighted_candidates,
        "selection_mode": selection_mode,
        "consistency_probability": round(consistency_probability, 3),
        "selection_roll": round(selection_roll, 4),
        "stability": stability,
        "novelty_bias": novelty_bias,
        "commitment_window_ticks": commitment_window_ticks,
    }
