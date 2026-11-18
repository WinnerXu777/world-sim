"""1008 P4: map_geo window mode and sparse bounding-box masks.

The proof obligations (docs/1008_spaces_p4_p5_gap.md section 4): the sparse representation is the dense one restricted to a bounding box, so on the
legacy full frame every answer is identical (tile owners, ``entity_at``, ``entities_in_radius``, fire and flood tiles, snapshot round trip),
and on a smaller or offset frame the dense and sparse masks still agree tile for tile.  The golden traces (``tools/golden_trace.py --sparse-geo``
default, ``--resources``, ``--spaces``) are the whole-engine half of the proof."""
import os
import random
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
import map_geo  # noqa: E402
from harness import spaces  # noqa: E402
from persistence import codec, world_snapshot  # noqa: E402

FRAMES = [  # (grid_w, grid_h, origin_col, origin_row): the legacy frame, a window with a negative origin, a tiny frame, a thin strip
    (cfg.GRID_W, cfg.GRID_H, 0, 0),
    (352, 352, -160, -160),
    (23, 17, 5, -3),
    (3, 90, 0, 0),
]


def random_shapes(rng, frame, count):
    gw, gh, oc, orow = frame
    x0, x1 = (oc - 6) * 8.0, (oc + gw + 6) * 8.0           # shapes centred around and beyond the frame edges
    y0, y1 = (orow - 6) * 8.0, (orow + gh + 6) * 8.0
    shapes = []
    for _ in range(count):
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
        kind = rng.choice(("circle", "circle", "polygon", "tiny", "huge", "zero"))
        if kind == "polygon":
            n = rng.randint(3, 9)
            r = rng.uniform(4.0, 120.0)
            pts = sorted(((rng.uniform(0, 6.2831853), rng.uniform(0.3, 1.0) * r) for _ in range(n)))
            import math
            shapes.append(("polygon", cx, cy, 0.0, [(cx + d * math.cos(a), cy + d * math.sin(a)) for a, d in pts]))
        else:
            r = {"circle": rng.uniform(3.0, 140.0), "tiny": rng.uniform(0.1, 3.0), "huge": rng.uniform(900.0, 5000.0), "zero": 0.0}[kind]
            shapes.append(("circle", cx, cy, r, None))
    return shapes


class GeoStateIsolation:
    """Run against an empty map_geo and restore whatever the suite had registered."""
    def setUp(self):
        self._geo = (dict(map_geo.MAP_GEO), dict(map_geo.TILE_TO_ENTITY), map_geo.geo_version, map_geo.window_frame())
        map_geo.MAP_GEO.clear()
        map_geo.TILE_TO_ENTITY.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        map_geo.MAP_GEO.clear()
        map_geo.TILE_TO_ENTITY.clear()
        map_geo.reset_window()
        frame = self._geo[3]
        map_geo.GRID_W, map_geo.GRID_H, map_geo._SPARSE = frame["grid_w"], frame["grid_h"], frame["sparse"]
        map_geo._ORIGIN_COL, map_geo._ORIGIN_ROW = frame["origin_tile"]
        map_geo.MAP_GEO.update(self._geo[0])
        map_geo.TILE_TO_ENTITY.update(self._geo[1])
        map_geo.geo_version = self._geo[2]

    def configure(self, frame, sparse):
        map_geo.MAP_GEO.clear()
        map_geo.TILE_TO_ENTITY.clear()
        map_geo.configure_window(frame[0], frame[1], (frame[2], frame[3]), sparse=sparse)


class SparseEqualsDenseTests(GeoStateIsolation, unittest.TestCase):
    def build(self, frame, sparse, shapes):
        self.configure(frame, sparse)
        for eid, (shape, cx, cy, r, pts) in enumerate(shapes):
            map_geo.register_entity(eid, shape, cx, cy, r, pts)

    def test_masks_and_tile_owners_agree_on_every_frame(self):
        for frame in FRAMES:
            shapes = random_shapes(random.Random(1008 + frame[0]), frame, 140)
            self.build(frame, False, shapes)
            dense = ({e: map_geo.MAP_GEO[e]["tile_mask"].clone() for e in map_geo.MAP_GEO}, dict(map_geo.TILE_TO_ENTITY))
            self.build(frame, True, shapes)
            self.assertEqual(set(map_geo.MAP_GEO), set(dense[0]))
            for eid in dense[0]:
                self.assertNotIn("tile_mask", map_geo.MAP_GEO[eid])
                self.assertTrue(torch.equal(map_geo.tile_mask(eid), dense[0][eid]), (frame, eid, shapes[eid][0]))
                self.assertEqual(map_geo.tiles_of(eid), torch.where(dense[0][eid].reshape(-1))[0].tolist(), (frame, eid))
            self.assertEqual(map_geo.TILE_TO_ENTITY, dense[1], frame)         # includes the last-writer order of overlapping entities

    def test_register_replace_unregister_and_mutate_keep_the_lookup_identical(self):
        frame = FRAMES[0]
        shapes = random_shapes(random.Random(5), frame, 60)
        results = []
        for sparse in (False, True):
            self.build(frame, sparse, shapes)
            version = map_geo.geo_version
            map_geo.register_entity(3, "circle", 100.0, 100.0, 40.0)                      # replace: later writer wins on shared tiles
            map_geo.geo_mutate(7, r=60.0, cx=300.0)
            map_geo.unregister_entity(11)
            map_geo.unregister_entity(10_000)                                              # unknown id: no-op
            results.append((dict(map_geo.TILE_TO_ENTITY), map_geo.geo_version - version, {e: map_geo.tiles_of(e) for e in map_geo.MAP_GEO}))
        self.assertEqual(results[0], results[1])

    def test_lookups_agree(self):
        frame = FRAMES[0]
        shapes = random_shapes(random.Random(6), frame, 80)
        m = torch.zeros((cfg.MAX_ENTITIES, 32))
        for eid, (_, cx, cy, _, _) in enumerate(shapes):
            m[eid, cfg.CX], m[eid, cfg.CY], m[eid, cfg.M_TYPE] = cx, cy, float(1 + eid % 7)
        rng = random.Random(7)
        points = [(rng.uniform(-80, 1300), rng.uniform(-80, 940)) for _ in range(400)]
        out = []
        for sparse in (False, True):
            self.build(frame, sparse, shapes)
            out.append(([map_geo.entity_at(x, y) for x, y in points],
                        [map_geo.entities_in_radius(x, y, 90.0, m) for x, y in points[:40]],
                        map_geo.background_tile_types(m).tolist()))
        self.assertEqual(out[0], out[1])

    def test_a_polygon_is_filled_the_same_when_it_hangs_over_the_frame_edge(self):
        frame = (40, 30, 0, 0)
        square = [(-50.0, -50.0), (200.0, -40.0), (230.0, 300.0), (-60.0, 280.0)]
        self.configure(frame, False)
        map_geo.register_entity(0, "polygon", 70.0, 120.0, 0.0, square)
        dense = map_geo.MAP_GEO[0]["tile_mask"].clone()
        self.configure(frame, True)
        map_geo.register_entity(0, "polygon", 70.0, 120.0, 0.0, square)
        self.assertTrue(torch.equal(map_geo.tile_mask(0), dense))
        self.assertGreater(int(dense.sum()), 100)

    def test_an_entity_outside_the_frame_covers_nothing_and_a_non_finite_radius_covers_all(self):
        self.configure((10, 10, 0, 0), True)
        map_geo.register_entity(0, "circle", 5000.0, 5000.0, 20.0)
        map_geo.register_entity(1, "circle", 40.0, 40.0, float("inf"))
        self.assertEqual(map_geo.tiles_of(0), [])
        self.assertEqual(len(map_geo.tiles_of(1)), 100)

    def test_space_clipping_agrees_inside_the_frame_offset(self):
        rects = [(1, 200.0, 100.0, 296.0, 180.0)]                                           # one interior inside the frame
        frame = (60, 40, 10, 5)
        shapes = [("circle", 250.0, 140.0, 300.0, None), ("circle", 240.0, 130.0, 30.0, None), ("circle", 200.0, 300.0, 80.0, None),
                  ("polygon", 250.0, 130.0, 0.0, [(180.0, 90.0), (320.0, 95.0), (300.0, 200.0), (190.0, 190.0)])]
        outs = []
        with mock.patch.dict(os.environ, {"EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1"}), \
                mock.patch.object(spaces, "_active_rectangles", return_value=rects):
            for sparse in (False, True):
                self.build(frame, sparse, shapes)
                outs.append([map_geo.tile_mask(e).clone() for e in range(len(shapes))])
        for a, b in zip(*outs):
            self.assertTrue(torch.equal(a, b))
        self.assertLess(int(outs[0][0].sum()), 60 * 40, "the clip actually removed tiles")



class FrameTests(GeoStateIsolation, unittest.TestCase):
    def test_default_frame_is_the_legacy_one_and_configure_needs_an_empty_registry(self):
        self.assertEqual(map_geo.window_frame(), {"grid_w": cfg.GRID_W, "grid_h": cfg.GRID_H, "origin_tile": [0, 0], "sparse": False})
        map_geo.register_entity(1, "circle", 40.0, 40.0, 10.0)
        with self.assertRaises(RuntimeError):
            map_geo.configure_window(10, 10)
        with self.assertRaises(ValueError):
            map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear(); map_geo.configure_window(0, 10)

    def test_pixels_and_tiles_round_trip_in_an_offset_frame(self):
        self.configure((352, 352, -160, -160), True)
        for px, py in ((-1280.0, -1280.0), (0.0, 0.0), (1535.0, 1535.0), (-0.5, 7.9), (8.0, -8.0)):
            idx = map_geo._px_to_tile_idx(px, py)
            cx, cy = map_geo.tile_center_px(idx)
            self.assertLessEqual(abs(cx - px), 4.0 + 1e-9), self.assertLessEqual(abs(cy - py), 4.0 + 1e-9)
        self.assertEqual(map_geo._px_to_tile_idx(-1281.0, 0.0), map_geo._px_to_tile_idx(-1280.0, 0.0), "clamped to the frame")
        self.assertEqual(map_geo._px_to_tile_idx(0.0, 0.0), 160 * 352 + 160)
        self.assertEqual(map_geo.tile_center_px(160 * 352 + 160), (4.0, 4.0))

    def test_the_legacy_clamp_and_truncation_are_unchanged(self):
        for px, py in ((0.0, 0.0), (-3.0, -0.2), (1199.9, 895.9), (9999.0, 9999.0), (7.99, 8.0)):
            col, row = max(0, min(int(px / cfg.TILE_SIZE), cfg.GRID_W - 1)), max(0, min(int(py / cfg.TILE_SIZE), cfg.GRID_H - 1))
            self.assertEqual(map_geo._px_to_tile_idx(px, py), row * cfg.GRID_W + col)


class SparseWorldTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """The real two-map world registers the same geometry sparse as dense, and a sparse snapshot round-trips."""
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.addCleanup(map_geo.reset_window)
        self.addCleanup(backend.engine.reset_world)

    async def world(self, sparse):
        backend.engine.reset_world()
        map_geo.reset_window()
        if sparse:
            map_geo.configure_window(cfg.GRID_W, cfg.GRID_H, (0, 0), sparse=True)
        random.seed(1008); torch.manual_seed(1008)
        engine = await real_world()
        return engine, {e: map_geo.tiles_of(e) for e in map_geo.MAP_GEO}, dict(map_geo.TILE_TO_ENTITY)

    async def test_starter_village_geometry_is_identical_sparse_and_dense(self):
        _, dense_tiles, dense_owner = await self.world(False)
        engine, sparse_tiles, sparse_owner = await self.world(True)
        self.assertGreater(len(dense_tiles), 3)
        self.assertEqual(sparse_tiles, dense_tiles)
        self.assertEqual(sparse_owner, dense_owner)
        m = engine.state.m_tensor
        for eid in list(dense_tiles)[:25]:
            cx, cy = float(m[eid, cfg.CX]), float(m[eid, cfg.CY])
            self.assertEqual(map_geo.entity_at(cx, cy), dense_owner.get(map_geo._px_to_tile_idx(cx, cy), -1))

    async def test_sparse_snapshot_has_no_masks_and_restores_the_same_geometry(self):
        engine, tiles, owners = await self.world(True)
        payload = codec.loads(world_snapshot.capture(engine, map_geo))
        geometry = payload["geometry"]
        self.assertEqual(geometry["frame"], map_geo.window_frame())
        self.assertTrue(all("tile_box" not in s and "tile_mask" not in s for s in geometry["shapes"].values()))
        version = map_geo.geo_version
        world_snapshot.restore(payload, engine, map_geo, backend.ar.PlayerControlRuntime)
        self.assertEqual({e: map_geo.tiles_of(e) for e in map_geo.MAP_GEO}, tiles)
        self.assertEqual(dict(map_geo.TILE_TO_ENTITY), owners)
        self.assertEqual(map_geo.geo_version, version)

    async def test_dense_snapshot_is_unchanged_and_a_frame_mismatch_is_refused(self):
        engine, _, _ = await self.world(False)
        dense = codec.loads(world_snapshot.capture(engine, map_geo))
        self.assertNotIn("frame", dense["geometry"])
        self.assertTrue(all("tile_mask" in s for s in dense["geometry"]["shapes"].values()))
        world_snapshot.validate(dense, engine)
        engine, _, _ = await self.world(True)
        sparse = codec.loads(world_snapshot.capture(engine, map_geo))
        world_snapshot.validate(sparse, engine)
        with self.assertRaises(ValueError):
            world_snapshot.validate(dense, engine)                       # a dense save into a sparse session
        map_geo.reset_window()
        with self.assertRaises(ValueError):
            world_snapshot.validate(sparse, engine)                      # and the other way round


if __name__ == "__main__":
    unittest.main()
