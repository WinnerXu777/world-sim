"""Matrix weights: the loader (rules prior by default, a verified trained file on request, the prior again on any failure), the shipped weights v2 and the imitation trainer (deterministic)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))
sys.path.insert(0, str(ROOT))

import numpy as np
import torch

from systems.actions import weights
from systems.decision import matrix as mx


class Loader(unittest.TestCase):
    def policy(self, value):
        env = {} if value is None else {weights.ENV: value}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            if value is None:
                os.environ.pop(weights.ENV, None)
            return weights.default_policy()

    def test_default_is_the_rules_prior(self):
        policy = self.policy(None)
        self.assertEqual(policy.weights_hash, mx.MatrixPolicy.initial().weights_hash)
        self.assertEqual(weights.STATUS["fallback"], False)
        self.assertEqual(self.policy("1").weights_hash, policy.weights_hash)

    def test_the_shipped_v2_loads_verified_and_differs_from_the_prior(self):
        policy = self.policy("2")
        self.assertEqual((policy.version, weights.STATUS["version"], weights.STATUS["fallback"]), (2, 2, False))
        self.assertNotEqual(policy.weights_hash, mx.MatrixPolicy.initial().weights_hash)
        provenance = json.loads(mx.default_weights_path(2).with_suffix(".provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["weights_hash"], policy.weights_hash)
        self.assertTrue(provenance["gate"]["improved_on_holdout"] and provenance["gate"]["silent_kl_bounded"])
        self.assertGreater(provenance["test"]["agreement_new"], provenance["test"]["agreement_prior"])
        self.assertTrue(np.array_equal(policy._np[1], mx.MatrixPolicy.initial()._np[1]))      # U and V (personality) are the prior's
        self.assertTrue(np.array_equal(policy._np[2], mx.MatrixPolicy.initial()._np[2]))

    def test_a_missing_or_unknown_version_falls_back_to_the_prior_and_says_so(self):
        for value in ("9", "banana"):
            policy = self.policy(value)
            self.assertEqual(policy.weights_hash, mx.MatrixPolicy.initial().weights_hash, value)
            self.assertTrue(weights.STATUS["fallback"], value)
            self.assertTrue(weights.STATUS["reason"], value)

    def test_a_tampered_file_falls_back(self):
        tmp = Path(tempfile.mkdtemp())
        bad = tmp / "weights_v5.npz"
        shutil.copy(mx.default_weights_path(2), bad)
        with np.load(bad, allow_pickle=False) as data:
            arrays = {k: data[k] for k in data.files}
        arrays["b"] = arrays["b"] + 0.5                                           # content no longer matches the stored hash
        np.savez(bad, **arrays)
        with unittest.mock.patch.object(mx, "WEIGHTS_DIR", tmp):
            policy = self.policy("5")
        self.assertEqual(policy.weights_hash, mx.MatrixPolicy.initial().weights_hash)
        self.assertIn("hash mismatch", weights.STATUS["reason"])

    def test_the_v2_policy_runs_where_the_prior_does(self):
        prior, trained = mx.MatrixPolicy.initial(), self.policy("2")
        X = torch.rand(6, mx.F, dtype=torch.float64)
        X[:, mx.FEATURE_INDEX["one"]] = 1.0
        P = torch.rand(6, mx.P_DIM, dtype=torch.float64)
        M = torch.ones(6, mx.K, dtype=torch.bool)
        for policy in (prior, trained):
            probs = policy.probabilities(X, P, M)
            self.assertTrue(torch.allclose(probs.sum(dim=1), torch.ones(6, dtype=torch.float64)))


class Trainer(unittest.TestCase):
    def dataset(self, rows=240, seed=7):
        """Features from a generator, mask mostly legal, labels from a *different* policy than the prior (so imitation has something to learn)."""
        rng = np.random.default_rng(seed)
        X = rng.random((rows, mx.F))
        X[:, mx.FEATURE_INDEX["one"]] = 1.0
        P = rng.random((rows, mx.P_DIM))
        M = rng.random((rows, mx.K)) < 0.8
        M[:, mx.ACTION_INDEX["idle"]] = True
        teacher = mx.MatrixPolicy.initial()
        W = teacher.W.clone()
        W[mx.FEATURE_INDEX["hunger"], mx.ACTION_INDEX["gather"]] += 12.0              # the "rules" gather when hungry, which the prior does less eagerly
        bent = mx.MatrixPolicy(W.numpy(), teacher._np[1], teacher._np[2], teacher._np[3], teacher.temperature, teacher.hysteresis)
        Y = bent.decide(torch.as_tensor(X), torch.as_tensor(P), torch.as_tensor(M)).action.numpy()
        return {"X": X, "P": P, "M": M, "Y": Y.astype(np.int64), "seed_of_row": np.where(np.arange(rows) < rows * 3 // 4, 1, 2).astype(np.int64)}

    def test_fit_is_deterministic_and_improves_the_holdout(self):
        from model_server import train_matrix
        data = self.dataset()
        first, second = train_matrix.fit(data, holdout_seed=2), train_matrix.fit(data, holdout_seed=2)
        self.assertEqual(first["policy"].weights_hash, second["policy"].weights_hash)
        self.assertGreater(first["test"]["agreement_new"], first["test"]["agreement_prior"])
        self.assertTrue(np.array_equal(first["policy"]._np[1], mx.MatrixPolicy.initial()._np[1]))      # U untouched
        self.assertGreater(first["max_weight_shift"], 0.0)

    def test_the_data_hash_depends_on_the_data(self):
        from model_server import train_matrix
        a, b = self.dataset(seed=1), self.dataset(seed=2)
        self.assertNotEqual(train_matrix.data_hash(a), train_matrix.data_hash(b))
        self.assertEqual(train_matrix.data_hash(a), train_matrix.data_hash(self.dataset(seed=1)))


if __name__ == "__main__":
    unittest.main()
