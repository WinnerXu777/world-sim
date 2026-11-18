"""EDEN_MARKET: buy / sell / set_price through the real ActionRunner on the synthetic Scene (flag, legality rows, atomic coin + goods, conservation, prices)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import unittest
import unittest.mock

from driver_pin import pin_anchor
from systems.affordance import EntityFact
from systems.actions import market_verbs, resource_verbs
from systems.market import enabled, runtime

from test_actions_runner import Scene

STALL = "e_store"          # Scene's storage entity, 5 from h_a (interaction range 16)


class MarketScene(Scene):
    def __init__(self, *, stock=None, till=0, purse=10, **kw):
        super().__init__(**kw)
        self.world.items.add("h_a", "coin", purse)
        for kind, q in (stock if stock is not None else {"rations": 3, "crop_bundle": 1}).items():
            self.world.items.add(STALL, kind, q)
        if till:
            self.world.items.add(STALL, "coin", till)
        runtime.register_stall(self.services, STALL)
        self.services._entities.append(EntityFact("builder:stall", "storage", 17.0, 10.0, True, 16.0))     # a stall owned by h_a's household ("builder")
        runtime.register_stall(self.services, "builder:stall")
        self.book = runtime.of(self.services)

    def held(self, owner, kind):
        return self.world.items.quantity(owner, kind)

    def total(self, kind):
        return self.world.items.total(kind)


class MarketCase(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {"EDEN_MARKET": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)


class FlagOff(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop("EDEN_MARKET", None)
        self.addCleanup(patcher.stop)

    def test_default_off_and_no_verbs_or_options(self):
        self.assertFalse(enabled())
        s = MarketScene()
        for verb in ("buy", "sell", "set_price"):
            params = {"container": STALL, "item": "rations", "price": 2} if verb == "set_price" else {"container": STALL, "item": "rations", "qty": 1}
            self.assertEqual(s.runner.aff.legal("h_a", verb, params).reason, "not_wired", verb)
        self.assertFalse([o for o in s.runner.aff.options("h_a") if o.verb in ("buy", "sell", "set_price")])
        self.assertNotIn("buy", resource_verbs.default_registry().actions)

    def test_the_flag_adds_the_verbs_to_the_default_registry(self):
        with unittest.mock.patch.dict(os.environ, {"EDEN_MARKET": "1"}):
            self.assertEqual({"buy", "sell", "set_price"} - set(resource_verbs.default_registry().actions), set())
        self.assertEqual(set(market_verbs.MARKET_REGISTRY.actions), {"buy", "sell", "set_price"})


class Buy(MarketCase):
    def test_a_purchase_moves_coin_and_goods_atomically_and_conserves_both(self):
        s = MarketScene()
        price = s.book.ask(STALL, "rations")
        coin_total, rations_total = s.total("coin"), s.total("rations")
        r = s.runner.run("h_a", "buy", {"container": STALL, "item": "rations", "qty": 2}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual((s.held("h_a", "coin"), s.held(STALL, "coin")), (10 - 2 * price, 2 * price))
        self.assertEqual((s.held("h_a", "rations"), s.held(STALL, "rations")), (2 + 2, 1))
        self.assertEqual((s.total("coin"), s.total("rations")), (coin_total, rations_total))
        self.assertEqual([e.type for e in r.report.events], ["bought"])
        sale = s.book.stall(STALL).sales[-1]
        self.assertEqual((sale.item, sale.qty, sale.price, sale.kind, sale.who), ("rations", 2, price, "buy", "h_a"))
        self.assertEqual(s.book.stall(STALL).bought["rations"], 2)

    def test_refusals_have_stable_codes_and_change_nothing(self):
        s = MarketScene(purse=1)
        s.runner.run("h_a", "buy", {"container": STALL, "item": "rations", "qty": 1}, proposer="rules:test")      # a read may add empty keys to the store: compare after one
        before = s.digest()
        cases = [({"container": STALL, "item": "rations", "qty": 1}, "illegal:cannot_afford"),
                 ({"container": STALL, "item": "rations", "qty": 9}, "illegal:out_of_stock"),
                 ({"container": STALL, "item": "wood_bundle", "qty": 1}, "illegal:out_of_stock"),
                 ({"container": "e_tree", "item": "rations", "qty": 1}, "illegal:no_stall"),
                 ({"container": "nowhere", "item": "rations", "qty": 1}, "ungrounded_target"),
                 ({"container": STALL, "item": "coin", "qty": 1}, "illegal:invalid_params"),
                 ({"container": STALL, "item": "rations", "qty": 0}, "illegal:invalid_params")]
        for params, code in cases:
            r = s.runner.run("h_a", "buy", params, proposer="rules:test")
            self.assertFalse(r.ok, params)
            self.assertEqual(r.code, code, params)
        self.assertTrue(Scene.same(before, s.digest()))

    def test_a_far_stall_is_not_perceived(self):
        s = MarketScene()
        s.services._entities.append(EntityFact("far:market_1", "storage", 150.0, 10.0, True, 16.0))
        runtime.register_stall(s.services, "far:market_1")
        s.world.items.add("far:market_1", "rations", 5)
        r = s.runner.run("h_a", "buy", {"container": "far:market_1", "item": "rations", "qty": 1}, proposer="rules:test")
        self.assertFalse(r.ok)

    def test_the_id_convention_marks_a_stall_without_registration(self):
        s = MarketScene()
        s.services._entities.append(EntityFact("town:market_1", "storage", 14.0, 11.0, True, 16.0))
        s.world.items.add("town:market_1", "rations", 1)
        self.assertTrue(runtime.is_stall(s.services, "town:market_1"))
        self.assertTrue(s.runner.run("h_a", "buy", {"container": "town:market_1", "item": "rations", "qty": 1}, proposer="rules:test").ok)

    def test_a_full_pack_refuses(self):
        s = MarketScene(capacity=16, purse=11)                  # the pack holds 5 items already: 16 in all is full
        r = s.runner.run("h_a", "buy", {"container": STALL, "item": "rations", "qty": 1}, proposer="rules:test")
        self.assertFalse(r.ok)
        self.assertIn(r.code, ("illegal:no_room",))

    def test_candidates_list_only_what_the_buyer_can_pay(self):
        s = MarketScene(purse=s_price(2))
        options = [o for o in s.runner.aff.options("h_a") if o.verb == "buy"]
        items = {o.params["item"] for o in options}
        self.assertIn("rations", items)
        poor = MarketScene(purse=0)
        self.assertFalse([o for o in poor.runner.aff.options("h_a") if o.verb == "buy"])

    def test_a_dearer_price_book_costs_more(self):
        s = MarketScene(purse=40)
        base = s.book.ask(STALL, "rations")
        s.book.factor["rations"] = 3.0
        self.assertGreater(s.book.ask(STALL, "rations"), base)
        r = s.runner.run("h_a", "buy", {"container": STALL, "item": "rations", "qty": 1}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual(s.held("h_a", "coin"), 40 - s.book.stall(STALL).sales[-1].price)


def s_price(units: int) -> int:
    """A purse for ``units`` rations at the default price."""
    return units * runtime.of(MarketScene().services).ask(STALL, "rations")


class Sell(MarketCase):
    def test_a_sale_pays_the_bid_from_the_till(self):
        s = MarketScene(stock={"rations": 0}, till=20)
        bid = s.book.bid(STALL, "wood_bundle")
        r = s.runner.run("h_a", "sell", {"container": STALL, "item": "wood_bundle", "qty": 1}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual((s.held("h_a", "coin"), s.held(STALL, "coin")), (10 + bid, 20 - bid))
        self.assertEqual((s.held("h_a", "wood_bundle"), s.held(STALL, "wood_bundle")), (1, 1))
        self.assertEqual(s.book.stall(STALL).sold["wood_bundle"], 1)

    def test_refusals(self):
        s = MarketScene(stock={"rations": 0}, till=0)
        before = s.digest()
        self.assertEqual(s.runner.run("h_a", "sell", {"container": STALL, "item": "wood_bundle", "qty": 1}, proposer="rules:test").code, "illegal:till_empty")
        self.assertEqual(s.runner.run("h_a", "sell", {"container": STALL, "item": "sword", "qty": 1}, proposer="rules:test").code, "illegal:no_item")
        self.assertEqual(s.runner.run("h_a", "sell", {"container": STALL, "item": "coin", "qty": 1}, proposer="rules:test").code, "illegal:invalid_params")
        self.assertTrue(Scene.same(before, s.digest()))
        full = MarketScene(stock={"wood_bundle": 5}, till=50)
        self.assertEqual(full.runner.run("h_a", "sell", {"container": STALL, "item": "wood_bundle", "qty": 1}, proposer="rules:test").code, "illegal:not_wanted")

    def test_the_bid_is_never_above_the_ask_so_a_round_trip_cannot_make_coin(self):
        s = MarketScene(stock={"rations": 0}, till=50, purse=10)
        coin = s.total("coin")
        self.assertTrue(s.runner.run("h_a", "sell", {"container": STALL, "item": "rations", "qty": 1}, proposer="rules:test").ok)
        self.assertTrue(s.runner.run("h_a", "buy", {"container": STALL, "item": "rations", "qty": 1}, proposer="rules:test").ok)
        self.assertLessEqual(s.held("h_a", "coin"), 10)
        self.assertEqual(s.total("coin"), coin)


class SetPrice(MarketCase):
    OWN = "builder:stall"

    def test_only_the_household_sets_a_price_inside_the_bounds(self):
        s = MarketScene(roster=True)
        s.world.items.add(self.OWN, "rations", 2)
        lo, hi = s.book.bounds("rations")
        r = s.runner.run("h_a", "set_price", {"container": self.OWN, "item": "rations", "price": hi}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual(s.book.ask(self.OWN, "rations"), hi)
        self.assertEqual(s.runner.run("h_a", "set_price", {"container": self.OWN, "item": "rations", "price": hi + 1}, proposer="rules:test").code, "illegal:price_out_of_bounds")
        self.assertEqual(s.runner.run("h_a", "set_price", {"container": self.OWN, "item": "rations", "price": lo - 1 or 0}, proposer="rules:test").code[:8], "illegal:")
        self.assertEqual(s.runner.run("h_a", "set_price", {"container": STALL, "item": "rations", "price": lo}, proposer="rules:test").code, "illegal:not_owner")

    def test_the_new_price_is_what_the_next_buyer_pays(self):
        s = MarketScene(roster=True)
        s.world.items.add(self.OWN, "rations", 2)
        s.world.items.add("h_a", "coin", 40)
        lo, hi = s.book.bounds("rations")
        self.assertTrue(s.runner.run("h_a", "set_price", {"container": self.OWN, "item": "rations", "price": hi}, proposer="rules:test").ok)
        before = s.held("h_a", "coin")
        self.assertTrue(s.runner.run("h_a", "buy", {"container": self.OWN, "item": "rations", "qty": 1}, proposer="rules:test").ok)
        self.assertEqual(before - s.held("h_a", "coin"), hi)


if __name__ == "__main__":
    unittest.main()
