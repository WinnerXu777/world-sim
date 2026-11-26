"""R66-PACE-2: the per-animal nearest queries get cheaper and give the same answers as before, ties included.

``systems/perception/queries.py`` puts a float64 prefilter in front of the unchanged exact scan (``pick_best_entity`` with ``math.hypot``) in
``nearest_entity_from_ids`` and ``nearest_human_from_mask``, and adds ``nearest_geo_entity_possible``, a batch test that is False only where
``nearest_geo_entity`` must return -1. ``animal_instinct_drink`` skips the query only there; ``animal_instinct_predator_attack`` computes its
distances once per tick (positions do not change inside its loop, only HP and THREAT do).

Every test compares the new code with REFERENCE copies of the cddfa86 bodies kept below verbatim and run against the live modules' globals, so
the comparison does not depend on git. The last class runs the real engine for 300 ticks twice, once with the reference functions patched in,
and compares the SHA-256 of the world state every 50 ticks."""
import asyncio
import hashlib
import json
import math
import os
import random
import struct
import subprocess
import sys
import time
import uuid
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
import instincts_and_tools as it  # noqa: E402
import map_geo  # noqa: E402
from systems.perception import queries  # noqa: E402
from systems.perception import resolver  # noqa: E402

# ---------------------------------------------------------------------------------------------------------------- reference (cddfa86, verbatim)
REFERENCE_QUERIES = r'''
def pick_best_entity(
    entity_ids: Iterable[int],
    score_fn: Callable[[int], float],
) -> int:
    """Return the entity id with the lowest score, or ``-1`` when empty."""
    best_entity_id = -1
    best_score = float("inf")
    for raw_entity_id in entity_ids:
        entity_id = int(raw_entity_id)
        score = float(score_fn(entity_id))
        if score < best_score:
            best_score = score
            best_entity_id = entity_id
    return best_entity_id


def point_distance(x0: float, y0: float, x1: float, y1: float) -> float:
    """Euclidean distance between two world positions."""
    return math.hypot(x1 - x0, y1 - y0)


def current_entity_id(px: float, py: float) -> int:
    """Entity covering a world point, or ``-1`` when empty."""
    return int(map_geo.entity_at(px, py))


def nearby_entity_ids(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    radius: float,
    type_filter: set[int] | None = None,
) -> list[int]:
    """List nearby map entities around a world point."""
    return [int(entity_id) for entity_id in map_geo.entities_in_radius(px, py, radius, m_tensor, type_filter)]


def nearest_geo_entity(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    type_filter: set[int] | None = None,
    radius: float = 0.0,
) -> int:
    """
    Return the covering entity first, then fall back to nearby geometry ranked by
    approximate edge distance.
    """
    entity_id = current_entity_id(px, py)
    if entity_id != -1:
        entity_type = int(m_tensor[entity_id, M_TYPE])
        if type_filter is None or entity_type in type_filter:
            return entity_id

    if radius <= 0.0:
        return -1

    candidates = nearby_entity_ids(m_tensor, px, py, radius, type_filter)
    if not candidates:
        return -1

    def _edge_distance(candidate_id: int) -> float:
        cx = float(m_tensor[candidate_id, CX])
        cy = float(m_tensor[candidate_id, CY])
        return max(0.0, point_distance(px, py, cx, cy) - max(1.0, float(m_tensor[candidate_id, SCALE])))

    return pick_best_entity(candidates, _edge_distance)


def nearest_entity_from_ids(
    m_tensor: torch.Tensor,
    px: float,
    py: float,
    entity_ids: list[int] | torch.Tensor,
) -> tuple[int, float]:
    """Nearest entity from an explicit candidate list."""
    ids = entity_ids.tolist() if isinstance(entity_ids, torch.Tensor) else list(entity_ids)
    if not ids:
        return -1, float("inf")

    def _distance(entity_id: int) -> float:
        return point_distance(px, py, float(m_tensor[entity_id, CX]), float(m_tensor[entity_id, CY]))

    best_entity_id = pick_best_entity(ids, _distance)
    if best_entity_id == -1:
        return -1, float("inf")
    return best_entity_id, _distance(best_entity_id)


def nearest_human_from_mask(
    h_tensor: torch.Tensor,
    px: float,
    py: float,
    human_mask: torch.Tensor,
    *,
    max_distance: float | None = None,
) -> tuple[int, float]:
    """Nearest human slot from a boolean mask."""
    if human_mask.numel() == 0 or not human_mask.any():
        return -1, float("inf")

    human_slots = torch.where(human_mask)[0]

    def _distance(slot: int) -> float:
        return point_distance(px, py, float(h_tensor[slot, X]), float(h_tensor[slot, Y]))

    best_slot = pick_best_entity(human_slots.tolist(), _distance)
    if best_slot == -1:
        return -1, float("inf")
    best_distance = _distance(best_slot)
    if max_distance is not None and best_distance > float(max_distance):
        return -1, float("inf")
    return best_slot, best_distance
'''

REFERENCE_INSTINCTS = r'''
def animal_instinct_drink(ctx: dict, m_tensor: torch.Tensor, **_) -> dict:
    """
    Animals drink from nearby lakes or wells.
    """
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    map_dirty = False
    for i in torch.where(a_mask)[0].tolist():
        if m_tensor[i, A_THIRST] <= 20.0:
            continue
        ax = float(m_tensor[i, CX])
        ay = float(m_tensor[i, CY])
        eid = _nearest_geo_entity(
            m_tensor, ax, ay, DRINKABLE_TYPES, DRINK_PROXIMITY_RADIUS
        )
        if eid == -1 or eid == i:
            continue
        water = float(m_tensor[eid, M_RESOURCE_WATER])
        if water <= 0.0:
            continue
        m_tensor[i, A_THIRST] -= DRINK_THIRST_RESTORE
        m_tensor[i, A_THIRST] = max(0.0, float(m_tensor[i, A_THIRST]))
        m_tensor[eid, M_RESOURCE_WATER] = max(
            0.0, water - DRINK_RESOURCE_COST
        )
        map_dirty = True
    return {"map_dirty": map_dirty} if map_dirty else {}


def animal_instinct_predator_attack(ctx: dict, m_tensor: torch.Tensor,
                                     h_tensor: torch.Tensor,
                                     pop_count_ref: list,
                                     entity_count_ref: list,
                                     device: str, **_) -> dict:
    """
    Predator animals (tiger, wolf) attack nearby humans or prey animals.
    Humans lose HP. Prey animals lose M_HP.
    """
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return {}
    a_mask = _legacy_animal_rows(a_mask, m_tensor)
    if not a_mask.any():
        return {}

    h_mask = ctx["h_mask"]
    dirty  = False

    for i in torch.where(a_mask)[0].tolist():
        species    = int(m_tensor[i, M_TYPE])
        prey_types = ANIMAL_PREY.get(species, set())
        if not prey_types:
            continue
        px = float(m_tensor[i, CX])
        py = float(m_tensor[i, CY])

        # Attack humans
        if AGENT_TYPE_HUMAN in prey_types and h_mask.any():
            h_pos  = h_tensor[h_mask, :2]
            center = torch.tensor([[px, py]], dtype=torch.float32,
                                   device=device)
            dists  = pairwise_distances(h_pos, center, space_a=space_slice(h_tensor, h_mask, "h"),
                                        space_b=space_slice(m_tensor, i, "m")).squeeze(1)
            near   = torch.where(h_mask)[0][dists < ANIMAL_PREDATOR_RANGE]
            if near.numel():
                victim = near[0]
                victim_mask = torch.zeros(h_tensor.shape[0], dtype=torch.bool, device=h_tensor.device)
                victim_mask[int(victim)] = True
                apply_human_damage(victim_mask, h_tensor, ANIMAL_PREDATOR_ATTACK_DAMAGE, hp_col=HP)
                h_tensor[victim, THREAT] = 100.0

        # Attack prey animals
        for prey_t in prey_types - {AGENT_TYPE_HUMAN}:
            prey_mask = a_mask & (m_tensor[:, M_TYPE] == prey_t)
            if not prey_mask.any():
                continue
            p_pos  = m_tensor[prey_mask][:, [CX, CY]].reshape(-1, 2)
            center = torch.tensor([[px, py]], dtype=torch.float32, device=device)
            dists  = pairwise_distances(p_pos, center, space_a=space_slice(m_tensor, prey_mask, "m"),
                                        space_b=space_slice(m_tensor, i, "m")).squeeze(1)
            hits   = torch.where(prey_mask)[0][dists < ANIMAL_PREDATOR_RANGE]
            if hits.numel():
                target_mask = torch.zeros(m_tensor.shape[0], dtype=torch.bool, device=m_tensor.device)
                target_mask[int(hits[0])] = True
                apply_entity_damage(target_mask, m_tensor, ANIMAL_PREDATOR_ATTACK_DAMAGE, hp_col=M_HP)

    return {"h_mask": h_tensor[:, TYPE] > AGENT_TYPE_EMPTY}
'''


REFERENCE_MOVE = r'''
def animal_instinct_move(ctx: dict, m_tensor: torch.Tensor,
                          device: str, **_) -> None:
    """
    Brownian motion for all live animals.
    Each species uses its own ANIMAL_MOVE_STEP from genesis_config.
    Predators bias toward nearest prey within detection range.
    """
    a_mask = ctx.get("a_mask")
    if a_mask is None or not a_mask.any():
        return
    a_mask = _legacy_animal_rows(a_mask, m_tensor)
    if not a_mask.any():
        return
    h_tensor = ctx.get("h_tensor_ref")   # passed via engine kwargs

    a_idx = torch.where(a_mask)[0]
    for i in a_idx.tolist():
        species = int(m_tensor[i, M_TYPE])
        step    = ANIMAL_MOVE_STEP.get(species, 2.0)
        dx = (random.random() - 0.5) * step * 2
        dy = (random.random() - 0.5) * step * 2
        lake_home_eid = -1

        # Predator attraction toward nearest prey (human or prey animal)
        prey_types = ANIMAL_PREY.get(species, set())
        if prey_types:
            pos = m_tensor[i, [CX, CY]]
            target_kind, target_slot, target_dist = nearest_predator_target(
                h_tensor,
                m_tensor,
                float(pos[0]),
                float(pos[1]),
                prey_types,
                max_distance=float(ANIMAL_PREDATOR_RANGE * 3),
                exclude_entity_slot=i,
            )
            if target_slot != -1 and target_dist < ANIMAL_PREDATOR_RANGE * 3:
                if target_kind == "human" and h_tensor is not None:
                    target_pos = h_tensor[target_slot, :2]
                else:
                    target_pos = m_tensor[target_slot, [CX, CY]]
                d = target_pos - pos
                n = d.norm().clamp(min=1e-6)
                dx += float(d[0] / n) * step
                dy += float(d[1] / n) * step

        if species == M_FISH:
            lake_mask = m_tensor[:, M_TYPE] == M_LAKE
            if lake_mask.any():
                lake_idx = torch.where(lake_mask)[0]
                lake_pos = m_tensor[lake_idx][:, [CX, CY]]
                pos      = m_tensor[i, [CX, CY]]
                nearest  = (((lake_pos - pos).pow(2)).sum(dim=1)).sqrt().argmin()
                lake_home_eid = int(lake_idx[nearest])
                center = m_tensor[lake_home_eid, [CX, CY]]
                home_r = max(4.0, float(m_tensor[lake_home_eid, SCALE]) * 0.8)
                delta  = center - pos
                dist   = float(delta.norm())
                if dist > home_r:
                    unit = delta / delta.norm().clamp(min=1e-6)
                    dx += float(unit[0]) * step * 2.5
                    dy += float(unit[1]) * step * 2.5

        m_tensor[i, CX] = float(m_tensor[i, CX]) + dx
        m_tensor[i, CY] = float(m_tensor[i, CY]) + dy
        x0, y0, x1, y1 = _world_limits()
        m_tensor[i, CX] = max(x0, min(x1, float(m_tensor[i, CX])))
        m_tensor[i, CY] = max(y0, min(y1, float(m_tensor[i, CY])))
        if species == M_FISH and lake_home_eid != -1:
            pos    = m_tensor[i, [CX, CY]]
            center = m_tensor[lake_home_eid, [CX, CY]]
            delta  = pos - center
            dist   = float(delta.norm())
            max_r  = max(4.0, float(m_tensor[lake_home_eid, SCALE]) * 0.95)
            if dist > max_r:
                unit = delta / delta.norm().clamp(min=1e-6)
                clamped = center + unit * max_r
                m_tensor[i, CX] = float(clamped[0].clamp(x0, x1))
                m_tensor[i, CY] = float(clamped[1].clamp(y0, y1))


'''


def _reference():
    """The cddfa86 functions, defined against the live modules' globals (constants, map_geo, torch)."""
    space = dict(vars(queries))
    space.update(vars(resolver))
    exec(compile(REFERENCE_QUERIES, "cddfa86:queries", "exec"), space)
    ref = {name: space[name] for name in ("pick_best_entity", "point_distance", "nearest_geo_entity", "nearest_entity_from_ids", "nearest_human_from_mask")}
    animals = dict(vars(it))
    animals["_nearest_geo_entity"] = ref["nearest_geo_entity"]
    exec(compile(REFERENCE_INSTINCTS, "cddfa86:instincts_and_tools", "exec"), animals)
    exec(compile(REFERENCE_MOVE, "cddfa86:move", "exec"), animals)
    ref["animal_instinct_move"] = animals["animal_instinct_move"]
    ref["animal_instinct_drink"] = animals["animal_instinct_drink"]
    ref["animal_instinct_predator_attack"] = animals["animal_instinct_predator_attack"]
    return ref


REF = _reference()


def bits(value):
    """The float's exact bits (so 0.0 / -0.0 and every last-place difference count)."""
    return struct.pack("<d", float(value)).hex()


def same_tensor(a, b):
    """Bit-identical tensors (NaN == NaN when the bits agree)."""
    return a.shape == b.shape and a.dtype == b.dtype and torch.equal(a.contiguous().view(torch.int32), b.contiguous().view(torch.int32))


# ---------------------------------------------------------------------------------------------------------------- scenes
def positions(rng, n, kind):
    """``n`` (x, y) pairs: ``grid`` puts many on a few integer points (exact ties, Pythagorean triples), ``far`` near 1e6, else uniform."""
    if kind == "grid":
        return [(float(rng.randint(-6, 6)) * 5.0, float(rng.randint(-6, 6)) * 5.0) for _ in range(n)]
    if kind == "far":
        return [(1.0e6 + rng.uniform(-50.0, 50.0), -1.0e6 + rng.uniform(-50.0, 50.0)) for _ in range(n)]
    return [(rng.uniform(-500.0, 500.0), rng.uniform(-500.0, 500.0)) for _ in range(n)]


def m_scene(rng, kind, rows=200):
    m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS), dtype=torch.float32)
    for slot, (x, y) in enumerate(positions(rng, rows, kind)):
        m[slot, cfg.CX], m[slot, cfg.CY] = x, y
    return m


def query_point(rng, kind):
    if kind == "grid":
        return float(rng.randint(-6, 6)) * 5.0, float(rng.randint(-6, 6)) * 5.0
    if kind == "far":
        return float(torch.tensor(1.0e6 + rng.uniform(-60.0, 60.0))), float(torch.tensor(-1.0e6 + rng.uniform(-60.0, 60.0)))
    return rng.uniform(-600.0, 600.0), rng.uniform(-600.0, 600.0)


class NearestFromIdsTests(unittest.TestCase):
    def check(self, m, px, py, ids):
        got = queries.nearest_entity_from_ids(m, px, py, ids)
        want = REF["nearest_entity_from_ids"](m, px, py, ids)
        self.assertEqual((got[0], bits(got[1])), (want[0], bits(want[1])), f"p=({px!r}, {py!r}) ids={ids!r}")

    def test_the_same_slot_and_distance_bits_as_cddfa86_over_random_scenes(self):
        rng = random.Random(661)
        for case in range(1500):
            kind = ("grid", "uniform", "far")[case % 3]
            m = m_scene(rng, kind)
            px, py = query_point(rng, kind)
            n = rng.choice((0, 1, 3, 7, 8, 9, 20, 64, 150))
            ids = [rng.randrange(200) for _ in range(n)]
            if case % 5 == 0:
                ids = sorted(set(ids))
            if case % 7 == 0 and ids:
                ids = ids + ids[: max(1, n // 3)]                              # duplicates: the first occurrence wins
            self.check(m, px, py, torch.tensor(ids, dtype=torch.long) if case % 2 else ids)

    def test_exact_ties_go_to_the_first_candidate_in_the_callers_order(self):
        m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS))
        triples = [(3.0, 4.0), (-4.0, 3.0), (5.0, 0.0), (0.0, -5.0), (-3.0, -4.0), (4.0, -3.0)]   # all exactly 5 from the origin
        for slot in range(40):
            m[slot, cfg.CX], m[slot, cfg.CY] = (30.0 + slot, 30.0) if slot >= len(triples) else triples[slot]
        for order in (list(range(40)), list(range(39, -1, -1)), [7, 3, 9, 1, 0, 2, 4, 5] + list(range(10, 40))):
            self.check(m, 0.0, 0.0, order)
            want = REF["nearest_entity_from_ids"](m, 0.0, 0.0, order)[0]
            self.assertEqual(queries.nearest_entity_from_ids(m, 0.0, 0.0, order)[0], want)
            self.assertEqual(want, next(s for s in order if s < len(triples)))

    def test_non_finite_positions_and_queries_behave_as_before(self):
        rng = random.Random(662)
        for case in range(300):
            m = m_scene(rng, "uniform")
            for slot in rng.sample(range(200), 5):
                m[slot, rng.choice((cfg.CX, cfg.CY))] = rng.choice((float("nan"), float("inf"), -float("inf")))
            px, py = query_point(rng, "uniform")
            if case % 4 == 0:
                px = rng.choice((float("nan"), float("inf")))
            self.check(m, px, py, list(range(0, 200, rng.choice((1, 2, 3)))))

    def test_tensor_query_points_and_huge_values_behave_as_before(self):
        m = m_scene(random.Random(663), "uniform")
        ids = list(range(100))
        self.check(m, torch.tensor(3.25), torch.tensor(-7.5), ids)              # float32 tensor arithmetic in the exact scan: no prefilter
        self.check(m, 1.0e200, 1.0e200, ids)                                   # float64 squares overflow: every candidate survives
        self.check(m, 2 ** 60, 5, ids)                                          # an int beyond 2**53: no prefilter
        self.check(m, 12, -40, ids)

    def test_a_long_candidate_list_is_scanned_exactly_only_near_its_minimum(self):
        m = m_scene(random.Random(664), "uniform")
        calls = []
        real = queries.point_distance
        with mock.patch.object(queries, "point_distance", side_effect=lambda *a: calls.append(a) or real(*a)):
            queries.nearest_entity_from_ids(m, 10.0, 20.0, list(range(64)))
        self.assertLessEqual(len(calls), 4, "the exact scan runs only on the survivors (and once for the returned distance)")

    def test_the_prefilter_test_bites_when_the_margin_is_wrong(self):
        """The comparison above would catch a prefilter that drops the true minimum."""
        rng = random.Random(665)
        mismatches = 0
        with mock.patch.object(queries, "PREFILTER_MARGIN", -1e-3):
            for _ in range(50):
                m = m_scene(rng, "uniform")
                px, py = query_point(rng, "uniform")
                ids = list(range(64))
                mismatches += queries.nearest_entity_from_ids(m, px, py, ids)[0] != REF["nearest_entity_from_ids"](m, px, py, ids)[0]
        self.assertGreater(mismatches, 25)


class NearestHumanTests(unittest.TestCase):
    def test_the_same_slot_and_distance_bits_as_cddfa86_over_random_scenes(self):
        rng = random.Random(671)
        for case in range(1500):
            kind = ("grid", "uniform", "far")[case % 3]
            h = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS))
            for slot, (x, y) in enumerate(positions(rng, cfg.MAX_HUMANS, kind)):
                h[slot, cfg.X], h[slot, cfg.Y] = x, y
            if case % 11 == 0:
                h[rng.randrange(cfg.MAX_HUMANS), cfg.X] = float("nan")
            mask = torch.tensor([rng.random() < rng.choice((0.0, 0.05, 0.3, 1.0)) for _ in range(cfg.MAX_HUMANS)])
            px, py = query_point(rng, kind)
            got = queries.nearest_human_from_mask(h, px, py, mask)
            want = REF["nearest_human_from_mask"](h, px, py, mask)
            self.assertEqual((got[0], bits(got[1])), (want[0], bits(want[1])))
            limit = want[1] if case % 2 else rng.choice((None, 0.0, 10.0, 1e9))  # exactly the best distance: kept, as before
            got = queries.nearest_human_from_mask(h, px, py, mask, max_distance=limit)
            want = REF["nearest_human_from_mask"](h, px, py, mask, max_distance=limit)
            self.assertEqual((got[0], bits(got[1])), (want[0], bits(want[1])))


class GeoFixture(unittest.TestCase):
    def setUp(self):
        saved_geo, saved_tiles = dict(map_geo.MAP_GEO), dict(map_geo.TILE_TO_ENTITY)
        map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear()
        map_geo.configure_window(352, 352, (-160, -160), sparse=True)

        def restore():
            map_geo.reset_window()
            map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear()
            map_geo.MAP_GEO.update(saved_geo); map_geo.TILE_TO_ENTITY.update(saved_tiles)
        self.addCleanup(restore)
        self.m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS))

    def place(self, slot, kind, x, y, scale, water=0.0):
        m = self.m
        m[slot, cfg.M_TYPE], m[slot, cfg.CX], m[slot, cfg.CY], m[slot, cfg.SCALE] = float(kind), x, y, scale
        m[slot, cfg.M_RESOURCE_WATER] = water
        map_geo.register_entity(slot, "circle", x, y, scale, device="cpu")

    def landscape(self, rng, count=40):
        kinds = (cfg.M_LAKE, cfg.M_WELL, cfg.M_GRASS, cfg.M_FOREST)
        for slot in range(count):
            self.place(slot, rng.choice(kinds), rng.uniform(-1200.0, 1200.0), rng.uniform(-1200.0, 1200.0), rng.choice((1.0, 4.0, 12.0, 30.0)),
                       water=rng.choice((0.0, 1.0, 2.5, 50.0)))


class GeoPossibleTests(GeoFixture):
    def test_false_only_where_the_cddfa86_query_finds_nothing(self):
        rng = random.Random(681)
        self.landscape(rng)
        points = [(rng.uniform(-1300.0, 1300.0), rng.uniform(-1300.0, 1300.0)) for _ in range(3000)]
        points += [(float(self.m[s, cfg.CX]) + 24.0, float(self.m[s, cfg.CY])) for s in range(40)]                 # exactly on the radius
        points += [(float(self.m[s, cfg.CX]) + math.nextafter(24.0, 99.0), float(self.m[s, cfg.CY])) for s in range(40)]
        points += [(float("nan"), 0.0), (0.0, float("inf"))]
        drinkable = it.DRINKABLE_TYPES
        for radius in (24.0, 0.0, -1.0, float("nan")):
            possible = queries.nearest_geo_entity_possible(self.m, points, drinkable, radius)
            self.assertEqual(len(possible), len(points))
            found = []
            for x, y in points:
                try:
                    found.append(REF["nearest_geo_entity"](self.m, x, y, drinkable, radius))
                except (ValueError, OverflowError):
                    found.append("raises")                                  # a NaN / inf point: the exact query must still run (and raise)
            for (x, y), ok, eid in zip(points, possible, found):
                if not ok:
                    self.assertEqual(eid, -1, f"({x!r}, {y!r}) radius {radius}: the query finds {eid}")
            if radius == 24.0:
                self.assertGreater(sum(1 for ok in possible if not ok), 2000, "most points are far from water: the query is skipped there")
                self.assertGreater(sum(1 for eid in found if eid not in (-1, "raises")), 20)
        self.assertEqual(queries.nearest_geo_entity_possible(self.m, [], drinkable, 24.0), [])

    def test_a_point_covered_by_water_is_possible_with_any_radius(self):
        self.place(3, cfg.M_LAKE, 100.0, 100.0, 30.0, water=5.0)
        self.assertEqual(REF["nearest_geo_entity"](self.m, 100.0, 100.0, it.DRINKABLE_TYPES, 0.0), 3)
        self.assertEqual(queries.nearest_geo_entity_possible(self.m, [(100.0, 100.0), (900.0, 900.0)], it.DRINKABLE_TYPES, 0.0), [True, False])

    def test_geo_ids_of_types_keeps_the_map_geo_order(self):
        self.landscape(random.Random(682))
        want = [eid for eid in map_geo.MAP_GEO if eid < cfg.MAX_ENTITIES and int(self.m[eid, cfg.M_TYPE]) in it.DRINKABLE_TYPES]
        self.assertEqual(map_geo.geo_ids_of_types(self.m, it.DRINKABLE_TYPES, cfg.MAX_ENTITIES), want)
        self.assertEqual(map_geo.geo_ids_of_types(self.m, None, cfg.MAX_ENTITIES), [eid for eid in map_geo.MAP_GEO if eid < cfg.MAX_ENTITIES])


# ---------------------------------------------------------------------------------------------------------------- the two instincts
def animal_scene(rng, m, h, *, animals=60, humans=12, kind="uniform", spaces=False):
    """Predators (tiger, wolf), prey (sheep, deer) and a few others in the rows after the landscape; humans in h. Returns (a_mask, h_mask)."""
    species = (cfg.M_TIGER, cfg.M_WOLF, cfg.M_SHEEP, cfg.M_DEER, cfg.M_SHEEP, cfg.M_DEER, cfg.M_FISH)
    first = 100
    for k, (x, y) in enumerate(positions(rng, animals, kind)):
        slot = first + k
        m[slot, cfg.M_TYPE], m[slot, cfg.CX], m[slot, cfg.CY] = float(rng.choice(species)), x / 8.0, y / 8.0
        m[slot, cfg.M_HP] = rng.choice((0.0, 10.0, 100.0))
        m[slot, cfg.A_THIRST] = rng.choice((5.0, 20.0, 21.0, 60.0))
        m[slot, cfg.M_SPACE] = float(rng.choice((0, 1))) if spaces else 0.0
    for slot, (x, y) in enumerate(positions(rng, humans, kind)):
        h[slot, cfg.TYPE], h[slot, cfg.X], h[slot, cfg.Y], h[slot, cfg.HP] = float(cfg.AGENT_TYPE_HUMAN), x / 8.0, y / 8.0, 100.0
        h[slot, cfg.H_SPACE] = float(rng.choice((0, 1))) if spaces else 0.0
    a_mask = (m[:, cfg.M_TYPE] >= cfg.M_SHEEP) & (m[:, cfg.M_TYPE] <= cfg.M_FISH)
    return a_mask, h[:, cfg.TYPE] == float(cfg.AGENT_TYPE_HUMAN)


class MoveTests(unittest.TestCase):
    def test_exact_random_scenes_and_cost_shape(self):
        for seed in range(20):
            rng = random.Random(seed)
            m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS), dtype=torch.float32)
            h = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS), dtype=torch.float32)
            mask, _ = animal_scene(rng, m, h, animals=60, humans=12, kind=("grid", "uniform", "far")[seed % 3])
            m[0, cfg.M_TYPE], m[0, cfg.CX], m[0, cfg.CY], m[0, cfg.SCALE] = cfg.M_LAKE, 0, 0, 25
            results = []
            for fn in (REF["animal_instinct_move"], it.animal_instinct_move):
                copy = m.clone()
                random.seed(seed + 250)
                with mock.patch.object(it, "_legacy_animal_rows", side_effect=lambda a, m: a), mock.patch.object(it, "_creatures_enabled", return_value=True):
                    fn({"a_mask": mask, "h_tensor_ref": h}, copy, device="cpu")
                results.append((copy, random.getstate()))
            self.assertTrue(same_tensor(results[0][0], results[1][0]), seed)
            self.assertEqual(results[0][1], results[1][1])
            with mock.patch.object(it, "_legacy_animal_rows", side_effect=lambda a, m: a), mock.patch.object(it, "_creatures_enabled", return_value=True), mock.patch.object(it, "nearest_predator_target", wraps=it.nearest_predator_target) as hunt:
                it.animal_instinct_move({"a_mask": mask, "h_tensor_ref": h}, m.clone(), device="cpu")
                self.assertEqual(hunt.call_count, 0)

    def test_nonfinite_positions_use_reference(self):
        m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS))
        h = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS))
        m[100, cfg.M_TYPE], m[100, cfg.M_HP], m[100, cfg.CX] = cfg.M_WOLF, 100, float("nan")
        mask = torch.zeros(cfg.MAX_ENTITIES, dtype=torch.bool)
        mask[100] = True
        expected = m.clone()
        random.seed(45)
        REF["animal_instinct_move"]({"a_mask": mask, "h_tensor_ref": h}, expected, device="cpu")
        state = random.getstate()
        actual = m.clone()
        random.seed(45)
        with mock.patch.object(it, "_creatures_enabled", return_value=True), mock.patch.object(it, "_legacy_animal_rows", side_effect=lambda a, m: a), mock.patch.object(it, "_animal_move_reference", wraps=it._animal_move_reference) as fallback:
            it.animal_instinct_move({"a_mask": mask, "h_tensor_ref": h}, actual, device="cpu")
            self.assertEqual(fallback.call_count, 1)
        self.assertTrue(same_tensor(expected, actual))
        self.assertEqual(state, random.getstate())

    def test_predator_as_prey_still_observes_moved_rows(self):
        m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS))
        h = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS))
        for slot, species, x in ((100, cfg.M_TIGER, 20), (101, cfg.M_WOLF, 10), (102, cfg.M_SHEEP, 5)):
            m[slot, cfg.M_TYPE], m[slot, cfg.M_HP], m[slot, cfg.CX] = species, 100, x
        mask = torch.zeros(cfg.MAX_ENTITIES, dtype=torch.bool)
        mask[100:103] = True
        with mock.patch.dict(it.ANIMAL_PREY, {cfg.M_WOLF: {cfg.M_TIGER}}), mock.patch.object(it, "_creatures_enabled", return_value=True), mock.patch.object(it, "_legacy_animal_rows", side_effect=lambda a, m: a):
            expected, actual = m.clone(), m.clone()
            random.seed(88)
            REF["animal_instinct_move"]({"a_mask": mask, "h_tensor_ref": h}, expected, device="cpu")
            state = random.getstate()
            random.seed(88)
            it.animal_instinct_move({"a_mask": mask, "h_tensor_ref": h}, actual, device="cpu")
        self.assertTrue(same_tensor(expected, actual))
        self.assertEqual(state, random.getstate())


class PredatorAttackTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("EDEN_CREATURES", None)

    def both(self, m, h, a_mask, h_mask):
        results = []
        for fn in (REF["animal_instinct_predator_attack"], it.animal_instinct_predator_attack):
            mm, hh = m.clone(), h.clone()
            out = fn({"a_mask": a_mask.clone(), "h_mask": h_mask.clone()}, mm, h_tensor=hh, pop_count_ref=[0], entity_count_ref=[0], device="cpu")
            results.append((mm, hh, out))
        (m0, h0, out0), (m1, h1, out1) = results
        self.assertTrue(same_tensor(m0, m1) and same_tensor(h0, h1))
        self.assertTrue(torch.equal(out0["h_mask"], out1["h_mask"]))
        return m0, h0

    def test_the_same_damage_as_cddfa86_over_random_scenes(self):
        rng = random.Random(691)
        hits = 0
        for case in range(120):
            for spaces in (False, True):
                with mock.patch.dict(os.environ, {"EDEN_SPACES": "1" if spaces else "0"}):
                    m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS))
                    h = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS))
                    a_mask, h_mask = animal_scene(rng, m, h, kind=("grid", "uniform", "far")[case % 3], spaces=spaces)
                    m_out, h_out = self.both(m, h, a_mask, h_mask)
                    hits += int((m_out[:, cfg.M_HP] != m[:, cfg.M_HP]).sum()) + int((h_out[:, cfg.HP] != h[:, cfg.HP]).sum())
        self.assertGreater(hits, 100, "the scenes really produce attacks on humans and prey")

    def test_no_humans_no_prey_and_no_animals_behave_as_before(self):
        rng = random.Random(692)
        m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS))
        h = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS))
        a_mask, h_mask = animal_scene(rng, m, h, kind="grid")
        self.both(m, h, a_mask, torch.zeros_like(h_mask))
        only_predators = a_mask & ((m[:, cfg.M_TYPE] == cfg.M_TIGER) | (m[:, cfg.M_TYPE] == cfg.M_WOLF))
        self.both(m, h, only_predators, h_mask)
        self.assertEqual(it.animal_instinct_predator_attack({"a_mask": torch.zeros_like(a_mask), "h_mask": h_mask}, m, h_tensor=h,
                                                            pop_count_ref=[0], entity_count_ref=[0], device="cpu"), {})

    def test_the_distances_are_computed_once_per_tick_not_per_predator(self):
        rng = random.Random(693)
        m = torch.zeros((cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS))
        h = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS))
        a_mask, h_mask = animal_scene(rng, m, h, animals=80, kind="grid")
        predators = int(((m[:, cfg.M_TYPE] == cfg.M_TIGER) | (m[:, cfg.M_TYPE] == cfg.M_WOLF)).sum())
        self.assertGreater(predators, 10)
        real = it.pairwise_distances
        calls = []
        with mock.patch.object(it, "pairwise_distances", side_effect=lambda *a, **k: calls.append(1) or real(*a, **k)):
            it.animal_instinct_predator_attack({"a_mask": a_mask, "h_mask": h_mask}, m, h_tensor=h, pop_count_ref=[0], entity_count_ref=[0], device="cpu")
        self.assertLessEqual(len(calls), 3, "one matrix for the humans and one per prey type")

    def test_a_batched_distance_matrix_equals_the_one_point_calls_bit_for_bit(self):
        """What the batching relies on: column k of cdist(a, B) is cdist(a, B[k]) exactly (EXACT_MODE, with and without spaces)."""
        rng = random.Random(694)
        from harness.numerics import pairwise_distances
        for case in range(200):
            kind = ("grid", "uniform", "far")[case % 3]
            a = torch.tensor(positions(rng, rng.choice((1, 5, 40, 300)), kind), dtype=torch.float32)
            b = torch.tensor(positions(rng, rng.choice((1, 3, 30)), kind), dtype=torch.float32)
            sa = torch.tensor([float(rng.choice((0, 1))) for _ in range(len(a))])
            sb = torch.tensor([float(rng.choice((0, 1))) for _ in range(len(b))])
            for spaced in (False, True):
                full = pairwise_distances(a, b, space_a=sa if spaced else None, space_b=sb if spaced else None)
                for k in range(len(b)):
                    one = pairwise_distances(a, b[k:k + 1], space_a=sa if spaced else None, space_b=sb[k] if spaced else None)
                    self.assertTrue(same_tensor(full[:, k:k + 1].contiguous(), one))


class DrinkTests(GeoFixture):
    def run_both(self, a_mask):
        results = []
        for fn in (REF["animal_instinct_drink"], it.animal_instinct_drink):
            m = self.m.clone()
            out = fn({"a_mask": a_mask.clone()}, m)
            results.append((m, out))
        (m0, out0), (m1, out1) = results
        self.assertTrue(same_tensor(m0, m1))
        self.assertEqual(out0, out1)
        return m0

    def test_the_same_drinks_and_water_as_cddfa86_over_random_scenes(self):
        rng = random.Random(701)
        drank = 0
        for case in range(60):
            map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear()
            self.m.zero_()
            self.landscape(rng, count=30)
            h = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS))
            a_mask, _ = animal_scene(rng, self.m, h, animals=90, kind="uniform")
            for slot in range(100, 190, 3):                                    # a third of them stand at a water body's edge
                water = rng.randrange(30)
                self.m[slot, cfg.CX] = float(self.m[water, cfg.CX]) + rng.choice((0.0, 10.0, 24.0, 30.0 + float(self.m[water, cfg.SCALE])))
                self.m[slot, cfg.CY] = float(self.m[water, cfg.CY])
            out = self.run_both(a_mask)
            drank += int((out[100:190, cfg.A_THIRST] < self.m[100:190, cfg.A_THIRST]).sum())
        self.assertGreater(drank, 50, "the scenes really make animals drink")

    def test_a_well_drained_earlier_in_the_tick_is_dry_for_the_next_animal(self):
        self.place(0, cfg.M_WELL, 200.0, 200.0, 4.0, water=1.5)
        for slot in (100, 101, 102):
            self.m[slot, cfg.M_TYPE], self.m[slot, cfg.CX], self.m[slot, cfg.CY], self.m[slot, cfg.A_THIRST] = float(cfg.M_SHEEP), 205.0, 200.0, 50.0
        out = self.run_both((self.m[:, cfg.M_TYPE] == cfg.M_SHEEP))
        self.assertEqual([float(out[s, cfg.A_THIRST]) for s in (100, 101, 102)], [15.0, 15.0, 50.0])
        self.assertEqual(float(out[0, cfg.M_RESOURCE_WATER]), 0.0)

    def test_the_query_is_skipped_where_nothing_drinkable_is_near(self):
        self.place(0, cfg.M_LAKE, 0.0, 0.0, 20.0, water=100.0)
        for k, slot in enumerate(range(100, 140)):
            self.m[slot, cfg.M_TYPE], self.m[slot, cfg.CX], self.m[slot, cfg.CY], self.m[slot, cfg.A_THIRST] = float(cfg.M_DEER), 500.0 + k, 500.0, 50.0
        self.m[140, cfg.M_TYPE], self.m[140, cfg.CX], self.m[140, cfg.CY], self.m[140, cfg.A_THIRST] = float(cfg.M_DEER), 10.0, 0.0, 50.0
        a_mask = self.m[:, cfg.M_TYPE] == cfg.M_DEER
        real = it._nearest_geo_entity
        calls = []
        with mock.patch.object(it, "_nearest_geo_entity", side_effect=lambda *a: calls.append(a) or real(*a)):
            m = self.m.clone()
            it.animal_instinct_drink({"a_mask": a_mask}, m)
        self.assertEqual(len(calls), 1, "only the deer at the lake asks")
        self.assertEqual(float(m[140, cfg.A_THIRST]), 15.0)
        self.run_both(a_mask)


# ---------------------------------------------------------------------------------------------------------------- the engine, 300 ticks
try:
    from test_startup_preservation import backend, _test_storage  # noqa: F401,E402  (isolated data root; imports map_test)
    from test_map_contract import AsyncRegistryIsolation  # noqa: E402
except Exception as exc:  # pragma: no cover - reported by the test below
    backend, AsyncRegistryIsolation, _IMPORT_ERROR = None, object, exc
else:
    _IMPORT_ERROR = None

TICKS, EVERY, SEED = 300, 50, 6602
QUERY_MODULES = ("systems.perception", "systems.perception.context", "systems.perception.ops", "systems.combat.hunting", "instincts_and_tools")


def state_hash(engine):
    state = engine.state
    digest = hashlib.sha256()
    for tensor in (state.h_tensor, state.m_tensor):
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    digest.update(json.dumps([list(engine._human_uid_by_slot), list(engine._entity_uid_by_slot)], default=str).encode())
    digest.update(repr(random.getstate()).encode())
    digest.update(torch.get_rng_state().numpy().tobytes())
    return digest.hexdigest()


class EngineDeterminismTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """playable_village (a well, villagers) plus a field of tigers, wolves, sheep and deer, thirsty, around the well and the villagers."""

    async def world(self):
        engine = backend.engine
        engine.reset_world()
        random.seed(SEED)
        torch.manual_seed(SEED)
        await backend.create_genesis(engine, map_name="playable_village")
        m = engine.state.m_tensor
        wells = [s for s in range(cfg.MAX_ENTITIES) if int(m[s, cfg.M_TYPE]) == cfg.M_WELL]
        humans = [s for s in range(cfg.MAX_HUMANS) if int(engine.state.h_tensor[s, cfg.TYPE]) == cfg.AGENT_TYPE_HUMAN]
        self.assertTrue(wells and humans)
        wx, wy = float(m[wells[0], cfg.CX]), float(m[wells[0], cfg.CY])
        m[wells[0], cfg.M_RESOURCE_WATER] = 5.5                                    # the village well starts dry: six drinks, then dry again
        hx, hy = float(engine.state.h_tensor[humans[0], cfg.X]), float(engine.state.h_tensor[humans[0], cfg.Y])
        rng = random.Random(SEED)
        field = [(cfg.M_TIGER, 3), (cfg.M_WOLF, 5), (cfg.M_SHEEP, 14), (cfg.M_DEER, 10)]
        for species, count in field:
            for k in range(count):
                cx, cy = (wx, wy) if k % 2 else (hx, hy)
                slot = it.animal_born(m, engine._entity_count_ref, cx + rng.uniform(-40.0, 40.0), cy + rng.uniform(-40.0, 40.0), species, device="cpu")
                if slot != -1:
                    m[slot, cfg.A_THIRST] = 45.0
        twins = [s for s in range(cfg.MAX_ENTITIES) if int(m[s, cfg.M_TYPE]) == cfg.M_SHEEP][:2]
        m[twins[1], cfg.CX], m[twins[1], cfg.CY] = m[twins[0], cfg.CX], m[twins[0], cfg.CY]   # an exact tie for every predator
        return engine

    def run_arm(self, engine, reference):
        patches = []
        if reference:
            for name in QUERY_MODULES:
                module = sys.modules.get(name)
                for attr, ref in (("nearest_entity_from_ids", REF["nearest_entity_from_ids"]), ("_nearest_entity_from_ids", REF["nearest_entity_from_ids"]),
                                  ("nearest_human_from_mask", REF["nearest_human_from_mask"])):
                    if module is not None and hasattr(module, attr):
                        patches.append(mock.patch.object(module, attr, ref))
            saved = [(entry, entry["fn"]) for entry in engine._registry]
            for entry in engine._registry:
                name = getattr(entry["fn"], "__name__", "")
                if name in ("animal_instinct_drink", "animal_instinct_predator_attack", "animal_instinct_move"):
                    entry["fn"] = REF[name]
            self.addCleanup(lambda: [entry.__setitem__("fn", fn) for entry, fn in saved])
        for patch in patches:
            patch.start()
        try:
            hashes = []
            for tick in range(TICKS + 1):
                if tick % EVERY == 0:
                    hashes.append(state_hash(engine))
                if tick < TICKS:
                    engine.step()
            return hashes
        finally:
            for patch in patches:
                patch.stop()
            if reference:
                for entry, fn in saved:
                    entry["fn"] = fn

    async def test_300_ticks_with_installed_creature_and_window_hooks(self):
        # Separate fresh processes install the hooks before map_test is imported.
        # Inline chunk generation removes background scheduling from the comparison.
        env = {k: v for k, v in os.environ.items() if not k.startswith("EDEN_")}
        env.update({"EDEN_CREATURES": "1", "EDEN_WINDOW": "1", "EDEN_SPACES": "1",
                    "EDEN_PERCEPTION_BOUNDED": "1", "EDEN_MAP_RESOURCES": "1",
                    "EDEN_CHUNK_WORKERS": "0", "EDEN_WORLD_SEED": "6602", "PYTHONHASHSEED": "0"})
        arms = []
        for arm in ("reference", "optimized"):
            env["EDEN_PACE_INSTALLED_ARM"] = arm
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--installed-arm"],
                                    env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])
            line = next((line for line in result.stdout.splitlines() if line.startswith("PACE_HASHES ")), None)
            self.assertIsNotNone(line, result.stdout[-4000:])
            arms.append(json.loads(line.removeprefix("PACE_HASHES ")))
        self.assertGreater(arms[0]["creatures"], 0)
        self.assertGreater(arms[1]["creatures"], 0)
        self.assertEqual(arms[0]["hashes"], arms[1]["hashes"])

    async def test_300_ticks_with_creatures_gate_equal_reference_move(self):
        self.assertIsNone(_IMPORT_ERROR)
        with mock.patch.dict(os.environ, {"EDEN_CREATURES": "1", "EDEN_WINDOW": "1"}):
            reference = self.run_arm(await self.world(), reference=True)
            actual = self.run_arm(await self.world(), reference=False)
        self.assertEqual(actual, reference)

    async def test_300_ticks_with_the_new_queries_equal_300_ticks_with_the_cddfa86_ones(self):
        self.assertIsNone(_IMPORT_ERROR)
        saved_env = mock.patch.dict(os.environ)
        saved_env.start()
        self.addCleanup(saved_env.stop)
        for flag in ("EDEN_CREATURES", "EDEN_WINDOW", "EDEN_SPACES"):
            os.environ.pop(flag, None)
        names = [getattr(e["fn"], "__name__", "") for e in backend.engine._registry]
        self.assertIn("animal_instinct_drink", names)
        self.assertIn("animal_instinct_predator_attack", names)
        reference = self.run_arm(await self.world(), reference=True)
        counts = {"hunt": 0, "drinks": 0, "attacks": 0}
        real_hunt = it.nearest_predator_target
        engine = await self.world()
        saved = [(entry, entry["fn"]) for entry in engine._registry]
        self.addCleanup(lambda: [entry.__setitem__("fn", fn) for entry, fn in saved])

        def counted(fn, key, hit):
            def wrapper(ctx, **kwargs):
                before = (kwargs["m_tensor"][:, cfg.M_HP].clone(), kwargs["h_tensor"][:, cfg.HP].clone()) if key == "attacks" else None
                out = fn(ctx, **kwargs)
                counts[key] += hit(out, kwargs, before)
                return out
            return wrapper
        for entry in engine._registry:
            name = getattr(entry["fn"], "__name__", "")
            if name == "animal_instinct_drink":
                entry["fn"] = counted(entry["fn"], "drinks", lambda out, kw, before: int(bool(out and out.get("map_dirty"))))
            elif name == "animal_instinct_predator_attack":
                entry["fn"] = counted(entry["fn"], "attacks", lambda out, kw, before: int((kw["m_tensor"][:, cfg.M_HP] < before[0]).sum())
                                      + int((kw["h_tensor"][:, cfg.HP] < before[1]).sum()))
        with mock.patch.object(it, "nearest_predator_target", side_effect=lambda *a, **k: counts.__setitem__("hunt", counts["hunt"] + 1) or real_hunt(*a, **k)):
            new = self.run_arm(engine, reference=False)
        for entry, fn in saved:
            entry["fn"] = fn
        self.assertGreater(counts["hunt"], TICKS, f"predators query every tick: {counts}")
        self.assertGreater(counts["drinks"], 0, f"animals drink at the well: {counts}")
        self.assertGreater(counts["attacks"], 0, f"predators hit something: {counts}")
        self.assertEqual(new, reference)


def _standing_benchmark():
    """Recreate the documented post-walk sampling, alternating the reference and current move loops.

    A full run starts six local backends and takes several minutes; run only
    while holding the suite lease. Data and logs are kept in the test root.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import live_smoke_window as smoke
    all_samples = {}
    for run in range(3):
        for arm in ("reference", "optimized"):
            data = _test_storage / ("pace-" + uuid.uuid4().hex)
            data.mkdir()
            flags = dict(smoke.FLAGS, EDEN_WINDOW_DORMANCY="1", EDEN_CREATURES="1",
                         EDEN_PACE_REFERENCE="1" if arm == "reference" else "0")
            backend_process = smoke.Backend(8041, data, flags, shim=True)
            backend_process.command = [sys.executable, str(Path(__file__).resolve()), "--pace-serve"]
            try:
                backend_process.start()
                reply = backend_process.post("/session/new", {"name": "pace"})
                reply.raise_for_status()
                def sample():
                    start_tick = backend_process.get("/frame").json()["tick"]
                    start_time = time.monotonic()
                    time.sleep(10.0)
                    end_tick = backend_process.get("/frame").json()["tick"]
                    return (end_tick - start_tick) / (time.monotonic() - start_time)
                pre = sample()
                smoke.phase_walk(backend_process)
                time.sleep(2.0)
                standing = [sample() for _ in range(3)]
                all_samples.setdefault(arm, []).extend(standing)
                print(json.dumps({"arm": arm, "run": run + 1, "pre_walk_ticks_s": pre,
                                  "standing_ticks_s": standing, "data": str(data)}), flush=True)
            finally:
                backend_process.stop()
    print(json.dumps({arm: {"standing_mean_ticks_s": sum(values) / len(values), "samples": values}
                      for arm, values in all_samples.items()}), flush=True)


if __name__ == "__main__":
    if "--standing-benchmark" in sys.argv:
        _standing_benchmark()
    elif "--pace-serve" in sys.argv:
        if os.environ.get("EDEN_PACE_REFERENCE") == "1":
            for entry in backend.engine._registry:
                if getattr(entry["fn"], "__name__", "") == "animal_instinct_move":
                    entry["fn"] = REF["animal_instinct_move"]
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import live_smoke_window as smoke
        smoke.serve_backend()
    elif "--installed-arm" in sys.argv:
        from simulation.dispatch import DISPATCH
        from harness.window_manager import manager_for
        names = {name for name, _ in DISPATCH.step_hooks}
        assert {"harness_window", "harness_creatures"} <= names, names
        test = EngineDeterminismTests(methodName="runTest")
        engine = asyncio.run(test.world())
        hashes = test.run_arm(engine, reference=os.environ["EDEN_PACE_INSTALLED_ARM"] == "reference")
        print("PACE_HASHES " + json.dumps({"hashes": hashes,
              "creatures": manager_for(engine).creatures.counters["populated"]}), flush=True)
    else:
        unittest.main()
