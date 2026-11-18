from __future__ import annotations

import random
from typing import Any, Callable

import torch

try:
    from harness.calendar import rate_scale as _rate
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.calendar import rate_scale as _rate
try:
    from genesis_config import (
        CX,
        CY,
        M_FOREST,
        M_LAKE,
        M_SEA,
        M_TYPE,
        SCALE,
        TICKS_PER_YEAR,
        X,
        Y,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        CX,
        CY,
        M_FOREST,
        M_LAKE,
        M_SEA,
        M_TYPE,
        SCALE,
        TICKS_PER_YEAR,
        X,
        Y,
    )


ToolFn = Callable[..., dict[str, Any] | None]

WEATHER_WEIGHTS: dict[str, tuple[tuple[str, float], ...]] = {
    "spring": (
        ("clear", 0.22),
        ("rain", 0.32),
        ("wind", 0.16),
        ("storm", 0.12),
        ("humid", 0.18),
    ),
    "summer": (
        ("clear", 0.24),
        ("heat", 0.24),
        ("wind", 0.16),
        ("rain", 0.12),
        ("storm", 0.08),
        ("dry", 0.16),
    ),
    "autumn": (
        ("clear", 0.24),
        ("rain", 0.24),
        ("wind", 0.22),
        ("storm", 0.16),
        ("dry", 0.14),
    ),
    "winter": (
        ("clear", 0.20),
        ("cold", 0.34),
        ("wind", 0.24),
        ("storm", 0.12),
        ("dry", 0.10),
    ),
}

SEASON_MODIFIERS: dict[str, dict[str, float]] = {
    "spring": {"food_growth": 1.20, "water_growth": 1.15, "farm_growth": 1.20},
    "summer": {"food_growth": 1.00, "water_growth": 0.92, "farm_growth": 1.05},
    "autumn": {"food_growth": 0.92, "water_growth": 1.00, "farm_growth": 0.95},
    "winter": {"food_growth": 0.60, "water_growth": 0.82, "farm_growth": 0.55},
}

WEATHER_MODIFIERS: dict[str, dict[str, float]] = {
    "clear": {"food_growth": 1.00, "water_growth": 1.00, "farm_growth": 1.00},
    "rain": {"food_growth": 1.08, "water_growth": 1.45, "farm_growth": 1.15},
    "humid": {"food_growth": 1.10, "water_growth": 1.18, "farm_growth": 1.08},
    "storm": {"food_growth": 0.82, "water_growth": 1.28, "farm_growth": 0.72},
    "wind": {"food_growth": 0.95, "water_growth": 0.95, "farm_growth": 0.90},
    "heat": {"food_growth": 0.82, "water_growth": 0.74, "farm_growth": 0.78},
    "dry": {"food_growth": 0.68, "water_growth": 0.50, "farm_growth": 0.56},
    "cold": {"food_growth": 0.66, "water_growth": 0.84, "farm_growth": 0.60},
}


def season_for_tick(tick: int) -> str:
    """Quarters of the year (``harness.calendar``: 600-tick year flag off, 96000-tick year with EDEN_CALENDAR=1)."""
    try:
        from harness import calendar as _calendar
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar as _calendar
    return _calendar.season_for_tick(tick)


def ensure_nature_state(engine: Any, *, tick: int) -> dict[str, Any]:
    state = getattr(engine, "_nature_state", None)
    if not isinstance(state, dict):
        state = {}
        engine._nature_state = state
    if state:
        return state

    season = season_for_tick(tick)
    weather = _choose_weather(season)
    duration = int(round(random.randint(60, 110) * _rate("weather")))
    state.update(
        {
            "season": season,
            "weather": weather,
            "weather_started_tick": tick,
            "weather_ends_tick": tick + duration,
            "weather_duration_ticks": duration,
            "pending_event": None,
            "extreme_cooldown_until": 0,
            "next_ecology_tick": tick + 40,
            "last_event": None,
            "last_ecology": None,
            "history": [],
        }
    )
    state["modifiers"] = build_nature_modifiers(state)
    return state


def build_nature_modifiers(state: dict[str, Any]) -> dict[str, float]:
    season = str(state.get("season", "spring"))
    weather = str(state.get("weather", "clear"))
    season_mods = SEASON_MODIFIERS.get(season, SEASON_MODIFIERS["spring"])
    weather_mods = WEATHER_MODIFIERS.get(weather, WEATHER_MODIFIERS["clear"])
    return {
        "food_growth": season_mods["food_growth"] * weather_mods["food_growth"] * _rate("regrow"),
        "water_growth": season_mods["water_growth"] * weather_mods["water_growth"] * _rate("regrow"),
        "farm_growth": season_mods["farm_growth"] * weather_mods["farm_growth"] * _rate("farm_growth"),
    }


def advance_nature_cycle(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    engine: Any,
    device: str = "cpu",
    flood_tool_fn: ToolFn | None = None,
    storm_tool_fn: ToolFn | None = None,
    wildfire_tool_fn: ToolFn | None = None,
    drought_tool_fn: ToolFn | None = None,
) -> dict[str, Any]:
    """Advance season/weather state and occasionally trigger extreme weather."""
    tick = int(getattr(engine, "tick", 0))
    state = ensure_nature_state(engine, tick=tick)
    current_season = season_for_tick(tick)
    if current_season != state.get("season"):
        state["season"] = current_season

    if tick >= int(state.get("weather_ends_tick", 0)):
        weather = _choose_weather(current_season)
        duration = int(round(random.randint(60, 110) * _rate("weather")))
        state["weather"] = weather
        state["weather_started_tick"] = tick
        state["weather_duration_ticks"] = duration
        state["weather_ends_tick"] = tick + duration
        state["pending_event"] = _plan_extreme_event(
            h_tensor,
            m_tensor,
            h_mask=ctx["h_mask"],
            tick=tick,
            weather=weather,
            cooldown_until=int(state.get("extreme_cooldown_until", 0)),
        )
        _append_history(
            state,
            {
                "tick": tick,
                "kind": "weather",
                "season": current_season,
                "weather": weather,
                "duration": duration,
            },
        )

    state["modifiers"] = build_nature_modifiers(state)
    event_outcome = _maybe_execute_pending_event(
        ctx,
        h_tensor,
        m_tensor,
        state=state,
        tick=tick,
        device=device,
        flood_tool_fn=flood_tool_fn,
        storm_tool_fn=storm_tool_fn,
        wildfire_tool_fn=wildfire_tool_fn,
        drought_tool_fn=drought_tool_fn,
    )
    event_outcome["nature_state"] = snapshot_nature_state(state)
    return event_outcome


def snapshot_nature_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "season": str(state.get("season", "spring")),
        "weather": str(state.get("weather", "clear")),
        "weather_started_tick": int(state.get("weather_started_tick", 0)),
        "weather_ends_tick": int(state.get("weather_ends_tick", 0)),
        "weather_duration_ticks": int(state.get("weather_duration_ticks", 0)),
        "pending_event": dict(state.get("pending_event")) if isinstance(state.get("pending_event"), dict) else None,
        "extreme_cooldown_until": int(state.get("extreme_cooldown_until", 0)),
        "last_event": dict(state.get("last_event")) if isinstance(state.get("last_event"), dict) else None,
        "last_ecology": dict(state.get("last_ecology")) if isinstance(state.get("last_ecology"), dict) else None,
        "modifiers": dict(state.get("modifiers", {})),
        "history": list(state.get("history", [])),
    }


def _choose_weather(season: str) -> str:
    entries = WEATHER_WEIGHTS.get(season, WEATHER_WEIGHTS["spring"])
    roll = random.random()
    total = 0.0
    for weather, weight in entries:
        total += weight
        if roll <= total:
            return weather
    return entries[-1][0]


def _plan_extreme_event(
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    h_mask: torch.Tensor,
    tick: int,
    weather: str,
    cooldown_until: int,
) -> dict[str, Any] | None:
    if tick < cooldown_until:
        return None

    candidates: list[dict[str, Any]] = []
    water_slots = _entity_slots_for_types(m_tensor, {M_LAKE, M_SEA})
    forest_slots = _entity_slots_for_types(m_tensor, {M_FOREST})
    drought_slots = _entity_slots_for_types(m_tensor, {M_LAKE})

    if weather in {"rain", "storm", "humid"} and water_slots:
        if weather in {"rain", "storm"}:
            candidates.append({"name": "flood", "weight": 0.30, "trigger_in": int(round(random.randint(12, 36) * _rate("weather")))})
        if h_mask.any():
            human_slot = random.choice(torch.where(h_mask)[0].tolist())
            candidates.append(
                {
                    "name": "storm",
                    "weight": 0.35 if weather == "storm" else 0.18,
                    "trigger_in": int(round(random.randint(8, 28) * _rate("weather"))),
                    "center_x": float(h_tensor[human_slot, X]),
                    "center_y": float(h_tensor[human_slot, Y]),
                    "radius": 140.0,
                }
            )

    if weather in {"heat", "dry", "wind"}:
        if drought_slots:
            candidates.append(
                {
                    "name": "drought",
                    "weight": 0.28 if weather in {"heat", "dry"} else 0.14,
                    "trigger_in": int(round(random.randint(16, 40) * _rate("weather"))),
                    "target_slot": random.choice(drought_slots),
                }
            )
        if forest_slots:
            target_slot = random.choice(forest_slots)
            candidates.append(
                {
                    "name": "wildfire",
                    "weight": 0.26 if weather in {"heat", "dry"} else 0.16,
                    "trigger_in": int(round(random.randint(10, 34) * _rate("weather"))),
                    "center_x": float(m_tensor[target_slot, CX]),
                    "center_y": float(m_tensor[target_slot, CY]),
                    "radius": float(max(50.0, m_tensor[target_slot, SCALE] * 1.2)),
                }
            )

    if not candidates:
        return None

    total = sum(max(0.0, float(item["weight"])) for item in candidates)
    if total <= 0.0 or random.random() > min(0.65, total):
        return None

    roll = random.random() * total
    running = 0.0
    chosen = candidates[-1]
    for candidate in candidates:
        running += max(0.0, float(candidate["weight"]))
        if roll <= running:
            chosen = candidate
            break
    planned = dict(chosen)
    planned["trigger_tick"] = tick + int(planned.pop("trigger_in", 20))
    planned["planned_at"] = tick
    return planned


def _maybe_execute_pending_event(
    ctx: dict[str, Any],
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    *,
    state: dict[str, Any],
    tick: int,
    device: str,
    flood_tool_fn: ToolFn | None,
    storm_tool_fn: ToolFn | None,
    wildfire_tool_fn: ToolFn | None,
    drought_tool_fn: ToolFn | None,
) -> dict[str, Any]:
    pending = state.get("pending_event")
    if not isinstance(pending, dict):
        return {}
    if tick < int(pending.get("trigger_tick", tick + 1)):
        return {}

    event_name = str(pending.get("name", ""))
    result: dict[str, Any] = {}
    if event_name == "flood" and flood_tool_fn is not None:
        result = dict(flood_tool_fn(ctx, m_tensor, h_tensor, pop_count_ref=[0], device=device) or {})
    elif event_name == "storm" and storm_tool_fn is not None:
        result = dict(
            storm_tool_fn(
                ctx,
                h_tensor,
                center_x=float(pending.get("center_x", 0.0)),
                center_y=float(pending.get("center_y", 0.0)),
                radius=float(pending.get("radius", 140.0)),
                device=device,
            )
            or {}
        )
    elif event_name == "wildfire" and wildfire_tool_fn is not None:
        result = dict(
            wildfire_tool_fn(
                ctx,
                m_tensor,
                center_x=float(pending.get("center_x", 0.0)),
                center_y=float(pending.get("center_y", 0.0)),
                radius=float(pending.get("radius", 60.0)),
                device=device,
            )
            or {}
        )
    elif event_name == "drought" and drought_tool_fn is not None:
        target_slot = int(pending.get("target_slot", -1))
        entity_mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
        if 0 <= target_slot < entity_mask.shape[0]:
            entity_mask[target_slot] = True
        result = dict(drought_tool_fn(ctx, m_tensor, entity_mask=entity_mask) or {})

    state["pending_event"] = None
    state["extreme_cooldown_until"] = tick + int(round(random.randint(220, 360) * _rate("weather")))
    state["last_event"] = {"tick": tick, "name": event_name}
    _append_history(
        state,
        {
            "tick": tick,
            "kind": "extreme",
            "name": event_name,
        },
    )
    result["frame_dirty"] = True
    if result.get("map_dirty"):
        result["frame_dirty"] = True
    return result


def _entity_slots_for_types(m_tensor: torch.Tensor, allowed_types: set[int]) -> list[int]:
    mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
    for entity_type in allowed_types:
        mask |= m_tensor[:, M_TYPE] == float(entity_type)
    return torch.where(mask)[0].tolist()


def _append_history(state: dict[str, Any], record: dict[str, Any]) -> None:
    history = list(state.get("history", []))
    history.append(record)
    state["history"] = history[-8:]
