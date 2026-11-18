"""Affordance engine on the real booted Stage 1 engine: commission parity with ``systems/commission``, real-world options, read-only
behaviour, dead residents, walls (detour and sealed target), and the Tier 1 mask for the 8 residents."""
from authored_village import load_village_maps
import copy
import hashlib
import json
import unittest
from driver_pin import pin_anchor

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from harness.adapter import EngineWorld
from systems.affordance import AffordanceEngine, EngineServices, Reach
from systems.affordance.testing import WalledServices, box
from systems.commission.config import COMMISSION_CONFIG
from systems.commission.decide import legal_options as stage1_legal_options
from systems.commission.engine import context, env_for, find_smith
from systems.commission.facts import commission_facts as stage1_facts
from systems.commission.lifecycle import create_order
from systems.commission.orders import get_order
from systems.decision.matrix import ACTION_INDEX, MENU
from systems.inventory.ops import remove_item


def digest(engine):
    parts = [engine.state.h_tensor.numpy().tobytes(), engine.state.m_tensor.numpy().tobytes(),
             json.dumps(engine.inventory_state, sort_keys=True, default=str).encode()]
    return hashlib.sha256(b"".join(parts)).hexdigest()


class RealEngineCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.world = EngineWorld(self.engine, seed=1008)
        self.services = EngineServices(self.engine)
        self.aff = AffordanceEngine(self.world, self.services)
        self.agent = AffordanceEngine(self.world, self.services, driver_mode="agent")      # the world's answer, without the roster driver table (driver.py)
        self.smith, _ = find_smith(self.engine)
        self.by_key = {self.engine.resident_store.get(u)["roster"]["key"]: u for u in self.engine._human_uid_by_slot if u}
        self.residents = [u for u in self.engine._human_uid_by_slot if u]

    def slot(self, human):
        return self.engine._human_slot_for_id(human)

    def put(self, human, x, y):
        self.engine.state.h_tensor[self.slot(human), cfg.X] = x
        self.engine.state.h_tensor[self.slot(human), cfg.Y] = y


class CommissionParityTests(RealEngineCase):
    def stage1_for(self, customer, order_id):
        ctx = context(self.engine)
        order = get_order(ctx, order_id)
        facts = stage1_facts(ctx, order, env_for(self.engine, self.smith, customer))
        return stage1_legal_options(facts)

    def scenario(self, name, expected, mutate, customer_key="iven"):
        customer = self.by_key[customer_key]
        ctx = context(self.engine)
        created = create_order(ctx, customer, self.smith, "sword", None, env_for(self.engine, self.smith, customer))
        self.assertTrue(created["ok"], (name, created))
        order_id = created["order_id"]
        saved = (copy.deepcopy(self.engine.inventory_state), self.engine.state.h_tensor.clone(), self.engine.state.m_tensor.clone(),
                 copy.deepcopy(self.engine.resident_store.get(self.smith)["relationships"]))
        try:
            mutate(ctx, order_id)
            stage1 = self.stage1_for(customer, order_id)
            ours = self.aff.commission_options(self.smith, customer, "sword", exclude_order=order_id)
            self.assertEqual(ours, stage1, f"{name}: affordance {ours} vs Stage 1 {stage1}")
            self.assertEqual(stage1, expected, f"{name}: Stage 1 itself changed")
        finally:
            self.engine.inventory_state.clear()
            self.engine.inventory_state.update(saved[0])
            self.engine.state.h_tensor.copy_(saved[1])
            self.engine.state.m_tensor.copy_(saved[2])
            self.engine.resident_store.get(self.smith)["relationships"].clear()
            self.engine.resident_store.get(self.smith)["relationships"].update(saved[3])

    def smith_inventory(self):
        return self.engine._human_inventory_record(self.smith)

    def forge_slot(self):
        return self.engine._entity_uid_by_slot.index("smith:forge")

    def test_smith_commission_parity_over_every_branch(self):
        customer = self.by_key["iven"]
        iven_slot = self.slot(customer)

        def nothing(ctx, order_id):
            pass

        def no_iron(ctx, order_id):
            remove_item(self.smith_inventory(), "iron_ingot", 4)

        def one_iron(ctx, order_id):
            remove_item(self.smith_inventory(), "iron_ingot", 3)            # 1 left, the sword needs 2

        def no_wood(ctx, order_id):
            remove_item(self.smith_inventory(), "wood_bundle", 4)

        def poor_customer(ctx, order_id):
            remove_item(self.engine._human_inventory_record(customer), "coin", 20)   # 20 left, price 30

        def forge_wrecked(ctx, order_id):
            self.engine.state.m_tensor[self.forge_slot(), cfg.M_HP] = 0.0

        def forge_gone(ctx, order_id):
            self.engine.state.m_tensor[self.forge_slot(), cfg.M_TYPE] = 0.0

        def busy(ctx, order_id):
            for key in ("builder", "gatherer"):
                other = create_order(ctx, self.by_key[key], self.smith, "sword", None, env_for(self.engine, self.smith, self.by_key[key]))
                self.assertTrue(other["ok"])

        def distrust(ctx, order_id):
            self.engine.resident_store.update_relationship(self.smith, customer, "customer", -0.6, self.engine.tick)

        def rival(ctx, order_id):
            self.engine.resident_store.get(self.smith)["relationships"].setdefault(customer, {})["tags"] = ["rival"]

        def smith_dead(ctx, order_id):
            self.engine.state.h_tensor[self.slot(self.smith), cfg.HP] = 0.0

        def several(ctx, order_id):
            no_iron(ctx, order_id), poor_customer(ctx, order_id), forge_wrecked(ctx, order_id), distrust(ctx, order_id)

        self.scenario("baseline", ["accept_commission"], nothing)
        self.scenario("no iron", ["refuse_no_materials"], no_iron)
        self.scenario("one iron (needs two)", ["refuse_no_materials"], one_iron)
        self.scenario("no wood", ["refuse_no_materials"], no_wood)
        self.scenario("customer cannot afford", ["refuse_cannot_afford"], poor_customer)
        self.scenario("forge wrecked", ["refuse_no_forge"], forge_wrecked)
        self.scenario("forge entity gone", ["refuse_no_forge"], forge_gone)
        self.scenario("busy (two other open orders)", ["refuse_busy"], busy)
        self.scenario("distrust", ["accept_commission", "refuse_distrust"], distrust)
        self.scenario("rival", ["accept_commission", "refuse_distrust"], rival)
        self.scenario("smith dead", ["refuse_busy"], smith_dead)
        self.scenario("several reasons at once", ["refuse_no_forge", "refuse_no_materials", "refuse_cannot_afford", "refuse_distrust"], several)
        self.assertEqual(iven_slot, self.slot(customer))

    def test_mask_columns_follow_the_offered_order(self):
        customer = self.by_key["iven"]
        smith_row = self.residents.index(self.smith)
        mask = self.aff.mask(self.residents)
        for name in ("accept_commission", "refuse_no_materials", "refuse_busy"):
            self.assertFalse(bool(mask[smith_row, ACTION_INDEX[name]]), name)               # no order yet
        ctx = context(self.engine)
        order = create_order(ctx, customer, self.smith, "sword", None, env_for(self.engine, self.smith, customer))
        mask = self.aff.mask(self.residents)
        expected = set(stage1_legal_options(stage1_facts(ctx, get_order(ctx, order["order_id"]), env_for(self.engine, self.smith, customer))))
        got = {n for n in ("accept_commission", "refuse_no_materials", "refuse_no_forge", "refuse_cannot_afford", "refuse_busy",
                           "refuse_distrust") if bool(mask[smith_row, ACTION_INDEX[n]])}
        self.assertEqual(got, expected)
        other = self.residents.index(self.by_key["builder"])
        self.assertFalse(bool(mask[other, ACTION_INDEX["accept_commission"]]))


class RealWorldOptionTests(RealEngineCase):
    def test_reads_change_nothing(self):
        before = digest(self.engine)
        self.aff.mask(self.residents)
        for h in self.residents:
            self.aff.options(h, include_illegal=True)
        self.assertEqual(digest(self.engine), before)

    def test_mask_for_the_eight_residents(self):
        mask = self.aff.mask(self.residents)
        self.assertEqual(tuple(mask.shape), (8, len(MENU)))
        self.assertTrue(bool(mask[:, ACTION_INDEX["idle"]].all()))
        self.assertFalse(bool(mask[:, ACTION_INDEX["repair"]].any()))
        self.assertFalse(bool(mask[:, ACTION_INDEX["eat"]].any()), "nobody is hungry at tick 0")
        for key in ("smith", "builder"):
            self.assertTrue(bool(mask[self.residents.index(self.by_key[key]), ACTION_INDEX["go_home"]]), key)

    def test_hungry_resident_is_offered_the_pack_ration_and_the_far_smith_the_campfire(self):
        iven, smith = self.by_key["iven"], self.smith
        for h in (iven, smith):
            self.engine.state.h_tensor[self.slot(h), cfg.HUNGER] = 70.0
        iven_eat = self.aff.legal(iven, "eat", {})
        self.assertEqual((iven_eat.ok, iven_eat.detail), (True, {"source": "pack", "item": "rations"}))
        smith_eat = self.agent.legal(smith, "eat", {})
        self.assertTrue(smith_eat.ok, smith_eat)
        self.assertEqual(self.aff.legal(smith, "eat", {}).reason, "roster_driven")      # the roster needs loop walks him there, not an action
        self.assertEqual(smith_eat.detail, {"source": "site", "place": "village:use_campfire"})    # no ration: the roster food site, across a portal
        self.assertTrue(60.0 < smith_eat.distance < 200.0, smith_eat.distance)     # interior to the portal, then door to campfire

    def test_drink_goes_to_the_well_site(self):
        iven = self.by_key["iven"]
        self.engine.state.h_tensor[self.slot(iven), cfg.THIRST] = 60.0
        verdict = self.agent.legal(iven, "drink", {})
        self.assertEqual((verdict.ok, verdict.detail["place"]), (True, "village:use_well"))
        self.assertEqual(self.aff.legal(iven, "drink", {}).reason, "roster_driven")

    def test_dead_resident_on_the_real_engine(self):
        victim = self.by_key["gatherer"]
        self.engine.state.h_tensor[self.slot(victim), cfg.HP] = 0.0
        self.assertEqual(self.aff.options(victim), [])
        row = self.aff.mask(self.residents)[self.residents.index(victim)]
        self.assertFalse(bool(row.any()))
        self.assertEqual(self.aff.legal(self.by_key["builder"], "greet", {"target": victim}).reason, "target_dead")

    def test_gather_nodes_and_give_item_range(self):
        gatherer, builder = self.by_key["gatherer"], self.by_key["builder"]
        nodes = {o.params["source"] for o in self.agent.options(gatherer, verbs=("gather_resource",))}
        self.assertEqual(self.aff.options(gatherer, verbs=("gather_resource",)), [])         # roster driver: gathering is demoted
        self.assertTrue({"village:wood_pile", "village:berry_patch"} <= nodes, nodes)
        ok = self.aff.legal(builder, "give_item", {"target": gatherer, "item": "coin", "qty": 5})
        self.assertTrue(ok.ok, ok)                                       # 4.8 units apart in the start crowd
        self.put(gatherer, 230.0, 160.0)                                 # 46 units away: perceived, not within reach of an immediate hand-over
        self.assertEqual(self.aff.legal(builder, "give_item", {"target": gatherer, "item": "coin", "qty": 5}).reason, "out_of_range")
        self.assertTrue(self.aff.legal(builder, "chat", {"target": gatherer}).ok)

    def test_a_target_behind_a_wall_needs_a_detour_not_a_straight_line(self):
        builder, gatherer = self.by_key["builder"], self.by_key["gatherer"]
        self.put(builder, 150.0, 160.0)
        self.put(gatherer, 220.0, 160.0)                                  # 70 apart, both in the open village
        wall = box("test_wall", 183.0, 120.0, 187.0, 200.0)               # a vertical wall x=185, y 120..200 between them
        services = WalledServices(self.engine, [wall])
        aff = AffordanceEngine(self.world, services)
        from systems.movement.spatial import segment_blocked
        self.assertTrue(segment_blocked((150.0, 160.0), (220.0, 160.0), services.contract()["boxes"]), "the straight line must be blocked")
        verdict = aff.legal(builder, "chat", {"target": gatherer})
        self.assertTrue(verdict.ok, verdict)
        self.assertEqual(verdict.reachability, "exact")
        self.assertGreater(verdict.distance, 70.0 + 20.0)                  # round the wall's end: clearly longer than 70
        self.assertEqual(aff.reach.stats["path_searches"], 1)
        # without the pathing the same question is answered "blocked/unreachable": exactly where straight-line mislabels
        straight_only = AffordanceEngine(self.world, services, Reach(services, max_expansions=1))
        self.assertFalse(straight_only.legal(builder, "chat", {"target": gatherer}).ok)

    def test_a_sealed_target_is_unreachable(self):
        builder, gatherer = self.by_key["builder"], self.by_key["gatherer"]
        self.put(builder, 150.0, 160.0)
        self.put(gatherer, 220.0, 160.0)
        cx, cy, h, t = 220.0, 160.0, 10.0, 1.0
        cage = [box("c_n", cx - h, cy - h, cx + h, cy - h + t), box("c_s", cx - h, cy + h - t, cx + h, cy + h),
                box("c_w", cx - h, cy - h, cx - h + t, cy + h), box("c_e", cx + h - t, cy - h, cx + h, cy + h)]
        aff = AffordanceEngine(self.world, WalledServices(self.engine, cage))
        verdict = aff.legal(builder, "follow", {"target": gatherer})
        self.assertEqual((verdict.ok, verdict.reason), (False, "unreachable"))
        self.assertEqual(verdict.reachability, "exact")                    # the sealed pocket is small: the search finishes
        self.assertEqual([o for o in aff.options(builder, verbs=("chat",)) if o.params["target"] == gatherer], [])

    def test_perception_radius_on_the_real_map(self):
        smith = self.smith
        seen = {n.id for n in self.aff.observation(smith).neighbours}
        self.assertEqual(seen, set(), "the smith is alone in his interior (the others are 400+ units away)")
        builder_seen = {n.id for n in self.aff.observation(self.by_key["builder"]).neighbours}
        self.assertNotIn(smith, builder_seen)
        self.assertEqual(self.aff.legal(self.by_key["builder"], "chat", {"target": smith}).reason, "no_target")
