"""EDEN_BONDS pass and EDEN_PLACES record ops on the real engine (the starter village, agent residents): who forgives, apologises and befriends whom, dormancy, the re-base of a known place."""
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
from systems.actions import bonds_day
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.actions.rebase import rebase_model_plane
from systems.places import FIELD


class Village(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    FLAGS = {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1", "EDEN_BONDS": "1", "EDEN_PLACES": "1"}

    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", self.FLAGS)
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
        self.h = self.engine.state.h_tensor
        self.a, self.b = self.humans[0], self.humans[1]
        for index, other in enumerate(self.humans[2:]):              # everybody else far away and far from each other
            slot = self.engine._human_slot_for_id(other)
            self.h[slot, cfg.X], self.h[slot, cfg.Y] = 3000.0 + 700.0 * index, 3000.0
        for human_id in self.humans:                                   # nobody is sociable or merciful unless a test says so
            self.traits(human_id, sociability=0.1, mercy=0.1, loyalty=0.1, discipline=0.1, deceitfulness=0.9, greed=0.9, aggression=0.9)      # no conscience either
        self.put_together(self.a, self.b)
        for human_id in (self.a, self.b):
            slot = self.engine._human_slot_for_id(human_id)
            self.h[slot, cfg.HUNGER], self.h[slot, cfg.THIRST], self.h[slot, cfg.THREAT] = 10.0, 10.0, 0.0
            self.engine.resident_store.get(human_id)["relationships"] = {}
        self.tick = 600

    def put_together(self, a, b):
        sa, sb = self.engine._human_slot_for_id(a), self.engine._human_slot_for_id(b)
        self.h[sb, cfg.X], self.h[sb, cfg.Y] = self.h[sa, cfg.X] + 5.0, self.h[sa, cfg.Y]

    def traits(self, human_id, **values):
        record = self.engine.resident_store.get(human_id)
        base = dict(((record.get("personality") or {}).get("traits")) or {})
        record["personality"] = {**(record.get("personality") or {}), "traits": {**base, **values}}

    def relate(self, owner, other, closeness, tags=()):
        self.engine.resident_store.get(owner)["relationships"][other] = {"kind": "known", "closeness": closeness, "last_seen_tick": 0, "tags": list(tags) or ["known"], "tag_meta": {}}

    def closeness(self, owner, other):
        return float(((self.engine.resident_store.get(owner) or {}).get("relationships") or {}).get(other, {}).get("closeness", 0.0))

    def run_pass(self):
        bonds_day.step(self.driver, self.engine, self.tick)


class Pass(Village):
    async def test_a_merciful_resident_forgives_a_neighbour_it_holds_a_grudge_against(self):
        self.traits(self.a, mercy=0.9)
        self.relate(self.a, self.b, -0.4)
        self.run_pass()
        self.assertAlmostEqual(self.closeness(self.a, self.b), -0.25, places=2)
        self.assertEqual(self.driver.routed["forgive:ok"], 1)

    async def test_a_resident_with_a_conscience_apologises_to_the_one_it_wronged(self):
        self.traits(self.a, mercy=0.8, loyalty=0.8, discipline=0.8, deceitfulness=0.1, greed=0.1, aggression=0.1)
        self.relate(self.b, self.a, -0.3)
        self.run_pass()
        self.assertGreater(self.closeness(self.b, self.a), -0.3)
        self.assertLess(self.closeness(self.b, self.a), 0.0)
        self.assertEqual(self.driver.routed["apologise:ok"], 1)

    async def test_sociable_neighbours_become_friends_and_the_pair_cools_down(self):
        self.traits(self.a, sociability=0.9)
        self.traits(self.b, sociability=0.1)
        self.run_pass()
        self.assertAlmostEqual(self.closeness(self.a, self.b), 0.05, places=3)
        self.assertAlmostEqual(self.closeness(self.b, self.a), 0.05, places=3)
        self.tick += bonds_day.BONDS_PERIOD
        self.run_pass()
        self.assertAlmostEqual(self.closeness(self.a, self.b), 0.05, places=3)                 # inside the pair cooldown: nothing new
        self.tick += bonds_day.PAIR_COOLDOWN
        self.tick -= self.tick % bonds_day.BONDS_PERIOD
        self.run_pass()
        self.assertGreater(self.closeness(self.a, self.b), 0.05)

    async def test_fond_sociable_neighbours_court_instead_of_befriending(self):
        self.traits(self.a, sociability=0.9)
        self.relate(self.a, self.b, 0.3)
        self.relate(self.b, self.a, 0.3)
        self.run_pass()
        self.assertEqual(self.driver.routed["court:ok"], 1)
        self.assertEqual(self.driver.routed["befriend:ok"], 0)
        self.assertAlmostEqual(self.closeness(self.a, self.b), 0.34, places=2)

    async def test_hungry_or_threatened_residents_do_nothing_and_distant_ones_do_not_meet(self):
        self.traits(self.a, sociability=0.9)
        self.h[self.engine._human_slot_for_id(self.a), cfg.HUNGER] = 80.0
        self.run_pass()
        self.assertEqual(self.closeness(self.a, self.b), 0.0)
        self.h[self.engine._human_slot_for_id(self.a), cfg.HUNGER] = 10.0
        self.h[self.engine._human_slot_for_id(self.b), cfg.X] += 500.0
        self.run_pass()
        self.assertEqual(self.closeness(self.a, self.b), 0.0)

    async def test_off_period_and_flag_off_do_nothing(self):
        self.traits(self.a, sociability=0.9)
        self.tick = 601
        self.run_pass()
        self.assertEqual(self.closeness(self.a, self.b), 0.0)
        self.tick = 600
        with unittest.mock.patch.dict("os.environ", {"EDEN_BONDS": "0"}):
            self.run_pass()
        self.assertEqual(self.closeness(self.a, self.b), 0.0)

    async def test_a_dormant_resident_is_left_alone(self):
        self.traits(self.a, sociability=0.9)
        mask = torch.zeros(len(self.engine._human_uid_by_slot), dtype=torch.bool)
        mask[self.engine._human_slot_for_id(self.b)] = True
        self.engine.__dict__["_dormant_h"] = mask
        self.run_pass()
        self.assertEqual(self.closeness(self.a, self.b), 0.0)


class Places(Village):
    async def test_marked_places_are_stored_in_the_record_and_move_with_a_rebase(self):
        runner = self.driver.runner(self.engine)
        slot = self.engine._human_slot_for_id(self.a)
        x, y = float(self.h[slot, cfg.X]), float(self.h[slot, cfg.Y])
        result = runner.run(self.a, "mark_place", {"name": "old oak"}, proposer="rules:test")
        self.assertTrue(result.ok, result.code)
        place = self.engine.resident_store.get(self.a)[FIELD]["old oak"]
        self.assertEqual(place["target_place"], {"x": x, "y": y})
        for human_id in self.humans:                                 # the window manager shifts the tensors first, then the plane
            s = self.engine._human_slot_for_id(human_id)
            self.h[s, cfg.X] += 30.0
            self.h[s, cfg.Y] -= 10.0
        counts = rebase_model_plane(self.engine, 30.0, -10.0)
        self.assertGreaterEqual(counts["record_positions"], 1)
        self.assertEqual(self.engine.resident_store.get(self.a)[FIELD]["old oak"]["target_place"], {"x": x + 30.0, "y": y - 10.0})

    async def test_asking_directions_copies_a_place_between_residents(self):
        runner = self.driver.runner(self.engine)
        self.assertTrue(runner.run(self.b, "mark_place", {"name": "mill"}, proposer="rules:test").ok)
        result = runner.run(self.a, "ask_directions", {"target": self.b, "name": "mill"}, proposer="rules:test")
        self.assertTrue(result.ok, result.code)
        self.assertTrue(result.ops[0]["ok"], result.ops)
        told = self.engine.resident_store.get(self.a)[FIELD]["mill"]
        self.assertEqual(told["source"], "told")
        self.assertEqual(told["target_place"], self.engine.resident_store.get(self.b)[FIELD]["mill"]["target_place"])
        self.assertGreater(self.closeness(self.a, self.b), 0.0)


if __name__ == "__main__":
    unittest.main()
