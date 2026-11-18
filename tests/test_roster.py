"""Roster loader and validator (P3.1)."""
from authored_village import MAP_FILES, load_village_maps
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from systems.movement.map_contract import clear_map_contracts, compose_group, load_from_environment, placed_group
from systems.movement.spatial import is_standable_point
from systems.roster import (anchors_from_registry, anchors_from_world_maps, load_roster, parse_roster, validate_roster,
                            validate_roster_for_world)
from world_map import load_map

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "world_data" / "rosters" / "starter_village.json"
VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"


def raw():
    return json.loads(ROSTER.read_text(encoding="utf-8"))


def errors(issues):
    return [i for i in issues if i.severity == "error"]


def has_error(issues, text):
    return any(text in str(i) for i in errors(issues))


class ParseTests(unittest.TestCase):
    def test_the_real_roster_parses_cleanly(self):
        roster, issues = load_roster(ROSTER)
        self.assertEqual(issues, [])
        self.assertEqual((roster.map_id, roster.needs_scale, [r.key for r in roster.residents]),
                         ("starter_village", 0.015, ["smith", "builder", "gatherer", "iven", "elsa", "rhea", "orrin", "nessa"]))
        smith = roster.by_key("smith")
        self.assertEqual((smith.name, smith.role, smith.stock, smith.personal["hammer"], smith.inventory["slots"]),
                         ("Brann", "smith", {"iron_ingot": 4, "wood_bundle": 4}, 1, 16))
        self.assertEqual(roster.by_key("iven").role, None)
        self.assertIsNone(roster.by_key("nobody"))

    def test_bad_structure_is_reported_not_raised(self):
        for text in ("{not json", '{"a": 1, "a": 2}', '{"needs_scale": NaN}', "[]"):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "r.json"
                path.write_text(text, encoding="utf-8")
                roster, issues = load_roster(path)
                self.assertIsNone(roster)
                self.assertTrue(errors(issues), text)
        roster, issues = load_roster(Path("does_not_exist.json"))
        self.assertTrue(has_error(issues, "cannot read"))

    def test_field_validation(self):
        mutations = {
            "needs_scale": [("needs_scale", 0), ("needs_scale", 2), ("needs_scale", "x")],
            "residents[0].key": [("key", "not an id"), ("key", 5)],
            "residents[0].sex": [("sex", 2), ("sex", True)],
            "residents[0].age": [("age", 5), ("age", "old")],
            "residents[0].role": [("role", "wizard")],
            "residents[0].archetype": [("archetype", "nope")],
            "residents[0].traits": [("traits", {"strength": 0.5}), ("traits", {"greed": 2}), ("traits", [])],
            "residents[0].anchors": [("anchors", {}), ("anchors", {"work": "x"}), ("anchors", {"spawn": 5}), ("anchors", {"fly": "x", "spawn": "y"})],
            "residents[0].stock": [("stock", {"unobtainium": 1}), ("stock", {"iron_ingot": 0}), ("stock", {"iron_ingot": 1.5})],
            "residents[0].inventory": [("inventory", {"slots": 0}), ("inventory", {"weight": -1}), ("inventory", {"extra": 1})],
            "residents[0].work_mode": [("work_mode", "idle")],
        }
        for path, cases in mutations.items():
            for key, value in cases:
                with self.subTest(path=path, value=value):
                    data = raw()
                    if path == "needs_scale":
                        data[key] = value
                    else:
                        data["residents"][0][key] = value
                    roster, issues = parse_roster(data)
                    self.assertIsNone(roster)
                    self.assertTrue(has_error(issues, path.split(".")[-1]), issues)

    def test_duplicate_keys_names_and_empty_lists(self):
        data = raw()
        data["residents"][1]["key"] = "smith"
        self.assertTrue(has_error(parse_roster(data)[1], "duplicate key"))
        data = raw()
        data["residents"][1]["name"] = "Brann"
        self.assertTrue(has_error(parse_roster(data)[1], "duplicate name"))
        data = raw()
        data["residents"] = []
        self.assertTrue(has_error(parse_roster(data)[1], "residents"))

    def test_unknown_keys_warn(self):
        data = raw()
        data["note"] = "x"
        data["residents"][0]["mood"] = "grim"
        roster, issues = parse_roster(data)
        self.assertEqual(errors(issues), [])
        self.assertEqual(sorted(i.path for i in roster.warnings), ["note", "residents[0].mood"])


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.maps = [load_map(path, base_dir=ROOT / "myassets") for path in MAP_FILES]
        cls.anchors = anchors_from_world_maps(cls.maps)
        cls.roster = load_roster(ROSTER)[0]

    def test_the_real_roster_validates_against_the_real_maps(self):
        issues = validate_roster(self.roster, self.anchors, map_ids={m.map_id for m in self.maps})
        self.assertEqual(errors(issues), [])
        self.assertEqual({i.path for i in issues}, {f"residents[{i}]" for i in range(3, 8)})  # approved interior transit warnings

    def test_unknown_anchor_and_wrong_kind(self):
        data = raw()
        data["residents"][0]["anchors"]["work"] = "smith:nope"
        roster, _ = parse_roster(data)
        self.assertTrue(has_error(validate_roster(roster, self.anchors), "unknown anchor id"))
        data = raw()
        data["residents"][0]["anchors"]["work"] = "smith:sleep"  # a sleep anchor used as work
        roster, _ = parse_roster(data)
        self.assertTrue(has_error(validate_roster(roster, self.anchors), "needs ('work',)"))
        data = raw()
        data["residents"][0]["anchors"]["spawn"] = "smith:talk"
        roster, _ = parse_roster(data)
        self.assertTrue(has_error(validate_roster(roster, self.anchors), "kind 'talk'"))

    def test_for_role_must_match_the_residents_role(self):
        data = raw()
        data["residents"][1]["anchors"]["work"] = "smith:work_forge"  # the builder at the smith's forge
        roster, _ = parse_roster(data)
        self.assertTrue(has_error(validate_roster(roster, self.anchors), "is for role 'smith'"))
        data = raw()
        data["residents"][3]["anchors"]["work"] = "village:builder_work"  # roleless resident: the label does not bind
        roster, _ = parse_roster(data)
        self.assertEqual([i for i in validate_roster(roster, self.anchors) if "role" in str(i)], [])

    def test_anchors_are_not_shared_except_spawn(self):
        data = raw()
        data["residents"][2]["anchors"]["talk"] = data["residents"][1]["anchors"]["talk"]
        roster, _ = parse_roster(data)
        self.assertTrue(has_error(validate_roster(roster, self.anchors), "also used by resident 'builder'"))
        shared = [r.anchors["spawn"] for r in self.roster.residents if r.key != "smith"]
        self.assertEqual(len(set(shared)), 1)  # four residents share the village spawn: allowed

    def test_map_id_mismatch(self):
        self.assertTrue(has_error(validate_roster(self.roster, self.anchors, map_ids={"other_map"}), "roster is for"))

    def test_roleless_resident_with_occupation_mode_warns(self):
        data = raw()
        data["residents"][3]["work_mode"] = "occupation"
        roster, _ = parse_roster(data)
        issues = validate_roster(roster, self.anchors)
        self.assertEqual(errors(issues), [])
        self.assertTrue(any("nothing to do" in str(i) for i in issues))


class RegistryValidationTests(unittest.TestCase):
    def setUp(self):
        clear_map_contracts()

    def tearDown(self):
        clear_map_contracts()

    def test_against_the_placed_maps_in_the_registry_with_standability(self):
        load_village_maps()
        roster = load_roster(ROSTER)[0]
        anchors = anchors_from_registry("starter_village")
        self.assertEqual(anchors["smith:spawn"]["position"], (660.0, 56.0))  # shifted by the interior's origin
        self.assertEqual(anchors["smith:spawn"]["map_id"], "smith_interior")
        contract = {**compose_group("starter_village"), "actor_radius": 2.4}
        self.assertEqual(errors(validate_roster_for_world(roster, "starter_village", contract)), [])
        self.assertTrue(all(is_standable_point(a["position"], contract) for a in anchors.values()
                            if a["kind"] in ("spawn", "work", "talk", "sleep")), "every roster-usable anchor is standable")

    def test_a_roster_for_an_unplaced_world_fails(self):
        roster = load_roster(ROSTER)[0]
        self.assertTrue(has_error(validate_roster_for_world(roster, "starter_village"), "unknown anchor id"))


if __name__ == "__main__":
    unittest.main()
