"""Tier 1 matrix policy: schema, rules equivalence, masks, hysteresis, personality, gate, weights file, provider, benchmark."""
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import numpy as np
import torch

from systems.commission import make_rules_provider, submit_request
from systems.decision import (DecisionError, DecisionOption, DecisionRequest, DecisionService, MatrixDecisionProvider, MatrixPolicy,
                              RulesDecisionProvider, summarize)
from systems.decision import matrix as mx
from systems.personality.catalog import TRAIT_NAMES

COMMISSION_IDS = list(mx.COMMISSION_OUTCOMES)


def commission_request(state, ids, n=0):
    return DecisionRequest(job_id=f"j{n}", resident_id="h_smith", world_epoch="E1", state_revision=1, tick=0, trigger=f"t:{n}",
                           question_kind="choice", topic="commission", state=state, options=tuple(DecisionOption(i) for i in ids))


def random_state(rng):
    traits = {name: round(rng.random(), 3) for name in rng.sample(TRAIT_NAMES, rng.randint(0, 6))}
    pressures = {name: round(rng.random(), 3) for name in rng.sample(["security", "vengeance", "greed", "fear"], rng.randint(0, 3))}
    return {"closeness": round(rng.uniform(-1, 1), 3), "rival": rng.random() < 0.3, "traits": traits, "pressures": pressures,
            "price": 18, "open_orders": 1, "capacity": 3, "missing": [], "forge_available": True}


def population(n, seed=0, **fixed):
    gen = torch.Generator().manual_seed(seed)
    X = torch.zeros(n, mx.F, dtype=torch.float64)
    X[:, mx.FEATURE_INDEX["one"]] = 1.0
    for name, value in fixed.items():
        X[:, mx.FEATURE_INDEX[name]] = value
    P = torch.full((n, mx.P_DIM), 0.5, dtype=torch.float64)
    M = torch.zeros(n, mx.K, dtype=torch.bool)
    M[:, : len(mx.MACRO_ACTIONS)] = True
    return X, P, M


def act(policy, X, P, M, **kw):
    return policy.decide(X, P, M, **kw).names()


class SchemaTests(unittest.TestCase):
    def test_vocabularies_are_consistent(self):
        self.assertEqual(mx.TRAITS, tuple(TRAIT_NAMES))
        self.assertEqual((mx.F, mx.P_DIM, mx.K), (26, 16, 30))
        for names in (mx.FEATURES, mx.MENU, mx.TRAITS):
            self.assertEqual(len(set(names)), len(names))
        self.assertEqual(len(mx.MACRO_ACTIONS), 24)
        self.assertEqual(set(mx.MACRO_SPEC) | set(mx.COMMISSION_SPEC), set(mx.MENU))
        self.assertEqual(mx.FEATURES[-1], "one")
        W, U, V, b = mx.initial_arrays()
        self.assertEqual((W.shape, U.shape, V.shape, b.shape), ((26, 30), (26, 30), (16, 30), (30,)))

    def test_commission_outcomes_match_the_commission_module(self):
        from systems.commission.decide import BASE_REFUSAL_SCORE, OPTION_DESCRIPTIONS
        self.assertEqual(set(OPTION_DESCRIPTIONS), set(mx.COMMISSION_OUTCOMES))
        for name, score in BASE_REFUSAL_SCORE.items():
            self.assertEqual(mx.COMMISSION_SPEC[name]["b"], score)


class RulesEquivalenceTests(unittest.TestCase):
    def test_matrix_reproduces_the_rules_provider_on_10000_logged_style_states(self):
        rules, matrix = make_rules_provider(), MatrixDecisionProvider()
        rng, agree, worst = random.Random(1008), 0, 0.0
        for n in range(10000):
            ids = rng.sample(COMMISSION_IDS, rng.randint(1, 6))
            request = commission_request(random_state(rng), ids, n)
            want, got = rules.decide(request), matrix.decide(request)
            worst = max(worst, max(abs(want[i] - got[i]) for i in ids))
            agree += summarize(request.options, want)[0] == summarize(request.options, got)[0]
        self.assertEqual(agree, 10000)                 # 100 percent argmax agreement at initialisation
        self.assertLess(worst, 1e-12, worst)           # and the whole distribution, not only the argmax

    def test_same_outcomes_through_the_real_commission_flow(self):
        from test_commission_orders import CUSTOMER, SMITH, make_ctx
        for closeness in (-0.6, 0.0, 0.5, 1.0):
            for rival in (False, True):
                results = []
                for provider in (make_rules_provider(), MatrixDecisionProvider()):
                    ctx, _ = make_ctx()
                    results.append(submit_request(ctx, CUSTOMER, SMITH, "sword", DecisionService(provider), "c",
                                                  {"closeness": closeness, "rival": rival}))
                with self.subTest(closeness=closeness, rival=rival):
                    self.assertEqual(results[0]["code"], results[1]["code"])
                    for key, value in results[0]["probabilities"].items():
                        self.assertAlmostEqual(value, results[1]["probabilities"][key], places=12)

    def test_service_reports_matrix_as_the_answering_provider(self):
        service = DecisionService(MatrixDecisionProvider())
        result = service.decide(commission_request({"closeness": 0.5}, ["accept_commission", "refuse_busy"]))
        self.assertEqual((result.provider_mode, result.top_option), ("matrix", "accept_commission"))
        self.assertEqual(service.counts["fallbacks"], 0)

    def test_unknown_topic_goes_to_rules_and_foreign_options_fall_back(self):
        service = DecisionService(MatrixDecisionProvider())
        generic = DecisionRequest("j", "h", "E", 1, 0, "t:1", "choice", (DecisionOption("a"), DecisionOption("b")), topic="generic")
        self.assertEqual(service.decide(generic).provider_mode, "rules")
        foreign = commission_request({}, ["accept_commission", "not_in_the_menu"])
        result = service.decide(foreign)
        self.assertEqual(result.provider_mode, "fallback")
        self.assertIn("outside the matrix menu", result.note)


class PolicyMathTests(unittest.TestCase):
    def setUp(self):
        self.policy = MatrixPolicy.initial()

    def test_illegal_options_have_probability_exactly_zero_and_are_never_chosen(self):
        gen = torch.Generator().manual_seed(3)
        X = torch.rand(500, mx.F, generator=gen, dtype=torch.float64)
        P = torch.rand(500, mx.P_DIM, generator=gen, dtype=torch.float64)
        M = torch.rand(500, mx.K, generator=gen) > 0.6
        M[:, 0] |= ~M.any(dim=1)
        result = self.policy.decide(X, P, M, current=torch.randint(0, mx.K, (500,), generator=gen))
        self.assertTrue(bool((result.probabilities[~M] == 0).all()))
        self.assertTrue(bool(M[torch.arange(500), result.action].all()))
        self.assertTrue(torch.allclose(result.probabilities.sum(dim=1), torch.ones(500, dtype=torch.float64)))

    def test_no_legal_option_gives_zeros_not_nan_and_never_escalates(self):
        X, P, M = population(3)
        M[1] = False
        result = self.policy.decide(X, P, M)
        self.assertEqual(result.no_legal.tolist(), [False, True, False])
        self.assertEqual(result.action.tolist()[1], -1)
        self.assertEqual(float(result.probabilities[1].sum()), 0.0)
        self.assertFalse(bool(torch.isnan(result.probabilities).any()))
        self.assertFalse(bool(self.policy.gate(result, [True, True, True])[1]))

    def test_one_legal_option_gets_probability_one(self):
        X, P, M = population(1)
        M[:] = False
        M[0, mx.ACTION_INDEX["REPLAN"]] = True
        result = self.policy.decide(X, P, M)
        self.assertEqual((float(result.top_p[0]), float(result.margin[0])), (1.0, 1.0))

    def test_batch_equals_row_by_row(self):
        gen = torch.Generator().manual_seed(5)
        X = torch.rand(40, mx.F, generator=gen, dtype=torch.float64)
        P = torch.rand(40, mx.P_DIM, generator=gen, dtype=torch.float64)
        M = torch.rand(40, mx.K, generator=gen) > 0.4
        M[:, 19] = True
        batch = self.policy.probabilities(X, P, M)
        rows = torch.stack([self.policy.probabilities(X[i:i + 1], P[i:i + 1], M[i:i + 1])[0] for i in range(40)])
        self.assertTrue(torch.allclose(batch, rows, atol=1e-15))

    def test_hysteresis_keeps_the_running_action_unless_something_clearly_wins(self):
        X, P, M = population(1, hunger=0.6, thirst=0.6)
        eat, drink = mx.ACTION_INDEX["eat"], mx.ACTION_INDEX["drink"]
        base = self.policy.scores(X, P)
        gap = float(base[0, drink] - base[0, eat])
        self.assertTrue(0 < gap < self.policy.hysteresis)   # drink wins narrowly without stickiness
        self.assertEqual(act(self.policy, X, P, M), ["drink"])
        self.assertEqual(act(self.policy, X, P, M, current=[eat]), ["eat"])           # ... but the running action is kept
        X2, _, _ = population(1, hunger=0.2, thirst=0.9)  # a clearly stronger need overrides the stickiness
        self.assertEqual(act(self.policy, X2, P, M, current=[eat]), ["drink"])
        self.assertEqual(act(self.policy, X, P, M, current=[-1]), ["drink"])    # nothing running: no bonus

    def test_stickiness_scales_the_bonus(self):
        X, P, M = population(2, hunger=0.6, thirst=0.6)
        eat = mx.ACTION_INDEX["eat"]
        S = self.policy.scores(X, P, current=[eat, eat], stickiness=[1.0, 0.0])
        self.assertAlmostEqual(float(S[0, eat] - S[1, eat]), self.policy.hysteresis, places=12)

    def test_sensible_defaults_for_the_macro_actions(self):
        policy = self.policy
        cases = [({"hunger": 0.9}, "eat"), ({"thirst": 0.9}, "drink"), ({"is_night": 1, "low_stamina": 0.7, "at_home": 1}, "sleep"),
                 ({"threat": 0.9, "near_danger": 1, "fear": 0.8}, "flee"), ({"plan_active": 1, "plan_step_failed": 1}, "REPLAN"),
                 ({"plan_active": 1}, "continue_plan_step"), ({}, "idle")]
        for features, expected in cases:
            X, P, M = population(1, **features)
            with self.subTest(features=features):
                self.assertEqual(act(policy, X, P, M), [expected])

    def test_personality_changes_the_decision_through_the_bilinear_term(self):
        X, P, M = population(2, threat=0.8, vengeance=0.8, rival=1.0)
        P[0, mx.TRAIT_INDEX["aggression"]], P[0, mx.TRAIT_INDEX["mercy"]] = 0.95, 0.05
        P[1, mx.TRAIT_INDEX["aggression"]], P[1, mx.TRAIT_INDEX["fearfulness"]] = 0.05, 0.95
        P[1, mx.TRAIT_INDEX["caution"]] = 0.9
        aggressive, timid = act(self.policy, X, P, M)
        self.assertEqual(aggressive, "attack")
        self.assertIn(timid, ("flee", "hide", "avoid"))

    def test_gate_escalates_only_uncertain_and_significant_rows(self):
        X, P, M = population(4, low_stamina=0.35)
        M[:] = False
        M[:, mx.ACTION_INDEX["idle"]] = True
        M[:, mx.ACTION_INDEX["rest"]] = True        # idle vs rest: nearly even on a zero state
        result = self.policy.decide(X, P, M)
        self.assertLess(float(result.margin[0]), 0.2)
        gate = self.policy.gate(result, [True, False, True, True], mx.GateConfig(min_top_p=0.9, min_margin=0.9))
        self.assertEqual(gate.tolist(), [True, False, True, True])
        confident = self.policy.gate(result, [True] * 4, mx.GateConfig(min_top_p=0.01, min_margin=0.0))
        self.assertEqual(confident.tolist(), [False] * 4)

    def test_input_shapes_are_checked(self):
        X, P, M = population(2)
        with self.assertRaises(ValueError):
            self.policy.decide(X[:, :5], P, M)
        with self.assertRaises(ValueError):
            self.policy.decide(X, P, M[:, :5])
        with self.assertRaises(ValueError):
            MatrixPolicy(*mx.initial_arrays(), temperature=0)


class WeightsFileTests(unittest.TestCase):
    def test_round_trip_keeps_hash_and_decisions(self):
        policy = MatrixPolicy.initial(version=7)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weights_v7.npz"
            digest = policy.save(path)
            loaded = MatrixPolicy.load(path)
        self.assertEqual((loaded.weights_hash, loaded.version), (digest, 7))
        X, P, M = population(5, hunger=0.7)
        self.assertTrue(torch.equal(policy.probabilities(X, P, M), loaded.probabilities(X, P, M)))

    def test_tampered_or_foreign_files_are_refused(self):
        policy = MatrixPolicy.initial()
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.npz"
            policy.save(good)
            with np.load(good, allow_pickle=False) as data:
                content = {k: data[k] for k in data.files}
            tampered = dict(content, W=content["W"] + 0.001)
            np.savez(Path(tmp) / "tampered.npz", **tampered)
            with self.assertRaises(DecisionError) as ctx:
                MatrixPolicy.load(Path(tmp) / "tampered.npz")
            self.assertIn("hash mismatch", str(ctx.exception))
            np.savez(Path(tmp) / "schema.npz", **dict(content, schema=np.int64(99)))
            with self.assertRaises(DecisionError):
                MatrixPolicy.load(Path(tmp) / "schema.npz")
            np.savez(Path(tmp) / "menu.npz", **dict(content, menu=np.array(list(reversed(mx.MENU)))))
            with self.assertRaises(DecisionError):
                MatrixPolicy.load(Path(tmp) / "menu.npz")

    def test_shipped_weights_v1_is_the_initial_policy(self):
        shipped = MatrixPolicy.load(mx.default_weights_path(1))
        self.assertEqual(shipped.weights_hash, MatrixPolicy.initial().weights_hash)
        self.assertEqual(shipped.describe()["actions"], 30)


class FeaturizerTests(unittest.TestCase):
    def test_population_features_read_needs_from_the_tensor_in_one_pass(self):
        import genesis_config as cfg
        h = torch.zeros(6, 32)
        h[2, cfg.HUNGER], h[2, cfg.THIRST], h[2, cfg.H_STAMINA], h[2, cfg.HP], h[2, cfg.THREAT], h[2, cfg.MOOD] = 80, 40, 25, 60, 10, 90
        X = mx.population_features(h, [2, 0], {"is_night": [1, 0], "near_food": [0, 1]})
        row = {name: float(X[0, i]) for name, i in mx.FEATURE_INDEX.items()}
        self.assertAlmostEqual(row["hunger"], 0.8)
        self.assertAlmostEqual(row["low_stamina"], 0.75)
        self.assertAlmostEqual(row["low_hp"], 0.4)
        self.assertAlmostEqual(row["low_mood"], 0.1)
        self.assertEqual((row["is_night"], row["near_food"], row["one"]), (1.0, 0.0, 1.0))
        with self.assertRaises(ValueError):
            mx.population_features(h, [0], {"bogus": [1]})

    def test_trait_matrix_defaults_missing_traits(self):
        P = mx.trait_matrix([{"greed": 0.9}, {}])
        self.assertEqual(tuple(P.shape), (2, 16))
        self.assertAlmostEqual(float(P[0, mx.TRAIT_INDEX["greed"]]), 0.9)
        self.assertAlmostEqual(float(P[1, mx.TRAIT_INDEX["greed"]]), 0.5)


class ShadowComparisonTests(unittest.TestCase):
    def test_rules_matrix_and_a_mock_clef_are_compared_on_the_same_requests(self):
        from systems.decision.report import compare, write_jsonl

        class MockClef(mx.DecisionProvider):         # same hash-seeded answers the mock model server gives
            mode = "mock"

            def decide(self, request):
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from model_server.backends.heuristics import decide_probabilities
                return decide_probabilities({"resident_id": request.resident_id, "trigger": request.trigger,
                                             "options": [{"id": o.id} for o in request.options]})

        rng = random.Random(7)
        requests = [commission_request(random_state(rng), rng.sample(COMMISSION_IDS, rng.randint(2, 6)), n) for n in range(300)]
        report = compare(requests, {"rules": make_rules_provider(), "matrix": MatrixDecisionProvider(), "mock_clef": MockClef()})
        self.assertEqual(report["errors"], {"rules": 0, "matrix": 0, "mock_clef": 0})
        self.assertEqual(report["agreement"]["rules~matrix"]["rate"], 1.0)
        self.assertLess(report["agreement"]["rules~mock_clef"]["rate"], 0.9)    # an unrelated model disagrees, and the report shows it
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(write_jsonl(report, Path(tmp) / "shadow.jsonl"), 300)

    def test_a_failing_provider_is_counted_not_fatal(self):
        from systems.decision.report import compare

        class Boom(mx.DecisionProvider):
            def decide(self, request):
                raise RuntimeError("down")

        report = compare([commission_request({}, ["accept_commission", "refuse_busy"])], {"rules": make_rules_provider(), "boom": Boom()})
        self.assertEqual((report["errors"]["boom"], report["agreement"]["rules~boom"]["compared"]), (1, 0))


class BenchmarkTests(unittest.TestCase):
    def test_hundred_resident_batch_is_cheap(self):
        result = mx.benchmark(100, repeats=300)
        print(f"\n[matrix benchmark] {result}")
        self.assertLess(result["p99_ms"], 5.0, result)    # generous bound for a loaded machine; measured figures are in the report


if __name__ == "__main__":
    unittest.main()
