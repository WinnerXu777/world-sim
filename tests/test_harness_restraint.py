"""1008 defend Phase 1 (1008_defend_phase1_gap.md, approved a806d0c): restraint (EDEN_RESTRAINT, column H_RESTRAINED = 30).

A restrained human's position is bit-identical while the counter runs, whoever tries to move it (instincts, the anchor driver, task movement), including
on an authored map where ``apply_motion_limits`` records where everyone ended the tick: the pin runs before it, so nothing walks the human back (that is
the ordering test, run in a subprocess on the real starter village). The counter counts down and the human moves again after it expires. A player's body
is never restrained. A re-base during the tick shifts the pinned position by the origin difference."""
import asyncio
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (isolated data root, imports map_test)
import genesis_config as cfg  # noqa: E402
from harness import restraint  # noqa: E402


class RestraintFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        patcher = mock.patch.dict(os.environ, {restraint.FLAG: "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = engine = backend.engine
        engine.reset_world()
        self.addCleanup(engine.reset_world)
        await backend.create_genesis(engine, map_name="render_test_village")
        h = engine.state.h_tensor
        self.slots = [int(s) for s in (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN).nonzero(as_tuple=False).flatten().tolist()]
        self.assertGreaterEqual(len(self.slots), 3)
        self.slot = self.slots[0]


class ApiTests(RestraintFixture):
    async def test_restrain_and_release(self):
        h = self.engine.state.h_tensor
        self.assertTrue(restraint.restrain(self.engine, self.slot, 12))
        self.assertEqual(float(h[self.slot, cfg.H_RESTRAINED]), 12.0)
        self.assertTrue(restraint.is_restrained(self.engine, self.slot))
        restraint.restrain(self.engine, self.slot, 5)
        self.assertEqual(float(h[self.slot, cfg.H_RESTRAINED]), 12.0, "the longer one wins")
        restraint.release(self.engine, self.slot)
        self.assertFalse(restraint.is_restrained(self.engine, self.slot))

    async def test_refusals(self):
        self.assertFalse(restraint.restrain(self.engine, self.slot, 0))
        self.assertFalse(restraint.restrain(self.engine, 999, 5))
        self.engine.state.h_tensor[self.slots[1], cfg.HP] = 0.0
        self.assertFalse(restraint.restrain(self.engine, self.slots[1], 5), "a dead human cannot be restrained")
        with mock.patch.dict(os.environ):
            os.environ.pop(restraint.FLAG)
            self.assertFalse(restraint.restrain(self.engine, self.slot, 5))
            self.assertIsNone(restraint.capture(self.engine))

    async def test_a_players_body_is_never_restrained(self):
        with mock.patch.object(self.engine.player_control, "describe_human_slot", side_effect=lambda s: {"slot": s} if s == self.slot else None):
            self.assertFalse(restraint.restrain(self.engine, self.slot, 5))
            self.engine.state.h_tensor[self.slot, cfg.H_RESTRAINED] = 9.0          # claimed while restrained: freed at the next capture
            self.assertIsNone(restraint.capture(self.engine))
            self.assertEqual(float(self.engine.state.h_tensor[self.slot, cfg.H_RESTRAINED]), 0.0)


class PinTests(RestraintFixture):
    async def test_the_position_is_bit_identical_while_restrained_and_the_counter_runs_out(self):
        h = self.engine.state.h_tensor
        for _ in range(5):
            self.engine.step()
        free = [s for s in self.slots if s != self.slot]
        restraint.restrain(self.engine, self.slot, 40)
        start = h[self.slot, [cfg.X, cfg.Y]].clone()
        others = {s: h[s, [cfg.X, cfg.Y]].clone() for s in free}
        for tick in range(40):
            self.engine.step()
            self.assertTrue(torch.equal(h[self.slot, [cfg.X, cfg.Y]], start), tick)
            self.assertEqual(float(h[self.slot, cfg.H_RESTRAINED]), float(39 - tick))
        self.assertTrue(any(not torch.equal(h[s, [cfg.X, cfg.Y]], others[s]) for s in free), "everybody else kept moving")
        moved = False
        for _ in range(60):
            self.engine.step()
            moved = moved or not torch.equal(h[self.slot, [cfg.X, cfg.Y]], start)
        self.assertTrue(moved, "free again after the counter ran out")

    async def test_the_other_needs_keep_running_while_restrained(self):
        h = self.engine.state.h_tensor
        restraint.restrain(self.engine, self.slot, 60)
        hunger = float(h[self.slot, cfg.HUNGER])
        for _ in range(60):
            self.engine.step()
        self.assertGreater(float(h[self.slot, cfg.HUNGER]), hunger)

    async def test_flag_off_nothing_is_pinned(self):
        h = self.engine.state.h_tensor
        h[self.slot, cfg.H_RESTRAINED] = 50.0
        with mock.patch.dict(os.environ):
            os.environ.pop(restraint.FLAG)
            start = h[self.slot, [cfg.X, cfg.Y]].clone()
            for _ in range(60):
                self.engine.step()
            self.assertEqual(float(h[self.slot, cfg.H_RESTRAINED]), 50.0, "the column is inert without the flag")
            self.assertFalse(torch.equal(h[self.slot, [cfg.X, cfg.Y]], start))

    async def test_a_rebase_during_the_tick_shifts_the_pinned_position(self):
        h = self.engine.state.h_tensor
        restraint.restrain(self.engine, self.slot, 5)
        manager = SimpleNamespace(frame=SimpleNamespace(origin=(2, 1)))
        self.engine._window = manager
        self.addCleanup(lambda: setattr(self.engine, "_window", None))
        captured = restraint.capture(self.engine)
        x, y = float(h[self.slot, cfg.X]), float(h[self.slot, cfg.Y])
        manager.frame.origin = (3, 1)                                  # the window moved one chunk east during the tick
        h[self.slot, cfg.X] += 17.0                                    # something moved the row
        restraint.pin(self.engine, captured)
        self.assertEqual((float(h[self.slot, cfg.X]), float(h[self.slot, cfg.Y])), (x - 256.0, y))

    async def test_a_replaced_row_is_left_alone(self):
        h = self.engine.state.h_tensor
        restraint.restrain(self.engine, self.slot, 5)
        captured = restraint.capture(self.engine)
        self.engine._human_uid_by_slot[self.slot] = "someone_else"
        h[self.slot, cfg.X] += 9.0
        moved = float(h[self.slot, cfg.X])
        self.assertEqual(restraint.pin(self.engine, captured), 0)
        self.assertEqual(float(h[self.slot, cfg.X]), moved)


async def finish(fixture):
    """What the runner does after a test: ``asyncTearDown``, then the cleanups in reverse order. ``fixture.doCleanups()`` cannot do this for an async case that no runner started
    (it has no asyncio runner, so every cleanup fails silently and the env patches, the window and the map contracts leak into the next module)."""
    await fixture.asyncTearDown()
    while fixture._cleanups:
        function, args, kwargs = fixture._cleanups.pop()
        result = function(*args, **kwargs)
        if asyncio.iscoroutine(result):
            await result


class DormancyPauseTests(unittest.IsolatedAsyncioTestCase):
    """A restrained human whose chunk is not integrated is dormant: its row is frozen whole, so the counter does not run down while the chunk is away."""

    async def test_restraint_pauses_while_dormant(self):
        from test_harness_dormancy import DormancyFixture
        from harness import dormancy

        class Fixture(DormancyFixture):
            async def runTest(self):
                pass
        fixture = Fixture()
        await fixture.asyncSetUp()
        self.addAsyncCleanup(finish, fixture)                          # the fixture is not run by the runner: tearing it down is ours
        with mock.patch.dict(os.environ, {restraint.FLAG: "1"}):
            engine = fixture.engine
            h = engine.state.h_tensor
            h[1, cfg.H_RESTRAINED] = 7.0                              # slot 1 stands in a chunk that is never integrated
            dormant_h, dormant_a = dormancy.refresh(engine)
            self.assertTrue(bool(dormant_h[1]))
            before = h[1].clone()
            for _ in range(5):                                         # the order Engine.step uses
                frozen = dormancy.freeze(engine, dormant_h, dormant_a)
                captured = restraint.capture(engine)
                h[1, cfg.X] += 3.0                                     # whatever moved it
                restraint.pin(engine, captured)
                dormancy.thaw(engine, frozen)
                self.assertTrue(torch.equal(h[1], before))
            self.assertEqual(float(h[1, cfg.H_RESTRAINED]), 7.0)


ORDERING_PROBE = r"""
import asyncio, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "at_the_beginning"))
os.environ["EDEN_RESTRAINT"] = "1"
from harness.headless import boot_engine, configure_environment
configure_environment()
async def main():
    backend, engine = await boot_engine(1008)
    import genesis_config as cfg
    from systems.roster.driver import runtime, anchor_driven_slots
    h = engine.state.h_tensor
    for _ in range(20):
        engine.step()
    slots = anchor_driven_slots(engine)
    before = {s: (float(h[s, cfg.X]), float(h[s, cfg.Y])) for s in slots}
    for _ in range(40):
        engine.step()
    travelled = {s: abs(float(h[s, cfg.X]) - before[s][0]) + abs(float(h[s, cfg.Y]) - before[s][1]) for s in slots}
    slot = max(slots, key=lambda s: travelled[s])                  # restrain the resident that is walking
    uid = engine._human_uid_by_slot[slot]
    from harness import restraint
    assert restraint.restrain(engine, slot, 120)
    start = (float(h[slot, cfg.X]), float(h[slot, cfg.Y]))
    series, finals = [], []
    for _ in range(120):
        engine.step()
        series.append((float(h[slot, cfg.X]), float(h[slot, cfg.Y])))
        finals.append(runtime(engine).final_positions.get(uid))
    after = []
    for _ in range(200):
        engine.step()
        after.append((float(h[slot, cfg.X]), float(h[slot, cfg.Y])))
    print(json.dumps({"start": start, "held": all(p == start for p in series), "finals_ok": all(f is None or tuple(f) == start for f in finals),
                      "moved_after": any(p != start for p in after), "moving_before": travelled[slot] > 0.5, "slots": len(slots)}))
asyncio.run(main())
"""


class OrderingTests(unittest.TestCase):
    def test_the_pin_runs_before_the_motion_limits_on_the_real_village(self):
        done = subprocess.run([sys.executable, "-c", ORDERING_PROBE, str(ROOT)], cwd=str(ROOT), capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr)[-1500:])
        result = json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])
        self.assertGreaterEqual(result["slots"], 2)
        self.assertTrue(result["held"], "bit-identical for 120 ticks with the anchor driver trying to walk it")
        self.assertTrue(result["finals_ok"], "apply_motion_limits recorded the pinned position (no walk-back jitter)")
        self.assertTrue(result["moving_before"], "the probe restrained a resident that was walking")
        self.assertTrue(result["moved_after"], "the anchor driver walks it again once it is free")


if __name__ == "__main__":
    unittest.main()
