"""Escalation ladder (EDEN_AGENT_LADDER) and reputation (EDEN_REPUTATION): the pure rules, and the S-1 family_farm scenario in a fresh process
(``model_server/s1_family_farm.py``: ``map_test`` owns a module-level engine, so the real-engine run cannot share this test process)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from systems.actions import ladder, reputation  # noqa: E402

MERCIFUL = {"mercy": 0.85, "loyalty": 0.85, "discipline": 0.75, "deceitfulness": 0.1, "greed": 0.2, "aggression": 0.1}
CORRUPT = {"mercy": 0.3, "loyalty": 0.5, "discipline": 0.3, "deceitfulness": 0.6, "greed": 0.6, "aggression": 0.4}


class PureRules(unittest.TestCase):
    def test_flags_default_off(self):
        for name in (ladder.ENV, reputation.ENV):
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(name, None)
                self.assertFalse((ladder.enabled if name == ladder.ENV else reputation.enabled)())

    def test_conscience_orders_the_two_parents(self):
        self.assertGreater(ladder.conscience(MERCIFUL), 0.5)
        self.assertLess(ladder.conscience(CORRUPT), 0.0)

    def test_desperation_grows_with_hunger_empty_pack_and_hungry_dependants(self):
        base = ladder.desperation(40, True, 0, False)
        self.assertAlmostEqual(base, 0.4)
        self.assertGreater(ladder.desperation(40, False, 0, False), base)
        self.assertGreater(ladder.desperation(40, True, 2, False), base)
        self.assertLess(ladder.desperation(40, True, 0, True), base)
        self.assertLessEqual(ladder.desperation(100, False, 9, False), 1.2)

    def test_conscience_raises_the_bar_of_stealing_and_family_lowers_it(self):
        good, bad = ladder.thresholds(ladder.conscience(MERCIFUL)), ladder.thresholds(ladder.conscience(CORRUPT))
        self.assertGreater(good["steal"], bad["steal"])
        self.assertLess(ladder.thresholds(0.3, family_push=0.12)["steal"], ladder.thresholds(0.3)["steal"])
        self.assertEqual(ladder.thresholds(0.0)["forage"], 0.0)

    def test_the_merciful_beg_the_corrupt_steal_at_the_same_hunger(self):
        d = ladder.desperation(45, False, 0, False)                      # 0.65: above the corrupt parent's steal bar (0.61), below the merciful one's (0.83)
        self.assertNotIn("steal", ladder.allowed(d, ladder.conscience(MERCIFUL)))
        self.assertIn("steal", ladder.allowed(d, ladder.conscience(CORRUPT)))
        self.assertEqual(ladder.allowed(d, ladder.conscience(MERCIFUL))[:2], ["forage", "trade"])

    def test_rungs_are_tried_in_cost_order_and_pride_moves_begging_last(self):
        order = ladder.allowed(1.2, 0.0)
        self.assertEqual(order, ["forage", "trade", "beg", "steal"])
        built = ladder.BUILT + ("borrow",)                                 # borrow is designed, not built: with it a proud resident begs after being lent to
        self.assertEqual(ladder.allowed(1.2, 0.0, built=built), ["forage", "trade", "beg", "borrow", "steal"])
        self.assertEqual(ladder.allowed(1.2, 0.0, pride=0.9, built=built), ["forage", "trade", "borrow", "beg", "steal"])

    def test_households_come_from_the_roster_key_and_the_entity_id(self):
        self.assertEqual(ladder.household_of_resident("family_mara"), "family")
        self.assertEqual(ladder.household_of_entity("neighbour:pantry"), "neighbour")
        self.assertEqual(ladder.household_of_entity("family_interior:storage"), "family")

    def test_response_by_personality(self):
        self.assertEqual(reputation.response_of({"vengefulness": 0.9, "mercy": 0.1}), "retaliate")
        self.assertEqual(reputation.response_of({"protectiveness": 0.8, "mercy": 0.8}), "confront")
        self.assertEqual(reputation.response_of({"caution": 0.9}), "avoid")
        self.assertEqual(reputation.response_of({}), "wary")

    def test_a_known_thief_with_hostile_closeness_is_refused(self):
        record = {"relationships": {"h_1": {"closeness": -0.3, "tags": ["thief"]}}}
        self.assertTrue(reputation.refuses(record, "h_1"))
        self.assertFalse(reputation.refuses(record, "h_2"))
        self.assertFalse(reputation.refuses({"relationships": {"h_1": {"closeness": 0.1, "tags": ["thief"]}}}, "h_1"))


def scenario(*args, timeout=900):
    out = Path(tempfile.mkdtemp()) / "out.json"
    proc = subprocess.run([sys.executable, "-m", "model_server.s1_family_farm", *args, "--json", str(out)], cwd=str(ROOT), capture_output=True, text=True,
                          timeout=timeout)
    return proc, json.loads(out.read_text(encoding="utf-8")) if out.exists() else None


class FamilyFarmScenario(unittest.TestCase):
    def test_forage_variant_feeds_the_family_without_theft(self):
        proc, result = scenario("--variant", "forage", "--ticks", "900")
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:] + proc.stderr[-800:])
        self.assertEqual(result["events"].get("theft", 0), 0)
        self.assertGreater(result["ladder"]["counts"].get("forage:ok", 0), 0)

    def test_steal_variant_with_reputation_leaves_a_traceable_theft(self):
        proc, result = scenario("--variant", "steal", "--ticks", "3000", "--reputation")
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:] + proc.stderr[-800:])
        self.assertGreater(result["events"].get("theft", 0), 0)
        self.assertGreater(result["events"].get("loss_discovered", 0), 0)
        self.assertGreater(result["reputation"]["counts"].get("opinion_drop", 0), 0)
        self.assertEqual(result["dead_at"], {})


if __name__ == "__main__":
    unittest.main()
