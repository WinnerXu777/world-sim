"""Authored map file: schema, loader, validator, spatial conversion (format 0.1-draft)."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from world_map import (MapValidationError, check_map_file, check_portal_targets, load_map, loads_strict,  # noqa: E402
                       parse_map, to_movement_contract, to_wall_boxes, validate_map)
from world_map.validate import walkable_grid  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "maps"
VILLAGE = FIXTURES / "tiny_village.json"
INTERIOR = FIXTURES / "tiny_interior.json"
RADIUS = 0.35  # spatial.RADIUS; asserted against the real constant in SpatialBridgeTests


def raw(path=VILLAGE):
    return json.loads(path.read_text(encoding="utf-8"))


def errors(issues):
    return [i for i in issues if i.severity == "error"]


_DEFAULT = object()


def check(data, base_dir=FIXTURES, radius=_DEFAULT):
    """Parse + validate a dict, as the loader would. radius=None means use the file's actor_radius."""
    world_map, issues = parse_map(data)
    if world_map is not None and not errors(issues):
        issues = issues + validate_map(world_map, base_dir, RADIUS if radius is _DEFAULT else radius)
    return issues


def has_error(issues, text):
    return any(text in str(i) for i in errors(issues))


class FixtureTests(unittest.TestCase):
    def test_fixtures_load_cleanly(self):
        village = load_map(VILLAGE, base_dir=FIXTURES, actor_radius=RADIUS)
        self.assertEqual((village.map_id, village.revision, village.format_version), ("tiny_village", 1, "0.2-draft"))
        self.assertEqual(village.units_per_tile, 2.0)
        self.assertEqual(village.bounds, [0.0, 0.0, 20.0, 16.0])
        self.assertEqual((len(village.walls), len(village.anchors), len(village.entities), len(village.portals)), (5, 4, 3, 1))
        self.assertEqual([layer.kind for layer in village.layers], ["terrain", "footprint"])
        self.assertFalse(next(e for e in village.entities if e.id == "tree_deco_01").interactive)
        interior = load_map(INTERIOR, base_dir=FIXTURES, actor_radius=RADIUS)
        self.assertEqual(interior.map_id, "tiny_interior")

    def test_cross_map_portals_resolve(self):
        maps = [load_map(VILLAGE, actor_radius=RADIUS), load_map(INTERIOR, actor_radius=RADIUS)]
        self.assertEqual(check_portal_targets(maps), [])
        self.assertTrue(any("not loaded" in str(i) for i in check_portal_targets(maps[:1])))

    def test_cross_map_portal_with_missing_target_anchor_is_an_error(self):
        data = raw(INTERIOR)
        data["anchors"] = [a for a in data["anchors"] if a["id"] != "interior_entry"]
        data["portals"] = []
        interior, _ = parse_map(data)
        issues = check_portal_targets([load_map(VILLAGE, actor_radius=RADIUS), interior])
        self.assertTrue(has_error(issues, "no anchor 'interior_entry'"))


class HeaderTests(unittest.TestCase):
    def test_units_per_tile_is_required_with_no_default(self):
        data = raw()
        del data["units_per_tile"]
        world_map, issues = parse_map(data)
        self.assertIsNone(world_map)
        self.assertTrue(has_error(issues, "units_per_tile"))

    def test_bad_header_values(self):
        for key, value in (("units_per_tile", 0), ("units_per_tile", -1), ("units_per_tile", "2"), ("units_per_tile", True),
                           ("tile_size_px", 0), ("tile_size_px", 48.5), ("size_tiles", [0, 8]), ("size_tiles", [10]),
                           ("size_tiles", [10, 8.5]), ("revision", -1), ("revision", None), ("map_id", "bad id!"),
                           ("format_version", "1.0")):
            with self.subTest(key=key, value=value):
                data = raw()
                data[key] = value
                world_map, issues = parse_map(data)
                self.assertIsNone(world_map)
                self.assertTrue(has_error(issues, key), issues)

    def test_units_per_tile_scales_bounds(self):
        data = raw()
        data["units_per_tile"] = 4.0
        world_map, _ = parse_map(data)
        self.assertEqual(world_map.bounds, [0.0, 0.0, 40.0, 32.0])

    def test_unknown_top_level_key_is_a_warning(self):
        data = raw()
        data["art_notes"] = "x"
        world_map, issues = parse_map(data)
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.path == "art_notes" for i in world_map.warnings))

    def test_non_finite_json_and_duplicate_keys_are_rejected(self):
        for text in ('{"units_per_tile": NaN}', '{"a": Infinity}', '{"a": 1, "a": 2}'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    loads_strict(text)

    def test_non_finite_numbers_from_python_dicts_are_rejected(self):
        data = raw()
        data["anchors"][0]["position"] = [float("nan"), 1]
        self.assertTrue(has_error(check(data), "anchors[0].position"))
        data = raw()
        data["units_per_tile"] = float("inf")
        self.assertTrue(has_error(parse_map(data)[1], "units_per_tile"))


class UniquenessAndBoundsTests(unittest.TestCase):
    def test_duplicate_ids(self):
        for collection, index, text in (("walls", 1, "walls[1].id"), ("anchors", 1, "anchors[1].id"),
                                        ("entities", 1, "entities[1].id"), ("portals", 0, None)):
            with self.subTest(collection=collection):
                data = raw()
                data[collection].append(copy.deepcopy(data[collection][0]))
                issues = check(data)
                self.assertTrue(has_error(issues, "duplicate id"), issues)

    def test_wall_and_entity_ids_share_one_namespace(self):
        data = raw()
        data["entities"][0]["id"] = data["walls"][0]["id"]
        self.assertTrue(has_error(check(data), "duplicate id"))

    def test_all_four_collections_share_one_id_namespace(self):
        for source, target in (("anchors", "walls"), ("anchors", "entities"), ("portals", "anchors"),
                               ("portals", "walls"), ("portals", "entities")):
            with self.subTest(source=source, target=target):
                data = raw()
                data[source][0]["id"] = data[target][0]["id"]
                self.assertTrue(has_error(check(data), "duplicate id"))

    def test_layer_names_are_a_separate_namespace(self):
        data = raw()
        data["layers"][0]["name"] = data["walls"][0]["id"]
        self.assertEqual(errors(check(data)), [])

    def test_coordinates_must_be_inside_bounds(self):
        cases = (("anchors", 0, "position", [21, 5]), ("anchors", 0, "position", [5, -0.1]),
                 ("entities", 0, "position", [8.5, 16.5]), ("walls", 0, "max", [20.5, 3]))
        for collection, index, key, value in cases:
            with self.subTest(collection=collection, value=value):
                data = raw()
                data[collection][index][key] = value
                self.assertTrue(has_error(check(data), "outside map bounds"))

    def test_degenerate_wall(self):
        data = raw()
        data["walls"][0]["max"] = data["walls"][0]["min"]
        self.assertTrue(has_error(check(data), "strictly less"))

    def test_entity_interactive_flag_must_be_explicit_bool(self):
        for value in (None, "yes", 1):
            data = raw()
            if value is None:
                del data["entities"][2]["interactive"]
            else:
                data["entities"][2]["interactive"] = value
            with self.subTest(value=value):
                self.assertTrue(has_error(check(data), "interactive"))

    def test_tile_grid_shape_and_palette(self):
        data = raw()
        data["layers"][0]["tiles"][0] = [1] * 9
        self.assertTrue(has_error(check(data), "layers[0].tiles[0]"))
        data = raw()
        data["layers"][0]["tiles"][2][2] = 9
        self.assertTrue(has_error(check(data), "not in the palette"))
        data = raw()
        data["layers"][0]["tiles"].pop()
        self.assertTrue(has_error(check(data), "layers[0].tiles"))
        data = raw()
        data["layers"][0]["kind"] = "ceiling"
        self.assertTrue(has_error(check(data), "kind"))


class GeometryTests(unittest.TestCase):
    def test_anchor_inside_wall_is_an_error(self):
        data = raw()
        data["anchors"][1]["position"] = [6.5, 5]  # inside wall_house_left
        self.assertTrue(has_error(check(data), "not standable"))

    def test_anchor_within_actor_radius_of_wall_is_an_error_but_just_outside_is_fine(self):
        data = raw()
        data["anchors"][1]["position"] = [7.3, 5]  # wall max x is 7; 7.3 < 7 + 0.35
        self.assertTrue(has_error(check(data), "not standable"))
        data["anchors"][1]["position"] = [7.36, 5]
        self.assertEqual([i for i in errors(check(data)) if "not standable" in str(i)], [])

    def test_anchor_too_close_to_map_edge_is_an_error(self):
        data = raw()
        data["anchors"][0]["position"] = [0.1, 12]
        self.assertTrue(has_error(check(data), "not standable"))
        data["anchors"][0]["position"] = [0.35, 12]
        self.assertEqual(errors(check(data)), [])

    def test_actor_radius_changes_the_answer(self):
        data = raw()
        data["anchors"][1]["position"] = [7.6, 5]
        self.assertEqual(errors(check(data, radius=0.35)), [])
        self.assertTrue(has_error(check(data, radius=0.7), "not standable"))

    def test_sealing_the_doorway_makes_interior_anchors_unreachable(self):
        data = raw()
        data["walls"].append({"id": "wall_door_plug", "min": [9.5, 8], "max": [11.5, 9]})
        issues = check(data)
        unreachable = [i for i in errors(issues) if "unreachable" in str(i)]
        self.assertEqual(sorted(i.path for i in unreachable), ["anchors[2]", "anchors[3]"])

    def test_door_gap_narrower_than_the_actor_is_unreachable(self):
        data = raw()
        data["walls"][3]["max"] = [11.0, 9]  # gap 11.0..11.5 = 0.5 < 2 * 0.35
        self.assertTrue(has_error(check(data), "unreachable"))
        data["walls"][3]["max"] = [10.0, 9]  # gap 10.0..11.5 = 1.5: passable
        self.assertEqual([i for i in errors(check(data)) if "unreachable" in str(i)], [])

    def test_walkable_grid_matches_slide_blocking(self):
        world_map, _ = parse_map(raw())
        grid, cols, rows, cell = walkable_grid(world_map, RADIUS)
        for x, y, expected in ((3, 12, True), (10.5, 10, True), (10.5, 8.5, True), (8, 8.5, False), (6.5, 5, False),
                               (10, 5, True), (0.1, 5, False)):
            with self.subTest(x=x, y=y):
                self.assertEqual(bool(grid[int(y / cell) * cols + int(x / cell)]), expected)


class SpriteTests(unittest.TestCase):
    def test_missing_sprite_file_is_an_error_only_when_base_dir_given(self):
        data = raw()
        data["entities"][0]["sprite"] = "sprites/missing.png"
        self.assertTrue(has_error(check(data, base_dir=FIXTURES), "sprite file not found"))
        self.assertEqual(errors(check(data, base_dir=None)), [])
        self.assertTrue(any(i.severity == "warning" and "not checked" in str(i) for i in check(data, base_dir=None)))

    def test_missing_palette_sprite_is_an_error(self):
        data = raw()
        data["layers"][0]["palette"]["2"] = "sprites/nope.png"
        self.assertTrue(has_error(check(data), "layers[0].palette.2"))

    def test_unsafe_sprite_references_are_rejected_without_a_base_dir(self):
        for ref in ("../secret.png", "sprites/../../x.png", "/abs/x.png", "C:/x.png", "..\\x.png"):
            with self.subTest(ref=ref):
                data = raw()
                data["entities"][0]["sprite"] = ref
                self.assertTrue(has_error(check(data, base_dir=None), "sprite reference must"))


class PortalTests(unittest.TestCase):
    def test_portal_from_unknown_anchor(self):
        data = raw()
        data["portals"][0]["from_anchor"] = "nope"
        self.assertTrue(has_error(check(data), "portals[0].from_anchor"))

    def test_portal_to_unknown_anchor_in_same_map(self):
        data = raw()
        data["portals"][0]["to_map"] = data["map_id"]
        data["portals"][0]["to_anchor"] = "nope"
        self.assertTrue(has_error(check(data), "portals[0].to_anchor"))

    def test_portal_from_non_door_anchor_warns(self):
        data = raw()
        data["portals"][0]["from_anchor"] = "sleep_bed"
        issues = check(data)
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.severity == "warning" and "expected 'door'" in str(i) for i in issues))


class SpatialBridgeTests(unittest.TestCase):
    def test_wall_boxes_have_the_exact_spatial_shape(self):
        import torch
        import genesis_config as cfg
        from systems.movement import spatial
        self.assertEqual(spatial.RADIUS, RADIUS)
        m = torch.zeros((2, 32))
        m[0, cfg.M_TYPE], m[0, cfg.M_HP], m[0, cfg.CX], m[0, cfg.CY], m[0, cfg.SCALE] = cfg.M_WALL, 10, 50, 40, 3
        reference = spatial.wall_boxes(m, ["wall_ref", ""])[0]
        mine = to_wall_boxes(parse_map(raw())[0])[0]
        self.assertEqual(list(mine), list(reference))
        self.assertEqual({k: type(v) for k, v in mine.items()}, {k: type(v) for k, v in reference.items()})
        for key in ("min", "max"):
            self.assertEqual((len(mine[key]), {type(v) for v in mine[key]}), (2, {float}))
        self.assertEqual(mine, {"id": "wall_house_back", "min": [6.0, 2.0], "max": [14.0, 3.0], "height": 2.4})
        json.dumps(to_wall_boxes(parse_map(raw())[0]))  # plain JSON-serialisable

    def test_wall_height_override_survives(self):
        data = raw()
        data["walls"][0]["height"] = 1.2
        self.assertEqual(to_wall_boxes(parse_map(data)[0])[0]["height"], 1.2)

    def test_converted_contract_blocks_slide_and_default_radius_matches_spatial(self):
        from systems.movement.spatial import RADIUS as spatial_radius, slide
        from world_map.validate import default_actor_radius
        self.assertEqual(default_actor_radius(), spatial_radius)
        contract = to_movement_contract(parse_map(raw())[0], spatial_radius)
        # Walking north from the spawn must stop 0.35 below the front-left wall (y=9) -> y = 9.35 at x=8.
        self.assertEqual(slide((8, 12), (8, 5), contract)[1], 9.35)
        # The doorway is open.
        self.assertEqual(slide((10.5, 12), (10.5, 5), contract), (10.5, 5))


class LoaderTests(unittest.TestCase):
    def write(self, tmp, data, name="m.json"):
        path = Path(tmp) / name
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return path

    def test_load_map_raises_with_issues_and_check_map_file_does_not(self):
        data = raw()
        data["anchors"][1]["position"] = [6.5, 5]
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, data)
            with self.assertRaises(MapValidationError) as ctx:
                load_map(path, actor_radius=RADIUS)
            self.assertTrue(any("not standable" in str(i) for i in ctx.exception.issues))
            world_map, issues = check_map_file(path, actor_radius=RADIUS)
            self.assertIsNotNone(world_map)
            self.assertTrue(errors(issues))

    def test_unreadable_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in (("bad.json", "{not json"), ("nan.json", '{"units_per_tile": NaN}'), ("list.json", "[]")):
                with self.subTest(name=name):
                    world_map, issues = check_map_file(self.write(tmp, content, name))
                    self.assertIsNone(world_map)
                    self.assertTrue(errors(issues))
            world_map, issues = check_map_file(Path(tmp) / "absent.json")
            self.assertIsNone(world_map)
            self.assertTrue(has_error(issues, "cannot read"))

    def test_loader_does_not_touch_backend_data_roots(self):
        import os
        before = os.environ.get("EDEN_DATA_ROOT")
        load_map(VILLAGE, actor_radius=RADIUS)
        self.assertEqual(os.environ.get("EDEN_DATA_ROOT"), before)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools" / "validate_map.py"), *map(str, args)],
                              capture_output=True, text=True, timeout=120)

    def test_cli_ok_and_nonzero_on_error(self):
        ok = self.run_cli(VILLAGE, INTERIOR, "--base-dir", FIXTURES)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("OK", ok.stdout)
        data = raw()
        data["walls"].append({"id": "wall_door_plug", "min": [9.5, 8], "max": [11.5, 9]})
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_cli(bad, "--base-dir", FIXTURES)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("unreachable", result.stdout)
            self.assertIn("FAILED", result.stdout)
            missing = self.run_cli(Path(tmp) / "nope.json")
            self.assertEqual(missing.returncode, 1)


if __name__ == "__main__":
    unittest.main()
