"""1008 Phase 2 (1008_creatures_gap.md section 6): the creature spawn plan is a pure, deterministic function of a generated chunk document and the table.

Real generated chunks are used (the generator is not touched: three chunk sha256s are pinned below so a generator change cannot hide behind this plan)."""
import collections
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from systems.creatures import spawn, table  # noqa: E402
from systems.worldgen import generate as gen, spec  # noqa: E402

SEED = 1008
RING = [(x, y) for x in range(-3, 4) for y in range(-3, 4)]
_CACHE: dict = {}


def chunk(cx, cy, seed=SEED):
    key = (seed, cx, cy)
    if key not in _CACHE:
        _CACHE[key] = gen.generate_chunk(seed, cx, cy)
    return _CACHE[key]


def busiest():
    """The chunk of RING whose plan has the most wolves (so 'disable wolf' shows something) and at least one other species."""
    return max(RING, key=lambda c: (sum(r["species"] == "wolf" for r in spawn.plan(chunk(*c).document)), len(spawn.plan(chunk(*c).document))))


class ConstantTests(unittest.TestCase):
    def test_constants_agree_with_the_generator(self):
        self.assertEqual(spawn.CHUNK_UNITS, spec.CHUNK_UNITS)
        self.assertEqual(spawn.TILE_UNITS, spec.UNITS_PER_TILE)
        self.assertEqual(spawn.CHUNK_TILES, spec.CHUNK_TILES)
        self.assertEqual(spawn.TERRAIN_WATER, spec.TERRAIN_WATER)

    def test_the_generator_is_untouched(self):
        # these hashes are what the generator produces today; if they move, the generator changed (not this plan)
        pinned = json.loads((ROOT / "tests" / "fixtures" / "creatures_chunk_hashes.json").read_text(encoding="utf-8"))
        for key, sha in pinned.items():
            cx, cy = (int(v) for v in key.split(","))
            self.assertEqual(chunk(cx, cy).sha256, sha, key)


class PurityTests(unittest.TestCase):
    def test_same_document_same_plan_and_the_document_is_not_modified(self):
        document = chunk(*busiest()).document
        before = copy.deepcopy(document)
        first = spawn.plan(document)
        second = spawn.plan(document)
        self.assertEqual(first, second)
        self.assertEqual(document, before)
        self.assertGreater(len(first), 0)

    def test_the_plan_does_not_depend_on_call_order(self):
        forward = {c: spawn.plan(chunk(*c).document) for c in RING}
        backward = {c: spawn.plan(chunk(*c).document) for c in reversed(RING)}
        self.assertEqual(forward, backward)

    def test_the_plan_is_the_same_in_another_process(self):
        code = ("import sys, json; sys.path.insert(0, sys.argv[1]); from systems.worldgen import generate as g; from systems.creatures import spawn; "
                "print(json.dumps([spawn.plan(g.generate_chunk(1008, x, y).document) for x, y in [(2, 2), (0, 3), (-1, 3)]]))")
        out = subprocess.run([sys.executable, "-c", code, str(ROOT / "at_the_beginning")], capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        here = json.loads(json.dumps([spawn.plan(chunk(x, y).document) for x, y in [(2, 2), (0, 3), (-1, 3)]]))
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), here)

    def test_another_seed_gives_another_world(self):
        plans = [spawn.plan(chunk(x, y, 7).document) for x, y in RING[:12]]
        base = [spawn.plan(chunk(x, y).document) for x, y in RING[:12]]
        self.assertNotEqual(plans, base)


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.plans = {c: spawn.plan(chunk(*c).document) for c in RING}
        self.all = [r for p in self.plans.values() for r in p]

    def test_records_are_complete_and_ids_are_unique(self):
        keys = {"uid", "species", "id", "x", "y", "group", "variant", "sex", "age", "life_exp", "hp"}
        uids = [r["uid"] for r in self.all]
        self.assertEqual(len(uids), len(set(uids)))
        for r in self.all:
            self.assertEqual(set(r), keys)
            self.assertEqual(r["id"], table.id_of(r["species"]))

    def test_only_enabled_species_with_a_habitat_appear(self):
        allowed = {n for n, row in table.CREATURES.items() if row["enabled"] and row["habitat"]}
        self.assertTrue({r["species"] for r in self.all} <= allowed)
        self.assertNotIn("rabbit", {r["species"] for r in self.all}, "rabbits are identity-only until enabled")

    def test_positions_are_inside_the_chunk_on_land_without_footprint(self):
        for c, plan in self.plans.items():
            document = chunk(*c).document
            for r in plan:
                self.assertTrue(0 <= r["x"] < 256 and 0 <= r["y"] < 256, r)
        free = sum(spawn._free(chunk(*c).document, r["x"], r["y"]) for c, p in self.plans.items() for r in p)
        self.assertGreaterEqual(free / len(self.all), 0.9, "jitter lands on legal tiles (fallback to the anchor is rare)")

    def test_groups_respect_the_table(self):
        for c, plan in self.plans.items():
            by_group = collections.defaultdict(list)
            for r in plan:
                by_group[(r["species"], r["group"])].append(r)
            for (species, _), members in by_group.items():
                lo, hi = table.CREATURES[species]["group"]["size"]
                self.assertLessEqual(len(members), hi)
                if len(plan) < spawn.MAX_PER_CHUNK:                                    # only the cap may cut a group short
                    self.assertGreaterEqual(len(members), lo, (c, species))

    def test_a_chunk_never_exceeds_the_cap(self):
        self.assertLessEqual(max(len(p) for p in self.plans.values()), spawn.MAX_PER_CHUNK)

    def test_density_is_a_handful_per_chunk(self):
        # 49 chunks of the seed-1008 world around the origin: not empty, not a zoo (the creature row quota is 96)
        self.assertGreater(len(self.all), 20)
        self.assertLess(len(self.all), 120)
        ring5 = sum(len(self.plans[(x, y)]) for x in range(-2, 3) for y in range(-2, 3))
        self.assertLess(ring5, 60)

    def test_wolves_are_packs_and_deer_are_herds(self):
        wolf_groups = collections.Counter((c, r["group"]) for c, p in self.plans.items() for r in p if r["species"] == "wolf")
        deer_groups = collections.Counter((c, r["group"]) for c, p in self.plans.items() for r in p if r["species"] == "deer")
        self.assertTrue(wolf_groups and all(1 <= n <= 6 for n in wolf_groups.values()))
        self.assertTrue(deer_groups)
        self.assertGreater(max(deer_groups.values()), 1)

    def test_ages_and_life_expectancy_follow_the_table(self):
        for r in self.all:
            lo, hi = table.CREATURES[r["species"]]["life_exp"]
            self.assertTrue(lo <= r["life_exp"] <= hi, r)
            self.assertTrue(0.0 <= r["age"] <= 0.6 * lo + 1e-3, r)
            self.assertIn(r["sex"], (0.0, 1.0))
            self.assertTrue(0 <= r["variant"] <= len(table.CREATURES[r["species"]]["variants"]))

    def test_group_ids_fit_float32_exactly(self):
        import numpy as np
        for r in self.all:
            self.assertEqual(int(np.float32(r["group"])), r["group"])


class PoiTests(unittest.TestCase):
    """The generator makes POIs rarely, so the POI rules are shown on a document with POIs added by hand (a copy of a real chunk)."""

    def doc(self, kinds):
        document = copy.deepcopy(chunk(2, 2).document)
        document["data"]["pois"] = [{"id": f"poi{i}", "kind": kind, "tile_rect": [0, 0, 1, 1], "position": [60.0 + 40 * i, 90.0]} for i, kind in enumerate(kinds)]
        return document

    def test_hostiles_stand_at_the_matching_pois_only(self):
        found = collections.Counter()
        for seed in range(40):
            document = self.doc(["ruin", "camp", "cave", "shrine"])
            for r in spawn.plan(document, world_seed=seed):
                found[r["species"]] += 1
        self.assertTrue(found["skeleton"] and found["goblin"] and found["giant_spider"], found)
        document = self.doc(["shrine"])
        for seed in range(40):
            self.assertEqual([r for r in spawn.plan(document, world_seed=seed) if r["species"] in ("skeleton", "goblin", "giant_spider")], [])

    def test_poi_groups_stand_near_their_poi(self):
        for seed in range(40):
            document = self.doc(["ruin"])
            for r in spawn.plan(document, world_seed=seed):
                if r["species"] == "skeleton":
                    self.assertLess(((r["x"] - 60.0) ** 2 + (r["y"] - 90.0) ** 2) ** 0.5, 40.0, r)


class RuleEdgeTests(unittest.TestCase):
    def test_a_chunk_without_spawns_or_pois_plans_nothing(self):
        document = copy.deepcopy(chunk(2, 2).document)
        document["data"]["spawns"] = []
        document["data"]["pois"] = []
        self.assertEqual(spawn.plan(document), [])

    def test_disabling_a_species_removes_it_without_moving_the_others(self):
        document = chunk(*busiest()).document
        full = spawn.plan(document)
        self.assertTrue(any(r["species"] == "wolf" for r in full))
        smaller = copy.deepcopy(table.CREATURES)
        smaller["wolf"]["enabled"] = False
        reduced = spawn.plan(document, smaller)
        self.assertEqual(reduced, [r for r in full if r["species"] != "wolf"], "each species' choices are independent hashes")


if __name__ == "__main__":
    unittest.main()
