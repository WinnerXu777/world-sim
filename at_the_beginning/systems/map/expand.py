from __future__ import annotations

import random
from typing import Any, Callable

import torch

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

from .chunk_generation import build_frontier_profile, generate_frontier_feature_plan
from .create import create_forest_patch_feature, create_lake_feature, create_mountain_chain_feature, create_natural_feature_at


PointClampFn = Callable[[float, float], tuple[float, float]]
CreateObjectFn = Callable[..., int]
CreateScatteredObjectsFn = Callable[..., list[int]]
CreateLineObjectsFn = Callable[..., list[int]]
ResolveBuildSiteFn = Callable[..., tuple[float, float, int] | None]
EDGE_SEED_OFFSET = {
    "north": 11,
    "south": 23,
    "east": 37,
    "west": 53,
}


def frontier_edges_for_humans(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    trigger_margin: float = 96.0,
) -> list[str]:
    """Return world edges that currently have humans close enough to trigger expansion."""
    if not h_mask.any():
        return []
    live_x = h_tensor[h_mask, cfg.X]
    live_y = h_tensor[h_mask, cfg.Y]
    edges: list[str] = []
    if bool((live_y <= float(trigger_margin)).any().item()):
        edges.append("north")
    if bool((live_y >= float(cfg.MAP_HEIGHT - trigger_margin)).any().item()):
        edges.append("south")
    if bool((live_x <= float(trigger_margin)).any().item()):
        edges.append("west")
    if bool((live_x >= float(cfg.MAP_WIDTH - trigger_margin)).any().item()):
        edges.append("east")
    return edges


def frontier_edges_for_camera_window(
    *,
    center_x: float,
    center_y: float,
    view_world_w: float,
    view_world_h: float,
    preload_margin: float = 160.0,
) -> list[str]:
    """Trigger frontier preload when the visible camera window nears the map edge."""
    width = max(0.0, float(view_world_w))
    height = max(0.0, float(view_world_h))
    if width <= 0.0 or height <= 0.0:
        return []
    half_w = width / 2.0
    half_h = height / 2.0
    margin = max(0.0, float(preload_margin))
    edges: list[str] = []
    if float(center_y) - half_h <= margin:
        edges.append("north")
    if float(center_y) + half_h >= float(cfg.MAP_HEIGHT) - margin:
        edges.append("south")
    if float(center_x) - half_w <= margin:
        edges.append("west")
    if float(center_x) + half_w >= float(cfg.MAP_WIDTH) - margin:
        edges.append("east")
    return edges


def frontier_edges_for_controlled_targets(
    engine: Any,
    *,
    preload_margin: float = 160.0,
) -> list[str]:
    """Fallback preload trigger based on possessed targets when no camera window is reported."""
    player_control = getattr(engine, "player_control", None)
    if player_control is None:
        return []
    margin = max(0.0, float(preload_margin))
    ordered_edges: list[str] = []
    for session in player_control.sessions_by_controller.values():
        mode = str(session.get("mode", "")).strip().lower()
        target_kind = str(session.get("target_kind", "human")).strip().lower()
        if mode != "possess" and not (mode == "incarnate" and target_kind == "human"):
            continue
        slot = int(session.get("slot", -1))
        if target_kind == "entity":
            if not (0 <= slot < engine.state.m_tensor.shape[0]) or int(engine.state.m_tensor[slot, cfg.M_TYPE]) <= 0:
                continue
            px = float(engine.state.m_tensor[slot, cfg.CX])
            py = float(engine.state.m_tensor[slot, cfg.CY])
        else:
            if not (0 <= slot < engine.state.h_tensor.shape[0]) or int(engine.state.h_tensor[slot, cfg.TYPE]) != cfg.AGENT_TYPE_HUMAN:
                continue
            px = float(engine.state.h_tensor[slot, cfg.X])
            py = float(engine.state.h_tensor[slot, cfg.Y])

        if py <= margin and "north" not in ordered_edges:
            ordered_edges.append("north")
        if py >= float(cfg.MAP_HEIGHT) - margin and "south" not in ordered_edges:
            ordered_edges.append("south")
        if px <= margin and "west" not in ordered_edges:
            ordered_edges.append("west")
        if px >= float(cfg.MAP_WIDTH) - margin and "east" not in ordered_edges:
            ordered_edges.append("east")
    return ordered_edges


def resolve_frontier_preload_edges(
    engine: Any,
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    trigger_margin: float = 96.0,
    preload_margin: float = 160.0,
) -> tuple[list[str], str]:
    """
    Choose the best frontier trigger source.

    Priority:
    1. Camera/view window reported by the client
    2. Controlled target position
    3. Legacy human-near-border fallback
    """
    view_state = getattr(engine, "_view_window_state", None)
    if isinstance(view_state, dict) and view_state:
        edges = frontier_edges_for_camera_window(
            center_x=float(view_state.get("center_x", cfg.MAP_WIDTH / 2.0)),
            center_y=float(view_state.get("center_y", cfg.MAP_HEIGHT / 2.0)),
            view_world_w=float(view_state.get("view_world_w", 0.0)),
            view_world_h=float(view_state.get("view_world_h", 0.0)),
            preload_margin=float(view_state.get("preload_margin", preload_margin)),
        )
        if edges:
            return edges, "camera_window"

    edges = frontier_edges_for_controlled_targets(engine, preload_margin=preload_margin)
    if edges:
        return edges, "controlled_target"

    edges = frontier_edges_for_humans(h_mask, h_tensor, trigger_margin=trigger_margin)
    if edges:
        return edges, "human_border"
    return [], "none"


def _normalize_edge(edge: str | None) -> str:
    value = str(edge or "auto").strip().lower()
    if value in {"n", "north"}:
        return "north"
    if value in {"s", "south"}:
        return "south"
    if value in {"e", "east"}:
        return "east"
    if value in {"w", "west"}:
        return "west"
    return "auto"


def _edge_spawn_point(edge: str, *, band_depth: float, pad: float = 28.0) -> tuple[float, float]:
    if edge == "west":
        return random.uniform(pad, band_depth), random.uniform(pad, cfg.MAP_HEIGHT - pad)
    if edge == "east":
        return random.uniform(cfg.MAP_WIDTH - band_depth, cfg.MAP_WIDTH - pad), random.uniform(pad, cfg.MAP_HEIGHT - pad)
    if edge == "north":
        return random.uniform(pad, cfg.MAP_WIDTH - pad), random.uniform(pad, band_depth)
    return random.uniform(pad, cfg.MAP_WIDTH - pad), random.uniform(cfg.MAP_HEIGHT - band_depth, cfg.MAP_HEIGHT - pad)


def _edge_entity_count(m_tensor: torch.Tensor, edge: str, *, band_depth: float) -> int:
    live = m_tensor[: cfg.MAX_ENTITIES, cfg.M_TYPE] > 0
    if not live.any():
        return 0
    x = m_tensor[: cfg.MAX_ENTITIES, cfg.CX]
    y = m_tensor[: cfg.MAX_ENTITIES, cfg.CY]
    if edge == "west":
        mask = x <= float(band_depth)
    elif edge == "east":
        mask = x >= float(cfg.MAP_WIDTH - band_depth)
    elif edge == "north":
        mask = y <= float(band_depth)
    else:
        mask = y >= float(cfg.MAP_HEIGHT - band_depth)
    return int((live & mask).sum().item())


def expand_world_edge(
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    edge: str = "auto",
    clamp_point_fn: PointClampFn,
    create_object_fn: CreateObjectFn,
    create_scattered_objects_fn: CreateScatteredObjectsFn,
    create_line_objects_fn: CreateLineObjectsFn,
    resolve_build_site_fn: ResolveBuildSiteFn,
    band_depth: float = 170.0,
    sample_depth: float = 220.0,
    target_entities_in_band: int = 18,
    max_new_features: int = 4,
    rng_seed: int | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    """
    Grow a frontier strip inside the current canvas.

    This is the first-step "infinite world" foundation: it gives the sim a
    reusable edge-expansion mechanic now, while true unbounded coordinates and
    rendering can come later.
    """
    edge = _normalize_edge(edge)
    if edge == "auto":
        edge = random.choice(["north", "south", "east", "west"])

    existing = _edge_entity_count(m_tensor, edge, band_depth=band_depth)
    budget = min(int(max_new_features), max(0, int(target_entities_in_band) - existing))
    if budget <= 0:
        return {}

    profile = build_frontier_profile(m_tensor, edge=edge, sample_depth=sample_depth)
    feature_plan = generate_frontier_feature_plan(profile, feature_budget=budget, rng_seed=rng_seed)
    created = 0
    created_types: list[int] = []
    for spec in feature_plan:
        center_x, center_y = _edge_spawn_point(edge, band_depth=band_depth)
        if spec.feature_type == cfg.M_LAKE:
            result = create_lake_feature(
                m_tensor,
                entity_count_ref,
                center_x=center_x,
                center_y=center_y,
                clamp_point_fn=clamp_point_fn,
                resolve_build_site_fn=resolve_build_site_fn,
                create_object_fn=create_object_fn,
                scale=float(spec.scale or random.uniform(38.0, 62.0)),
                device=device,
            )
        elif spec.feature_type == cfg.M_FOREST:
            result = create_forest_patch_feature(
                m_tensor,
                entity_count_ref,
                center_x=center_x,
                center_y=center_y,
                create_scattered_objects_fn=create_scattered_objects_fn,
                radius=float(spec.radius or random.uniform(55.0, 100.0)),
                count=max(1, int(spec.count)),
                device=device,
            )
        elif spec.feature_type == cfg.M_GRASS:
            eid = create_natural_feature_at(
                m_tensor,
                entity_count_ref,
                feature_type=cfg.M_GRASS,
                center_x=center_x,
                center_y=center_y,
                clamp_point_fn=clamp_point_fn,
                create_object_fn=create_object_fn,
                scale=float(spec.scale or random.uniform(52.0, 92.0)),
                device=device,
            )
            result = {"map_dirty": eid != -1} if eid != -1 else {}
        elif spec.feature_type == cfg.M_BEACH:
            eid = create_natural_feature_at(
                m_tensor,
                entity_count_ref,
                feature_type=cfg.M_BEACH,
                center_x=center_x,
                center_y=center_y,
                clamp_point_fn=clamp_point_fn,
                create_object_fn=create_object_fn,
                scale=float(spec.scale or random.uniform(40.0, 72.0)),
                device=device,
            )
            result = {"map_dirty": eid != -1} if eid != -1 else {}
        elif spec.feature_type == cfg.M_MOUNTAIN:
            if edge in {"north", "south"}:
                start_x, start_y = clamp_point_fn(center_x - 48.0, center_y)
                end_x, end_y = clamp_point_fn(center_x + 48.0, center_y)
            else:
                start_x, start_y = clamp_point_fn(center_x, center_y - 48.0)
                end_x, end_y = clamp_point_fn(center_x, center_y + 48.0)
            result = create_mountain_chain_feature(
                m_tensor,
                entity_count_ref,
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
                create_line_objects_fn=create_line_objects_fn,
                segments=max(1, int(spec.segments)),
                scale=float(spec.scale or random.uniform(26.0, 40.0)),
                device=device,
            )
        else:
            eid = create_natural_feature_at(
                m_tensor,
                entity_count_ref,
                feature_type=cfg.M_BARREN,
                center_x=center_x,
                center_y=center_y,
                clamp_point_fn=clamp_point_fn,
                create_object_fn=create_object_fn,
                scale=float(spec.scale or random.uniform(34.0, 68.0)),
                device=device,
            )
            result = {"map_dirty": eid != -1} if eid != -1 else {}

        if result.get("map_dirty"):
            created += 1
            created_types.append(int(spec.feature_type))

    if not created:
        return {}
    return {
        "map_dirty": True,
        "edge": edge,
        "created": created,
        "created_types": created_types,
        "profile": {
            "dominant_type": int(profile.dominant_type),
            "sample_count": int(profile.sample_count),
            "weights": {str(type_id): round(weight, 3) for type_id, weight in profile.normalized_weights().items()},
        },
    }


def maybe_expand_frontier(
    h_mask: torch.Tensor,
    h_tensor: torch.Tensor,
    m_tensor: torch.Tensor,
    entity_count_ref: list,
    *,
    engine: Any,
    clamp_point_fn: PointClampFn,
    create_object_fn: CreateObjectFn,
    create_scattered_objects_fn: CreateScatteredObjectsFn,
    create_line_objects_fn: CreateLineObjectsFn,
    resolve_build_site_fn: ResolveBuildSiteFn,
    trigger_margin: float = 96.0,
    cooldown_ticks: int = 120,
    band_depth: float = 170.0,
    sample_depth: float = 220.0,
    preload_margin: float = 160.0,
    max_expansions_per_tick: int = 1,
    device: str = "cpu",
) -> dict[str, Any]:
    """Auto-expand the frontier when humans push against a world edge."""
    if not h_mask.any():
        return {}

    state = getattr(engine, "_frontier_state", None)
    if not isinstance(state, dict):
        state = {"edge_ticks": {}}
    edge_ticks = state.setdefault("edge_ticks", {})

    triggered_edges, trigger_source = resolve_frontier_preload_edges(
        engine,
        h_mask,
        h_tensor,
        trigger_margin=trigger_margin,
        preload_margin=preload_margin,
    )
    if not triggered_edges:
        state["last_trigger_source"] = "none"
        engine._frontier_state = state
        return {}

    expanded: list[dict[str, Any]] = []
    current_tick = int(getattr(engine, "tick", 0))
    for edge in triggered_edges:
        last_tick = int(edge_ticks.get(edge, -cooldown_ticks))
        if current_tick - last_tick < int(cooldown_ticks):
            continue
        result = expand_world_edge(
            m_tensor,
            entity_count_ref,
            edge=edge,
            clamp_point_fn=clamp_point_fn,
            create_object_fn=create_object_fn,
            create_scattered_objects_fn=create_scattered_objects_fn,
            create_line_objects_fn=create_line_objects_fn,
            resolve_build_site_fn=resolve_build_site_fn,
            band_depth=band_depth,
            sample_depth=sample_depth,
            rng_seed=(current_tick * 1009) + EDGE_SEED_OFFSET.get(edge, 0),
            device=device,
        )
        if not result.get("map_dirty"):
            continue
        edge_ticks[edge] = current_tick
        result["trigger_source"] = trigger_source
        expanded.append(result)
        if hasattr(engine, "_queue_event"):
            engine._queue_event(
                "frontier_expand",
                f"frontier:{edge}:{current_tick}",
                -1,
                edge=edge,
                created=result.get("created", 0),
                trigger_source=trigger_source,
            )
        if len(expanded) >= int(max_expansions_per_tick):
            break

    state["edge_ticks"] = edge_ticks
    state["last_trigger_source"] = trigger_source
    engine._frontier_state = state
    if not expanded:
        return {}
    return {
        "map_dirty": True,
        "frontier_expansions": expanded,
    }
