import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'at_the_beginning'))
from harness import powers as pw
from harness.world import Table, World
import genesis_config as cfg

NAMES = {'age_shift', 'life_exp_modify', 'grant_instinct', 'revoke_instinct', 'inherit_instinct', 'quarantine'}

class MindTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'EDEN_GOD_POWER_PORTS': '1', 'EDEN_GOD_MIND_PORTS': '1'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.reg = pw.build_registry()
        cols = {'type': cfg.TYPE, 'age': cfg.H_AGE, 'life_exp': cfg.H_LIFE_EXP, 'infection': cfg.H_INFECTION,
                'cooldown': cfg.H_COOLDOWN, 'stamina': cfg.H_STAMINA, 'threat': cfg.THREAT,
                'acquired_instinct_mask': 19, 'acquired_instinct_mask_1': 25, 'acquired_instinct_mask_2': 26,
                'parent_instincts': 23, 'parent_instincts_1': 27, 'parent_instincts_2': 28}
        t = Table('humans', torch.zeros(4, cfg.HUMAN_TENSOR_COLS), cols, type_col='type')
        self.w = World(10, [t]); self.t = t
        self.ids = [self.w.add_row('humans', age=0.5, life_exp=10, infection=70, threat=90, stamina=5,
                                  parent_instincts_2=8) for _ in range(2)]
        self.sel = {'of': 'humans', 'ids': [self.ids[0]]}

    def test_gating(self):
        with patch.dict(os.environ, {'EDEN_GOD_MIND_PORTS': '0'}):
            self.assertFalse(NAMES & set(pw.build_registry().powers))
        self.assertTrue(NAMES <= set(self.reg.powers))

    def test_ports(self):
        cases = [('age_shift', {'years': -5}, {'age': 0}),
                 ('life_exp_modify', {'value': -5, 'mode': 'set'}, {'life_exp': 1}),
                 ('grant_instinct', {'bit': 63}, {'acquired_instinct_mask_2': 32768}),
                 ('revoke_instinct', {'bit': 63}, {'acquired_instinct_mask_2': 0}),
                 ('inherit_instinct', {}, {'acquired_instinct_mask_2': 8}),
                 ('quarantine', {}, {'cooldown': 5, 'stamina': 0, 'threat': 100})]
        for name, args, changed in cases:
            args = {'targets': self.sel, **args}
            before = self.t.tensor.clone()
            self.assertTrue(pw.call(self.w, name, args, dry_run=True, registry=self.reg).ok, name)
            self.assertTrue(torch.equal(before, self.t.tensor))
            result = pw.call(self.w, name, args, registry=self.reg)
            self.assertTrue(result.ok, (name, result.reason))
            expected = before.clone()
            for field, value in changed.items(): expected[0, self.t.col(field)] = value
            self.assertTrue(torch.equal(expected, self.t.tensor), name)
            self.assertFalse(pw.call(self.w, name, {**args, 'bogus': 1}, registry=self.reg).ok)
        for name in ('grant_instinct', 'revoke_instinct'):
            self.assertFalse(pw.call(self.w, name, {'targets': self.sel, 'bit': 64}, registry=self.reg).ok)
        for name, key in [('age_shift', 'years'), ('life_exp_modify', 'value')]:
            self.assertFalse(pw.call(self.w, name, {'targets': self.sel, key: float('inf')}, registry=self.reg).ok)

if __name__ == '__main__': unittest.main()


class IndividualPowerChecks(MindTests):
    def check_power(self, name, args, event):
        before = self.t.tensor.clone()
        result = pw.call(self.w, name, {'targets': self.sel, **args}, registry=self.reg, dry_run=True)
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(torch.equal(before, self.t.tensor))
        result = pw.call(self.w, name, {'targets': self.sel, **args}, registry=self.reg)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.report.events[0].type, event)
        self.assertTrue(torch.equal(before[1], self.t.tensor[1]))
        self.assertFalse(pw.call(self.w, name, {'targets': {'of': 'humans', 'ids': ['missing']}, **args}, registry=self.reg).ok)

class AgeShiftTests(IndividualPowerChecks):
    def test_age(self):
        self.check_power('age_shift', {'years': 2}, 'age_adjusted')
        self.assertEqual(self.t.get(self.ids[0], 'age'), 2.5)

class LifeExpTests(IndividualPowerChecks):
    def test_life(self):
        self.check_power('life_exp_modify', {'value': 2}, 'life_exp_adjusted')
        self.assertEqual(self.t.get(self.ids[0], 'life_exp'), 20)

class GrantInstinctTests(IndividualPowerChecks):
    def test_grant(self):
        self.check_power('grant_instinct', {'bit': 2}, 'instinct_granted')
        self.assertEqual(self.t.get(self.ids[0], 'acquired_instinct_mask'), 4)

class RevokeInstinctTests(IndividualPowerChecks):
    def test_revoke(self):
        self.t.tensor[0, self.t.col('acquired_instinct_mask')] = 7
        self.check_power('revoke_instinct', {'bit': 2}, 'instinct_revoked')
        self.assertEqual(self.t.get(self.ids[0], 'acquired_instinct_mask'), 3)

class InheritInstinctTests(IndividualPowerChecks):
    def test_inherit(self):
        self.check_power('inherit_instinct', {}, 'instinct_inherited')
        self.assertEqual(self.t.get(self.ids[0], 'acquired_instinct_mask_2'), 8)

class QuarantineTests(IndividualPowerChecks):
    def test_quarantine(self):
        self.check_power('quarantine', {}, 'quarantine')
        self.assertEqual(self.t.get(self.ids[0], 'threat'), 100)

class FlagCombinations(unittest.TestCase):
    def test_combinations(self):
        for ports in ('0', '1'):
            for mind in ('0', '1'):
                with patch.dict(os.environ, {'EDEN_GOD_POWER_PORTS': ports, 'EDEN_GOD_MIND_PORTS': mind, 'EDEN_GOD_NEW_TOOLS': '0'}):
                    names = set(pw.build_registry().powers)
                    self.assertEqual(bool(NAMES & names), ports == mind == '1')
                    with patch.dict(os.environ, {'EDEN_GOD_MIND_PORTS': '0'}):
                        baseline = set(pw.build_registry().powers)
                    if mind == '0':
                        self.assertEqual(names, baseline)


class KinTests(MindTests):
    def test_parent_cycle_and_gap(self):
        with patch.dict(os.environ, {'EDEN_GOD_NEW_TOOLS': '1'}):
            reg = pw.build_registry()
            parent, child = self.ids
            self.w.residents.update({parent: {}, child: {}})
            self.t.tensor[0, self.t.col('age')] = 30
            self.t.tensor[1, self.t.col('age')] = 5
            args = {'owner': parent, 'other': child, 'kind': 'parent'}
            self.assertTrue(pw.call(self.w, 'set_kin', args, registry=reg, dry_run=True).ok)
            self.assertEqual(self.w.residents[parent], {})
            result = pw.call(self.w, 'set_kin', args, registry=reg)
            self.assertTrue(result.ok)
            self.assertEqual(result.report.events[0].type, 'kin_changed')
            self.assertEqual(self.w.residents[child]['relationships'][parent]['kind'], 'parent')
            self.assertEqual(self.w.residents[parent]['relationships'][child]['kind'], 'child')
            self.t.tensor[1, self.t.col('age')] = 50
            self.assertFalse(pw.call(self.w, 'set_kin', {'owner': child, 'other': parent, 'kind': 'parent'}, registry=reg).ok)


class RefusalMatrix(MindTests):
    def test_refusals(self):
        cases = [ ('age_shift', {'targets': self.sel, 'years': float('nan')}),
                  ('life_exp_modify', {'targets': self.sel, 'value': float('inf')}),
                  ('life_exp_modify', {'targets': self.sel, 'value': 1, 'mode': 'bad'}),
                  ('grant_instinct', {'targets': self.sel, 'bit': -1}),
                  ('revoke_instinct', {'targets': self.sel, 'bit': 64}) ]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                self.assertFalse(pw.call(self.w, name, args, registry=self.reg).ok)
        for name, field in [('inherit_instinct', 'age'), ('quarantine', 'infection')]:
            self.t.tensor[:, self.t.col(field)] = 100 if field == 'age' else 0
            self.assertFalse(pw.call(self.w, name, {'targets': self.sel}, registry=self.reg).ok)
        for name, args, field in [('age_shift', {'years': 1}, 'age'), ('life_exp_modify', {'value': 1}, 'life_exp'),
                                  ('grant_instinct', {'bit': 0}, 'acquired_instinct_mask'),
                                  ('revoke_instinct', {'bit': 0}, 'acquired_instinct_mask'),
                                  ('inherit_instinct', {}, 'parent_instincts'), ('quarantine', {}, 'infection')]:
            col = self.t.columns.pop(field)
            try:
                self.assertFalse(pw.call(self.w, name, {'targets': self.sel, **args}, registry=self.reg).ok, name)
            finally:
                self.t.columns[field] = col

    def test_all_flag_combinations(self):
        for ports in ('0', '1'):
            for mind in ('0', '1'):
                for new in ('0', '1'):
                    with patch.dict(os.environ, {'EDEN_GOD_POWER_PORTS': ports, 'EDEN_GOD_MIND_PORTS': mind, 'EDEN_GOD_NEW_TOOLS': new}):
                        names = set(pw.build_registry().powers)
                        self.assertEqual(NAMES & names, NAMES if ports == mind == '1' else set())
                        new_names = {'inspect_resident', 'grant_item', 'set_kin', 'set_relationship', 'set_season', 'set_time_of_day'}
                        self.assertEqual(new_names & names, new_names if new == '1' else set())
