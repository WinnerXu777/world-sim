"""Dedicated item kinds for resource nodes (G-005): berries, mushrooms, reed_bundle, iron_ore exist, the two edible lists stay equal, and no node yields the farmers' crop_bundle."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from systems.affordance import config as aff  # noqa: E402
from systems.inventory.schema import ITEM_KIND_DEFS, build_item_stack  # noqa: E402
from systems.map import resources  # noqa: E402
from systems.tasks.families.survival import EDIBLE_ITEM_KINDS  # noqa: E402

NEW_KINDS = ("berries", "mushrooms", "reed_bundle", "iron_ore")


class ItemKindTests(unittest.TestCase):
    def test_new_kinds_are_defined_and_buildable(self):
        for kind in NEW_KINDS:
            definition = ITEM_KIND_DEFS[kind]
            self.assertTrue(definition["stackable"] and definition["max_stack"] > 1, kind)
            self.assertGreater(definition["unit_weight"], 0.0, kind)
            self.assertTrue(build_item_stack(kind, item_id=f"t_{kind}", quantity=2)["quantity"] == 2, kind)

    def test_the_edible_lists_are_equal_and_include_the_new_foods(self):
        self.assertEqual(aff.EDIBLE_ITEMS, tuple(EDIBLE_ITEM_KINDS))
        self.assertEqual(EDIBLE_ITEM_KINDS[:3], ("rations", "fish_catch", "crop_bundle"))      # eating order of the old kinds is unchanged
        self.assertEqual(EDIBLE_ITEM_KINDS[3:], ("berries", "mushrooms"))
        for kind in EDIBLE_ITEM_KINDS:
            self.assertIn("food", ITEM_KIND_DEFS[kind]["tags"], kind)

    def test_food_tagged_node_items_are_exactly_the_edible_ones(self):
        for name, item in resources.ITEM.items():
            self.assertEqual(name in resources.EDIBLE, item in EDIBLE_ITEM_KINDS, name)

    def test_every_node_item_exists_and_none_is_the_farmers_cargo(self):
        for name, item in resources.ITEM.items():
            self.assertIn(item, ITEM_KIND_DEFS, name)
            self.assertNotEqual(item, "crop_bundle", name)

    def test_ore_does_not_yield_ingots(self):
        self.assertEqual(resources.ITEM["ore"], "iron_ore")


if __name__ == "__main__":
    unittest.main()
