import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'at_the_beginning'))
from harness import powers
from harness.world import World

class NewPowersTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'EDEN_GOD_NEW_TOOLS': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.reg = powers.build_registry()
        self.world = World.synthetic()
        self.uid = self.world.add_row('humans', hp=100)
        self.targets = {'of': 'humans', 'ids': [self.uid]}

    def test_flag_off(self):
        with patch.dict(os.environ, {'EDEN_GOD_NEW_TOOLS': '0'}):
            self.assertNotIn('grant_item', powers.build_registry().powers)
            self.assertNotIn('inspect_resident', powers.build_registry().powers)

    def test_inspection_is_read_only(self):
        self.world.residents[self.uid] = {'memory': {'danger': [1]}, 'opinions': {'x': 4}}
        before = copy.deepcopy(self.world.residents)
        revision = self.world.revision
        for dry in (True, False):
            result = powers.call(self.world, 'inspect_resident', {'targets': self.targets}, registry=self.reg, dry_run=dry)
            self.assertTrue(result.ok)
            result.plan.preview['residents'][self.uid]['memory']['danger'].append(2)
            self.assertEqual(self.world.residents, before)
            self.assertEqual(self.world.revision, revision)

    def test_grant(self):
        args = {'targets': self.targets, 'item': 'wood_bundle', 'qty': 2}
        self.assertTrue(powers.call(self.world, 'grant_item', args, registry=self.reg, dry_run=True).ok)
        self.assertEqual(self.world.items.quantity(self.uid, 'wood_bundle'), 0)
        self.assertTrue(powers.call(self.world, 'grant_item', args, registry=self.reg).ok)
        self.assertEqual(self.world.items.quantity(self.uid, 'wood_bundle'), 2)
        args['item'] = 'nonexistent'
        self.assertFalse(powers.call(self.world, 'grant_item', args, registry=self.reg).ok)
        args.update(item='wood_bundle', qty=0)
        self.assertFalse(powers.call(self.world, 'grant_item', args, registry=self.reg).ok)


class AddedPowersTests(NewPowersTests):
    def setUp(self):
        super().setUp()
        from harness import calendar
        self.calendar = calendar
        self.other = self.world.add_row('humans', hp=100)
        self.world.residents.update({self.uid: {}, self.other: {}})

    def test_relationship_and_kin(self):
        args = {'owner': self.uid, 'other': self.other, 'value': 0.75}
        before = copy.deepcopy(self.world.residents)
        self.assertTrue(powers.call(self.world, 'set_relationship', args, registry=self.reg, dry_run=True).ok)
        self.assertEqual(before, self.world.residents)
        result = powers.call(self.world, 'set_relationship', args, registry=self.reg)
        self.assertTrue(result.ok)
        self.assertEqual(self.world.residents[self.uid]['relationships'][self.other]['closeness'], .75)
        self.assertEqual(result.report.events[0].type, 'relationship_changed')
        self.assertFalse(powers.call(self.world, 'set_relationship', {**args, 'value': 2}, registry=self.reg).ok)
        self.assertFalse(powers.call(self.world, 'set_relationship', {**args, 'other': 'missing'}, registry=self.reg).ok)
        result = powers.call(self.world, 'set_kin', {'owner': self.uid, 'other': self.other, 'kind': 'spouse'}, registry=self.reg)
        self.assertTrue(result.ok)
        self.assertEqual(self.world.residents[self.other]['relationships'][self.uid]['kind'], 'mate')
        self.assertFalse(powers.call(self.world, 'set_kin', {'owner': self.uid, 'other': self.uid, 'kind': 'parent'}, registry=self.reg).ok)
        self.assertFalse(powers.call(self.world, 'set_kin', {'owner': self.uid, 'other': self.other, 'kind': 'parent'}, registry=self.reg).ok)

    def test_calendar_overrides(self):
        tick = self.world.tick
        for name, field, value, event in [('set_season', 'season', 'winter', 'season_changed'), ('set_time_of_day', 'time', 'night', 'time_changed')]:
            args = {'value': value}
            before = getattr(self.calendar.for_world(self.world), field + '_override')
            self.assertTrue(powers.call(self.world, name, args, registry=self.reg, dry_run=True).ok)
            self.assertEqual(getattr(self.calendar.for_world(self.world), field + '_override'), before)
            result = powers.call(self.world, name, args, registry=self.reg)
            self.assertTrue(result.ok)
            self.assertEqual(result.report.events[0].type, event)
            self.assertEqual(getattr(self.calendar.for_world(self.world), field + '_override'), value)
            self.assertTrue(powers.call(self.world, name, {'value': 'clear'}, registry=self.reg).ok)
            self.assertIsNone(getattr(self.calendar.for_world(self.world), field + '_override'))
            self.assertFalse(powers.call(self.world, name, {'value': 'bad'}, registry=self.reg).ok)
        self.assertEqual(self.world.tick, tick)

    def test_item_permit(self):
        from harness import effects
        plan = powers.plan(self.world, 'grant_item', {'targets': self.targets, 'item': 'wood_bundle', 'qty': 2}, registry=self.reg)
        report = effects.EffectApplier(self.world).apply(plan.effects, atomic=True)
        self.assertFalse(report.ok)
        self.assertEqual(self.world.items.quantity(self.uid, 'wood_bundle'), 0)


class GrantItemRefusalTests(NewPowersTests):
    def test_no_room(self):
        with patch.object(self.world.items, 'room', return_value=0):
            result = powers.call(self.world, 'grant_item', {'targets': self.targets, 'item': 'wood_bundle'}, registry=self.reg)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'no_room')


class InspectResidentTests(NewPowersTests):
    def test_empty_selection_refused(self):
        result = powers.call(self.world, 'inspect_resident', {'targets': {'of': 'humans', 'ids': ['missing']}}, registry=self.reg)
        self.assertFalse(result.ok)

class GrantItemTests(NewPowersTests):
    def test_event_and_selection(self):
        other = self.world.add_row('humans', hp=100)
        result = powers.call(self.world, 'grant_item', {'targets': self.targets, 'item': 'wood_bundle'}, registry=self.reg)
        self.assertTrue(result.ok)
        self.assertEqual(result.report.events[0].type, 'item_granted')
        self.assertEqual(self.world.items.quantity(other, 'wood_bundle'), 0)
        self.assertFalse(powers.call(self.world, 'grant_item', {'targets': {'of': 'humans', 'ids': ['missing']}, 'item': 'wood_bundle'}, registry=self.reg).ok)

class NewFlagTests(unittest.TestCase):
    def test_other_flag_combinations(self):
        new_names = {'inspect_resident', 'grant_item', 'set_kin', 'set_relationship', 'set_season', 'set_time_of_day'}
        for ports in ('0', '1'):
            for mind in ('0', '1'):
                with patch.dict(os.environ, {'EDEN_GOD_POWER_PORTS': ports, 'EDEN_GOD_MIND_PORTS': mind, 'EDEN_GOD_NEW_TOOLS': '0'}):
                    baseline = set(powers.build_registry().powers)
                    self.assertFalse(new_names & baseline)
                    with patch.dict(os.environ, {'EDEN_GOD_NEW_TOOLS': '1'}):
                        self.assertEqual(set(powers.build_registry().powers) - baseline, new_names)


class GapTests(AddedPowersTests):
    def test_isolation_and_light(self):
        other = World.synthetic()
        with patch.dict(os.environ, {'EDEN_CALENDAR': '1'}):
            self.assertTrue(powers.call(self.world, 'set_time_of_day', {'value': 'night'}, registry=self.reg).ok)
            self.assertTrue(powers.call(self.world, 'set_season', {'value': 'winter'}, registry=self.reg).ok)
            cal = self.calendar.for_world(self.world)
            self.assertEqual(cal.block_for_tick(3000), 'night')
            self.assertEqual(cal.season_for_tick(3000), 'winter')
            self.assertEqual(cal.light_at(3000), self.calendar.LIGHT_FLOOR)
            self.assertEqual(self.calendar.for_world(other).season_for_tick(3000), 'spring')
            self.assertNotEqual(self.calendar.for_world(other).block_for_tick(3000), 'night')

    def test_atomic_invalid_effects(self):
        from harness import effects as fx
        for effect in (fx.CalendarOverride('time', 'bad'), fx.CalendarOverride('bad', None),
                       fx.ResidentRelations(((self.uid, self.other, 'known', float('nan')),)),
                       fx.ResidentRelations((('missing', self.other, 'known', 0),)),
                       fx.ResidentRelations(((self.uid, self.other, '', None),)),
                       fx.ResidentRelations((('bad',),))):
            report = self.world.effects.apply([fx.CalendarOverride('season', 'winter'), effect], atomic=True)
            self.assertFalse(report.ok)
            self.assertIsNone(self.calendar.for_world(self.world).season_override)

    def test_engine_store_is_called(self):
        from harness import effects as fx
        from unittest.mock import Mock
        engine = Mock()
        self.world.engine = engine
        self.world.effects.apply([fx.ResidentRelations(((self.uid, self.other, 'mate', .5),))], atomic=True)
        engine.resident_store.update_relationship.assert_called_once_with(self.uid, self.other, 'mate', .5, self.world.tick)


class NewRefusalMatrix(AddedPowersTests):
    def test_invalid_inputs(self):
        cases = [('grant_item', {'targets': self.targets, 'item': 'missing'}, 'unknown_item'),
                 ('grant_item', {'targets': self.targets, 'item': 'wood_bundle', 'qty': 0}, 'invalid_quantity'),
                 ('set_relationship', {'owner': self.uid, 'other': self.uid, 'value': 0}, 'self_link'),
                 ('set_relationship', {'owner': self.uid, 'other': self.other, 'value': float('inf')}, 'invalid_arguments'),
                 ('set_kin', {'owner': self.uid, 'other': 'missing', 'kind': 'spouse'}, 'unknown_resident'),
                 ('set_kin', {'owner': self.uid, 'other': self.other, 'kind': 'parent'}, 'no_column'),
                 ('set_season', {'value': 'bad'}, 'invalid_value'),
                 ('set_time_of_day', {'value': 'bad'}, 'invalid_value')]
        for name, args, reason in cases:
            with self.subTest(name=name, reason=reason):
                result = powers.call(self.world, name, args, registry=self.reg)
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, reason)

