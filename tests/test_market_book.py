"""EDEN_MARKET: the pure part (prices, scarcity, daily update) with no engine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import unittest

from systems.market import book as mb
from systems.market.book import MarketBook

VALUES = {"rations": 1.8, "crop_bundle": 2.0, "coin": 1.0, "wood": 0.9, "gem": 30.0}


def make() -> MarketBook:
    return MarketBook(lambda kind: VALUES.get(kind, 1.0))


class Prices(unittest.TestCase):
    def test_ask_is_above_bid_and_both_are_whole_positive_coin(self):
        for value in (0.3, 0.9, 1.0, 1.8, 4.0, 30.0):
            for factor in (0.5, 1.0, 2.0, 3.0):
                ask, bid = mb.default_ask(value, factor), mb.default_bid(value, factor)
                self.assertGreaterEqual(bid, 1)
                self.assertGreaterEqual(ask, bid, (value, factor))
                self.assertIsInstance(ask, int)

    def test_prices_rise_with_the_factor(self):
        asks = [mb.default_ask(1.8, f) for f in (0.5, 1.0, 2.0, 3.0)]
        self.assertEqual(asks, sorted(asks))
        self.assertLess(asks[0], asks[-1])

    def test_a_keeper_price_overrides_the_default_ask_but_not_the_bid_ceiling(self):
        book = make()
        self.assertEqual(book.ask("t:market", "rations"), mb.default_ask(1.8, 1.0))
        book.set_ask("t:market", "rations", 9)
        self.assertEqual(book.ask("t:market", "rations"), 9)
        self.assertLessEqual(book.bid("t:market", "rations"), 9)
        book.set_ask("t:market", "rations", 1)
        self.assertEqual(book.bid("t:market", "rations"), 1)             # never above the ask: the stall cannot lose by buying and reselling

    def test_bounds_are_half_to_three_times_the_reference(self):
        lo, hi = mb.price_bounds(2.0, 1.0)
        self.assertEqual((lo, hi), (1, 6))
        lo, hi = mb.price_bounds(30.0, 1.0)
        self.assertEqual((lo, hi), (15, 90))
        lo, hi = mb.price_bounds(0.2, 1.0)
        self.assertEqual((lo, hi), (1, 3))
        for value in (0.2, 1.0, 7.0):
            lo, hi = mb.price_bounds(value, 2.0)
            self.assertTrue(1 <= lo <= hi)

    def test_stall_household_is_the_id_prefix(self):
        self.assertEqual(make().stall("neighbour:pantry").owner, "neighbour")
        self.assertEqual(make().stall("family_interior:stall").owner, "family")


class Scarcity(unittest.TestCase):
    def test_clamped_and_monotone_in_demand_and_supply(self):
        self.assertEqual(mb.scarcity(0, 0), 1.0)
        self.assertEqual(mb.scarcity(100, 0), mb.SCARCITY_MAX)
        self.assertEqual(mb.scarcity(0, 100), mb.SCARCITY_MIN)
        self.assertLess(mb.scarcity(1, 4), mb.scarcity(3, 4))
        self.assertGreater(mb.scarcity(3, 1), mb.scarcity(3, 4))

    def test_smoothing_moves_a_share_toward_today(self):
        self.assertAlmostEqual(mb.smooth(10, 0), 7.0)
        self.assertAlmostEqual(mb.smooth(0, 10), 3.0)


class DailyUpdate(unittest.TestCase):
    def sales(self, book, stall, item, units, tick=0):
        for _ in range(units):
            book.record_sale(tick, stall, item, 1, book.ask(stall, item), "buy", "h")

    def test_first_call_fixes_the_day_and_a_repeat_is_ignored(self):
        book = make()
        self.assertIsNone(book.daily_update(0))
        self.assertIsNone(book.daily_update(0))
        self.sales(book, "t:market", "rations", 4)
        self.assertIsNotNone(book.daily_update(1))
        self.assertIsNone(book.daily_update(1))

    def test_demand_without_supply_raises_the_price_over_the_days(self):
        book = make()
        book.daily_update(0)
        asks = []
        for day in range(1, 8):
            self.sales(book, "t:market", "rations", 5)
            book.daily_update(day, stock={})
            asks.append(book.ask("t:market", "rations"))
        self.assertEqual(asks, sorted(asks))
        self.assertGreater(asks[-1], asks[0])
        self.assertLessEqual(book.f("rations"), mb.SCARCITY_MAX)

    def test_unmet_demand_counts_like_a_sale(self):
        met, unmet = make(), make()
        for book, record in ((met, lambda b: self.sales(b, "t:market", "rations", 3)), (unmet, lambda b: b.record_unmet("t:market", "rations", 3))):
            book.daily_update(0)
            record(book)
            book.daily_update(1)
        self.assertEqual(met.f("rations"), unmet.f("rations"))
        self.assertGreater(unmet.f("rations"), 1.0)

    def test_stock_and_outside_supply_lower_the_price_and_a_blight_raises_it_again(self):
        book = make()
        book.daily_update(0)
        for day in range(1, 6):
            self.sales(book, "t:market", "rations", 2)
            book.daily_update(day, stock={"rations": 12}, outside_supply={"rations": 4.0})
        glut = book.f("rations")
        self.assertLess(glut, 1.0)
        for day in range(6, 14):
            self.sales(book, "t:market", "rations", 2)
            book.daily_update(day, stock={"rations": 0}, outside_supply={"rations": 0.0})            # the harvest failed
        self.assertGreater(book.f("rations"), glut)

    def test_a_demand_shock_moves_the_factor_like_real_demand(self):
        calm, panic = make(), make()
        panic.shock["rations"] = 3.0
        for book in (calm, panic):
            book.daily_update(0)
            for day in range(1, 5):
                self.sales(book, "t:market", "rations", 2)
                book.daily_update(day, stock={"rations": 3})
        self.assertGreater(panic.f("rations"), calm.f("rations"))

    def test_the_stall_wants_stock_for_two_days_of_its_own_sales(self):
        book = make()
        self.assertEqual(book.target("t:market", "rations"), mb.MIN_TARGET)
        book.daily_update(0)
        for day in range(1, 12):
            self.sales(book, "t:market", "rations", 8)
            book.daily_update(day)
        self.assertGreater(book.target("t:market", "rations"), mb.MIN_TARGET)

    def test_tallies_reset_each_day_and_the_ring_is_bounded(self):
        book = make()
        book.daily_update(0)
        self.sales(book, "t:market", "rations", 3)
        book.daily_update(1)
        self.assertEqual(sum(book.stall("t:market").bought.values()), 0)
        for n in range(mb.RING + 50):
            book.record_sale(n, "t:market", "wood", 1, 1, "sell", "h")
        self.assertEqual(len(book.stall("t:market").sales), mb.RING)

    def test_gouging_is_an_ask_far_above_the_reference(self):
        book = make()
        self.assertFalse(book.gouging("t:market", "rations"))
        book.set_ask("t:market", "rations", 3 * book.reference("rations"))
        self.assertTrue(book.gouging("t:market", "rations"))

    def test_same_inputs_same_factors(self):
        runs = []
        for _ in range(2):
            book = make()
            book.daily_update(0)
            for day in range(1, 6):
                self.sales(book, "t:market", "rations", day)
                book.record_unmet("t:market", "wood", day)
                book.daily_update(day, stock={"rations": day})
            runs.append(dict(book.factor))
        self.assertEqual(runs[0], runs[1])


if __name__ == "__main__":
    unittest.main()
