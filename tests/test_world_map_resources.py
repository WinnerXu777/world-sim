"""G-005 step 1 (data only): the optional ``resource`` object on map entities and the chunk-document keys (chunk, data, pinned_map)."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from test_world_map import FIXTURES, check, errors, raw  # noqa: E402
from world_map import check_map_bytes, check_map_file, parse_map  # noqa: E402
from world_map import resources as wr  # noqa: E402

# the four maps that existed before G-005 declared nothing; the S-1 maps (family_farm and its interiors) declare resources on purpose
MAPS_DIR = ROOT / "world_data" / "maps2d"
REAL_MAPS = [MAPS_DIR / f"{name}.json" for name in ("starter_village", "smith_interior", "village_lodge_interior", "west_cottage_interior")]
S1_MAPS = [MAPS_DIR / f"{name}.json" for name in ("family_farm", "family_home_interior", "neighbour_home_interior")]


def entity(**over):
    base = {"id": "bush_01", "kind": "berry_bush", "interactive": True, "position": [3.0, 2.0]}
    base.update(over)
    return base


def with_entity(item):
    data = raw()
    data["entities"].append(item)
    return data


def messages(issues):
    return [f"{i.path}: {i.message}" for i in errors(issues)]


class ResourceKeyTests(unittest.TestCase):
    def test_valid_flat_keys_are_parsed_onto_the_entity_and_the_file_is_otherwise_unchanged(self):
        keys = {"resource": "berries", "amount": 24, "cap": 40, "regrow": 0.02, "radius": 6, "item": "berries", "tiles": 3}
        world_map, issues = parse_map(with_entity(entity(**keys)))
        self.assertEqual(errors(issues), [])
        found = next(e for e in world_map.entities if e.id == "bush_01")
        self.assertEqual(found.resource, {"name": "berries", "amount": 24.0, "cap": 40.0, "regrow": 0.02, "radius": 6.0, "item": "berries", "tiles": 3})
        self.assertTrue(all(e.resource is None for e in world_map.entities if e.id != "bush_01"))
        self.assertEqual(errors(check(with_entity(entity(**keys)))), [])

    def test_every_resource_accepts_each_of_its_kinds_and_the_stock_and_shelter_keys_their_kinds(self):
        for name, kinds in wr.RESOURCE_KINDS.items():
            for kind in kinds:
                with self.subTest(resource=name, kind=kind):
                    extra = {"water": 30} if name == "crops" else {}
                    self.assertEqual(errors(parse_map(with_entity(entity(kind=kind, resource=name, **extra)))[1]), [])
        for kind in wr.STORAGE_KINDS:
            self.assertEqual(errors(parse_map(with_entity(entity(kind=kind, stock={"rations": 2})))[1]), [])
        for kind in wr.SHELTER_KINDS:
            self.assertEqual(errors(parse_map(with_entity(entity(kind=kind, capacity=3)))[1]), [])
        self.assertEqual(wr.KIND_RESOURCE["well"], "water")
        self.assertEqual(wr.KIND_RESOURCE["berry_bush"], "berries")
        self.assertEqual(wr.KIND_RESOURCE["ore_vein"], "ore")                      # generator kinds are in the table

    def test_the_resource_must_fit_the_kind_and_the_entity_must_be_interactive(self):
        self.assertTrue(any("does not fit entity kind" in m for m in messages(parse_map(with_entity(entity(kind="bed", resource="water")))[1])))
        decoration = entity(interactive=False, resource="berries")
        self.assertTrue(any("need an interactive entity" in m for m in messages(parse_map(with_entity(decoration))[1])))

    def test_wrong_values_are_errors_with_paths(self):
        cases = [
            ({"resource": "nope"}, "resource"),
            ({"resource": 3}, "resource"),
            ({"resource": "berries", "amount": -1}, "amount"),
            ({"resource": "berries", "amount": 50, "cap": 40}, "exceeds cap"),
            ({"resource": "berries", "cap": 0}, "cap"),
            ({"resource": "berries", "amount": 2_000_000}, "amount"),
            ({"resource": "berries", "regrow": 11}, "regrow"),
            ({"resource": "berries", "regrow": float("nan")}, "regrow"),
            ({"resource": "berries", "radius": 0}, "radius"),
            ({"resource": "berries", "radius": 257}, "radius"),
            ({"resource": "berries", "item": "Berries!"}, "item"),
            ({"resource": "berries", "amount": True}, "amount"),
            ({"resource": "berries", "tiles": -1}, "tiles"),
            ({"resource": "berries", "tiles": 1.5}, "tiles"),
            ({"resource": "berries", "water": 10}, "only a crops entity"),
            ({"amount": 5}, "needs a \"resource\""),
            ({"stock": {"rations": 1}}, "only for storage kinds"),
            ({"capacity": 2}, "only for shelter kinds"),
        ]
        for keys, needle in cases:
            with self.subTest(keys=keys):
                found = messages(parse_map(with_entity(entity(**keys)))[1])
                self.assertTrue(any(needle in m and "entities[3]" in m for m in found), found)

    def test_stock_and_capacity_rules(self):
        crate = entity(id="crate_01", kind="crate")
        for stock in ({}, {"rations": 0}, {"rations": 1.5}, {"Rations": 1}, {"rations": 10001}, [], None):
            with self.subTest(stock=stock):
                self.assertTrue(messages(parse_map(with_entity({**crate, "stock": stock}))[1]))
        for capacity in (0, 33, 2.5, True, "2"):
            with self.subTest(capacity=capacity):
                self.assertTrue(messages(parse_map(with_entity(entity(kind="bed", capacity=capacity)))[1]))

    def test_a_bad_declaration_never_hides_a_second_error_in_the_same_file(self):
        data = with_entity(entity(resource="berries", cap=0))
        data["entities"].append({"id": "x1", "kind": "k", "interactive": "yes", "position": [1, 1]})
        found = messages(parse_map(data)[1])
        self.assertTrue(any("cap" in m for m in found) and any("interactive" in m for m in found), found)

    def test_an_entity_without_any_of_the_keys_is_untouched(self):
        world_map, _ = parse_map(raw())
        self.assertTrue(all(e.resource is None for e in world_map.entities))


class ExistingMapsUnchangedTests(unittest.TestCase):
    def test_the_real_maps_declare_no_resource_and_parse_with_the_same_verdict(self):
        self.assertGreaterEqual(len(REAL_MAPS), 4)
        for path in REAL_MAPS:
            with self.subTest(path=path.name):
                world_map, issues = check_map_file(path, ROOT / "myassets", None)
                self.assertIsNotNone(world_map)
                self.assertEqual(errors(issues), [])
                self.assertTrue(all(e.resource is None for e in world_map.entities))
                self.assertEqual(world_map.extras, {})

    def test_the_s1_maps_parse_clean_and_declare_resources(self):
        declared = 0
        for path in S1_MAPS:
            with self.subTest(path=path.name):
                world_map, issues = check_map_file(path, ROOT / "myassets", None)
                self.assertIsNotNone(world_map)
                self.assertEqual(errors(issues), [])
                declared += sum(e.resource is not None for e in world_map.entities)
        self.assertGreater(declared, 0)

    def test_the_format_version_is_still_0_2_draft(self):
        from world_map.schema import ACCEPTED_FORMAT_VERSIONS, FORMAT_VERSION
        self.assertEqual((FORMAT_VERSION, ACCEPTED_FORMAT_VERSIONS), ("0.2-draft", ("0.1-draft", "0.2-draft")))


class ChunkKeyTests(unittest.TestCase):
    def chunk_bytes(self, cx=3, cy=2, pinned=None):
        from systems.worldgen.generate import generate_chunk
        chunk = generate_chunk(1008, cx, cy, pinned)
        return chunk.payload, chunk.document

    def test_a_generated_chunk_no_longer_warns_and_exposes_its_blocks(self):
        payload, doc = self.chunk_bytes()
        world_map, issues = check_map_bytes(payload, ROOT / "myassets")
        self.assertEqual(errors(issues), [])
        self.assertFalse(any("unknown top-level key" in i.message for i in issues))
        self.assertEqual(world_map.extras["chunk"]["cx"], 3)
        self.assertEqual(world_map.extras["chunk"]["cy"], 2)
        self.assertIn("biome", world_map.extras["data"])
        self.assertNotIn("pinned_map", world_map.extras)

    def test_a_pointer_chunk_parses_and_names_its_map(self):
        from systems.worldgen.pinned import PinnedArea, PinnedSet
        payload, _ = self.chunk_bytes(0, 0, PinnedSet([PinnedArea("big", -64, -64, 256, 256)]))
        world_map, issues = check_map_bytes(payload, ROOT / "myassets")
        self.assertEqual(errors(issues), [])
        self.assertEqual(world_map.extras["pinned_map"], "big")

    def test_structure_errors(self):
        base = raw()
        cases = [
            ({"chunk": {"cx": 1}}, "chunk"),
            ({"chunk": {"cx": 1.5, "cy": 2}}, "chunk"),
            ({"chunk": [1, 2]}, "chunk"),
            ({"data": [1]}, "data"),
            ({"pinned_map": 7}, "pinned_map"),
            ({"pinned_map": "e_000001"}, "pinned_map"),
        ]
        for extra, needle in cases:
            with self.subTest(extra=extra):
                data = copy.deepcopy(base)
                data.update(extra)
                self.assertTrue(any(needle in m for m in messages(parse_map(data)[1])), extra)

    def test_a_pointer_document_must_be_empty(self):
        data = raw()
        data["pinned_map"] = "starter_village"
        found = messages(parse_map(data)[1])
        self.assertTrue(any("pointer document" in m for m in found), found)
        empty = copy.deepcopy(data)
        for key in ("walls", "anchors", "entities", "portals"):
            empty[key] = []
        for layer in empty["layers"]:
            layer["tiles"] = [[0] * len(row) for row in layer["tiles"]]
        self.assertEqual(errors(parse_map(empty)[1]), [])

    def test_other_unknown_top_level_keys_still_warn(self):
        data = raw()
        data["mystery"] = 1
        self.assertTrue(any(i.path == "mystery" and i.severity == "warning" for i in parse_map(data)[1]))


class RegistryTests(unittest.TestCase):
    def test_register_world_map_carries_the_resource_object_only_where_declared(self):
        from systems.movement import map_contract as mc
        data = with_entity(entity(resource="berries", amount=5))
        world_map, issues = parse_map(data)
        self.assertEqual(errors(issues), [])
        name = "g005_resource_registry_test"
        try:
            mc.register_world_map(world_map, name=name)
            entities = {e["id"]: e for e in mc.get_map_contract(name)["entities"]}
            self.assertEqual(entities["bush_01"]["resource"], {"name": "berries", "amount": 5.0})
            self.assertTrue(all("resource" not in e for i, e in entities.items() if i != "bush_01"))
            copies = mc.copy_entities(mc.get_map_contract(name))
            next(e for e in copies if e["id"] == "bush_01")["resource"]["amount"] = 99.0
            self.assertEqual({e["id"]: e for e in mc.get_map_contract(name)["entities"]}["bush_01"]["resource"]["amount"], 5.0)
        finally:
            mc.unregister_map_contract(name)


if __name__ == "__main__":
    unittest.main()
