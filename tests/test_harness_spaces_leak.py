"""1008 WS-D P3 leak test (Option L): with an actor inside an interior, no query family returns a row, a human, a tile or a wall of the
overworld, and the other way round. The interiors are numerically close enough to the village that a large query radius reaches
across (the village ends at x=384, the smith interior starts at x=620), so these tests fail if a family forgets the space.

Families: nearby_entity_ids, nearest_geo_entity, best_resource_entity, entity_radial_ids, agent_radial_mask, nearest_entity,
entity_at / tile lookups, fire and flood damage to humans, world_contract line-of-sight and standability.
Flags: EDEN_SPACES=1 with EDEN_PERCEPTION_BOUNDED=1; a control test shows the same fixture leaks with the space filter absent."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from test_map_portals import real_world  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
import map_geo  # noqa: E402
from harness import engine_hooks as eh, spaces  # noqa: E402
from runtime.common import nearest_entity  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402
from systems.movement.spatial import is_standable_point, segment_blocked, world_contract  # noqa: E402
from systems.nature.disasters import apply_flood  # noqa: E402
from systems.nature.hazards import apply_fire_tick  # noqa: E402
from systems.perception import (agent_radial_mask, best_resource_entity, entity_radial_ids, nearby_entity_ids,  # noqa: E402
                                nearest_geo_entity)

ON = {"EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1"}
RADIUS = 500.0                       # reaches across the 236 units between the village and the smith interior
SMITH_POINT = (668.0, 60.0)          # inside smith_interior (space 1)
VILLAGE_POINT = (300.0, 60.0)        # inside the village (space 0)
NODES = {cfg.M_RESOURCE_NODE}


class LeakFixture(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        DISPATCH.clear()
        patcher = mock.patch.dict(os.environ, ON, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        eh.install(DISPATCH)
        self.engine = await real_world()
        self.m, self.h = self.engine.state.m_tensor, self.engine.state.h_tensor

    async def asyncTearDown(self):
        eh.uninstall(DISPATCH)
        DISPATCH.clear()
        await super().asyncTearDown()

    def add(self, x, y, m_type, geo_radius=None, cols=None):
        slot = iat.entity_born(self.m, self.engine._entity_count_ref, x, y, m_type, hp=100.0, scale=geo_radius or 4.0,
                               register_geo=False, device=self.engine.state.device, col_vals=cols or {})
        self.assertNotEqual(slot, -1)
        if geo_radius:
            map_geo.register_entity(slot, "circle", x, y, float(geo_radius), device=self.engine.state.device)
        self.addCleanup(map_geo.unregister_entity, slot)
        spaces.refresh(self.engine)
        return slot

    def node(self, x, y, stock):
        return self.add(x, y, cfg.M_RESOURCE_NODE, geo_radius=6.0,
                        cols={cfg.M_NODE_KIND: 1.0, cfg.M_NODE_STOCK: stock, cfg.M_NODE_CAP: 100.0})

    def place_human(self, slot, point):
        self.h[slot, cfg.X], self.h[slot, cfg.Y] = point
        spaces.refresh(self.engine)


class QueryFamilyLeakTests(LeakFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # a depleted node next to the actor and a rich one across the gap, in each space
        self.smith_node = self.node(680.0, 50.0, stock=0.0)
        self.village_node = self.node(370.0, 60.0, stock=90.0)
        self.assertEqual(int(self.m[self.smith_node, cfg.M_SPACE]), 1)
        self.assertEqual(int(self.m[self.village_node, cfg.M_SPACE]), 0)

    async def test_nearby_entity_ids_never_crosses_in_either_direction(self):
        self.assertEqual(nearby_entity_ids(self.m, *SMITH_POINT, RADIUS, NODES), [self.smith_node])
        self.assertEqual(nearby_entity_ids(self.m, *VILLAGE_POINT, RADIUS, NODES), [self.village_node])

    async def test_nearest_geo_entity_never_crosses_in_either_direction(self):
        self.assertEqual(nearest_geo_entity(self.m, *SMITH_POINT, NODES, RADIUS), self.smith_node)
        self.assertEqual(nearest_geo_entity(self.m, *VILLAGE_POINT, NODES, RADIUS), self.village_node)
        self.m[self.smith_node, cfg.M_TYPE] = 0.0                    # remove the only same-space candidate: nothing, not the other space
        self.assertEqual(nearest_geo_entity(self.m, *SMITH_POINT, NODES, RADIUS), -1)

    async def test_best_resource_entity_does_not_pick_the_rich_node_of_the_other_space(self):
        self.assertEqual(best_resource_entity(self.m, *SMITH_POINT, NODES, cfg.M_NODE_STOCK, RADIUS), -1)    # own node is depleted
        self.m[self.smith_node, cfg.M_NODE_STOCK] = 5.0
        self.assertEqual(best_resource_entity(self.m, *SMITH_POINT, NODES, cfg.M_NODE_STOCK, RADIUS), self.smith_node)
        self.m[self.village_node, cfg.M_NODE_STOCK] = 0.0
        self.m[self.smith_node, cfg.M_NODE_STOCK] = 90.0
        self.assertEqual(best_resource_entity(self.m, *VILLAGE_POINT, NODES, cfg.M_NODE_STOCK, RADIUS), -1)  # village node depleted

    async def test_radial_helpers_with_the_actor_space(self):
        self.assertEqual(entity_radial_ids(self.m, *SMITH_POINT, RADIUS, space=1).tolist().count(self.village_node), 0)
        self.assertIn(self.smith_node, entity_radial_ids(self.m, *SMITH_POINT, RADIUS, space=1).tolist())
        self.assertEqual(entity_radial_ids(self.m, *VILLAGE_POINT, RADIUS, space=0).tolist().count(self.smith_node), 0)
        self.assertIn(self.village_node, entity_radial_ids(self.m, *VILLAGE_POINT, RADIUS, space=0).tolist())
        live = self.h[:, cfg.TYPE] > cfg.AGENT_TYPE_EMPTY
        inside = agent_radial_mask(self.h, live, *SMITH_POINT, RADIUS, "cpu", space=1)
        outside = agent_radial_mask(self.h, live, *VILLAGE_POINT, RADIUS, "cpu", space=0)
        live_rows = live.nonzero().flatten().tolist()
        for mask, space in ((inside, 1), (outside, 0)):
            for row, hit in zip(live_rows, mask.tolist()):
                if hit:
                    self.assertEqual(int(self.h[row, cfg.H_SPACE]), space, row)
        self.assertTrue(any(inside.tolist()) and any(outside.tolist()), "each space has residents in range")

    async def test_bounded_nearest_entity_with_the_actor_space(self):
        eid, _ = nearest_entity(self.m, *SMITH_POINT, type_ids=NODES, max_distance=RADIUS, space=1, space_col=cfg.M_SPACE)
        self.assertEqual(eid, self.smith_node)
        self.m[self.smith_node, cfg.M_TYPE] = 0.0
        eid, dist = nearest_entity(self.m, *SMITH_POINT, type_ids=NODES, max_distance=RADIUS, space=1, space_col=cfg.M_SPACE)
        self.assertEqual(eid, -1)

    async def test_world_contract_walls_do_not_open_a_line_between_the_spaces(self):
        contract = world_contract(self.engine)
        for target in ((300.0, 60.0), (200.0, 150.0), (370.0, 60.0)):
            self.assertTrue(segment_blocked(SMITH_POINT, target, contract["boxes"]), target)
            self.assertTrue(segment_blocked(target, SMITH_POINT, contract["boxes"]), target)
        self.assertFalse(is_standable_point((500.0, 60.0), contract), "the gap between the maps is not walkable")
        self.assertTrue(is_standable_point(SMITH_POINT, contract))
        self.assertTrue(is_standable_point(VILLAGE_POINT, contract))


class TileFamilyLeakTests(LeakFixture):
    """Tile lookups (``entity_at``) and the human damage built on them (fire, flood)."""

    async def test_every_tile_inside_an_interior_resolves_to_a_row_of_that_space_or_nothing(self):
        for space, x0, y0, x1, y1 in spaces.rectangles(self.engine):
            for x in range(int(x0) + 4, int(x1) - 3, 4):
                for y in range(int(y0) + 4, int(y1) - 3, 4):
                    eid = map_geo.entity_at(float(x), float(y))
                    if eid != -1:
                        self.assertEqual(int(self.m[eid, cfg.M_SPACE]), space, (space, x, y, eid))

    async def test_a_big_area_entity_of_the_village_does_not_register_tiles_inside_an_interior(self):
        forest = self.add(300.0, 60.0, cfg.M_FOREST, geo_radius=400.0)              # its circle reaches x=700, over the smith
        for space, x0, y0, x1, y1 in spaces.rectangles(self.engine):
            for x in range(int(x0) + 4, int(x1) - 3, 4):                       # inside the rectangle by half a tile: a tile is owned by its centre
                for y in range(int(y0) + 4, int(y1) - 3, 4):
                    self.assertNotEqual(map_geo.entity_at(float(x), float(y)), forest, (space, x, y))

    async def test_fire_damages_the_village_resident_under_it_and_not_the_smith_inside_the_interior(self):
        self.place_human(0, SMITH_POINT)                                         # the smith, inside
        self.place_human(1, (330.0, 60.0))                                       # a villager, under the fire
        forest = self.add(300.0, 60.0, cfg.M_FOREST, geo_radius=400.0, cols={cfg.M_BURNING: 1.0})
        before = [float(self.h[s, cfg.HP]) for s in (0, 1)]
        h_mask = self.h[:, cfg.TYPE] > cfg.AGENT_TYPE_EMPTY
        apply_fire_tick({"h_mask": h_mask}, self.m, self.h, device="cpu")
        self.assertEqual(float(self.h[0, cfg.HP]), before[0], "the smith inside the interior was burnt by a village fire")
        self.assertLess(float(self.h[1, cfg.HP]), before[1], "control: the villager under the fire is damaged")
        self.assertEqual(int(self.m[forest, cfg.M_SPACE]), 0)

    async def test_flood_damages_the_village_resident_under_it_and_not_the_smith_inside_the_interior(self):
        self.place_human(0, SMITH_POINT)
        self.place_human(1, (330.0, 60.0))
        self.add(250.0, 60.0, cfg.M_LAKE, geo_radius=20.0)                       # water near the village forest
        forest = self.add(300.0, 60.0, cfg.M_FOREST, geo_radius=400.0)
        before = [float(self.h[s, cfg.HP]) for s in (0, 1)]
        h_mask = self.h[:, cfg.TYPE] > cfg.AGENT_TYPE_EMPTY
        apply_flood({"h_mask": h_mask}, self.h, self.m, device="cpu", expand_radius=100.0)
        self.assertEqual(int(self.m[forest, cfg.M_TYPE]), cfg.M_SEA, "control: the forest next to the lake flooded")
        self.assertEqual(float(self.h[0, cfg.HP]), before[0], "the smith inside the interior was drowned by a village flood")
        self.assertLess(float(self.h[1, cfg.HP]), before[1], "control: the villager under the flood is damaged")

    async def test_interior_fire_does_not_burn_the_village(self):
        self.place_human(0, SMITH_POINT)
        self.place_human(1, (330.0, 60.0))
        self.add(680.0, 40.0, cfg.M_FOREST, geo_radius=500.0, cols={cfg.M_BURNING: 1.0})   # a burning forest in the smith, huge circle
        before = [float(self.h[s, cfg.HP]) for s in (0, 1)]
        apply_fire_tick({"h_mask": self.h[:, cfg.TYPE] > cfg.AGENT_TYPE_EMPTY}, self.m, self.h, device="cpu")
        self.assertEqual(float(self.h[1, cfg.HP]), before[1], "the villager was burnt by a fire inside the smith interior")
        self.assertLess(float(self.h[0, cfg.HP]), before[0], "control: the smith inside is damaged")


if __name__ == "__main__":
    unittest.main()
