"""1008 Phase 2 (1008_creatures_gap.md section 3 and 4): the creature definition table.

The id/name list below is the contract with the asset side: it is written out here on purpose, so changing an id (or reusing one) fails this test and not only a
snapshot. ``tests/fixtures/creatures_contract.json`` is the exported contract (regenerate with ``tools/export_creatures.py`` ONLY when a species is added)."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from systems.creatures import table  # noqa: E402

FROZEN_IDS = {
    "sheep": 40, "deer": 41, "tiger": 42, "wolf": 43, "fish": 44,
    "boar": 45, "fox": 46, "goblin": 47, "skeleton": 48, "giant_spider": 49, "goat": 50, "rabbit": 51, "dog": 52, "cat": 53, "cow": 54, "horse": 55,
    "chicken": 56, "songbird": 57, "crow": 58,
    "brambleback": 60, "mire_lantern": 61, "cinder_moth": 62, "cairn_keeper": 63, "thread_thief": 64, "bellhorn": 65, "glassfin": 66, "moonhart": 67,
    "rootling": 68, "hollow_rook": 69,
}
SPARE_IDS = {59, *range(70, 80)}


class IdTests(unittest.TestCase):
    def test_no_id_is_ever_reassigned_or_dropped(self):
        for name, ident in FROZEN_IDS.items():
            self.assertIn(name, table.CREATURES, f"{name} was removed: the asset side depends on it")
            self.assertEqual(table.CREATURES[name]["id"], ident, f"{name} changed id")
        self.assertEqual({r["id"] for r in table.CREATURES.values()} & SPARE_IDS, set(), "a spare id was used without updating the frozen list")
        self.assertEqual(set(table.CREATURES) - set(FROZEN_IDS), set(), "a species was added: add it to FROZEN_IDS and the contract fixture")

    def test_ids_are_unique_and_inside_the_animal_range(self):
        ids = [r["id"] for r in table.CREATURES.values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i in cfg.ANIMAL_TYPES for i in ids))
        self.assertEqual({n: getattr(cfg, f"M_{n.upper()}") for n in ("sheep", "deer", "tiger", "wolf", "fish")},
                         {n: FROZEN_IDS[n] for n in ("sheep", "deer", "tiger", "wolf", "fish")})

    def test_the_exported_contract_equals_the_frozen_fixture(self):
        fixture = json.loads((ROOT / "tests" / "fixtures" / "creatures_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(table.export(), fixture)

    def test_lookups(self):
        self.assertEqual(table.get(43)["label"], "wolf")
        self.assertIs(table.get("wolf"), table.get(43))
        self.assertIsNone(table.get(99))
        self.assertEqual(table.id_of("giant_spider"), 49)


class ValidationTests(unittest.TestCase):
    def broken(self, name, **changes):
        bad = copy.deepcopy(table.CREATURES)
        bad[name].update(changes)
        return table.validate(bad)

    def test_the_shipped_table_is_valid(self):
        self.assertEqual(table.validate(), [])

    def test_bad_rows_are_named(self):
        cases = {
            "outside": self.broken("wolf", id=12),
            "already used": self.broken("fox", id=45),
            "fractions": self.broken("wolf", aggro=1.5),
            "needs a range": self.broken("wolf", range=0.0),
            "walk <= run": self.broken("wolf", speed={"walk": 5.0, "run": 1.0}),
            "activity": self.broken("wolf", activity={"day": 1.0}),
            "unknown species": self.broken("wolf", diet={"eats": ["meat"], "prey": ["unicorn"], "humans": "never"}),
            "vocabulary": self.broken("wolf", diet={"eats": ["rocks"], "prey": [], "humans": "never"}),
            "group.size": self.broken("wolf", group={"kind": "pack", "size": [6, 3], "cohesion": 1.0}),
            "territory": self.broken("wolf", territory={"radius": 100.0, "leash": 50.0}),
            "loot entry": self.broken("wolf", loot=[{"item": "meat", "min": 3, "max": 1, "p": 1.0}]),
            "exactly one": self.broken("wolf", habitat={"spawn_entry": "wolf", "poi": ["ruin"]}),
            "unknown keys": self.broken("wolf", colour="red"),
            "label": self.broken("wolf", label="Wolf"),
        }
        for fragment, problems in cases.items():
            self.assertTrue(any(fragment in p and p.startswith(("wolf:", "fox:")) for p in problems), (fragment, problems))

    def test_a_missing_key_is_reported_not_crashed_on(self):
        bad = copy.deepcopy(table.CREATURES)
        del bad["wolf"]["hp"]
        self.assertTrue(any("missing keys" in p for p in table.validate(bad)))


class LegacyParityTests(unittest.TestCase):
    """The five legacy species: the table says exactly what genesis_config says (so installing it can never change them)."""

    def test_the_legacy_dictionaries_equal_the_table(self):
        derived = table.legacy_dicts(cfg.AGENT_TYPE_HUMAN)
        for name in ("ANIMAL_LIFE_EXP", "ANIMAL_SCALE", "ANIMAL_BASE_AGGRESSION", "ANIMAL_MOVE_STEP", "ANIMAL_PREY"):
            legacy = getattr(cfg, name)
            for ident in (cfg.M_SHEEP, cfg.M_DEER, cfg.M_TIGER, cfg.M_WOLF, cfg.M_FISH):
                self.assertEqual(legacy.get(ident), derived[name].get(ident), (name, ident))

    def test_legacy_species_keep_the_legacy_brain(self):
        for name in ("sheep", "deer", "tiger", "wolf", "fish"):
            self.assertEqual(table.CREATURES[name]["brain"], "legacy")
        self.assertTrue(all(r["brain"] == "table" for r in table.CREATURES.values() if r["id"] >= 45))

    def test_prey_names_resolve_to_ids(self):
        self.assertEqual(table.prey_ids("fox"), {table.id_of("rabbit"), table.id_of("chicken")})


class DataSanityTests(unittest.TestCase):
    def test_the_first_set_is_enabled_and_the_invented_species_are_not(self):
        for name in ("wolf", "boar", "deer", "fox", "goblin", "skeleton", "giant_spider"):
            self.assertTrue(table.CREATURES[name]["enabled"], name)
        for name in ("brambleback", "mire_lantern", "cinder_moth", "cairn_keeper", "thread_thief", "bellhorn", "glassfin", "moonhart", "rootling", "hollow_rook"):
            self.assertFalse(table.CREATURES[name]["enabled"], name)

    def test_frames_and_pivots_follow_the_bible(self):
        a, b, c = table.FRAME_A, table.FRAME_B, table.FRAME_C
        expected = {"wolf": a, "boar": a, "fox": a, "sheep": a, "goat": a, "goblin": a, "skeleton": a, "giant_spider": a, "rabbit": b, "chicken": b, "songbird": b,
                    "crow": b, "fish": b, "deer": c, "cow": c, "horse": c, "cairn_keeper": c, "bellhorn": c, "moonhart": c, "brambleback": a, "rootling": a,
                    "hollow_rook": a, "mire_lantern": b, "cinder_moth": b, "thread_thief": b, "glassfin": b}
        for name, frame in expected.items():
            self.assertEqual(tuple(table.CREATURES[name]["frame"]), frame, name)

    def test_the_generator_species_are_table_species(self):
        from systems.worldgen.generate import SPECIES
        for name, _ in SPECIES:
            self.assertIn(name, table.CREATURES, name)
            self.assertEqual(table.CREATURES[name]["habitat"].get("spawn_entry"), name)

    def test_only_art_that_exists_has_a_sprite(self):
        from systems.worldgen import assets
        sprites = {r["name"]: r["sprite"] for r in table.export()["species"] if r["sprite"]}
        self.assertEqual(set(sprites), set(assets.SPECIES_SPRITES))
        for name, path in sprites.items():
            self.assertEqual(path, assets.SPECIES_SPRITES[name])

    def test_importing_the_table_does_not_need_torch(self):
        path = ROOT / "at_the_beginning" / "systems" / "creatures" / "table.py"
        code = ("import sys, importlib.util as u; s = u.spec_from_file_location('t', sys.argv[1]); m = u.module_from_spec(s); s.loader.exec_module(m); "
                "print('torch' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


class InterfaceTests(unittest.TestCase):
    """The lookups the model plane reads (latenight2's request): the legacy sets with the flag off, the table with it on."""

    def test_flag_off_the_sets_are_the_legacy_ones(self):
        from unittest import mock
        import os
        from systems.combat.hunting import HUNTABLE_ANIMAL_TYPES
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_CREATURES", None)
            self.assertEqual(table.hostile_types(), frozenset({cfg.M_TIGER, cfg.M_WOLF}))
            self.assertEqual(table.huntable_types(), frozenset(HUNTABLE_ANIMAL_TYPES))

    def test_flag_on_the_sets_come_from_the_rows(self):
        from unittest import mock
        import os
        with mock.patch.dict(os.environ, {"EDEN_CREATURES": "1"}):
            self.assertEqual(table.hostile_types(), frozenset(r["id"] for r in table.CREATURES.values() if r["hostile"]))
            self.assertIn(table.id_of("giant_spider"), table.hostile_types())
            self.assertIn(table.id_of("boar"), table.huntable_types())
            self.assertTrue({cfg.M_TIGER, cfg.M_WOLF} <= table.hostile_types() and set(table.LEGACY_HUNTABLE) <= table.huntable_types())

    def test_by_type_name_of_loot_of(self):
        self.assertEqual(table.by_type(45)["label"], "boar")
        self.assertIsNone(table.by_type(3))
        self.assertIsNone(table.by_type("x"))
        self.assertEqual(table.name_of(46), "fox")
        self.assertIsNone(table.name_of(99))
        loot = table.loot_of(41)
        self.assertTrue(loot and all(set(e) == {"item", "min", "max", "p"} for e in loot))
        loot[0]["item"] = "changed"
        self.assertNotEqual(table.loot_of(41)[0]["item"], "changed", "callers get copies")
        self.assertEqual(table.loot_of(3), [])

    def test_loot_and_product_items_exist_in_the_inventory_catalog(self):
        from systems.inventory.schema import ITEM_KIND_DEFS
        for name, row in table.CREATURES.items():
            for entry in row["loot"]:
                self.assertIn(entry["item"], ITEM_KIND_DEFS, (name, entry))
            for product in row["products"]:
                self.assertIn(product["item"], ITEM_KIND_DEFS, (name, product))

    def test_threat_and_perception_defaults(self):
        self.assertEqual(table.threat_of(41), 0.0)                       # deer: no damage
        self.assertGreater(table.threat_of(43), table.threat_of(46))     # a wolf frightens more than a fox
        self.assertEqual(table.perceive_radius_of(43), table.CREATURES["wolf"]["aggro_range"])
        self.assertEqual(table.threat_of(99), 0.0)
        copy_table = copy.deepcopy(table.CREATURES)
        copy_table["wolf"]["threat"] = 120.0
        self.assertTrue(any("threat" in p for p in table.validate(copy_table)))

    def test_tame_products_carcass_defaults_and_vocabulary(self):
        for name, row in table.CREATURES.items():
            self.assertIn(row["tame"]["mode"], table.TAME_MODES, name)
        self.assertEqual(table.CREATURES["dog"]["tame"]["mode"], "domestic")
        self.assertEqual(table.CREATURES["wolf"]["tame"]["mode"], "tameable")
        self.assertEqual(table.CREATURES["skeleton"]["tame"]["mode"], "wild")
        self.assertEqual(table.CREATURES["chicken"]["products"][0]["item"], "egg")
        bad = copy.deepcopy(table.CREATURES)
        bad["dog"]["tame"]["mode"] = "feral"
        bad["chicken"]["products"] = [{"item": "egg", "every_days": 0, "needs": "fed"}]
        bad["deer"]["carcass"] = {"ticks": -1}
        problems = table.validate(bad)
        self.assertTrue(any(p.startswith("dog:") for p in problems) and any(p.startswith("chicken:") for p in problems) and any(p.startswith("deer:") for p in problems))


if __name__ == "__main__":
    unittest.main()
