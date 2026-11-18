"""S-1 batch 2 (1008_actions.md 10.14): ``offer_trade`` / ``accept_trade``, ``steal_when_safe``, ``share_news`` / ``gossip`` on the synthetic Scene of
``test_actions_runner`` (effects, refusals, the ledger, the offer book). The Gate C table rows of these verbs are in ``test_actions_runner.GateCTests``;
roster-resident behaviour is in ``test_actions_roster.py`` (``Batch2Roster``)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_actions_runner import Scene, setrow  # noqa: E402
from systems.actions.offers import offers_of  # noqa: E402


def packs(s, *owners):
    return {o: {k: s.world.items.quantity(o, k) for k in ("rations", "iron_ingot", "wood_bundle", "fish_catch")} for o in owners}


class TradeTests(unittest.TestCase):
    def offer(self, s, **kw):
        args = {"target": "h_b", "give": "iron_ingot", "want": "rations", **kw}
        return s.runner.run("h_a", "offer_trade", args, proposer="tier1:rules")

    def test_a_fair_offer_is_answered_by_rules_and_swapped_atomically_through_accept_trade(self):
        s = Scene()
        before = packs(s, "h_a", "h_b")
        r = self.offer(s)
        self.assertTrue(r.ok, (r.code, r.detail))
        op = r.ops[0]
        self.assertEqual((op["kind"], op["answer"], op["accepted"]), ("trade_offer", "accept", True))
        after = packs(s, "h_a", "h_b")
        self.assertEqual((after["h_a"]["iron_ingot"], after["h_a"]["rations"]), (before["h_a"]["iron_ingot"] - 1, before["h_a"]["rations"] + 1))
        self.assertEqual((after["h_b"]["iron_ingot"], after["h_b"]["rations"]), (before["h_b"]["iron_ingot"] + 1, before["h_b"]["rations"] - 1))
        rows = [(e["verb"], e["actor"], e["proposer"], e["ok"]) for e in s.audit.entries]
        self.assertEqual(rows, [("accept_trade", "h_b", "rules:trade_response", True), ("offer_trade", "h_a", "tier1:rules", True)])
        self.assertEqual(len(offers_of(s.services)), 0)                                     # the offer is closed
        self.assertAlmostEqual(s.records["h_a"]["relationships"]["h_b"]["closeness"], 0.03)
        self.assertAlmostEqual(s.records["h_b"]["relationships"]["h_a"]["closeness"], 0.03)
        types = [e.type for e in s.world.events.events()]
        self.assertIn("traded", types)
        self.assertIn("trade_offered", types)

    def test_the_asked_resident_refuses_by_its_own_rules_and_nothing_moves(self):
        cases = {
            "refuse_unfair": (dict(give="wood_bundle"), None),                             # 1.5 for 3.0
            "refuse_no_item": (dict(want="fish_catch"), None),                              # h_b holds none
            "refuse_distrust": ({}, lambda s: s.records["h_b"].update({"relationships": {"h_a": {"closeness": -0.5, "tags": []}}})),
            "refuse_needs": ({}, lambda s: setrow(s.world, "h_b", hunger=70)),               # hungry: keeps its food against a non-edible
        }
        for answer, (kw, prepare) in cases.items():
            with self.subTest(answer):
                s = Scene()
                if prepare:
                    prepare(s)
                before = packs(s, "h_a", "h_b")
                r = self.offer(s, **kw)
                self.assertTrue(r.ok, (r.code, r.detail))                                     # the offer itself was legal
                self.assertEqual(r.ops[0]["answer"], answer)
                self.assertEqual(packs(s, "h_a", "h_b"), before)
                self.assertEqual([e["verb"] for e in s.audit.entries], ["offer_trade"])
                self.assertEqual(len(offers_of(s.services)), 0)

    def test_offer_legality_is_the_offerers_own_business(self):
        s = Scene()
        self.assertEqual(self.offer(s, give="fish_catch").code, "illegal:no_item")          # does not hold it
        self.assertEqual(self.offer(s, target="h_far").code, "illegal:no_target")           # not perceived
        self.assertEqual(self.offer(s, want="iron_ingot").code, "illegal:invalid_params")   # give == want
        self.assertEqual(self.offer(s, give_qty=0).code, "illegal:invalid_params")
        self.assertEqual(self.offer(s, want="unobtainium").code, "ungrounded_item")
        self.assertEqual(self.offer(s, target="h_dead").code, "illegal:target_dead")

    def test_only_the_addressed_resident_can_accept_and_an_offer_lapses(self):
        s = Scene()
        book = offers_of(s.services)
        offer_id = book.open("h_a", "h_b", "iron_ingot", 1, "rations", 1, 0)
        self.assertEqual(s.runner.run("h_smith", "accept_trade", {"offer": offer_id}).code, "illegal:not_addressed")
        self.assertEqual(s.runner.run("h_b", "accept_trade", {"offer": "offer_99999"}).code, "illegal:no_offer")
        s.world._clock.tick = 500
        self.assertEqual(s.runner.run("h_b", "accept_trade", {"offer": offer_id}).code, "illegal:no_offer")      # lapsed after 60 ticks
        s.world._clock.tick = 5
        r = s.runner.run("h_b", "accept_trade", {"offer": offer_id})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(s.runner.run("h_b", "accept_trade", {"offer": offer_id}).code, "illegal:no_offer")      # once

    def test_accept_rechecks_both_packs(self):
        s = Scene()
        offer_id = offers_of(s.services).open("h_a", "h_b", "iron_ingot", 1, "rations", 1, 0)
        s.world.items.remove("h_a", "iron_ingot", 1)                                       # the offerer spent it meanwhile
        self.assertEqual(s.runner.run("h_b", "accept_trade", {"offer": offer_id}).code, "illegal:no_item")


class StealTests(unittest.TestCase):
    def steal(self, s, proposer="rules", confidence=None, **kw):
        return s.runner.run("h_a", "steal_when_safe", {"item": "rations", **kw}, proposer=proposer, confidence=confidence)

    def test_a_witness_within_help_range_makes_it_unsafe(self):
        s = Scene()
        before = s.digest()
        r = self.steal(s, target="h_b")                                                      # h_smith stands 4 away
        self.assertEqual((r.ok, r.code, r.detail.get("by")), (False, "illegal:watched", "h_smith"))
        self.assertTrue(Scene.same(before, s.digest()))

    def test_unwatched_theft_from_a_resident_moves_the_item_and_writes_a_private_theft_event(self):
        s = Scene()
        setrow(s.world, "h_smith", x=210, y=10)
        r = self.steal(s, target="h_b")
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual((s.world.items.quantity("h_a", "rations"), s.world.items.quantity("h_b", "rations")), (3, 0))
        theft = [e for e in s.world.events.events() if e.type == "theft"]
        self.assertEqual(len(theft), 1)
        self.assertEqual((theft[0].actors, theft[0].visibility, set(theft[0].witnesses)), (("h_a", "h_b"), "private", {"h_a", "h_b"}))
        self.assertEqual(theft[0].payload["item"], "rations")

    def test_the_resident_must_hold_the_item_and_the_world_says_so(self):
        s = Scene()
        setrow(s.world, "h_smith", x=210, y=10)
        before = packs(s, "h_a", "h_b")
        r = self.steal(s, target="h_b", item="iron_ingot")
        self.assertEqual((r.ok, r.code), (False, "refused:no_item"))
        self.assertEqual(packs(s, "h_a", "h_b"), before)
        self.assertEqual([e.type for e in s.world.events.events() if e.type == "theft"], [])

    def test_from_an_open_container(self):
        s = Scene(inv={"e_store": {"rations": 3}})
        setrow(s.world, "h_smith", x=210, y=10)
        setrow(s.world, "h_b", x=210, y=40)
        r = self.steal(s, container="e_store", qty=2)
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual((s.world.items.quantity("e_store", "rations"), s.world.items.quantity("h_a", "rations")), (1, 4))
        self.assertEqual(self.steal(s, container="e_store", qty=5).code, "illegal:no_item")

    def test_exactly_one_of_target_and_container(self):
        s = Scene()
        self.assertEqual(self.steal(s).code, "illegal:invalid_params")
        self.assertEqual(self.steal(s, target="h_b", container="e_store").code, "illegal:invalid_params")

    def test_destructive_the_risk_gate_applies(self):
        s = Scene()
        setrow(s.world, "h_smith", x=210, y=10)
        before = s.digest()
        gated = self.steal(s, proposer="tier1:rules", target="h_b")
        self.assertEqual(gated.code, "risk_gated")
        self.assertTrue(Scene.same(before, s.digest()))
        self.assertTrue(self.steal(s, proposer="model", confidence=0.9, target="h_b").ok)


class NewsTests(unittest.TestCase):
    def scene(self):
        s = Scene()
        s.records["h_a"]["relationships"]["h_smith"] = {"kind": "known", "closeness": 0.4, "tags": []}
        s.world.events.emit("quarrel", actors=("h_smith", "h_far"), place=(14.0, 10.0), witnesses=("h_a", "h_smith", "h_far"))
        return s

    def test_share_news_makes_the_listener_a_witness_of_the_same_event_and_remembers_it(self):
        s = self.scene()
        before_events = len(s.world.events.events())
        r = s.runner.run("h_a", "share_news", {"target": "h_b", "event": "ev_000001"})
        self.assertTrue(r.ok, (r.code, r.detail))
        found = s.world.events.get("ev_000001")
        self.assertEqual(set(found.witnesses), {"h_a", "h_b"})
        self.assertEqual(len(s.world.events.events()), before_events + 1)                   # only the "shared_news" event is new
        self.assertEqual(s.world.events.events()[-1].type, "shared_news")
        note = s.records["h_b"]["memory"]["recent_events"][-1]
        self.assertEqual((note["kind"], note["other_human_id"], note["about_event"]), ("heard_news", "h_a", "ev_000001"))
        self.assertAlmostEqual(s.records["h_a"]["relationships"]["h_b"]["closeness"], 0.02)
        again = s.runner.run("h_a", "share_news", {"target": "h_b", "event": "ev_000001"})
        self.assertEqual(again.code, "illegal:already_knows")

    def test_only_what_the_teller_witnessed_can_be_told(self):
        s = self.scene()
        self.assertEqual(s.runner.run("h_b", "share_news", {"target": "h_a", "event": "ev_000001"}).code, "illegal:not_witnessed")
        self.assertEqual(s.runner.run("h_a", "share_news", {"target": "h_b", "event": "ev_999999"}).code, "ungrounded_event")
        self.assertEqual(s.runner.run("h_a", "share_news", {"target": "h_far", "event": "ev_000001"}).code, "illegal:no_target")

    def test_gossip_tells_the_latest_event_about_a_person_and_moves_the_listeners_opinion(self):
        s = self.scene()
        r = s.runner.run("h_a", "gossip", {"target": "h_b", "about": "h_smith"})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertIn("h_b", s.world.events.get("ev_000002").witnesses)
        self.assertEqual(s.world.events.events()[-1].type, "gossiped")
        self.assertAlmostEqual(s.records["h_b"]["relationships"]["h_smith"]["closeness"], 0.05)      # 0.4 x 0.5, capped at 0.05
        self.assertEqual(s.runner.run("h_a", "gossip", {"target": "h_b", "about": "h_smith"}).code, "illegal:nothing_to_tell")
        self.assertEqual(s.runner.run("h_a", "gossip", {"target": "h_b", "about": "h_nope"}).code, "ungrounded_target")
        self.assertEqual(s.runner.run("h_a", "gossip", {"target": "h_b", "about": "h_a"}).code, "illegal:invalid_params")

    def test_options_list_what_a_resident_could_tell(self):
        s = self.scene()
        options = s.runner.aff.options("h_a", verbs=("share_news", "gossip"))
        self.assertTrue(options)
        self.assertIn(("share_news", "ev_000001"), [(o.verb, o.params.get("event")) for o in options])
        self.assertIn(("gossip", "h_smith"), [(o.verb, o.params.get("about")) for o in options])


if __name__ == "__main__":
    unittest.main()
