"""Pure/mock long-walk probes; no backend process is launched."""
import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import Mock

from tools.live_smoke_window import displacement, distance_result, stamped_input, memory_summary, phase_long_walk, player_void_delta


class LongWalkTests(unittest.TestCase):
    def test_distance_across_positive_negative_and_large_rebases(self):
        self.assertEqual(displacement(((0, 0), (10, 20)), ((20, -2), (-110, 532))), (5000, 0))
        self.assertEqual(displacement(((20, -2), (-110, 532)), ((0, 0), (10, 20))), (-5000, 0))
        huge = 2**60
        self.assertEqual(displacement(((huge, -huge), (10, 20)), ((huge+20, -huge-2), (-110, 532))), (5000, 0))

    def test_incomplete_legs_cannot_pass(self):
        self.assertFalse(distance_result(4999, (0, 0), 5000, False)['outbound_complete'])
        self.assertFalse(distance_result(5000, (40, 0), 5000, True)['return_complete'])
        result = distance_result(5000, (10, 10), 5000, True)
        self.assertTrue(result['outbound_complete'] and result['return_complete'])

    def counters(self):
        return dict(accepted=0, stale_window=0, stale_exhausted=0, valid_input_rejected=0)

    def reply(self, code, **payload):
        return SimpleNamespace(status_code=code, json=lambda: payload)

    def test_stale_refresh_stamps_and_new_sequence(self):
        bodies = []
        replies = iter([self.reply(409, reason='stale_window_epoch'), self.reply(200, ok=True)])
        def post(path, body):
            bodies.append(dict(body))
            return next(replies)
        b = SimpleNamespace(post=post, get=lambda _: self.reply(200, window_epoch=4))
        counts = self.counters()
        stamped_input(b, {'seq': 2}, {'window_epoch': 3}, counts)
        self.assertEqual([(p['seq'], p['window_epoch']) for p in bodies], [(2, 3), (3, 4)])
        self.assertEqual(counts, dict(accepted=1, stale_window=1, stale_exhausted=0, valid_input_rejected=0))

    def test_stale_budget_and_permanent_reject(self):
        b = SimpleNamespace(post=Mock(return_value=self.reply(409, reason='stale_window_epoch')),
                            get=Mock(return_value=self.reply(200, window_epoch=4)))
        counts = self.counters()
        with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
            stamped_input(b, {'seq': 1}, {'window_epoch': 3}, counts)
        self.assertEqual(b.post.call_count, 3)
        self.assertEqual(b.get.call_count, 2)
        self.assertEqual(counts['stale_exhausted'], 1)
        b.post = Mock(return_value=self.reply(409, reason='possession_epoch_mismatch'))
        b.get.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'input rejected'):
            stamped_input(b, {'seq': 1}, {'window_epoch': 3}, counts)
        self.assertEqual(b.post.call_count, 1)
        b.get.assert_not_called()
        self.assertEqual(counts['valid_input_rejected'], 1)

    def test_missing_memory_is_unknown_and_no_invented_bound(self):
        result = memory_summary([{'bytes': None, 'source': None}])
        self.assertIsNone(result['peak_bytes'])
        self.assertIsNone(result['bounded_growth_acceptance'])
        self.assertTrue(result['missing'])
        self.assertEqual(memory_summary([{'bytes': 100}, {'bytes': 200}, {'bytes': 150}])['peak_bytes'], 200)

    def test_ambiguous_transport_failure_is_not_replayed(self):
        b = SimpleNamespace(post=Mock(side_effect=httpx.ReadTimeout('timeout')), get=Mock())
        with self.assertRaises(httpx.ReadTimeout):
            stamped_input(b, {'seq': 1}, {'window_epoch': 1}, self.counters())
        self.assertEqual(b.post.call_count, 1)
        b.get.assert_not_called()

    def test_timeout_does_not_become_live_pass(self):
        frame = dict(window_origin=[0, 0], window_epoch=1, agents=[dict(id='p', x=0, y=0)])
        b = SimpleNamespace(proc=SimpleNamespace(pid=0), post=lambda *a: self.reply(200, ok=True, target_id='p', world_epoch=1, possession_epoch=1),
                            get=lambda *a: self.reply(200, **frame))
        evidence = {}
        phase_long_walk(b, 5000, 0, evidence)
        self.assertFalse(evidence['outbound_complete'])
        self.assertFalse(evidence['return_complete'])
        self.assertFalse(evidence['measured_walk_pass'])
        self.assertFalse(evidence['live_gate_complete'])
        self.assertIsNone(evidence['void_hits'])

    def stats(self, player=0, resident=0):
        return {'counters': {'void_hits': player+resident, 'void_hits_player': player, 'void_hits_resident': resident}}

    def delta(self, before, after, **kwargs):
        scope = dict(before_world_epoch='world-a', after_world_epoch='world-a', same_manager=True, same_counter_generation=True, sole_controller=True)
        scope.update(kwargs)
        return player_void_delta(before, after, **scope)

    def test_prepared_counter_adapter_distinguishes_player_and_resident(self):
        result = self.delta(self.stats(3, 7), self.stats(3, 10))
        self.assertTrue(result['known'])
        self.assertEqual(result['player_void_hits'], 0)
        self.assertEqual(result['resident_void_hits'], 3)
        self.assertEqual(self.delta(self.stats(3), self.stats(5))['player_void_hits'], 2)

    def test_missing_invalid_reset_or_changed_scope_counters_stay_unknown(self):
        for invalid in ({}, {'counters': {}}, self.stats(True), self.stats(-1),
                        {'counters': {'void_hits': 3, 'void_hits_player': 1, 'void_hits_resident': 1}}):
            result = self.delta(self.stats(), invalid)
            self.assertFalse(result['known'])
            self.assertIsNone(result['player_void_hits'])
        self.assertFalse(self.delta(self.stats(2), self.stats(1))['known'])
        for scope in ({'same_manager': False}, {'same_counter_generation': False}, {'sole_controller': False}, {'after_world_epoch': 'world-b'}):
            self.assertFalse(self.delta(self.stats(), self.stats(), **scope)['known'])


if __name__ == '__main__':
    unittest.main()
