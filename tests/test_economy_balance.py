"""Earned stall revenue funds wages without minting coin or lowering the till float."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from collections import Counter

from driver_pin import pin_anchor
from test_market_verbs import MarketScene, STALL
from systems.actions.ladder import Ladder, Errand
from systems.actions import market_day
from systems.actions.labour_verbs import wage_for
from systems.affordance import EntityFact
from test_actions_runner import Scene
import torch


class TillCollection(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = patch.dict(os.environ, {"EDEN_MARKET": "1", "EDEN_ECONOMY_BALANCE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def scene(self, **kwargs):
        s = MarketScene(purse=0, **kwargs)
        self.driver = SimpleNamespace(ladder=Ladder(), routed=Counter(), runner=lambda engine: s.runner)
        self.fact = next(f for f in s.services.entities() if f.id == STALL)
        return s

    def collect(self, s):
        market_day._collect_till(self.driver, None, s.runner, "h_a", self.fact, 0)

    def test_sale_proceeds_become_payable_wages_and_coin_is_conserved(self):
        s = self.scene(till=6)
        s.world.items.remove("h_a", "rations", 2)
        self.assertEqual(wage_for(s.services, "h_a"), ("", 0))
        total = s.total("coin")
        self.collect(s)
        self.assertEqual((s.held("h_a", "coin"), s.held(STALL, "coin")), (4, 2))
        self.assertEqual(s.total("coin"), total)
        self.assertEqual(wage_for(s.services, "h_a"), ("coin", 2))
        self.collect(s)
        self.assertEqual((s.held("h_a", "coin"), s.held(STALL, "coin")), (4, 2))

    def test_default_off_leaves_inventory_and_audit_untouched(self):
        s = self.scene(till=6)
        with patch.dict(os.environ):
            os.environ.pop("EDEN_ECONOMY_BALANCE", None)
            self.assertFalse(market_day.balance_enabled())
            before = s.digest()
            self.collect(s)
            self.assertTrue(s.same(before, s.digest()))
            self.assertFalse(self.driver.routed)

    def test_existing_errand_is_not_interrupted(self):
        s = self.scene(till=6)
        errand = Errand("work", "labour", (20, 10), "h_b", "collect_wage", {}, 800)
        self.driver.ladder.errands["h_a"] = errand
        self.collect(s)
        self.assertIs(self.driver.ladder.errands["h_a"], errand)
        self.assertEqual(s.held(STALL, "coin"), 6)

    def test_capacity_limits_collection_without_losing_coin(self):
        s = self.scene(till=6, capacity=6, stock={})
        total = s.total("coin")
        room = s.world.items.room("h_a", "coin")
        self.collect(s)
        self.assertEqual(s.held("h_a", "coin"), min(4, room))
        self.assertGreaterEqual(s.held(STALL, "coin"), 2)
        self.assertEqual(s.total("coin"), total)

    def test_arrival_refreshes_changed_till_and_does_not_signal_food_relief(self):
        s = self.scene(till=3)
        ladder = self.driver.ladder
        ladder.errands["h_a"] = Errand("till", "fetch", (15, 10), STALL, "fetch_item",
                                       {"container": STALL, "item": "coin", "qty": 4}, 600)
        ladder.arrive(self.driver, None, "h_a", 0)
        self.assertEqual((s.held("h_a", "coin"), s.held(STALL, "coin")), (1, 2))
        self.assertNotIn("h_a", ladder.relieved)
        self.assertNotIn("h_a", ladder.errands)

    def test_out_of_range_keeper_gets_a_bounded_collection_errand(self):
        s = self.scene(till=6)
        s.services._entities = [type(f)(f.id, f.kind, 50.0, 10.0, f.alive, f.interact_radius)
                                if f.id == STALL else f for f in s.services._entities]
        self.fact = next(f for f in s.services.entities() if f.id == STALL)
        with patch.object(self.driver.ladder, "stand_point", return_value=(45.0, 10.0)):
            self.collect(s)
        errand = self.driver.ladder.errands["h_a"]
        self.assertEqual((errand.rung, errand.verb, errand.target), ("till", "fetch_item", STALL))
        self.assertEqual(errand.expires, 1500)
        self.assertEqual(s.held(STALL, "coin"), 6)

    def test_arrival_with_empty_till_or_flag_disabled_cancels(self):
        for flag in ("0", "1"):
            s = self.scene(till=2)
            ladder = self.driver.ladder
            ladder.errands["h_a"] = Errand("till", "fetch", (15, 10), STALL, "fetch_item",
                                           {"container": STALL, "item": "coin", "qty": 4}, 600)
            with patch.dict(os.environ, {"EDEN_ECONOMY_BALANCE": flag}):
                ladder.arrive(self.driver, None, "h_a", 0)
            self.assertEqual(s.held(STALL, "coin"), 2)
            self.assertNotIn("h_a", ladder.errands)


class FarmHarvest(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)
        patcher = patch.dict(os.environ, {"EDEN_MAP_RESOURCES": "1", "EDEN_ECONOMY_BALANCE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def scene(self, capacity=None):
        import genesis_config as cfg
        s = Scene(roster=True, capacity=capacity)
        table = s.world.table("entities")
        table.columns["burning"] = table.tensor.shape[1]
        table.tensor = torch.cat((table.tensor, torch.zeros(table.tensor.shape[0], 1)), dim=1)
        s.world.add_row("entities", "builder:plot", type=cfg.M_FARM, x=15, y=10, hp=100, food=4.5, burning=0)
        s.services._entities.append(EntityFact("builder:plot", "farm_plot", 15, 10, True, 16))
        return s

    def harvest(self, s, **kwargs):
        return s.runner.run("h_a", "harvest_farm", {"farm": "builder:plot", "qty": 3, **kwargs}, proposer="rules:test")

    def test_harvest_draws_from_grown_stock_and_declares_exact_production(self):
        s = self.scene()
        result = self.harvest(s)
        self.assertTrue(result.ok, result.code)
        self.assertEqual(s.world.table("entities").get("builder:plot", "food"), 1.5)
        self.assertEqual(s.world.items.quantity("h_a", "crop_bundle"), 3)
        self.assertEqual(result.report.events[0].payload["qty"], 3)
        self.assertEqual(s.world.items.total("coin"), 0)
        self.assertEqual(wage_for(s.services, "h_a"), ("crop_bundle", 1))
        self.assertEqual(self.harvest(s, qty=2).code, "illegal:no_item")

    def test_out_of_range_harvest_is_refused_without_changing_stock(self):
        s = self.scene()
        humans = s.world.table("humans")
        humans.tensor[humans.slot_of("h_a"), humans.col("x")] = 80
        self.assertEqual(self.harvest(s).code, "illegal:out_of_range")
        self.assertEqual(s.world.table("entities").get("builder:plot", "food"), 4.5)

    def test_cannot_harvest_another_household_or_empty_or_burning_farm(self):
        s = self.scene()
        s.records["h_a"]["roster"]["key"] = "stranger"
        self.assertEqual(self.harvest(s).code, "illegal:not_owner")
        s.records["h_a"]["roster"]["key"] = "builder"
        table = s.world.table("entities")
        slot = table.slot_of("builder:plot")
        table.tensor[slot, table.col("food")] = 0.5
        self.assertEqual(self.harvest(s, qty=1).code, "illegal:no_item")
        table.tensor[slot, table.col("food")] = 4
        table.tensor[slot, table.col("burning")] = 1
        self.assertEqual(self.harvest(s).code, "illegal:no_source")
        self.assertEqual(s.world.items.quantity("h_a", "crop_bundle"), 0)

    def test_capacity_and_invalid_quantity_reject_atomically(self):
        s = self.scene(capacity=6)
        self.assertEqual(self.harvest(s).code, "illegal:no_room")
        for qty in (0, -1, True):
            self.assertEqual(self.harvest(s, qty=qty).code, "illegal:invalid_params")
        self.assertEqual(s.world.table("entities").get("builder:plot", "food"), 4.5)

    def test_flag_off_has_no_action_or_options(self):
        s = self.scene()
        with patch.dict(os.environ, {"EDEN_ECONOMY_BALANCE": "0"}):
            self.assertEqual(self.harvest(s).code, "unknown_action")
            self.assertEqual(s.runner.aff.legal("h_a", "harvest_farm", {"farm": "builder:plot"}).reason, "not_wired")
            self.assertEqual(s.runner.aff.options("h_a", verbs=("harvest_farm",)), [])

    def test_missing_farm_during_travel_cancels_the_errand(self):
        s = self.scene()
        ladder = Ladder()
        ladder.errands["h_a"] = Errand("forage", "harvest", (15, 10), "builder:gone", "harvest_farm", {"farm": "builder:gone", "qty": 3}, 600)
        driver = SimpleNamespace(ladder=ladder, routed=Counter(), runner=lambda engine: s.runner)
        ladder.arrive(driver, None, "h_a", 0)
        self.assertNotIn("h_a", ladder.errands)


class Tier0FoodGate(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)

    def run_needs(self, hunger=50, thirst=35, flag="1", ladder_on=True, starve="0"):
        import genesis_config as cfg
        from systems.actions.agent_driver import _plan_tier0_needs
        h = torch.zeros((1, 32))
        h[0, cfg.HUNGER], h[0, cfg.THIRST] = hunger, thirst
        engine = SimpleNamespace(state=SimpleNamespace(h_tensor=h), world_epoch=0, tick=1)
        state = SimpleNamespace(trips={}, trip_epoch=0, rations=0)
        roster = {"needs_sites": False}
        with patch.dict(os.environ, {"EDEN_ECONOMY_BALANCE": flag, "EDEN_LADDER_STARVE": starve}):
            _plan_tier0_needs(engine, 0, "h_a", roster, state, ladder_on)
        return float(h[0, cfg.HUNGER]), float(h[0, cfg.THIRST]), state.rations

    def test_thirsty_moderately_hungry_resident_gets_water_without_free_food(self):
        self.assertEqual(self.run_needs(), (50.0, 10.0, 1))

    def test_emergency_hunger_and_water_keep_the_existing_rescues(self):
        self.assertEqual(self.run_needs(hunger=90), (65.0, 10.0, 2))

    def test_starvation_mode_never_reintroduces_food_through_thirst(self):
        self.assertEqual(self.run_needs(hunger=99, starve="1"), (99.0, 10.0, 1))

    def test_flag_off_and_ladder_off_keep_legacy_food_and_water(self):
        self.assertEqual(self.run_needs(flag="0"), (25.0, 10.0, 2))
        self.assertEqual(self.run_needs(ladder_on=False), (25.0, 10.0, 2))

    def test_existing_food_trip_finishes_under_the_original_policy(self):
        import genesis_config as cfg
        from systems.roster.needs import plan
        h = torch.zeros((1, 32))
        h[0, cfg.HUNGER] = 50
        engine = SimpleNamespace(state=SimpleNamespace(h_tensor=h), world_epoch=0, tick=1)
        state = SimpleNamespace(trips={"h_a": {"kind": "food", "phase": "walk", "started": 0, "stood": 0}}, trip_epoch=0, rations=0)
        plan(engine, 0, "h_a", {"needs_sites": False}, state, allow_food=False)
        self.assertEqual(float(h[0, cfg.HUNGER]), 25)
        self.assertNotIn("h_a", state.trips)


class RationObservation(unittest.TestCase):
    def test_observation_delegates_unchanged_and_restores_on_exception(self):
        import genesis_config as cfg
        from model_server.economy_audit import FoodRationAudit
        from systems.roster import needs
        h = torch.zeros((1, 32))
        h[0, cfg.HUNGER] = 45
        engine = SimpleNamespace(state=SimpleNamespace(h_tensor=h), tick=11)
        driver = SimpleNamespace(ladder=SimpleNamespace(errands={}))
        audit = FoodRationAudit(engine, {"h_a": "resident"}, driver, 10)
        with patch.object(needs, "ration", return_value="original") as original:
            with self.assertRaises(ValueError):
                with audit:
                    self.assertEqual(needs.ration(engine, 0, "water", {}, None, "h_a"), "original")
                    self.assertEqual(needs.ration(engine, 0, "food", {}, None, "h_a"), "original")
                    raise ValueError("probe ends")
            self.assertIs(needs.ration, original)
            self.assertEqual(original.call_count, 2)
        self.assertEqual(audit.summary()["total"], {"resident": 1})
        self.assertEqual(audit.summary()["tail"], {"resident": 1})
        self.assertEqual(audit.summary()["reasons"], {"thirst_then_food": 1})


if __name__ == "__main__":
    unittest.main()
