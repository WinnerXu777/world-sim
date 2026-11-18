"""Standable spawn handling on authored maps (G4): helpers in spatial.py, Engine.spawn, create_genesis anchors."""
import unittest

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation, FIXTURES, SMITH, make_authored_world
from systems.movement.map_contract import register_map_contract, register_map_file
from systems.movement.spatial import (is_standable_point, slide, snap_to_standable, standable_spawn_point,
                                      world_contract)

SMITH_CONTRACT = {"actor_radius": 2.4, "bounds": [0.0, 0.0, 48.0, 48.0],
                  "boxes": [{"id": "w", "min": [16.0, 8.0], "max": [32.0, 16.0]}]}


def human_positions(engine):
    h = engine.state.h_tensor
    return [(float(h[s, backend.X]), float(h[s, backend.Y])) for s in range(h.shape[0]) if float(h[s, backend.TYPE]) > 0]


class StandablePointTests(unittest.TestCase):
    def test_standable_points_are_returned_unchanged(self):
        for point in ((8, 32), (24, 21), (24.0, 18.4), (45.6, 45.6), (2.4, 2.4)):
            with self.subTest(point=point):
                self.assertTrue(is_standable_point(point, SMITH_CONTRACT))
                self.assertEqual(snap_to_standable(point, SMITH_CONTRACT), point)

    def test_embedded_points_snap_to_the_nearest_face(self):
        cases = {(24, 12): (24, 18.401), (24, 6): (24, 5.599), (14, 12): (13.599, 12), (33, 12): (34.401, 12)}
        for point, expected in cases.items():
            with self.subTest(point=point):
                snapped = snap_to_standable(point, SMITH_CONTRACT)
                self.assertTrue(is_standable_point(snapped, SMITH_CONTRACT))
                self.assertAlmostEqual(snapped[0], expected[0], places=3)
                self.assertAlmostEqual(snapped[1], expected[1], places=3)

    def test_snapped_actor_is_not_frozen_unlike_an_embedded_one(self):
        snapped = snap_to_standable((24, 12), SMITH_CONTRACT)
        moved = slide(snapped, (snapped[0], snapped[1] + 5), SMITH_CONTRACT)
        self.assertGreater(moved[1], snapped[1])
        self.assertEqual(slide((24, 12), (24, 17), SMITH_CONTRACT), (24, 12))  # what the snap prevents

    def test_points_outside_the_bounds_are_clamped_in(self):
        self.assertEqual(snap_to_standable((-5, 100), SMITH_CONTRACT), (2.4, 45.6))

    def test_a_point_with_no_standable_neighbourhood_is_rejected(self):
        full = {"actor_radius": 2.4, "bounds": [0.0, 0.0, 48.0, 48.0],
                "boxes": [{"id": "all", "min": [0.0, 0.0], "max": [48.0, 48.0]}]}
        self.assertIsNone(snap_to_standable((24, 24), full))
        self.assertFalse(is_standable_point((24, 24), full))
        too_big = {"actor_radius": 30.0, "bounds": [0.0, 0.0, 48.0, 48.0], "boxes": []}  # radius larger than the map
        self.assertIsNone(snap_to_standable((24, 24), too_big))

    def test_overlapping_boxes_are_resolved_by_repeated_pushes(self):
        contract = {"actor_radius": 1.0, "bounds": [0.0, 0.0, 100.0, 100.0],
                    "boxes": [{"id": "a", "min": [40.0, 40.0], "max": [60.0, 60.0]},
                              {"id": "b", "min": [60.0, 40.0], "max": [80.0, 60.0]}]}
        snapped = snap_to_standable((59, 50), contract)
        self.assertTrue(is_standable_point(snapped, contract))


class AuthoredSpawnTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_genesis_places_the_starter_villagers_at_the_spawn_anchor(self):
        register_map_file(SMITH, base_dir=FIXTURES)
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        engine = backend.engine
        self.assertEqual((engine._map_name, engine.world_loaded, engine.pop_count), ("example_smith", True, 4))
        contract = world_contract(engine)
        self.assertEqual(contract["map_id"], "example_smith")
        positions = human_positions(engine)
        self.assertEqual(len(positions), 4)
        self.assertEqual(positions[0], (8.0, 32.0))  # the first villager is exactly on the anchor
        for position in positions:
            self.assertTrue(is_standable_point(position, contract), position)
            self.assertLessEqual(max(abs(position[0] - 8.0), abs(position[1] - 32.0)), 2 * 2.4 * 2 + 1e-6)
        self.assertEqual(len(set(positions)), 4)  # fanned out, not stacked
        names = {engine.resident_store.get(uid)["profile"]["name"] for uid in engine._human_uid_by_slot if uid}
        self.assertEqual(names, {"Mara", "Iven", "Toma", "Elsa"})

    async def test_no_legacy_generator_entities_are_created_for_an_authored_map(self):
        register_map_file(SMITH, base_dir=FIXTURES)
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        legacy = {backend.M_GRASS, backend.M_FOREST, backend.M_HOUSE, backend.M_VILLAGE, backend.M_WALL}
        present = {int(t) for t in backend.engine.state.m_tensor[:, backend.M_TYPE].tolist() if t > 0}
        self.assertFalse(present & legacy)

    async def test_a_map_without_spawn_anchors_spawns_around_the_map_centre(self):
        register_map_contract("blank", 2.4, [0, 0, 48, 48], [])  # registered, not a built-in name, no anchors
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="blank")
        positions = human_positions(backend.engine)
        self.assertEqual(len(positions), 4)
        self.assertEqual(positions[0], (24.0, 24.0))
        self.assertTrue(all(is_standable_point(p, world_contract(backend.engine)) for p in positions))

    async def test_unregistered_unknown_map_names_still_raise(self):
        backend.engine.reset_world()
        with self.assertRaises(ValueError):
            await backend.create_genesis(backend.engine, map_name="not_a_map")

    async def test_engine_spawn_snaps_out_of_walls_and_rejects_impossible_points(self):
        engine = await make_authored_world()
        before = engine.pop_count
        self.assertTrue(engine.spawn(24.0, 12.0, 0.0, 70.0, age=20.0, preferred_name="Snapped"))  # inside the forge wall
        positions = human_positions(engine)
        self.assertEqual(len(positions), before + 1)
        self.assertTrue(all(is_standable_point(p, world_contract(engine)) for p in positions[-1:]))
        self.assertNotIn((24.0, 12.0), positions)
        register_map_contract("example_smith", 2.4, [0, 0, 48, 48], [{"id": "all", "min": [0, 0], "max": [48, 48]}])
        self.assertFalse(engine.spawn(24.0, 24.0, 0.0, 70.0, age=20.0, preferred_name="Nowhere"))
        self.assertEqual(len(human_positions(engine)), before + 1)  # rejected: nothing was added

    async def test_legacy_maps_spawn_exactly_where_asked(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        wall = world_contract(backend.engine)["boxes"][0]
        inside = ((wall["min"][0] + wall["max"][0]) / 2, (wall["min"][1] + wall["max"][1]) / 2)
        self.assertEqual(standable_spawn_point(backend.engine, *inside), inside)
        before = len(human_positions(backend.engine))
        self.assertTrue(backend.engine.spawn(*inside, 1.0, 70.0, age=20.0))
        positions = human_positions(backend.engine)
        self.assertEqual(len(positions), before + 1)
        self.assertIn(inside, positions)  # even inside a legacy wall: legacy behaviour is unchanged


if __name__ == "__main__":
    unittest.main()
