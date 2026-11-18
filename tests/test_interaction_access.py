"""Wall-aware interaction helper (P3.3): range, line of sight, own-footprint exclusion, engine lookup."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from systems.commission.access import DEFAULT_INTERACT_RADIUS, interaction_ok

FORGE_WALL = {"id": "w_forge", "min": [16.0, 8.0], "max": [32.0, 16.0]}
OTHER_WALL = {"id": "w_other", "min": [0.0, 40.0], "max": [48.0, 44.0]}


class PureTests(unittest.TestCase):
    def test_in_range_and_clear(self):
        result = interaction_ok((24.0, 29.0), (24.0, 21.0), 16.0, [FORGE_WALL])
        self.assertEqual((result["ok"], result["reason"]), (True, ""))
        self.assertAlmostEqual(result["distance"], 8.0)

    def test_out_of_range(self):
        result = interaction_ok((24.0, 60.0), (24.0, 21.0), 16.0, [])
        self.assertEqual((result["ok"], result["reason"]), (False, "out_of_range"))

    def test_range_boundary_is_inclusive(self):
        self.assertTrue(interaction_ok((0.0, 0.0), (16.0, 0.0), 16.0, [])["ok"])
        self.assertFalse(interaction_ok((0.0, 0.0), (16.0001, 0.0), 16.0, [])["ok"])

    def test_a_wall_between_blocks(self):
        result = interaction_ok((24.0, 22.0), (24.0, 6.0), 20.0, [FORGE_WALL])  # the forge wall lies between
        self.assertEqual((result["ok"], result["reason"]), (False, "blocked"))

    def test_the_targets_own_footprint_is_ignored(self):
        # the forge entity sits at the wall edge (24, 16): its own wall must not block touching it
        self.assertFalse(interaction_ok((24.0, 22.0), (24.0, 14.0), 16.0, [FORGE_WALL])["ok"])
        result = interaction_ok((24.0, 22.0), (24.0, 14.0), 16.0, [FORGE_WALL], ignore_ids=("w_forge",))
        self.assertEqual((result["ok"], result["reason"]), (True, ""))

    def test_ignoring_one_footprint_does_not_open_other_walls(self):
        boxes = [FORGE_WALL, {"id": "w_second", "min": [20.0, 17.0], "max": [28.0, 19.0]}]
        result = interaction_ok((24.0, 22.0), (24.0, 14.0), 16.0, boxes, ignore_ids=("w_forge",))
        self.assertEqual((result["ok"], result["reason"]), (False, "blocked"))

    def test_contact_and_embedding_count_as_blocked(self):
        self.assertEqual(interaction_ok((12.0, 12.0), (16.0, 12.0), 16.0, [FORGE_WALL])["reason"], "blocked")  # touches the edge
        self.assertEqual(interaction_ok((24.0, 12.0), (30.0, 12.0), 16.0, [FORGE_WALL])["reason"], "blocked")  # starts inside

    def test_a_clear_diagonal_around_a_corner(self):
        self.assertTrue(interaction_ok((33.0, 20.0), (40.0, 12.0), 16.0, [FORGE_WALL])["ok"])
        self.assertFalse(interaction_ok((10.0, 12.0), (40.0, 12.0), 40.0, [FORGE_WALL])["ok"])

    def test_non_finite_input_is_out_of_range(self):
        self.assertEqual(interaction_ok((0.0, 0.0), (float("nan"), 0.0), 16.0, [])["reason"], "out_of_range")
        self.assertEqual(interaction_ok((0.0, 0.0), (1.0, 0.0), float("inf"), [])["reason"], "out_of_range")

    def test_default_radius_is_two_tiles(self):
        self.assertEqual(DEFAULT_INTERACT_RADIUS, 16.0)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from test_startup_preservation import backend
        from test_map_contract import FIXTURES, SMITH
        from systems.movement.map_contract import clear_map_contracts, register_map_file
        self.backend = backend
        clear_map_contracts()
        register_map_file(SMITH, base_dir=FIXTURES)
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        self.engine = backend.engine
        self.addCleanup(clear_map_contracts)

    def place(self, x, y):
        self.engine.state.h_tensor[0, self.backend.X], self.engine.state.h_tensor[0, self.backend.Y] = x, y

    def test_the_forge_is_reachable_from_the_work_anchor_through_its_own_footprint(self):
        from systems.commission.access import engine_interaction_ok
        self.place(24.0, 21.0)  # the work anchor, below the forge wall (16,8)-(32,16)
        forge = (24.0, 16.0)
        result = engine_interaction_ok(self.engine, 0, forge, radius=8.0, target_entity_id="example_smith:forge")
        self.assertEqual((result["ok"], result["reason"]), (True, ""))
        without_owner = engine_interaction_ok(self.engine, 0, (24.0, 14.0), radius=8.0)  # same spot, footprint not excluded
        self.assertEqual((without_owner["ok"], without_owner["reason"]), (False, "blocked"))

    def test_the_far_side_of_the_forge_wall_is_blocked_for_anything_else(self):
        from systems.commission.access import engine_interaction_ok
        self.place(24.0, 5.0)  # north of the forge wall
        result = engine_interaction_ok(self.engine, 0, (24.0, 21.0), radius=30.0)
        self.assertEqual((result["ok"], result["reason"]), (False, "blocked"))

    def test_default_radius_applies_and_out_of_range_is_reported(self):
        from systems.commission.access import engine_interaction_ok
        self.place(8.0, 32.0)
        result = engine_interaction_ok(self.engine, 0, (24.0, 21.0), target_entity_id="example_smith:forge")
        self.assertEqual((result["ok"], result["reason"]), (False, "out_of_range"))  # 19.4 units > 16

    async def test_legacy_maps_only_check_the_range(self):
        from systems.commission.access import engine_interaction_ok
        from systems.movement.map_contract import clear_map_contracts
        clear_map_contracts()
        self.backend.engine.reset_world()
        await self.backend.create_genesis(self.backend.engine, map_name="playable_village")
        wall = self.backend.world_contract(self.backend.engine)["boxes"][0]
        self.place(wall["min"][0] - 3.0, (wall["min"][1] + wall["max"][1]) / 2)
        far_side = (wall["max"][0] + 3.0, (wall["min"][1] + wall["max"][1]) / 2)
        self.assertTrue(engine_interaction_ok(self.backend.engine, 0, far_side, radius=30.0)["ok"])  # no wall test on legacy maps


if __name__ == "__main__":
    unittest.main()
