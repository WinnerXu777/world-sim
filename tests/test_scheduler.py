import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
from simulation.scheduler import FixedStepScheduler


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay
        await asyncio.sleep(0)


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_work_is_inside_fifty_ms_budget_not_added_to_it(self):
        clock = FakeClock()
        scheduler = FixedStepScheduler(clock=clock, sleep=clock.sleep)
        starts = []
        def step():
            starts.append(clock())
            clock.now += .012
        await scheduler.run(step, lambda: len(starts) < 5)
        for actual, expected in zip(starts, [0, .05, .10, .15, .20]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(scheduler.status()["work_ms"]["p95"], 12)
        self.assertEqual(scheduler.overruns, 0)

    async def test_overload_drops_wall_deadlines_and_yields_without_skipping_sim_steps(self):
        clock = FakeClock()
        scheduler = FixedStepScheduler(clock=clock, sleep=clock.sleep)
        calls = []
        def step():
            calls.append(clock())
            clock.now += .2
        await scheduler.run(step, lambda: len(calls) < 4)
        self.assertEqual(scheduler.steps, 4)
        self.assertEqual(scheduler.overruns, 4)
        self.assertGreater(scheduler.dropped_deadlines, 0)
        self.assertEqual(sum(delay == 0 for delay in clock.sleeps), 4)
        self.assertTrue(any(delay > 0 for delay in clock.sleeps))

    async def test_pause_keeps_event_loop_available_and_resume_has_no_catchup(self):
        clock = FakeClock()
        scheduler = FixedStepScheduler(clock=clock, sleep=clock.sleep)
        scheduler.set_time_scale(0)
        starts = []
        async def resume():
            for _ in range(10):
                await asyncio.sleep(0)
            self.assertEqual(starts, [])
            scheduler.set_time_scale(1)
        task = asyncio.create_task(resume())
        await scheduler.run(lambda: starts.append(clock()), lambda: len(starts) < 3)
        await task
        self.assertAlmostEqual(starts[1] - starts[0], .05)
        self.assertEqual(scheduler.dropped_deadlines, 0)

    async def test_speed_change_uses_full_steps_at_new_cadence(self):
        clock = FakeClock()
        scheduler = FixedStepScheduler(clock=clock, sleep=clock.sleep)
        scheduler.set_time_scale(2)
        starts = []
        await scheduler.run(lambda: starts.append(clock()), lambda: len(starts) < 3)
        self.assertEqual(starts, [0, .025, .05])

    async def test_cancel_during_pause_exits(self):
        scheduler = FixedStepScheduler()
        scheduler.set_time_scale(0)
        task = asyncio.create_task(scheduler.run(lambda: self.fail("Paused step executed"), lambda: True))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    def test_invalid_settings_rejected(self):
        for rate in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                FixedStepScheduler(rate)
        with self.assertRaises(ValueError):
            FixedStepScheduler().set_time_scale(100)


if __name__ == "__main__":
    unittest.main()
