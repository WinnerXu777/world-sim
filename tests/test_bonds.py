"""EDEN_BONDS: court / befriend / apologise / forgive. The pure rules, the verbs through the ActionRunner on the synthetic Scene, the flag-off behaviour."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import unittest
import unittest.mock

from driver_pin import pin_anchor
from systems.actions import resource_verbs
from systems.bonds import enabled, rules
from test_actions_runner import Scene


class Rules(unittest.TestCase):
    def test_apology_moves_a_grudge_toward_zero_never_past_it(self):
        self.assertEqual(rules.apology_effect(-0.02, 0.5, False), 0.0)                   # no grudge, nothing to apologise for
        self.assertAlmostEqual(rules.apology_effect(-0.3, 0.5, False), rules.APOLOGY_STEP, places=4)
        self.assertEqual(rules.apology_effect(-0.06, 1.0, False), 0.06)                  # capped at the grudge itself
        self.assertGreater(rules.apology_effect(-0.3, 1.0, False), rules.apology_effect(-0.3, 0.0, False))          # mercy helps
        self.assertAlmostEqual(rules.apology_effect(-0.9, 0.5, False), rules.APOLOGY_STEP * 0.5, places=4)         # a grave grudge: half
        self.assertAlmostEqual(rules.apology_effect(-0.3, 0.5, True), rules.APOLOGY_STEP * rules.APOLOGY_VS_THIEF, places=4)

    def test_forgiving_stops_at_zero(self):
        self.assertEqual(rules.forgive_delta(0.2), 0.0)
        self.assertEqual(rules.forgive_delta(-0.4), rules.FORGIVE_STEP)
        self.assertEqual(rules.forgive_delta(-0.1), 0.1)

    def test_steps_stop_at_the_caps(self):
        self.assertEqual(rules.befriend_step(0.1, 0.1), rules.BEFRIEND_STEP)
        self.assertEqual(rules.befriend_step(0.9, 0.7), 0.0)
        self.assertEqual(rules.befriend_step(0.9, 0.1), rules.BEFRIEND_STEP)               # the weaker side still gains
        self.assertEqual(rules.court_step(0.9), 0.0)

    def test_flag_default_off(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDEN_BONDS", None)
            self.assertFalse(enabled())


def relation(closeness, tags=(), kind="known"):
    return {"closeness": closeness, "tags": list(tags), "kind": kind}


class BondsCase(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {"EDEN_BONDS": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def close(self, scene, owner, other):
        return scene.records[owner].get("relationships", {}).get(other, {}).get("closeness", 0.0)


class Befriend(BondsCase):
    def test_both_sides_gain_and_it_is_an_event(self):
        s = Scene()
        r = s.runner.run("h_a", "befriend", {"target": "h_b"}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertAlmostEqual(self.close(s, "h_a", "h_b"), rules.BEFRIEND_STEP)
        self.assertAlmostEqual(self.close(s, "h_b", "h_a"), rules.BEFRIEND_STEP)
        self.assertIn("befriended", [e.type for e in r.report.events])

    def test_a_hostile_neighbour_refuses_and_nothing_changes(self):
        s = Scene()
        s.records["h_b"]["relationships"] = {"h_a": relation(-0.4)}
        before = s.digest()
        r = s.runner.run("h_a", "befriend", {"target": "h_b"}, proposer="rules:test")
        self.assertFalse(r.ok)
        self.assertEqual(r.code, "illegal:refuse_distrust")
        self.assertTrue(s.same(before, s.digest()))

    def test_at_the_cap_it_is_not_needed_and_a_far_target_is_out_of_range(self):
        s = Scene()
        s.records["h_a"]["relationships"] = {"h_b": relation(0.8)}
        s.records["h_b"]["relationships"] = {"h_a": relation(0.8)}
        self.assertEqual(s.runner.run("h_a", "befriend", {"target": "h_b"}).code, "illegal:not_needed")
        self.assertFalse(s.runner.run("h_a", "befriend", {"target": "h_far"}).ok)
        self.assertEqual(s.runner.run("h_a", "befriend", {"target": "h_dead"}).code, "illegal:target_dead")

    def test_the_mask_lists_the_neighbours_in_talking_distance(self):
        s = Scene()
        names = {o.params["target"] for o in s.runner.aff.options("h_a") if o.verb == "befriend"}
        self.assertEqual(names, {"h_b", "h_smith"})


class Court(BondsCase):
    def test_needs_some_fondness_first(self):
        s = Scene()
        self.assertEqual(s.runner.run("h_a", "court", {"target": "h_b"}).code, "illegal:refuse_distrust")
        s.records["h_a"]["relationships"] = {"h_b": relation(0.3)}
        s.records["h_b"]["relationships"] = {"h_a": relation(0.3)}
        r = s.runner.run("h_a", "court", {"target": "h_b"})
        self.assertTrue(r.ok, r.code)
        self.assertAlmostEqual(self.close(s, "h_a", "h_b"), 0.3 + rules.COURT_STEP)

    def test_kin_are_not_courted(self):
        s = Scene()
        s.records["h_a"]["relationships"] = {"h_b": relation(0.5, kind="family")}
        s.records["h_b"]["relationships"] = {"h_a": relation(0.5, kind="family")}
        self.assertEqual(s.runner.run("h_a", "court", {"target": "h_b"}).code, "illegal:kin")


class Apologise(BondsCase):
    def test_the_grudge_shrinks_and_the_listener_remembers(self):
        s = Scene()
        s.records["h_b"]["relationships"] = {"h_a": relation(-0.3)}
        r = s.runner.run("h_a", "apologise", {"target": "h_b"}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        effect = rules.apology_effect(-0.3, 0.5, False)
        self.assertAlmostEqual(self.close(s, "h_b", "h_a"), round(-0.3 + effect, 3))
        self.assertLess(self.close(s, "h_b", "h_a"), 0.0)                                  # an apology never makes a friend
        self.assertAlmostEqual(self.close(s, "h_a", "h_b"), rules.SELF_RELIEF)
        self.assertTrue(any(m["kind"] == "heard_apology" for m in s.records["h_b"]["memory"]["recent_events"]))

    def test_no_grievance_no_apology(self):
        s = Scene()
        self.assertEqual(s.runner.run("h_a", "apologise", {"target": "h_b"}).code, "illegal:no_grievance")

    def test_against_a_thief_tag_it_is_worth_half(self):
        s = Scene()
        s.records["h_b"]["relationships"] = {"h_a": relation(-0.3, tags=["thief"])}
        self.assertTrue(s.runner.run("h_a", "apologise", {"target": "h_b"}).ok)
        self.assertAlmostEqual(self.close(s, "h_b", "h_a"), round(-0.3 + rules.apology_effect(-0.3, 0.5, True), 3))
        self.assertIn("thief", s.records["h_b"]["relationships"]["h_a"]["tags"])           # only restitution removes it

    def test_candidates_are_the_neighbours_that_hold_a_grudge(self):
        s = Scene()
        s.records["h_b"]["relationships"] = {"h_a": relation(-0.3)}
        names = {o.params["target"] for o in s.runner.aff.options("h_a") if o.verb == "apologise"}
        self.assertEqual(names, {"h_b"})


class Forgive(BondsCase):
    def test_the_grudge_moves_toward_zero_and_stops_there(self):
        s = Scene()
        s.records["h_a"]["relationships"] = {"h_b": relation(-0.4)}
        self.assertTrue(s.runner.run("h_a", "forgive", {"target": "h_b"}).ok)
        self.assertAlmostEqual(self.close(s, "h_a", "h_b"), -0.25)
        s.records["h_a"]["relationships"]["h_b"]["closeness"] = -0.1
        self.assertTrue(s.runner.run("h_a", "forgive", {"target": "h_b"}).ok)
        self.assertAlmostEqual(self.close(s, "h_a", "h_b"), 0.0)
        self.assertEqual(s.runner.run("h_a", "forgive", {"target": "h_b"}).code, "illegal:no_grievance")

    def test_no_proximity_needed_but_the_target_must_exist(self):
        s = Scene(extra_records={"h_far": {"relationships": {}}})
        s.records["h_a"]["relationships"] = {"h_far": relation(-0.4)}
        self.assertTrue(s.runner.run("h_a", "forgive", {"target": "h_far"}).ok)
        self.assertEqual(s.runner.run("h_a", "forgive", {"target": "nobody"}).code, "ungrounded_target")
        self.assertEqual(s.runner.run("h_a", "forgive", {"target": "h_a"}).code, "illegal:self_target")


class FlagOff(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop("EDEN_BONDS", None)
        self.addCleanup(patcher.stop)

    def test_not_wired_no_options_and_not_registered(self):
        s = Scene()
        for verb, params in (("befriend", {"target": "h_b"}), ("court", {"target": "h_b"}), ("apologise", {"target": "h_b"}), ("forgive", {"target": "h_b"})):
            self.assertEqual(s.runner.aff.legal("h_a", verb, params).reason, "not_wired", verb)
            self.assertNotIn(verb, resource_verbs.default_registry().actions)
        self.assertFalse([o for o in s.runner.aff.options("h_a") if o.verb in ("befriend", "court", "apologise", "forgive")])


if __name__ == "__main__":
    unittest.main()
