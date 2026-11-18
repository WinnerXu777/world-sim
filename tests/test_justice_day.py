"""EDEN_JUSTICE on a real engine: a known theft is reported to the nearest authority, the authority walks to the thief and levies damages; no authority, no action."""
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
from systems.actions import justice_day, reputation
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.justice import runtime as justice_runtime

CALM = {"mercy": 0.9, "loyalty": 0.9, "discipline": 0.9, "caution": 0.5}


class Base(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_REPUTATION": "1", "EDEN_JUSTICE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        traits = unittest.mock.patch("systems.personality.assign.get_personality_traits", lambda personality: dict(CALM))
        traits.start()
        self.addCleanup(traits.stop)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.engine.__dict__.pop("_reputation", None)
        humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
            self.engine.state.h_tensor[self.engine._human_slot_for_id(human_id), cfg.HUNGER] = 0.0
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.victim, self.thief, self.judge = humans[0], humans[1], humans[2]
        self.engine.resident_store.get(self.judge)["occupation"] = {"kind": "guard"}
        self.engine.resident_store.update_relationship(self.judge, self.victim, "known", 0.3, 0)
        self.runner = self.driver.runner(self.engine)
        self.docket = justice_runtime.of(self.runner.services)
        self.give(self.thief, "rations", 3)
        self.give(self.thief, "coin", 5)
        self.theft = reputation.Theft("ev_theft", self.thief, "resident", self.victim, "", "rations", 2, 6.0, 0, 0, True, discovered=True, knowers=[self.victim])
        reputation.of(self.engine).thefts.append(self.theft)
        self.engine.resident_store.update_relationship(self.victim, self.thief, "known", -0.4, 0)
        self.engine.resident_store.get(self.victim)["relationships"][self.thief]["tags"] = ["thief"]

    def give(self, human_id, item, qty):
        world = EngineWorld(self.engine, seed=0)
        report = world.apply([fx.Transfer(item, qty, None, human_id)], atomic=True, cause="test:give", items=fx.ItemPermit(produce={item: qty}))
        self.assertTrue(report.ok, report)

    def held(self, human_id, item):
        return self.runner.services.inventory(human_id).get(item, 0)

    def together(self, *ids):
        h = self.engine.state.h_tensor
        base = self.engine._human_slot_for_id(ids[0])
        for other in ids[1:]:
            slot = self.engine._human_slot_for_id(other)
            h[slot, cfg.X], h[slot, cfg.Y] = float(h[base, cfg.X]), float(h[base, cfg.Y])

    def far(self, human_id, dx=40.0):
        slot = self.engine._human_slot_for_id(human_id)
        self.engine.state.h_tensor[slot, cfg.X] = float(self.engine.state.h_tensor[slot, cfg.X]) + dx


class Reports(Base):
    async def test_a_victim_in_reach_of_the_authority_reports_and_the_authority_levies_in_the_same_pass(self):
        self.together(self.victim, self.thief, self.judge)
        victim_before = self.held(self.victim, "rations")
        justice_day.step(self.driver, self.engine, 0)
        case = self.docket.cases["case_00001"]
        self.assertEqual((case.authority, case.status, case.outcome), (self.judge, "closed", "paid"))
        self.assertEqual(self.held(self.thief, "rations"), 1)
        self.assertGreater(self.held(self.victim, "rations"), victim_before)
        types = [e.type for e in self.runner.world.events.events()]
        self.assertIn("theft_reported", types)
        self.assertIn("damages_levied", types)

    async def test_one_report_per_theft(self):
        self.together(self.victim, self.thief, self.judge)
        justice_day.step(self.driver, self.engine, 0)
        self.assertEqual(self.docket.cases["case_00001"].status, "closed")
        justice_day.step(self.driver, self.engine, justice_day.JUSTICE_PERIOD)
        self.assertEqual(len(self.docket.cases), 1)

    async def test_a_victim_away_from_the_authority_walks_there_with_a_report_errand(self):
        self.together(self.thief, self.judge)
        self.far(self.victim)
        justice_day.step(self.driver, self.engine, 0)
        errand = self.driver.ladder.errands[self.victim]
        self.assertEqual((errand.purpose, errand.verb, errand.target), ("report", "report_theft", self.judge))
        self.assertIsNone(self.docket.against(self.thief))
        self.together(self.judge, self.victim)
        self.driver.ladder.arrive(self.driver, self.engine, self.victim, 40)
        self.assertIsNotNone(self.docket.against(self.thief, self.victim))
        self.assertNotIn(self.victim, self.driver.ladder.errands)

    async def test_without_an_authority_nothing_happens(self):
        self.engine.resident_store.get(self.judge)["occupation"] = {"kind": "farmer"}
        self.together(self.victim, self.thief, self.judge)
        justice_day.step(self.driver, self.engine, 0)
        self.assertEqual(self.docket.cases, {})
        self.assertNotIn(self.victim, self.driver.ladder.errands)

    async def test_only_on_the_justice_period(self):
        self.together(self.victim, self.thief, self.judge)
        justice_day.step(self.driver, self.engine, 7)
        self.assertEqual(self.docket.cases, {})


class Enforcement(Base):
    async def test_the_authority_walks_to_a_thief_who_is_away_and_levies_on_arrival(self):
        self.together(self.victim, self.judge)
        justice_day.step(self.driver, self.engine, 0)                # reports in reach; the thief is elsewhere
        self.far(self.thief)
        case = self.docket.against(self.thief, self.victim)
        self.assertIsNotNone(case)
        justice_day.step(self.driver, self.engine, justice_day.JUSTICE_PERIOD)
        errand = self.driver.ladder.errands[self.judge]
        self.assertEqual((errand.purpose, errand.verb, errand.target), ("enforce", "levy_damages", self.thief))
        self.assertEqual(case.status, "open")
        self.together(self.thief, self.judge)
        self.driver.ladder.arrive(self.driver, self.engine, self.judge, 130)
        self.assertEqual((case.status, case.outcome), ("closed", "paid"))
        self.assertNotIn(self.judge, self.driver.ladder.errands)

    async def test_a_case_nobody_served_lapses(self):
        self.together(self.victim, self.judge)
        justice_day.step(self.driver, self.engine, 0)
        case = self.docket.against(self.thief, self.victim)
        self.far(self.thief)
        self.engine.state.h_tensor[self.engine._human_slot_for_id(self.judge), cfg.HP] = 0.0       # the authority died: no one can serve it
        end = (case.expires // justice_day.JUSTICE_PERIOD + 1) * justice_day.JUSTICE_PERIOD
        justice_day.step(self.driver, self.engine, end)
        self.assertEqual((case.status, case.outcome), ("lapsed", "lapsed"))


if __name__ == "__main__":
    unittest.main()
