"""Pure/mock long-walk probes; no backend process is launched."""
import math
import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import Mock

from tools.live_smoke_window import (displacement, distance_result, stamped_input, memory_summary, memory_bound, phase_long_walk, player_void_delta,
                                     left_behind_stable, live_gate, void_from_window_stats, Steer, route_verdict, backend_pid,
                                     Breadcrumbs)


def simulate(walls, goal_x=None, speed=10.0, steps=6000, start=(0.0, 0.0), jitter=0.0, heading=None, done=None, name='out', **steer_kw):
    """A point walker on a plane with axis-aligned walls, X then Y like the engine's slide; one input per step (4 ticks, 0.1 s of a fake
    clock). ``jitter`` adds +/- that much to the reported x on alternate steps (the live frame's sub-unit wobble). ``heading(pos)`` and
    ``done(pos)`` default to due east until ``goal_x``. Returns (steer, final true position)."""
    clock = [0.0]
    steer = Steer(name, clock=lambda: clock[0], **steer_kw)
    heading = heading or (lambda pos: (1.0, 0.0))
    done = done or (lambda pos: pos[0] >= goal_x)
    x, y = start
    inside = lambda px, py: any(x0 <= px < x1 and y0 <= py < y1 for x0, y0, x1, y1 in walls)
    for step in range(steps):
        if done((x, y)) or steer.exhausted:
            break
        seen = (x + (jitter if step % 2 else -jitter), y)
        move = steer.move(seen, heading(seen), tick=4 * step)
        if not inside(x + move['x'] * speed, y):
            x += move['x'] * speed
        if not inside(x, y + move['y'] * speed):
            y += move['y'] * speed
        clock[0] += 0.1
    return steer, (x, y)


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
        self.assertFalse(evidence['void_telemetry_ready'])                  # the mock answers no shim route: unknown, not 0
        self.assertIsNone(evidence['memory']['bounded_growth_acceptance'])
        self.assertIsNone(evidence['left_behind']['ok'])
        self.assertTrue(evidence['live_gate_reasons'])

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

    # R0.5: Gate D checks --------------------------------------------------------------------------------------------------
    def shim(self, player=0, resident=0, manager=11, generation=0, controlled=('p',), world='world-a'):
        return {'world_epoch': world, 'manager_id': manager, 'counter_generation': generation, 'controlled': list(controlled),
                'stats': self.stats(player, resident)}

    def test_window_stats_scope_feeds_void_delta(self):
        clean = void_from_window_stats(self.shim(0, 2), self.shim(0, 9), 'p')
        self.assertTrue(clean['known'])
        self.assertEqual(clean['player_void_hits'], 0)
        self.assertEqual(clean['resident_void_hits'], 7)
        self.assertIn('shim', clean['telemetry_source'])
        self.assertEqual(void_from_window_stats(self.shim(1), self.shim(4), 'p')['player_void_hits'], 3)
        for after in (self.shim(manager=12), self.shim(generation=1), self.shim(controlled=('p', 'q')), self.shim(controlled=()),
                      self.shim(world='world-b'), {'detail': 'Not Found'}, None):
            result = void_from_window_stats(self.shim(), after, 'p')
            self.assertFalse(result['known'], after)
            self.assertIsNone(result['player_void_hits'])
        self.assertFalse(void_from_window_stats(self.shim(manager=None), self.shim(manager=None), 'p')['known'])

    def mem(self, *rows):
        return [{'bytes': value, 'mark': mark} for mark, value in rows]

    def test_memory_bound_pass_fail_unknown(self):
        plateau = memory_bound(self.mem(('start', 100), (None, 180), ('half', 200), (None, 230), ('far', 240), ('end', 250)))
        self.assertIs(plateau['ok'], True)
        self.assertEqual(plateau['peak_minus_start_bytes'], 150)           # information only, no threshold
        self.assertEqual(plateau['sublinear_factor'], 0.5)
        self.assertIn('orchestrator ruling', plateau['sublinear_factor_source'])
        self.assertIs(memory_bound(self.mem(('start', 100), ('half', 200), ('far', 301), ('end', 301)))['ok'], False)
        for rows in ((('start', 100), ('half', 200)), (('start', 100), ('half', 200), ('far', 220)),      # no far / no end sample
                     (('start', None), ('half', 200), ('far', 250), ('end', 250)), ()):
            self.assertIsNone(memory_bound(self.mem(*rows))['ok'], rows)
        self.assertIsNone(memory_summary(self.mem(('start', 100), ('half', None), ('far', 120), ('end', 120)))['bounded_growth_acceptance'])

    def test_memory_bound_needs_clearly_sublinear_growth(self):
        # orchestrator ruling 1118: second-half growth <= 0.5 x first-half growth, and return-leg growth <= first-half growth
        linear = self.mem(('start', 1000), (None, 1500), ('half', 2000), (None, 2500), ('far', 3000), ('end', 3000))
        self.assertIs(memory_bound(linear)['ok'], False)                   # exactly linear growth fails
        self.assertIs(memory_summary(linear)['bounded_growth_acceptance'], False)
        self.assertIs(memory_bound(self.mem(('start', 1000), ('half', 2000), ('far', 2500), ('end', 2600)))['ok'], True)    # 0.5x boundary
        self.assertIs(memory_bound(self.mem(('start', 1000), ('half', 2000), ('far', 2501), ('end', 2501)))['ok'], False)
        self.assertIs(memory_bound(self.mem(('start', 1000), ('half', 2000), ('far', 2100), ('end', 3200)))['ok'], False)   # return leg grows
        self.assertIs(memory_bound(self.mem(('start', 1000), ('half', 2000), ('far', 2100), ('end', 3100)))['ok'], True)    # = first half
        self.assertIs(memory_bound(self.mem(('start', 1000), ('half', 1000), ('far', 1000), ('end', 1000)))['ok'], True)    # flat plateau

    def walk_sample(self, epoch, origin, **residents):
        return {'epoch': epoch, 'origin': list(origin),
                'residents': {rid: {'absolute': pos, 'space': 0, 'slot': None} for rid, pos in residents.items()}}

    def test_left_behind_absolute_positions_across_rebase(self):
        far = (-3000.0, 50.0)                                               # outside the [-1280, 1536) frame of every origin used
        samples = [self.walk_sample(1, (0, 0), r=far, p=(0, 0), near=(10.0, 10.0)),
                   self.walk_sample(1, (0, 0), r=far, p=(300, 0), near=(60.0, 10.0)),
                   self.walk_sample(2, (2, 0), r=far, p=(600, 0), near=(400.0, 10.0)),
                   self.walk_sample(3, (4, 0), r=(far[0] + 0.004, far[1]), p=(900, 0))]
        result = left_behind_stable(samples, 'p')
        self.assertIs(result['ok'], True)
        self.assertGreaterEqual(result['pairs_across_rebase'], 1)
        self.assertEqual(result['drift'], [])                               # 'near' moved but stayed in the frame: ignored
        samples[3]['residents']['r']['absolute'] = (far[0] + 3.0, far[1])
        drifted = left_behind_stable(samples, 'p')
        self.assertIs(drifted['ok'], False)
        self.assertEqual(drifted['drift'][0]['id'], 'r')
        same_epoch = [self.walk_sample(1, (0, 0), r=far, p=(0, 0)) for _ in range(4)]
        self.assertIsNone(left_behind_stable(same_epoch, 'p')['ok'])        # no re-base seen: unknown, never a pass
        self.assertIsNone(left_behind_stable([], 'p')['ok'])

    # R0.5 amend: steering, route lag, the real backend pid ----------------------------------------------------------------
    def test_pledge_follows_a_wall_wider_than_any_side_step(self):
        steer, (x, y) = simulate([(100.0, -300.0, 120.0, 300.0)], goal_x=400.0)   # 600 units tall: the old +/-1 wiggle stays stuck at x 90
        self.assertGreaterEqual(x, 400.0)
        self.assertEqual(len(steer.episodes), 1)
        episode = steer.episodes[0]
        self.assertEqual((episode['leg'], episode['outcome']), ('out', 'cleared'))
        self.assertEqual(episode['start_delta'], [90.0, 0.0])
        self.assertGreater(abs(episode['end_delta'][1]), 300.0)              # it went round the end of the wall
        self.assertGreaterEqual(episode['max_turn_degrees'], 45.0)
        self.assertEqual(steer.turn, 0.0)
        self.assertFalse(steer.exhausted)

    def test_pledge_backs_out_of_a_pocket_open_to_the_west(self):
        # run 3's shape: east, north and south closed, the walker came in from the west; the perpendicular search exhausted itself here
        pocket = [(100.0, -200.0, 120.0, 200.0), (-500.0, -220.0, 120.0, -200.0), (-500.0, 200.0, 120.0, 220.0)]
        steer, (x, y) = simulate(pocket, goal_x=400.0)
        self.assertGreaterEqual(x, 400.0)
        self.assertFalse(steer.exhausted)
        self.assertEqual(steer.episodes[-1]['outcome'], 'cleared')
        self.assertGreaterEqual(max(e['max_turn_degrees'] for e in steer.episodes), 135.0)   # it had to head back west to get out
        self.assertLessEqual(len(steer.episodes), steer.max_episodes)

    def test_pledge_closed_box_fails_cleanly_at_the_cap(self):
        box = [(-100.0, -100.0, 100.0, -80.0), (-100.0, 80.0, 100.0, 100.0), (-100.0, -80.0, -80.0, 80.0), (80.0, -80.0, 100.0, 80.0)]
        steer, _ = simulate(box, goal_x=400.0)
        self.assertTrue(steer.exhausted)
        self.assertEqual(steer.episodes[-1]['outcome'], 'dead_end')
        self.assertGreater(steer.episodes[-1]['max_turn_degrees'], steer.max_turn)
        self.assertEqual(steer.move((0.0, 0.0), (1.0, 0.0), tick=10**6), {'x': 0.0, 'y': 0.0})   # no more input once it gave up
        timed, _ = simulate(box, goal_x=400.0, max_turn=10**9, max_seconds=30.0)               # the time cap ends an endless follow too
        self.assertTrue(timed.exhausted)
        self.assertLessEqual(timed.episodes[-1]['duration_s'], 30.0 + 0.5)    # decided once per 16-tick window (0.4 s on the fake clock)
        capped, _ = simulate(box, goal_x=400.0, max_episodes=0)
        self.assertTrue(capped.exhausted and capped.episodes == [])

    def test_pledge_open_ground_walks_straight(self):
        steer, (x, y) = simulate([], goal_x=500.0)
        self.assertGreaterEqual(x, 500.0)
        self.assertEqual((y, steer.episodes), (0.0, []))

    def test_stuck_test_has_hysteresis_against_sub_unit_jitter(self):
        # run 4's failure: a corner, and a frame position that wobbles 0.6 units while the walker is pinned; a one-step test reads the wobble
        # as movement and never turns far enough (orchestrator ruling: stuck = net progress < 1 unit over the last N inputs)
        corner = [(100.0, -300.0, 120.0, 50.0), (-300.0, 50.0, 120.0, 70.0)]
        steer, (x, _) = simulate(corner, goal_x=400.0, jitter=0.3, max_seconds=60.0)
        self.assertGreaterEqual(x, 400.0)
        self.assertFalse(steer.exhausted)
        self.assertGreaterEqual(max(e['max_turn_degrees'] for e in steer.episodes), 135.0)
        fooled, (x, _) = simulate(corner, goal_x=400.0, jitter=0.3, max_seconds=60.0, stuck_window=0, steps=3000)
        self.assertLess(x, 400.0)                                            # no hysteresis: the wobble reads as movement, it stays pinned
        self.assertEqual(fooled.episodes, [])                                # ... without ever noticing it is stuck

    def test_breadcrumbs_keep_a_point_every_spacing_units(self):
        crumbs = Breadcrumbs(spacing=16.0)
        for i in range(101):
            crumbs.record((float(i), 0.0))
        self.assertEqual([p[0] for p in crumbs.points], [0.0, 16.0, 32.0, 48.0, 64.0, 80.0, 96.0])
        crumbs.record((96.0, 15.9))
        self.assertEqual(len(crumbs.points), 7)

    def outbound_crumbs(self, path, spacing=16.0):
        crumbs = Breadcrumbs(spacing=spacing)
        for (x0, y0), (x1, y1) in zip(path, path[1:]):
            n = int(max(abs(x1 - x0), abs(y1 - y0)))
            for k in range(n + 1):
                crumbs.record((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
        return crumbs

    def test_back_leg_retraces_the_breadcrumbs_around_a_wall(self):
        wall = [(100.0, -50000.0, 250.0, 150.0)]                             # the straight line home from (400, 0) runs into it
        crumbs = self.outbound_crumbs([(0, 0), (50, 0), (50, 200), (300, 200), (300, 0), (400, 0)])
        home = lambda pos: math.hypot(*pos) <= 32.0
        steer, end = simulate(wall, start=(400.0, 0.0), heading=crumbs.heading, done=home, name='back', max_seconds=120.0, steps=4000)
        self.assertTrue(home(end), end)
        self.assertFalse(steer.exhausted)
        self.assertLessEqual(crumbs.index, 3)                                # home is declared within 32 units: the last crumbs are optional
        direct, end = simulate(wall, start=(400.0, 0.0), heading=lambda p: (-p[0] / max(1e-9, math.hypot(*p)), -p[1] / max(1e-9, math.hypot(*p))),
                               done=home, name='back', max_seconds=30.0, steps=4000)
        self.assertFalse(home(end))                                          # aiming straight home is what run 4 did: no way through here

    def test_breadcrumbs_skip_ahead_and_end_at_the_start(self):
        crumbs = self.outbound_crumbs([(0, 0), (200, 0), (200, 100), (0, 100), (0, 2)])   # the outbound looped back near the start
        h = crumbs.heading((0.0, 4.0))                                       # standing close to an early crumb: jump there, do not replay the loop
        self.assertLessEqual(crumbs.index, 1)
        self.assertAlmostEqual(math.hypot(*h), 1.0)
        crumbs.index = 0
        self.assertEqual(crumbs.heading((0.0, -50.0)), (0.0, 1.0))           # the last target is the start itself

    def test_closing_void_read_happens_when_the_walk_fails(self):
        shim = self.shim(0, 0)
        frames = iter([dict(window_origin=[0, 0], window_epoch=1, agents=[dict(id='p', x=0, y=0)]),
                       dict(window_origin=[0, 0], window_epoch=1, agents=[dict(id='p', x=0, y=0, space=2)])])   # the walker leaves space 0

        def get(path, **kw):
            return self.reply(200, **(shim if path == '/_smoke/window_stats' else next(frames)))
        b = SimpleNamespace(proc=SimpleNamespace(pid=0), get=get,
                            post=lambda *a: self.reply(200, ok=True, target_id='p', world_epoch=1, possession_epoch=1))
        evidence = {}
        phase_long_walk(b, 5000, 60, evidence)
        self.assertIn('left overworld', evidence['error'])
        self.assertTrue(evidence['void_telemetry_ready'])
        self.assertEqual(evidence['void_hits'], 0)
        self.assertFalse(evidence['live_gate_complete'])
        self.assertEqual(evidence['path']['breadcrumbs'], {'count': 0, 'spacing': 16.0, 'reach': 12.0, 'index_reached': None, 'jumps': 0})
        self.assertIn('retraces the outbound breadcrumbs', evidence['path']['steering'])

    def route(self, cx, integrated, state='ready', coherent=True):
        return {'chunk': [cx, 0], 'route': [{'chunk_id': f'{cx}:0', 'state': state}], 'integrated': integrated, 'coherent_with_frame': coherent}

    def test_route_verdict_allows_a_one_sample_integration_lag(self):
        samples = [self.route(1, ['1:0']), self.route(2, ['1:0']), self.route(2, ['1:0', '2:0']), self.route(3, ['2:0']), self.route(3, ['3:0'])]
        result = route_verdict(samples)
        self.assertIs(result['ok'], True)
        self.assertEqual(result['lag_samples'], 2)
        self.assertEqual(result['max_consecutive_lag'], 1)
        self.assertEqual([lag['chunk'] for lag in result['lags']], [[2, 0], [3, 0]])
        skipped = [self.route(1, ['1:0']), self.route(2, ['1:0']), self.route(2, None), self.route(2, ['1:0'], coherent=False), self.route(2, ['2:0'])]
        self.assertIs(route_verdict(skipped)['ok'], True)                    # samples with no coherent set neither extend nor break a lag run

    def test_route_verdict_fails_on_two_consecutive_lags_or_a_chunk_not_ready(self):
        lagging = [self.route(1, ['1:0']), self.route(2, ['1:0']), self.route(2, ['1:0']), self.route(2, ['2:0'])]
        result = route_verdict(lagging)
        self.assertIs(result['ok'], False)
        self.assertEqual(result['max_consecutive_lag'], 2)
        self.assertIs(route_verdict([self.route(1, ['1:0']), self.route(2, ['2:0'], state='pending')])['ok'], False)
        self.assertIs(route_verdict([{'chunk': [1, 0], 'route': [], 'integrated': ['1:0'], 'coherent_with_frame': True}])['ok'], False)
        self.assertIs(route_verdict([])['ok'], False)

    def test_memory_samples_the_real_backend_interpreter(self):
        self.assertEqual(backend_pid({'pid': 4321}, 99), (4321, 'backend_interpreter'))
        for stats in ({}, None, {'pid': 'x'}, {'pid': True}):
            self.assertEqual(backend_pid(stats, 99), (99, 'launcher_fallback'))
        fallback = [{'bytes': v, 'mark': m, 'pid_kind': 'launcher_fallback'} for m, v in (('start', 10), ('half', 10), ('far', 10), ('end', 10))]
        self.assertIsNone(memory_bound(fallback)['ok'])                      # the venv launcher stub's RSS is never evidence
        real = [{**s, 'pid_kind': 'backend_interpreter'} for s in fallback]
        self.assertIs(memory_bound(real)['ok'], True)

    def test_live_gate_needs_void_memory_residents_and_inputs(self):
        good = {'measured_walk_pass': True, 'void_hits': 0, 'memory': {'bounded_growth_acceptance': True},
                'left_behind': {'ok': True}, 'input_counts': {'valid_input_rejected': 0, 'stale_window': 4}}
        self.assertEqual(live_gate(good), (True, []))
        for key, value in (('measured_walk_pass', False), ('void_hits', None), ('void_hits', 1), ('memory', {'bounded_growth_acceptance': None}),
                           ('left_behind', {'ok': None}), ('left_behind', {'ok': False}), ('input_counts', {'valid_input_rejected': 1})):
            ok, reasons = live_gate({**good, key: value})
            self.assertFalse(ok, key)
            self.assertTrue(reasons)


if __name__ == '__main__':
    unittest.main()
