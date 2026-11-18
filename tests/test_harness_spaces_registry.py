"""1008 WS-D P3a: the space registry and the pure resolver ``space_at`` (harness/spaces.py), over the four authored village maps
placed at the golden world's origins. No engine is booted: the registry is derived from ``map_contract`` alone."""
import copy
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))
from harness import spaces  # noqa: E402
from harness.headless import MAP_NAMES, MAP_ORIGINS  # noqa: E402
from systems.movement import map_contract  # noqa: E402

PRIMARY = "starter_village"


def register_village(names=MAP_NAMES):
    from world_map import load_map_bytes
    for name in names:
        raw = (ROOT / "world_data" / "maps2d" / f"{name}.json").read_bytes()
        world_map = load_map_bytes(raw)
        if name == PRIMARY:
            map_contract.register_world_map(world_map, raw=raw)
        else:
            map_contract.register_world_map(world_map, origin=MAP_ORIGINS[name], raw=raw, primary=False, world=PRIMARY)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.saved = copy.copy(map_contract.MAP_CONTRACTS)
        map_contract.clear_map_contracts()
        self.engine = types.SimpleNamespace(_map_name=PRIMARY)

    def tearDown(self):
        map_contract.clear_map_contracts()
        map_contract.MAP_CONTRACTS.update(self.saved)

    def test_legacy_world_is_one_implicit_overworld(self):
        self.assertEqual(spaces.space_table(self.engine), [])
        self.assertEqual(spaces.space_at(self.engine, 100.0, 100.0), 0)
        self.assertIsNone(spaces.space_of_map(self.engine, "smith_interior"))
        self.assertIsNone(spaces.map_of_space(self.engine, 0))

    def test_ids_follow_registration_order_primary_first(self):
        register_village()
        table = spaces.space_table(self.engine)
        self.assertEqual([r["space"] for r in table], [0, 1, 2, 3])
        self.assertEqual([r["map_id"] for r in table], list(MAP_NAMES))
        self.assertEqual([r["kind"] for r in table], ["overworld", "interior", "interior", "interior"])
        self.assertEqual(spaces.space_of_map(self.engine, "village_lodge_interior"), 2)
        self.assertEqual(spaces.map_of_space(self.engine, 3), "west_cottage_interior")
        self.assertIsNone(spaces.map_of_space(self.engine, 4))
        self.assertIsNone(spaces.map_of_space(self.engine, -1))

    def test_ids_are_stable_for_the_same_registration_order(self):
        register_village()
        first = spaces.space_table(self.engine)
        map_contract.clear_map_contracts()
        register_village()
        self.assertEqual(spaces.space_table(self.engine), first)

    def test_a_different_registration_order_changes_the_ids(self):
        register_village((PRIMARY, "west_cottage_interior", "smith_interior"))
        self.assertEqual(spaces.space_of_map(self.engine, "west_cottage_interior"), 1)
        self.assertEqual(spaces.space_of_map(self.engine, "smith_interior"), 2)

    def test_table_rows_carry_layout_bounds_origin_and_file_identity(self):
        register_village()
        for row in spaces.space_table(self.engine):
            entry = map_contract.get_map_contract(row["map_id"])
            self.assertEqual(row["bounds"], entry["bounds"])
            self.assertEqual(row["origin"], entry["origin"])
            self.assertEqual(row["sha256"], entry["info"]["sha256"])
            self.assertEqual(row["revision"], entry["info"]["revision"])
        self.assertEqual(spaces.space_table(self.engine)[1]["origin"], [float(v) for v in MAP_ORIGINS["smith_interior"]])

    def test_space_at_the_corners_the_centres_and_just_outside_of_every_map(self):
        register_village()
        for row in spaces.space_table(self.engine):
            x0, y0, x1, y1 = row["bounds"]
            inside = [(x0, y0), (x1, y1), (x0, y1), (x1, y0), ((x0 + x1) / 2, (y0 + y1) / 2)]
            for x, y in inside:
                self.assertEqual(spaces.space_at(self.engine, x, y), row["space"], (row["map_id"], x, y))
            if row["space"] != 0:                      # the overworld is the fallback, so only interiors have an outside edge
                for x, y in [(x0 - 0.01, y0), (x1 + 0.01, y1), (x0, y0 - 0.01), (x1, y1 + 0.01)]:
                    self.assertEqual(spaces.space_at(self.engine, x, y), 0, (row["map_id"], x, y))

    def test_a_point_in_no_map_is_the_overworld(self):
        register_village()
        for point in [(-5000.0, -5000.0), (1e7, 1e7), (500.0, 2000.0)]:
            self.assertEqual(spaces.space_at(self.engine, *point), 0)

    def test_the_interior_rectangles_are_disjoint_and_away_from_the_overworld(self):
        register_village()
        table = spaces.space_table(self.engine)
        for i, a in enumerate(table):
            for b in table[i + 1:]:
                disjoint = a["bounds"][2] < b["bounds"][0] or b["bounds"][2] < a["bounds"][0] or \
                    a["bounds"][3] < b["bounds"][1] or b["bounds"][3] < a["bounds"][1]
                self.assertTrue(disjoint, (a["map_id"], b["map_id"]))

    def test_resolve_with_precomputed_rectangles_equals_space_at(self):
        register_village()
        rects = spaces.rectangles(self.engine)
        self.assertEqual([r[0] for r in rects], [1, 2, 3])
        for x, y in [(650.0, 20.0), (700.0, 430.0), (1000.0, 200.0), (10.0, 10.0), (-1.0, -1.0)]:
            self.assertEqual(spaces.resolve(rects, x, y), spaces.space_at(self.engine, x, y))

    def test_overlapping_rectangles_resolve_to_the_lowest_id(self):
        rects = [(1, 0.0, 0.0, 10.0, 10.0), (2, 5.0, 5.0, 15.0, 15.0)]
        self.assertEqual(spaces.resolve(rects, 7.0, 7.0), 1)
        self.assertEqual(spaces.resolve(rects, 12.0, 12.0), 2)
        self.assertEqual(spaces.resolve(rects, 10.0, 10.0), 1)

    def test_flag_dependency(self):
        env = {"EDEN_SPACES": "1"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("EDEN_PERCEPTION_BOUNDED", None)
            with self.assertRaises(spaces.SpaceConfigError) as caught:
                spaces.check_flags()
            self.assertIn("EDEN_PERCEPTION_BOUNDED=1", str(caught.exception))
            os.environ["EDEN_PERCEPTION_BOUNDED"] = "1"
            spaces.check_flags()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDEN_SPACES", None)
            os.environ.pop("EDEN_PERCEPTION_BOUNDED", None)
            spaces.check_flags()                       # flag off: never raises


if __name__ == "__main__":
    unittest.main()
