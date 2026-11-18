"""Task-store bridge, step 1: the read-only harness view of the legacy resident task queues (never writes, ids never order)."""
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from authored_village import load_village_maps  # noqa: E402
from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from harness import engine_hooks as eh  # noqa: E402
from harness.legacy_tasks import LegacyTaskView, ReadOnlyTaskStore  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402
from systems.tasks import ops  # noqa: E402


class LegacyTaskViewTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        self.env = mock.patch.dict(os.environ, {eh.FLAG: "1"})
        self.env.start()
        eh.install(DISPATCH)
        self.engine = backend.engine
        self.engine.reset_world()
        await backend.create_genesis(self.engine, map_name="starter_village")
        self.view = eh.runtime(self.engine).world.legacy_tasks
        self.ids = [u for u in self.engine._human_uid_by_slot if u]
        self.a, self.b = self.ids[0], self.ids[1]
        for human_id in self.ids:                                      # start from empty queues so only these tasks are visible
            ops.clear_resident_tasks(self.engine.resident_store.get(human_id), self.engine.tick)
            self.engine.resident_store.get(human_id)["task_state"]["last_completed_task"] = {}

    async def asyncTearDown(self):
        eh.uninstall(DISPATCH)
        self.env.stop()
        if hasattr(self.engine, "harness"):
            del self.engine.harness
        await super().asyncTearDown()

    def resident(self, human_id):
        return self.engine.resident_store.get(human_id)

    def queue(self, human_id, kind="rest", **kw):
        return ops.queue_resident_task(self.resident(human_id), kind, tick=self.engine.tick, **kw)

    def test_the_world_exposes_the_view_and_an_empty_queue_is_empty(self):
        self.assertIsInstance(eh.runtime(self.engine).world.legacy_tasks, LegacyTaskView)
        self.assertEqual(self.view.all(), [])
        self.assertFalse(self.view.has("task_999999"))
        self.assertIsNone(self.view.get("task_999999"))

    def test_queued_active_and_paused_tasks_map_to_assigned_records_in_slot_and_queue_order(self):
        first = self.queue(self.a, "rest", priority=0.9)
        second = self.queue(self.a, "rest", priority=0.2, metadata={"harness_args": {"where": "home"}, "duration": 30})
        other = self.queue(self.b, "rest")
        records = self.view.all()
        self.assertEqual([r["owner"] for r in records], [self.a, self.a, self.b])
        self.assertEqual([r["legacy"]["id"] for r in records], [first["id"], second["id"], other["id"]])
        for r in records:
            self.assertEqual((r["status"], r["owner_table"], r["kind"]), ("assigned", "humans", "rest"))
        self.assertEqual(records[0]["legacy_status"], "active")
        self.assertEqual(records[1]["legacy_status"], "queued")
        self.assertEqual((records[1]["args"], records[1]["duration"]), ({"where": "home"}, 30))
        self.assertEqual([r["id"] for r in self.view.open_for(self.a)], [first["id"], second["id"]])
        self.assertEqual(self.view.get(second["id"])["priority"], 0.2)

    def test_a_harness_id_in_metadata_names_the_task_and_the_legacy_id_still_finds_it(self):
        task = self.queue(self.a, "rest", metadata={"harness_id": "t_000042"})
        self.assertEqual(self.view.get("t_000042")["legacy"]["id"], task["id"])
        self.assertEqual(self.view.get(task["id"])["id"], "t_000042")

    def test_order_follows_queue_position_not_the_id_text(self):
        tasks = [self.queue(self.a, "rest", metadata={"harness_id": name}) for name in ("t_000900", "t_000100", "t_000500")]
        self.assertEqual([r["id"] for r in self.view.all() if r["owner"] == self.a], ["t_000900", "t_000100", "t_000500"])
        self.assertEqual(len(tasks), 3)

    def test_a_completed_task_shows_as_done_and_is_no_longer_open(self):
        task = self.queue(self.a, "rest")
        ops.complete_current_task(self.resident(self.a), self.engine.tick, outcome="completed", reason="rested")
        record = self.view.get(task["id"])
        self.assertEqual((record["status"], record["reason"]), ("done", "rested"))
        self.assertEqual(self.view.open_for(self.a), [])

    def test_a_cancelled_outcome_shows_as_cancelled(self):
        task = self.queue(self.a, "rest")
        ops.complete_current_task(self.resident(self.a), self.engine.tick, outcome="cancelled", reason="no longer needed")
        self.assertEqual(self.view.get(task["id"])["status"], "cancelled")

    def test_reading_never_changes_the_resident_records_or_the_store_flags(self):
        self.queue(self.a, "rest")
        self.queue(self.b, "rest")
        before = copy.deepcopy({u: self.resident(u) for u in self.ids})
        dirty, memory_dirty, revisions = (set(self.engine.resident_store._dirty), set(self.engine.resident_store._memory_dirty),
                                          dict(self.engine.resident_store._revisions))
        for _ in range(3):
            self.view.all(), self.view.get("task_000001"), self.view.open_for(self.a), self.view.has("x")
        self.assertEqual({u: self.resident(u) for u in self.ids}, before)
        self.assertEqual((set(self.engine.resident_store._dirty), set(self.engine.resident_store._memory_dirty),
                          dict(self.engine.resident_store._revisions)), (dirty, memory_dirty, revisions))

    def test_returned_records_are_copies(self):
        self.queue(self.a, "rest")
        record = self.view.all()[0]
        record["legacy"]["status"] = "tampered"
        record["args"]["x"] = 1
        self.assertEqual(self.view.all()[0]["legacy_status"], "active")
        self.assertEqual(self.view.all()[0]["args"], {})

    def test_writes_are_refused_but_a_despawn_cleanup_is_a_no_op(self):
        with self.assertRaises(ReadOnlyTaskStore):
            self.view.new_id()
        with self.assertRaises(ReadOnlyTaskStore):
            self.view.put({"id": "t_1"})
        with self.assertRaises(ReadOnlyTaskStore):
            self.view.update("t_1", status="done")
        self.queue(self.a, "rest")
        self.assertEqual(self.view.cancel_owned_by(self.a, self.engine.tick, "owner_gone"), [])
        self.assertEqual(len(self.view.open_for(self.a)), 1)

    def test_the_effect_path_still_uses_the_world_task_store(self):
        world = eh.runtime(self.engine).world
        self.assertIsNot(world.tasks, world.legacy_tasks)


if __name__ == "__main__":
    unittest.main()
