"""EDEN_AGENT_ACTIONS (default off): Tier 1 action macros run through ActionRunner with audit entries. With the flag off the driver is untouched."""
from authored_village import load_village_maps
import os
import random
import unittest
from unittest import mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from driver_pin import pin_anchor
from systems.actions.agent_driver import ACTIONS_ENV, AgentDriver, RulesTier1
from systems.roster.driver import runtime


class AgentActions(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in self.humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.h = self.engine.state.h_tensor
        self.by_key = {self.engine.resident_store.get(u)["roster"]["key"]: u for u in self.humans}

    def flag(self, value="1"):
        patcher = mock.patch.dict(os.environ, {ACTIONS_ENV: value})
        patcher.start()
        self.addCleanup(patcher.stop)

    def slot(self, human_id):
        return self.engine._human_slot_for_id(human_id)

    def step(self, n):
        for _ in range(n):
            self.engine.step()

    def pack(self, human_id, kind):
        record = self.engine.resident_store.get(human_id)
        from systems.inventory.queries import total_quantity
        return total_quantity(backend.get_owner_inventory(self.engine.inventory_state, "human", human_id), kind)

    async def test_flag_off_routes_nothing_and_builds_no_runner(self):
        self.flag("0")
        who = self.by_key["iven"]
        self.h[self.slot(who), cfg.HUNGER] = 35.0
        self.step(30)
        self.assertEqual(dict(self.driver.routed), {})
        self.assertIsNone(self.driver._runner_ctx[1])
        self.assertFalse(self.driver.status()["actions"]["enabled"])

    async def test_pack_food_is_eaten_through_the_runner_at_the_trip_threshold_instead_of_a_trip(self):
        self.flag()
        who = self.by_key["iven"]
        rations = self.pack(who, "rations")
        self.assertGreater(rations, 0, "the scenario needs food in the pack")
        trips = runtime(self.engine).trips_done
        self.h[self.slot(who), cfg.HUNGER] = 35.0
        self.step(3)
        self.assertEqual(self.driver.routed.get("eat:ok"), 1, dict(self.driver.routed))
        self.assertLess(float(self.h[self.slot(who), cfg.HUNGER]), 20.0)
        self.assertEqual(self.pack(who, "rations"), rations - 1)
        self.assertEqual(runtime(self.engine).trips_done, trips)
        self.assertNotIn(who, runtime(self.engine).trips)
        entries = [e for e in self.driver.runner(self.engine).audit.entries if e["actor"] == who]
        self.assertEqual([(e["verb"], e["ok"], e["proposer"]) for e in entries], [("eat", True, "tier1:rules")])

    async def test_without_food_in_the_pack_the_trip_still_happens_and_the_miss_is_counted_once(self):
        self.flag()
        who = self.by_key["iven"]
        from systems.actions import EngineRecordOps  # noqa: F401
        inventory = backend.get_owner_inventory(self.engine.inventory_state, "human", who)
        for item in list(inventory["items"]):
            if item["kind"] in ("rations", "fish_catch", "crop_bundle", "berries", "mushrooms"):
                item["quantity"] = 0
        inventory["items"] = [i for i in inventory["items"] if i["quantity"] > 0]
        self.h[self.slot(who), cfg.HUNGER] = 35.0
        self.step(5)
        self.assertEqual(self.driver.routed.get("none:eat"), 1, dict(self.driver.routed))     # cooldown: asked once, not every tick
        self.assertIn(who, runtime(self.engine).trips)

    async def test_rest_goes_through_the_runner_as_the_sleep_task_and_the_driver_yields(self):
        self.flag()
        who = self.by_key["builder"]
        self.h[self.slot(who), cfg.H_STAMINA] = 20.0
        self.driver.cache.clear()
        self.step(12)
        self.assertGreaterEqual(self.driver.routed.get("rest:ok", 0), 1, dict(self.driver.routed))
        record = self.engine.resident_store.get(who)
        self.assertTrue(any(t["task_kind"] == "sleep" for t in record.get("tasks", [])) or self.driver.yielded > 0)
        rests = [e for e in self.driver.runner(self.engine).audit.entries if e["verb"] == "rest"]
        self.assertTrue(rests and all(e["ok"] and e["proposer"] == "tier1:rules" for e in rests))

    async def test_a_macro_nobody_can_run_is_counted_and_cooled_down(self):
        self.flag()
        who = self.by_key["builder"]
        tick = int(self.engine.tick)
        self.assertIsNone(self.driver.route(self.engine, who, "gather", tick))
        self.assertEqual(self.driver.routed["none:gather"], 1)
        self.assertIsNone(self.driver.route(self.engine, who, "gather", tick + 1))               # cooling down: not even counted
        self.assertEqual(self.driver.routed["none:gather"], 1)
        self.assertIsNone(self.driver.route(self.engine, who, "gather", tick + 100))
        self.assertEqual(self.driver.routed["none:gather"], 2)


if __name__ == "__main__":
    unittest.main()
