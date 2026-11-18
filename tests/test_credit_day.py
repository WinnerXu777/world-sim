"""EDEN_CREDIT daily pass on a real engine: overdue note, default (tag + closeness), repayment by a borrower with a conscience, none without."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import random
import unittest
import unittest.mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_map_contract import AsyncRegistryIsolation
from authored_village import load_village_maps
import genesis_config as cfg
from driver_pin import pin_anchor
from harness import effects as fx
from harness.adapter import EngineWorld
from systems.actions import credit_day, ladder
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.actions.gameclock import day_ticks
from systems.credit import runtime as credit_runtime

CONSCIENTIOUS = {"mercy": 0.9, "loyalty": 0.9, "discipline": 0.9}
CORRUPT = {"mercy": 0.1, "deceitfulness": 0.9, "greed": 0.9, "aggression": 0.6}


class Base(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_CREDIT": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.borrower, self.lender = humans[0], humans[1]
        self.runner = self.driver.runner(self.engine)
        self.book = credit_runtime.of(self.runner.services)
        for human_id in humans:
            slot = self.engine._human_slot_for_id(human_id)
            self.engine.state.h_tensor[slot, cfg.HUNGER] = 0.0
        self.engine.resident_store.update_relationship(self.lender, self.borrower, "known", 0.3, 0)

    def traits(self, by_id):
        from systems.actions import reputation
        patcher = unittest.mock.patch("systems.personality.assign.get_personality_traits", lambda personality: dict(by_id))
        patcher.start()
        self.addCleanup(patcher.stop)

    def give(self, human_id, item, qty):
        world = EngineWorld(self.engine, seed=0)
        report = world.apply([fx.Transfer(item, qty, None, human_id)], atomic=True, cause="test:give", items=fx.ItemPermit(produce={item: qty}))
        self.assertTrue(report.ok, report)

    def together(self):
        h = self.engine.state.h_tensor
        a, b = self.engine._human_slot_for_id(self.borrower), self.engine._human_slot_for_id(self.lender)
        h[a, cfg.X], h[a, cfg.Y] = float(h[b, cfg.X]), float(h[b, cfg.Y])

    def relation(self):
        return self.engine.resident_store.get(self.lender)["relationships"][self.borrower]

    def lend(self, tick=0):
        return self.book.open(self.lender, self.borrower, "rations", 1, 0.3, tick, day_ticks())


class Overdue(Base):
    async def test_overdue_is_noted_once_then_default_tags_the_borrower(self):
        loan = self.lend()
        before = self.relation()["closeness"]
        self.traits(CORRUPT)                                         # no repayment: the loan goes bad
        credit_day.step(self.driver, self.engine, loan.due - credit_day.CREDIT_PERIOD)
        self.assertEqual(self.book.counts["overdue"], 0)
        credit_day.step(self.driver, self.engine, loan.due)
        self.assertEqual(self.book.counts["overdue"], 1)
        self.assertLess(self.relation()["closeness"], before)
        credit_day.step(self.driver, self.engine, loan.due + credit_day.CREDIT_PERIOD)
        self.assertEqual(self.book.counts["overdue"], 1)             # noted once
        self.assertEqual(loan.status, "open")
        credit_day.step(self.driver, self.engine, loan.due + day_ticks())
        self.assertEqual(loan.status, "defaulted")
        self.assertIn("defaulter", self.relation()["tags"])
        self.assertTrue(self.book.defaulted(self.borrower, self.lender))
        types = [e.type for e in self.runner.world.events.events()]
        self.assertIn("loan_overdue", types)
        self.assertIn("loan_defaulted", types)


class Repayment(Base):
    async def test_a_borrower_with_a_conscience_who_holds_enough_pays_the_lender_back(self):
        self.traits(CONSCIENTIOUS)
        loan = self.lend()
        self.give(self.borrower, "rations", 2)
        self.give(self.lender, "rations", 3)
        self.together()
        lender_before = self.runner.services.inventory(self.lender).get("rations", 0)
        credit_day.step(self.driver, self.engine, credit_day.CREDIT_PERIOD)
        self.assertEqual(loan.status, "repaid")
        self.assertGreater(self.runner.services.inventory(self.lender).get("rations", 0), lender_before)

    async def test_a_borrower_away_from_the_lender_gets_a_repay_errand_that_follows_them(self):
        self.traits(CONSCIENTIOUS)
        loan = self.lend()
        self.give(self.borrower, "rations", 2)
        h = self.engine.state.h_tensor
        far = self.engine._human_slot_for_id(self.borrower)
        h[far, cfg.X] = float(h[far, cfg.X]) + 300.0
        credit_day.step(self.driver, self.engine, credit_day.CREDIT_PERIOD)
        errand = self.driver.ladder.errands[self.borrower]
        self.assertEqual((errand.purpose, errand.verb, errand.target), ("repay", "pay_debt", self.lender))
        self.assertEqual(loan.status, "open")
        self.together()
        self.driver.ladder.arrive(self.driver, self.engine, self.borrower, 130)
        self.assertEqual(loan.status, "repaid")
        self.assertNotIn(self.borrower, self.driver.ladder.errands)

    async def test_no_conscience_or_hungry_or_too_little_means_no_repayment(self):
        loan = self.lend()
        self.give(self.borrower, "rations", 2)
        self.together()
        self.traits(CORRUPT)
        credit_day.step(self.driver, self.engine, credit_day.CREDIT_PERIOD)
        self.assertEqual(loan.status, "open")
        self.assertNotIn(self.borrower, self.driver.ladder.errands)

    async def test_a_hungry_borrower_keeps_the_food(self):
        self.traits(CONSCIENTIOUS)
        loan = self.lend()
        self.give(self.borrower, "rations", 2)
        self.together()
        self.engine.state.h_tensor[self.engine._human_slot_for_id(self.borrower), cfg.HUNGER] = 70.0
        credit_day.step(self.driver, self.engine, credit_day.CREDIT_PERIOD)
        self.assertEqual(loan.status, "open")

    async def test_only_on_the_credit_period(self):
        self.traits(CONSCIENTIOUS)
        loan = self.lend()
        self.give(self.borrower, "rations", 2)
        self.together()
        credit_day.step(self.driver, self.engine, credit_day.CREDIT_PERIOD + 1)
        self.assertEqual(loan.status, "open")


if __name__ == "__main__":
    unittest.main()
