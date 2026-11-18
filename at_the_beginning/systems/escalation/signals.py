from __future__ import annotations

"""Signal extraction for pressure-driven escalation routing."""

from typing import Any

import torch

try:
    import genesis_config as cfg
    from harness.numerics import spaces_enabled
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.harness.numerics import spaces_enabled


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _nearest_candidates(m_tensor, px: float, py: float, type_ids: set[int], space: int | None) -> list[int]:
    """Row ids, ascending, that the exact scan in ``_nearest_entity`` has to look at.

    The exact scan reads four scalars per live row. This narrows it with one vectorised pass: rows of the wanted types
    (and space), then only those whose squared distance is within a 1e-9 relative margin of the smallest one. The exact
    scan (strict ``<``, ascending ids) runs on that short list, so it returns the same row and distance, including ties:
    the squared distance and the Python distance are both monotone in the true distance and differ by about 1e-16
    relative, far below the margin, so the winner is always inside the list. Anything unusual (non-finite inputs or
    columns, non-int type ids) returns every live row, i.e. the original behaviour.
    """
    live = (m_tensor[:, cfg.M_TYPE] > 0).nonzero(as_tuple=False).flatten()
    everything = live.tolist()
    if len(everything) < 8:
        return everything
    try:
        qx, qy = float(px), float(py)
        wanted = sorted({t for t in type_ids if isinstance(t, int) and not isinstance(t, bool)})
    except (TypeError, ValueError):
        return everything
    if not (qx - qx == 0.0 and qy - qy == 0.0) or len(wanted) != len(type_ids):
        return everything
    rows = m_tensor.index_select(0, live)
    columns = (cfg.M_TYPE, cfg.CX, cfg.CY) if space is None else (cfg.M_TYPE, cfg.CX, cfg.CY, cfg.M_SPACE)
    if not bool(torch.isfinite(rows[:, list(columns)]).all()):
        return everything
    ok = torch.isin(rows[:, cfg.M_TYPE].long(), torch.tensor(wanted, dtype=torch.long))
    if space is not None:
        ok &= rows[:, cfg.M_SPACE].long() == int(space)
    if not bool(ok.any()):
        return []
    pick = live[ok]
    d2 = (rows[ok][:, cfg.CX].double() - qx) ** 2 + (rows[ok][:, cfg.CY].double() - qy) ** 2
    near = d2 <= float(d2.min()) * (1.0 + 1e-9)
    return pick[near].tolist()


def _nearest_entity(
    m_tensor,
    px: float,
    py: float,
    *,
    type_ids: set[int],
    space: int | None = None,
) -> tuple[int, float]:
    best_eid = -1
    best_dist = float("inf")
    for eid in _nearest_candidates(m_tensor, px, py, type_ids, space):
        if int(m_tensor[eid, cfg.M_TYPE]) not in type_ids:
            continue
        if space is not None and int(m_tensor[eid, cfg.M_SPACE]) != space:
            continue
        distance = _dist(px, py, float(m_tensor[eid, cfg.CX]), float(m_tensor[eid, cfg.CY]))
        if distance < best_dist:
            best_dist = distance
            best_eid = eid
    return best_eid, best_dist


def distress_proxy_from_row(row) -> float:
    return (
        float(row[cfg.HUNGER]) / 100.0
        + float(row[cfg.THREAT]) / 100.0
        + (100.0 - float(row[cfg.MOOD])) / 100.0
        + float(row[cfg.CRITICAL_HEALTH])
    )


def _recent_event_score(memory: dict[str, Any], tick: int, kinds: set[str], *, horizon_ticks: int) -> float:
    best = 0.0
    for entry in reversed(list(memory.get("recent_events", []))):
        kind = str(entry.get("kind", ""))
        if kind not in kinds:
            continue
        age = max(0, int(tick) - int(entry.get("tick", tick)))
        if age > horizon_ticks:
            continue
        best = max(best, 1.0 - (age / float(max(horizon_ticks, 1))))
    return round(best, 3)


def build_escalation_signals(
    engine: Any,
    slot: int,
    human_id: str,
    resident: dict[str, Any],
    *,
    escalated_flag: bool,
) -> dict[str, Any]:
    h_tensor = engine.state.h_tensor
    m_tensor = engine.state.m_tensor
    row = h_tensor[slot]
    px = float(row[cfg.X])
    py = float(row[cfg.Y])
    tick = int(engine.tick)
    own_space = int(row[cfg.H_SPACE]) if spaces_enabled() else None      # EDEN_SPACES: a resident only reads threats of its own space

    predator_eid, predator_dist = _nearest_entity(
        m_tensor,
        px,
        py,
        type_ids={cfg.M_TIGER, cfg.M_WOLF},
        space=own_space,
    )
    hazard_eid, hazard_dist = _nearest_entity(
        m_tensor,
        px,
        py,
        type_ids={cfg.M_LAVA, cfg.M_SEA},
        space=own_space,
    )

    memory = resident.get("memory", {})
    pressures = dict(resident.get("pressures", {}))
    goals = list(resident.get("goals", []))
    goal_state = dict(resident.get("goal_state", {}))
    primary_goal = goals[0] if goals else {}
    manual_interaction = None
    player_control = getattr(engine, "player_control", None)
    if player_control is not None:
        manual_interaction = player_control.recent_interactions_for_target(
            target_kind="human",
            target_id=human_id,
            current_tick=tick,
            horizon_ticks=max(1, int(cfg.TICK_RATE_HZ * 8)),
        )

    return {
        "tick": tick,
        "slot": int(slot),
        "human_id": human_id,
        "escalated_flag": bool(escalated_flag),
        "hp": float(row[cfg.HP]),
        "hunger": float(row[cfg.HUNGER]),
        "thirst": float(row[cfg.THIRST]),
        "threat": float(row[cfg.THREAT]),
        "mood": float(row[cfg.MOOD]),
        "stamina": float(row[cfg.H_STAMINA]),
        "critical_health": float(row[cfg.CRITICAL_HEALTH]),
        "distress_proxy": distress_proxy_from_row(row),
        "predator_eid": predator_eid,
        "predator_dist": predator_dist,
        "hazard_eid": hazard_eid,
        "hazard_dist": hazard_dist,
        "recent_attack_signal": _recent_event_score(
            memory,
            tick,
            {"attacked", "attack", "killed_by"},
            horizon_ticks=max(1, int(cfg.TICK_RATE_HZ * 6)),
        ),
        "recent_kin_signal": _recent_event_score(
            memory,
            tick,
            {"child_birth", "born_to_parent", "witnessed_death"},
            horizon_ticks=max(1, int(cfg.TICK_RATE_HZ * 20)),
        ),
        "recent_world_signal": _recent_event_score(
            memory,
            tick,
            {"world_decree"},
            horizon_ticks=max(1, int(cfg.TICK_RATE_HZ * 20)),
        ),
        "pressures": pressures,
        "goal_state": goal_state,
        "primary_goal": primary_goal,
        "goal_count": len(goals),
        "manual_interaction": manual_interaction,
    }
