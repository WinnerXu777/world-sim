"""1008 Gate E: the two O(rows) Python loops (``map_geo.entities_in_radius`` and ``escalation.signals._nearest_entity``) got a
vectorised pre-filter. The pre-filter may only ever drop rows the exact loop would drop too, so every answer, its order and its
tie-breaks must equal the original code, which is kept here as the oracle.  Randomised over ties, boundary distances (a row at
exactly the radius, and one float step either side), several spaces, empty and tiny maps, dead rows, NaN/inf inputs."""
import math
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
import map_geo  # noqa: E402
from harness import spaces  # noqa: E402
from systems.escalation import signals  # noqa: E402


def radius_oracle(cx, cy, radius, m_tensor, m_type_filter, want_space, geo_ids):
    """The pre-Gate-E body of ``map_geo.entities_in_radius``, verbatim."""
    results = []
    for eid in list(geo_ids):
        if eid >= cfg.MAX_ENTITIES:
            continue
        if want_space is not None and int(m_tensor[eid, cfg.M_SPACE]) != want_space:
            continue
        ecx = float(m_tensor[eid, cfg.CX])
        ecy = float(m_tensor[eid, cfg.CY])
        dist = ((ecx - cx) ** 2 + (ecy - cy) ** 2) ** 0.5
        if dist > radius:
            continue
        if m_type_filter is not None:
            et = int(m_tensor[eid, cfg.M_TYPE])
            if et not in m_type_filter:
                continue
        results.append(eid)
    return results


def nearest_oracle(m_tensor, px, py, type_ids, space):
    """The pre-Gate-E body of ``signals._nearest_entity``, verbatim."""
    best_eid = -1
    best_dist = float("inf")
    for eid in (m_tensor[:, cfg.M_TYPE] > 0).nonzero(as_tuple=False).flatten().tolist():
        if int(m_tensor[eid, cfg.M_TYPE]) not in type_ids:
            continue
        if space is not None and int(m_tensor[eid, cfg.M_SPACE]) != space:
            continue
        distance = signals._dist(px, py, float(m_tensor[eid, cfg.CX]), float(m_tensor[eid, cfg.CY]))
        if distance < best_dist:
            best_dist = distance
            best_eid = eid
    return best_eid, best_dist


def f32(value):
    return float(torch.tensor(value, dtype=torch.float32))


def random_world(rng, count, spaces_used=3, types=(1, 2, 5, 8, 10, 13, 24)):
    m = torch.zeros(cfg.MAX_ENTITIES, 32)
    rows = rng.sample(range(cfg.MAX_ENTITIES), count)
    for eid in rows:
        m[eid, cfg.M_TYPE] = rng.choice(types)
        m[eid, cfg.CX] = f32(rng.uniform(-400, 1400))
        m[eid, cfg.CY] = f32(rng.uniform(-400, 1400))
        m[eid, cfg.M_SPACE] = rng.randrange(spaces_used)
    return m, rows


def plant_ties_and_boundaries(rng, m, rows, qx, qy, radius):
    """Move some rows to exactly `radius` from (qx, qy) along the axes and a 3-4-5 diagonal, to duplicates of each other, and to one float32 step off."""
    spare = rows[:]
    rng.shuffle(spare)
    for eid in spare[: max(1, len(spare) // 3)]:
        kind = rng.randrange(6)
        r = radius if math.isfinite(radius) and radius > 0 else rng.uniform(1, 50)
        if kind == 0:
            x, y = qx + r, qy
        elif kind == 1:
            x, y = qx, qy - r
        elif kind == 2:
            x, y = qx + 3 * r / 5, qy + 4 * r / 5
        elif kind == 3:
            x, y = qx - r, qy
        elif kind == 4:
            ref = spare[0]
            x, y = float(m[ref, cfg.CX]), float(m[ref, cfg.CY])          # exact duplicate position -> tie
        else:
            x, y = qx + r, qy
            x = float(torch.nextafter(torch.tensor(f32(x)), torch.tensor(float("inf" if rng.random() < 0.5 else "-inf"))))
        m[eid, cfg.CX] = f32(x)
        m[eid, cfg.CY] = f32(y)


class EntitiesInRadiusExactTests(unittest.TestCase):
    def run_case(self, m, geo_ids, cx, cy, radius, type_filter, want_space):
        with mock.patch.dict(map_geo.MAP_GEO, {}, clear=True):
            for eid in geo_ids:
                map_geo.MAP_GEO[eid] = {"shape": "circle", "cx": 0.0, "cy": 0.0, "r": 1.0, "points": []}
            with mock.patch.object(spaces, "point_space", lambda x, y: want_space):
                got = map_geo.entities_in_radius(cx, cy, radius, m, type_filter)
        want = radius_oracle(cx, cy, radius, m, type_filter, want_space, geo_ids)
        self.assertEqual(got, want, (cx, cy, radius, type_filter, want_space, len(geo_ids)))
        return got

    def test_random_worlds_equal_the_original_including_order(self):
        rng = random.Random(1008)
        nonempty = 0
        for trial in range(400):
            count = rng.choice([0, 1, 3, 7, 8, 9, 40, 150, 300])
            m, rows = random_world(rng, count)
            geo_ids = rows[:]
            rng.shuffle(geo_ids)                                                  # MAP_GEO order is insertion order, not ascending
            if rng.random() < 0.2:
                geo_ids.append(cfg.MAX_ENTITIES + rng.randrange(1, 40))           # a pocket-style id beyond the tensor must be skipped
            qx, qy = f32(rng.uniform(-300, 1300)), f32(rng.uniform(-300, 1300))
            radius = rng.choice([0.0, 0.5, 8.0, 30.0, 96.0, 250.0, 800.0, 5000.0, -3.0, float("inf"), f32(rng.uniform(1, 400))])
            if rows:
                plant_ties_and_boundaries(rng, m, rows, qx, qy, radius)
            type_filter = rng.choice([None, {1}, {2, 5}, {99}, set()])
            want_space = rng.choice([None, 0, 1, 2])
            got = self.run_case(m, geo_ids, qx, qy, radius, type_filter, want_space)
            nonempty += bool(got)
        self.assertGreater(nonempty, 60)                                          # the comparison was not vacuous

    def test_a_row_at_exactly_the_radius_and_one_float_step_either_side(self):
        for radius in (5.0, 96.0, 250.0):
            m = torch.zeros(cfg.MAX_ENTITIES, 32)
            ids = list(range(10, 30))
            for eid in ids:
                m[eid, cfg.M_TYPE] = 2
            m[10, cfg.CX], m[10, cfg.CY] = 100.0 + radius, 200.0                           # exactly at the radius
            m[11, cfg.CX], m[11, cfg.CY] = float(torch.nextafter(torch.tensor(100.0 + radius), torch.tensor(1e9))), 200.0
            m[12, cfg.CX], m[12, cfg.CY] = float(torch.nextafter(torch.tensor(100.0 + radius), torch.tensor(-1e9))), 200.0
            m[13, cfg.CX], m[13, cfg.CY] = 100.0 + 3 * radius / 5, 200.0 + 4 * radius / 5  # 3-4-5 diagonal
            got = self.run_case(m, ids, 100.0, 200.0, radius, None, None)
            self.assertIn(10, got)
            self.assertIn(12, got)
            self.assertNotIn(11, got)

    def test_non_finite_inputs_keep_the_original_semantics(self):
        rng = random.Random(7)
        m, rows = random_world(rng, 40)
        for cx, cy, radius in [(float("nan"), 5.0, 50.0), (5.0, float("inf"), 50.0), (5.0, 5.0, float("nan")), (5.0, 5.0, float("inf"))]:
            self.run_case(m, rows, cx, cy, radius, None, None)
        m[rows[3], cfg.CX] = float("nan")                                                  # a NaN coordinate: the original keeps the row
        self.run_case(m, rows, 100.0, 100.0, 300.0, None, None)

    def test_dead_and_frozen_rows_are_judged_by_position_only(self):
        rng = random.Random(11)
        m, rows = random_world(rng, 60)
        for eid in rows[::2]:
            m[eid, cfg.M_TYPE] = 0                                                          # stale MAP_GEO keys over dead rows
        self.run_case(m, rows, 500.0, 500.0, 400.0, None, None)
        self.run_case(m, rows, 500.0, 500.0, 400.0, {2, 5}, 0)

    def test_the_prefilter_actually_narrows(self):
        rng = random.Random(3)
        m, rows = random_world(rng, 300)
        with mock.patch.dict(map_geo.MAP_GEO, {}, clear=True):
            for eid in rows:
                map_geo.MAP_GEO[eid] = {}
            kept = map_geo._radius_candidates(500.0, 500.0, 30.0, m, cfg.CX, cfg.CY, cfg.MAX_ENTITIES)
        self.assertLess(len(kept), 40)
        self.assertTrue(set(kept) >= set(radius_oracle(500.0, 500.0, 30.0, m, None, None, rows)))


class NearestEntityExactTests(unittest.TestCase):
    def check(self, m, px, py, type_ids, space):
        got = signals._nearest_entity(m, px, py, type_ids=type_ids, space=space)
        want = nearest_oracle(m, px, py, type_ids, space)
        self.assertEqual(got, want, (px, py, type_ids, space))
        return got

    def test_random_worlds_equal_the_original_including_ties(self):
        rng = random.Random(1009)
        found = 0
        for trial in range(500):
            count = rng.choice([0, 1, 5, 7, 8, 12, 60, 200, 400])
            m, rows = random_world(rng, count)
            px, py = f32(rng.uniform(-300, 1300)), f32(rng.uniform(-300, 1300))
            if rows:
                plant_ties_and_boundaries(rng, m, rows, px, py, rng.uniform(1, 200))
                if rng.random() < 0.5:                                                      # equidistant rows on all four sides
                    for eid, (dx, dy) in zip(rows[:4], [(7, 0), (-7, 0), (0, 7), (0, -7)]):
                        m[eid, cfg.CX], m[eid, cfg.CY] = f32(px + dx), f32(py + dy)
                        m[eid, cfg.M_TYPE] = 8
            type_ids = rng.choice([{8, 10}, {1}, {2, 5, 13}, {99}, set(), {24}])
            space = rng.choice([None, 0, 1, 2])
            eid, dist = self.check(m, px, py, type_ids, space)
            found += eid >= 0
        self.assertGreater(found, 150)

    def test_ties_resolve_to_the_lowest_id(self):
        m = torch.zeros(cfg.MAX_ENTITIES, 32)
        for eid in (40, 17, 90, 3, 55, 61, 70, 71, 72, 73):
            m[eid, cfg.M_TYPE] = 8
            m[eid, cfg.CX], m[eid, cfg.CY] = 300.0, 400.0
        self.assertEqual(self.check(m, 310.0, 410.0, {8}, None)[0], 3)

    def test_nothing_matching_and_inf_and_nan_positions(self):
        rng = random.Random(5)
        m, rows = random_world(rng, 50)
        self.assertEqual(self.check(m, 0.0, 0.0, {77}, None), (-1, float("inf")))
        self.assertEqual(self.check(m, float("nan"), 0.0, {8, 10}, None), (-1, float("inf")))
        self.assertEqual(self.check(m, float("inf"), 0.0, {8, 10}, None), nearest_oracle(m, float("inf"), 0.0, {8, 10}, None))
        m[rows[1], cfg.CX] = float("nan")
        self.check(m, 100.0, 100.0, {1, 2, 5, 8, 10, 13, 24}, None)

    def test_dead_rows_never_win(self):
        rng = random.Random(9)
        m, rows = random_world(rng, 80)
        for eid in rows[::3]:
            m[eid, cfg.M_TYPE] = 0
        for _ in range(30):
            self.check(m, f32(rng.uniform(0, 1000)), f32(rng.uniform(0, 1000)), {1, 2, 5, 8, 10, 13, 24}, rng.choice([None, 0, 1]))

    def test_the_prefilter_returns_a_short_list(self):
        rng = random.Random(4)
        m, rows = random_world(rng, 300, types=(8,))
        self.assertLessEqual(len(signals._nearest_candidates(m, 500.0, 500.0, {8}, None)), 3)


if __name__ == "__main__":
    unittest.main()
