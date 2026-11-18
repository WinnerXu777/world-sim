"""EDEN_LABOUR ladder rung on a real engine: ask the employer for a shift, stay near them with a ``labour`` errand, collect the wage once the shift is done."""
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
from systems.actions import ladder
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.labour import book as lb
from systems.labour import runtime as labour_runtime


class Labour(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_LABOUR": "1"})
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
        self.worker, self.employer = humans[0], humans[1]
        self.runner = self.driver.runner(self.engine)
        self.jobs = labour_runtime.of(self.runner.services)
        h = self.engine.state.h_tensor
        for human_id in humans:
            slot = self.engine._human_slot_for_id(human_id)
            h[slot, cfg.HUNGER] = 0.0
        a, b = self.engine._human_slot_for_id(self.worker), self.engine._human_slot_for_id(self.employer)
        h[a, cfg.X], h[a, cfg.Y] = float(h[b, cfg.X]), float(h[b, cfg.Y])
        self.give(self.employer, "rations", 4)

    def give(self, human_id, item, qty):
        world = EngineWorld(self.engine, seed=0)
        report = world.apply([fx.Transfer(item, qty, None, human_id)], atomic=True, cause="test:give", items=fx.ItemPermit(produce={item: qty}))
        self.assertTrue(report.ok, report)

    def held(self, human_id, item="rations"):
        return self.runner.services.inventory(human_id).get(item, 0)

    def ask(self, tick):
        S = self.runner.aff.situation(self.worker)
        return self.driver.ladder._work(self.driver, self.engine, self.runner, S, self.worker, tick, "", [], 0.0, 0, only=self.employer)

    async def test_the_rung_is_built_only_while_the_flag_is_on(self):
        self.assertIn("work", ladder.Ladder.built())
        with unittest.mock.patch.dict("os.environ", {"EDEN_LABOUR": "0"}):
            self.assertNotIn("work", ladder.Ladder.built())

    async def test_a_hired_worker_stays_on_shift_then_collects_the_wage(self):
        self.engine.resident_store.update_relationship(self.employer, self.worker, "known", 0.2, 0)
        self.assertEqual(self.ask(10), "work")
        job = self.jobs.of_worker(self.worker, 10)
        self.assertIsNotNone(job)
        errand = self.driver.ladder.errands[self.worker]
        self.assertEqual((errand.purpose, errand.verb, errand.target), ("labour", "collect_wage", self.employer))
        worker_before, employer_before = self.held(self.worker), self.held(self.employer)
        self.driver.ladder.arrive(self.driver, self.engine, self.worker, job.ready_at - 1)           # still on shift: nothing moves
        self.assertIn(self.worker, self.driver.ladder.errands)
        self.assertEqual(self.held(self.worker), worker_before)
        self.engine.tick = job.ready_at                                                              # the predicate reads the engine's clock
        self.driver.ladder.arrive(self.driver, self.engine, self.worker, job.ready_at)
        self.assertNotIn(self.worker, self.driver.ladder.errands)
        self.assertEqual(job.status, "paid")
        self.assertEqual((self.held(self.worker), self.held(self.employer)), (worker_before + job.qty, employer_before - job.qty))

    async def test_a_stranger_who_is_refused_is_put_on_cooldown(self):
        self.engine.resident_store.update_relationship(self.employer, self.worker, "known", -0.6, 0)
        self.assertEqual(self.ask(10), "work")
        self.assertNotIn(self.worker, self.driver.ladder.errands)
        self.assertIsNone(self.jobs.of_worker(self.worker, 10))
        self.assertTrue(self.driver.ladder.cooling(self.worker, "work", self.employer, 11))


if __name__ == "__main__":
    unittest.main()
