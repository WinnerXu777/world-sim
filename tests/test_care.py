"""light_fire / treat_wound (EDEN_TEMPERATURE / EDEN_WOUNDS) on the real engine (the starter village, agent residents), the clothing item class, and the flag-off identity."""
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
from harness import effects as fx, temperature, wounds
from harness.adapter import EngineWorld
from systems import clothing
from systems.actions import care_day, resource_verbs
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.inventory import schema

FLAGS = {"EDEN_AGENT_ACTIONS": "1", "EDEN_TEMPERATURE": "1", "EDEN_WOUNDS": "1"}


class Clothing(unittest.TestCase):
    def test_the_garments_are_declared_items_and_the_best_one_counts(self):
        for kind in clothing.INSULATION:
            self.assertIn("clothing", schema.item_kind_def(kind)["tags"])
        self.assertEqual(clothing.insulation_of({}), 0.0)
        self.assertEqual(clothing.insulation_of({"cloak": 1}), 4.0)
        self.assertEqual(clothing.insulation_of({"cloak": 1, "fur_coat": 1, "rations": 3}), 9.0)


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
        self.engine.__dict__.pop("_warmth_sources", None)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in self.humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.h = self.engine.state.h_tensor
        self.a, self.b = self.humans[0], self.humans[1]
        for index, other in enumerate(self.humans[2:]):
            slot = self.engine._human_slot_for_id(other)
            self.h[slot, cfg.X], self.h[slot, cfg.Y] = 3000.0 + 700.0 * index, 3000.0
        base = self.engine._human_slot_for_id(self.a)
        slot = self.engine._human_slot_for_id(self.b)
        self.h[slot, cfg.X], self.h[slot, cfg.Y] = self.h[base, cfg.X] + 8.0, self.h[base, cfg.Y]
        self.engine.tick = 600
        self.runner = self.driver.runner(self.engine)
        wounds._records(self.engine).clear()
        for human_id in self.humans:
            for item in ("wood_bundle", "bandage", "herb_bundle"):
                self.strip(human_id, item)

    def strip(self, human_id, item):
        have = self.runner.services.inventory(human_id).get(item, 0)
        if have:
            world = EngineWorld(self.engine, seed=0)
            report = world.apply([fx.Transfer(item, have, human_id, None)], atomic=True, cause="test:strip", items=fx.ItemPermit(consume={item: have}))
            self.assertTrue(report.ok, report)

    def give(self, human_id, item, qty):
        world = EngineWorld(self.engine, seed=0)
        report = world.apply([fx.Transfer(item, qty, None, human_id)], atomic=True, cause="test:give", items=fx.ItemPermit(produce={item: qty}))
        self.assertTrue(report.ok, report)

    def held(self, human_id, item):
        return self.runner.services.inventory(human_id).get(item, 0)

    def wound(self, uid, bleed=0.2):
        wounds._records(self.engine)[uid] = {"bleed": bleed, "tick": int(self.engine.tick)}


class Fire(Village):
    async def test_a_bundle_of_wood_lights_a_fire_that_warms_and_burns_out(self):
        self.give(self.a, "wood_bundle", 2)
        result = self.runner.run(self.a, "light_fire", {})
        self.assertTrue(result.ok, result)
        self.assertEqual(self.held(self.a, "wood_bundle"), 1)
        sources = self.engine.__dict__["_warmth_sources"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["until"], 600 + 1200)
        slot = self.engine._human_slot_for_id(self.a)
        self.assertEqual((sources[0]["x"], sources[0]["y"]), (float(self.h[slot, cfg.X]), float(self.h[slot, cfg.Y])))
        lit = temperature._fires(self.engine).shape[0]
        self.engine.tick = 600 + 1200
        self.assertEqual(temperature._fires(self.engine).shape[0], lit - 1)
        self.assertEqual(self.engine.__dict__["_warmth_sources"], [])

    async def test_no_wood_or_a_fire_already_near_refuses(self):
        refused = self.runner.run(self.a, "light_fire", {})
        self.assertFalse(refused.ok)
        self.assertTrue(refused.code)
        self.give(self.a, "wood_bundle", 2)
        self.assertTrue(self.runner.run(self.a, "light_fire", {}).ok)
        again = self.runner.run(self.b, "light_fire", {})                       # b is wood-less
        self.assertFalse(again.ok)
        self.give(self.b, "wood_bundle", 1)
        near = self.runner.run(self.b, "light_fire", {})
        self.assertFalse(near.ok)
        self.assertEqual(self.held(self.b, "wood_bundle"), 1)

    async def test_the_candidates_offer_it_only_with_wood(self):
        from systems.affordance import care_predicates
        self.assertEqual(care_predicates._candidates_fire(self.runner.aff.situation(self.a)), [])
        self.give(self.a, "wood_bundle", 1)
        S = self.runner.aff.situation(self.a)
        self.assertEqual(care_predicates._candidates_fire(S), [{}])

    async def test_flag_off_the_verb_is_not_registered_or_wired(self):
        with unittest.mock.patch.dict("os.environ", {"EDEN_TEMPERATURE": "", "EDEN_WOUNDS": ""}):
            self.assertNotIn("light_fire", resource_verbs.default_registry().actions)
            self.give(self.a, "wood_bundle", 1)
            S = self.runner.aff.situation(self.a)
            from systems.affordance import care_predicates
            self.assertEqual(care_predicates._candidates_fire(S), [])
            self.assertEqual(care_predicates.light_fire(S).reason, "not_wired")


class Treat(Village):
    async def test_a_bandage_stops_the_bleed_of_the_carer(self):
        self.wound(self.a, 0.2)
        self.give(self.a, "bandage", 1)
        result = self.runner.run(self.a, "treat_wound", {})
        self.assertTrue(result.ok)
        self.assertFalse(wounds.wounded_of(self.engine, self.a))
        self.assertEqual(self.held(self.a, "bandage"), 0)

    async def test_herbs_stop_only_part_of_it(self):
        self.wound(self.a, 0.2)
        self.give(self.a, "herb_bundle", 1)
        self.assertTrue(self.runner.run(self.a, "treat_wound", {}).ok)
        self.assertAlmostEqual(wounds.bleed_of(self.engine, self.a), 0.08, places=6)
        self.assertEqual(self.held(self.a, "herb_bundle"), 0)

    async def test_a_neighbour_in_reach_is_treated_and_holds_the_carer_dearer(self):
        self.wound(self.b, 0.25)
        self.give(self.a, "bandage", 1)
        before = ((self.engine.resident_store.get(self.b).get("relationships") or {}).get(self.a) or {}).get("closeness", 0.0)
        self.assertTrue(self.runner.run(self.a, "treat_wound", {"target": self.b}).ok)
        self.assertFalse(wounds.wounded_of(self.engine, self.b))
        after = self.engine.resident_store.get(self.b)["relationships"][self.a]["closeness"]
        self.assertGreater(after, before)

    async def test_nothing_to_treat_or_nothing_to_treat_with_refuses_and_keeps_the_item(self):
        self.give(self.a, "bandage", 1)
        self.assertFalse(self.runner.run(self.a, "treat_wound", {}).ok)             # not wounded
        self.assertEqual(self.held(self.a, "bandage"), 1)
        self.wound(self.a, 0.2)
        self.give(self.b, "rations", 1)
        self.assertFalse(self.runner.run(self.b, "treat_wound", {"target": self.a}).ok)  # b carries nothing to treat with

    async def test_a_far_neighbour_is_out_of_reach(self):
        far = self.humans[2]
        self.wound(far, 0.3)
        self.give(self.a, "bandage", 1)
        self.assertFalse(self.runner.run(self.a, "treat_wound", {"target": far}).ok)
        self.assertTrue(wounds.wounded_of(self.engine, far))

    async def test_flag_off_not_wired(self):
        with unittest.mock.patch.dict("os.environ", {"EDEN_WOUNDS": ""}):
            self.wound(self.a, 0.2)
            self.give(self.a, "bandage", 1)
            S = self.runner.aff.situation(self.a)
            from systems.affordance import care_predicates
            self.assertEqual(care_predicates._candidates_treat(S), [])
            self.assertEqual(care_predicates.treat_wound(S).reason, "not_wired")


class Day(Village):
    def step(self, tick=600):
        self.engine.tick = tick
        care_day.step(self.driver, self.engine, tick)

    def relate(self, owner, other, closeness):
        self.engine.resident_store.get(owner).setdefault("relationships", {})[other] = {"kind": "known", "closeness": closeness, "last_seen_tick": 0, "tags": ["known"], "tag_meta": {}}

    async def test_a_wounded_resident_with_a_bandage_dresses_its_own_wound(self):
        self.wound(self.a, 0.2)
        self.give(self.a, "bandage", 1)
        self.step()
        self.assertFalse(wounds.wounded_of(self.engine, self.a))

    async def test_a_dear_neighbour_is_dressed_a_stranger_is_not(self):
        self.wound(self.b, 0.2)
        self.give(self.a, "bandage", 1)
        self.relate(self.a, self.b, 0.0)
        self.step()
        self.assertTrue(wounds.wounded_of(self.engine, self.b))
        self.relate(self.a, self.b, 0.6)
        self.step()
        self.assertFalse(wounds.wounded_of(self.engine, self.b))

    async def test_the_cold_resident_with_wood_lights_one_fire(self):
        self.give(self.a, "wood_bundle", 2)
        with unittest.mock.patch.object(temperature, "cold_of", lambda e, s: 10.0):
            self.step()
            self.step(610)
        self.assertEqual(len(self.engine.__dict__["_warmth_sources"]), 1)
        self.assertEqual(self.held(self.a, "wood_bundle"), 1)

    async def test_the_warm_resident_keeps_its_wood_and_off_period_ticks_do_nothing(self):
        self.give(self.a, "wood_bundle", 2)
        with unittest.mock.patch.object(temperature, "cold_of", lambda e, s: 0.0):
            self.step()
        with unittest.mock.patch.object(temperature, "cold_of", lambda e, s: 10.0):
            self.step(605)
        self.assertEqual(self.held(self.a, "wood_bundle"), 2)

    async def test_both_flags_off_the_pass_is_a_no_op(self):
        with unittest.mock.patch.dict("os.environ", {"EDEN_TEMPERATURE": "", "EDEN_WOUNDS": ""}):
            self.give(self.a, "bandage", 1)
            self.step()
        self.assertEqual(self.held(self.a, "bandage"), 1)


if __name__ == "__main__":
    unittest.main()
