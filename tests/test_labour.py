"""EDEN_LABOUR: the job book (pure) and work_for / collect_wage through the ActionRunner on the synthetic Scene."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import unittest
import unittest.mock

from driver_pin import pin_anchor
from systems.labour import book as lb, enabled
from systems.labour import runtime as labour_runtime
from systems.actions import resource_verbs
from systems.actions.offers import item_value
from test_actions_runner import Scene

VALUES = {"rations": 1.8, "coin": 1.0, "crop_bundle": 2.0}


def make_book():
    return lb.JobBook(lambda kind: VALUES.get(kind, 1.0))


class Book(unittest.TestCase):
    def test_wage_units_cover_the_wage_value(self):
        self.assertEqual(lb.wage_units(1.8), 2)
        self.assertEqual(lb.wage_units(1.0), 2)
        self.assertEqual(lb.wage_units(5.0), 1)

    def test_hire_pay_and_one_shift_at_a_time(self):
        book = make_book()
        job = book.hire("e", "w", "rations", 2, 100)
        self.assertEqual((job.ready_at, job.expires), (100 + lb.WORK_TICKS, 100 + lb.WORK_TICKS + lb.CLAIM_TTL))
        self.assertIs(book.of_worker("w", 150), job)
        self.assertIs(book.between("w", "e", 150), job)
        self.assertIsNone(book.between("w", "other", 150))
        self.assertEqual(book.staff("e", 150), 1)
        self.assertIs(book.pay(job.id, 400), job)
        self.assertIsNone(book.of_worker("w", 400))
        self.assertIsNone(book.pay(job.id, 401))                            # paid once
        self.assertEqual((book.counts["hired"], book.counts["paid"]), (1, 1))

    def test_an_unclaimed_shift_lapses(self):
        book = make_book()
        job = book.hire("e", "w", "coin", 2, 0)
        self.assertEqual(book.lapse(job.expires - 1), [])
        self.assertEqual(book.lapse(job.expires), [job])
        self.assertEqual(job.status, "lapsed")
        self.assertIsNone(book.of_worker("w"))

    def test_flag_default_off(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDEN_LABOUR", None)
            self.assertFalse(enabled())


class LabourScene(Scene):
    """h_a (builder) asks h_b (gatherer, with rations to spare) for a shift."""

    def __init__(self, closeness=0.2, tags=(), stock=4, coin=5, **kw):
        super().__init__(inv={"h_b": {"rations": stock, "coin": coin}}, **kw)
        self.records["h_b"]["relationships"] = {"h_a": {"closeness": closeness, "tags": list(tags), "kind": "known"}}
        self.records["h_a"]["relationships"] = {"h_b": {"closeness": closeness, "tags": [], "kind": "known"}}
        self.book = labour_runtime.of(self.services)

    def held(self, owner, kind):
        return self.world.items.quantity(owner, kind)

    def shift(self):
        return self.runner.run("h_a", "work_for", {"target": "h_b"}, proposer="rules:test")

    def collect(self, tick):
        """Collect the wage with the world clock at ``tick``."""
        self.world.clock.advance(tick - self.world.clock.tick)
        return self.runner.run("h_a", "collect_wage", {"target": "h_b"}, proposer="rules:test")


class LabourCase(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {"EDEN_LABOUR": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)


class FlagOff(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = unittest.mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop("EDEN_LABOUR", None)
        self.addCleanup(patcher.stop)

    def test_not_wired_and_no_options(self):
        s = LabourScene()
        for verb in ("work_for", "collect_wage"):
            self.assertEqual(s.runner.aff.legal("h_a", verb, {"target": "h_b"}).reason, "not_wired", verb)
        self.assertFalse([o for o in s.runner.aff.options("h_a") if o.verb in ("work_for", "collect_wage")])
        self.assertNotIn("work_for", resource_verbs.default_registry().actions)


class Work(LabourCase):
    def test_a_shift_is_hired_then_paid_when_done(self):
        s = LabourScene()
        r = s.shift()
        self.assertTrue(r.ok, r.code)
        self.assertTrue(r.ops[0].get("hired"), r.ops)
        job = s.book.between("h_a", "h_b")
        wage = lb.wage_units(item_value("rations"))
        self.assertEqual((job.item, job.qty), ("rations", wage))
        self.assertEqual((s.held("h_a", "rations"), s.held("h_b", "rations")), (2, 4))   # nothing moves yet
        early = s.collect(job.ready_at - 1)
        self.assertEqual(early.code, "illegal:shift_not_done")
        s.world.clock.advance(job.ready_at - s.world.clock.tick)
        self.assertTrue(any(o.verb == "collect_wage" for o in s.runner.aff.options("h_a")))
        total = {k: s.world.items.total(k) for k in ("rations", "coin")}
        paid = s.collect(job.ready_at)
        self.assertTrue(paid.ok, paid.code)
        self.assertEqual((s.held("h_a", "rations"), s.held("h_b", "rations")), (2 + wage, 4 - wage))
        self.assertEqual({k: s.world.items.total(k) for k in total}, total)
        self.assertEqual(job.status, "paid")
        self.assertGreater(s.records["h_b"]["relationships"]["h_a"]["closeness"], 0.2)
        again = s.collect(job.ready_at + 1)
        self.assertEqual(again.code, "illegal:no_job")

    def test_an_employer_without_spare_food_pays_in_coin(self):
        s = LabourScene(stock=1, coin=5)
        r = s.shift()
        self.assertTrue(r.ops[0].get("hired"), r.ops)
        job = s.book.between("h_a", "h_b")
        self.assertEqual((job.item, job.qty), ("coin", 2))

    def test_the_employers_rules(self):
        cases = [(dict(closeness=-0.5), "refuse_distrust"), (dict(tags=["rival"]), "refuse_distrust"), (dict(tags=["defaulter"]), "refuse_defaulter"),
                 (dict(stock=1, coin=0), "refuse_no_wage")]
        for kwargs, answer in cases:
            s = LabourScene(**kwargs)
            r = s.shift()
            self.assertTrue(r.ok, (kwargs, r.code))
            self.assertEqual(r.ops[0]["answer"], answer, kwargs)
            self.assertFalse(r.ops[0].get("hired"), kwargs)
            self.assertIsNone(s.book.between("h_a", "h_b"), kwargs)

    def test_one_shift_at_a_time_and_a_staff_limit(self):
        s = LabourScene()
        self.assertTrue(s.shift().ops[0].get("hired"))
        self.assertEqual(s.shift().code, "illegal:already_working")
        self.assertFalse([o for o in s.runner.aff.options("h_a") if o.verb == "work_for"])
        s.book.hire("h_b", "x1", "coin", 2, 0)                              # a second hand fills the books
        self.assertEqual(s.book.staff("h_b", 0), lb.MAX_WORKERS)
        from systems.actions.labour_verbs import respond_to_job
        self.assertEqual(respond_to_job(s.world, s.services, "h_c", "h_b", 0)["answer"], "refuse_staffed")

    def test_an_expired_shift_cannot_be_collected(self):
        s = LabourScene()
        s.shift()
        job = s.book.between("h_a", "h_b")
        late = s.collect(job.expires)
        self.assertEqual(late.code, "illegal:no_job")
        self.assertEqual((s.held("h_a", "rations"), s.held("h_b", "rations")), (2, 4))

    def test_an_employer_who_spent_the_wage_cannot_pay(self):
        s = LabourScene()
        s.shift()
        job = s.book.between("h_a", "h_b")
        s.world.items.remove("h_b", "rations", 4)
        r = s.collect(job.ready_at)
        self.assertEqual(r.code, "illegal:employer_cannot_pay")


if __name__ == "__main__":
    unittest.main()
