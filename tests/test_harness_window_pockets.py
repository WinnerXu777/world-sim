"""1008 WS-D P5 (e): interior pockets of the window format. Interiors sit in a fixed pool of 256 x 256 unit squares outside the window-local range
(x in [1792, 2048) or [-2048, -1792)); each pocket is its own 32 x 32 tile frame, so a tile lookup in an interior finds the interior's entity and a
re-base never touches it."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_harness_window_manager import ON, WindowFixture  # noqa: E402
from authored_village import village_environment  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
import map_geo  # noqa: E402
from harness import spaces, window  # noqa: E402
from systems.movement import map_contract  # noqa: E402


class PocketGeometryTests(unittest.TestCase):
    def setUp(self):
        map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear()
        map_geo.configure_window(*window.WINDOW_FRAME[:2], window.WINDOW_FRAME[2], sparse=True)
        map_geo.configure_pockets(window.POCKET_ORIGINS)
        self.addCleanup(map_geo.reset_window)
        self.addCleanup(lambda: (map_geo.MAP_GEO.clear(), map_geo.TILE_TO_ENTITY.clear()))

    def test_the_pool_is_32_pockets_outside_the_window_range(self):
        origins = window.POCKET_ORIGINS
        self.assertEqual(len(origins), 32)
        for x, y in origins:
            self.assertTrue(x >= 1792.0 or x + 256.0 <= -1792.0, (x, y))
            self.assertTrue(-2048.0 <= y and y + 256.0 <= 2048.0)
        self.assertEqual(len(set(origins)), 32)
        self.assertEqual(window.authored_pocket(0), 0)
        self.assertEqual(window.authored_pocket(2), 2)
        with self.assertRaises(ValueError):
            window.authored_pocket(32)

    def test_a_pocket_entity_has_its_own_tiles_and_the_lookup_finds_it(self):
        x0, y0 = window.POCKET_ORIGINS[2]
        map_geo.register_entity(7, "circle", x0 + 100.0, y0 + 60.0, 20.0)
        map_geo.register_entity(8, "circle", 300.0, 300.0, 20.0)                        # main frame
        tiles = map_geo.tiles_of(7)
        self.assertGreater(len(tiles), 10)
        self.assertTrue(all(t >= map_geo.GRID_W * map_geo.GRID_H for t in tiles))
        self.assertEqual(map_geo.MAP_GEO[7]["pocket"], 2)
        self.assertNotIn("pocket", map_geo.MAP_GEO[8])
        self.assertTrue(all(t < map_geo.GRID_W * map_geo.GRID_H for t in map_geo.tiles_of(8)))
        self.assertEqual(map_geo.entity_at(x0 + 100.0, y0 + 60.0), 7)
        self.assertEqual(map_geo.entity_at(300.0, 300.0), 8)
        self.assertEqual(map_geo.entity_at(x0 + 240.0, y0 + 240.0), -1)                 # inside the pocket, outside the entity
        self.assertEqual(map_geo.entity_at(1700.0, 0.0), -1, "between the window range and the pocket strip: no frame, nothing found")
        for ti in tiles:
            cx, cy = map_geo.tile_center_px(ti)
            self.assertEqual(map_geo.entity_at(cx, cy), 7)

    def test_the_tile_mask_of_a_pocket_entity_is_pocket_sized_and_the_background_skips_it(self):
        x0, y0 = window.POCKET_ORIGINS[0]
        map_geo.register_entity(7, "circle", x0 + 50.0, y0 + 50.0, 10.0)
        mask = map_geo.tile_mask(7)
        self.assertEqual(tuple(mask.shape), (32, 32))
        self.assertEqual(int(mask.sum()), len(map_geo.tiles_of(7)))
        m = torch.zeros((16, cfg.M_COLS if hasattr(cfg, "M_COLS") else 32))
        m[7, cfg.M_TYPE] = float(cfg.M_FOREST)
        grid = map_geo.background_tile_types(m)
        self.assertEqual(int((grid != 0).sum()), 0)

    def test_a_rebase_shift_leaves_pocket_entities_alone(self):
        x0, y0 = window.POCKET_ORIGINS[1]
        map_geo.register_entity(7, "circle", x0 + 50.0, y0 + 50.0, 10.0)
        map_geo.register_entity(8, "circle", 300.0, 300.0, 20.0)
        before = map_geo.tiles_of(7)
        self.assertEqual(map_geo.shift_entities([7, 8], -256.0, -256.0), 1)
        self.assertEqual(map_geo.tiles_of(7), before)
        self.assertEqual((map_geo.MAP_GEO[8]["cx"], map_geo.MAP_GEO[8]["cy"]), (44.0, 44.0))

    def test_unregistering_removes_the_pocket_tiles(self):
        x0, y0 = window.POCKET_ORIGINS[3]
        map_geo.register_entity(7, "circle", x0 + 50.0, y0 + 50.0, 10.0)
        map_geo.unregister_entity(7)
        self.assertEqual(map_geo.TILE_TO_ENTITY, {})

    def test_restore_rebuilds_pocket_boxes_from_shapes(self):
        x0, y0 = window.POCKET_ORIGINS[3]
        map_geo.register_entity(7, "circle", x0 + 50.0, y0 + 50.0, 10.0)
        tiles = map_geo.tiles_of(7)
        shapes = {eid: {k: v for k, v in geo.items() if k != "tile_box"} for eid, geo in map_geo.MAP_GEO.items()}
        map_geo.MAP_GEO.clear()
        map_geo.restore_shapes(shapes)
        self.assertEqual(map_geo.tiles_of(7), tiles)
        self.assertIn("pockets", map_geo.window_frame())

    def test_configure_pockets_needs_the_sparse_frame_and_whole_tiles(self):
        map_geo.reset_window()
        with self.assertRaises(RuntimeError):
            map_geo.configure_pockets(window.POCKET_ORIGINS)
        map_geo.configure_window(*window.WINDOW_FRAME[:2], window.WINDOW_FRAME[2], sparse=True)
        with self.assertRaises(ValueError):
            map_geo.configure_pockets([(1792.5, 0.0)])


class LoaderTests(unittest.TestCase):
    def setUp(self):
        map_contract.clear_map_contracts()
        self.addCleanup(map_contract.clear_map_contracts)

    @staticmethod
    def load_window_world():
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}):
            return map_contract.load_from_environment({**village_environment(), "EDEN_WINDOW": "1"})

    def test_window_mode_places_the_interiors_in_pockets_and_ignores_the_env_origins(self):
        names = self.load_window_world()
        self.assertEqual(names[0], "starter_village")
        origins = {n: map_contract.MAP_CONTRACTS[n]["origin"] for n in names[1:]}
        self.assertEqual(origins["smith_interior"], list(window.POCKET_ORIGINS[0]))
        self.assertEqual(origins["village_lodge_interior"], list(window.POCKET_ORIGINS[1]))
        self.assertEqual(origins["west_cottage_interior"], list(window.POCKET_ORIGINS[2]))
        for n in names[1:]:
            b = map_contract.MAP_CONTRACTS[n]["bounds"]
            self.assertTrue(b[0] >= 1792.0 and b[2] <= 2048.0, (n, b))

    def test_without_the_flag_the_env_origins_are_used(self):
        names = map_contract.load_from_environment(village_environment())
        self.assertEqual(map_contract.MAP_CONTRACTS["smith_interior"]["origin"], [620.0, 0.0])

    def test_an_interior_larger_than_a_pocket_is_refused_by_name(self):
        with mock.patch.object(window, "POCKET_UNITS", 40.0):
            with self.assertRaises(ValueError) as caught:
                self.load_window_world()
        self.assertIn("pocket holds", str(caught.exception))
        self.assertEqual(map_contract.MAP_CONTRACTS, {}, "a failed load leaves nothing registered")


class PocketSpaceTests(WindowFixture):
    async def test_a_point_in_a_pocket_is_the_interior_space_and_rebase_does_not_move_it(self):
        map_contract.clear_map_contracts()
        self.addCleanup(map_contract.clear_map_contracts)
        LoaderTests.load_window_world()
        self.engine._map_name = "starter_village"
        self.addCleanup(setattr, self.engine, "_map_name", "unknown")
        x0, y0 = window.POCKET_ORIGINS[0]
        self.assertEqual(spaces.space_at(self.engine, x0 + 40.0, y0 + 40.0), 1)
        self.assertEqual(spaces.space_at(self.engine, 100.0, 100.0), 0)
        interior_before = list(map_contract.MAP_CONTRACTS["smith_interior"]["bounds"])
        self.place_human(0, 520.0, 520.0)
        self.manager.rebase((1, 1))
        self.assertEqual(map_contract.MAP_CONTRACTS["smith_interior"]["bounds"], interior_before)
        self.assertEqual(spaces.space_at(self.engine, x0 + 40.0, y0 + 40.0), 1)
        self.assertEqual(map_contract.MAP_CONTRACTS["starter_village"]["bounds"][0], -256.0)


if __name__ == "__main__":
    unittest.main()
