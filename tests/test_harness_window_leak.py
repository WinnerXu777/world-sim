"""1008 WS-D P5 leak test in window mode (proof 8): interiors sit in consecutive pockets (smith, lodge, west cottage at pockets 0, 1, 2, 256 units apart,
no isolation distance), the overworld window runs next to them. With an actor in one space no query family returns a row, a human, a tile or a wall of another
space. Same families as ``test_harness_spaces_leak`` (that file guards the finite world); EDEN_WINDOW=1 changes where interiors are and drops the isolation
distance, so the space filters are the only guard."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from test_map_portals import real_world  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
import map_geo  # noqa: E402
from harness import engine_hooks as eh, spaces, window  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402
from systems.movement.map_contract import MAP_CONTRACTS  # noqa: E402
from systems.movement.spatial import is_standable_point, segment_blocked, world_contract  # noqa: E402
from systems.nature.disasters import apply_flood  # noqa: E402
from systems.nature.hazards import apply_fire_tick  # noqa: E402
from systems.perception import (agent_radial_mask, best_resource_entity, entity_radial_ids, nearby_entity_ids,  # noqa: E402
                                nearest_geo_entity)

ON = {"EDEN_WINDOW": "1", "EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1", "EDEN_MAP_RESOURCES": "1"}
RADIUS = 500.0                       # reaches the neighbouring pocket (256 away) and the open overworld (about 300 away)
NODES = {cfg.M_RESOURCE_NODE}
VILLAGE_POINT = (300.0, 60.0)        # inside the village (space 0)
OPEN_POINT = (1500.0, 60.0)          # open overworld at the edge of the window, 290 units from the smith pocket


def centre(name):
    x0, y0, x1, y1 = MAP_CONTRACTS[name]["bounds"]
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


class WindowLeakFixture(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        DISPATCH.clear()
        patcher = mock.patch.dict(os.environ, ON, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear()
        self.addCleanup(map_geo.reset_window)                    # registered first: runs after the per-test unregister cleanups
        eh.install(DISPATCH)
        self.engine = await real_world()
        self.m, self.h = self.engine.state.m_tensor, self.engine.state.h_tensor
        self.smith, self.lodge, self.cottage = (centre(n) for n in ("smith_interior", "village_lodge_interior", "west_cottage_interior"))

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
        return self.add(x, y, cfg.M_RESOURCE_NODE, geo_radius=6.0, cols={cfg.M_NODE_KIND: 1.0, cfg.M_NODE_STOCK: stock, cfg.M_NODE_CAP: 100.0})

    def place_human(self, slot, point):
        self.h[slot, cfg.X], self.h[slot, cfg.Y] = point
        spaces.refresh(self.engine)


class PocketLayoutTests(WindowLeakFixture):
    async def test_interiors_are_in_consecutive_pockets_with_their_spaces(self):
        for index, (name, point) in enumerate((("smith_interior", self.smith), ("village_lodge_interior", self.lodge), ("west_cottage_interior", self.cottage))):
            ox, oy = window.POCKET_ORIGINS[index]
            self.assertTrue(ox <= point[0] < ox + 256.0 and oy <= point[1] < oy + 256.0, (name, point))
            self.assertEqual(spaces.space_at(self.engine, *point), index + 1)
        self.assertEqual(spaces.space_at(self.engine, *VILLAGE_POINT), 0)
        self.assertEqual(spaces.space_at(self.engine, *OPEN_POINT), 0)


class QueryFamilyLeakTests(WindowLeakFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.smith_node = self.node(self.smith[0] + 12.0, self.smith[1] - 10.0, stock=0.0)         # depleted, same space as the actor
        self.lodge_node = self.node(self.lodge[0] + 12.0, self.lodge[1] - 10.0, stock=90.0)        # rich, next pocket
        self.village_node = self.node(370.0, 60.0, stock=90.0)
        self.open_node = self.node(OPEN_POINT[0], OPEN_POINT[1] + 10.0, stock=90.0)
        for slot, space in ((self.smith_node, 1), (self.lodge_node, 2), (self.village_node, 0), (self.open_node, 0)):
            self.assertEqual(int(self.m[slot, cfg.M_SPACE]), space, slot)

    def same_space_nodes(self, point, space):
        """Every node row of ``space`` within RADIUS of the point (the authored interiors carry nodes of their own)."""
        rows = (self.m[:, cfg.M_TYPE] == cfg.M_RESOURCE_NODE).nonzero().flatten().tolist()
        return sorted(s for s in rows if int(self.m[s, cfg.M_SPACE]) == space
                      and ((float(self.m[s, cfg.CX]) - point[0]) ** 2 + (float(self.m[s, cfg.CY]) - point[1]) ** 2) ** 0.5 <= RADIUS)

    async def test_nearby_entity_ids_never_crosses_in_any_direction(self):
        for point, space, own in ((self.smith, 1, self.smith_node), (self.lodge, 2, self.lodge_node), (OPEN_POINT, 0, self.open_node),
                                  (VILLAGE_POINT, 0, self.village_node)):
            found = sorted(nearby_entity_ids(self.m, *point, RADIUS, NODES))
            self.assertIn(own, found)
            self.assertEqual(found, self.same_space_nodes(point, space), (space, point))

    async def test_nearest_and_best_resource_never_pick_another_space(self):
        self.assertIn(nearest_geo_entity(self.m, *self.smith, NODES, RADIUS), self.same_space_nodes(self.smith, 1))
        for slot in self.same_space_nodes(self.smith, 1):                         # no same-space candidate left: nothing, not the next pocket's node
            self.m[slot, cfg.M_TYPE] = 0.0
        self.assertEqual(nearest_geo_entity(self.m, *self.smith, NODES, RADIUS), -1)
        self.assertEqual(best_resource_entity(self.m, *self.smith, NODES, cfg.M_NODE_STOCK, RADIUS), -1)
        self.assertIn(best_resource_entity(self.m, *self.lodge, NODES, cfg.M_NODE_STOCK, RADIUS), self.same_space_nodes(self.lodge, 2))

    async def test_radial_helpers_with_the_actor_space(self):
        for point, space, own in ((self.smith, 1, self.smith_node), (self.lodge, 2, self.lodge_node), (OPEN_POINT, 0, self.open_node)):
            ids = entity_radial_ids(self.m, *point, RADIUS, space=space).tolist()
            self.assertIn(own, ids)
            for other in (self.smith_node, self.lodge_node, self.village_node, self.open_node):
                if other != own and int(self.m[other, cfg.M_SPACE]) != space:
                    self.assertNotIn(other, ids, (space, other))
        self.place_human(1, self.smith)
        self.place_human(2, self.lodge)
        self.place_human(3, OPEN_POINT)
        live = self.h[:, cfg.TYPE] > cfg.AGENT_TYPE_EMPTY
        rows = live.nonzero().flatten().tolist()
        for point, space in ((self.smith, 1), (self.lodge, 2), (OPEN_POINT, 0)):
            mask = agent_radial_mask(self.h, live, *point, RADIUS, "cpu", space=space)
            hits = [row for row, hit in zip(rows, mask.tolist()) if hit]
            self.assertTrue(hits, space)
            for row in hits:
                self.assertEqual(int(self.h[row, cfg.H_SPACE]), space, (space, row))

    async def test_world_contract_walls_close_every_line_between_the_spaces(self):
        contract = world_contract(self.engine)
        pairs = ((self.smith, self.lodge), (self.lodge, self.cottage), (self.smith, OPEN_POINT), (self.smith, VILLAGE_POINT), (self.lodge, OPEN_POINT))
        for a, b in pairs:
            self.assertTrue(segment_blocked(a, b, contract["boxes"]), (a, b))
            self.assertTrue(segment_blocked(b, a, contract["boxes"]), (b, a))
        for point in (self.smith, self.lodge, self.cottage, VILLAGE_POINT):
            self.assertTrue(is_standable_point(point, contract), point)


class TileFamilyLeakTests(WindowLeakFixture):
    def rectangles(self):
        return spaces.rectangles(self.engine)

    async def test_every_tile_inside_an_interior_resolves_to_a_row_of_that_space_or_nothing(self):
        self.node(self.smith[0], self.smith[1], stock=10.0)
        for space, x0, y0, x1, y1 in self.rectangles():
            for x in range(int(x0) + 4, int(x1) - 3, 4):
                for y in range(int(y0) + 4, int(y1) - 3, 4):
                    eid = map_geo.entity_at(float(x), float(y))
                    if eid != -1:
                        self.assertEqual(int(self.m[eid, cfg.M_SPACE]), space, (space, x, y, eid))

    async def test_a_big_overworld_entity_never_registers_tiles_in_a_pocket_and_a_big_pocket_entity_stays_in_its_pocket(self):
        forest = self.add(OPEN_POINT[0], OPEN_POINT[1], cfg.M_FOREST, geo_radius=400.0)        # reaches x=1900, over the smith pocket
        huge = self.add(self.smith[0], self.smith[1], cfg.M_FOREST, geo_radius=500.0)          # fills the pocket and more
        self.assertEqual(int(self.m[forest, cfg.M_SPACE]), 0)
        self.assertEqual(int(self.m[huge, cfg.M_SPACE]), 1)
        for space, x0, y0, x1, y1 in self.rectangles():
            for x in range(int(x0) + 4, int(x1) - 3, 4):
                for y in range(int(y0) + 4, int(y1) - 3, 4):
                    found = map_geo.entity_at(float(x), float(y))
                    self.assertNotEqual(found, forest, (space, x, y))
                    if space != 1:
                        self.assertNotEqual(found, huge, (space, x, y))
        self.assertTrue(all(t >= map_geo.GRID_W * map_geo.GRID_H for t in map_geo.tiles_of(huge)))
        self.assertTrue(all(t < map_geo.GRID_W * map_geo.GRID_H for t in map_geo.tiles_of(forest)))

    async def test_a_village_fire_burns_the_villager_and_neither_interior(self):
        self.place_human(0, self.smith)
        self.place_human(1, self.lodge)
        self.place_human(2, (330.0, 60.0))
        self.add(300.0, 60.0, cfg.M_FOREST, geo_radius=400.0, cols={cfg.M_BURNING: 1.0})
        before = [float(self.h[s, cfg.HP]) for s in (0, 1, 2)]
        apply_fire_tick({"h_mask": self.h[:, cfg.TYPE] > cfg.AGENT_TYPE_EMPTY}, self.m, self.h, device="cpu")
        self.assertEqual(float(self.h[0, cfg.HP]), before[0], "the smith was burnt by a village fire")
        self.assertEqual(float(self.h[1, cfg.HP]), before[1], "the lodge occupant was burnt by a village fire")
        self.assertLess(float(self.h[2, cfg.HP]), before[2], "control: the villager under the fire is damaged")

    async def test_a_fire_in_the_smith_burns_only_the_smith_occupant(self):
        self.place_human(0, self.smith)
        self.place_human(1, self.lodge)
        self.place_human(2, (330.0, 60.0))
        self.place_human(3, OPEN_POINT)
        self.add(self.smith[0], self.smith[1], cfg.M_FOREST, geo_radius=500.0, cols={cfg.M_BURNING: 1.0})
        before = [float(self.h[s, cfg.HP]) for s in (0, 1, 2, 3)]
        apply_fire_tick({"h_mask": self.h[:, cfg.TYPE] > cfg.AGENT_TYPE_EMPTY}, self.m, self.h, device="cpu")
        self.assertLess(float(self.h[0, cfg.HP]), before[0], "control: the smith occupant is damaged")
        for slot, who in ((1, "lodge occupant"), (2, "villager"), (3, "walker in the open")):
            self.assertEqual(float(self.h[slot, cfg.HP]), before[slot], f"the {who} was burnt by a fire inside the smith")

    async def test_a_flood_in_the_open_does_not_drown_an_interior(self):
        self.place_human(0, self.smith)
        self.place_human(1, (OPEN_POINT[0] + 10.0, OPEN_POINT[1]))
        self.add(OPEN_POINT[0] - 30.0, OPEN_POINT[1], cfg.M_LAKE, geo_radius=20.0)
        forest = self.add(OPEN_POINT[0] + 10.0, OPEN_POINT[1], cfg.M_FOREST, geo_radius=400.0)
        before = [float(self.h[s, cfg.HP]) for s in (0, 1)]
        apply_flood({"h_mask": self.h[:, cfg.TYPE] > cfg.AGENT_TYPE_EMPTY}, self.h, self.m, device="cpu", expand_radius=100.0)
        self.assertEqual(int(self.m[forest, cfg.M_TYPE]), cfg.M_SEA, "control: the forest next to the lake flooded")
        self.assertEqual(float(self.h[0, cfg.HP]), before[0], "the smith was drowned by a flood in the open")
        self.assertLess(float(self.h[1, cfg.HP]), before[1], "control: the walker in the flood is damaged")


if __name__ == "__main__":
    unittest.main()
