"""1008 interim dormancy (EDEN_WINDOW_DORMANCY, design 1008_dormancy_gap.md): the predicate, the freeze net, the wake catch-up, the boot refusal."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import dormancy, engine_hooks as eh, spaces  # noqa: E402
from simulation.dispatch import Dispatcher  # noqa: E402

SIZE = 256.0


class DormancyFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_WINDOW_DORMANCY": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        grace = mock.patch.object(dormancy, "GRACE_TICKS", 0)
        grace.start()
        self.addCleanup(grace.stop)
        self.place_human(0, 520.0, 520.0)                              # the player's surroundings, integrated
        self.place_human(1, 3000.0, 500.0)                             # far beyond the frame: its chunk is never integrated
        for slot in (0, 1):
            self.engine._human_uid_by_slot[slot] = f"h_t{slot}"
        self.engine.player_control.sessions_by_controller["p"] = {"target_kind": "human", "slot": 0, "controller_id": "p"}   # the window follows slot 0
        self.addCleanup(self.engine.player_control.sessions_by_controller.pop, "p", None)
        self.run_ticks(30)
        self.addCleanup(lambda: setattr(self.engine, "_dormant_h", None))
        self.addCleanup(lambda: setattr(self.engine, "_dormant_a", None))
        self.engine.__dict__.pop("_dormant_since", None)
        self.engine.__dict__.pop("_dormancy_log", None)
        self.engine.__dict__.pop("_outside_since", None)


class PredicateTests(DormancyFixture):
    async def test_only_the_resident_outside_the_integrated_chunks_is_dormant(self):
        dormant_h, dormant_a = dormancy.refresh(self.engine)
        self.assertFalse(bool(dormant_h[0]))
        self.assertTrue(bool(dormant_h[1]))
        self.assertEqual(int(dormant_h.sum()), 1)
        self.assertEqual(int(dormant_a.sum()), 0)
        self.assertTrue(dormancy.is_dormant(self.engine, 1))
        self.assertFalse(dormancy.is_dormant(self.engine, 0))
        self.assertEqual([entry[1:] for entry in self.engine._dormancy_log], [("sleep", "h_t1")])

    async def test_an_interior_resident_is_never_dormant(self):
        self.engine.state.h_tensor[1, cfg.H_SPACE] = 1.0
        dormant_h, _ = dormancy.refresh(self.engine)
        self.assertEqual(int(dormant_h.sum()), 0)

    async def test_flag_off_or_no_window_gives_nothing(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_WINDOW_DORMANCY")
            self.assertEqual(dormancy.refresh(self.engine), (None, None))
            self.assertFalse(dormancy.is_dormant(self.engine, 1))
        self.engine._window = None
        self.assertEqual(dormancy.refresh(self.engine), (None, None))


    async def test_a_players_own_human_is_never_dormant(self):
        self.engine.state.h_tensor[0, cfg.X] = 3000.0                  # the controlled human far out (a re-base would follow it in a real tick)
        self.engine.player_control.sessions_by_controller["p"]["slot"] = 0
        dormant_h, _ = dormancy.refresh(self.engine)
        self.assertFalse(bool(dormant_h[0]))

    async def test_the_grace_period_delays_dormancy(self):
        with mock.patch.object(dormancy, "GRACE_TICKS", 40):
            dormant_h, _ = dormancy.refresh(self.engine)
            self.assertEqual(int(dormant_h.sum()), 0, "just seen outside: not yet")
            self.engine.tick += 39
            self.assertEqual(int(dormancy.refresh(self.engine)[0].sum()), 0)
            self.engine.tick += 1
            self.assertEqual(int(dormancy.refresh(self.engine)[0].sum()), 1)
            self.engine.state.h_tensor[1, cfg.X] = 530.0               # back inside: the clock resets
            self.run_ticks(2)
            dormancy.refresh(self.engine)
            self.assertNotIn("h_t1", self.engine._outside_since)


class FreezeTests(DormancyFixture):
    async def test_a_rebase_during_the_tick_does_not_undo_the_shift(self):
        """The runaway found live: the window hook re-bases mid-step, thaw wrote the old-frame row back, the next tick re-based again."""
        h = self.engine.state.h_tensor
        dormant_h, dormant_a = dormancy.refresh(self.engine)
        frozen = dormancy.freeze(self.engine, dormant_h, dormant_a)
        absolute_before = self.manager.frame.origin[0] * SIZE + float(h[1, cfg.X])
        self.manager.rebase((1, 0))                                   # shifts every space-0 row, the dormant one included
        dormancy.thaw(self.engine, frozen)
        self.assertAlmostEqual(self.manager.frame.origin[0] * SIZE + float(h[1, cfg.X]), absolute_before, places=3)

    async def test_a_dormant_row_is_bit_identical_whatever_touches_it(self):
        h = self.engine.state.h_tensor
        dormant_h, dormant_a = dormancy.refresh(self.engine)
        before = h[1].clone()
        frozen = dormancy.freeze(self.engine, dormant_h, dormant_a)
        h[1, cfg.X] += 55.0                                           # an anchor mover step
        h[1, cfg.HUNGER] += 9.0                                       # a need tick
        h[1, cfg.HP] -= 3.0
        dormancy.thaw(self.engine, frozen)
        self.assertTrue(torch.equal(h[1], before))

    async def test_a_removed_row_is_not_resurrected(self):
        h = self.engine.state.h_tensor
        dormant_h, dormant_a = dormancy.refresh(self.engine)
        frozen = dormancy.freeze(self.engine, dormant_h, dormant_a)
        h[1, cfg.TYPE] = 0.0                                          # died / removed by a god command
        dormancy.thaw(self.engine, frozen)
        self.assertEqual(float(h[1, cfg.TYPE]), 0.0)

    async def test_the_live_row_is_untouched_by_freeze_and_thaw(self):
        h = self.engine.state.h_tensor
        dormant_h, dormant_a = dormancy.refresh(self.engine)
        frozen = dormancy.freeze(self.engine, dormant_h, dormant_a)
        h[0, cfg.HUNGER] += 4.0
        dormancy.thaw(self.engine, frozen)
        self.assertEqual(float(h[0, cfg.HUNGER]), 4.0)

    async def test_nothing_dormant_means_no_copy(self):
        self.engine.state.h_tensor[1, cfg.X] = 530.0
        self.run_ticks(3)
        dormant_h, dormant_a = dormancy.refresh(self.engine)
        self.assertIsNone(dormancy.freeze(self.engine, dormant_h, dormant_a))


class WakeTests(DormancyFixture):
    async def test_wake_when_the_chunk_is_integrated_again(self):
        h = self.engine.state.h_tensor
        dormancy.refresh(self.engine)
        self.engine.tick += 4000
        h[1, cfg.X], h[1, cfg.Y] = 530.0, 530.0                       # the window comes back (the row's chunk is integrated)
        dormancy.refresh(self.engine)
        self.assertEqual([entry[1:] for entry in self.engine._dormancy_log], [("sleep", "h_t1"), ("wake", "h_t1")])
        self.assertAlmostEqual(float(h[1, cfg.HUNGER]), min(cfg.HUNGER_TICK_RATE * 4000, dormancy.CATCH_UP["hunger_cap"]), places=3)

    async def test_catch_up_numbers_and_caps(self):
        h = self.engine.state.h_tensor
        h[1, cfg.HUNGER], h[1, cfg.THIRST], h[1, cfg.H_AGE], h[1, cfg.H_STAMINA], h[1, cfg.THREAT] = 10.0, 5.0, 30.0, 20.0, 40.0
        result = dormancy.wake(self.engine, 1, 100)
        self.assertAlmostEqual(result["hunger"], 10.0 + cfg.HUNGER_TICK_RATE * 100, places=4)
        self.assertAlmostEqual(result["thirst"], 5.0 + cfg.THIRST_TICK_RATE * 100, places=4)
        self.assertAlmostEqual(result["age"], 30.0 + 100.0 / cfg.TICKS_PER_YEAR, places=4)
        self.assertEqual(float(h[1, cfg.H_STAMINA]), 100.0)
        self.assertEqual(float(h[1, cfg.THREAT]), 0.0)
        result = dormancy.wake(self.engine, 1, 10 ** 7)
        self.assertEqual(result["hunger"], dormancy.CATCH_UP["hunger_cap"])
        self.assertEqual(result["thirst"], dormancy.CATCH_UP["thirst_cap"])
        self.assertLess(dormancy.CATCH_UP["hunger_cap"], 90.0, "under the starvation threshold: nobody dies of the absence")

    async def test_a_resident_already_past_the_cap_is_not_lowered(self):
        h = self.engine.state.h_tensor
        h[1, cfg.HUNGER] = 95.0
        dormancy.wake(self.engine, 1, 5000)
        self.assertEqual(float(h[1, cfg.HUNGER]), 95.0)


class SaveTests(DormancyFixture):
    async def test_dormant_since_round_trips_through_the_window_section(self):
        dormancy.refresh(self.engine)
        state = self.manager.snapshot()
        self.assertEqual(state["dormant_since"], {"h_t1": int(self.engine.tick)})
        self.engine._dormant_since = {}
        self.manager.load(state)
        self.assertEqual(self.engine._dormant_since, {"h_t1": int(self.engine.tick)})

    async def test_nothing_dormant_leaves_the_section_unchanged(self):
        self.engine.state.h_tensor[1, cfg.X] = 530.0
        self.run_ticks(3)
        dormancy.refresh(self.engine)
        self.assertNotIn("dormant_since", self.manager.snapshot())


class AnchorDriverTests(unittest.TestCase):
    def test_the_anchor_mover_skips_dormant_slots(self):
        from systems.roster import driver
        engine = mock.Mock()
        with mock.patch.object(driver, "roster_slots", return_value=[3, 5, 7]):
            engine._dormant_h = None
            self.assertEqual(driver.anchor_driven_slots(engine), [3, 5, 7])
            engine._dormant_h = torch.zeros(10, dtype=torch.bool)
            engine._dormant_h[5] = True
            self.assertEqual(driver.anchor_driven_slots(engine), [3, 7])


class BootTests(unittest.TestCase):
    def test_dormancy_without_the_window_refuses_to_boot(self):
        with mock.patch.dict(os.environ, {"EDEN_WINDOW_DORMANCY": "1"}):
            os.environ.pop("EDEN_WINDOW", None)
            with self.assertRaises(spaces.SpaceConfigError) as caught:
                eh.install(Dispatcher())
            self.assertIn("EDEN_WINDOW=1", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
