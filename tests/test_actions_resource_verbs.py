"""G-005: the resource-node verbs ``eat_from_node`` and ``gather_from_node`` (``systems/actions/resource_verbs.py``) on a real engine with
``EDEN_MAP_RESOURCES=1``: legality (``can_eat_from_node`` / ``can_gather``), the runner path with the ``ItemPermit`` built from ``produces``, conservation
(items created == stock removed) and the flag-off behaviour (verbs not registered, predicates answer ``not_wired``)."""
import os
import tempfile
import unittest
from unittest import mock

from test_startup_preservation import backend  # noqa: F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation
from test_map_entities import rows_by_id
from test_harness_map_resources import world as map_world
import genesis_config as cfg
from harness.adapter import EngineWorld
from systems.actions import REGISTRY, ActionRunner, EngineRecordOps
from systems.actions.resource_verbs import RESOURCE_REGISTRY, default_registry
from systems.affordance import AffordanceEngine, EngineServices
from systems.map import resources as map_resources

FLAG_ON = {map_resources.FLAG: "1"}


class NodeVerbCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, FLAG_ON)
        env.start()
        self.addCleanup(env.stop)
        self.engine = await map_world(self._tmp.name, True)
        self.rows = rows_by_id(self.engine)
        self.world = EngineWorld(self.engine, seed=1008)
        self.services = EngineServices(self.engine)
        self.runner = ActionRunner(self.world, self.services, aff=AffordanceEngine(self.world, self.services, driver_mode="agent"),
                                   record_ops=EngineRecordOps(self.engine))
        self.h, self.m = self.engine.state.h_tensor, self.engine.state.m_tensor
        slot = self.h[:, cfg.TYPE].eq(cfg.AGENT_TYPE_HUMAN).nonzero(as_tuple=False).flatten().tolist()[0]
        self.slot, self.who = slot, self.engine._human_uid_by_slot[slot]

    def stand_at(self, node_id, offset=0.0):
        self.h[self.slot, cfg.X] = self.m[self.rows[node_id], cfg.CX] + offset
        self.h[self.slot, cfg.Y] = self.m[self.rows[node_id], cfg.CY]

    def items(self, kind):
        return self.world.items.quantity(self.who, kind)


class NodeVerbs(NodeVerbCase):
    async def test_the_registry_has_the_node_verbs_only_while_the_flag_is_on(self):
        self.enterContext(mock.patch.dict(os.environ, {"EDEN_MARKET": "0", "EDEN_CREDIT": "0", "EDEN_LABOUR": "0", "EDEN_JUSTICE": "0"}))     # the economy registries have their own flags
        self.assertEqual(sorted(RESOURCE_REGISTRY.actions), ["approach_node", "eat_from_node", "gather_from_node"])
        self.assertIn("gather_from_node", self.runner.registry.actions)
        self.assertIn("eat_from_node", default_registry().actions)
        self.assertEqual(len(REGISTRY.actions), len(default_registry().actions) - 3)                  # the S1 registry itself is untouched
        with mock.patch.dict(os.environ, {map_resources.FLAG: "0"}):
            self.assertIs(default_registry(), REGISTRY)
            self.assertNotIn("gather_from_node", self.runner.registry.actions)
            self.stand_at("bush_01")
            self.assertEqual(self.runner.run(self.who, "gather_from_node", {"node": "bush_01"}).code, "unknown_action")
            verdict = self.runner.aff.legal(self.who, "gather_from_node", {"node": "bush_01"})
            self.assertEqual((verdict.ok, verdict.reason), (False, "not_wired"))
            self.assertEqual(self.runner.aff.options(self.who, verbs=("gather_from_node", "eat_from_node")), [])

    async def test_eat_from_a_node_uses_the_legacy_numbers_and_creates_no_item(self):
        self.stand_at("bush_01")
        self.h[self.slot, cfg.HUNGER] = 55.0
        food = float(self.m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD])
        berries = self.items("berries")
        result = self.runner.run(self.who, "eat_from_node", {"node": "bush_01"})
        self.assertTrue(result.ok, (result.code, result.detail))
        self.assertEqual(float(self.h[self.slot, cfg.HUNGER]), 55.0 - cfg.EAT_HUNGER_RESTORE)
        self.assertEqual(float(self.m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD]), food - cfg.EAT_RESOURCE_COST)
        self.assertEqual(self.items("berries"), berries)

    async def test_eat_is_refused_when_far_not_hungry_or_not_edible(self):
        self.h[self.slot, cfg.HUNGER] = 55.0
        self.stand_at("bush_01", offset=60.0)
        far = self.runner.run(self.who, "eat_from_node", {"node": "bush_01"})
        self.assertEqual((far.ok, far.code), (False, "illegal:out_of_range"))
        self.stand_at("bush_01")
        self.h[self.slot, cfg.HUNGER] = 5.0
        self.assertEqual(self.runner.run(self.who, "eat_from_node", {"node": "bush_01"}).code, "illegal:not_needed")
        self.h[self.slot, cfg.HUNGER] = 55.0
        self.stand_at("ore_01")
        ore = self.runner.run(self.who, "eat_from_node", {"node": "ore_01"})
        self.assertEqual((ore.ok, ore.code), (False, "illegal:no_edible"))
        self.assertEqual(self.runner.run(self.who, "eat_from_node", {"node": "nothing_here"}).code, "ungrounded_target")

    async def test_gather_moves_stock_to_items_under_the_runner_built_permit_and_conserves(self):
        self.stand_at("ore_01")
        item = map_resources.ITEM["ore"]
        stock, held, total = float(self.m[self.rows["ore_01"], cfg.M_NODE_STOCK]), self.items(item), self.world.items.total(item)
        result = self.runner.run(self.who, "gather_from_node", {"node": "ore_01", "qty": 2})
        self.assertTrue(result.ok, (result.code, result.detail))
        self.assertEqual(result.draft.produces, ((item, 2),))
        self.assertEqual(float(self.m[self.rows["ore_01"], cfg.M_NODE_STOCK]), stock - 2)
        self.assertEqual(self.items(item), held + 2)
        self.assertEqual(self.world.items.total(item), total + 2)               # items created == stock units removed
        self.assertEqual(result.report.created.get(item), 2)

    async def test_gather_validation(self):
        self.stand_at("ore_01")
        self.assertEqual(self.runner.run(self.who, "gather_from_node", {"node": "ore_01", "qty": 0}).code, "illegal:invalid_params")
        too_many = self.runner.run(self.who, "gather_from_node", {"node": "ore_01", "qty": 10_000})
        self.assertEqual((too_many.ok, too_many.code), (False, "illegal:no_source"))
        self.assertEqual(too_many.detail.get("node_reason"), "empty")
        self.stand_at("ore_01", offset=80.0)
        self.assertEqual(self.runner.run(self.who, "gather_from_node", {"node": "ore_01"}).code, "illegal:out_of_range")

    async def test_options_and_the_macro_mask_follow_the_reach(self):
        aff = self.runner.aff
        self.stand_at("bush_01", offset=60.0)
        self.assertEqual(aff.options(self.who, verbs=("gather_from_node",)), [])
        self.stand_at("bush_01")
        options = aff.options(self.who, verbs=("gather_from_node",))
        self.assertIn("bush_01", [o.params["node"] for o in options])
        self.h[self.slot, cfg.HUNGER] = 55.0
        self.assertIn("bush_01", [o.params["node"] for o in aff.options(self.who, verbs=("eat_from_node",))])
        from systems.decision.matrix import ACTION_INDEX
        mask = aff.mask([self.who])
        self.assertTrue(bool(mask[0, ACTION_INDEX["gather"]]))
        self.stand_at("bush_01", offset=60.0)
        self.assertNotIn("bush_01", [o.params["node"] for o in aff.options(self.who, verbs=("gather_from_node",))])


class ApproachNode(NodeVerbCase):
    async def test_a_node_in_sight_but_out_of_reach_is_approachable_and_one_in_reach_is_not(self):
        aff = self.runner.aff
        self.stand_at("bush_01", offset=10.0)
        far = aff.legal(self.who, "approach_node", {"node": "bush_01"})
        self.assertTrue(far.ok, (far.reason, far.detail))
        self.assertIn("bush_01", [o.params["node"] for o in aff.options(self.who, verbs=("approach_node",))])
        self.stand_at("bush_01")
        near = aff.legal(self.who, "approach_node", {"node": "bush_01"})
        self.assertEqual((near.ok, near.reason), (False, "in_reach"))
        self.assertNotIn("bush_01", [o.params["node"] for o in aff.options(self.who, verbs=("approach_node",))])
        self.stand_at("bush_01", offset=10.0)
        unknown = aff.legal(self.who, "approach_node", {"node": "no_such_node"})            # (the test map is 20 x 16: everything is in sight)
        self.assertEqual((unknown.ok, unknown.reason), (False, "no_source"))

    async def test_an_empty_node_is_not_approachable_and_the_flag_off_answers_not_wired(self):
        self.stand_at("ore_01", offset=-10.0)
        self.m[self.rows["ore_01"], cfg.M_NODE_STOCK] = 0.0
        self.assertEqual(self.runner.aff.legal(self.who, "approach_node", {"node": "ore_01"}).reason, "no_source")
        self.stand_at("bush_01", offset=10.0)
        with mock.patch.dict(os.environ, {map_resources.FLAG: "0"}):
            verdict = self.runner.aff.legal(self.who, "approach_node", {"node": "bush_01"})
            self.assertEqual((verdict.ok, verdict.reason), (False, "not_wired"))

    async def test_the_gather_macro_offers_the_approach_only_out_of_reach(self):
        aff = self.runner.aff
        self.stand_at("ore_01", offset=-10.0)
        far = [(o.verb, o.params.get("node")) for o in aff.macro_options(self.who, "gather")]
        self.assertIn(("approach_node", "ore_01"), far)
        self.stand_at("ore_01")
        near = [(o.verb, o.params.get("node")) for o in aff.macro_options(self.who, "gather")]
        self.assertIn(("gather_from_node", "ore_01"), near)
        self.assertNotIn(("approach_node", "ore_01"), near)

    async def test_the_runner_queues_a_point_task_and_the_resident_walks_into_reach_then_gathers(self):
        self.stand_at("ore_01", offset=-10.0)
        result = self.runner.run(self.who, "approach_node", {"node": "ore_01"}, proposer="tier1:rules")
        self.assertTrue(result.ok, (result.code, result.detail))
        record = self.engine.resident_store.get(self.who)
        task = next(t for t in record["tasks"] if t["task_kind"] == "move_to_place")
        self.assertEqual(task["target_kind"], "point")
        self.assertEqual((task["target_place"]["x"], task["target_place"]["y"]),
                         (float(self.m[self.rows["ore_01"], cfg.CX]), float(self.m[self.rows["ore_01"], cfg.CY])))
        for _ in range(200):
            self.engine.step()
            if self.runner.aff.legal(self.who, "gather_from_node", {"node": "ore_01"}).ok:
                break
        gathered = self.runner.run(self.who, "gather_from_node", {"node": "ore_01"})
        self.assertTrue(gathered.ok, (gathered.code, gathered.detail))


if __name__ == "__main__":
    unittest.main()
