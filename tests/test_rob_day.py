"""EDEN_ROB on the real engine (the starter village, agent residents): the ladder's rob rung and its deterrents, the robbery's consequences, the authority's arrest after damages."""
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
from harness import effects as fx, restraint
from harness.adapter import EngineWorld
from systems import rob as rules
from systems.actions import justice_day, reputation
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.guard import runtime as guard_runtime
from systems.justice import runtime as justice_runtime

FLAGS = {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_REPUTATION": "1", "EDEN_JUSTICE": "1", "EDEN_DEFEND": "1", "EDEN_ROB": "1", "EDEN_RESTRAINT": "1"}
RUTHLESS = dict(mercy=0.1, loyalty=0.1, discipline=0.1, deceitfulness=0.9, greed=0.9, aggression=0.9)
DECENT = dict(mercy=0.9, loyalty=0.9, discipline=0.9, deceitfulness=0.1, greed=0.1, aggression=0.1)


class Village(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", FLAGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.engine.__dict__.pop("_reputation", None)
        self.engine.__dict__.pop("_dormant_h", None)
        self.addCleanup(self.engine.__dict__.pop, "_dormant_h", None)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in self.humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.h = self.engine.state.h_tensor
        self.robber, self.victim, self.judge = self.humans[0], self.humans[1], self.humans[2]
        for index, other in enumerate(self.humans[3:]):
            slot = self.engine._human_slot_for_id(other)
            self.h[slot, cfg.X], self.h[slot, cfg.Y] = 3000.0 + 700.0 * index, 3000.0
        for human_id in self.humans:
            self.traits(human_id, **DECENT)
            record = self.engine.resident_store.get(human_id)
            record["relationships"] = {}
            record["occupation"] = {"kind": "gatherer"}
            slot = self.engine._human_slot_for_id(human_id)
            self.h[slot, cfg.HUNGER], self.h[slot, cfg.THIRST], self.h[slot, cfg.THREAT], self.h[slot, cfg.HP] = 10.0, 10.0, 0.0, 100.0
        self.traits(self.robber, **RUTHLESS)
        self.h[self.engine._human_slot_for_id(self.robber), cfg.HUNGER] = 90.0
        self.engine.resident_store.get(self.judge)["occupation"] = {"kind": "guard"}
        self.put(self.robber, 0.0)
        self.put(self.victim, 8.0)
        self.put(self.judge, 2000.0)
        self.runner = self.driver.runner(self.engine)
        self.give(self.victim, "rations", 3)
        self.tick = 600
        self.engine.tick = self.tick

    def put(self, human_id, dx):
        base = self.engine._human_slot_for_id(self.robber)
        slot = self.engine._human_slot_for_id(human_id)
        self.h[slot, cfg.X], self.h[slot, cfg.Y] = self.h[base, cfg.X] + dx, self.h[base, cfg.Y]

    def traits(self, human_id, **values):
        record = self.engine.resident_store.get(human_id)
        base = dict(((record.get("personality") or {}).get("traits")) or {})
        record["personality"] = {**(record.get("personality") or {}), "traits": {**base, **values}}

    def give(self, human_id, item, qty):
        world = EngineWorld(self.engine, seed=0)
        report = world.apply([fx.Transfer(item, qty, None, human_id)], atomic=True, cause="test:give", items=fx.ItemPermit(produce={item: qty}))
        self.assertTrue(report.ok, report)

    def held(self, human_id, item="rations"):
        return self.runner.services.inventory(human_id).get(item, 0)

    def hp(self, human_id):
        return float(self.h[self.engine._human_slot_for_id(human_id), cfg.HP])

    def rung(self, human_id=None):
        human_id = human_id or self.robber
        S = self.runner.aff.situation(human_id)
        return self.driver.ladder._rob(self.driver, self.engine, self.runner, S, human_id, self.tick, "", [], 0.9, 0)

    def win(self, chance=1.0):
        patcher = unittest.mock.patch.object(rules, "p_success", lambda a, b: chance)
        patcher.start()
        self.addCleanup(patcher.stop)


class Rung(Village):
    async def test_a_desperate_ruthless_resident_robs_the_neighbour_who_carries_food(self):
        self.win()
        self.assertEqual(self.rung(), "rob")
        self.assertEqual(self.held(self.robber), 1)
        self.assertEqual(self.held(self.victim), 2)
        self.assertEqual(self.hp(self.victim), 100.0 - rules.ROB_DAMAGE)
        theft = reputation.of(self.engine).thefts[-1]
        self.assertTrue(theft.violent and theft.culprit_known and theft.discover_at == self.tick)
        self.assertEqual((theft.thief, theft.owner), (self.robber, self.victim))
        self.assertLess(self.engine.resident_store.get(self.victim)["relationships"][self.robber]["closeness"], -0.1)

    async def test_the_victim_that_fights_it_off_keeps_its_food_and_the_pair_cools_down(self):
        self.win(0.0)
        self.assertEqual(self.rung(), "rob")                                        # the attempt was made
        self.assertEqual(self.held(self.victim), 3)
        self.assertEqual(self.hp(self.robber), 100.0 - rules.ROB_BACKLASH)
        self.assertTrue(self.driver.ladder.cooling(self.robber, "rob", self.victim, self.tick))
        self.assertIsNone(self.rung())                                              # cooling: not tried again at once

    async def test_a_far_victim_is_walked_to_and_robbed_on_arrival(self):
        self.win()
        self.put(self.victim, 120.0)
        self.assertEqual(self.rung(), "errand")
        errand = self.driver.ladder.errands[self.robber]
        self.assertEqual((errand.purpose, errand.verb, errand.target), ("rob", "rob", self.victim))
        self.put(self.victim, 8.0)
        self.driver.ladder.arrive(self.driver, self.engine, self.robber, self.tick)
        self.assertNotIn(self.robber, self.driver.ladder.errands)
        self.assertEqual(self.held(self.victim), 2)

    async def test_deterrents_and_scruples(self):
        self.win()
        self.put(self.judge, 30.0)                                                  # an authority within sight of the victim
        self.assertIsNone(self.rung())
        self.put(self.judge, 2000.0)
        guard_runtime.of(self.runner.services).open(self.judge, "person", self.victim, self.tick, self.tick + 600)
        self.assertIsNone(self.rung())                                              # a guard stands over the victim
        guard_runtime.of(self.runner.services).close("post_00001", "test", self.tick)
        self.traits(self.robber, **DECENT)
        self.assertIsNone(self.rung())                                              # a resident with a conscience does not
        self.traits(self.robber, **RUTHLESS)
        self.h[self.engine._human_slot_for_id(self.robber), cfg.HP] = rules.ROB_MIN_HP - 1
        self.assertIsNone(self.rung())                                              # too hurt to fight
        self.h[self.engine._human_slot_for_id(self.robber), cfg.HP] = 100.0
        self.engine.resident_store.get(self.robber)["relationships"][self.victim] = {"kind": "known", "closeness": 0.5, "last_seen_tick": 0, "tags": ["known"], "tag_meta": {}}
        self.assertIsNone(self.rung())                                              # not someone it holds dear
        self.assertEqual(self.held(self.victim), 3)

    async def test_nobody_dormant_or_without_food(self):
        self.win()
        mask = torch.zeros(len(self.engine._human_uid_by_slot), dtype=torch.bool)
        mask[self.engine._human_slot_for_id(self.victim)] = True
        self.engine._dormant_h = mask
        self.assertIsNone(self.rung())
        del self.engine._dormant_h
        world = EngineWorld(self.engine, seed=0)
        world.apply([fx.Transfer("rations", 3, self.victim, None)], atomic=True, cause="test:take", items=fx.ItemPermit(consume={"rations": 3}))
        self.assertIsNone(self.rung())

    async def test_the_rung_exists_only_with_the_flag(self):
        self.assertIn("rob", self.driver.ladder.built())
        with unittest.mock.patch.dict("os.environ", {"EDEN_ROB": ""}):
            self.assertNotIn("rob", self.driver.ladder.built())
        with unittest.mock.patch.dict("os.environ", {"EDEN_LADDER_RUNGS": "forage,rob"}):       # the stress-run knob
            self.assertEqual(self.driver.ladder.built(), ("forage", "rob"))


class Consequences(Village):
    async def test_the_robbery_is_reported_levied_and_the_robber_is_held(self):
        self.win()
        self.put(self.judge, 2000.0)
        self.assertEqual(self.rung(), "rob")
        reputation.step(self.driver, self.engine, self.tick)                         # the victim knows at once
        self.assertTrue(reputation.of(self.engine).thefts[-1].discovered)
        self.put(self.judge, 4.0)
        self.put(self.victim, 8.0)
        self.h[self.engine._human_slot_for_id(self.victim), cfg.HP] = 100.0
        justice_day.step(self.driver, self.engine, 0)
        docket = justice_runtime.of(self.runner.services)
        case = next(iter(docket.cases.values()))
        self.assertEqual((case.thief, case.victim, case.authority, case.status), (self.robber, self.victim, self.judge, "closed"))
        slot = self.engine._human_slot_for_id(self.robber)
        self.assertEqual(float(self.h[slot, cfg.H_RESTRAINED]), float(rules.ARREST_TICKS))
        self.assertIn("arrested", [e.type for e in self.runner.world.events.events()])

    async def test_without_the_restraint_flag_the_arrest_is_refused_and_damages_still_stand(self):
        self.win()
        self.rung()
        reputation.step(self.driver, self.engine, self.tick)
        self.put(self.judge, 4.0)
        with unittest.mock.patch.dict("os.environ", {"EDEN_RESTRAINT": ""}):
            justice_day.step(self.driver, self.engine, 0)
        case = next(iter(justice_runtime.of(self.runner.services).cases.values()))
        self.assertEqual(case.status, "closed")
        self.assertEqual(float(self.h[self.engine._human_slot_for_id(self.robber), cfg.H_RESTRAINED]), 0.0)

    async def test_arrest_needs_an_authority_a_conviction_and_a_free_target(self):
        runner = self.runner
        self.put(self.judge, 4.0)
        self.assertEqual(runner.run(self.victim, "arrest_or_restrain", {"target": self.robber}, proposer="rules:test").code, "illegal:not_authority")
        self.assertEqual(runner.run(self.judge, "arrest_or_restrain", {"target": self.robber}, proposer="rules:test").code, "illegal:not_convicted")
        self.win()
        self.put(self.judge, 2000.0)
        self.rung()
        self.put(self.judge, 4.0)
        first = runner.run(self.judge, "arrest_or_restrain", {"target": self.robber}, proposer="rules:test")
        self.assertTrue(first.ok, (first.code, first.ops))
        self.assertEqual(runner.run(self.judge, "arrest_or_restrain", {"target": self.robber}, proposer="rules:test").code, "illegal:already_restrained")
        restraint.release(self.engine, self.engine._human_slot_for_id(self.robber))

    async def test_a_resident_cannot_be_held_for_a_theft_that_was_not_a_robbery(self):
        reputation.of(self.engine).thefts.append(reputation.Theft("ev_t", self.robber, "resident", self.victim, "", "rations", 1, 3.0, 0, 0, True, discovered=True))
        self.put(self.judge, 4.0)
        self.assertEqual(self.runner.run(self.judge, "arrest_or_restrain", {"target": self.robber}, proposer="rules:test").code, "illegal:not_convicted")


if __name__ == "__main__":
    unittest.main()
