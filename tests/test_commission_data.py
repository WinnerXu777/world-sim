"""P4.2 data: sword, iron ingot, smith occupation, recipe, and the single economy constant."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from systems.commission.config import COMMISSION_CONFIG, price_for, work_ticks_for
from systems.crafting.ops import crafting_missing_ingredients
from systems.crafting.resolver import crafting_recipe_def, crafting_recipe_ids, crafting_recipes_for_occupation
from systems.inventory.ops import add_item
from systems.inventory.schema import ITEM_KIND_DEFS, build_item_stack
from systems.inventory.store import build_inventory_record
from systems.occupation.catalog import ALL_OCCUPATION_NAMES, OCCUPATION_DEFS, OCCUPATION_NAMES
from systems.occupation.inheritance import sample_occupation_kind


class DataTests(unittest.TestCase):
    def test_items(self):
        iron, sword = ITEM_KIND_DEFS["iron_ingot"], ITEM_KIND_DEFS["sword"]
        self.assertTrue(iron["stackable"])
        self.assertIn("iron", iron["tags"])
        self.assertFalse(sword["stackable"])
        self.assertEqual(sword["slot"], "main_hand")
        self.assertIn("weapon", sword["tags"])
        self.assertEqual(build_item_stack("sword", item_id="i1")["kind"], "sword")

    def test_recipe(self):
        recipe = crafting_recipe_def("sword")
        self.assertEqual(recipe["output_kind"], "sword")
        self.assertEqual([(i["item_kind"], i["quantity"]) for i in recipe["ingredient_requirements"]], [("iron_ingot", 2), ("wood_bundle", 1)])
        self.assertEqual((recipe["station_kind"], recipe["occupation_tags"], recipe["required_tool_tags"]), ("forge", ("smith",), ("hammer",)))
        self.assertIn("sword", crafting_recipe_ids())
        self.assertEqual(crafting_recipes_for_occupation("smith"), ("sword",))
        for other in ("farmer", "builder", "guard", "gatherer", "trader", "healer", "hunter"):
            self.assertNotIn("sword", crafting_recipes_for_occupation(other))

    def test_missing_ingredients_for_a_sword(self):
        record = build_inventory_record("x", "human", "x", capacity_slots=20, capacity_weight=None)
        self.assertEqual({m["item_kind"]: m["missing_quantity"] for m in crafting_missing_ingredients("sword", record["items"])},
                         {"iron_ingot": 2, "wood_bundle": 1})
        add_item(record, "iron_ingot", 2)
        add_item(record, "wood_bundle", 1)
        self.assertEqual(crafting_missing_ingredients("sword", record["items"]), [])

    def test_smith_is_assignable_but_never_sampled(self):
        self.assertIn("smith", ALL_OCCUPATION_NAMES)
        self.assertNotIn("smith", OCCUPATION_NAMES)
        self.assertEqual(sample_occupation_kind("h_000001", preferred_kind="smith")["kind"], "smith")
        for index in range(200):
            self.assertNotEqual(sample_occupation_kind(f"h_{index:06d}")["kind"], "smith")
        self.assertEqual(sample_occupation_kind("h_000001", preferred_kind="not_a_job")["origin"] != "preferred", True)

    def test_legacy_occupation_sampling_is_unchanged(self):
        # the tuple the sampler iterates is exactly the pre-smith list, in the same order
        self.assertEqual(OCCUPATION_NAMES, ("builder", "farmer", "fisherman", "gatherer", "guard", "healer", "hunter", "trader", "woodcutter"))

    def test_smith_blueprint(self):
        smith = OCCUPATION_DEFS["smith"]
        self.assertEqual(smith["required_tools"], ("hammer",))
        self.assertIn("work_site", smith["block_routines"]["day"])
        self.assertIn("sleep", smith["block_routines"]["night"])
        self.assertIn("socialize", smith["block_routines"]["dusk"])
        self.assertNotIn("sword", smith["required_tools"] + smith["optional_tools"])  # a sword is never baseline-provisioned

    def test_economy_numbers_live_in_one_constant(self):
        self.assertEqual(price_for("sword"), 30)
        self.assertEqual(work_ticks_for("sword"), 900)
        self.assertEqual(COMMISSION_CONFIG["smith_stock"], {"iron_ingot": 4, "wood_bundle": 4})
        tuned = {**COMMISSION_CONFIG, "prices": {"sword": 45}, "work_ticks_per_time_unit": 400}
        self.assertEqual((price_for("sword", tuned), work_ticks_for("sword", tuned)), (45, 600))


if __name__ == "__main__":
    unittest.main()
