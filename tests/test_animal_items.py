"""The animal-product item kinds that creature loot names exist in the inventory catalog (data only: nothing eats them, nothing enumerates them in a golden world)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import unittest

from systems.creatures import table
from systems.inventory.schema import ITEM_KIND_DEFS, build_item_stack

PRODUCTS = ("meat", "hide", "bone", "feather", "egg", "wool", "silk", "scrap")
KNOWN_MISSING = set()


class AnimalItems(unittest.TestCase):
    def test_every_product_is_a_stackable_material_that_is_not_food(self):
        for kind in PRODUCTS:
            definition = ITEM_KIND_DEFS[kind]
            self.assertTrue(definition["stackable"], kind)
            self.assertNotIn("food", definition["tags"], kind)               # raw materials: no verb eats them (cooking does not exist yet)
            self.assertGreater(definition["value"], 0.0, kind)
            stack = build_item_stack(kind, item_id=f"it_{kind}", quantity=3)
            self.assertEqual((stack["kind"], stack["quantity"]), (kind, 3))

    def test_every_loot_item_of_the_creature_table_is_a_real_kind(self):
        named = {entry["item"] for row in table.CREATURES.values() for entry in row["loot"]}
        self.assertEqual(named - set(ITEM_KIND_DEFS), KNOWN_MISSING & named)


if __name__ == "__main__":
    unittest.main()
