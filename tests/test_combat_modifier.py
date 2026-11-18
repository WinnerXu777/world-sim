"""1008 defend Phase 1 (1008_defend_phase1_gap.md): the combat modifier hook in ``resolve_human_attack_intents`` and the restrained-attacker rule.

With the hook ``None`` and ``EDEN_RESTRAINT`` off the resolver must be the one from before the hook existed: ``tests/fixtures/combat_resolver_before_defend.py`` is
that file, verbatim, and the first test compares both over randomized crowds (results and tensors, bit for bit)."""
import copy
import importlib.util
import math
import os
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from genesis_config import (AGENT_TYPE_HUMAN, ATTACK_RANGE, H_RESTRAINED, H_STAMINA, HP, THREAT, TYPE, X, Y)  # noqa: E402
from systems.combat import modifiers  # noqa: E402
from systems.combat.intents import CombatIntent  # noqa: E402
from systems.combat.resolver import resolve_human_attack_intents  # noqa: E402

_spec = importlib.util.spec_from_file_location("combat_resolver_before_defend", ROOT / "tests" / "fixtures" / "combat_resolver_before_defend.py")
before = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(before)


def world(seed, n=12, animals=3):
    rng = random.Random(seed)
    h = torch.zeros(32, 32)
    m = torch.zeros(64, 32)
    for slot in range(n):
        h[slot, TYPE] = float(AGENT_TYPE_HUMAN) if rng.random() < 0.9 else 0.0
        h[slot, X], h[slot, Y] = float(rng.randrange(0, 40)), float(rng.randrange(0, 40))
        h[slot, HP] = rng.choice([0.0, 30.0, 100.0, 100.0])
        h[slot, H_STAMINA] = rng.choice([0.0, 5.0, 50.0, 100.0, 100.0])
        h[slot, THREAT] = rng.choice([0.0, 20.0, 80.0])
    animal_types = sorted(cfg.ANIMAL_TYPES)
    for k in range(animals):
        row = 10 + k
        m[row, cfg.M_TYPE] = float(rng.choice(animal_types))
        m[row, cfg.CX], m[row, cfg.CY] = float(rng.randrange(0, 40)), float(rng.randrange(0, 40))
        m[row, cfg.M_HP] = rng.choice([0.0, 60.0])
    return h, m


def intents(seed, n=12):
    rng = random.Random(seed * 7 + 1)
    out = []
    for _ in range(rng.randrange(0, 14)):
        kind = rng.choice(["human", "human", "entity", "bogus"])
        out.append(CombatIntent(source="sim", action="attack", attacker_kind=rng.choice(["human", "human", "entity"]), attacker_slot=rng.randrange(0, n),
                                target_kind=kind, target_slot=rng.randrange(0, n if kind == "human" else 14), target_id="t"))
    return out


def run(module, seed, **kw):
    h, m = world(seed)
    result = module.resolve_human_attack_intents(intents(seed), h, m, "cpu", walls=[], attack_range=ATTACK_RANGE * 4, **kw)
    return repr(result), h, m


class IdentityTests(unittest.TestCase):
    def test_no_hook_and_no_flag_is_the_old_resolver_bit_for_bit(self):
        modifiers.set_modifier(None)
        with mock.patch.dict(os.environ):
            os.environ.pop(modifiers.RESTRAINT_FLAG, None)
            resolved = 0
            for seed in range(300):
                new_result, new_h, new_m = run(sys.modules["systems.combat.resolver"], seed)
                old_result, old_h, old_m = run(before, seed)
                self.assertEqual(new_result, old_result, seed)
                self.assertTrue(torch.equal(new_h, old_h) and torch.equal(new_m, old_m), seed)
                resolved += "resolved': 0" not in new_result
        self.assertGreater(resolved, 100, "the generator must produce real fights")

    def test_a_hook_that_changes_nothing_is_the_old_resolver_too(self):
        self.addCleanup(modifiers.set_modifier, None)
        modifiers.set_modifier(lambda h, attacker, target, damage: (target, damage))
        for seed in range(100):
            new_result, new_h, new_m = run(sys.modules["systems.combat.resolver"], seed)
            old_result, old_h, old_m = run(before, seed)
            self.assertEqual(new_result, old_result, seed)
            self.assertTrue(torch.equal(new_h, old_h) and torch.equal(new_m, old_m), seed)


class HookTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(modifiers.set_modifier, None)
        self.h = torch.zeros(8, 32)
        self.m = torch.zeros(8, 32)
        for slot, (x, y) in enumerate([(0.0, 0.0), (5.0, 0.0), (7.0, 0.0), (900.0, 900.0)]):
            self.h[slot, TYPE], self.h[slot, X], self.h[slot, Y] = float(AGENT_TYPE_HUMAN), x, y
            self.h[slot, HP], self.h[slot, H_STAMINA] = 100.0, 100.0

    def fight(self, attacker=0, target=1):
        intent = CombatIntent(source="t", action="attack", attacker_kind="human", attacker_slot=attacker, target_kind="human", target_slot=target, target_id="x")
        return resolve_human_attack_intents([intent], self.h, self.m, "cpu", walls=[])

    def test_a_guard_takes_the_hit_and_the_original_target_is_still_threatened(self):
        modifiers.set_modifier(lambda h, attacker, target, damage: (2, damage))
        result = self.fight()
        self.assertEqual(float(self.h[1, HP]), 100.0)
        self.assertEqual(float(self.h[2, HP]), 100.0 - cfg.ATTACK_DAMAGE)
        self.assertEqual(float(self.h[1, THREAT]), 40.0)
        self.assertEqual(float(self.h[2, THREAT]), 0.0)
        outcome = result["outcomes"][0]
        self.assertEqual(outcome["modified"], {"target_slot": 1, "damage": float(cfg.ATTACK_DAMAGE)})
        self.assertEqual((outcome["damage_slot"], outcome["target_slot"]), (2, 1))

    def test_a_weapon_and_a_shield_change_the_damage(self):
        modifiers.set_modifier(lambda h, attacker, target, damage: (target, damage * 2.0))
        self.fight()
        self.assertEqual(float(self.h[1, HP]), 100.0 - 2.0 * cfg.ATTACK_DAMAGE)
        self.h[1, HP] = 100.0
        self.h[0, H_STAMINA] = 100.0
        modifiers.set_modifier(lambda h, attacker, target, damage: (target, damage * 0.5))
        self.fight()
        self.assertEqual(float(self.h[1, HP]), 100.0 - 0.5 * cfg.ATTACK_DAMAGE)

    def test_zero_damage_still_threatens(self):
        modifiers.set_modifier(lambda h, attacker, target, damage: (target, 0.0))
        result = self.fight()
        self.assertEqual(float(self.h[1, HP]), 100.0)
        self.assertEqual(float(self.h[1, THREAT]), 40.0)
        self.assertIn("modified", result["outcomes"][0])

    def test_bad_answers_are_ignored(self):
        for answer in [(5, 10.0), (-1, 10.0), (2, -1.0), (2, float("nan")), (2, math.inf), None, "x", (1,), 7]:     # slot 5 is a free row
            self.h[1, HP] = 100.0
            self.h[0, H_STAMINA] = 100.0
            self.h[1, THREAT] = 0.0
            self.h[2, HP] = 100.0
            modifiers.set_modifier(lambda h, attacker, target, damage, a=answer: a)
            result = self.fight()
            self.assertEqual(float(self.h[1, HP]), 100.0 - cfg.ATTACK_DAMAGE, answer)
            self.assertEqual(float(self.h[2, HP]), 100.0, answer)
            self.assertNotIn("modified", result["outcomes"][0], answer)

    def test_a_modifier_that_raises_does_not_stop_the_fight(self):
        def boom(h, attacker, target, damage):
            raise RuntimeError("faulty")
        modifiers.set_modifier(boom)
        self.fight()
        self.assertEqual(float(self.h[1, HP]), 100.0 - cfg.ATTACK_DAMAGE)

    def test_entity_targets_are_not_offered_to_the_hook(self):
        calls = []
        modifiers.set_modifier(lambda h, attacker, target, damage: calls.append(target) or (target, damage))
        animal = sorted(cfg.ANIMAL_TYPES)[0]
        self.m[3, cfg.M_TYPE], self.m[3, cfg.CX], self.m[3, cfg.CY], self.m[3, cfg.M_HP] = float(animal), 4.0, 0.0, 60.0
        intent = CombatIntent(source="t", action="attack", attacker_kind="human", attacker_slot=0, target_kind="entity", target_slot=3, target_id="a")
        resolve_human_attack_intents([intent], self.h, self.m, "cpu", walls=[])
        self.assertEqual(calls, [])


class RestrainedAttackerTests(unittest.TestCase):
    def setUp(self):
        self.h = torch.zeros(4, 32)
        for slot, x in enumerate([0.0, 5.0]):
            self.h[slot, TYPE], self.h[slot, X], self.h[slot, HP], self.h[slot, H_STAMINA] = float(AGENT_TYPE_HUMAN), x, 100.0, 100.0
        self.h[0, H_RESTRAINED] = 5.0

    def hit(self):
        intent = CombatIntent(source="t", action="attack", attacker_kind="human", attacker_slot=0, target_kind="human", target_slot=1, target_id="x")
        return resolve_human_attack_intents([intent], self.h, torch.zeros(4, 32), "cpu", walls=[])["resolved"]

    def test_a_restrained_human_cannot_attack_when_the_flag_is_on(self):
        with mock.patch.dict(os.environ, {modifiers.RESTRAINT_FLAG: "1"}):
            self.assertEqual(self.hit(), 0)
            self.h[0, H_RESTRAINED] = 0.0
            self.assertEqual(self.hit(), 1)

    def test_flag_off_the_column_is_ignored(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(modifiers.RESTRAINT_FLAG, None)
            self.assertEqual(self.hit(), 1)


if __name__ == "__main__":
    unittest.main()
