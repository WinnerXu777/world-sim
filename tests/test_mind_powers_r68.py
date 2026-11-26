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


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'EDEN_GOD_POWER_PORTS': '1', 'EDEN_GOD_MIND_PORTS': '1', 'EDEN_WINDOW': '0'})
        self.env.start(); self.addCleanup(self.env.stop)
        from harness.frame import SpaceFrame
        self.t = Table('humans', torch.zeros(3, 3), {'x': 0, 'y': 1, 'type': 2}, type_col='type', pos_cols=('x', 'y'))
        self.w = World(5, [self.t], frame=SpaceFrame(bounds=(0, 0, 20, 20)))
        self.a = self.w.add_row('humans', x=1, y=2)
        self.b = self.w.add_row('humans', x=4, y=5)
        self.reg = pw.build_registry()
        self.args = {'targets': {'of': 'humans', 'ids': [self.a]}, 'target_x': 101, 'target_y': 2, 'force': 100}

    def test_dry_run_atomic_and_bounded(self):
        before = self.t.tensor.clone()
        self.assertTrue(pw.call(self.w, 'migration', self.args, registry=self.reg, dry_run=True).ok)
        self.assertTrue(torch.equal(before, self.t.tensor))
        result = pw.call(self.w, 'migration', self.args, registry=self.reg)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(self.t.get(self.a, 'x'), 20)
        self.assertEqual(self.t.get(self.a, 'y'), 2)
        self.assertTrue(torch.equal(before[1], self.t.tensor[1]))
        self.assertEqual(result.report.events[0].type, 'migration')

    def test_refusals_and_gating(self):
        for force in (-1, float('inf'), float('nan')):
            self.assertFalse(pw.call(self.w, 'migration', {**self.args, 'force': force}, registry=self.reg).ok)
        with patch.dict(os.environ, {'EDEN_WINDOW': '1'}):
            self.assertEqual(pw.call(self.w, 'migration', self.args, registry=self.reg).reason, 'window_unsupported')
        with patch.dict(os.environ, {'EDEN_GOD_MIND_PORTS': '0'}):
            self.assertNotIn('migration', pw.build_registry().powers)

class AreaResourcePorts(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'EDEN_GOD_POWER_PORTS': '1', 'EDEN_GOD_MIND_PORTS': '1', 'EDEN_SPACES': '0'})
        env.start(); self.addCleanup(env.stop)
        self.h = Table('humans', torch.zeros(4, cfg.HUMAN_TENSOR_COLS),
                       {'x': cfg.X, 'y': cfg.Y, 'type': cfg.TYPE, 'hunger': cfg.HUNGER, 'thirst': cfg.THIRST}, type_col='type', pos_cols=('x', 'y'))
        self.e = Table('entities', torch.zeros(3, cfg.MAP_TENSOR_COLS),
                       {'x': cfg.CX, 'y': cfg.CY, 'type': cfg.M_TYPE, 'food': cfg.M_RESOURCE_FOOD, 'water': cfg.M_RESOURCE_WATER}, type_col='type', pos_cols=('x', 'y'))
        self.w = World(1, [self.h, self.e])
        self.ids = [self.w.add_row('humans', x=x, y=1, hunger=30, thirst=50) for x in (1, 2, 100)]
        self.source = self.w.add_row('entities', x=1, y=1, food=1.5, water=1, type=cfg.M_LAKE)
        self.reg = pw.build_registry()
        nearest = patch('systems.perception.queries.nearest_geo_entity', return_value=0)
        nearest.start(); self.addCleanup(nearest.stop)
        self.args = {'center_x': 1, 'center_y': 1, 'radius': 10}

    def test_limited_stock_and_dry_run(self):
        oldh, olde = self.h.tensor.clone(), self.e.tensor.clone()
        dry = pw.call(self.w, 'harvest_food', self.args, dry_run=True, registry=self.reg)
        self.assertTrue(dry.ok, dry.reason)
        self.assertTrue(torch.equal(oldh, self.h.tensor)); self.assertTrue(torch.equal(olde, self.e.tensor))
        got = pw.call(self.w, 'harvest_food', self.args, registry=self.reg)
        self.assertTrue(got.ok, got.reason)
        self.assertEqual([self.h.get(i, 'hunger') for i in self.ids], [10, 10, 30])
        self.assertEqual(self.e.get(self.source, 'food'), 0)
        self.assertEqual(got.report.events[0].type, 'food_harvested')
        self.assertFalse(pw.call(self.w, 'harvest_food', self.args, registry=self.reg).ok)

    def test_water_and_refusals(self):
        got = pw.call(self.w, 'draw_water', self.args, registry=self.reg)
        self.assertTrue(got.ok, got.reason)
        self.assertEqual([self.h.get(i, 'thirst') for i in self.ids], [15, 50, 50])
        self.assertEqual(self.e.get(self.source, 'water'), 0)
        self.assertFalse(pw.call(self.w, 'draw_water', {**self.args, 'radius': -1}, registry=self.reg).ok)
        self.assertFalse(pw.call(self.w, 'draw_water', {**self.args, 'thirst_restore': float('inf')}, registry=self.reg).ok)
        with patch('systems.perception.queries.nearest_geo_entity', return_value=-1):
            self.assertEqual(pw.call(self.w, 'draw_water', self.args, registry=self.reg).reason, 'no_source')
        with patch.dict(os.environ, {'EDEN_GOD_MIND_PORTS': '0'}):
            self.assertNotIn('draw_water', pw.build_registry().powers)
            self.assertNotIn('harvest_food', pw.build_registry().powers)

    def test_replan_after_stock_changes(self):
        from harness import effects as fx
        planned = pw.plan(self.w, 'harvest_food', self.args, registry=self.reg)
        self.assertTrue(planned.ok)
        self.w.apply([fx.set_('entities', [self.source], 'food', 0.25)], atomic=True)
        result = pw.apply(self.w, planned, registry=self.reg)
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(result.replanned)
        self.assertEqual([self.h.get(i, 'hunger') for i in self.ids], [10, 30, 30])
        self.assertEqual(self.e.get(self.source, 'food'), 0)

class ReproducePorts(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from harness.adapter import EngineWorld
        class Residents:
            def __init__(self): self.records = {}
            def get(self, uid): return self.records.get(uid)
            def ensure_resident(self, uid, slot, tensor, tick, **kw):
                self.records.setdefault(uid, {'slot': slot})
                return self.records[uid]
        class Engine:
            def _make_human_id(self):
                uid = f'h_{self._next_human_uid:06d}'
                self._next_human_uid += 1
                return uid
            def _human_inventory_record(self, owner): return {'items': []}
            def _storage_case_inventory_record(self, owner): return {'items': []}
        env = patch.dict(os.environ, {'EDEN_GOD_POWER_PORTS': '1', 'EDEN_GOD_MIND_PORTS': '1', 'EDEN_SPACES': '0'})
        env.start(); self.addCleanup(env.stop)
        e = Engine(); self.e = e
        e.state = SimpleNamespace(h_tensor=torch.zeros(6, cfg.HUMAN_TENSOR_COLS), m_tensor=torch.zeros(2, cfg.MAP_TENSOR_COLS), device='cpu')
        e._human_uid_by_slot = [None] * 6; e._entity_uid_by_slot = [None] * 2
        e._prev_h_mask = torch.zeros(6, dtype=torch.bool)
        e._pending_birth_links_by_slot = {}; e._next_human_uid = 10; e._pop_count = [3]
        e.tick = 17; e.resident_store = Residents(); e.inventory_state = {'inventories': {}}
        self.w = EngineWorld(e, seed=9); self.h = self.w.table('humans')
        self.ids = [self.w.add_row('humans', entity_id=f'h_{i+1:06d}', x=10+i, y=10, hp=100, stamina=100, age=25, sex=sex) for i, sex in enumerate((1, 1, 0))]
        e._prev_h_mask[:3] = True
        for i, uid in enumerate(self.ids): e.resident_store.ensure_resident(uid, i, e.state.h_tensor, 17)
        self.h.tensor[0, cfg.ACQUIRED_INSTINCT_MASK_1] = 8
        self.reg = pw.build_registry()

    def test_live_batch_dry_run_and_links(self):
        args = {'targets': {'of': 'humans'}}
        before = self.h.tensor.clone()
        plan = pw.plan(self.w, 'reproduce', args, registry=self.reg)
        self.assertTrue(plan.ok, plan.reason)
        self.assertEqual(len(plan.preview['births']), 2)
        self.assertTrue(torch.equal(before, self.h.tensor))
        self.assertEqual(self.e._next_human_uid, 10)
        out = pw.apply(self.w, plan, registry=self.reg)
        self.assertTrue(out.ok, out.reason)
        self.assertEqual(out.report.spawned, [('humans', 'h_000010'), ('humans', 'h_000011')])
        self.assertEqual(self.e._pop_count, [5])
        self.assertEqual(self.e._pending_birth_links_by_slot[3]['parent_ids'], [self.ids[0], self.ids[2]])
        self.assertEqual(self.e._pending_birth_links_by_slot[4]['parent_ids'], [self.ids[1], self.ids[2]])
        self.assertIn('h_000010', self.e.resident_store.records)
        self.assertEqual(self.h.get('h_000010', 'parent_instincts_1'), 8)
        self.assertGreater(self.h.get(self.ids[0], 'cooldown'), 0)
        self.assertEqual(out.report.events[0].type, 'reproduction')

    def test_stale_tick_is_atomic(self):
        plan = pw.plan(self.w, 'reproduce', {}, registry=self.reg)
        self.assertTrue(plan.ok)
        before = self.h.tensor.clone()
        self.e.tick += 1
        out = pw.apply(self.w, plan, registry=self.reg)
        self.assertFalse(out.ok)
        self.assertTrue(torch.equal(before, self.h.tensor))
        self.assertEqual(self.e._next_human_uid, 10)
        self.assertEqual(self.e._pending_birth_links_by_slot, {})

    def test_capacity_and_readiness(self):
        self.e._prev_h_mask[4:] = True
        out = pw.call(self.w, 'reproduce', {}, registry=self.reg)
        self.assertTrue(out.ok, out.reason)
        self.assertEqual(len(out.report.spawned), 1)
        self.assertEqual(self.e._pop_count, [4])
        with patch.dict(os.environ, {'EDEN_GOD_MIND_PORTS': '0'}):
            self.assertNotIn('reproduce', pw.build_registry().powers)

    def test_real_engine_processes_parent_links(self):
        import tempfile
        from harness.adapter import EngineWorld
        # Keep the real engine's disposable data inside the repository.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as root:
            with patch.dict(os.environ, {'EDEN_DATA_ROOT': root, 'EDEN_PROFILE': 'gameplay'}):
                import map_test
                engine = map_test.Engine()
                engine._runtime_profile = 'render_test'
                world = EngineWorld(engine, seed=9)
                table = world.table('humans')
                mother = world.add_row('humans', entity_id=engine._make_human_id(), x=20, y=20, hp=100, stamina=100, age=25, sex=1)
                father = world.add_row('humans', entity_id=engine._make_human_id(), x=21, y=20, hp=100, stamina=100, age=25, sex=0)
                engine._pop_count[0] = 2
                engine._prev_h_mask[:2] = True
                for slot, uid in enumerate((mother, father)):
                    engine.resident_store.ensure_resident(uid, slot, table.tensor, 0)
                plan = pw.plan(world, 'reproduce', {}, registry=self.reg)
                before_rows, before_ids = table.tensor.clone(), list(table.ids)
                store = engine.resident_store
                old_cache, old_dirty = dict(store._cache), set(store._dirty)
                old_memory, old_revisions = set(store._memory_dirty), dict(store._revisions)
                real_ensure = store.ensure_resident
                def broken(uid, slot, tensor, tick):
                    real_ensure(uid, slot, tensor, tick)
                    raise RuntimeError('injected resident store failure')
                with patch.object(store, 'ensure_resident', side_effect=broken):
                    failed = pw.apply(world, plan, registry=self.reg)
                self.assertFalse(failed.ok)
                self.assertTrue(failed.report.rolled_back)
                self.assertTrue(torch.equal(before_rows, table.tensor))
                self.assertEqual(before_ids, table.ids)
                self.assertEqual(store._cache, old_cache)
                self.assertEqual(store._dirty, old_dirty)
                self.assertEqual(store._memory_dirty, old_memory)
                self.assertEqual(store._revisions, old_revisions)
                self.assertEqual(engine._next_human_uid, 3)
                self.assertEqual(engine._pending_birth_links_by_slot, {})
                out = pw.call(world, 'reproduce', {}, registry=self.reg)
                self.assertTrue(out.ok, out.reason)
                child = out.report.spawned[0][1]
                h, a, m = engine._current_masks()
                engine._sync_slot_ids_and_events(h, a, m)
                self.assertEqual(engine._pending_birth_links_by_slot, {})
                self.assertEqual(engine.resident_store.get(child)['relationships'][mother]['kind'], 'parent')
                self.assertEqual(engine.resident_store.get(mother)['relationships'][child]['kind'], 'child')
                self.assertEqual(engine.resident_store.get(child)['relationships'][father]['kind'], 'parent')

    def test_uid_collision_and_disabled_apply_are_atomic(self):
        args = {'targets': {'of': 'humans'}}
        plan = pw.plan(self.w, 'reproduce', args, registry=self.reg)
        before = self.h.tensor.clone()
        self.e._human_uid_by_slot[5] = 'h_000010'
        self.assertFalse(pw.apply(self.w, plan, registry=self.reg).ok)
        self.assertTrue(torch.equal(before, self.h.tensor))
        self.assertEqual(self.e._next_human_uid, 10)
        self.e._human_uid_by_slot[5] = None
        with patch.dict(os.environ, {'EDEN_GOD_MIND_PORTS': '0'}):
            self.assertFalse(pw.apply(self.w, plan, registry=self.reg).ok)
        self.assertTrue(torch.equal(before, self.h.tensor))

    def test_same_tick_parent_changes_refused(self):
        for field, value in [('x', 100), ('cooldown', 1), ('sex', 0), ('age', 5)]:
            with self.subTest(field=field):
                plan = pw.plan(self.w, 'reproduce', {}, registry=self.reg)
                self.assertTrue(plan.ok)
                slot = self.h.slot_of(self.ids[0]); col = self.h.col(field)
                before = self.h.tensor[slot, col].item()
                self.h.tensor[slot, col] = value
                after_external_change = self.h.tensor.clone()
                out = pw.apply(self.w, plan, registry=self.reg)
                self.assertFalse(out.ok)
                self.assertTrue(torch.equal(after_external_change, self.h.tensor))
                self.assertEqual(self.e._next_human_uid, 10)
                self.h.tensor[slot, col] = before

    def test_failed_birth_rolls_back_all(self):
        plan = pw.plan(self.w, 'reproduce', {}, registry=self.reg)
        old_rows, old_ids = self.h.tensor.clone(), list(self.h.ids)
        old_records = dict(self.e.resident_store.records)
        ensure = self.e.resident_store.ensure_resident
        def fail(uid, slot, tensor, tick):
            ensure(uid, slot, tensor, tick)
            if uid == 'h_000011': raise RuntimeError('injected failure')
        with patch.object(self.e.resident_store, 'ensure_resident', side_effect=fail):
            out = pw.apply(self.w, plan, registry=self.reg)
        self.assertFalse(out.ok)
        self.assertTrue(out.report.rolled_back)
        self.assertEqual(out.report.skipped[0].reason, 'birth_failed')
        self.assertEqual(out.report.spawned, [])
        self.assertTrue(torch.equal(old_rows, self.h.tensor))
        self.assertEqual(old_ids, self.h.ids)
        self.assertEqual(self.e.resident_store.records, old_records)
        self.assertEqual(self.e._next_human_uid, 10)
        self.assertEqual(self.e._pop_count, [3])
        self.assertEqual(self.e._pending_birth_links_by_slot, {})
        self.assertEqual(self.w.revision, 0)
        self.assertEqual(self.w.events.events(), [])

    def test_resource_ports_use_live_geometry(self):
        import map_geo
        et = self.w.table('entities')
        eid = next(i for i in range(cfg.MAX_ENTITIES) if i not in map_geo.MAP_GEO)
        self.e.state.m_tensor = torch.zeros(cfg.MAX_ENTITIES, cfg.MAP_TENSOR_COLS)
        self.e._entity_uid_by_slot = [None] * cfg.MAX_ENTITIES
        et.tensor = self.e.state.m_tensor
        source = 'e_000001'
        et.ids[eid] = source
        for field, value in {'x': 600, 'y': 600, 'type': cfg.M_LAKE, 'food': 1, 'water': 1, 'scale': 32}.items():
            et.tensor[eid, et.col(field)] = value
        for uid in self.ids:
            self.h.tensor[self.h.slot_of(uid), cfg.X] = 600
            self.h.tensor[self.h.slot_of(uid), cfg.Y] = 600
        map_geo.register_entity(eid, 'circle', 600, 600, 32)
        try:
            for power, field in [('harvest_food', 'food'), ('draw_water', 'water')]:
                out = pw.call(self.w, power, {'center_x': 600, 'center_y': 600, 'radius': 24}, registry=self.reg)
                self.assertTrue(out.ok, (power, out.reason))
                self.assertEqual(et.get(source, field), 0)
                self.assertTrue(self.e._force_map_refresh)
        finally:
            map_geo.unregister_entity(eid)

    def test_resource_same_tick_changes_are_refused(self):
        import map_geo
        et = self.w.table('entities')
        source = self.w.add_row('entities', entity_id='e_000001', x=10, y=10, type=cfg.M_LAKE, food=2, water=2)
        args = {'center_x': 10, 'center_y': 10, 'radius': 24}
        with patch('systems.perception.queries.nearest_geo_entity', return_value=0):
            plan = pw.plan(self.w, 'harvest_food', args, registry=self.reg)
            self.assertTrue(plan.ok)
            et.tensor[0, et.col('food')] = 0
            before = self.h.tensor.clone()
            self.assertFalse(pw.apply(self.w, plan, registry=self.reg).ok)
            self.assertTrue(torch.equal(before, self.h.tensor))
            self.assertEqual(et.get(source, 'food'), 0)
            et.tensor[0, et.col('food')] = 2
            plan = pw.plan(self.w, 'draw_water', args, registry=self.reg)
            old_version = map_geo.geo_version
            try:
                map_geo.geo_version += 1
                self.assertFalse(pw.apply(self.w, plan, registry=self.reg).ok)
                self.assertEqual(et.get(source, 'water'), 2)
            finally:
                map_geo.geo_version = old_version

    def test_no_birth_plan_rejects_same_tick_eligibility_change(self):
        self.h.tensor[:3, cfg.H_SEX] = 0
        self.h.tensor[0, cfg.H_COOLDOWN] = 0.2
        plan = pw.plan(self.w, 'reproduce', {}, registry=self.reg)
        self.assertTrue(plan.ok)
        self.assertEqual(plan.preview['births'], [])
        self.assertEqual(plan.effects[0].births, ())
        self.h.tensor[1, cfg.H_SEX] = 1
        before = self.h.tensor.clone()
        out = pw.apply(self.w, plan, registry=self.reg)
        self.assertFalse(out.ok)
        self.assertTrue(out.report.rolled_back)
        self.assertTrue(torch.equal(before, self.h.tensor))
        self.assertEqual(self.e._next_human_uid, 10)
        self.assertEqual(self.e._pending_birth_links_by_slot, {})
        self.assertEqual(self.w.events.events(), [])
