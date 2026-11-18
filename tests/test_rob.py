"""EDEN_ROB: the contest rules, the ``rob`` verb through the ActionRunner on the synthetic Scene, the risk gate, the flag-off behaviour."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import unittest
import unittest.mock

from driver_pin import pin_anchor
from systems import rob as rules
from test_actions_runner import Scene, setrow


class Rules(unittest.TestCase):
    def test_power_grows_with_health_and_temper_and_a_guard_helps_the_victim(self):
        self.assertGreater(rules.power(100, 0.9), rules.power(100, 0.1))
        self.assertGreater(rules.power(100, 0.5), rules.power(40, 0.5))
        self.assertAlmostEqual(rules.power(100, 0.5, True) - rules.power(100, 0.5), rules.GUARD_BONUS)

    def test_the_chance_stays_in_its_band_and_follows_the_stronger_side(self):
        self.assertEqual(rules.p_success(5.0, 0.0), rules.CEIL)
        self.assertEqual(rules.p_success(0.0, 5.0), rules.FLOOR)
        self.assertGreater(rules.p_success(0.9, 0.5), 0.5)
        self.assertLess(rules.p_success(0.5, 0.9), 0.5)
        self.assertEqual(rules.p_success(0.6, 0.6), 0.5)

    def test_flag_default_off(self):
        with unittest.mock.patch.dict(os.environ):
            os.environ.pop("EDEN_ROB", None)
            self.assertFalse(rules.enabled())


class RobCase(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {"EDEN_ROB": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def force(self, chance):
        patcher = unittest.mock.patch.object(rules, "p_success", lambda a, b: chance)
        patcher.start()
        self.addCleanup(patcher.stop)

    def hp(self, scene, human_id):
        return scene.world.table("humans").get(human_id, "hp")


class Rob(RobCase):
    def test_a_win_moves_the_food_hurts_the_victim_and_is_a_ledger_event(self):
        self.force(1.0)
        s = Scene()
        r = s.runner.run("h_a", "rob", {"target": "h_b"}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual(s.world.items.quantity("h_b", "rations"), 0)
        self.assertEqual(s.world.items.quantity("h_a", "rations"), 3)
        self.assertEqual(self.hp(s, "h_b"), 100 - rules.ROB_DAMAGE)
        self.assertEqual(self.hp(s, "h_a"), 100)
        self.assertIn("robbery", [e.type for e in r.report.events])
        self.assertLess(s.records["h_b"]["relationships"]["h_a"]["closeness"], 0.0)

    def test_a_loss_costs_the_robber_and_leaves_the_victim_its_food(self):
        self.force(0.0)
        s = Scene()
        r = s.runner.run("h_a", "rob", {"target": "h_b"}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual(s.world.items.quantity("h_b", "rations"), 1)
        self.assertEqual(self.hp(s, "h_a"), 100 - rules.ROB_BACKLASH)
        self.assertEqual(self.hp(s, "h_b"), 100)
        self.assertIn("robbery_failed", [e.type for e in r.report.events])

    def test_the_odds_are_in_the_verdict_and_the_draw_is_deterministic(self):
        s = Scene()
        verdict = s.runner.aff.legal("h_a", "rob", {"target": "h_b"})
        self.assertTrue(verdict.ok)
        self.assertEqual(set(verdict.detail), {"item", "qty", "guarded", "p"})
        self.assertGreaterEqual(verdict.detail["p"], rules.FLOOR)
        outcomes = []
        for _ in range(2):
            t = Scene()
            outcomes.append(t.runner.run("h_a", "rob", {"target": "h_b"}, proposer="rules:test").report.events[-1].type)
        self.assertEqual(outcomes[0], outcomes[1])

    def test_nothing_to_take_too_hurt_far_dead_or_self(self):
        s = Scene()
        setrow(s.world, "h_a", hp=rules.ROB_MIN_HP - 1)
        self.assertEqual(s.runner.run("h_a", "rob", {"target": "h_b"}, proposer="rules:test").code, "illegal:too_hurt")
        u = Scene()
        self.assertFalse(u.runner.run("h_a", "rob", {"target": "h_far"}, proposer="rules:test").ok)
        self.assertEqual(u.runner.run("h_a", "rob", {"target": "h_dead"}, proposer="rules:test").code, "illegal:target_dead")
        self.assertEqual(u.runner.run("h_a", "rob", {"target": "h_a"}, proposer="rules:test").code, "illegal:self_target")
        self.assertEqual(u.runner.run("h_a", "rob", {"target": "h_smith"}, proposer="rules:test").code, "illegal:nothing_to_take")        # h_smith carries nothing

    def test_it_is_destructive_a_model_below_the_gate_cannot_rob(self):
        s = Scene()
        r = s.runner.run("h_a", "rob", {"target": "h_b"}, proposer="tier1:matrix", confidence=0.3)
        self.assertEqual(r.code, "risk_gated")
        self.assertEqual((s.world.items.quantity("h_b", "rations"), self.hp(s, "h_b"), self.hp(s, "h_a")), (1, 100, 100))

    def test_the_mask_lists_no_candidates(self):
        s = Scene()
        self.assertEqual([o for o in s.runner.aff.options("h_a") if o.verb == "rob"], [])

    def test_flag_off_is_not_wired(self):
        os.environ.pop("EDEN_ROB")
        s = Scene()
        before = s.digest()
        self.assertFalse(s.runner.run("h_a", "rob", {"target": "h_b"}, proposer="rules:test").ok)
        self.assertTrue(s.same(before, s.digest()))


class Arrest(RobCase):
    def test_flag_off_restraint_off_and_a_scene_without_an_engine_refuse(self):
        s = Scene()
        r = s.runner.run("h_a", "arrest_or_restrain", {"target": "h_b"}, proposer="rules:test")
        self.assertFalse(r.ok)
        self.assertIn(r.code, ("illegal:not_wired", "illegal:no_engine", "illegal:not_authority"))


if __name__ == "__main__":
    unittest.main()
