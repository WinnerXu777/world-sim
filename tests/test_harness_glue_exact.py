"""R2-H1(d): the per-tick resident glue optimisations are exact. Each check compares against the original formulation."""
import random
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from runtime.resident_store import ResidentAgentStore  # noqa: E402
from systems.crafting.lifecycle import ensure_crafting_state  # noqa: E402
from systems.personality import traits as tr  # noqa: E402
from systems.tasks.lifecycle import ensure_task_state  # noqa: E402


def normalize_traits_reference(traits):
    normalized = dict(tr.BALANCED_BASE)
    for name in tr.TRAIT_NAMES:
        if traits is not None and name in traits:
            normalized[name] = tr.clamp_trait(float(traits[name]))
    return normalized


def snapshot_reference(h_tensor, slot, tick):
    row = h_tensor[slot]
    return {"tick": tick, "slot": slot, "x": round(float(row[cfg.X]), 2), "y": round(float(row[cfg.Y]), 2),
            "sex": int(round(float(row[cfg.H_SEX]))), "age": round(float(row[cfg.H_AGE]), 3), "hp": round(float(row[cfg.HP]), 3),
            "hunger": round(float(row[cfg.HUNGER]), 3), "thirst": round(float(row[cfg.THIRST]), 3), "threat": round(float(row[cfg.THREAT]), 3),
            "mood": round(float(row[cfg.MOOD]), 3), "stamina": round(float(row[cfg.H_STAMINA]), 3),
            "infection": round(float(row[cfg.H_INFECTION]), 3), "tribe": round(float(row[cfg.H_TRIBE]), 3),
            "escalated": bool(float(row[cfg.ESCALATION_FLAG]) > 0.0)}


class NormalizeTraitsMemoTests(unittest.TestCase):
    def test_matches_the_original_for_many_inputs_including_repeats(self):
        rng = random.Random(7)
        names = list(tr.TRAIT_NAMES)
        for _ in range(400):
            traits = {n: rng.choice([rng.uniform(-0.5, 1.5), 0, 1, True, 0.5, 0.1234567]) for n in rng.sample(names, rng.randint(0, len(names)))}
            traits["not_a_trait"] = rng.random()
            expected = normalize_traits_reference(traits)
            for _ in range(2):                                    # second call is a cache hit
                self.assertEqual(tr.normalize_traits(traits), expected)
        self.assertEqual(tr.normalize_traits(None), normalize_traits_reference(None))
        self.assertEqual(tr.normalize_traits({}), normalize_traits_reference({}))

    def test_every_call_returns_a_fresh_dict(self):
        traits = {tr.TRAIT_NAMES[0]: 0.4}
        first = tr.normalize_traits(traits)
        first[tr.TRAIT_NAMES[0]] = 99.0
        first["extra"] = 1
        second = tr.normalize_traits(traits)
        self.assertEqual(second, normalize_traits_reference(traits))
        self.assertIsNot(first, second)

    def test_nan_and_unhashable_values_behave_like_the_original(self):
        nan = float("nan")
        traits = {tr.TRAIT_NAMES[0]: nan}
        self.assertEqual(str(tr.normalize_traits(traits)), str(normalize_traits_reference(traits)))
        with self.assertRaises(TypeError):
            tr.normalize_traits({tr.TRAIT_NAMES[0]: [0.5]})        # the original raises in float([..]); the memo must not hide it
        with self.assertRaises(TypeError):
            normalize_traits_reference({tr.TRAIT_NAMES[0]: [0.5]})


class SnapshotTests(unittest.TestCase):
    def test_snapshot_equals_the_original_formulation(self):
        rng = random.Random(3)
        h = torch.zeros((6, cfg.HUMAN_TENSOR_COLS))
        for _ in range(50):
            for slot in range(6):
                for col in (cfg.X, cfg.Y, cfg.H_SEX, cfg.H_AGE, cfg.HP, cfg.HUNGER, cfg.THIRST, cfg.THREAT, cfg.MOOD, cfg.H_STAMINA,
                            cfg.H_INFECTION, cfg.H_TRIBE, cfg.ESCALATION_FLAG):
                    h[slot, col] = rng.choice([rng.uniform(-5, 2000), 0.0, 0.5, 1.4999999, 1e-7, 100.0, -0.0])
            store = ResidentAgentStore.__new__(ResidentAgentStore)
            for slot in range(6):
                self.assertEqual(store._snapshot_from_tensor(h, slot, 42), snapshot_reference(h, slot, 42))


class SetdefaultReplacementTests(unittest.TestCase):
    def test_existing_values_are_kept_by_identity_and_missing_keys_filled(self):
        for ensure, key in ((ensure_task_state, "task_state"), (ensure_crafting_state, "crafting_state")):
            fresh = {}
            ensure(fresh, 100)
            full = fresh[key]
            keep = {"marker": object()}
            resident = {key: {"schema_version": 1, "kept_list": keep}}
            ensure(resident, 100)
            self.assertIs(resident[key]["kept_list"], keep)
            for name, value in full.items():
                self.assertIn(name, resident[key], f"{key}.{name} was not filled")
            again = {k: resident[key][k] for k in full}
            ensure(resident, 100)
            self.assertTrue(all(resident[key][k] == again[k] for k in again))      # idempotent


if __name__ == "__main__":
    unittest.main()
