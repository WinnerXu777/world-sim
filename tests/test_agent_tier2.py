"""EDEN_AGENT_TIER2: the macro-menu DecisionRequest builder (pure parts, the gate, a fake provider in every mode, and the mock model server in shadow and on)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import math
import random
import time
import unittest
import unittest.mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_map_contract import AsyncRegistryIsolation
from authored_village import load_village_maps
import genesis_config as cfg
from driver_pin import pin_anchor
from engine_isolation import restore_after
from systems.actions import tier2
from systems.actions.agent_driver import AgentDriver, MatrixTier1, Row
from systems.decision import (DecisionError, DecisionProvider, DecisionService, RulesDecisionProvider, validate_request)

LEGAL = ["eat", "drink", "rest", "work_at_station"]
FLAT = {"eat": 0.30, "drink": 0.28, "rest": 0.22, "work_at_station": 0.20}          # unsure: top 0.30 < 0.45
SURE = {"eat": 0.90, "drink": 0.05, "rest": 0.03, "work_at_station": 0.02}


class Answer(DecisionProvider):
    mode = "live"

    def __init__(self, probabilities=None, boom=False):
        self.probabilities, self.boom, self.calls = probabilities, boom, 0

    def decide(self, request):
        self.calls += 1
        if self.boom:
            raise RuntimeError("model down")
        return dict(self.probabilities)


class Pure(unittest.TestCase):
    def test_flag_default_off(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop(tier2.ENV, None)
            self.assertFalse(tier2.enabled())

    def test_significance_and_uncertainty(self):
        self.assertFalse(tier2.significant(10, 10, 0, 100))
        self.assertTrue(tier2.significant(50, 0, 0, 100))
        self.assertTrue(tier2.significant(0, 60, 0, 100))
        self.assertTrue(tier2.significant(0, 0, 30, 100))
        self.assertTrue(tier2.significant(0, 0, 0, 40))
        self.assertTrue(tier2.uncertain(0.30, 0.02))
        self.assertTrue(tier2.uncertain(0.80, 0.05))
        self.assertFalse(tier2.uncertain(0.80, 0.50))

    def test_the_situation_revision_is_stable_and_follows_the_situation(self):
        needs = {"hunger": 61.0, "thirst": 12.0}
        base = tier2.situation_revision(LEGAL, "eat", needs)
        self.assertEqual(base, tier2.situation_revision(list(reversed(LEGAL)), "eat", {"thirst": 14.0, "hunger": 69.0}))      # same buckets, order does not matter
        self.assertNotEqual(base, tier2.situation_revision(LEGAL[:-1], "eat", needs))
        self.assertNotEqual(base, tier2.situation_revision(LEGAL, "rest", needs))
        self.assertNotEqual(base, tier2.situation_revision(LEGAL, "eat", {"hunger": 71.0, "thirst": 12.0}))

    def request(self):
        return tier2.build_request(human_id="h_1", world_epoch="e1", tick=100, legal=LEGAL + ["attack"], probabilities={**FLAT, "attack": 0.0}, running="eat",
                                   needs={"hunger": 70.0, "thirst": 10.0})

    def test_the_request_is_a_valid_typed_question_over_the_legal_macros_only(self):
        request = self.request()
        validate_request(request)
        self.assertEqual([o.id for o in request.options], LEGAL + ["attack"])
        self.assertEqual(request.topic, "macro")
        self.assertEqual(request.state_revision, tier2.situation_revision(LEGAL + ["attack"], "eat", {"hunger": 70.0, "thirst": 10.0}))
        self.assertEqual(request.trigger, f"macro_review:{request.state_revision}")
        self.assertEqual(next(o for o in request.options if o.id == "attack").tags, ("destructive",))
        self.assertTrue(all(o.description for o in request.options))
        self.assertEqual(set(request.state["tier1"]), set(o.id for o in request.options))

    def test_the_rules_answer_is_tier1s_own_distribution(self):
        request = tier2.build_request(human_id="h_1", world_epoch="e1", tick=1, legal=LEGAL, probabilities=FLAT, running="", needs={"hunger": 70.0})
        rules = RulesDecisionProvider()
        rules.register_scorer(tier2.TOPIC, tier2.macro_scorer)
        got = rules.decide(request)
        for macro, p in FLAT.items():
            self.assertAlmostEqual(got[macro], p, places=6)


class Fake(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        random.seed(1008)
        torch.manual_seed(1008)
        self.human = next(u for u in self.engine._human_uid_by_slot if u)
        self.slot = self.engine._human_slot_for_id(self.human)
        self.row = Row(self.slot, self.human, {}, {}, "work", None, (False, False))
        self.set_needs(hunger=70.0)

    def set_needs(self, hunger=0.0, thirst=0.0, threat=0.0, hp=100.0):
        h = self.engine.state.h_tensor
        h[self.slot, cfg.HUNGER], h[self.slot, cfg.THIRST], h[self.slot, cfg.THREAT], h[self.slot, cfg.HP] = hunger, thirst, threat, hp

    def run_with(self, provider, probabilities=FLAT, tier1="eat"):
        service = DecisionService(provider)
        t2 = tier2.Tier2(service=service)
        details = {self.human: {"legal": list(LEGAL), "probabilities": dict(probabilities)}}
        out = t2.refine(self.engine, [self.row], {self.human: tier1}, details, 500, running={self.human: "eat"})
        return t2, out[self.human], service

    async def test_a_confident_or_unimportant_row_is_not_asked(self):
        provider = Answer({"eat": 0.0, "drink": 1.0, "rest": 0.0, "work_at_station": 0.0})
        t2, chosen, _ = self.run_with(provider, SURE)
        self.assertEqual((chosen, provider.calls, t2.counts["not_gated"]), ("eat", 0, 1))
        self.set_needs()
        t2, chosen, _ = self.run_with(provider, FLAT)
        self.assertEqual((chosen, provider.calls, t2.counts["not_gated"]), ("eat", 0, 1))

    async def test_with_no_model_the_answer_is_tier1s_and_the_ask_is_counted(self):
        service = DecisionService()                                                    # rules only
        t2 = tier2.Tier2(service=service)
        details = {self.human: {"legal": list(LEGAL), "probabilities": dict(FLAT)}}
        out = t2.refine(self.engine, [self.row], {self.human: "eat"}, details, 500)
        self.assertEqual(out[self.human], "eat")
        self.assertEqual((t2.counts["asked"], t2.counts["changed"], t2.counts["mode_rules"]), (1, 0, 1))

    async def test_a_model_answer_changes_the_macro_and_is_logged(self):
        t2, chosen, service = self.run_with(Answer({"eat": 0.1, "drink": 0.7, "rest": 0.1, "work_at_station": 0.1}))
        self.assertEqual(chosen, "drink")
        self.assertEqual((t2.counts["asked"], t2.counts["changed"], t2.counts["mode_live"]), (1, 1, 1))
        self.assertEqual(t2.log[-1]["tier1"], "eat")
        self.assertEqual(t2.log[-1]["chosen"], "drink")
        self.assertEqual(service.counts["requests"], 1)

    async def test_a_failing_or_malformed_model_falls_back_to_tier1(self):
        t2, chosen, service = self.run_with(Answer(boom=True))
        self.assertEqual((chosen, t2.counts["changed"], service.counts["fallbacks"]), ("eat", 0, 1))
        t2, chosen, service = self.run_with(Answer({"eat": 0.5, "drink": 0.5}))      # does not cover exactly the offered options
        self.assertEqual((chosen, service.counts["fallbacks"]), ("eat", 1))
        t2, chosen, service = self.run_with(Answer({"eat": 2.0, "drink": -1.0, "rest": 0.0, "work_at_station": 0.0}))
        self.assertEqual((chosen, service.counts["fallbacks"]), ("eat", 1))

    async def test_the_matrix_tier1_exposes_its_legal_set_and_distribution(self):
        with unittest.mock.patch.dict("os.environ", {tier2.ENV: "1"}):
            driver = AgentDriver(MatrixTier1(prior_strength=0.0))
        self.assertTrue(driver.tier1.keep_detail)
        self.assertIsNotNone(driver.tier2)
        driver.warm(self.engine)
        driver.tier1.decide(self.engine, [self.row])
        detail = driver.tier1.last_detail[self.human]
        self.assertGreaterEqual(len(detail["legal"]), 1)
        self.assertAlmostEqual(sum(detail["probabilities"].values()), 1.0, places=6)
        self.assertEqual(set(detail["probabilities"]), set(detail["legal"]))


class MockServer(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """Shadow changes nothing; on asks the mock server and uses its cached answer on the second ask of an unchanged situation."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.human = next(u for u in self.engine._human_uid_by_slot if u)
        self.slot = self.engine._human_slot_for_id(self.human)
        self.engine.state.h_tensor[self.slot, cfg.HUNGER] = 70.0
        self.row = Row(self.slot, self.human, {}, {}, "work", None, (False, False))
        from model_server import gate_a
        self.proc, url = gate_a.spawn_server([])
        self.addCleanup(self.proc.terminate)
        restore_after(self, self.engine)                              # configure_plane installs on the shared backend engine: undo it for later tests
        self.plane, self.service = gate_a.configure_plane(self.engine, url, "off", lambda: self.engine.tick / 20.0)
        self.addCleanup(self.plane.close)

    def ask(self, t2):
        details = {self.human: {"legal": list(LEGAL), "probabilities": dict(FLAT)}}
        return t2.refine(self.engine, [self.row], {self.human: "eat"}, details, 500, running={self.human: "eat"})[self.human]

    async def test_shadow_applies_the_rules_answer_and_logs_the_model(self):
        self.plane.set_modes(tier2="shadow")
        t2 = tier2.Tier2()
        self.assertEqual(self.ask(t2), "eat")
        for _ in range(60):
            self.plane.pump()
            time.sleep(0.05)
        self.assertEqual(self.ask(t2), "eat")
        self.assertEqual(t2.counts["changed"], 0)
        self.assertGreaterEqual(t2.counts["asked"], 2)

    async def test_on_uses_the_models_answer_once_it_has_arrived(self):
        self.plane.set_modes(tier2="on")
        t2 = tier2.Tier2()
        self.assertEqual(self.ask(t2), "eat")                         # first ask: the answer is pending, Tier 1 stands
        for _ in range(80):
            self.plane.pump()
            time.sleep(0.05)
        second = self.ask(t2)                                         # the same situation: the model's cached answer
        self.assertEqual((t2.counts["asked"], t2.counts["mode_fallback"], t2.counts["mode_mock"]), (2, 1, 1))
        self.assertIn(second, LEGAL)
        self.assertEqual(t2.counts["changed"], int(second != "eat"))
        self.assertEqual(t2.log[-1]["mode"], "mock")


if __name__ == "__main__":
    unittest.main()
