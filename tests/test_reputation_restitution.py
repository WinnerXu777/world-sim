"""EDEN_REPUTATION: restitution by a thief with a conscience, and forgiveness over time (the two paths the S-1 scenario run never reached).

Real booted engine (starter_village, agent-driven residents) with the three flags patched on; the theft is recorded directly through
``reputation.record_theft`` so the test does not depend on a scenario finding a thief.
"""
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
from systems.actions import reputation
from systems.actions.agent_driver import AgentDriver, RulesTier1

CONSCIENTIOUS = {"mercy": 0.9, "loyalty": 0.9, "discipline": 0.9}      # conscience about 0.78
MERCIFUL, HARD = {"mercy": 0.9}, {"mercy": 0.2}


class ReputationBase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_REPUTATION": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.engine.__dict__.pop("_reputation", None)
        humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.thief, self.victim = humans[0], humans[1]
        self.state = reputation.of(self.engine)

    def traits(self, by_id):
        """Patch the personality the reputation module reads: ``{human id: traits}``, anything else gets mid-range traits."""
        patcher = unittest.mock.patch.object(reputation, "_traits", lambda engine, human_id: dict(by_id.get(human_id, {})))
        patcher.start()
        self.addCleanup(patcher.stop)

    def give(self, human_id, item, qty):
        world = EngineWorld(self.engine, seed=0)
        report = world.apply([fx.Transfer(item, qty, None, human_id)], atomic=True, cause="test:give", items=fx.ItemPermit(produce={item: qty}))
        self.assertTrue(report.ok, report)

    def relation(self, owner, other):
        return ((self.engine.resident_store.get(owner) or {}).get("relationships") or {}).get(other)

    def set_relation(self, owner, other, closeness, tags=()):
        self.engine.resident_store.update_relationship(owner, other, "known", closeness, 0)
        relation = self.engine.resident_store.get(owner)["relationships"][other]
        relation["closeness"], relation["tags"] = closeness, list(tags)


class Restitution(ReputationBase):
    def known_theft(self, tick):
        world = EngineWorld(self.engine, seed=0)
        event = world.events.emit("theft", actors=(self.thief, self.victim), visibility="private")
        reputation.record_theft(self.engine, world, self.thief, "resident", self.victim, "rations", 1, event.id, tick)
        theft = self.state.thefts[-1]
        theft.discover_at, theft.culprit_known = tick, True                  # the draws are not what is under test
        return theft

    async def test_a_fed_thief_with_a_conscience_walks_to_the_victim_and_gives_the_item_back(self):
        self.traits({self.thief: CONSCIENTIOUS, self.victim: HARD})
        self.set_relation(self.victim, self.thief, 0.0)
        self.give(self.thief, "rations", 2)
        self.engine.state.h_tensor[self.engine._human_slot_for_id(self.thief), cfg.HUNGER] = 10.0
        theft = self.known_theft(tick=100)
        reputation.step(self.driver, self.engine, 100)                         # discovery, the victim's opinion drops, the thief decides to make amends
        self.assertTrue(theft.discovered)
        dropped = dict(self.relation(self.victim, self.thief))                  # a copy: the stored relation is updated in place later
        self.assertLess(dropped["closeness"], 0.0)
        self.assertIn("thief", dropped["tags"])
        errand = self.driver.ladder.errands[self.thief]
        self.assertEqual((errand.purpose, errand.verb, errand.target), ("restitution", "give_item", self.victim))
        h = self.engine.state.h_tensor                                           # the thief reaches the victim
        h[self.engine._human_slot_for_id(self.thief), cfg.X] = float(h[self.engine._human_slot_for_id(self.victim), cfg.X])
        h[self.engine._human_slot_for_id(self.thief), cfg.Y] = float(h[self.engine._human_slot_for_id(self.victim), cfg.Y])
        before = self.driver.runner(self.engine).services.inventory(self.victim).get("rations", 0)
        self.driver.ladder.arrive(self.driver, self.engine, self.thief, 130)
        self.assertNotIn(self.thief, self.driver.ladder.errands)
        self.assertEqual(self.driver.runner(self.engine).services.inventory(self.victim).get("rations", 0), before + 1)
        self.assertTrue(theft.restituted)
        healed = self.relation(self.victim, self.thief)
        self.assertGreaterEqual(healed["closeness"], dropped["closeness"] + 0.15 - 1e-9)
        self.assertEqual(self.state.counts["restitution"], 1)

    async def test_a_thief_without_a_conscience_or_still_hungry_makes_no_amends(self):
        self.traits({self.thief: {"mercy": 0.1, "deceitfulness": 0.9, "greed": 0.9}, self.victim: HARD})
        self.give(self.thief, "rations", 2)
        self.engine.state.h_tensor[self.engine._human_slot_for_id(self.thief), cfg.HUNGER] = 10.0
        self.known_theft(tick=100)
        reputation.step(self.driver, self.engine, 100)
        self.assertNotIn(self.thief, self.driver.ladder.errands)
        self.traits({self.thief: CONSCIENTIOUS, self.victim: HARD})
        self.engine.state.h_tensor[self.engine._human_slot_for_id(self.thief), cfg.HUNGER] = 70.0
        reputation.step(self.driver, self.engine, 101)
        self.assertNotIn(self.thief, self.driver.ladder.errands)               # a starving conscientious thief keeps what it took


class Forgiveness(ReputationBase):
    def steps_to_forgive(self, mercy_traits):
        self.traits({self.victim: mercy_traits})
        self.set_relation(self.victim, self.thief, -0.5, ["thief"])
        for n in range(1, 2000):
            reputation._decay(self.engine, self.state, n * reputation.DECAY_PERIOD)
            if "thief" not in self.relation(self.victim, self.thief)["tags"]:
                return n
        self.fail("never forgiven")

    async def test_grudges_decay_toward_zero_faster_for_the_merciful_and_the_tag_goes_at_zero(self):
        merciful = self.steps_to_forgive(MERCIFUL)
        self.assertEqual(self.relation(self.victim, self.thief)["closeness"], 0.0)
        self.assertEqual(self.state.counts["forgiven"], 1)
        hard = self.steps_to_forgive(HARD)
        self.assertLess(merciful, hard)

    async def test_a_tag_whose_closeness_recovered_by_other_means_is_dropped_at_the_next_decay(self):
        self.traits({self.victim: HARD})
        self.set_relation(self.victim, self.thief, 0.2, ["thief"])            # befriended again (a gift, a long chat): the old tag must not linger
        reputation._decay(self.engine, self.state, reputation.DECAY_PERIOD)
        self.assertNotIn("thief", self.relation(self.victim, self.thief)["tags"])
        self.assertEqual(self.relation(self.victim, self.thief)["closeness"], 0.2)


if __name__ == "__main__":
    unittest.main()
