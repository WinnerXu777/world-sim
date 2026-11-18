"""Map format 0.2-draft additions: actor_radius, interact_radius, owner_entity, id rules, interior seal."""
import unittest

from test_world_map import (FIXTURES, INTERIOR, RADIUS, check, check_map_file, errors, has_error, load_map, parse_map,
                            raw, to_movement_contract, to_wall_boxes, validate_map)
from world_map import to_anchor_list


class VersionAndNewFieldTests(unittest.TestCase):
    def test_old_0_1_files_still_load_with_a_note(self):
        data = raw()
        data["format_version"] = "0.1-draft"
        for key in ("actor_radius", "coordinate_system"):
            data.pop(key)
        for entity in data["entities"]:
            entity.pop("interact_radius", None)
        world_map, issues = parse_map(data)
        self.assertEqual(errors(issues), [])
        self.assertEqual(world_map.format_version, "0.1-draft")
        self.assertIsNone(world_map.actor_radius)
        self.assertTrue(any(i.path == "format_version" and i.severity == "warning" for i in issues))
        self.assertEqual(errors(check(data)), [])

    def test_unknown_versions_are_rejected(self):
        for version in ("0.3-draft", "0.2", None, 0.2):
            data = raw()
            data["format_version"] = version
            self.assertIsNone(parse_map(data)[0], version)

    def test_actor_radius_parsing(self):
        self.assertEqual(parse_map(raw())[0].actor_radius, 0.5)
        for bad in (0, -1, "1", True, float("inf"), float("nan"), None):
            with self.subTest(bad=bad):
                data = raw()
                data["actor_radius"] = bad
                self.assertTrue(has_error(parse_map(data)[1], "actor_radius"))
        data = raw()
        del data["actor_radius"]
        world_map, issues = parse_map(data)
        self.assertIsNone(world_map.actor_radius)
        self.assertTrue(any(i.path == "actor_radius" and i.severity == "warning" for i in issues))

    def test_validator_uses_the_file_radius_unless_overridden(self):
        data = raw()
        data["actor_radius"] = 0.7
        data["anchors"][1]["position"] = [7.6, 5]  # wall max x = 7: standable only for radius <= 0.6
        world_map, _ = parse_map(data)
        self.assertTrue(has_error(validate_map(world_map, FIXTURES), "not standable"))
        self.assertEqual(errors(validate_map(world_map, FIXTURES, actor_radius=0.35)), [])  # override wins
        data["actor_radius"] = 0.35
        world_map, _ = parse_map(data)
        self.assertEqual(errors(validate_map(world_map, FIXTURES)), [])
        self.assertTrue(has_error(validate_map(world_map, FIXTURES, actor_radius=0.7), "not standable"))

    def test_file_radius_drives_reachability(self):
        data = raw()
        data["walls"][3]["max"] = [10.2, 9]  # doorway gap 10.2..11.5 = 1.3 wide
        data["actor_radius"] = 0.5
        self.assertEqual([i for i in errors(check(data, radius=None)) if "unreachable" in str(i)], [])
        data["actor_radius"] = 0.7  # needs 1.4
        self.assertTrue(has_error(check(data, radius=None), "unreachable"))

    def test_movement_contract_exposes_the_radius(self):
        world_map = parse_map(raw())[0]
        self.assertEqual(to_movement_contract(world_map)["actor_radius"], 0.5)
        self.assertEqual(to_movement_contract(world_map, 0.9)["actor_radius"], 0.9)
        data = raw()
        del data["actor_radius"]
        self.assertEqual(to_movement_contract(parse_map(data)[0])["actor_radius"], RADIUS)

    def test_interact_radius(self):
        world_map = parse_map(raw())[0]
        self.assertEqual({e.id: e.interact_radius for e in world_map.entities},
                         {"forge_01": 3.0, "chest_01": None, "tree_deco_01": None})
        for bad in (0, -2, "3", True, float("nan"), None):
            with self.subTest(bad=bad):
                data = raw()
                data["entities"][1]["interact_radius"] = bad
                self.assertTrue(has_error(parse_map(data)[1], "entities[1].interact_radius"))

    def test_coordinate_system_must_match_when_present(self):
        data = raw()
        data["coordinate_system"] = "bottom_left"
        self.assertTrue(has_error(parse_map(data)[1], "coordinate_system"))
        del data["coordinate_system"]
        self.assertEqual(errors(parse_map(data)[1]), [])

    def test_pixels_per_unit_is_derived_and_not_stored(self):
        data = raw()
        data["pixels_per_unit"] = 24.0  # 48 / 2.0: matches, but still should not be stored
        issues = parse_map(data)[1]
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.path == "pixels_per_unit" and i.severity == "warning" for i in issues))
        data["pixels_per_unit"] = 6.0
        self.assertTrue(has_error(parse_map(data)[1], "pixels_per_unit"))

    def test_map_kind(self):
        self.assertEqual(parse_map(raw())[0].map_kind, "exterior")
        self.assertEqual(parse_map(raw(INTERIOR))[0].map_kind, "interior")
        data = raw()
        data["map_kind"] = "dungeon"
        self.assertTrue(has_error(parse_map(data)[1], "map_kind"))

    def test_palette_keys_must_be_positive_integer_strings(self):
        for key in ("0", "-1", "a", "1.5", ""):
            with self.subTest(key=key):
                data = raw()
                data["layers"][0]["palette"][key] = "sprites/grass.png"
                self.assertTrue(has_error(parse_map(data)[1], "palette"))


class RevisionTests(unittest.TestCase):
    def test_0_2_requires_a_non_negative_integer(self):
        for good in (0, 1, 12345):
            data = raw()
            data["revision"] = good
            self.assertEqual(parse_map(data)[0].revision, good)
        for bad in ("3", "v3", "", -1, 1.0, 2.5, True, False, None, [1]):
            with self.subTest(bad=bad):
                data = raw()
                data["revision"] = bad
                world_map, issues = parse_map(data)
                self.assertIsNone(world_map)
                self.assertTrue(has_error(issues, "revision"))

    def test_0_1_may_still_use_a_string_with_a_warning(self):
        data = raw()
        data["format_version"] = "0.1-draft"
        data["revision"] = "legacy-7"
        world_map, issues = parse_map(data)
        self.assertEqual(world_map.revision, "legacy-7")
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.path == "revision" and i.severity == "warning" for i in issues))
        data["revision"] = 4
        self.assertEqual(parse_map(data)[0].revision, 4)
        for bad in (True, False, -1, 1.5, ""):
            data["revision"] = bad
            self.assertIsNone(parse_map(data)[0], bad)


class AnchorForRoleTests(unittest.TestCase):
    def with_role(self, role):
        data = raw()
        data["anchors"][2]["for_role"] = role  # work_forge
        return data

    def test_known_roles_are_exposed_on_the_anchor_and_the_export(self):
        for role in ("smith", "builder", "gatherer"):
            data = self.with_role(role)
            world_map, issues = parse_map(data)
            self.assertEqual(errors(issues), [])
            self.assertFalse(any(i.path == "anchors[2].for_role" for i in issues))
            self.assertEqual(world_map.anchors[2].for_role, role)
            self.assertEqual(to_anchor_list(world_map)[2], {"id": "work_forge", "kind": "work", "position": [8.5, 4.8], "for_role": role})
        world_map = parse_map(raw())[0]
        self.assertIsNone(world_map.anchors[2].for_role)
        self.assertNotIn("for_role", to_anchor_list(world_map)[2])

    def test_unknown_role_warns_but_loads(self):
        world_map, issues = parse_map(self.with_role("wizard"))
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.path == "anchors[2].for_role" and i.severity == "warning" for i in issues))
        self.assertEqual(world_map.anchors[2].for_role, "wizard")

    def test_invalid_roles_are_errors(self):
        for bad in ("", "  ", 5, None, True, ["smith"], "e_000042"):
            with self.subTest(bad=bad):
                self.assertTrue(has_error(parse_map(self.with_role(bad))[1], "anchors[2].for_role"))

    def test_role_text_is_not_checked_against_resident_or_entity_ids(self):
        world_map, issues = parse_map(self.with_role("forge_01"))  # an entity id used as a role: just an unknown role
        self.assertEqual(errors(issues), [])


class GeneratedIdTests(unittest.TestCase):
    def test_ids_matching_the_generated_entity_pattern_are_rejected(self):
        for collection in ("walls", "entities", "anchors", "portals"):
            with self.subTest(collection=collection):
                data = raw()
                data[collection][0]["id"] = "e_000123"
                self.assertTrue(has_error(parse_map(data)[1], "backend-generated"))

    def test_near_misses_are_allowed(self):
        data = raw()
        for ok in ("e_12345", "e_1234567", "E_000123", "xe_000123", "e_00012a"):
            data["walls"][0]["id"] = ok
            self.assertEqual([i for i in parse_map(data)[1] if "backend-generated" in str(i)], [], ok)


class OwnerEntityAndAccessTests(unittest.TestCase):
    def test_owner_entity_must_reference_an_entity(self):
        data = raw()
        data["walls"][0]["owner_entity"] = "forge_01"
        self.assertEqual(errors(check(data)), [])
        self.assertEqual(parse_map(data)[0].walls[0].owner_entity, "forge_01")
        data["walls"][0]["owner_entity"] = "nope"
        self.assertTrue(has_error(parse_map(data)[1], "walls[0].owner_entity"))
        data["walls"][0]["owner_entity"] = 5
        self.assertTrue(has_error(parse_map(data)[1], "walls[0].owner_entity"))

    def test_owner_entity_does_not_change_the_box(self):
        data = raw()
        before = to_wall_boxes(parse_map(data)[0])
        data["walls"][0]["owner_entity"] = "forge_01"
        self.assertEqual(to_wall_boxes(parse_map(data)[0]), before)

    def test_blocking_entity_without_access_anchor_warns(self):
        data = raw()
        data["walls"][0]["owner_entity"] = "forge_01"
        self.assertFalse(any("no work or talk anchor" in str(i) for i in check(data)))  # work_forge is outside the wall
        data["anchors"] = [a for a in data["anchors"] if a["kind"] != "work"]
        issues = check(data)
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.severity == "warning" and "no work or talk anchor" in str(i) for i in issues))

    def test_access_anchor_must_be_within_interact_radius_when_declared(self):
        data = raw()
        data["walls"][0]["owner_entity"] = "forge_01"  # forge (8.5, 3.6); work anchor (8.5, 4.8) is 1.2 away
        data["entities"][0]["interact_radius"] = 1.0
        self.assertTrue(any("no work or talk anchor" in str(i) for i in check(data)))
        data["entities"][0]["interact_radius"] = 1.5
        self.assertFalse(any("no work or talk anchor" in str(i) for i in check(data)))

    def test_non_interactive_owner_is_not_checked(self):
        data = raw()
        data["walls"][0]["owner_entity"] = "tree_deco_01"
        data["anchors"] = [a for a in data["anchors"] if a["kind"] != "work"]
        self.assertFalse(any("no work or talk anchor" in str(i) for i in check(data)))


class InteriorSealTests(unittest.TestCase):
    def test_sealed_interior_has_no_seal_warning(self):
        issues = check(raw(INTERIOR))
        self.assertEqual(errors(issues), [])
        self.assertFalse(any("not sealed" in str(i) for i in issues))

    def test_open_interior_warns_but_exterior_does_not(self):
        data = raw(INTERIOR)
        data["walls"] = [w for w in data["walls"] if w["id"] != "interior_wall_e"]
        issues = check(data)
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.severity == "warning" and "not sealed" in str(i) for i in issues))
        data["map_kind"] = "exterior"
        self.assertFalse(any("not sealed" in str(i) for i in check(data)))

    def test_thin_edge_wall_still_seals(self):
        data = raw(INTERIOR)
        for wall in data["walls"]:
            if wall["id"] == "interior_wall_w":
                wall["max"] = [0.1, 7.5]
        self.assertFalse(any("not sealed" in str(i) for i in check(data)))


class ExampleSmithTests(unittest.TestCase):
    """Mirrors the example in myassets/MAP_CONTRACT_REPLY.md. The values live only in this fixture, not in code."""
    PATH = FIXTURES / "example_smith.json"

    def test_validates_cleanly_with_the_file_radius(self):
        world_map, issues = check_map_file(self.PATH, base_dir=FIXTURES)
        self.assertEqual(issues, [])
        self.assertEqual((world_map.map_id, world_map.revision, world_map.units_per_tile, world_map.actor_radius),
                         ("example_smith", 0, 8.0, 2.4))
        self.assertEqual(world_map.bounds, [0.0, 0.0, 48.0, 48.0])
        self.assertEqual(world_map.walls[0].owner_entity, "example_smith:forge")

    def test_geometry_matches_the_documented_example(self):
        world_map = load_map(self.PATH, base_dir=FIXTURES)
        self.assertEqual(to_wall_boxes(world_map),
                         [{"id": "example_smith:wall_forge", "min": [16.0, 8.0], "max": [32.0, 16.0], "height": 2.4}])
        self.assertEqual({a.id: a.position for a in world_map.anchors},
                         {"example_smith:spawn": (8.0, 32.0), "example_smith:work": (24.0, 21.0),
                          "example_smith:talk": (24.0, 29.0)})
        contract = to_movement_contract(world_map)
        self.assertEqual(contract["actor_radius"], 2.4)
        from systems.movement.spatial import slide
        self.assertAlmostEqual(slide((24, 21), (24, 0), contract)[1], 18.4)  # stops 2.4 below the forge box

    def test_anchors_sit_outside_the_inflated_forge_box(self):
        world_map = load_map(self.PATH, base_dir=FIXTURES)
        wall = world_map.walls[0]
        for anchor in world_map.anchors:
            x, y = anchor.position
            inside = wall.min[0] - 2.4 < x < wall.max[0] + 2.4 and wall.min[1] - 2.4 < y < wall.max[1] + 2.4
            self.assertFalse(inside, anchor.id)

    def test_a_blocked_work_anchor_is_an_error_and_losing_it_only_warns(self):
        data = raw(self.PATH)
        data["anchors"][1]["position"] = [24, 17]  # inside the inflated box (wall max y 16 + 2.4)
        self.assertTrue(has_error(check(data, radius=None), "not standable"))
        data = raw(self.PATH)
        data["anchors"] = [a for a in data["anchors"] if a["kind"] == "spawn"]
        issues = check(data, radius=None)
        self.assertEqual(errors(issues), [])
        self.assertTrue(any("no work or talk anchor" in str(i) for i in issues))

    def test_radius_changes_standability(self):
        data = raw(self.PATH)
        data["actor_radius"] = 3.2  # 16 + 3.2 = 19.2 < 21
        self.assertEqual(errors(check(data, radius=None)), [])
        data["actor_radius"] = 5.5  # 16 + 5.5 = 21.5 > 21
        self.assertTrue(has_error(check(data, radius=None), "not standable"))


class ClearanceWarningTests(unittest.TestCase):
    def near_wall(self, x):
        data = raw()
        data["anchors"][3]["position"] = [x, 5]  # sleep_bed; wall_house_left max x = 7, file radius 0.5
        return check(data, radius=None)

    def test_anchor_close_to_a_wall_warns_but_is_not_an_error(self):
        issues = self.near_wall(8.0)  # standable (>= 7.5) but < radius + 1 = 8.5
        self.assertEqual(errors(issues), [])
        self.assertTrue(any(i.severity == "warning" and "radius + 1" in str(i) and i.path == "anchors[3]" for i in issues))

    def test_anchor_clear_of_the_margin_has_no_warning(self):
        self.assertFalse(any("radius + 1" in str(i) and i.path == "anchors[3]" for i in self.near_wall(8.6)))

    def test_embedded_anchor_keeps_the_error_and_no_extra_warning(self):
        issues = self.near_wall(7.4)
        self.assertTrue(has_error(issues, "not standable"))
        self.assertFalse(any("radius + 1" in str(i) and i.path == "anchors[3]" for i in issues))

    def test_example_smith_has_no_clearance_warnings(self):
        issues = check_map_file(FIXTURES / "example_smith.json", base_dir=FIXTURES)[1]
        self.assertEqual(issues, [])


def gap_data(gap, radius=2.4):
    half = gap / 2
    return {"format_version": "0.2-draft", "map_id": "gap_test", "revision": 0, "tile_size_px": 48, "units_per_tile": 8,
            "actor_radius": radius, "size_tiles": [10, 6],
            "walls": [{"id": "wall_top", "min": [40, 0], "max": [42, 24 - half]},
                      {"id": "wall_bottom", "min": [40, 24 + half], "max": [42, 48]}],
            "anchors": [{"id": "west", "kind": "spawn", "position": [20, 24]}, {"id": "east", "kind": "work", "position": [62, 24]}]}


class MarginalGapTests(unittest.TestCase):
    """r = 2.4, 8 units per tile: a gap g leaves a centre band of g - 4.8; below 2r + 1 = 5.8 it is marginal."""

    def issues(self, gap):
        return check(gap_data(gap), base_dir=None, radius=None)

    def marginal(self, issues):
        return [i for i in issues if i.severity == "warning" and "passes a gap" in str(i)]

    def test_comfortable_gaps_do_not_warn(self):
        for gap in (8.0, 10.0, 16.0, 5.8):  # 5.8 = 2r + 1 exactly
            with self.subTest(gap=gap):
                issues = self.issues(gap)
                self.assertEqual(errors(issues), [])
                self.assertEqual(self.marginal(issues), [])

    def test_marginal_gaps_warn_and_stay_passable(self):
        for gap in (5.0, 5.79, 4.9):
            with self.subTest(gap=gap):
                issues = self.issues(gap)
                self.assertEqual(errors(issues), [])
                self.assertEqual([i.path for i in self.marginal(issues)], ["anchors[1]"])

    def test_blocked_gaps_are_an_error_not_a_marginal_warning(self):
        for gap in (4.79, 4.0, 2.0):
            with self.subTest(gap=gap):
                issues = self.issues(gap)
                self.assertTrue(has_error(issues, "unreachable"))
                self.assertEqual(self.marginal(issues), [])

    def test_marginal_boundary_scales_with_the_radius(self):
        issues = check(gap_data(2.0, radius=0.35), base_dir=None, radius=None)  # 2r = 0.7, 2r + 1 = 1.7
        self.assertEqual(self.marginal(issues), [])
        issues = check(gap_data(1.2, radius=0.35), base_dir=None, radius=None)
        self.assertEqual(len(self.marginal(issues)), 1)

    def test_a_marginal_side_route_does_not_warn_when_a_wide_route_exists(self):
        data = gap_data(8.0)
        data["walls"].append({"id": "extra", "min": [10, 10], "max": [11, 12]})
        self.assertEqual(self.marginal(check(data, base_dir=None, radius=None)), [])


if __name__ == "__main__":
    unittest.main()
