"""EDEN_PLACES: mark_place / remember_place / ask_directions on the synthetic Scene, the record shape, the re-base, the flag-off behaviour."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import copy
import os
import unittest
import unittest.mock

from driver_pin import pin_anchor
from systems.actions import rebase, resource_verbs
from systems.places import FIELD, MAX_NAME, MAX_PLACES, answer_directions, clean_name, enabled, remember
from test_actions_runner import Scene


class Pure(unittest.TestCase):
    def test_names_are_cleaned(self):
        self.assertEqual(clean_name("  the   old oak "), "the old oak")
        self.assertEqual(len(clean_name("x" * 100)), MAX_NAME)
        self.assertEqual(clean_name(""), "")
        self.assertEqual(clean_name(None), "")

    def test_memory_is_capped_and_forgets_the_oldest(self):
        record = {}
        for i in range(MAX_PLACES + 3):
            remember(record, f"p{i:02d}", i, i, 0, i, "mark")
        self.assertEqual(len(record[FIELD]), MAX_PLACES)
        self.assertNotIn("p00", record[FIELD])
        self.assertIn(f"p{MAX_PLACES + 2:02d}", record[FIELD])

    def test_directions_need_knowledge_and_trust(self):
        teller = {FIELD: {"well": {"target_place": {"x": 5.0, "y": 6.0}, "space": 0.0, "tick": 3, "source": "mark"}}, "relationships": {"asker": {"closeness": 0.0}}}
        asker = {}
        self.assertEqual(answer_directions(asker, teller, "asker", "mill", 10), {"ok": False, "reason": "refuse_unknown"})
        teller["relationships"]["asker"]["closeness"] = -0.5
        self.assertEqual(answer_directions(asker, teller, "asker", "well", 10)["reason"], "refuse_distrust")
        self.assertNotIn(FIELD, asker)
        teller["relationships"]["asker"]["closeness"] = 0.1
        self.assertTrue(answer_directions(asker, teller, "asker", "well", 10)["ok"])
        self.assertEqual(asker[FIELD]["well"]["target_place"], {"x": 5.0, "y": 6.0})
        self.assertEqual(asker[FIELD]["well"]["source"], "told")

    def test_flag_default_off(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDEN_PLACES", None)
            self.assertFalse(enabled())


class PlacesCase(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {"EDEN_PLACES": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)


class Marking(PlacesCase):
    def test_mark_place_stores_where_the_actor_stands(self):
        s = Scene()
        r = s.runner.run("h_a", "mark_place", {"name": "  home  field "}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        place = s.records["h_a"][FIELD]["home field"]
        self.assertEqual(place["target_place"], {"x": 10.0, "y": 10.0})
        self.assertEqual(place["source"], "mark")

    def test_an_empty_name_is_rejected(self):
        s = Scene()
        before = s.digest()
        self.assertEqual(s.runner.run("h_a", "mark_place", {"name": "   "}).code, "illegal:invalid_params")
        self.assertTrue(s.same(before, s.digest()))

    def test_remember_place_takes_only_what_is_perceived(self):
        s = Scene()
        r = s.runner.run("h_a", "remember_place", {"place": "v:well"})
        self.assertTrue(r.ok, r.code)
        self.assertEqual(s.records["h_a"][FIELD]["v:well"]["target_place"], {"x": 60.0, "y": 10.0})
        self.assertEqual(s.runner.run("h_a", "remember_place", {"place": "e_nowhere"}).code, "ungrounded_place")      # the runner grounds a place id before the predicate sees it

    def test_the_mask_offers_perceived_places_not_yet_known(self):
        s = Scene()
        s.runner.run("h_a", "remember_place", {"place": "v:well"})
        offered = {o.params["place"] for o in s.runner.aff.options("h_a") if o.verb == "remember_place"}
        self.assertIn("v:bed", offered)
        self.assertNotIn("v:well", offered)


class Asking(PlacesCase):
    def scene(self, closeness=0.1):
        s = Scene()
        s.records["h_b"][FIELD] = {"mill": {"target_place": {"x": 300.0, "y": 40.0}, "space": 0.0, "tick": 1, "source": "mark"}}
        s.records["h_b"]["relationships"] = {"h_a": {"closeness": closeness, "tags": [], "kind": "known"}}
        return s

    def test_a_neighbour_who_knows_the_place_tells_it(self):
        s = self.scene()
        r = s.runner.run("h_a", "ask_directions", {"target": "h_b", "name": "mill"}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual(s.records["h_a"][FIELD]["mill"]["target_place"], {"x": 300.0, "y": 40.0})
        self.assertEqual(s.records["h_a"][FIELD]["mill"]["source"], "told")
        self.assertGreater(s.records["h_a"]["relationships"]["h_b"]["closeness"], 0.0)

    def test_an_unknown_place_or_a_distrustful_neighbour_is_refused_by_the_asked(self):
        s = self.scene()
        r = s.runner.run("h_a", "ask_directions", {"target": "h_b", "name": "castle"})
        self.assertEqual((r.ok, r.ops[0]["ok"], r.ops[0]["reason"]), (True, False, "refuse_unknown"))          # the question was asked; the asked resident said no
        self.assertNotIn(FIELD, s.records["h_a"])
        s = self.scene(closeness=-0.6)
        r = s.runner.run("h_a", "ask_directions", {"target": "h_b", "name": "mill"})
        self.assertEqual((r.ops[0]["ok"], r.ops[0]["reason"]), (False, "refuse_distrust"))
        self.assertNotIn(FIELD, s.records["h_a"])

    def test_asking_for_a_place_already_known_is_not_needed(self):
        s = self.scene()
        s.runner.run("h_a", "ask_directions", {"target": "h_b", "name": "mill"})
        self.assertEqual(s.runner.run("h_a", "ask_directions", {"target": "h_b", "name": "mill"}).code, "illegal:not_needed")

    def test_far_and_dead_targets_cannot_be_asked(self):
        s = self.scene()
        self.assertFalse(s.runner.run("h_a", "ask_directions", {"target": "h_far", "name": "mill"}).ok)
        self.assertEqual(s.runner.run("h_a", "ask_directions", {"target": "h_dead", "name": "mill"}).code, "illegal:target_dead")


class Rebase(unittest.TestCase):
    def test_a_known_place_moves_with_the_window(self):
        record = {FIELD: {"well": {"target_place": {"x": 10.0, "y": 20.0}, "space": 0.0, "tick": 1, "source": "mark"}}}
        self.assertIn(FIELD, rebase.RECORD_FIELDS)
        moved = sum(rebase._walk(record.get(name), -3.0, 4.0) for name in rebase.RECORD_FIELDS)
        self.assertEqual(moved, 1)
        self.assertEqual(record[FIELD]["well"]["target_place"], {"x": 7.0, "y": 24.0})


class FlagOff(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop("EDEN_PLACES", None)
        self.addCleanup(patcher.stop)

    def test_not_wired_no_options_not_registered(self):
        s = Scene()
        before = copy.deepcopy(s.records)
        for verb, params in (("mark_place", {"name": "x"}), ("remember_place", {"place": "v:well"}), ("ask_directions", {"target": "h_b", "name": "x"})):
            self.assertEqual(s.runner.aff.legal("h_a", verb, params).reason, "not_wired", verb)
            self.assertNotIn(verb, resource_verbs.default_registry().actions)
        self.assertFalse([o for o in s.runner.aff.options("h_a") if o.verb in ("mark_place", "remember_place", "ask_directions")])
        self.assertEqual(s.records, before)


if __name__ == "__main__":
    unittest.main()
