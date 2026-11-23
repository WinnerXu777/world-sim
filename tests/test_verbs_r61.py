import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'at_the_beginning'))
from test_actions_runner import Scene, setrow
from systems.actions.r61 import InvitationBook
from systems.actions import catalog
from systems.decision.matrix import K

class R61Tests(unittest.TestCase):
    def setUp(self):
        self.flag = patch.dict(os.environ, {'EDEN_VERBS_R61': '1'})
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.s = Scene()

    def test_retaliate(self):
        s = self.s
        self.assertEqual(s.runner.run('h_a', 'retaliate', {'target': 'h_b'}).code, 'illegal:no_justification')
        s.records['h_a']['goals'] = [{'id':'g1','kind':'retaliate','target_id':'h_b','status':'active'}]
        self.assertEqual(s.runner.run('h_a', 'retaliate', {'target':'h_b'}, proposer='model', confidence=0.1).code, 'risk_gated')
        r = s.runner.run('h_a', 'retaliate', {'target':'h_b'})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(s.records['h_a']['tasks'][0]['task_kind'], 'attack_target')
        self.assertEqual(s.records['h_a']['tasks'][0]['metadata']['justification']['id'], 'g1')
        self.assertEqual(r.report.events[0].type, 'began_retaliation')

    def test_recorded_harm(self):
        self.s.records['h_a']['memory'] = {'recent_events': [{'kind':'attacked', 'other_human_id':'h_b', 'tick': 2}]}
        result = self.s.runner.run('h_a', 'retaliate', {'target':'h_b'})
        self.assertTrue(result.ok, result.code)
        self.assertEqual(result.draft.preview['justification']['kind'], 'harm')

    def test_forgive(self):
        s = self.s
        self.assertEqual(s.runner.run('h_a', 'forgive', {'target':'h_b'}).code, 'illegal:no_grievance')
        s.records['h_a']['relationships']['h_b'] = {'closeness': -0.4}
        s.records['h_a']['goals'] = [{'kind':'retaliate','target_id':'h_b'}, {'kind':'retaliate','target_id':'h_smith'}]
        r = s.runner.run('h_a', 'forgive', {'target':'h_b'})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(s.records['h_a']['relationships']['h_b']['closeness'], -0.25)
        self.assertEqual(len(s.records['h_a']['goals']), 1)
        self.assertEqual(r.report.events[0].type, 'forgave')

    def test_invite(self):
        s = self.s
        self.assertEqual(s.runner.run('h_a', 'invite', {'target':'h_far','place':'v:bed'}).code, 'illegal:no_target')
        r = s.runner.run('h_a', 'invite', {'target':'h_b','place':'v:bed'})
        self.assertTrue(r.ok, (r.code, r.detail))
        self.assertEqual(r.ops[0]['answer'], 'accepted')
        self.assertEqual(r.report.events[0].type, 'invited')
        self.assertIn('invitation_accepted', [e.type for e in s.world.events.events()])
        s.records['h_b']['relationships']['h_a'] = {'closeness': -0.1}
        r = s.runner.run('h_a', 'invite', {'target':'h_b','place':'v:bed'})
        self.assertEqual(r.ops[0]['answer'], 'declined')
        setrow(s.world, 'h_b', mood=20)
        s.records['h_b']['relationships']['h_a']['closeness'] = 0.3
        r = s.runner.run('h_a', 'invite', {'target':'h_b','place':'v:bed'})
        self.assertEqual(r.ops[0]['answer'], 'declined')
        book = InvitationBook(); entry = book.open('a','b','p',0)
        self.assertEqual(book.answer(entry,60,1,100), 'expired')

    def test_invitation_travel_and_expiry(self):
        s = self.s
        result = s.runner.run('h_a', 'invite', {'target': 'h_b', 'place': 'v:bed'})
        self.assertTrue(result.ok)
        task = s.records['h_b']['tasks'][0]
        self.assertEqual(task['task_kind'], 'move_to_place')
        self.assertEqual(task['target_place'], {'x': 12.0, 'y': 10.0})
        self.assertEqual(task['expires_tick'], 60)
        s.runner.expire_invitations(59)
        self.assertEqual(len(s.records['h_b']['tasks']), 1)
        s.runner.expire_invitations(60)
        self.assertEqual(s.records['h_b']['tasks'], [])
        self.assertEqual(s.services._r61_invitations.records[0]['state'], 'expired')
        self.assertIn('invitation_expired', [e.type for e in s.world.events.events()])
        s.runner.expire_invitations(61)
        self.assertEqual([e.type for e in s.world.events.events()].count('invitation_expired'), 1)

    def test_pending_expiry_and_decline(self):
        s = self.s
        from systems.actions.r61 import invitations_of
        book = invitations_of(s.services)
        entry = book.open('h_a', 'h_b', 'v:bed', 0)
        s.runner.expire_invitations(60)
        self.assertEqual(entry['state'], 'expired')
        s.records['h_b']['relationships']['h_a'] = {'closeness': -0.3}
        result = s.runner.run('h_a', 'invite', {'target': 'h_b', 'place': 'v:bed'})
        self.assertEqual(result.ops[0]['answer'], 'declined')
        self.assertEqual(s.records['h_b'].get('tasks', []), [])
        self.assertIn('invitation_declined', [e.type for e in s.world.events.events()])

    def test_failed_atomic_apply_does_not_open_invitation(self):
        from types import SimpleNamespace
        s = self.s
        with patch.object(s.world, 'apply', return_value=SimpleNamespace(ok=False, skipped=[])) as apply:
            result = s.runner.run('h_a', 'invite', {'target': 'h_b', 'place': 'v:bed'})
        self.assertEqual(result.code, 'apply_failed')
        self.assertEqual(len(apply.call_args.args[0]), 2)
        self.assertEqual(s.services._r61_invitations.records, [])
        self.assertNotIn('tasks', s.records['h_b'])

    def test_predicate_refusals(self):
        aff = self.s.runner.aff
        for verb, args, reason in [
            ('forgive', {}, 'invalid_params'),
            ('forgive', {'target':'h_a'}, 'self_target'),
            ('forgive', {'target':'missing'}, 'no_target'),
            ('forgive', {'target':'h_b'}, 'no_grievance'),
            ('invite', {'target':'h_b'}, 'invalid_params'),
            ('invite', {'target':'h_b','place':'missing'}, 'no_place'),
            ('invite', {'target':'h_a','place':'v:bed'}, 'self_target'),
            ('retaliate', {'target':'h_b'}, 'no_justification'),
        ]:
            with self.subTest(verb=verb, args=args):
                self.assertEqual(aff.legal('h_a', verb, args).reason, reason)

    def test_social_predicate_refusals(self):
        aff = self.s.runner.aff
        for verb in ('invite', 'retaliate'):
            extra = {'place': 'v:bed'} if verb == 'invite' else {}
            for target, reason in [('', 'invalid_params'), ('h_a', 'self_target'),
                                   ('h_far', 'no_target'), ('h_dead', 'target_dead')]:
                with self.subTest(verb=verb, target=target):
                    self.assertEqual(aff.legal('h_a', verb, {'target': target, **extra}).reason, reason)
            self.assertEqual(aff.legal('h_dead', verb, {'target': 'h_a', **extra}).reason, 'dead')
        self.assertEqual(aff.legal('h_dead', 'forgive', {'target': 'h_a'}).reason, 'dead')

    def test_flag_off_preserves_existing_catalog_and_matrix(self):
        s = self.s
        with patch.dict(os.environ, {'EDEN_VERBS_R61':'0'}):
            self.assertNotIn('invite', s.runner.registry.actions)
            self.assertNotIn('retaliate', s.runner.registry.actions)
            from systems.affordance.engine import AffordanceEngine
            off = AffordanceEngine(s.world, s.runner.services)
            self.assertEqual(off.legal('h_a','invite',{}).reason, 'unknown_verb')
            from systems.actions.agent_driver import AgentDriver, ROUTABLE_VERBS
            from systems.affordance.engine import MACRO_VERBS
            driver = AgentDriver()
            self.assertEqual(driver.r61_routable, ROUTABLE_VERBS)
            self.assertEqual(off._macros, MACRO_VERBS)
            self.assertNotIn('invite', off._definitions)
            self.assertNotIn('retaliate', off._definitions)

            self.assertEqual(len(catalog.CATALOG), 65)
            width = s.runner.aff.mask(['h_a']).shape[1]
        self.assertEqual(width, K)
        self.assertEqual(s.runner.aff.mask(['h_a']).shape[1], width)

if __name__ == '__main__': unittest.main()
