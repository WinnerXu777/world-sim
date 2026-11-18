"""1008 scaling: EDEN_ENSURE_ONCE (default off). ``ResidentAgentStore.ensure_resident`` is called three times per resident per tick (the id sync, the escalation
sweep, the reasoning-review queue) and each call re-ran the whole behaviour pass (personality, occupation, schedule, crafting, construction, tasks, pressures,
goals, plans). With the flag ``1`` only the first call of a tick runs it; the repeats refresh the snapshot (it reads the tensors, which changed between the
calls) and the pressures (they depend on the snapshot) and nothing else. The proof that this is pure is the ``check`` mode: it runs everything as before and
records every section other than snapshot/runtime/pressures that a repeat call changed. These tests run ``check`` over real roster worlds with both drivers,
show the recorder does catch a change, and show the golden trace is bit-identical with the flag on."""
import copy
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
ROOT = Path(__file__).resolve().parents[1]

from test_startup_preservation import backend  # noqa: E402,F401  (isolated data root, imports map_test)
import genesis_config as cfg  # noqa: E402
from runtime import resident_store as rs  # noqa: E402


class StoreFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        patcher = mock.patch.dict(os.environ, {rs.ENSURE_ONCE_ENV: "check"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = engine = backend.engine
        engine.reset_world()
        self.addCleanup(engine.reset_world)
        await backend.create_genesis(engine, map_name="render_test_village")
        self.store = engine.resident_store
        self.store.ensure_once_violations.clear()
        h = engine.state.h_tensor
        self.slots = [int(s) for s in (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN).nonzero(as_tuple=False).flatten().tolist()]
        self.assertGreaterEqual(len(self.slots), 2)

    def call(self, slot, tick):
        uid = self.engine._human_uid_by_slot[slot]
        return self.store.ensure_resident(uid, slot, self.engine.state.h_tensor, tick)


class PurityTests(StoreFixture):
    async def test_a_world_running_in_check_mode_has_no_violations(self):
        for _ in range(240):
            self.engine.step()
        self.assertEqual(self.store.ensure_once_violations, [])
        self.assertGreater(len(self.store._behavior_seen), 0, "the check mode was really active")

    async def test_the_recorder_catches_a_section_a_repeat_call_changes(self):
        slot = self.slots[0]
        tick = int(self.engine.tick) + 5
        resident = self.call(slot, tick)
        resident["tasks"] = []                                   # something the full pass would rebuild
        resident["task_state"] = {}
        self.call(slot, tick)
        self.assertTrue(any("tasks" in moved or "task_state" in moved for _, _, moved in self.store.ensure_once_violations), self.store.ensure_once_violations)

    async def test_a_new_tick_is_a_full_pass_again(self):
        slot = self.slots[0]
        tick = int(self.engine.tick) + 5
        self.call(slot, tick)
        resident = self.call(slot, tick)
        resident["tasks"] = []
        self.store.ensure_once_violations.clear()
        self.call(slot, tick + 1)
        self.assertEqual(self.store.ensure_once_violations, [], "the first call of a tick is never a repeat")


class SkipTests(StoreFixture):
    async def test_the_skip_refreshes_snapshot_and_pressures_and_leaves_the_rest(self):
        slot = self.slots[0]
        tick = int(self.engine.tick) + 5
        with mock.patch.dict(os.environ, {rs.ENSURE_ONCE_ENV: "1"}):
            first = self.call(slot, tick)
            before = copy.deepcopy(first)
            self.engine.state.h_tensor[slot, cfg.THIRST] += 20.0
            self.engine.state.h_tensor[slot, cfg.X] += 3.0
            with mock.patch.object(self.store, "_ensure_behavior_state", side_effect=AssertionError("the repeat call must not run the behaviour pass")):
                second = self.call(slot, tick)
        self.assertEqual(second["snapshot"]["thirst"], round(float(self.engine.state.h_tensor[slot, cfg.THIRST]), 3))
        self.assertNotEqual(second["snapshot"]["thirst"], before["snapshot"]["thirst"])
        for key in before:
            if key not in rs.ENSURE_ONCE_EXEMPT:
                self.assertEqual(second[key], before[key], key)

    async def test_flag_off_every_call_runs_the_full_pass(self):
        slot = self.slots[0]
        self.store._behavior_seen.clear()
        with mock.patch.dict(os.environ):
            os.environ.pop(rs.ENSURE_ONCE_ENV)
            with mock.patch.object(self.store, "_ensure_behavior_state", wraps=self.store._ensure_behavior_state) as spy:
                self.call(slot, 77)
                self.call(slot, 77)
                self.call(slot, 77)
        self.assertEqual(spy.call_count, 3)
        self.assertEqual(self.store._behavior_seen, {})


class GoldenTests(unittest.TestCase):
    def test_the_default_golden_is_bit_identical_with_the_flag_on(self):
        env = {**os.environ, rs.ENSURE_ONCE_ENV: "1"}
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "golden_trace.py"), "--check", "--strict"], cwd=str(ROOT), env=env,
                              capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr)[-1500:])
        self.assertIn("no drift", done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
