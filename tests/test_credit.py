"""EDEN_CREDIT: the loan book (pure), borrow / lend / pay_debt through the ActionRunner on the synthetic Scene, and the daily pass (overdue, default, repayment) on a real engine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import random
import unittest
import unittest.mock

import torch

from driver_pin import pin_anchor
from systems.credit import book as cb, enabled
from systems.credit import runtime as credit_runtime
from systems.actions import credit_day, credit_verbs, resource_verbs
from test_actions_runner import Scene

VALUES = {"rations": 1.8, "coin": 1.0, "crop_bundle": 2.0}


def make_book():
    return cb.LoanBook(lambda kind: VALUES.get(kind, 1.0))


class Book(unittest.TestCase):
    def test_a_friend_is_lent_at_par_and_anyone_else_a_quarter_over(self):
        self.assertAlmostEqual(cb.owed_value(1.8, 2, 0.5), 3.6)
        self.assertAlmostEqual(cb.owed_value(1.8, 2, 0.1), 4.5)

    def test_payments_in_any_item_clear_the_value_and_close_the_loan(self):
        book = make_book()
        loan = book.open("lender", "borrower", "rations", 2, 0.1, 100, 2400)
        self.assertEqual((loan.owed, loan.due), (4.5, 100 + 2400))
        self.assertIs(book.between("borrower", "lender"), loan)
        book.pay(loan.id, "coin", 2, 200)
        self.assertEqual((loan.status, loan.owed), ("open", 2.5))
        self.assertEqual(book.units_needed(loan, "coin"), 3)
        self.assertEqual(book.units_needed(loan, "rations"), 2)
        book.pay(loan.id, "rations", 2, 300)
        self.assertEqual(loan.status, "repaid")
        self.assertIsNone(book.between("borrower", "lender"))
        self.assertEqual(book.counts["repaid"], 1)
        self.assertIsNone(book.pay(loan.id, "coin", 1, 400))                 # a closed loan takes no payment

    def test_overdue_then_default_after_the_grace_period(self):
        book = make_book()
        loan = book.open("l", "b", "rations", 1, 0.5, 0, 1000)
        self.assertEqual(book.overdue(999, 1000), ([], []))
        late, gone = book.overdue(1000, 1000)
        self.assertEqual((late, gone), ([loan], []))
        loan.noted_overdue = True
        self.assertEqual(book.overdue(1500, 1000), ([], []))
        late, gone = book.overdue(2000, 1000)
        self.assertEqual(gone, [loan])
        book.default(loan, 2000)
        self.assertTrue(book.defaulted("b", "l"))
        self.assertEqual(book.open_of("b"), [])

    def test_flag_default_off(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDEN_CREDIT", None)
            self.assertFalse(enabled())


class CreditScene(Scene):
    """h_a (builder, hungry) asks h_b (gatherer, well stocked) who knows h_a at the given closeness."""

    def __init__(self, closeness=0.3, tags=(), lender_stock=4, **kw):
        super().__init__(inv={"h_b": {"rations": lender_stock, "coin": 5}}, **kw)
        self.records["h_b"]["relationships"] = {"h_a": {"closeness": closeness, "tags": list(tags), "kind": "known"}}
        self.records["h_a"]["relationships"] = {"h_b": {"closeness": closeness, "tags": [], "kind": "known"}}
        self.book = credit_runtime.of(self.services)

    def held(self, owner, kind):
        return self.world.items.quantity(owner, kind)


class CreditCase(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {"EDEN_CREDIT": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)


class FlagOff(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop("EDEN_CREDIT", None)
        self.addCleanup(patcher.stop)

    def test_not_wired_and_no_options(self):
        s = CreditScene()
        for verb, params in (("borrow_item", {"target": "h_b", "item": "", "qty": 1}), ("lend_item", {"target": "h_b", "item": "rations", "qty": 1}),
                             ("pay_debt", {"target": "h_b", "item": "coin", "qty": 1})):
            self.assertEqual(s.runner.aff.legal("h_a", verb, params).reason, "not_wired", verb)
        self.assertFalse([o for o in s.runner.aff.options("h_a") if o.verb in ("borrow_item", "lend_item", "pay_debt")])
        self.assertNotIn("borrow_item", resource_verbs.default_registry().actions)


class Borrow(CreditCase):
    def test_a_friend_lends_at_par_and_the_loan_is_recorded(self):
        s = CreditScene(closeness=0.5)
        r = s.runner.run("h_a", "borrow_item", {"target": "h_b", "item": "", "qty": 2}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertTrue(r.ops[0].get("lent"), r.ops)
        self.assertEqual((s.held("h_a", "rations"), s.held("h_b", "rations")), (2 + 2, 4 - 2))
        loan = s.book.between("h_a", "h_b")
        self.assertEqual((loan.item, loan.qty), ("rations", 2))
        self.assertAlmostEqual(loan.owed, cb.owed_value(s.book.value("rations"), 2, 0.5))
        self.assertGreater(s.records["h_a"]["relationships"]["h_b"]["closeness"], 0.5)

    def test_a_less_close_neighbour_owes_interest(self):
        s = CreditScene(closeness=0.1)
        self.assertTrue(s.runner.run("h_a", "borrow_item", {"target": "h_b", "item": "rations", "qty": 1}, proposer="rules:test").ops[0].get("lent"))
        self.assertAlmostEqual(s.book.between("h_a", "h_b").owed, cb.owed_value(s.book.value("rations"), 1, 0.1))
        self.assertGreater(s.book.between("h_a", "h_b").owed, s.book.value("rations"))

    def test_the_lenders_rules(self):
        cases = [(dict(closeness=0.0), "refuse_stranger"), (dict(closeness=-0.5), "refuse_distrust"), (dict(closeness=0.5, tags=["defaulter"]), "refuse_defaulter"),
                 (dict(closeness=0.5, lender_stock=1), "refuse_no_item"), (dict(closeness=0.5, tags=["rival"]), "refuse_distrust")]
        for kwargs, answer in cases:
            s = CreditScene(**kwargs)
            r = s.runner.run("h_a", "borrow_item", {"target": "h_b", "item": "", "qty": 1}, proposer="rules:test")
            self.assertTrue(r.ok, (kwargs, r.code))
            self.assertEqual(r.ops[0]["answer"], answer, kwargs)
            self.assertFalse(r.ops[0].get("lent"), kwargs)
            self.assertIsNone(s.book.between("h_a", "h_b"), kwargs)

    def test_a_second_loan_is_refused_by_the_predicate_and_by_the_lender(self):
        s = CreditScene(closeness=0.5)
        self.assertTrue(s.runner.run("h_a", "borrow_item", {"target": "h_b", "item": "", "qty": 1}, proposer="rules:test").ops[0].get("lent"))
        again = s.runner.run("h_a", "borrow_item", {"target": "h_b", "item": "", "qty": 1}, proposer="rules:test")
        self.assertEqual(again.code, "illegal:already_indebted")
        self.assertFalse([o for o in s.runner.aff.options("h_a") if o.verb == "borrow_item"])
        direct = s.runner.run("h_b", "lend_item", {"target": "h_a", "item": "rations", "qty": 1}, proposer="rules:test")
        self.assertEqual(direct.code, "illegal:already_indebted")

    def test_conservation(self):
        s = CreditScene(closeness=0.5)
        total = {k: s.world.items.total(k) for k in ("rations", "coin")}
        s.runner.run("h_a", "borrow_item", {"target": "h_b", "item": "", "qty": 2}, proposer="rules:test")
        self.assertEqual({k: s.world.items.total(k) for k in total}, total)


class PayDebt(CreditCase):
    def borrowed(self, closeness=0.1):
        s = CreditScene(closeness=closeness)
        self.assertTrue(s.runner.run("h_a", "borrow_item", {"target": "h_b", "item": "rations", "qty": 1}, proposer="rules:test").ops[0].get("lent"))
        return s

    def test_paying_in_kind_closes_the_loan_and_warms_the_lender(self):
        s = self.borrowed()
        loan = s.book.between("h_a", "h_b")
        need = s.book.units_needed(loan, "rations")
        before = s.records["h_b"]["relationships"]["h_a"]["closeness"]
        r = s.runner.run("h_a", "pay_debt", {"target": "h_b", "item": "rations", "qty": need}, proposer="rules:test")
        self.assertTrue(r.ok, r.code)
        self.assertEqual(loan.status, "repaid")
        self.assertIsNone(s.book.between("h_a", "h_b"))
        self.assertGreater(s.records["h_b"]["relationships"]["h_a"]["closeness"], before)

    def test_a_part_payment_in_coin_leaves_the_rest_owed(self):
        s = self.borrowed()
        s.world.items.add("h_a", "coin", 5)
        loan = s.book.between("h_a", "h_b")
        owed = loan.owed
        self.assertTrue(s.runner.run("h_a", "pay_debt", {"target": "h_b", "item": "coin", "qty": 1}, proposer="rules:test").ok)
        self.assertEqual((loan.status, round(owed - loan.owed, 6)), ("open", 1.0))
        options = [o for o in s.runner.aff.options("h_a") if o.verb == "pay_debt"]
        self.assertTrue(options)
        self.assertEqual(options[0].params["target"], "h_b")

    def test_refusals(self):
        s = CreditScene(closeness=0.5)
        self.assertEqual(s.runner.run("h_a", "pay_debt", {"target": "h_b", "item": "coin", "qty": 1}, proposer="rules:test").code, "illegal:no_debt")
        s2 = self.borrowed()
        self.assertEqual(s2.runner.run("h_a", "pay_debt", {"target": "h_b", "item": "crop_bundle", "qty": 1}, proposer="rules:test").code, "illegal:no_item")
        self.assertEqual(s2.runner.run("h_a", "pay_debt", {"target": "h_b", "item": "", "qty": 1}, proposer="rules:test").code, "illegal:invalid_params")


if __name__ == "__main__":
    unittest.main()
