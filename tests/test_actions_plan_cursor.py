"""PlanCursors: a Tier 3 plan runs one step at a time and the next step waits for the previous step's task (1008_actions.md section 10.9)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "at_the_beginning"))

from test_actions_runner import Scene, setrow  # noqa: E402
from systems.actions import PlanCursors  # noqa: E402

REST = {"op": "rest", "args": {}}
WORK = {"op": "go_to_work", "args": {}}


def hungry_tired_scene(**kw):
    scene = Scene(**kw)
    setrow(scene.world, "h_a", hunger=80, stamina=40)
    return scene


def ran(scene, verb):
    return [e for e in scene.audit.entries if e["verb"] == verb and not e["dry_run"] and e["ok"]]


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.scene = hungry_tired_scene()
        self.cursors = PlanCursors(self.scene.runner, timeout_ticks=10)

    def tasks(self):
        return list(self.scene.records["h_a"].get("tasks", []))

    def test_the_next_step_waits_for_the_previous_task(self):
        self.cursors.start("h_a", [REST, WORK], confidence=0.9, tick=0, epoch="E")
        self.assertEqual(self.cursors.advance(1, "E"), [])
        self.assertEqual((len(ran(self.scene, "rest")), len(ran(self.scene, "go_to_work"))), (1, 0))
        self.assertEqual(len(self.tasks()), 1)
        for tick in (2, 3, 4):
            self.assertEqual(self.cursors.advance(tick, "E"), [])                       # the task is still queued: nothing new runs
        self.assertEqual(len(ran(self.scene, "go_to_work")), 0)
        self.assertEqual(self.cursors.status()["active"]["h_a"]["index"], 1)
        self.scene.ops.finish_task("h_a", self.tasks()[0]["id"])
        self.assertEqual(self.cursors.advance(5, "E"), [])                              # task done: step 2 starts (and queues its own task)
        self.assertEqual(len(ran(self.scene, "go_to_work")), 1)
        self.scene.ops.finish_task("h_a", self.tasks()[0]["id"])
        done = self.cursors.advance(6, "E")
        self.assertEqual([(e["actor"], e["status"], e["completed"]) for e in done], [("h_a", "done", 2)])
        self.assertEqual(self.cursors.active(), [])

    def test_instant_steps_chain_in_one_advance(self):
        eat = {"op": "eat", "args": {"item": "rations"}}
        self.cursors.start("h_a", [eat, eat], confidence=0.9, tick=0, epoch="E")
        done = self.cursors.advance(1, "E")
        self.assertEqual([(e["status"], e["completed"]) for e in done], [("done", 2)])
        self.assertEqual(self.scene.world.items.quantity("h_a", "rations"), 0)

    def test_a_task_that_never_ends_times_out(self):
        self.cursors.start("h_a", [REST, WORK], confidence=0.9, tick=0, epoch="E")
        self.cursors.advance(1, "E")
        self.assertEqual(self.cursors.advance(11, "E"), [])                             # exactly the timeout: still allowed
        event = self.cursors.advance(12, "E")[0]
        self.assertEqual((event["status"], event["reason"], event["completed"]), ("aborted", "timeout", 1))
        self.assertEqual(len(ran(self.scene, "go_to_work")), 0)

    def test_a_task_that_ends_badly_aborts_the_plan(self):
        self.cursors.start("h_a", [REST, WORK], confidence=0.9, tick=0, epoch="E")
        self.cursors.advance(1, "E")
        self.scene.ops.finish_task("h_a", self.tasks()[0]["id"], outcome="failed")
        event = self.cursors.advance(2, "E")[0]
        self.assertEqual((event["status"], event["reason"]), ("aborted", "task_failed"))
        self.assertEqual(len(ran(self.scene, "go_to_work")), 0)

    def test_a_changed_epoch_aborts_before_any_step_runs(self):
        self.cursors.start("h_a", [REST, WORK], confidence=0.9, tick=0, epoch="E1:0")
        event = self.cursors.advance(1, "E1:1")[0]                                       # the model switch moved (or the world was reset)
        self.assertEqual((event["status"], event["reason"], event["completed"]), ("aborted", "stale_epoch", 0))
        self.assertEqual(ran(self.scene, "rest"), [])

    def test_a_refused_later_step_aborts_with_the_runner_code(self):
        bad = {"op": "eat", "args": {"item": "gold"}}                                   # not edible / not held
        self.cursors.start("h_a", [REST, bad], confidence=0.9, tick=0, epoch="E")
        self.cursors.advance(1, "E")
        self.scene.ops.finish_task("h_a", self.tasks()[0]["id"])
        event = self.cursors.advance(2, "E")[0]
        self.assertEqual(event["status"], "aborted")
        self.assertTrue(event["reason"].startswith("step_1:"), event)
        self.assertEqual((event["completed"], event["failed_at"]), (1, 1))

    def test_a_new_plan_supersedes_the_running_one(self):
        self.cursors.start("h_a", [REST, WORK], confidence=0.9, tick=0, epoch="E")
        self.cursors.advance(1, "E")
        info = self.cursors.start("h_a", [WORK], confidence=0.9, tick=2, epoch="E")
        self.assertTrue(info["superseded"])
        self.assertEqual(self.cursors.status()["recent"][-1]["reason"], "superseded")
        self.assertEqual(self.cursors.active(), ["h_a"])
        self.assertIsNone(self.cursors.cancel("nobody"))
        self.assertEqual(self.cursors.cancel("h_a", "mode_off", tick=3)["reason"], "mode_off")


class FakeRunner:
    """Routine steps and a task that vanishes: the two waits that cannot be produced on the static scene."""
    def __init__(self, ops_by_op, record):
        self.ops_by_op, self.record, self.calls = ops_by_op, record, []
        self.services = SimpleNamespace(record=lambda actor: self.record)

    def run(self, actor, op, args, **kw):
        self.calls.append(op)
        return SimpleNamespace(ok=True, code="ok", ops=list(self.ops_by_op.get(op, [])))


class FakeRunnerTests(unittest.TestCase):
    def test_a_routine_step_waits_the_placeholder_ticks(self):
        runner = FakeRunner({"sleep": [{"kind": "set_routine", "ok": True}]}, {})
        cursors = PlanCursors(runner, routine_wait_ticks=30)
        cursors.start("a", [{"op": "sleep"}, {"op": "eat"}], confidence=0.8, tick=0, epoch="E")
        cursors.advance(1, "E")
        cursors.advance(30, "E")
        self.assertEqual(runner.calls, ["sleep"])
        cursors.advance(31, "E")                                                         # 1 + 30 elapsed: the next step starts
        self.assertEqual(runner.calls, ["sleep", "eat"])

    def test_a_task_gone_from_the_queue_without_a_record_lets_the_plan_continue(self):
        runner = FakeRunner({"rest": [{"kind": "queue_task", "ok": True, "task_id": "t1"}]}, {"tasks": [{"id": "t1"}]})
        cursors = PlanCursors(runner)
        cursors.start("a", [{"op": "rest"}, {"op": "eat"}], confidence=0.8, tick=0, epoch="E")
        cursors.advance(1, "E")
        self.assertEqual(runner.calls, ["rest"])
        runner.record["tasks"] = []                                                      # cleared by an interruption: no last_completed_task for it
        done = cursors.advance(2, "E")
        self.assertEqual(runner.calls, ["rest", "eat"])
        self.assertEqual(done[0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
