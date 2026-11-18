"""H-Q2: the Task effect (create / assign / cancel / complete a task record as data) for durative actions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness import effects as fx  # noqa: E402
from harness.effects import Task  # noqa: E402
from harness.items import DictItemStore  # noqa: E402
from harness.tasks import ASSIGNED, CANCELLED, DONE, PENDING, DictTaskStore  # noqa: E402
from harness.world import World  # noqa: E402


def make():
    w = World.synthetic(seed=5)
    a = w.add_row("humans", x=10, y=10, hp=100)
    b = w.add_row("humans", x=20, y=10, hp=100)
    return w, a, b


def reasons(report):
    return [s.reason for s in report.skipped]


class CreateTests(unittest.TestCase):
    def test_create_unowned_and_owned_tasks_with_allocated_ids(self):
        w, a, b = make()
        report = w.apply([fx.task_create("eat", a, args={"item": "bread"}, priority=0.9, duration=5),
                          fx.task_create("fetch_water")])
        self.assertTrue(report.ok)
        (op1, t1), (op2, t2) = report.tasks
        self.assertEqual((op1, op2, t1, t2), ("create", "create", "t_000001", "t_000002"))
        first, second = w.tasks.get(t1), w.tasks.get(t2)
        self.assertEqual((first["status"], first["owner"], first["args"], first["priority"], first["duration"], first["created_tick"]),
                         (ASSIGNED, a, {"item": "bread"}, 0.9, 5, 0))
        self.assertEqual((second["status"], second["owner"]), (PENDING, None))
        self.assertEqual((report.applied, report.changed, w.revision), ({"Task": 2}, True, 1))
        self.assertEqual([t["id"] for t in w.tasks.open_for(a)], [t1])

    def test_explicit_id_lets_one_batch_create_then_assign_then_complete(self):
        w, a, b = make()
        report = w.apply([fx.Task("create", task_id="walk-1", kind="walk"), fx.task_assign("walk-1", b),
                          fx.task_complete("walk-1")], atomic=True)
        self.assertTrue(report.ok, [(s.reason, s.detail) for s in report.skipped])
        record = w.tasks.get("walk-1")
        self.assertEqual((record["status"], record["owner"], record["closed_tick"]), (DONE, b, 0))

    def test_invalid_creates_are_refused_with_stable_reasons_and_change_nothing(self):
        w, a, b = make()
        cases = [(fx.Task("create"), "invalid_task"), (fx.task_create("x", priority=1.5), "invalid_task"),
                 (fx.task_create("x", priority=True), "invalid_task"), (fx.task_create("x", duration=0), "invalid_task"),
                 (fx.task_create("x", duration=2.5), "invalid_task"), (fx.task_create("x", expires_tick=0), "invalid_task"),
                 (fx.task_create("x", args=[1]), "invalid_task"), (fx.Task("explode", task_id="q"), "invalid_task"),
                 (fx.task_create("x", owner="h_nobody"), "unknown_owner"),
                 (fx.task_create("x", owner=a, owner_table="nowhere"), "unknown_owner")]
        for effect, reason in cases:
            r = w.apply([effect], atomic=True)
            self.assertEqual((reasons(r), r.rolled_back), ([reason], True), repr(effect))
        self.assertEqual((w.tasks.all(), w.revision), ([], 0))

    def test_a_dead_owner_is_refused(self):
        w, a, b = make()
        w.apply([fx.despawn("humans", b)])
        self.assertEqual(reasons(w.apply([fx.task_create("x", b)])), ["unknown_owner"])

    def test_duplicate_explicit_id_is_refused_including_inside_one_batch(self):
        w, a, b = make()
        w.apply([fx.Task("create", task_id="same", kind="x")])
        self.assertEqual(reasons(w.apply([fx.Task("create", task_id="same", kind="y")])), ["task_exists"])
        r = w.apply([fx.Task("create", task_id="new", kind="x"), fx.Task("create", task_id="new", kind="y")], atomic=True)
        self.assertEqual((reasons(r), w.tasks.has("new")), (["task_exists"], False))


class AssignCancelTests(unittest.TestCase):
    def test_assign_reassign_cancel_and_closed_tasks_stay_closed(self):
        w, a, b = make()
        report = w.apply([fx.Task("create", task_id="t", kind="carry")])
        w.apply([fx.task_assign("t", a)])
        w.apply([fx.task_assign("t", b)])
        self.assertEqual(w.tasks.get("t")["owner"], b)
        self.assertEqual(([t["id"] for t in w.tasks.open_for(a)], [t["id"] for t in w.tasks.open_for(b)]), ([], ["t"]))
        w.apply([fx.task_cancel("t", "changed my mind")])
        record = w.tasks.get("t")
        self.assertEqual((record["status"], record["reason"], w.tasks.open_for(b)), (CANCELLED, "changed my mind", []))
        for effect in (fx.task_assign("t", a), fx.task_cancel("t"), fx.task_complete("t")):
            self.assertEqual(reasons(w.apply([effect])), ["task_closed"])
        self.assertEqual(reasons(w.apply([fx.task_cancel("ghost")])), ["unknown_task"])
        self.assertEqual(reasons(w.apply([fx.Task("assign", task_id="t2")])), ["unknown_task"])

    def test_assign_needs_a_live_owner(self):
        w, a, b = make()
        w.apply([fx.Task("create", task_id="t", kind="x")])
        self.assertEqual(reasons(w.apply([fx.task_assign("t", "h_nobody")])), ["unknown_owner"])
        self.assertEqual(reasons(w.apply([fx.Task("assign", task_id="t", owner=None)])), ["invalid_task"])
        self.assertEqual(w.tasks.get("t")["status"], PENDING)

    def test_atomic_batch_with_one_bad_task_effect_applies_nothing(self):
        w, a, b = make()
        before = w.revision
        r = w.apply([fx.task_create("x", a), fx.delta("humans", a, "hunger", 5), fx.task_cancel("ghost")], atomic=True)
        self.assertEqual((reasons(r), r.rolled_back, w.tasks.all(), w.table("humans").get(a, "hunger"), w.revision), (["unknown_task"], True, [], 0.0, before))

    def test_validate_sees_earlier_effects_of_the_same_batch_and_changes_nothing(self):
        w, a, b = make()
        batch = [fx.Task("create", task_id="t", kind="x"), fx.task_cancel("t"), fx.task_assign("t", a)]
        self.assertEqual([p.reason for p in w.effects.validate(batch)], ["task_closed"])
        self.assertEqual((w.tasks.all(), w.revision), ([], 0))


class OwnerLeavesTests(unittest.TestCase):
    def test_despawning_the_owner_cancels_its_open_tasks_only(self):
        w, a, b = make()
        w.apply([fx.Task("create", task_id="a1", kind="x", owner=a), fx.Task("create", task_id="a2", kind="y", owner=a),
                 fx.Task("create", task_id="b1", kind="x", owner=b), fx.Task("create", task_id="free", kind="z")])
        w.apply([fx.task_complete("a2")])
        report = w.apply([fx.despawn("humans", a)])
        self.assertEqual(report.tasks, [("cancel", "a1")])
        status = {t["id"]: (t["status"], t["reason"]) for t in w.tasks.all()}
        self.assertEqual(status, {"a1": (CANCELLED, "owner_gone"), "a2": (DONE, ""), "b1": (ASSIGNED, ""), "free": (PENDING, "")})


class StoreTests(unittest.TestCase):
    def test_store_returns_copies_and_rejects_duplicates(self):
        store = DictTaskStore()
        store.put({"id": "t", "owner": None, "status": PENDING, "args": {"k": [1]}})
        got = store.get("t")
        got["args"]["k"].append(2)
        self.assertEqual(store.get("t")["args"], {"k": [1]})
        with self.assertRaises(KeyError):
            store.put({"id": "t", "owner": None, "status": PENDING})

    def test_allocated_ids_skip_existing_ones_and_are_deterministic(self):
        def run():
            w, a, b = make()
            w.apply([fx.Task("create", task_id="t_000001", kind="x")])
            return w.apply([fx.task_create("y"), fx.task_create("z")]).tasks
        self.assertEqual(run(), [("create", "t_000002"), ("create", "t_000003")])
        self.assertEqual(run(), run())

    def test_a_custom_store_can_be_injected_and_items_still_conserve(self):
        store = DictTaskStore()
        w = World.synthetic(tasks=store, items=DictItemStore())
        a = w.add_row("humans", x=1, y=1, hp=10)
        w.items.add(a, "bread", 2)
        w.apply([fx.task_create("eat", a), fx.Transfer("bread", 1, a, None)], items=fx.ItemPermit.of(consume=["bread"]))
        self.assertEqual((len(store.all()), w.items.total("bread")), (1, 1))


if __name__ == "__main__":
    unittest.main()
