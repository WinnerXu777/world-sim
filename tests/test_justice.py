"""EDEN_JUSTICE: the law and the docket (pure), report_theft / levy_damages through the ActionRunner on the synthetic Scene."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import unittest
import unittest.mock

from driver_pin import pin_anchor
from systems.affordance import config as aff
from systems.actions import resource_verbs
from systems.actions.offers import item_value
from systems.justice import docket as dk, enabled, law
from systems.justice import runtime as justice_runtime
from test_actions_runner import Scene

VALUES = {"rations": 3.0, "coin": 1.0, "crop_bundle": 2.0, "wood_bundle": 1.0}


class Law(unittest.TestCase):
    def test_who_holds_authority(self):
        self.assertTrue(law.is_authority({"occupation": {"kind": "guard"}}))
        self.assertTrue(law.is_authority({"occupation": {"kind": "elder"}}))
        self.assertTrue(law.is_authority({"occupation": {"kind": "farmer"}, "roster": {"authority": True}}))
        self.assertFalse(law.is_authority({"occupation": {"kind": "smith"}}))
        self.assertFalse(law.is_authority({}))

    def test_damages_are_half_again(self):
        self.assertAlmostEqual(law.damages(6.0), 9.0)

    def test_the_levy_takes_the_stolen_item_then_coin_and_leaves_one_unit_of_food(self):
        value = lambda k: VALUES.get(k, 1.0)           # noqa: E731
        taken = law.levy({"rations": 3, "coin": 5}, "rations", 9.0, value, aff.EDIBLE_ITEMS)
        self.assertEqual(taken, [("rations", 2), ("coin", 3)])
        self.assertEqual(law.levy({"rations": 1}, "rations", 9.0, value, aff.EDIBLE_ITEMS), [])              # the last food stays
        self.assertEqual(law.levy({"rations": 1, "coin": 2}, "rations", 9.0, value, aff.EDIBLE_ITEMS), [("coin", 2)])
        self.assertEqual(law.levy({"coin": 9, "wood_bundle": 4}, "rations", 5.0, value, aff.EDIBLE_ITEMS), [("coin", 5)])
        self.assertEqual(law.levy({"crop_bundle": 3, "rations": 1}, "rations", 4.0, value, aff.EDIBLE_ITEMS), [("rations", 1), ("crop_bundle", 1)])


class Docket(unittest.TestCase):
    def test_open_close_and_lapse(self):
        book = dk.Docket()
        case = book.open("t", "v", "a", "v", "rations", 2, 6.0, 100, 2400)
        self.assertEqual(case.expires, 100 + dk.CASE_TTL_DAYS * 2400)
        self.assertIs(book.against("t", "v"), case)
        self.assertIsNone(book.against("t", "other"))
        self.assertIs(book.for_authority("a", "t", 200), case)
        self.assertIsNone(book.for_authority("b", "t"))
        self.assertIs(book.close(case.id, "paid", 300), case)
        self.assertIsNone(book.close(case.id, "paid", 301))
        self.assertIsNone(book.against("t"))
        second = book.open("t", "v", "a", "v", "rations", 1, 3.0, 400, 2400)
        self.assertEqual(book.lapse(second.expires - 1), [])
        self.assertEqual(book.lapse(second.expires), [second])
        self.assertEqual((second.status, second.outcome), ("lapsed", "lapsed"))

    def test_flag_default_off(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDEN_JUSTICE", None)
            self.assertFalse(enabled())


class JusticeScene(Scene):
    """h_a (the victim) holds h_b (the thief) as a thief; h_smith is the guard standing by both."""

    def __init__(self, thief_pack=None, closeness=0.2, grievance=True, authority="guard", **kw):
        super().__init__(inv={"h_b": thief_pack if thief_pack is not None else {"rations": 3, "coin": 5}}, **kw)
        self.records["h_smith"]["occupation"] = {"kind": authority}
        self.records["h_smith"]["relationships"] = {"h_a": {"closeness": closeness, "tags": [], "kind": "known"}}
        self.records["h_a"]["relationships"] = {"h_b": {"closeness": -0.4, "tags": ["thief"] if grievance else [], "kind": "known"}}
        self.records["h_b"]["relationships"] = {}
        self.docket = justice_runtime.of(self.services)

    def held(self, owner, kind):
        return self.world.items.quantity(owner, kind)

    def report(self, target="h_smith", **kw):
        params = {"target": target, "about": "h_b", "item": "rations", "qty": 2, "victim": "h_a", **kw}
        return self.runner.run("h_a", "report_theft", params, proposer="rules:test")

    def levy(self):
        return self.runner.run("h_smith", "levy_damages", {"target": "h_b"}, proposer="rules:test")


class JusticeCase(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {"EDEN_JUSTICE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)


class FlagOff(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop("EDEN_JUSTICE", None)
        self.addCleanup(patcher.stop)

    def test_not_wired_and_no_options(self):
        s = JusticeScene()
        self.assertEqual(s.runner.aff.legal("h_a", "report_theft", {"target": "h_smith", "about": "h_b", "item": "rations", "qty": 1}).reason, "not_wired")
        self.assertEqual(s.runner.aff.legal("h_smith", "levy_damages", {"target": "h_b"}).reason, "not_wired")
        self.assertFalse([o for o in s.runner.aff.options("h_smith") if o.verb in ("report_theft", "levy_damages")])
        self.assertNotIn("report_theft", resource_verbs.default_registry().actions)


class Report(JusticeCase):
    def test_the_authority_accepts_and_a_case_is_opened(self):
        s = JusticeScene()
        r = s.report()
        self.assertTrue(r.ok, r.code)
        self.assertTrue(r.ops[0].get("opened"), r.ops)
        case = s.docket.against("h_b", "h_a")
        self.assertEqual((case.authority, case.reporter, case.item, case.qty), ("h_smith", "h_a", "rations", 2))
        self.assertAlmostEqual(case.value, item_value("rations") * 2)

    def test_the_authoritys_rules(self):
        cases = [(dict(authority="smith"), "refuse_not_authority"), (dict(closeness=-0.5), "refuse_distrust")]
        for kwargs, answer in cases:
            s = JusticeScene(**kwargs)
            r = s.report()
            self.assertTrue(r.ok, (kwargs, r.code))
            self.assertEqual(r.ops[0]["answer"], answer, kwargs)
            self.assertIsNone(s.docket.against("h_b"), kwargs)
        s = JusticeScene()
        self.assertTrue(s.report().ops[0]["opened"])
        self.assertEqual(s.report().ops[0]["answer"], "refuse_known_case")

    def test_a_resident_reports_only_someone_it_holds_as_a_thief(self):
        s = JusticeScene(grievance=False)
        self.assertEqual(s.report().code, "illegal:no_grievance")
        self.assertEqual(JusticeScene().report(about="h_a").code, "illegal:invalid_params")


class Levy(JusticeCase):
    def opened(self, **kw):
        s = JusticeScene(**kw)
        self.assertTrue(s.report().ops[0]["opened"])
        return s

    def test_damages_move_from_the_thief_to_the_victim_and_the_case_closes(self):
        s = self.opened()
        total = {k: s.world.items.total(k) for k in ("rations", "coin")}
        self.assertTrue([o for o in s.runner.aff.options("h_smith") if o.verb == "levy_damages"])
        r = s.levy()
        self.assertTrue(r.ok, r.code)
        case = s.docket.cases["case_00001"]
        self.assertEqual((case.status, case.outcome), ("closed", "paid"))
        self.assertEqual((s.held("h_b", "rations"), s.held("h_b", "coin")), (1, 2))              # the thief keeps its last food
        self.assertEqual((s.held("h_a", "rations"), s.held("h_a", "coin")), (2 + 2, 0 + 3))
        self.assertEqual({k: s.world.items.total(k) for k in total}, total)
        self.assertGreater(s.records["h_a"]["relationships"]["h_b"]["closeness"], -0.4)
        self.assertLess(s.records["h_b"]["relationships"]["h_smith"]["closeness"], 0.0)
        self.assertEqual(s.levy().code, "illegal:no_case")                                       # once

    def test_a_poor_thief_pays_what_it_can(self):
        s = self.opened(thief_pack={"rations": 1, "coin": 2})
        self.assertTrue(s.levy().ok)
        self.assertEqual(s.docket.cases["case_00001"].outcome, "part_paid")
        self.assertEqual((s.held("h_b", "rations"), s.held("h_b", "coin")), (1, 0))

    def test_a_thief_with_nothing_to_spare_is_not_stripped_of_its_last_food(self):
        s = self.opened(thief_pack={"rations": 1})
        self.assertTrue(s.levy().ok)
        self.assertEqual(s.docket.cases["case_00001"].outcome, "nothing_to_levy")
        self.assertEqual(s.held("h_b", "rations"), 1)

    def test_only_an_authority_with_a_case_can_levy(self):
        s = self.opened()
        self.assertEqual(s.runner.run("h_a", "levy_damages", {"target": "h_b"}, proposer="rules:test").code, "illegal:not_authority")
        s2 = JusticeScene()
        self.assertEqual(s2.levy().code, "illegal:no_case")

    def test_an_expired_case_cannot_be_levied(self):
        s = self.opened()
        case = s.docket.cases["case_00001"]
        s.world.clock.advance(case.expires - s.world.clock.tick)
        self.assertEqual(s.levy().code, "illegal:no_case")


if __name__ == "__main__":
    unittest.main()
