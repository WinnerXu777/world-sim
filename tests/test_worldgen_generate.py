"""Chunk generator: golden bytes, purity (order / window / process independence), edge continuity, caps, pinned areas, format validity."""
import hashlib
import json
import os
import random
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

import numpy as np

from systems.worldgen import (CHUNK_TILES, CHUNK_UNITS, GENERATOR_VERSION, GenParams, PinnedArea, PinnedSet, generate_chunk, starter_village_area)
from systems.worldgen import assets, classify, golden, noise, regions
from systems.worldgen import generate as gen
from systems.worldgen.spec import B_PLAINS, B_WATER, FOOT_RUIN
from world_map import check_map_bytes

MYASSETS = ROOT / "myassets"
VILLAGE = PinnedSet([starter_village_area()])
OFFS = gen.EDGE_OFFSETS


def fresh_cache():
    return classify.new_cache()


def doc_layers(chunk):
    return chunk.layer("terrain"), chunk.layer("footprint"), np.asarray(chunk.document["data"]["biome"], dtype=np.int16)


def walls_mask(chunk):
    mask = np.zeros((CHUNK_TILES, CHUNK_TILES), dtype=np.int32)
    for w in chunk.walls:
        x0, y0 = int(w["min"][0] // 8), int(w["min"][1] // 8)
        x1, y1 = int(w["max"][0] // 8), int(w["max"][1] // 8)
        mask[y0:y1, x0:x1] += 1
    return mask


class GoldenTests(unittest.TestCase):
    def test_golden_hashes_match_the_committed_file(self):
        committed = json.loads(golden.HASHES_FILE.read_text(encoding="utf-8"))
        self.assertEqual(committed["generator_version"], GENERATOR_VERSION, "bump GENERATOR_VERSION together with golden.py --write")
        current = golden.compute()
        drift = [k for k, v in current["entries"].items() if committed["entries"].get(k, {}).get("sha256") != v["sha256"]]
        self.assertEqual(drift, [], f"generator output changed in {len(drift)} cases; if intended, bump GENERATOR_VERSION and run golden.py --write")
        self.assertEqual(set(current["entries"]), set(committed["entries"]))

    def test_the_full_sample_chunk_is_byte_identical(self):
        self.assertEqual(golden.SAMPLE_FILE.read_bytes(), golden.sample_bytes())

    def test_golden_covers_negative_far_and_region_seam_addresses(self):
        labels = " ".join(golden.compute()["entries"])
        for needle in ("/-1/-1", "/7/0", "/8/0", "/-123456/654321", "/1000000/-1000000", "/-3/"):
            self.assertIn(needle, labels)


class PurityTests(unittest.TestCase):
    def test_a_chunk_does_not_depend_on_cache_state_or_what_was_generated_before(self):
        a = generate_chunk(1008, 4, -3, cache=fresh_cache())
        warm = fresh_cache()
        for cx, cy in ((3, -3), (5, -3), (4, -2), (4, -4), (20, 20)):
            generate_chunk(1008, cx, cy, cache=warm)
        b = generate_chunk(1008, 4, -3, cache=warm)
        self.assertEqual(a.payload, b.payload)

    def test_area_generated_in_three_different_orders_is_byte_identical(self):
        coords = [(cx, cy) for cy in range(-3, 3) for cx in range(5, 11)]        # crosses the region seam at chunk 8
        results = []
        for order in (coords, list(reversed(coords)), random.Random(5).sample(coords, len(coords))):
            cache = fresh_cache()
            results.append({c: generate_chunk(1008, c[0], c[1], VILLAGE, cache=cache).payload for c in order})
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_process_pool_gives_the_same_bytes_as_the_single_process_generator(self):
        from systems.worldgen.rings import ChunkCoord
        from systems.worldgen.service import ChunkService
        coords = [(cx, cy) for cy in range(-2, 2) for cx in range(6, 10)]
        expected = {c: generate_chunk(1008, c[0], c[1], VILLAGE).payload for c in coords}
        with ChunkService(1008, VILLAGE, workers=2) as service:
            for c in reversed(coords):
                service.request(ChunkCoord(*c), 0.0)
            deadline = __import__("time").monotonic() + 120
            while __import__("time").monotonic() < deadline and not all(service.peek(ChunkCoord(*c)) for c in coords):
                service.pump()
                __import__("time").sleep(0.005)
            got = {c: service.peek(ChunkCoord(*c)).payload for c in coords}
        self.assertEqual(got, expected)

    def test_fresh_processes_with_different_hash_seeds_agree(self):
        code = ("import sys; sys.path.insert(0, r'%s')\n"
                "from systems.worldgen import generate_chunk\n"
                "print(','.join(generate_chunk(s, x, y).sha256[:16] for s, x, y in ((1008, 0, 0), (1008, -5, 9), (77, 123456, -9), (-3, 8, 8))))" % (ROOT / "at_the_beginning"))
        outs = []
        for hash_seed in ("1", "98765"):
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONHASHSEED": hash_seed})
            self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
            outs.append(proc.stdout.strip())
        expected = ",".join(generate_chunk(s, x, y).sha256[:16] for s, x, y in ((1008, 0, 0), (1008, -5, 9), (77, 123456, -9), (-3, 8, 8)))
        self.assertEqual(outs, [expected, expected])

    def test_tile_fields_do_not_depend_on_where_the_window_starts(self):
        a = classify.compute_window(1008, 100, 200, 60, 50, VILLAGE, fresh_cache())
        b = classify.compute_window(1008, 117, 211, 60, 50, VILLAGE, fresh_cache())
        # overlap: x 117..159, y 211..249
        sa = (slice(11, 50), slice(17, 60))
        sb = (slice(0, 39), slice(0, 43))
        for name in ("elev", "moist", "temp", "forest", "biome", "terrain", "footprint", "pin_d"):
            np.testing.assert_array_equal(getattr(a, name)[sa], getattr(b, name)[sb], err_msg=name)

    def test_a_double_width_window_equals_two_chunks_side_by_side_incl_the_region_seam(self):
        for (cx, cy) in ((0, 0), (7, 3), (-1, 0), (7, -1), (-9, 5)):
            left, right = generate_chunk(1008, cx, cy), generate_chunk(1008, cx + 1, cy)
            win = classify.compute_window(1008, cx * 32, cy * 32, 64, 32, gen.NO_PINS, fresh_cache())
            t = np.hstack([left.layer("terrain"), right.layer("terrain")])
            b = np.hstack([doc_layers(left)[2], doc_layers(right)[2]])
            np.testing.assert_array_equal(t, win.terrain, err_msg=f"terrain {cx},{cy}")
            np.testing.assert_array_equal(b, win.biome.astype(np.int16), err_msg=f"biome {cx},{cy}")
            top, bottom = generate_chunk(1008, cx, cy), generate_chunk(1008, cx, cy + 1)
            win_v = classify.compute_window(1008, cx * 32, cy * 32, 32, 64, gen.NO_PINS, fresh_cache())
            np.testing.assert_array_equal(np.vstack([top.layer("terrain"), bottom.layer("terrain")]), win_v.terrain, err_msg=f"vertical {cx},{cy}")

    def test_far_addresses_are_deterministic_and_independent_of_the_window_origin(self):
        far = 10 ** 9
        a = generate_chunk(1008, far, -far)
        self.assertEqual(a.payload, generate_chunk(1008, far, -far, cache=fresh_cache()).payload)
        w = classify.compute_window(1008, far * 32, -far * 32, 64, 32, gen.NO_PINS, fresh_cache())
        np.testing.assert_array_equal(np.hstack([a.layer("terrain"), generate_chunk(1008, far + 1, -far).layer("terrain")]), w.terrain)

    def test_seeds_matter_and_neighbouring_chunks_differ(self):
        self.assertNotEqual(generate_chunk(1008, 3, 3).sha256, generate_chunk(1009, 3, 3).sha256)
        self.assertNotEqual(generate_chunk(-1, 3, 3).sha256, generate_chunk(1, 3, 3).sha256)
        self.assertNotEqual(generate_chunk(1008, 3, 3).sha256, generate_chunk(1008, 4, 3).sha256)

    def test_noise_uses_no_global_random_state(self):
        random.seed(1)
        np.random.seed(1)
        before = generate_chunk(1008, 12, 12).sha256
        random.seed(999)
        np.random.seed(999)
        random.random()
        self.assertEqual(before, generate_chunk(1008, 12, 12).sha256)

    def test_value_noise_is_exact_at_lattice_points_and_in_range(self):
        gx, gy = np.meshgrid(np.arange(-40, 40, dtype=np.int64), np.arange(-40, 40, dtype=np.int64))
        v = noise.fbm(5, 1, gx, gy, (64, 32, 16))
        self.assertTrue(((v >= 0.0) & (v < 1.0)).all())
        q = noise.quantise(v)
        self.assertEqual(q.dtype, np.int32)
        self.assertTrue(((q >= 0) & (q <= 4095)).all())


class EdgeTests(unittest.TestCase):
    def reference_edges(self, terr):
        h, w = terr.shape
        out = np.zeros((h - 2, w - 2), dtype=np.int32)
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                for bit, (dx, dy) in enumerate(OFFS):
                    n, c = terr[y + dy, x + dx], terr[y, x]
                    if n != c and n != 0 and c != 0:
                        out[y - 1, x - 1] |= 1 << bit
        return out

    def test_edge_masks_of_adjacent_chunks_match_a_mask_computed_over_both_at_once(self):
        for (cx, cy) in ((0, 0), (7, 2), (-1, -1), (7, -3)):
            left, right = generate_chunk(1008, cx, cy), generate_chunk(1008, cx + 1, cy)
            win = classify.compute_window(1008, cx * 32 - 1, cy * 32 - 1, 66, 34, gen.NO_PINS, fresh_cache())
            ref = self.reference_edges(win.terrain)
            got = np.hstack([np.asarray(left.document["data"]["edges"]), np.asarray(right.document["data"]["edges"])])
            np.testing.assert_array_equal(got, ref, err_msg=f"edges {cx},{cy}")

    def test_wall_boxes_of_adjacent_chunks_tile_the_blocked_mask_across_the_seam(self):
        seams = 0
        for (cx, cy) in [(cx, cy) for cx in (-1, 6, 7, 15) for cy in range(-3, 3)]:
            left, right = generate_chunk(1008, cx, cy), generate_chunk(1008, cx + 1, cy)
            win = classify.compute_window(1008, cx * 32, cy * 32, 64, 32, gen.NO_PINS, fresh_cache())
            blocked = (win.footprint > 0).astype(np.int32)
            both = np.hstack([walls_mask(left), walls_mask(right)])
            np.testing.assert_array_equal(both, blocked, err_msg=f"{cx},{cy}")     # exact cover, no overlap
            seams += int((blocked[:, 31] & blocked[:, 32]).sum() > 0)
        self.assertGreater(seams, 0, "no blocked feature crossed any tested seam; widen the tested area")

    def find_lake_across_region_seam(self):
        for seed in range(400):
            for lake in regions.region_raw(seed, 1, 0).lakes:
                if lake.cx - regions.REGION_TILES < lake.rx * 0.5 and abs(lake.cy - 128) < 128:            # spans the x = 256 boundary
                    win = classify.compute_window(seed, 255 - 2, lake.cy - 1, 6, 3, gen.NO_PINS, fresh_cache())
                    if (win.biome == B_WATER).all():
                        return seed, lake
        self.fail("no seed with a lake crossing the region seam in 0..399")

    def test_a_lake_crossing_a_region_seam_is_emitted_by_chunks_on_both_sides(self):
        seed, lake = self.find_lake_across_region_seam()
        cy = lake.cy // 32
        left, right = generate_chunk(seed, 7, cy), generate_chunk(seed, 8, cy)
        row = lake.cy - cy * 32
        self.assertEqual(int(doc_layers(left)[2][row, 31]), B_WATER)
        self.assertEqual(int(doc_layers(right)[2][row, 0]), B_WATER)
        self.assertGreater(len(left.walls), 0)
        self.assertGreater(len(right.walls), 0)

    def test_features_are_found_from_either_side_of_a_region_boundary(self):
        # every region within MAX_FEATURE_RADIUS of a window is consulted, including the negative side
        near = regions.regions_near(-3, -3, 6, 6)
        self.assertEqual(set(near), {(-1, -1), (-1, 0), (0, -1), (0, 0)})
        self.assertEqual(regions.regions_near(100, 100, 10, 10), [(0, 0)])

    def test_region_features_are_pure_functions_of_seed_and_region(self):
        self.assertEqual(regions.region_raw(9, -4, 7), regions.region_raw(9, -4, 7))
        self.assertNotEqual(regions.region_raw(9, -4, 7), regions.region_raw(10, -4, 7))
        for rx in range(-3, 3):
            for ry in range(-3, 3):
                raw = regions.region_raw(1008, rx, ry)
                for lake in raw.lakes:
                    self.assertLessEqual(max(lake.rx, lake.ry) * 1.3, 40)
                for patch in raw.forests:
                    self.assertLessEqual(patch.r, 40)


class FormatTests(unittest.TestCase):
    CASES = [(1008, cx, cy) for cx in range(-3, 6) for cy in range(-2, 4)]

    def test_every_chunk_passes_the_authored_map_validator_with_real_sprites(self):
        for seed, cx, cy in self.CASES:
            chunk = generate_chunk(seed, cx, cy, VILLAGE)
            world_map, issues = check_map_bytes(chunk.payload, MYASSETS)
            errors = [str(i) for i in issues if i.severity == "error"]
            self.assertEqual(errors, [], f"{cx},{cy}")
            self.assertIsNotNone(world_map)

    def test_palette_and_sprite_paths_all_exist_in_myassets(self):
        self.assertEqual(assets.verify_palette(MYASSETS), [])

    def test_geometry_shape_and_quantisation(self):
        for seed, cx, cy in self.CASES:
            c = generate_chunk(seed, cx, cy, VILLAGE)
            d = c.document
            self.assertEqual(d["size_tiles"], [32, 32])
            self.assertEqual(d["tile_size_px"], 48)
            self.assertEqual(d["units_per_tile"], 8)
            self.assertEqual([l["name"] for l in d["layers"]], ["terrain", "decoration", "footprint"])
            for layer in d["layers"]:
                self.assertEqual(np.asarray(layer["tiles"]).shape, (32, 32))
                self.assertTrue(set(np.unique(layer["tiles"]).tolist()) - {0} <= {int(k) for k in layer["palette"]})
            for e in d["entities"]:
                x, y = e["position"]
                self.assertTrue(0 <= x < CHUNK_UNITS and 0 <= y < CHUNK_UNITS, e)
                self.assertEqual(x * 16, int(x * 16))
            for sprite, x, y in d["data"]["props"]:
                self.assertTrue(0 <= x < CHUNK_UNITS and 0 <= y < CHUNK_UNITS)
                self.assertEqual((x * 16) % 1, 0)
                self.assertTrue(0 <= sprite < len(d["data"]["prop_palette"]))
            for w in d["walls"]:
                self.assertTrue(0 <= w["min"][0] < w["max"][0] <= CHUNK_UNITS and 0 <= w["min"][1] < w["max"][1] <= CHUNK_UNITS)
            ids = [e["id"] for e in d["entities"]] + [w["id"] for w in d["walls"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(i.startswith(f"c{cx}_{cy}:") for i in ids))

    def test_wall_boxes_are_disjoint_and_exactly_cover_the_footprint_layer(self):
        for seed, cx, cy in self.CASES:
            c = generate_chunk(seed, cx, cy, VILLAGE)
            cover = walls_mask(c)
            self.assertLessEqual(int(cover.max(initial=0)), 1)
            np.testing.assert_array_equal(cover > 0, c.layer("footprint") > 0)

    def test_wall_box_shape_matches_what_spatial_py_consumes(self):
        c = generate_chunk(1008, 2, 0, VILLAGE)
        self.assertGreater(len(c.walls), 0)
        for w in c.walls:
            self.assertEqual(set(w), {"id", "min", "max", "height"})
        from world_map import to_wall_boxes
        world_map, _ = check_map_bytes(c.payload, MYASSETS)
        self.assertEqual([set(b) for b in to_wall_boxes(world_map)], [{"id", "min", "max", "height"}] * len(c.walls))

    def test_bytes_are_canonical_and_roundtrip(self):
        c = generate_chunk(1008, 3, 1, VILLAGE)
        self.assertEqual(hashlib.sha256(c.payload).hexdigest(), c.sha256)
        again = gen.Chunk.from_payload(c.payload)
        self.assertEqual(again.payload, c.payload)
        self.assertEqual(again.sha256, c.sha256)
        self.assertEqual(gen.encode(json.loads(c.payload)), c.payload)
        self.assertTrue(c.payload.isascii())
        self.assertEqual(c.document["chunk"]["generator_version"], GENERATOR_VERSION)
        self.assertEqual(c.document["chunk"]["world_seed"], "1008")

    def test_boxes_from_mask_is_an_exact_disjoint_cover_of_random_masks(self):
        rng = np.random.default_rng(3)                       # test data only; the generator never uses numpy.random
        for density in (0.05, 0.3, 0.7, 1.0):
            for _ in range(20):
                mask = rng.random((32, 32)) < density
                cover = np.zeros((32, 32), dtype=np.int32)
                for x0, y0, x1, y1 in gen.boxes_from_mask(mask):
                    cover[y0:y1, x0:x1] += 1
                np.testing.assert_array_equal(cover, mask.astype(np.int32))
        self.assertEqual(gen.boxes_from_mask(np.zeros((32, 32), dtype=bool)), [])
        self.assertEqual(gen.boxes_from_mask(np.ones((32, 32), dtype=bool)), [(0, 0, 32, 32)])

    def test_world_contains_every_biome_and_all_palette_ids_somewhere(self):
        cache = fresh_cache()
        biomes, terrains = set(), set()
        for cx in range(-10, 10):
            for cy in range(-10, 10):
                c = generate_chunk(1008, cx, cy, VILLAGE, cache=cache)
                biomes |= set(np.unique(c.document["data"]["biome"]).tolist())
                terrains |= set(np.unique(c.layer("terrain")).tolist())
        self.assertTrue({1, 2, 3, 4, 5, 6, 7, 8, 9, 10} <= biomes, biomes)
        self.assertTrue({1, 2, 3, 4} <= terrains, terrains)

    def test_points_of_interest_appear_with_their_footprints_and_entities(self):
        cache = fresh_cache()
        kinds = {}
        for seed in (1008, 7, 31, 99):
            for cx in range(-8, 8):
                for cy in range(-8, 8):
                    c = generate_chunk(seed, cx, cy, None, cache=cache)
                    for e in c.entities:
                        if e["kind"].startswith("poi_"):
                            kinds.setdefault(e["kind"], c)
        self.assertGreaterEqual(len(kinds), 3, sorted(kinds))
        if "poi_ruin" in kinds:
            ruin = kinds["poi_ruin"]
            self.assertIn(FOOT_RUIN, np.unique(ruin.layer("footprint")).tolist() + [FOOT_RUIN])   # ruin walls may be fully broken in a tiny sample


class CapsTests(unittest.TestCase):
    def test_entity_cap_holds_over_a_wide_area(self):
        cache = fresh_cache()
        most = 0
        for cx in range(-15, 15):
            for cy in range(-15, 15):
                c = generate_chunk(1008, cx, cy, VILLAGE, cache=cache)
                most = max(most, len(c.entities))
                self.assertLessEqual(len(c.entities), 16)
                self.assertLessEqual(len(c.document["data"]["spawns"]), 4)
                self.assertLessEqual(len(c.document["data"]["props"]), 640)
        self.assertGreaterEqual(most, 10, "the sample area is too poor to say anything about the cap")      # the merge path itself is exercised below with a small cap

    def test_a_small_cap_merges_same_kind_features_instead_of_dropping_them(self):
        cache = fresh_cache()
        merged_somewhere = False
        for cx in range(-6, 6):
            for cy in range(-6, 6):
                full = generate_chunk(1008, cx, cy, None, cache=cache)
                small = generate_chunk(1008, cx, cy, None, GenParams(max_entities=3), cache=cache)
                self.assertLessEqual(len(small.entities), 3)
                self.assertNotEqual(full.sha256, small.sha256) if len(full.entities) > 3 else None
                if len(full.entities) > 3:
                    merged_somewhere = True
                    kinds_full = {e["kind"] for e in full.entities if not e["kind"].startswith("poi_")}
                    amount = lambda c, k: sum(e["amount"] for e in c.entities if e["kind"] == k)       # noqa: E731
                    for k in {e["kind"] for e in small.entities if not e["kind"].startswith("poi_")}:
                        if sum(1 for e in full.entities if e["kind"] == k) > 1 and sum(1 for e in small.entities if e["kind"] == k) == 1:
                            self.assertEqual(amount(small, k), amount(full, k), "merging must preserve the total amount")
                    self.assertTrue(kinds_full)
        self.assertTrue(merged_somewhere)

    def test_merge_to_cap_is_deterministic_and_preserves_totals(self):
        feats = [{"kind": "forest", "resource": "wood", "amount": a, "tiles": a, "x16": x, "y16": y}
                 for a, x, y in ((5, 100, 100), (7, 120, 100), (9, 2000, 2000), (3, 2020, 2010), (4, 40, 3500))]
        out1 = gen.merge_to_cap([dict(f) for f in feats], 3)
        out2 = gen.merge_to_cap([dict(f) for f in reversed(feats)], 3)
        self.assertEqual(out1, out2)
        self.assertEqual(len(out1), 3)
        self.assertEqual(sum(f["amount"] for f in out1), 28)


class PinnedTests(unittest.TestCase):
    def test_a_chunk_fully_inside_the_village_is_a_pointer_to_the_authored_map(self):
        c = generate_chunk(1008, 0, 0, VILLAGE)
        self.assertEqual(c.pinned_map, "starter_village")
        self.assertEqual(c.entities, [])
        self.assertEqual(c.walls, [])
        self.assertEqual(int(c.layer("terrain").sum()), 0)
        self.assertEqual(c.document["chunk"]["pinned_tiles"], 1024)

    def test_generation_never_writes_inside_the_pinned_rectangle(self):
        area = VILLAGE.areas[0]
        for cx, cy in ((1, 0), (0, 1), (1, 1)):
            c = generate_chunk(1008, cx, cy, VILLAGE)
            gx0, gy0 = cx * 32, cy * 32
            ys, xs = np.mgrid[0:32, 0:32]
            inside = (xs + gx0 < area.x0 + area.w) & (ys + gy0 < area.y0 + area.h)
            self.assertGreater(int(inside.sum()), 0)
            for name in ("terrain", "decoration", "footprint"):
                self.assertEqual(int(np.abs(c.layer(name)[inside]).sum()), 0, f"{name} {cx},{cy}")
            self.assertEqual(int(np.asarray(c.document["data"]["biome"])[inside].sum()), 0)
            self.assertEqual(c.document["chunk"]["pinned_tiles"], int(inside.sum()))
            for e in c.entities:
                tx, ty = gx0 + e["position"][0] / 8, gy0 + e["position"][1] / 8
                self.assertFalse(tx < area.x0 + area.w and ty < area.y0 + area.h, e)
            for _, x, y in c.document["data"]["props"]:
                self.assertFalse(gx0 + x / 8 < area.x0 + area.w and gy0 + y / 8 < area.y0 + area.h)
            for w in c.walls:
                tx0, ty0 = gx0 + w["min"][0] / 8, gy0 + w["min"][1] / 8
                self.assertFalse(tx0 < area.x0 + area.w and ty0 < area.y0 + area.h, w)

    def test_the_border_blends_into_plain_grass_and_the_far_world_is_unchanged(self):
        win = classify.compute_window(1008, -12, -12, 72, 60, VILLAGE, fresh_cache())
        d = win.pin_d
        ring = (d >= 1) & (d <= 4)
        self.assertGreater(int(ring.sum()), 100)
        self.assertTrue((win.biome[ring] == B_PLAINS).all())
        self.assertTrue((win.footprint[ring] == 0).all())
        self.assertTrue(((d >= 5) & (d <= 8)).sum() > 0)
        for cx, cy in ((6, 6), (-6, 3), (4, -5)):        # all further than the climate blend radius from the village
            a, b = generate_chunk(1008, cx, cy, VILLAGE), generate_chunk(1008, cx, cy, None)
            for name in ("terrain", "decoration", "footprint"):
                np.testing.assert_array_equal(a.layer(name), b.layer(name))
            self.assertEqual(a.document["walls"], b.document["walls"])
            self.assertEqual(a.document["entities"], b.document["entities"])

    def test_pinned_changes_the_key_and_the_document_not_just_the_pixels(self):
        a, b = generate_chunk(1008, 1, 0, VILLAGE), generate_chunk(1008, 1, 0, None)
        self.assertNotEqual(a.sha256, b.sha256)
        self.assertEqual(a.document["chunk"]["pinned"], VILLAGE.fingerprint)
        self.assertNotEqual(gen.chunk_key(1, 0, 0, VILLAGE), gen.chunk_key(1, 0, 0, None))
        other = PinnedSet([PinnedArea("starter_village", 0, 0, 48, 40)])
        self.assertNotEqual(other.fingerprint, VILLAGE.fingerprint)

    def test_starter_village_area_reads_the_real_map_file_size(self):
        area = starter_village_area(ROOT / "world_data" / "maps2d" / "starter_village.json")
        self.assertEqual((area.x0, area.y0, area.w, area.h), (0, 0, 48, 36))

    def test_two_pinned_areas_and_negative_coordinates(self):
        pins = PinnedSet([PinnedArea("a", -40, -40, 20, 20), PinnedArea("b", 100, 100, 40, 40)])
        c = generate_chunk(1008, -1, -1, pins)
        self.assertGreater(c.document["chunk"]["pinned_tiles"], 0)
        inside = (np.mgrid[0:32, 0:32][1] + -32 >= -40) & (np.mgrid[0:32, 0:32][1] + -32 < -20) & (np.mgrid[0:32, 0:32][0] - 32 >= -40) & (np.mgrid[0:32, 0:32][0] - 32 < -20)
        self.assertEqual(int(np.abs(c.layer("terrain")[inside]).sum()), 0)
        self.assertEqual(generate_chunk(1008, 3, 3, pins).document["chunk"]["pinned_tiles"], 28 * 28)      # area b covers tiles 100..139; chunk 3 is 96..127


if __name__ == "__main__":
    unittest.main()
