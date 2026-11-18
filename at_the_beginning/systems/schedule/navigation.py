from __future__ import annotations

"""Low-strength schedule navigation bias for ordinary resident routines."""

import hashlib
import math
import random
from typing import Any

import torch

try:
    import genesis_config as cfg
    from systems.occupation.resolver import occupation_preferred_place_tags
    from systems.perception import entity_unit_vector, nearest_geo_entity
    from systems.schedule.ops import choose_resident_schedule_routine, ensure_resident_schedule, schedule_refresh_due
    from systems.schedule.resolver import tick_to_time_block
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.systems.occupation.resolver import occupation_preferred_place_tags
    from at_the_beginning.systems.perception import entity_unit_vector, nearest_geo_entity
    from at_the_beginning.systems.schedule.ops import (
        choose_resident_schedule_routine,
        ensure_resident_schedule,
        schedule_refresh_due,
    )
    from at_the_beginning.systems.schedule.resolver import tick_to_time_block


PLACE_TAG_TYPES: dict[str, set[int]] = {
    "water": {cfg.M_LAKE, cfg.M_WELL, cfg.M_BEACH, cfg.M_FARM},
    "shore": {cfg.M_LAKE, cfg.M_BEACH},
    "dock": {cfg.M_LAKE, cfg.M_BEACH, cfg.M_VILLAGE},
    "field": {cfg.M_FARM, cfg.M_GRASS},
    "farm": {cfg.M_FARM, cfg.M_GRASS},
    "settlement": {cfg.M_HOUSE, cfg.M_VILLAGE, cfg.M_WELL, cfg.M_WALL},
    "forest": {cfg.M_FOREST},
    "grove": {cfg.M_FOREST, cfg.M_GRASS},
    "wild": {cfg.M_FOREST, cfg.M_GRASS, cfg.M_BEACH},
    "trail": {cfg.M_GRASS, cfg.M_BEACH},
    "gate": {cfg.M_WALL, cfg.M_VILLAGE},
    "wall": {cfg.M_WALL},
    "home": {cfg.M_HOUSE, cfg.M_VILLAGE},
    "hearth": {cfg.M_HOUSE, cfg.M_VILLAGE},
    "market": {cfg.M_VILLAGE, cfg.M_HOUSE},
    "road": {cfg.M_GRASS, cfg.M_BEACH, cfg.M_VILLAGE},
    "worksite": {cfg.M_HOUSE, cfg.M_VILLAGE, cfg.M_WALL, cfg.M_FARM},
    "quarry": {cfg.M_MOUNTAIN, cfg.M_BARREN},
}


ROUTINE_DEFAULT_TYPES: dict[str, set[int]] = {
    "sleep": {cfg.M_HOUSE, cfg.M_VILLAGE, cfg.M_WELL},
    "stay_home": {cfg.M_HOUSE, cfg.M_VILLAGE, cfg.M_WELL},
    "return_home": {cfg.M_HOUSE, cfg.M_VILLAGE, cfg.M_WELL},
    "visit_water": {cfg.M_LAKE, cfg.M_WELL, cfg.M_BEACH, cfg.M_FARM},
    "guard": {cfg.M_WALL, cfg.M_VILLAGE, cfg.M_HOUSE},
    "patrol": {cfg.M_WALL, cfg.M_VILLAGE, cfg.M_HOUSE},
    "socialize": {cfg.M_VILLAGE, cfg.M_HOUSE, cfg.M_WELL},
    "rest": {cfg.M_HOUSE, cfg.M_VILLAGE, cfg.M_WELL},
    "gather": {cfg.M_FOREST, cfg.M_GRASS, cfg.M_FARM, cfg.M_BEACH},
    "work_site": {cfg.M_HOUSE, cfg.M_VILLAGE, cfg.M_FARM, cfg.M_WALL},
    "wander_local": {cfg.M_GRASS, cfg.M_FOREST, cfg.M_BEACH, cfg.M_VILLAGE},
}


ROUTINE_WEIGHT: dict[str, float] = {
    "sleep": 0.88,
    "stay_home": 0.72,
    "return_home": 0.78,
    "visit_water": 0.82,
    "guard": 0.74,
    "patrol": 0.66,
    "socialize": 0.52,
    "rest": 0.42,
    "gather": 0.62,
    "work_site": 0.68,
    "wander_local": 0.46,
}


def _wander_vector(human_id: str, tick: int, *, time_block: str) -> tuple[float, float]:
    bucket = int(tick) // max(1, int(cfg.TICK_RATE_HZ * 6))
    seed_text = f"{human_id}|{time_block}|{bucket}|wander"
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    angle = rng.random() * math.tau
    return math.cos(angle), math.sin(angle)


def _routine_target_types(resident: dict[str, Any], routine_kind: str) -> set[int]:
    place_types: set[int] = set()
    for tag in occupation_preferred_place_tags(resident):
        place_types.update(PLACE_TAG_TYPES.get(str(tag), set()))
    routine_defaults = set(ROUTINE_DEFAULT_TYPES.get(str(routine_kind), set()))
    if routine_kind in {"gather", "work_site", "wander_local"} and place_types:
        return place_types | routine_defaults
    if place_types and routine_kind in {"visit_water", "guard", "patrol", "socialize", "rest"}:
        return place_types | routine_defaults
    return routine_defaults or place_types


def build_schedule_navigation_bias(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    resident_store: Any,
    human_ids_by_slot: list[str | None],
    tick: int,
    device: str,
    player_control_runtime: Any | None = None,
) -> dict[str, torch.Tensor]:
    bias = torch.zeros((h_tensor.shape[0], 2), dtype=h_tensor.dtype, device=device)
    if resident_store is None or not h_mask.any():
        return {"nav_schedule_bias": bias}

    for slot in torch.where(h_mask)[0].tolist():
        if player_control_runtime is not None and player_control_runtime.describe_human_slot(slot) is not None:
            continue
        if float(h_tensor[slot, cfg.ESCALATION_FLAG]) > 0.0:
            continue
        if float(h_tensor[slot, cfg.HUNGER]) >= cfg.FOOD_SEEK_THRESHOLD:
            continue
        if float(h_tensor[slot, cfg.THIRST]) >= cfg.WATER_SEEK_THRESHOLD:
            continue
        if float(h_tensor[slot, cfg.THREAT]) >= cfg.SHELTER_SEEK_THREAT:
            continue
        if float(h_tensor[slot, cfg.HP]) < 45.0 or float(h_tensor[slot, cfg.H_STAMINA]) < 20.0:
            continue

        human_id = human_ids_by_slot[slot] if 0 <= slot < len(human_ids_by_slot) else None
        if not human_id:
            continue
        resident = resident_store.get(human_id)
        if resident is None:
            continue
        ensure_resident_schedule(resident, tick)

        current_routine = dict((resident.get("schedule_state", {}) or {}).get("current_routine") or {})
        current_time_block = str(current_routine.get("time_block", "")).strip()
        time_block = tick_to_time_block(tick)
        has_active_plan = any(
            str(plan.get("status", "queued")) in {"active", "queued"}
            for plan in list(resident.get("plans", []))
        )
        if not current_routine or current_time_block != time_block or schedule_refresh_due(resident, tick):
            decision = choose_resident_schedule_routine(
                resident,
                tick,
                context={
                    "reason": "live_schedule",
                    "has_home": True,
                    "settlement_present": True,
                    "survival_override": False,
                    "active_plan_override": has_active_plan,
                    "urgent_override": False,
                },
            )
            if bool(decision.get("ok", False)):
                current_routine = dict(decision.get("routine") or {})
                resident_store.touch_resident(human_id)

        routine_kind = str(current_routine.get("kind", "")).strip()
        if not routine_kind:
            continue

        px = float(h_tensor[slot, cfg.X])
        py = float(h_tensor[slot, cfg.Y])
        weight = float(ROUTINE_WEIGHT.get(routine_kind, 0.0))
        if weight <= 0.0:
            continue

        target_types = _routine_target_types(resident, routine_kind)
        target_eid = nearest_geo_entity(
            m_tensor,
            px,
            py,
            type_filter=target_types or None,
            radius=220.0,
        )

        if target_eid != -1:
            ux, uy = entity_unit_vector(m_tensor, px, py, target_eid)
        elif routine_kind in {"wander_local", "patrol", "gather"}:
            ux, uy = _wander_vector(human_id, tick, time_block=time_block)
        else:
            continue

        bias[slot, 0] = float(ux) * weight
        bias[slot, 1] = float(uy) * weight

    return {"nav_schedule_bias": bias}
