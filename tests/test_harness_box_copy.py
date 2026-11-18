"""copy_boxes keeps its contract (fresh, independent, equal to deepcopy) while no longer paying for deepcopy."""
import copy
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from authored_village import load_village_maps  # noqa: E402
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from systems.movement import map_contract as mc  # noqa: E402


def random_box(rng):
    box = {"id": f"b{rng.randrange(99)}", "min": [rng.uniform(-9, 9) for _ in range(3)],
           "max": [rng.uniform(-9, 9) for _ in range(3)], "height": rng.uniform(0, 5)}
    if rng.random() < 0.5:
        box["tags"] = ["wall", "solid"]
    if rng.random() < 0.3:
        box["meta"] = {"nested": [1, 2, {"deep": [3]}], "flag": True, "none": None}
    if rng.random() < 0.2:
        box["tuple"] = (1, 2)
    return box


class CopyBoxesTests(unittest.TestCase):
    def test_equal_to_deepcopy_and_fully_independent_for_random_boxes(self):
        rng = random.Random(1008)
        for _ in range(200):
            override = {"boxes": [random_box(rng) for _ in range(rng.randrange(0, 8))]}
            snapshot = copy.deepcopy(override)
            got = mc.copy_boxes(override)
            self.assertEqual(got, snapshot["boxes"])
            self.assertEqual(got, copy.deepcopy(override["boxes"]))
            for box in got:                                   # mutate every mutable thing in the copy
                for value in box.values():
                    if isinstance(value, list):
                        value.append(99.0)
                        value[0] = -1
                    elif isinstance(value, dict):
                        value["x"] = 1
                        for inner in value.values():
                            if isinstance(inner, list):
                                inner.append(7)
                box["id"] = "changed"
            self.assertEqual(override, snapshot, "mutating the copy changed the source")
            again = mc.copy_boxes(override)
            self.assertEqual(again, snapshot["boxes"])
            for a, b in zip(got, again):
                self.assertIsNot(a, b)

    def test_scalar_lists_are_new_lists_and_nested_values_are_not_shared(self):
        src = {"boxes": [{"id": "a", "min": [0, 0, 0], "max": [1, 1, 1], "height": 1, "meta": {"k": [1]}}]}
        out = mc.copy_boxes(src)
        self.assertIsNot(out[0]["min"], src["boxes"][0]["min"])
        self.assertIsNot(out[0]["meta"], src["boxes"][0]["meta"])
        self.assertIsNot(out[0]["meta"]["k"], src["boxes"][0]["meta"]["k"])

    def test_empty_and_non_dict_boxes(self):
        self.assertEqual(mc.copy_boxes({"boxes": []}), [])
        odd = {"boxes": [[1, [2]]]}
        out = mc.copy_boxes(odd)
        self.assertEqual(out, odd["boxes"])
        self.assertIsNot(out[0][1], odd["boxes"][0][1])


class RealMapTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()

    def test_every_registered_map_copies_exactly_and_independently(self):
        checked = 0
        for name, entry in list(mc.MAP_CONTRACTS.items()):
            snapshot = copy.deepcopy(entry["boxes"])
            got = mc.copy_boxes(entry)
            self.assertEqual(got, snapshot, name)
            for box in got:
                box["min"].append(0)
            self.assertEqual(entry["boxes"], snapshot, name)
            checked += 1
        self.assertGreater(checked, 0, "no registered maps were checked")


if __name__ == "__main__":
    unittest.main()
