"""Tier 1 instinct feature block (cold / hot / wounded / fear_memory): flag-gated columns, the weight table, the flag-off identity of ``MatrixTier1``."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import random
import unittest
import unittest.mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_map_contract import AsyncRegistryIsolation
from authored_village import load_village_maps
import genesis_config as cfg
from driver_pin import pin_anchor
from harness import danger, darkness, sleep, temperature, wounds
from systems.actions.agent_driver import AgentDriver, MatrixTier1, Row, RulesTier1
from systems.decision import instinct_features as ext, matrix

FLAG_ENV = ("EDEN_TEMPERATURE", "EDEN_WOUNDS", "EDEN_DANGER", "EDEN_SLEEP", "EDEN_DARKNESS", "EDEN_EMOTION")


class Table(unittest.TestCase):
    def test_every_spec_row_names_a_macro_and_a_feature(self):
        for macro, spec in ext.EXT_SPEC.items():
            self.assertIn(macro, matrix.MACRO_ACTIONS)
            self.assertTrue(set(spec) <= set(ext.FEATURES), macro)
        self.assertEqual(set(ext.FLAGS), set(ext.FEATURES))
        self.assertEqual(tuple(ext.DEFS), ext.FEATURES)

    def test_weights_shape_and_hash_are_stable(self):
        W = ext.weights()
        self.assertEqual(tuple(W.shape), (len(ext.FEATURES), matrix.K))
        self.assertEqual(float(W[ext.FEATURES.index("cold"), matrix.ACTION_INDEX["go_home"]]), 1.6)
        self.assertEqual(ext.schema_hash(), ext.schema_hash())
        self.assertEqual(ext.INSTINCT_SCHEMA_VERSION, 3)
        self.assertEqual(ext.FEATURES[:4], ("cold", "hot", "wounded", "fear_memory"))        # the v1 columns keep their index

    def test_the_base_matrix_schema_and_the_shipped_weights_are_untouched(self):
        self.assertEqual(matrix.FEATURE_SCHEMA_VERSION, 1)
        self.assertNotIn("cold", matrix.FEATURES)
        from systems.actions import weights
        with unittest.mock.patch.dict(os.environ, {"EDEN_MATRIX_WEIGHTS": "2"}):
            policy = weights.default_policy()
        self.assertEqual((policy.version, weights.STATUS["fallback"]), (2, False))


class Fake:
    """Just enough engine for ``build``: slots, a tensor, the reader state."""

    def __init__(self, n=3):
        self.ids = [f"h{i}" for i in range(n)]
        self.state = unittest.mock.Mock()
        self.state.h_tensor = torch.zeros(n, 40)

    def _human_slot_for_id(self, uid):
        return self.ids.index(uid) if uid in self.ids else None


class Build(unittest.TestCase):
    def setUp(self):
        for name in FLAG_ENV:
            os.environ.pop(name, None)
        patcher = unittest.mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = Fake()

    def test_all_flags_off_is_none_and_zero(self):
        self.assertEqual(ext.active(), ())
        self.assertIsNone(ext.scores(self.engine, self.engine.ids))
        self.assertEqual(float(ext.build(self.engine, self.engine.ids).abs().sum()), 0.0)

    def test_each_column_is_live_only_with_its_flag(self):
        with unittest.mock.patch.object(temperature, "cold_of", lambda e, s: 10.0), unittest.mock.patch.object(temperature, "hot_of", lambda e, s: 40.0), \
                unittest.mock.patch.object(wounds, "bleed_of", lambda e, u: 0.15), unittest.mock.patch.object(danger, "danger_pressure", lambda e, u, x, y: 0.7):
            os.environ["EDEN_TEMPERATURE"] = "1"
            self.assertEqual(ext.active(), ("cold", "hot"))
            row = ext.build(self.engine, ["h0"])[0].tolist()
            self.assertEqual(row, [0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])                       # 40 degrees clamps to 1
            os.environ["EDEN_WOUNDS"] = "1"
            self.assertEqual(ext.build(self.engine, ["h0"])[0].tolist(), [0.5, 1.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            os.environ["EDEN_DANGER"] = "1"
            self.assertEqual(ext.build(self.engine, ["h0"])[0].tolist(), [0.5, 1.0, 0.5, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            os.environ.pop("EDEN_TEMPERATURE")
            self.assertEqual(ext.build(self.engine, ["h0"])[0].tolist(), [0.0, 0.0, 0.5, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_an_unknown_resident_reads_as_zero(self):
        os.environ["EDEN_WOUNDS"] = "1"
        with unittest.mock.patch.object(wounds, "bleed_of", lambda e, u: 9.0):
            self.assertEqual(ext.build(self.engine, ["nobody"])[0].tolist(), [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_tired_and_dark_columns_follow_their_own_flags(self):
        with unittest.mock.patch.object(sleep, "debt_of", lambda e, u: 60.0), unittest.mock.patch.object(darkness, "unease_of", lambda e, s: 0.4):
            os.environ["EDEN_SLEEP"] = "1"
            self.assertEqual(ext.active(), ("tired",))
            self.assertEqual(ext.build(self.engine, ["h0"])[0].tolist(), [0.0, 0.0, 0.0, 0.0, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0])
            os.environ["EDEN_DARKNESS"] = "1"
            self.assertEqual(ext.build(self.engine, ["h0"])[0].tolist(), [0.0, 0.0, 0.0, 0.0, 0.6, 0.4, 0.0, 0.0, 0.0, 0.0])
            os.environ.pop("EDEN_SLEEP")
            self.assertEqual(ext.build(self.engine, ["h0"])[0].tolist(), [0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 0.0, 0.0, 0.0, 0.0])

    def test_the_tired_prefer_sleep_and_the_afraid_of_the_dark_prefer_home(self):
        os.environ["EDEN_SLEEP"] = "1"
        os.environ["EDEN_DARKNESS"] = "1"
        with unittest.mock.patch.object(sleep, "debt_of", lambda e, u: 100.0), unittest.mock.patch.object(darkness, "unease_of", lambda e, s: 1.0):
            X, S = ext.scores(self.engine, ["h0"])
        self.assertAlmostEqual(float(S[0, matrix.ACTION_INDEX["sleep"]]), 3.0)
        self.assertAlmostEqual(float(S[0, matrix.ACTION_INDEX["go_home"]]), 2.2)
        self.assertLess(float(S[0, matrix.ACTION_INDEX["explore"]]), 0)

    def test_scores_follow_the_table(self):
        os.environ["EDEN_TEMPERATURE"] = "1"
        with unittest.mock.patch.object(temperature, "cold_of", lambda e, s: 20.0), unittest.mock.patch.object(temperature, "hot_of", lambda e, s: 0.0):
            X, S = ext.scores(self.engine, ["h0"])
        self.assertEqual(float(S[0, matrix.ACTION_INDEX["go_home"]]), 1.6)
        self.assertEqual(float(S[0, matrix.ACTION_INDEX["explore"]]), -1.0)
        self.assertEqual(float(S[0, matrix.ACTION_INDEX["eat"]]), 0.0)


class Village(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        for name in FLAG_ENV:
            os.environ.pop(name, None)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "1", "EDEN_AGENT_LADDER": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        self.humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in self.humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        random.seed(1008)
        torch.manual_seed(1008)

    def rows(self):
        from systems.roster.driver import current_routine
        out = []
        for human_id in self.humans:
            slot = self.engine._human_slot_for_id(human_id)
            resident = self.engine.resident_store.get(human_id)
            out.append(Row(slot, human_id, resident["roster"], resident, current_routine(self.engine, human_id, resident), None, (False, False)))
        return out

    async def test_flag_off_the_decision_is_unchanged_and_nothing_is_recorded(self):
        tier = MatrixTier1(prior_strength=0.0)
        base = tier.decide(self.engine, self.rows())
        self.assertIsNone(tier.last_instinct)
        again = MatrixTier1(prior_strength=0.0).decide(self.engine, self.rows())
        self.assertEqual(base, again)

    async def test_with_a_flag_on_the_block_is_recorded_and_moves_the_scores_not_the_prior(self):
        tier = MatrixTier1(prior_strength=0.0)
        os.environ["EDEN_TEMPERATURE"] = "1"
        with unittest.mock.patch.object(temperature, "cold_of", lambda e, s: 20.0), unittest.mock.patch.object(temperature, "hot_of", lambda e, s: 0.0):
            tier.decide(self.engine, self.rows())
        X, S = tier.last_instinct
        self.assertEqual(tuple(X.shape), (len(self.humans), len(ext.FEATURES)))
        self.assertTrue(bool((X[:, 0] == 1.0).all()))
        self.assertTrue(bool((S[:, matrix.ACTION_INDEX["go_home"]] > 0).all()))

    async def test_cold_residents_choose_shelter_in_the_pure_matrix(self):
        os.environ["EDEN_TEMPERATURE"] = "1"
        with unittest.mock.patch.object(temperature, "cold_of", lambda e, s: 20.0), unittest.mock.patch.object(temperature, "hot_of", lambda e, s: 0.0):
            cold = MatrixTier1(prior_strength=0.0).decide(self.engine, self.rows())
        os.environ.pop("EDEN_TEMPERATURE")
        plain = MatrixTier1(prior_strength=0.0).decide(self.engine, self.rows())
        self.assertGreaterEqual(sum(1 for h in self.humans if cold[h] == "go_home"), sum(1 for h in self.humans if plain[h] == "go_home"))

    async def test_with_the_rules_prior_at_full_strength_the_rules_macro_still_wins(self):
        os.environ["EDEN_TEMPERATURE"] = "1"
        with unittest.mock.patch.object(temperature, "cold_of", lambda e, s: 20.0), unittest.mock.patch.object(temperature, "hot_of", lambda e, s: 0.0):
            with_ext = MatrixTier1(prior_strength=1.0).decide(self.engine, self.rows())
        os.environ.pop("EDEN_TEMPERATURE")
        self.assertEqual(with_ext, MatrixTier1(prior_strength=1.0).decide(self.engine, self.rows()))


if __name__ == "__main__":
    unittest.main()
