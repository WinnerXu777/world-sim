"""Interim dormancy as the model plane sees it (``actions/dormancy_gate.py``): a dormant resident is skipped by the agent driver and the periodic passes, and treated as newly arrived on wake."""
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
from systems.actions import credit_day, dormancy_gate, justice_day
from systems.actions.agent_driver import AgentDriver, Goal, RulesTier1
from systems.actions.ladder import Errand
from systems.credit import runtime as credit_runtime
from systems.roster.driver import runtime


class Dormancy(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_CREDIT": "1", "EDEN_JUSTICE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.engine.__dict__.pop("_dormant_h", None)
        self.addCleanup(self.engine.__dict__.pop, "_dormant_h", None)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in self.humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.sleeper, self.other = self.humans[0], self.humans[1]
        self.slot = self.engine._human_slot_for_id(self.sleeper)

    def set_dormant(self, *ids):
        mask = torch.zeros(len(self.engine._human_uid_by_slot), dtype=torch.bool)
        for human_id in ids:
            mask[self.engine._human_slot_for_id(human_id)] = True
        self.engine.__dict__["_dormant_h"] = mask

    async def test_without_the_predicate_nothing_changes(self):
        self.assertFalse(dormancy_gate.asleep(self.engine, self.sleeper))
        slots = [self.engine._human_slot_for_id(h) for h in self.humans]
        self.assertEqual(dormancy_gate.filter_slots(self.driver, self.engine, slots), slots)
        self.assertEqual(self.driver.dormant, set())

    async def test_a_dormant_resident_is_not_driven_and_the_others_are(self):
        self.set_dormant(self.sleeper)
        before = tuple(float(self.engine.state.h_tensor[self.slot, c]) for c in (cfg.X, cfg.Y))
        for _ in range(30):
            self.engine.tick += 1                                               # the harness refreshes the real mask inside engine.step(); here the driver is called directly
            self.driver.step(self.engine)
        self.assertNotIn(self.sleeper, self.driver.last_goal)
        self.assertNotIn(self.sleeper, self.driver.cache)
        self.assertTrue(any(h in self.driver.last_goal for h in self.humans if h != self.sleeper))
        self.assertEqual(self.driver.dormant, {self.sleeper})
        self.assertEqual(self.driver.errors, 0)
        after = tuple(float(self.engine.state.h_tensor[self.slot, c]) for c in (cfg.X, cfg.Y))
        self.assertEqual(before, after)                                       # the driver did not walk it (the harness freezes the row; here nothing else moves it)

    async def test_waking_drops_the_stale_state_and_it_is_replanned(self):
        self.driver.last_goal[self.sleeper] = Goal("routine", "work", (1.0, 2.0))
        self.driver.cache[self.sleeper] = {"sig": None, "macro": "work_at_station", "tick": 0}
        self.driver.ladder.errands[self.sleeper] = Errand("forage", "forage_node", (5.0, 5.0), "e", "eat_from_node", {}, 10 ** 6)
        runtime(self.engine).mover.plans[self.sleeper] = {"goal": (1.0, 1.0), "waypoints": [(1.0, 1.0)], "index": 0, "revision": "r", "best": 1.0, "stalled": 0, "replans": 0}
        self.set_dormant(self.sleeper)
        self.driver.step(self.engine)
        self.assertIn(self.sleeper, self.driver.dormant)
        self.engine.__dict__.pop("_dormant_h")                                # the chunk is integrated again
        self.driver.step(self.engine)
        self.assertEqual(self.driver.dormant, set())
        self.assertNotIn(self.sleeper, self.driver.ladder.errands)
        self.assertEqual(self.driver.routed["dormancy.sleep"], 1)
        self.assertEqual(self.driver.routed["dormancy.wake"], 1)
        plan = runtime(self.engine).mover.plans.get(self.sleeper)
        self.assertTrue(plan is None or plan["goal"] != (1.0, 1.0))                  # the stale movement plan is gone

    async def test_the_periodic_passes_skip_a_dormant_resident(self):
        loans = credit_runtime.of(self.driver.runner(self.engine).services)
        loan = loans.open(self.other, self.sleeper, "rations", 1, 0.3, 0, 2400)
        self.set_dormant(self.sleeper)
        self.assertFalse(justice_day._alive(self.engine, self.sleeper))
        self.assertTrue(justice_day._alive(self.engine, self.other))
        credit_day.step(self.driver, self.engine, credit_day.CREDIT_PERIOD)
        self.assertNotIn(self.sleeper, self.driver.ladder.errands)           # no repayment errand for the dormant borrower
        self.assertEqual(loan.status, "open")


if __name__ == "__main__":
    unittest.main()
