"""1008 WS-D: EDEN_PERCEPTION_BOUNDED. ``runtime.common.nearest_entity`` takes optional ``max_distance`` / ``space`` and
``human_runtime._build_case`` only passes them when the flag is on (default off, bit-identical to the unbounded behaviour).
Reader located in 1008_frontier_freeze_diff.md: a food row far from every resident changed the resident's memory and movement."""
import os
import random
import tempfile
import unittest
from unittest import mock

import torch

from test_startup_preservation import backend  # noqa: F401  (path setup shared with the other engine tests)
from test_map_contract import AsyncRegistryIsolation
from test_harness_map_resources import world as map_world
import genesis_config as cfg
from runtime import common
from runtime.common import nearest_entity, perception_bounded

FLAG = "EDEN_PERCEPTION_BOUNDED"
SPACE_COL = 31          # any unused column stands in for the future M_SPACE


def legacy_nearest_entity(m_tensor, px, py, type_ids=None, resource_col=None, min_resource=0.0, require_complete=False):
    """The function as it was before this change (copied), used as the flag-off reference."""
    best_eid, best_dist = -1, float("inf")
    for eid in torch.where(m_tensor[:, cfg.M_TYPE] > 0)[0].tolist():
        type_id = int(m_tensor[eid, cfg.M_TYPE])
        if type_ids is not None and type_id not in type_ids:
            continue
        if resource_col is not None and float(m_tensor[eid, resource_col]) <= min_resource:
            continue
        if require_complete and float(m_tensor[eid, cfg.S_BUILD_PROGRESS]) < 100.0:
            continue
        distance = common.dist(px, py, float(m_tensor[eid, cfg.CX]), float(m_tensor[eid, cfg.CY]))
        if distance < best_dist:
            best_dist, best_eid = distance, eid
    return best_eid, best_dist


def toy(rows):
    """rows: (type, x, y, food, space). Returns a small m_tensor."""
    m = torch.zeros(len(rows) + 2, 32)
    for i, (kind, x, y, food, space) in enumerate(rows, start=1):
        m[i, cfg.M_TYPE], m[i, cfg.CX], m[i, cfg.CY] = float(kind), x, y
        m[i, cfg.M_RESOURCE_FOOD], m[i, SPACE_COL] = food, float(space)
    return m


class NearestEntityTests(unittest.TestCase):
    def test_flag_is_off_by_default_and_read_at_call_time(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(FLAG, None)
            self.assertFalse(perception_bounded())
            os.environ[FLAG] = "1"
            self.assertTrue(perception_bounded())
            os.environ[FLAG] = "0"
            self.assertFalse(perception_bounded())

    def test_default_arguments_equal_the_unbounded_legacy_function_on_random_worlds(self):
        rng = random.Random(7)
        kinds = [cfg.M_GRASS, cfg.M_FOREST, cfg.M_LAKE, cfg.M_HOUSE, cfg.M_WALL, cfg.M_TIGER]
        for _ in range(60):
            m = toy([(rng.choice(kinds), rng.uniform(0, 1200), rng.uniform(0, 900), rng.choice([0.0, 5.0, 50.0]), 0)
                     for _ in range(rng.randint(0, 40))])
            px, py = rng.uniform(0, 1200), rng.uniform(0, 900)
            for kwargs in ({}, {"type_ids": {cfg.M_FOREST, cfg.M_GRASS}}, {"type_ids": {cfg.M_LAKE}, "resource_col": cfg.M_RESOURCE_FOOD},
                           {"resource_col": cfg.M_RESOURCE_FOOD, "min_resource": 10.0}):
                self.assertEqual(nearest_entity(m, px, py, **kwargs), legacy_nearest_entity(m, px, py, **kwargs))

    def test_max_distance_is_inclusive_and_drops_farther_rows(self):
        m = toy([(cfg.M_FOREST, 100, 0, 5.0, 0), (cfg.M_FOREST, 300, 0, 5.0, 0)])
        self.assertEqual(nearest_entity(m, 0, 0, max_distance=100.0), (1, 100.0))
        self.assertEqual(nearest_entity(m, 0, 0, max_distance=99.9), (-1, float("inf")))
        m2 = toy([(cfg.M_FOREST, 300, 0, 5.0, 0)])
        self.assertEqual(nearest_entity(m2, 0, 0), (1, 300.0))                     # unbounded still finds the far row
        self.assertEqual(nearest_entity(m2, 0, 0, max_distance=220.0), (-1, float("inf")))
        self.assertEqual(nearest_entity(m2, 0, 0, max_distance=float("inf")), (1, 300.0))

    def test_space_filter_needs_both_space_and_column(self):
        m = toy([(cfg.M_FOREST, 10, 0, 5.0, 1), (cfg.M_FOREST, 50, 0, 5.0, 0)])
        self.assertEqual(nearest_entity(m, 0, 0, space=0, space_col=SPACE_COL), (2, 50.0))
        self.assertEqual(nearest_entity(m, 0, 0, space=1, space_col=SPACE_COL), (1, 10.0))
        self.assertEqual(nearest_entity(m, 0, 0, space=2, space_col=SPACE_COL), (-1, float("inf")))
        self.assertEqual(nearest_entity(m, 0, 0, space=1), (1, 10.0))              # no column: ignored (the space columns do not exist yet)
        self.assertEqual(nearest_entity(m, 0, 0, space_col=SPACE_COL), (1, 10.0))   # no space: ignored


class BuildCaseTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    async def engine_without_food(self):
        engine = await map_world(self._tmp.name, False)
        m = engine.state.m_tensor
        m[:, cfg.M_RESOURCE_FOOD] = 0.0                    # no row anywhere holds food: the only food row is the one the test adds
        self.engine = engine
        h = engine.state.h_tensor
        self.slot = h[:, cfg.TYPE].eq(cfg.AGENT_TYPE_HUMAN).nonzero(as_tuple=False).flatten().tolist()[0]
        self.human_id = engine._human_uid_by_slot[self.slot]
        self.px, self.py = float(h[self.slot, cfg.X]), float(h[self.slot, cfg.Y])
        return engine

    def add_far_food(self, distance):
        m = self.engine.state.m_tensor
        slot = (m[:, cfg.M_TYPE] == 0).nonzero(as_tuple=False).flatten().tolist()[0]
        m[slot] = 0.0
        m[slot, cfg.M_TYPE], m[slot, cfg.CX], m[slot, cfg.CY] = float(cfg.M_FOREST), self.px + distance, self.py
        m[slot, cfg.SCALE], m[slot, cfg.M_RESOURCE_FOOD] = 6.0, 50.0
        self.engine._entity_uid_by_slot[slot] = "far_food"
        self.engine._entity_count_ref[0] = max(int(self.engine._entity_count_ref[0]), slot + 1)
        return slot

    def case(self):
        resident = self.engine.resident_store.get(self.human_id)
        return self.engine.human_agent._build_case(self.engine, self.slot, self.human_id, resident)

    def remembered_food(self):
        return list(self.engine.resident_store.get(self.human_id)["memory"]["known_food_sources"])

    async def test_flag_off_the_far_row_is_the_nearest_food_and_is_remembered(self):
        await self.engine_without_food()
        far = self.add_far_food(cfg.SURVIVAL_SCAN_RADIUS + 200.0)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(FLAG, None)
            case = self.case()
        self.assertEqual(case["food"]["eid"], far)
        self.assertGreater(case["food"]["dist"], cfg.SURVIVAL_SCAN_RADIUS)
        self.assertIn(far, [int(entry["entity_id"]) for entry in self.remembered_food()])

    async def test_flag_on_a_far_row_changes_neither_the_case_nor_the_memory_nor_the_decision(self):
        await self.engine_without_food()
        with mock.patch.dict(os.environ, {FLAG: "1"}):
            before = self.case()
            memory_before = self.remembered_food()
            decision_before = self.engine.human_agent._decide(before)
            self.add_far_food(cfg.SURVIVAL_SCAN_RADIUS + 200.0)
            after = self.case()
            decision_after = self.engine.human_agent._decide(after)
        self.assertEqual(after["food"], before["food"])
        self.assertEqual(after["food"]["eid"], -1)
        self.assertEqual(self.remembered_food(), memory_before)
        self.assertEqual(decision_after, decision_before)

    async def test_flag_on_a_row_inside_the_radius_is_still_found(self):
        await self.engine_without_food()
        near = self.add_far_food(cfg.SURVIVAL_SCAN_RADIUS - 20.0)
        with mock.patch.dict(os.environ, {FLAG: "1"}):
            case = self.case()
        self.assertEqual(case["food"]["eid"], near)
        self.assertIn(near, [int(entry["entity_id"]) for entry in self.remembered_food()])


if __name__ == "__main__":
    unittest.main()
