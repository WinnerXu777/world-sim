"""G-005 step 3: node regrow as a harness system (bit-for-bit with the legacy function), eat_from_node and gather as effect builders."""
import os
import random
import tempfile
import unittest
from unittest import mock

import torch

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation
from test_map_entities import rows_by_id
from test_harness_map_resources import NAME, world as map_world
import genesis_config as cfg
from harness import effects as fx
from harness import engine_hooks, resources
from simulation.dispatch import DISPATCH
from systems.map import resources as map_resources
from systems.nature import ecology


def harness_world(engine):
    return engine_hooks.runtime(engine).world


def free_slots(engine, count):
    m = engine.state.m_tensor
    return (m[:, cfg.M_TYPE] == 0).nonzero(as_tuple=False).flatten().tolist()[:count]


def random_nodes(engine, seed, count=40):
    """Overwrite ``count`` free rows with random resource nodes (all kinds, burning, empty, full, depleted, no rate) and give them ids."""
    rng = random.Random(seed)
    m = engine.state.m_tensor
    ids = []
    for i, slot in enumerate(free_slots(engine, count)):
        kind = rng.randint(1, 7)
        cap = rng.choice([0.0, 5.0, 40.0, 100.0, 500.0])
        stock = rng.choice([0.0, 0.3, rng.uniform(0, cap or 1.0), cap, cap * 1.1])
        m[slot] = 0.0
        m[slot, cfg.M_TYPE] = float(cfg.M_RESOURCE_NODE)
        m[slot, cfg.CX], m[slot, cfg.CY] = rng.uniform(0, 400), rng.uniform(0, 400)
        m[slot, cfg.SCALE] = 6.0
        m[slot, cfg.M_NODE_KIND] = float(kind)
        m[slot, cfg.M_NODE_CAP] = cap
        m[slot, cfg.M_GROWTH_RATE] = rng.choice([0.0, 0.003, 0.02, 0.5, rng.uniform(0, 1)])
        m[slot, cfg.M_BURNING] = rng.choice([0.0, 0.0, 0.0, 3.0])
        m[slot, cfg.M_DEPLETED_TICK] = rng.choice([-1.0, -1.0, 12.0])
        column = cfg.M_RESOURCE_FOOD if kind in (1, 5, 7) else cfg.M_NODE_STOCK
        m[slot, column] = stock
        engine._entity_uid_by_slot[slot] = f"rn_{seed}_{i}"
        ids.append(f"rn_{seed}_{i}")
    engine._entity_count_ref[0] = max(engine._entity_count_ref[0], max(free_slots(engine, 0) or [0]), int(m[:, cfg.M_TYPE].nonzero().max()) + 1)
    return ids


class NodeBase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    async def make(self):
        engine = await map_world(self._tmp.name, True)
        self.engine, self.rows = engine, rows_by_id(engine)
        self.addCleanup(resources.uninstall, engine)
        self.w = harness_world(engine)
        return engine

    def resident(self):
        slot = self.engine.state.h_tensor[:, cfg.TYPE].eq(cfg.AGENT_TYPE_HUMAN).nonzero(as_tuple=False).flatten().tolist()[0]
        return self.engine._human_uid_by_slot[slot], slot

    def put_at(self, slot, uid):
        node = self.rows[uid]
        self.engine.state.h_tensor[slot, cfg.X] = self.engine.state.m_tensor[node, cfg.CX]
        self.engine.state.h_tensor[slot, cfg.Y] = self.engine.state.m_tensor[node, cfg.CY]


class RegrowEquivalenceTests(NodeBase):
    async def test_matches_the_legacy_function_bit_for_bit_on_random_states(self):
        engine = await self.make()
        for seed in range(30):
            random_nodes(engine, seed)
            m = engine.state.m_tensor
            for multiplier in (1.0, 0.0, 2.5):
                legacy = m.clone()
                ecology.apply_node_regrow(legacy, food_multiplier=multiplier)
                before_revision = self.w.revision
                written = resources.regrow_nodes(self.w, food_multiplier=multiplier)
                self.assertIsNotNone(written)
                self.assertTrue(torch.equal(legacy, m), f"seed {seed} multiplier {multiplier}")
                self.assertGreaterEqual(self.w.revision, before_revision)
                m.copy_(legacy)

    async def test_recovered_nodes_clear_depleted_tick_and_emit_once(self):
        engine = await self.make()
        m = engine.state.m_tensor
        node = self.rows["bush_01"]
        m[node, cfg.M_RESOURCE_FOOD] = 0.0
        m[node, cfg.M_DEPLETED_TICK] = 9.0
        resources.regrow_nodes(self.w)
        self.assertEqual(float(m[node, cfg.M_DEPLETED_TICK]), -1.0)
        seen = [e for e in self.w.events.events() if e.type == "resource_regrown"]
        self.assertEqual([e.actors for e in seen], [("bush_01",)])
        resources.regrow_nodes(self.w)
        self.assertEqual(len([e for e in self.w.events.events() if e.type == "resource_regrown"]), 1)

    async def test_a_world_without_nodes_does_nothing(self):
        engine = await self.make()
        m = engine.state.m_tensor
        m[m[:, cfg.M_TYPE] == cfg.M_RESOURCE_NODE] = 0.0
        revision = self.w.revision
        self.assertEqual(resources.regrow_nodes(self.w), 0)
        self.assertEqual(self.w.revision, revision)

    async def test_a_node_without_a_stable_id_returns_none(self):
        engine = await self.make()
        engine._entity_uid_by_slot[self.rows["bush_01"]] = None
        engine.state.m_tensor[self.rows["bush_01"], cfg.M_RESOURCE_FOOD] = 1.0
        self.assertIsNone(resources.regrow_nodes(self.w))


class InstallTests(NodeBase):
    async def run_ticks(self, flag, ticks=12):
        """Boot a world with or without the flagged install, step it, and return the per-tick node values and the expected ones."""
        flags = {"EDEN_HARNESS": "1", resources.FLAG: "1"}
        with mock.patch.dict(os.environ, flags if flag else {}, clear=False):
            if not flag:
                os.environ.pop(resources.FLAG, None)
            engine_hooks.install(DISPATCH)
            try:
                engine = await self.make()
                names = [getattr(e["fn"], "__name__", "") for e in engine._registry]
                self.assertEqual("instinct_resource_regrow_nodes" in names, flag)
                self.assertEqual(engine.node_regrow_external, flag)
                m = engine.state.m_tensor
                bush, ore = self.rows["bush_01"], self.rows["ore_01"]
                m[bush, cfg.M_RESOURCE_FOOD], m[ore, cfg.M_NODE_STOCK] = 3.0, 3.0
                m[bush, cfg.M_DEPLETED_TICK] = m[ore, cfg.M_DEPLETED_TICK] = 4.0
                seen = []
                for _ in range(ticks):
                    before = (m[bush, cfg.M_RESOURCE_FOOD].clone(), m[ore, cfg.M_NODE_STOCK].clone())
                    engine.step()
                    mult = float(engine._nature_state["modifiers"].get("food_growth", 1.0))
                    want = (torch.minimum(before[0] + m[bush, cfg.M_GROWTH_RATE] * mult, m[bush, cfg.M_NODE_CAP]),
                            torch.minimum(before[1] + m[ore, cfg.M_GROWTH_RATE] * mult, m[ore, cfg.M_NODE_CAP]))
                    seen.append((float(m[bush, cfg.M_RESOURCE_FOOD]) == float(want[0]), float(m[ore, cfg.M_NODE_STOCK]) == float(want[1])))
                return seen, [float(m[bush, cfg.M_DEPLETED_TICK]), float(m[ore, cfg.M_DEPLETED_TICK])], float(m[bush, cfg.M_RESOURCE_FOOD])
            finally:
                engine_hooks.uninstall(DISPATCH)
                if hasattr(self, "engine") and hasattr(self.engine, "harness"):
                    del self.engine.harness

    async def test_flagged_install_regrows_like_the_legacy_entry_every_tick(self):
        for flag in (False, True):
            seen, depleted, food = await self.run_ticks(flag)
            self.assertTrue(all(a and b for a, b in seen), f"flag={flag}: {seen}")      # each tick equals min(before + rate*mult, cap) in float32
            self.assertEqual(depleted, [-1.0, -1.0])
            self.assertGreater(food, 3.0)

    async def test_install_is_idempotent_and_switches_legacy_node_regrow_off(self):
        engine = await self.make()
        self.assertFalse(getattr(engine, "node_regrow_external", False))
        self.assertTrue(resources.install(engine))
        self.assertTrue(resources.install(engine))
        self.assertTrue(engine.node_regrow_external)
        self.assertEqual(len([e for e in engine._registry if getattr(e["fn"], "__name__", "") == "instinct_resource_regrow_nodes"]), 1)
        m = engine.state.m_tensor
        m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD] = 1.0
        ecology.apply_resource_regrow(m, include_nodes=not engine.node_regrow_external)    # what the legacy entry now does
        self.assertEqual(float(m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD]), 1.0)
        resources.uninstall(engine)
        self.assertFalse(engine.node_regrow_external)
        self.assertFalse([e for e in engine._registry if getattr(e["fn"], "__name__", "") == "instinct_resource_regrow_nodes"])

    def test_manifest_lists_the_system(self):
        spec = resources.REGISTRY.systems["resource_regrow_nodes"]
        self.assertEqual(spec.phase, "world")
        self.assertIn("entities.node_stock", spec.writes)


class EatTests(NodeBase):
    async def test_eat_uses_the_legacy_numbers_and_creates_no_item(self):
        await self.make()
        who, slot = self.resident()
        self.put_at(slot, "bush_01")
        h, m = self.engine.state.h_tensor, self.engine.state.m_tensor
        h[slot, cfg.HUNGER] = 55.0
        draft = resources.eat_from_node(self.w, who, "bush_01")
        self.assertEqual(draft.produces, ())
        self.assertEqual(draft.consumes, ())
        report = self.w.apply(draft.effects, atomic=True, cause="test")
        self.assertTrue(report.ok, report.skipped)
        self.assertEqual(float(h[slot, cfg.HUNGER]), 55.0 - cfg.EAT_HUNGER_RESTORE)
        self.assertEqual(float(m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD]), 24.0 - cfg.EAT_RESOURCE_COST)
        self.assertEqual(float(m[self.rows["bush_01"], cfg.M_DEPLETED_TICK]), -1.0)

    async def test_hunger_floors_at_zero_and_food_at_the_unit_left(self):
        await self.make()
        who, slot = self.resident()
        self.put_at(slot, "bush_01")
        h, m = self.engine.state.h_tensor, self.engine.state.m_tensor
        h[slot, cfg.HUNGER] = 21.0
        m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD] = 0.4
        draft = resources.eat_from_node(self.w, who, "bush_01")
        self.assertTrue(self.w.apply(draft.effects, atomic=True, cause="test").ok)
        self.assertEqual(float(h[slot, cfg.HUNGER]), 1.0)
        self.assertEqual(float(m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD]), 0.0)
        self.assertEqual(float(m[self.rows["bush_01"], cfg.M_DEPLETED_TICK]), float(self.w.tick))
        self.assertIn("resource_depleted", [e.type for e in self.w.events.events()])

    async def test_refusals(self):
        await self.make()
        who, slot = self.resident()
        self.put_at(slot, "bush_01")
        h, m = self.engine.state.h_tensor, self.engine.state.m_tensor

        def reason(node="bush_01", actor=who):
            with self.assertRaises(resources.ResourceRefused) as ctx:
                resources.eat_from_node(self.w, actor, node)
            return ctx.exception.reason

        h[slot, cfg.HUNGER] = 10.0
        self.assertEqual(reason(), "not_hungry")
        h[slot, cfg.HUNGER] = 50.0
        self.assertEqual(reason("ore_01"), "not_edible")
        self.assertEqual(reason("forge_01"), "not_a_node")
        self.assertEqual(reason("nothing"), "not_a_node")
        self.assertEqual(reason(actor="nobody"), "no_actor")
        m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD] = 0.0
        self.assertEqual(reason(), "empty")
        m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD] = 5.0
        h[slot, cfg.X] += 500.0
        self.assertEqual(reason(), "too_far")


class GatherTests(NodeBase):
    async def test_gather_moves_stock_to_items_under_a_permit(self):
        await self.make()
        who, slot = self.resident()
        self.put_at(slot, "ore_01")
        m = self.engine.state.m_tensor
        draft = resources.gather(self.w, who, "ore_01", qty=2)
        item = map_resources.ITEM["ore"]
        self.assertEqual(draft.produces, ((item, 2),))
        before = self.w.items.quantity(who, item)
        refused = self.w.apply(draft.effects, atomic=True, cause="test")            # no permit: creation is refused, nothing applies
        self.assertFalse(refused.ok)
        self.assertEqual(float(m[self.rows["ore_01"], cfg.M_NODE_STOCK]), 500.0)
        self.assertEqual(self.w.items.quantity(who, item), before)
        permit = fx.ItemPermit(produce={item: 2})
        report = self.w.apply(draft.effects, atomic=True, cause="test", items=permit)
        self.assertTrue(report.ok, report.skipped)
        self.assertEqual(float(m[self.rows["ore_01"], cfg.M_NODE_STOCK]), 498.0)
        self.assertEqual(self.w.items.quantity(who, item), before + 2)
        self.assertEqual(report.created.get(item), 2)

    async def test_items_created_equal_stock_removed(self):
        await self.make()
        who, slot = self.resident()
        self.put_at(slot, "bush_01")
        m = self.engine.state.m_tensor
        item = map_resources.ITEM["berries"]
        start_stock, start_items = float(m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD]), self.w.items.quantity(who, item)
        for qty in (1, 2):
            draft = resources.gather(self.w, who, "bush_01", qty=qty)
            self.assertTrue(self.w.apply(draft.effects, atomic=True, cause="test", items=fx.ItemPermit(produce={item: qty})).ok)
        self.assertEqual(start_stock - float(m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD]), 3.0)
        self.assertEqual(self.w.items.quantity(who, item) - start_items, 3)

    async def test_emptying_a_node_marks_it_depleted_and_emits(self):
        await self.make()
        who, slot = self.resident()
        self.put_at(slot, "bush_01")
        m = self.engine.state.m_tensor
        m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD] = 2.0
        draft = resources.gather(self.w, who, "bush_01", qty=2)
        item = map_resources.ITEM["berries"]
        self.assertTrue(self.w.apply(draft.effects, atomic=True, cause="test", items=fx.ItemPermit(produce={item: 2})).ok)
        self.assertEqual(float(m[self.rows["bush_01"], cfg.M_RESOURCE_FOOD]), 0.0)
        self.assertEqual(float(m[self.rows["bush_01"], cfg.M_DEPLETED_TICK]), float(self.w.tick))
        self.assertEqual([e.type for e in self.w.events.events() if e.type == "resource_depleted"], ["resource_depleted"])

    async def test_refusals(self):
        await self.make()
        who, slot = self.resident()
        self.put_at(slot, "ore_01")

        def reason(qty, node="ore_01"):
            with self.assertRaises(resources.ResourceRefused) as ctx:
                resources.gather(self.w, who, node, qty=qty)
            return ctx.exception.reason

        self.assertEqual(reason(0), "bad_qty")
        self.assertEqual(reason(True), "bad_qty")
        self.assertEqual(reason(2.5), "bad_qty")
        self.assertEqual(reason(501), "empty")
        self.engine.state.m_tensor[self.rows["ore_01"], cfg.M_NODE_STOCK] = 5000.0
        self.assertEqual(reason(300), "no_room")
        self.assertEqual(reason(1, "forge_01"), "not_a_node")
        self.assertEqual(reason(1, "bush_01"), "too_far")

    async def test_the_item_comes_from_the_node_kind(self):
        from systems.inventory.schema import ITEM_KIND_DEFS
        for kind, item in ((1, "berries"), (2, "wood_bundle"), (3, "stone_chunk"), (4, "iron_ore"), (5, "fish_catch"), (6, "reed_bundle"),
                           (7, "mushrooms")):
            self.assertEqual(resources.node_item(kind), item)
            self.assertIn(item, ITEM_KIND_DEFS)          # every node item is a real inventory kind
        self.assertEqual(resources.stock_field(1), "food")
        self.assertEqual(resources.stock_field(4), "node_stock")


if __name__ == "__main__":
    unittest.main()
