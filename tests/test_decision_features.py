"""Tier 1 feature builder on the real booted Stage 1 engine: finite, in range, reproducible, perception-bounded, read-only, and the
shadow helper (matrix vs the Stage 1 survival rules) on a seeded headless run."""
from authored_village import load_village_maps
import copy
import json
import os
import unittest
import unittest.mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from harness.adapter import EngineWorld
from systems.affordance import EngineServices
from systems.affordance.services import StaticServices
from systems.decision import features as feat
from systems.decision import matrix
from systems.decision.matrix import FEATURE_INDEX, FEATURES


class FeatureCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.world = EngineWorld(self.engine, seed=1008)
        self.services = EngineServices(self.engine)
        self.residents = [u for u in self.engine._human_uid_by_slot if u]
        self.by_key = {self.engine.resident_store.get(u)["roster"]["key"]: u for u in self.residents}

    def slot(self, human):
        return self.engine._human_slot_for_id(human)

    def put(self, human, x, y):
        self.engine.state.h_tensor[self.slot(human), cfg.X] = x
        self.engine.state.h_tensor[self.slot(human), cfg.Y] = y

    def build(self, residents=None):
        return feat.build_features(self.world, self.services, residents or self.residents)


class SchemaTests(unittest.TestCase):
    def test_columns_are_the_matrix_columns_in_order(self):
        self.assertEqual(tuple(feat.FEATURE_DEFS), FEATURES)
        self.assertEqual(feat.COLUMNS_SCHEMA, matrix.FEATURE_SCHEMA_VERSION)
        self.assertEqual(feat.FEATURE_SCHEMA_VERSION, 2)
        self.assertEqual(set(feat.RANGE), set(FEATURES))

    def test_empty_batch(self):
        from harness.world import World
        world = World.synthetic(seed=1, humans=4, entities=4)
        batch = feat.build_features(world, StaticServices(), [])
        self.assertEqual(tuple(batch.X.shape), (0, matrix.F))
        self.assertEqual(feat.check_ranges(batch), [])


class CalendarTimeColumnTests(unittest.TestCase):
    """``is_night`` keeps its block values while EDEN_CALENDAR is off (schema, weights and goldens untouched) and follows the light curve while it is on."""

    def test_flag_off_is_the_block_value(self):
        from systems.schedule.resolver import tick_to_time_block
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDEN_CALENDAR", None)
            for tick in range(0, 2400, 37):
                block = tick_to_time_block(tick)
                self.assertEqual(feat._time_block_value(tick), 1.0 if block == "night" else 0.5 if block == "dusk" else 0.0, tick)

    def test_flag_on_follows_the_light(self):
        from harness import calendar
        with unittest.mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            values = [feat._time_block_value(t) for t in range(0, 12000, 100)]
            for tick in (0, 3000, 6000, 9000):
                self.assertAlmostEqual(feat._time_block_value(tick), min(1.0, max(0.0, 1.0 - calendar.now(tick).light)))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in values))
        self.assertLess(min(values), 0.2)
        self.assertGreater(max(values), 0.8)
        self.assertTrue(any(0.0 < v < 1.0 and v not in (0.5,) for v in values))      # continuous, not three steps

    def test_the_schema_does_not_change(self):
        self.assertEqual(feat.FEATURE_SCHEMA_VERSION, 2)
        self.assertEqual(tuple(feat.FEATURE_DEFS), FEATURES)


class BuilderTests(FeatureCase):
    def test_eight_residents_finite_in_range_and_shaped(self):
        batch = self.build()
        self.assertEqual(len(self.residents), 8)
        self.assertEqual(tuple(batch.X.shape), (8, matrix.F))
        self.assertEqual(tuple(batch.P.shape), (8, matrix.P_DIM))
        self.assertTrue(bool(batch.alive.all()))
        self.assertEqual(feat.check_ranges(batch), [])
        self.assertTrue(bool(torch.isfinite(batch.X).all()))
        self.assertTrue(bool((batch.X[:, FEATURE_INDEX["one"]] == 1.0).all()))

    def test_reproducible_in_one_process(self):
        a, b = self.build(), self.build()
        self.assertTrue(torch.equal(a.X, b.X))
        self.assertTrue(torch.equal(a.P, b.P))
        self.assertEqual(a.ids, b.ids)

    async def test_reproducible_across_two_seeded_boots(self):
        first = self.build().X.clone()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.world, self.services = EngineWorld(self.engine, seed=1008), EngineServices(self.engine)
        residents = [u for u in self.engine._human_uid_by_slot if u]
        self.assertEqual(residents, self.residents)
        second = feat.build_features(self.world, self.services, residents).X
        self.assertTrue(torch.equal(first, second))

    def test_needs_columns_follow_the_tensor(self):
        iven = self.by_key["iven"]
        h = self.engine.state.h_tensor
        h[self.slot(iven), cfg.HUNGER] = 80.0
        h[self.slot(iven), cfg.THIRST] = 25.0
        h[self.slot(iven), cfg.HP] = 40.0
        h[self.slot(iven), cfg.H_STAMINA] = 10.0
        h[self.slot(iven), cfg.THREAT] = 60.0
        h[self.slot(iven), cfg.MOOD] = 30.0
        row = self.build([iven]).row(iven)
        self.assertAlmostEqual(row["hunger"], 0.80)
        self.assertAlmostEqual(row["thirst"], 0.25)
        self.assertAlmostEqual(row["low_hp"], 0.60)
        self.assertAlmostEqual(row["low_stamina"], 0.90)
        self.assertAlmostEqual(row["threat"], 0.60)
        self.assertAlmostEqual(row["low_mood"], 0.70)

    def test_pack_food_and_places(self):
        smith = self.by_key["smith"]
        row = self.build([smith]).row(smith)
        self.assertEqual(row["has_food_item"], 0.0)                 # the smith carries no ration at boot
        iven = self.by_key["iven"]
        self.assertEqual(self.build([iven]).row(iven)["has_food_item"], 1.0)    # one ration
        self.assertEqual(self.build([iven]).row(iven)["near_food"], 1.0)
        anchors = self.services.anchors(iven)
        spot = anchors.get("sleep") or anchors.get("home")
        self.put(iven, spot.x, spot.y)
        self.assertEqual(self.build([iven]).row(iven)["at_home"], 1.0)
        self.put(iven, spot.x + 200, spot.y)
        self.assertEqual(self.build([iven]).row(iven)["at_home"], 0.0)

    def test_at_station_and_time_block(self):
        smith = self.by_key["smith"]
        work = self.services.anchors(smith)["work"]
        self.put(smith, work.x, work.y)
        self.assertEqual(self.build([smith]).row(smith)["at_station"], 1.0)
        self.put(smith, work.x + 10, work.y)
        self.assertEqual(self.build([smith]).row(smith)["at_station"], 0.0)
        self.engine.tick = 0
        day = self.build([smith]).row(smith)["is_night"]
        self.engine.tick = 3 * 600 + 5
        self.assertEqual(self.build([smith]).row(smith)["is_night"], 1.0)
        self.assertIn(day, (0.0, 0.5, 1.0))

    def test_dead_resident_row_is_zero_except_needs_and_one(self):
        iven = self.by_key["iven"]
        self.engine.state.h_tensor[self.slot(iven), cfg.HP] = 0.0
        batch = self.build([iven, self.by_key["smith"]])
        self.assertFalse(bool(batch.alive[0]))
        self.assertTrue(bool(batch.alive[1]))
        row = batch.row(iven)
        for name in ("fear", "vengeance", "is_night", "near_kin", "near_stranger", "has_food_item", "plan_active", "closeness"):
            self.assertEqual(row[name], 0.0, name)
        self.assertEqual(row["one"], 1.0)
        self.assertEqual(row["low_hp"], 1.0)
        self.assertEqual(feat.check_ranges(batch), [])

    def test_unknown_resident_is_a_zero_row(self):
        batch = self.build(["h_does_not_exist", self.by_key["smith"]])
        self.assertFalse(bool(batch.alive[0]))
        self.assertEqual(float(batch.X[0].sum()), 1.0)                  # only the constant
        self.assertEqual(feat.check_ranges(batch), [])

    def test_neighbours_closeness_and_rival(self):
        iven, elsa = self.by_key["iven"], self.by_key["elsa"]
        x, y = float(self.engine.state.h_tensor[self.slot(iven), cfg.X]), float(self.engine.state.h_tensor[self.slot(iven), cfg.Y])
        self.put(elsa, x + 30, y)
        for other in self.residents:
            if other not in (iven, elsa):
                self.put(other, x + 900, y + 900)
        record = self.engine.resident_store.get(iven)
        relations = record.setdefault("relationships", {})
        relations[elsa] = {"closeness": 0.6, "tags": []}
        row = self.build([iven]).row(iven)
        self.assertAlmostEqual(row["closeness"], 0.6)
        self.assertEqual(row["rival"], 0.0)
        self.assertAlmostEqual(row["near_kin"], 1 / 3)
        self.assertEqual(row["near_stranger"], 0.0)
        relations[elsa] = {"closeness": -0.5, "tags": ["rival"]}
        row = self.build([iven]).row(iven)
        self.assertAlmostEqual(row["closeness"], -0.5)                  # negative closeness survives (not clamped to 0)
        self.assertEqual(row["rival"], 1.0)
        self.assertAlmostEqual(row["near_stranger"], 1 / 3)
        self.assertEqual(feat.check_ranges(self.build([iven])), [])

    def test_perception_bounded(self):
        """A change to anything outside the perception radius, or in another resident's pack/record, leaves a row unchanged."""
        iven, elsa = self.by_key["iven"], self.by_key["elsa"]
        x, y = float(self.engine.state.h_tensor[self.slot(iven), cfg.X]), float(self.engine.state.h_tensor[self.slot(iven), cfg.Y])
        for other in self.residents:
            if other != iven:
                self.put(other, x + 700, y + 700)
        self.put(elsa, x + 400, y)                                           # far outside the social radius
        before = self.build([iven]).X.clone()
        # the far resident's needs, record, pack and relationships change; so does a predator that is far away
        h = self.engine.state.h_tensor
        h[self.slot(elsa), cfg.HUNGER], h[self.slot(elsa), cfg.HP], h[self.slot(elsa), cfg.THREAT] = 95.0, 15.0, 90.0
        record = self.engine.resident_store.get(elsa)
        record.setdefault("pressures", {})["fear_pressure"] = 0.9
        record.setdefault("relationships", {})[iven] = {"closeness": -0.9, "tags": ["rival"]}
        inventory = self.engine._human_inventory_record(elsa)
        inventory.setdefault("items", []).append({"kind": "rations", "quantity": 5})
        self.assertTrue(torch.equal(before, self.build([iven]).X))
        # and the same resident moved *into* range does change it
        self.put(elsa, x + 40, y)
        self.assertFalse(torch.equal(before, self.build([iven]).X))

    def test_read_only(self):
        def digest():
            return (self.engine.state.h_tensor.clone(), self.engine.state.m_tensor.clone(),
                    json.dumps(self.engine.inventory_state, sort_keys=True, default=str),
                    json.dumps({u: self.engine.resident_store.get(u) for u in self.residents}, sort_keys=True, default=str))
        before = digest()
        self.build()
        after = digest()
        self.assertTrue(torch.equal(before[0], after[0]) and torch.equal(before[1], after[1]))
        self.assertEqual(before[2:], after[2:])

    def test_cost_is_reported(self):
        batch = self.build()
        self.assertIn("total", batch.timing_ms)
        self.assertGreaterEqual(batch.timing_ms["total"], 0.0)

    def test_matrix_accepts_the_batch(self):
        from systems.affordance import AffordanceEngine
        M = AffordanceEngine(self.world, self.services).mask(self.residents)
        batch = self.build()
        result = matrix.MatrixPolicy.initial().decide(batch.X, batch.P, M)
        self.assertEqual(len(result.names()), 8)
        self.assertTrue(bool(torch.isfinite(result.probabilities).all()))


class ShadowTests(FeatureCase):
    def test_rules_macro_mapping(self):
        calm = {"hunger": 10.0, "thirst": 10.0, "threat": 0.0, "stamina": 90.0, "hp": 100.0}
        self.assertIsNone(feat.rules_macro(calm, {}, True))
        self.assertEqual(feat.rules_macro(dict(calm, thirst=90.0), {}, True), "drink")
        self.assertEqual(feat.rules_macro(dict(calm, hunger=90.0), {"rations": 1}, True), "eat")
        self.assertEqual(feat.rules_macro(dict(calm, threat=90.0), {}, True), "flee")

    def test_shadow_compare_is_deterministic_and_does_not_touch_the_tick_hooks(self):
        first = feat.shadow_compare(self.engine, ticks=80, sample_every=40)
        self.assertEqual(first["samples"], 8 * 3)
        self.assertEqual(first["feature_problems"], [])
        self.assertIn("features", first["timing_ms"])
        self.assertTrue(set(first) >= {"agreement", "confusion", "matrix_choice_when_rules_silent", "would_escalate", "weights_hash"})
        json.dumps(first)                                                    # serialisable

    def test_shadow_compare_perturbed_states(self):
        report = feat.shadow_compare(self.engine, ticks=0, sample_every=1, perturb_seed=7)
        self.assertEqual(report["samples"], 8)
        self.assertEqual(report["feature_problems"], [])
        self.assertGreater(report["rules_spoke"], 0)
        again = feat.shadow_compare(self.engine, ticks=0, sample_every=1, perturb_seed=7)
        self.assertEqual(report["confusion"], again["confusion"])


if __name__ == "__main__":
    unittest.main()
