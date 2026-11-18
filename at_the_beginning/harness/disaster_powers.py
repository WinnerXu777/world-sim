"""Disaster and hazard god powers ported from instincts_and_tools.py and systems/nature/disasters.py.

Eight powers ported under EDEN_GOD_POWER_PORTS=1:
1. wildfire: ignite forest entities within radius (burning=1.0, food=0.0).
2. earthquake: damage entities (-60 hp) and residents (-30 hp), convert terrain to barren (M_BARREN, food=0.0), raise threat to 100 and flee outward.
3. storm: displace residents within radius, damage unsheltered (-8 hp), penalty to mood (-25) and raise threat (+30).
4. volcanic_eruption: inner radius converts terrain to lava (M_LAVA, food/cooling) and kills residents; outer radius ignites forests (burning=1.0) and flees residents.
5. drought: dry lakes (food=0.0, water=0.0, fertility=0.0) across all lakes, an area, or a typed selector.
6. flood: expand water into adjacent expandable land (type=M_SEA, food=0.0, flooded=1.0), damage residents standing on flooded tiles.
7. area_attack: kill residents in blast radius, flee survivors in outer ring outward.
8. smite: kill residents matched by a typed selector immediately.

All powers follow the pure plan() -> atomic apply() pipeline, deterministic world-keyed randomness,
space isolation, float32 precision, and witness event emissions.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional, Sequence

import torch

from . import effects as fx
from . import target_selectors as sel
from .numerics import pairwise_distances, space_slice
from .powers import Draft, FLEE_STEP, PowerRefused, _humans, _resolution, bounded_amounts
from .registry import Registry, power
from .spaces import point_space

try:
    from genesis_config import (
        FLOOD_HP_DAMAGE,
        M_BARREN,
        M_FOREST,
        M_LAKE,
        M_LAVA,
        M_MOUNTAIN,
        M_SEA,
        QUAKE_AGENT_DAMAGE,
        QUAKE_ENTITY_DAMAGE,
        QUAKE_RUBBLE_PROB,
        STORM_DISPLACEMENT,
        STORM_HP_DAMAGE,
        STORM_MOOD_PENALTY,
        STORM_THREAT_RAISE,
        VOLCANO_INNER_RADIUS,
        VOLCANO_LAVA_COOLING,
        VOLCANO_OUTER_RADIUS,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import (
        FLOOD_HP_DAMAGE,
        M_BARREN,
        M_FOREST,
        M_LAKE,
        M_LAVA,
        M_MOUNTAIN,
        M_SEA,
        QUAKE_AGENT_DAMAGE,
        QUAKE_ENTITY_DAMAGE,
        QUAKE_RUBBLE_PROB,
        STORM_DISPLACEMENT,
        STORM_HP_DAMAGE,
        STORM_MOOD_PENALTY,
        STORM_THREAT_RAISE,
        VOLCANO_INNER_RADIUS,
        VOLCANO_LAVA_COOLING,
        VOLCANO_OUTER_RADIUS,
    )

try:
    import map_geo
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import map_geo


def _check_amounts(**amounts) -> None:
    for name, value in amounts.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise PowerRefused("invalid_amount", f"{name} must be a finite number >= 0, got {value!r}")


def _check_center(center: Any) -> tuple[float, float]:
    if (not isinstance(center, (list, tuple)) or len(center) != 2
            or any(not isinstance(c, (int, float)) or isinstance(c, bool) or not math.isfinite(c) for c in center)):
        raise PowerRefused("invalid_center", "center must be two finite numbers [x, y]")
    return (float(center[0]), float(center[1]))


def _centroid(world, ids: Sequence, table_name: str = "humans") -> Optional[tuple[float, float]]:
    if not ids or table_name not in world.tables:
        return None
    table = world.table(table_name)
    points = [table.position(table.slot_of(i)) for i in ids if table.slot_of(i) is not None]
    points = [p for p in points if p is not None]
    if not points:
        return None
    return (float(sum(p[0] for p in points) / len(points)), float(sum(p[1] for p in points) / len(points)))


def _clamp_positions(world, xs: Sequence[float], ys: Sequence[float]) -> tuple[list[float], list[float]]:
    bounds = world.bounds()
    if bounds is None:
        try:
            from genesis_config import MAP_HEIGHT, MAP_WIDTH
        except ImportError:
            from at_the_beginning.genesis_config import MAP_HEIGHT, MAP_WIDTH
        bounds = (0.0, 0.0, float(MAP_WIDTH), float(MAP_HEIGHT))
    x0, y0, x1, y1 = bounds
    out_x = [min(x1, max(x0, float(x))) for x in xs]
    out_y = [min(y1, max(y0, float(y))) for y in ys]
    return out_x, out_y


def _area_slots_and_ids(world, table_name: str, center: tuple[float, float], radius: float) -> tuple[list[int], tuple[str, ...]]:
    """Live slots and stable IDs of table_name strictly within radius of center, with full space isolation."""
    if table_name not in world.tables:
        return [], ()
    table = world.table(table_name)
    slots = [s for s in table.live_slots() if table.ids[s] is not None]
    if not slots:
        return [], ()
    pos = table.tensor[slots][:, [table.col("x"), table.col("y")]]
    center_tensor = torch.tensor([[center[0], center[1]]], dtype=pos.dtype, device=pos.device)

    space = point_space(center[0], center[1])
    row_space = None
    if space is not None:
        if table.space_col and table.space_col in table.columns:
            row_space = table.tensor[slots, table.col(table.space_col)]
        else:
            row_space = space_slice(table.tensor, slots, "h" if table_name == "humans" else "m")
    center_space = torch.tensor([float(space)], dtype=pos.dtype, device=pos.device) if row_space is not None else None

    dists = pairwise_distances(pos, center_tensor, space_a=row_space, space_b=center_space).squeeze(1)
    matched_slots = [s for s, d in zip(slots, dists.tolist()) if d < float(radius)]
    matched_ids = tuple(table.ids[s] for s in matched_slots)
    return matched_slots, matched_ids


def register_disaster_powers(reg: Registry) -> None:
    """Register all eight disaster powers onto the provided registry with risk='destructive'."""

    @power("wildfire", risk="destructive", registry=reg)
    def wildfire(world, center: list, radius: float = 80.0) -> Draft:
        """Ignite all forest entities within radius of a point; food is cleared and burning is set to 1.0."""
        _check_amounts(radius=radius)
        c = _check_center(center)
        if "entities" not in world.tables:
            raise PowerRefused("no_targets", "world has no 'entities' table")
        table = world.table("entities")
        for col_name in ("burning", "food", "type"):
            if col_name not in table.columns:
                raise PowerRefused("no_column", f"entities table missing {col_name!r}")
        slots, eids = _area_slots_and_ids(world, "entities", c, radius)
        forest_ids = tuple(eid for eid in eids if int(table.get(eid, "type")) == M_FOREST)
        if not forest_ids:
            raise PowerRefused("no_targets", f"no forest entities within {radius} of {list(center)}")

        effects = [
            fx.set_("entities", forest_ids, "burning", 1.0),
            fx.set_("entities", forest_ids, "food", 0.0),
        ]
        event = fx.Emit("wildfire", place=c, visibility="local", radius=float(radius),
                        payload={"ignited": len(forest_ids)})
        preview = {
            "affected": list(forest_ids),
            "center": [c[0], c[1]],
            "radius": float(radius),
            "ignited": len(forest_ids),
            "reversible": False,
        }
        res = _resolution(world, {"of": "entities", "center": list(center), "radius": float(radius)}, forest_ids)
        return Draft(res, effects, preview, event)

    @power("earthquake", risk="destructive", registry=reg)
    def earthquake(world, center: list, radius: float = 120.0,
                   rubble_draws: Optional[list] = None) -> Draft:
        """Damage entities and residents within radius, convert some terrain to barren rubble, raise threat and flee survivors."""
        _check_amounts(radius=radius)
        c = _check_center(center)
        if rubble_draws is not None:
            if (not isinstance(rubble_draws, (list, tuple))
                    or any(not isinstance(d, (int, float)) or isinstance(d, bool) or not math.isfinite(d) for d in rubble_draws)):
                raise PowerRefused("invalid_amount", "rubble_draws must be a list of finite numbers")

        has_entities = "entities" in world.tables
        has_humans = "humans" in world.tables

        entity_ids: tuple[str, ...] = ()
        human_ids: tuple[str, ...] = ()
        if has_entities:
            _, entity_ids = _area_slots_and_ids(world, "entities", c, radius)
        if has_humans:
            _, human_ids = _area_slots_and_ids(world, "humans", c, radius)

        if not entity_ids and not human_ids:
            raise PowerRefused("no_targets", f"nothing within {radius} of {list(center)}")

        effects = []
        rubble_ids: list[str] = []

        if entity_ids:
            table_e = world.table("entities")
            for col_name in ("hp", "type", "food"):
                if col_name not in table_e.columns:
                    raise PowerRefused("no_column", f"entities table missing {col_name!r}")
            cur_hp = [table_e.get(i, "hp") for i in entity_ids]
            effects.append(fx.delta("entities", entity_ids, "hp",
                                    bounded_amounts(cur_hp, -QUAKE_ENTITY_DAMAGE, 0.0, None)))

            for idx, eid in enumerate(entity_ids):
                et = int(table_e.get(eid, "type"))
                if rubble_draws is not None and idx < len(rubble_draws):
                    draw = float(rubble_draws[idx])
                else:
                    draw = world.rng("earthquake", eid).random()
                if draw < QUAKE_RUBBLE_PROB and et not in {M_SEA, M_LAVA}:
                    rubble_ids.append(eid)

            if rubble_ids:
                rubble_tuple = tuple(rubble_ids)
                effects.append(fx.set_("entities", rubble_tuple, "type", float(M_BARREN)))
                effects.append(fx.set_("entities", rubble_tuple, "food", 0.0))

        if human_ids:
            table_h = world.table("humans")
            for col_name in ("hp", "threat", "x", "y"):
                if col_name not in table_h.columns:
                    raise PowerRefused("no_column", f"humans table missing {col_name!r}")
            cur_hp_h = [table_h.get(i, "hp") for i in human_ids]
            effects.append(fx.delta("humans", human_ids, "hp",
                                    bounded_amounts(cur_hp_h, -QUAKE_AGENT_DAMAGE, 0.0, None)))
            effects.append(fx.set_("humans", human_ids, "threat", 100.0))

            slots = [table_h.slot_of(i) for i in human_ids]
            pos = table_h.tensor[slots][:, [table_h.col("x"), table_h.col("y")]]
            away = pos - torch.tensor([[c[0], c[1]]], dtype=pos.dtype, device=pos.device)
            push = away / away.norm(dim=1, keepdim=True).clamp(min=1e-6) * float(FLEE_STEP)
            raw_new_pos = pos + push
            clamped_x, clamped_y = _clamp_positions(world, raw_new_pos[:, 0].tolist(), raw_new_pos[:, 1].tolist())
            effects.append(fx.set_("humans", human_ids, "x", clamped_x))
            effects.append(fx.set_("humans", human_ids, "y", clamped_y))

        all_affected = tuple(entity_ids) + tuple(human_ids)
        event = fx.Emit("earthquake", actors=tuple(human_ids), place=c, visibility="local", radius=float(radius),
                        payload={"entities": len(entity_ids), "humans": len(human_ids), "rubble": len(rubble_ids)})
        preview = {
            "affected_entities": list(entity_ids),
            "affected_humans": list(human_ids),
            "rubble_entities": list(rubble_ids),
            "center": [c[0], c[1]],
            "radius": float(radius),
            "reversible": False,
        }
        res = _resolution(world, {"of": "world", "center": list(center), "radius": float(radius)}, all_affected)
        return Draft(res, effects, preview, event)

    @power("storm", risk="destructive", registry=reg)
    def storm(world, center: list, radius: float = 120.0,
              displacement_draws: Optional[list] = None) -> Draft:
        """Displace residents in radius, damage unsheltered residents, lower mood and raise threat."""
        _check_amounts(radius=radius)
        c = _check_center(center)
        if "humans" not in world.tables:
            raise PowerRefused("no_targets", "world has no 'humans' table")
        table = world.table("humans")
        for col_name in ("x", "y", "hp", "mood", "threat"):
            if col_name not in table.columns:
                raise PowerRefused("no_column", f"humans table missing {col_name!r}")
        if displacement_draws is not None:
            if not isinstance(displacement_draws, (list, tuple)):
                raise PowerRefused("invalid_amount", "displacement_draws must be a list")
            for item in displacement_draws:
                if (not isinstance(item, (list, tuple)) or len(item) != 2
                        or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in item)):
                    raise PowerRefused("invalid_amount", "displacement_draws items must be pairs of finite numbers")

        _, human_ids = _area_slots_and_ids(world, "humans", c, radius)
        if not human_ids:
            raise PowerRefused("no_targets", f"no residents within {radius} of {list(center)}")

        effects = []
        new_xs: list[float] = []
        new_ys: list[float] = []
        for idx, hid in enumerate(human_ids):
            cur_x = table.get(hid, "x")
            cur_y = table.get(hid, "y")
            if displacement_draws is not None and idx < len(displacement_draws):
                draw_x, draw_y = float(displacement_draws[idx][0]), float(displacement_draws[idx][1])
                dx = (draw_x - 0.5) * STORM_DISPLACEMENT if (0.0 <= draw_x <= 1.0 and 0.0 <= draw_y <= 1.0) else draw_x
                dy = (draw_y - 0.5) * STORM_DISPLACEMENT if (0.0 <= draw_x <= 1.0 and 0.0 <= draw_y <= 1.0) else draw_y
            else:
                st = world.rng("storm", hid)
                dx = (st.random() - 0.5) * STORM_DISPLACEMENT
                dy = (st.random() - 0.5) * STORM_DISPLACEMENT
            new_xs.append(cur_x + dx)
            new_ys.append(cur_y + dy)

        clamped_x, clamped_y = _clamp_positions(world, new_xs, new_ys)
        effects.append(fx.set_("humans", human_ids, "x", clamped_x))
        effects.append(fx.set_("humans", human_ids, "y", clamped_y))

        unsheltered_ids = tuple(hid for hid in human_ids if ("shelter" not in table.columns or table.get(hid, "shelter") == 0.0))
        if unsheltered_ids:
            cur_hp = [table.get(hid, "hp") for hid in unsheltered_ids]
            effects.append(fx.delta("humans", unsheltered_ids, "hp",
                                    bounded_amounts(cur_hp, -STORM_HP_DAMAGE, 0.0, None)))

        cur_mood = [table.get(hid, "mood") for hid in human_ids]
        effects.append(fx.delta("humans", human_ids, "mood",
                                bounded_amounts(cur_mood, -STORM_MOOD_PENALTY, 0.0, None)))
        cur_threat = [table.get(hid, "threat") for hid in human_ids]
        effects.append(fx.delta("humans", human_ids, "threat",
                                bounded_amounts(cur_threat, STORM_THREAT_RAISE, None, 100.0)))

        event = fx.Emit("storm", actors=human_ids, place=c, visibility="local", radius=float(radius),
                        payload={"count": len(human_ids), "unsheltered": len(unsheltered_ids)})
        preview = {
            "affected": list(human_ids),
            "unsheltered": list(unsheltered_ids),
            "center": [c[0], c[1]],
            "radius": float(radius),
            "reversible": False,
        }
        res = _resolution(world, {"of": "humans", "center": list(center), "radius": float(radius)}, human_ids)
        return Draft(res, effects, preview, event)

    @power("volcanic_eruption", risk="destructive", registry=reg)
    def volcanic_eruption(world, center: list, inner_radius: float = 60.0,
                          outer_radius: float = 160.0) -> Draft:
        """Convert inner terrain to lava, ignite outer forests, kill inner residents, and flee outer residents."""
        _check_amounts(inner_radius=inner_radius, outer_radius=outer_radius)
        if outer_radius < inner_radius:
            raise PowerRefused("invalid_amount", "outer_radius must be >= inner_radius")
        c = _check_center(center)

        has_entities = "entities" in world.tables
        has_humans = "humans" in world.tables

        inner_eids: tuple[str, ...] = ()
        outer_eids: tuple[str, ...] = ()
        inner_hids: tuple[str, ...] = ()
        outer_hids: tuple[str, ...] = ()

        if has_entities:
            _, inner_eids = _area_slots_and_ids(world, "entities", c, inner_radius)
            _, outer_eids = _area_slots_and_ids(world, "entities", c, outer_radius)
        if has_humans:
            _, inner_hids = _area_slots_and_ids(world, "humans", c, inner_radius)
            _, outer_all_hids = _area_slots_and_ids(world, "humans", c, outer_radius)
            inner_set_h = set(inner_hids)
            outer_hids = tuple(hid for hid in outer_all_hids if hid not in inner_set_h)

        lava_ids: tuple[str, ...] = ()
        outer_forest_ids: tuple[str, ...] = ()
        if has_entities:
            table_e = world.table("entities")
            for col_name in ("type", "food", "burning"):
                if col_name not in table_e.columns:
                    raise PowerRefused("no_column", f"entities table missing {col_name!r}")
            lava_ids = tuple(eid for eid in inner_eids if int(table_e.get(eid, "type")) != M_SEA)
            inner_set_e = set(inner_eids)
            outer_forest_ids = tuple(eid for eid in outer_eids if eid not in inner_set_e and int(table_e.get(eid, "type")) == M_FOREST)

        if not lava_ids and not outer_forest_ids and not inner_hids and not outer_hids:
            raise PowerRefused("no_targets", f"nothing within {outer_radius} of {list(center)}")

        effects = []
        if lava_ids:
            effects.append(fx.set_("entities", lava_ids, "type", float(M_LAVA)))
            table_e = world.table("entities")
            if "lava_cooling" in table_e.columns:
                effects.append(fx.set_("entities", lava_ids, "food", 0.0))
                effects.append(fx.set_("entities", lava_ids, "lava_cooling", float(VOLCANO_LAVA_COOLING)))
            else:
                effects.append(fx.set_("entities", lava_ids, "food", float(VOLCANO_LAVA_COOLING)))

        if outer_forest_ids:
            effects.append(fx.set_("entities", outer_forest_ids, "burning", 1.0))

        if inner_hids:
            effects.append(fx.despawn("humans", inner_hids))

        if outer_hids:
            table_h = world.table("humans")
            effects.append(fx.set_("humans", outer_hids, "threat", 100.0))
            slots = [table_h.slot_of(i) for i in outer_hids]
            pos = table_h.tensor[slots][:, [table_h.col("x"), table_h.col("y")]]
            away = pos - torch.tensor([[c[0], c[1]]], dtype=pos.dtype, device=pos.device)
            push = away / away.norm(dim=1, keepdim=True).clamp(min=1e-6) * float(FLEE_STEP)
            raw_new_pos = pos + push
            clamped_x, clamped_y = _clamp_positions(world, raw_new_pos[:, 0].tolist(), raw_new_pos[:, 1].tolist())
            effects.append(fx.set_("humans", outer_hids, "x", clamped_x))
            effects.append(fx.set_("humans", outer_hids, "y", clamped_y))

        all_affected = tuple(lava_ids) + tuple(outer_forest_ids) + tuple(inner_hids) + tuple(outer_hids)
        event = fx.Emit("volcanic_eruption", actors=tuple(inner_hids) + tuple(outer_hids), place=c, visibility="local",
                        radius=float(outer_radius),
                        payload={"inner_entities": len(lava_ids), "outer_forests": len(outer_forest_ids),
                                 "killed_humans": len(inner_hids), "fleeing_humans": len(outer_hids)})
        preview = {
            "inner_entities": list(lava_ids),
            "outer_forests": list(outer_forest_ids),
            "killed_humans": list(inner_hids),
            "fleeing_humans": list(outer_hids),
            "center": [c[0], c[1]],
            "inner_radius": float(inner_radius),
            "outer_radius": float(outer_radius),
            "reversible": False,
        }
        res = _resolution(world, {"of": "world", "center": list(center), "radius": float(outer_radius)}, all_affected)
        return Draft(res, effects, preview, event)

    @power("drought", risk="destructive", registry=reg)
    def drought(world, targets: Optional[dict] = None, center: Optional[list] = None,
                radius: Optional[float] = None) -> Draft:
        """Dry out lakes: clear food, water and fertility (defaults to all lakes or a selector/area)."""
        if "entities" not in world.tables:
            raise PowerRefused("no_targets", "world has no 'entities' table")
        table = world.table("entities")
        for col_name in ("type", "food", "water", "fertility"):
            if col_name not in table.columns:
                raise PowerRefused("no_column", f"entities table missing {col_name!r}")
        if radius is not None:
            _check_amounts(radius=radius)
        c = _check_center(center) if center is not None else None

        if targets is not None:
            if not isinstance(targets, dict) or targets.get("of") != "entities":
                raise PowerRefused("invalid_targets", "targets must be a selector over 'entities'")
            try:
                candidate_ids = sel.resolve(targets, world).ids
            except sel.SelectorError as exc:
                raise PowerRefused("invalid_selector", str(exc)) from None
        elif c is not None:
            r = float(radius) if radius is not None else 80.0
            _, candidate_ids = _area_slots_and_ids(world, "entities", c, r)
        else:
            slots = [s for s in table.live_slots() if table.ids[s] is not None]
            candidate_ids = tuple(table.ids[s] for s in slots)

        lake_ids = tuple(eid for eid in candidate_ids if int(table.get(eid, "type")) == M_LAKE)
        if not lake_ids:
            raise PowerRefused("no_targets", "no lakes matched")

        effects = [
            fx.set_("entities", lake_ids, "food", 0.0),
            fx.set_("entities", lake_ids, "water", 0.0),
            fx.set_("entities", lake_ids, "fertility", 0.0),
        ]
        place = c if c is not None else _centroid(world, lake_ids, table_name="entities")
        vis = "local" if c is not None else "global"
        event = fx.Emit("drought", place=place, visibility=vis,
                        radius=float(radius) if radius is not None else 80.0,
                        payload={"lakes": len(lake_ids)})
        preview = {
            "affected": list(lake_ids),
            "lakes": len(lake_ids),
            "reversible": False,
        }
        res = _resolution(world, {"of": "entities", "lakes": True}, lake_ids)
        return Draft(res, effects, preview, event)

    @power("flood", risk="destructive", registry=reg)
    def flood(world, expand_radius: float = 100.0, center: Optional[list] = None,
              radius: Optional[float] = None) -> Draft:
        """Expand water into adjacent land, clear food, set flooded flag, and damage residents on flooded land."""
        _check_amounts(expand_radius=expand_radius)
        if radius is not None:
            _check_amounts(radius=radius)
        c = _check_center(center) if center is not None else None

        if "entities" not in world.tables:
            raise PowerRefused("no_targets", "world has no 'entities' table")
        table_e = world.table("entities")
        for col_name in ("type", "food", "flooded", "x", "y"):
            if col_name not in table_e.columns:
                raise PowerRefused("no_column", f"entities table missing {col_name!r}")

        slots_e = [s for s in table_e.live_slots() if table_e.ids[s] is not None]
        if not slots_e:
            raise PowerRefused("no_targets", "no live entities")

        types = [int(table_e.tensor[s, table_e.col("type")]) for s in slots_e]
        water_slots = [s for s, t in zip(slots_e, types) if t in {M_SEA, M_LAKE}]
        expandable_slots = [s for s, t in zip(slots_e, types) if t not in {0, M_SEA, M_LAKE, M_MOUNTAIN, M_LAVA}]

        if not water_slots or not expandable_slots:
            raise PowerRefused("no_targets", "no expandable land near water")

        w_pos = table_e.tensor[water_slots][:, [table_e.col("x"), table_e.col("y")]]
        e_pos = table_e.tensor[expandable_slots][:, [table_e.col("x"), table_e.col("y")]]

        space_w = space_slice(table_e.tensor, water_slots, "m") if point_space(0, 0) is not None else None
        space_e = space_slice(table_e.tensor, expandable_slots, "m") if point_space(0, 0) is not None else None

        dists = pairwise_distances(e_pos, w_pos, space_a=space_e, space_b=space_w)
        near = (dists < float(expand_radius)).any(dim=1)

        flood_slots = [s for s, is_near in zip(expandable_slots, near.tolist()) if is_near]
        if c is not None:
            r = float(radius) if radius is not None else float(expand_radius)
            flood_pos = table_e.tensor[flood_slots][:, [table_e.col("x"), table_e.col("y")]]
            c_tens = torch.tensor([[c[0], c[1]]], dtype=flood_pos.dtype, device=flood_pos.device)
            c_dist = pairwise_distances(flood_pos, c_tens).squeeze(1)
            flood_slots = [s for s, d in zip(flood_slots, c_dist.tolist()) if d < r]

        if not flood_slots:
            raise PowerRefused("no_targets", f"no land within {expand_radius} of water")

        flood_ids = tuple(table_e.ids[s] for s in flood_slots)

        effects = [
            fx.set_("entities", flood_ids, "type", float(M_SEA)),
            fx.set_("entities", flood_ids, "food", 0.0),
            fx.set_("entities", flood_ids, "flooded", 1.0),
        ]

        damaged_human_ids: list[str] = []
        if "humans" in world.tables:
            table_h = world.table("humans")
            h_slots = [s for s in table_h.live_slots() if table_h.ids[s] is not None]
            if h_slots:
                flooded_tiles: set[int] = set()
                for eid_slot in flood_slots:
                    if hasattr(map_geo, "MAP_GEO") and eid_slot in map_geo.MAP_GEO:
                        flooded_tiles.update(map_geo.tiles_of(eid_slot))
                if flooded_tiles and hasattr(map_geo, "_px_to_tile_idx"):
                    for hs in h_slots:
                        hx = float(table_h.tensor[hs, table_h.col("x")])
                        hy = float(table_h.tensor[hs, table_h.col("y")])
                        t_idx = map_geo._px_to_tile_idx(hx, hy)
                        if t_idx in flooded_tiles:
                            damaged_human_ids.append(table_h.ids[hs])

        damaged_tuple = tuple(damaged_human_ids)
        if damaged_tuple:
            table_h = world.table("humans")
            for col_name in ("hp", "threat"):
                if col_name not in table_h.columns:
                    raise PowerRefused("no_column", f"humans table missing {col_name!r}")
            cur_hp = [table_h.get(i, "hp") for i in damaged_tuple]
            effects.append(fx.delta("humans", damaged_tuple, "hp",
                                    bounded_amounts(cur_hp, -FLOOD_HP_DAMAGE * 10, 0.0, None)))
            effects.append(fx.set_("humans", damaged_tuple, "threat", 100.0))

        place = c if c is not None else _centroid(world, flood_ids, table_name="entities")
        event = fx.Emit("flood", actors=damaged_tuple, place=place, visibility="local",
                        radius=float(expand_radius),
                        payload={"flooded_entities": len(flood_ids), "damaged_humans": len(damaged_tuple)})
        preview = {
            "flooded_entities": list(flood_ids),
            "damaged_humans": list(damaged_tuple),
            "expand_radius": float(expand_radius),
            "reversible": False,
        }
        res = _resolution(world, {"of": "entities", "flood": True}, tuple(flood_ids) + damaged_tuple)
        return Draft(res, effects, preview, event)

    @power("area_attack", risk="destructive", registry=reg)
    def area_attack(world, center: list, radius: float = 40.0,
                    flee_radius_multiplier: float = 2.5) -> Draft:
        """Kill residents in the blast radius and flee nearby survivors outward."""
        _check_amounts(radius=radius, flee_radius_multiplier=flee_radius_multiplier)
        c = _check_center(center)
        if "humans" not in world.tables:
            raise PowerRefused("no_targets", "world has no 'humans' table")
        table = world.table("humans")
        for col_name in ("x", "y", "type"):
            if col_name not in table.columns:
                raise PowerRefused("no_column", f"humans table missing {col_name!r}")

        max_r = float(radius * flee_radius_multiplier)
        slots_all, all_ids = _area_slots_and_ids(world, "humans", c, max_r)
        if not all_ids:
            raise PowerRefused("no_targets", f"no residents within {max_r} of {list(center)}")

        pos_all = table.tensor[slots_all][:, [table.col("x"), table.col("y")]]
        c_tens = torch.tensor([[c[0], c[1]]], dtype=pos_all.dtype, device=pos_all.device)
        dists = pairwise_distances(pos_all, c_tens).squeeze(1).tolist()

        kill_ids = tuple(eid for eid, d in zip(all_ids, dists) if d < float(radius))
        flee_ids = tuple(eid for eid, d in zip(all_ids, dists) if float(radius) <= d < max_r)

        effects = []
        if kill_ids:
            effects.append(fx.despawn("humans", kill_ids))

        if flee_ids:
            flee_slots = [table.slot_of(i) for i in flee_ids]
            pos_flee = table.tensor[flee_slots][:, [table.col("x"), table.col("y")]]
            away = pos_flee - c_tens
            push = away / away.norm(dim=1, keepdim=True).clamp(min=1e-6) * float(FLEE_STEP)
            raw_new_pos = pos_flee + push
            clamped_x, clamped_y = _clamp_positions(world, raw_new_pos[:, 0].tolist(), raw_new_pos[:, 1].tolist())
            effects.append(fx.set_("humans", flee_ids, "x", clamped_x))
            effects.append(fx.set_("humans", flee_ids, "y", clamped_y))

        event = fx.Emit("area_attack", actors=tuple(kill_ids) + tuple(flee_ids), place=c, visibility="local",
                        radius=max_r, payload={"killed": len(kill_ids), "fleeing": len(flee_ids)})
        preview = {
            "killed": list(kill_ids),
            "fleeing": list(flee_ids),
            "center": [c[0], c[1]],
            "radius": float(radius),
            "reversible": False,
        }
        res = _resolution(world, {"of": "humans", "center": list(center), "radius": float(radius)},
                          tuple(kill_ids) + tuple(flee_ids))
        return Draft(res, effects, preview, event)

    @power("smite", risk="destructive", registry=reg)
    def smite(world, targets: dict) -> Draft:
        """Strike down the residents matched by a selector immediately."""
        resolution = _humans(world, targets)
        ids = resolution.ids
        effects = [fx.despawn("humans", ids)]
        event = fx.Emit("smite", actors=ids, place=_centroid(world, ids), visibility="local",
                        radius=80.0, payload={"count": len(ids)})
        preview = {
            "affected": list(ids),
            "killed": len(ids),
            "reversible": False,
        }
        return Draft(resolution, effects, preview, event)
