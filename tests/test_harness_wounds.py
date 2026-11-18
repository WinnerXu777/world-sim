"""1008 Part 2.A2 (1008_instincts_wiring_gap.md step 3): EDEN_WOUNDS, the bleed that follows a blow.

Pure closed form against tick-by-tick, hit detection from the HP column, the cadence and the dormant catch-up, treatment, indoor clotting, the roster's needs scale, the
resident-record round trip and the registration."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import engine_hooks, wounds as W  # noqa: E402


class PureTests(unittest.TestCase):
    def test_the_closed_form_equals_tick_by_tick(self):
        bleed, lost = 0.9, 0.0
        q = W.decay(W.HALF_LIFE)
        for _ in range(137):
            lost += bleed
            bleed *= q
        got_lost, got_bleed = W.advance(0.9, 137)
        self.assertAlmostEqual(got_lost, lost, places=9)
        self.assertAlmostEqual(got_bleed, bleed, places=9)

    def test_advancing_in_two_windows_equals_one(self):
        a, b = W.advance(1.0, 60)
        c, d = W.advance(b, 90)
        e, f = W.advance(1.0, 150)
        self.assertAlmostEqual(a + c, e, places=9)
        self.assertAlmostEqual(d, f, places=9)

    def test_the_bleed_halves_every_half_life_and_zero_stays_zero(self):
        self.assertAlmostEqual(W.advance(1.0, W.HALF_LIFE)[1], 0.5, places=9)
        self.assertEqual(W.advance(0.0, 500), (0.0, 0.0))
        self.assertEqual(W.advance(1.0, 0), (0.0, 1.0))


class WoundFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_WOUNDS": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        engine = self.engine
        self.addCleanup(lambda: [engine.__dict__.pop(k, None) for k in ("_wounds", "_wound_hp", "_dormant_h")])
        self.addCleanup(setattr, engine, "resident_store", engine.resident_store)
        self.events = []
        self.addCleanup(setattr, engine, "_queue_event", engine._queue_event)
        engine._queue_event = lambda kind, uid, slot, **extra: self.events.append((kind, uid, slot, extra))
        self.uids = {}
        engine.tick = 1000                                          # a multiple of the cadence

    def resident(self, slot, hp=100.0, indoors=False):
        self.place_human(slot, 500.0 + slot, 500.0)
        h = self.engine.state.h_tensor
        h[slot, cfg.HP] = hp
        h[slot, cfg.H_SHELTER] = 1.0 if indoors else 0.0
        uid = f"h{slot}"
        self.engine._human_uid_by_slot[slot] = uid
        self.uids[slot] = uid
        self.addCleanup(self.engine._human_uid_by_slot.__setitem__, slot, None)
        return uid

    def set_hp(self, slot, hp):
        self.engine.state.h_tensor[slot, cfg.HP] = hp

    def quiet_hp(self, slot, hp):
        """Set HP without it counting as a hit on the next tick."""
        self.set_hp(slot, hp)
        self.engine._wound_hp = self.engine.state.h_tensor[:, cfg.HP].clone()

    def hp(self, slot):
        return float(self.engine.state.h_tensor[slot, cfg.HP])

    def tick(self, n=1):
        for _ in range(n):
            self.engine.tick += 1
            W.step(self.engine)


class DetectionTests(WoundFixture):
    async def test_a_big_drop_is_a_hit_and_a_small_one_is_not(self):
        self.resident(0)
        W.step(self.engine)                                         # takes the baseline
        self.set_hp(0, 98.0)
        self.tick()
        self.assertEqual(W.bleed_of(self.engine, "h0"), 0.0, "2 HP is a scratch of the vitals, not a hit")
        self.set_hp(0, 83.0)                                        # 15 HP bite
        self.tick()
        self.assertAlmostEqual(W.bleed_of(self.engine, "h0"), 15.0 * W.BLEED_PER_HP)
        (kind, uid, slot, extra), = self.events
        self.assertEqual((kind, uid, slot), ("human_wounded", "h0", 0))
        self.assertEqual(extra["damage"], 15.0)

    async def test_healing_is_not_a_hit_and_a_second_blow_adds_to_the_bleed(self):
        self.resident(0)
        W.step(self.engine)
        self.set_hp(0, 60.0)
        self.tick()
        first = W.bleed_of(self.engine, "h0")
        self.set_hp(0, 90.0)
        self.tick()
        self.assertEqual(W.bleed_of(self.engine, "h0"), first, "a rise changes nothing")
        self.set_hp(0, 70.0)
        self.tick()
        self.assertAlmostEqual(W.bleed_of(self.engine, "h0"), first + 20.0 * W.BLEED_PER_HP, places=4)

    async def test_a_dormant_row_a_dead_row_and_a_row_without_an_id_are_not_wounded(self):
        for slot in (0, 1, 2):
            self.resident(slot)
        self.engine._human_uid_by_slot[2] = None
        W.step(self.engine)
        dormant = torch.zeros(self.engine.state.h_tensor.shape[0], dtype=torch.bool)
        dormant[0] = True
        self.engine._dormant_h = dormant
        for slot, hp in ((0, 50.0), (1, 0.0), (2, 50.0)):
            self.set_hp(slot, hp)
        self.tick()
        self.assertEqual(self.events, [])
        self.assertEqual(W._records(self.engine), {})

    async def test_the_callbacks_see_every_hit(self):
        seen = []
        callback = lambda engine, slot, uid, damage: seen.append((slot, uid, damage))  # noqa: E731
        W.on_hit(callback)
        self.addCleanup(W.off_hit, callback)
        self.resident(0)
        W.step(self.engine)
        self.set_hp(0, 80.0)
        self.tick()
        self.assertEqual(seen, [(0, "h0", 20.0)])


class CourseTests(WoundFixture):
    def wound(self, slot=0, damage=20.0):
        uid = self.resident(slot)
        W.step(self.engine)
        self.set_hp(slot, 100.0 - damage)
        self.engine.tick += 1
        W.step(self.engine)
        return uid

    async def test_the_cadence_bills_the_bleed_in_closed_form_and_raises_infection(self):
        uid = self.wound()
        start = self.engine.tick
        b0 = W.bleed_of(self.engine, uid)
        self.tick(19)                                               # ticks 1001..1020: the advance happens at 1020 for 19 elapsed
        self.assertEqual(self.engine.tick, start + 19)
        want_lost, want_bleed = W.advance(b0, 19)
        self.assertAlmostEqual(80.0 - self.hp(0), want_lost, places=3)
        self.assertAlmostEqual(W.bleed_of(self.engine, uid), want_bleed, places=6)
        self.assertGreater(float(self.engine.state.h_tensor[0, cfg.H_INFECTION]), 0.0)

    async def test_the_total_cost_is_the_closed_form_up_to_the_last_advance(self):
        uid = self.wound()
        hit_tick, b0 = W.record_of(self.engine, uid)["tick"], W.bleed_of(self.engine, uid)
        self.tick(200)
        last = self.engine.tick - (self.engine.tick % W.CADENCE)
        self.assertAlmostEqual(80.0 - self.hp(0), W.advance(b0, last - hit_tick)[0], places=3)

    async def test_a_dormant_resident_catches_up_on_waking(self):
        uid = self.wound()
        dormant = torch.zeros(self.engine.state.h_tensor.shape[0], dtype=torch.bool)
        dormant[0] = True
        self.engine._dormant_h = dormant
        record = W.record_of(self.engine, uid)
        since, b0 = record["tick"], record["bleed"]
        self.engine.tick += 400
        W.step(self.engine)
        self.assertEqual(self.hp(0), 80.0, "no HP is taken while the row sleeps")
        self.assertEqual(record["tick"], since)
        self.engine._dormant_h = None
        self.engine.tick += 20 - (self.engine.tick % 20)
        W.step(self.engine)
        elapsed = self.engine.tick - since
        self.assertAlmostEqual(80.0 - self.hp(0), W.advance(b0, elapsed)[0], places=3)

    async def test_treatment_stops_the_bleed_and_an_untreated_deep_wound_kills(self):
        treated, untreated = self.wound(0, 25.0), self.wound(1, 25.0)
        self.quiet_hp(0, 40.0)
        self.quiet_hp(1, 40.0)                                      # same wound state, both low
        W._records(self.engine)[untreated]["bleed"] = 2.5
        self.assertTrue(W.treat(self.engine, treated))
        self.assertFalse(W.treat(self.engine, "nobody"))
        self.tick(200)
        self.assertEqual(self.hp(0), 40.0, "the treated resident loses nothing more")
        self.assertEqual(W.bleed_of(self.engine, treated), 0.0)
        self.assertLessEqual(self.hp(1), 0.0, "2.5 HP a tick, no healing in this room: dead")
        self.assertEqual(W.bleed_of(self.engine, untreated), 0.0, "a dead resident's wound is dropped")

    async def test_indoors_a_wound_clots_faster(self):
        out, inside = self.wound(0), None
        uid2 = self.resident(1, indoors=True)
        W.step(self.engine)
        self.set_hp(1, 80.0)
        self.engine.tick += 1
        W.step(self.engine)
        self.tick(100)
        self.assertLess(80.0 - self.hp(1), 80.0 - self.hp(0))
        self.assertLess(W.bleed_of(self.engine, uid2), W.bleed_of(self.engine, out))

    async def test_the_rosters_needs_scale_slows_the_course(self):
        a, b = self.wound(0), self.wound(1)
        starts = {u: (W.record_of(self.engine, u)["tick"], W.bleed_of(self.engine, u)) for u in (a, b)}
        scale = torch.ones(self.engine.state.h_tensor.shape[0])
        scale[1] = 0.1
        with mock.patch("systems.roster.driver.needs_scale_vector", return_value=scale):
            self.tick(100)
        last = self.engine.tick - (self.engine.tick % W.CADENCE)
        for slot, uid, factor in ((0, a, 1.0), (1, b, 0.1)):
            tick0, b0 = starts[uid]
            self.assertAlmostEqual(80.0 - self.hp(slot), W.advance(b0, (last - tick0) * factor)[0], places=3)
        self.assertGreater(W.bleed_of(self.engine, b), W.bleed_of(self.engine, a))


class RecordTests(WoundFixture):
    async def test_the_wound_is_mirrored_into_the_resident_record_and_read_back(self):
        saved = {}
        dirty = []

        class Store:
            def get(self, uid):
                return saved.setdefault(uid, {})

            def _mark_dirty(self, uid):
                dirty.append(uid)

        self.engine.resident_store = Store()
        uid = self.resident(0)
        W.step(self.engine)
        self.set_hp(0, 70.0)
        self.tick()
        self.assertAlmostEqual(saved[uid]["wound"]["bleed"], 30.0 * W.BLEED_PER_HP, places=3)
        self.assertIn(uid, dirty)
        self.engine.__dict__.pop("_wounds")                         # a new process: only the resident file remains
        self.assertAlmostEqual(W.bleed_of(self.engine, uid), 30.0 * W.BLEED_PER_HP, places=3)
        W.treat(self.engine, uid)
        self.assertNotIn("wound", saved[uid])


class RegistrationTests(WoundFixture):
    async def test_the_post_step_hook_is_installed_only_with_the_flag(self):
        from simulation.dispatch import DISPATCH
        self.addCleanup(engine_hooks.uninstall, DISPATCH)
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_WOUNDS")
            engine_hooks.uninstall(DISPATCH)
            engine_hooks.install(DISPATCH)
            self.assertNotIn("harness_wounds", {n for n, _ in DISPATCH.post_step_hooks})
        engine_hooks.uninstall(DISPATCH)
        engine_hooks.install(DISPATCH)
        self.assertIn("harness_wounds", {n for n, _ in DISPATCH.post_step_hooks})


if __name__ == "__main__":
    unittest.main()
