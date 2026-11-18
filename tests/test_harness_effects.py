"""EffectApplier (bounds, re-resolution, conservation, revision) and EventLedger (witnesses, idempotence, subscribers)."""
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness import effects as fx  # noqa: E402
from harness.events import EventLedger  # noqa: E402
from harness.frame import SpaceFrame  # noqa: E402
from harness.items import DictItemStore  # noqa: E402
from harness.world import World  # noqa: E402


def small_world(**kwargs):
    w = World.synthetic(seed=11, **kwargs)
    ids = [w.add_row("humans", x=10 + 5 * i, y=10, hp=100, hunger=50, stamina=100) for i in range(4)]
    return w, ids


class DeltaSetTests(unittest.TestCase):
    def test_delta_is_vectorised_clamped_and_bumps_revision(self):
        w, (a, b, c, d) = small_world()
        report = w.apply([fx.delta("humans", [a, b, c], "hunger", [10, 60, -80])])
        h = w.table("humans")
        self.assertEqual([h.get(i, "hunger") for i in (a, b, c, d)], [60.0, 100.0, 0.0, 50.0])  # 110 and -30 clamp to [0, 100]
        self.assertEqual((report.clamped, report.revision, w.revision, report.ok), (2, 1, 1, True))

    def test_adjacent_deltas_to_one_field_accumulate_including_duplicate_ids(self):
        w, (a, *_rest) = small_world()
        w.apply([fx.delta("humans", a, "hunger", 5), fx.delta("humans", [a, a], "hunger", [2, 3])])
        self.assertEqual(w.table("humans").get(a, "hunger"), 60.0)

    def test_order_between_set_and_delta_is_preserved(self):
        w, (a, *_rest) = small_world()
        w.apply([fx.set_("humans", a, "hunger", 10), fx.delta("humans", a, "hunger", 5), fx.set_("humans", a, "hunger", 40)])
        self.assertEqual(w.table("humans").get(a, "hunger"), 40.0)
        w.apply([fx.set_("humans", a, "hunger", 10), fx.delta("humans", a, "hunger", 5)])
        self.assertEqual(w.table("humans").get(a, "hunger"), 15.0)

    def test_set_with_reject_mode_refuses_out_of_range_but_clamp_mode_clamps(self):
        w, (a, *_rest) = small_world()
        report = w.apply([fx.set_("humans", a, "type", 99), fx.set_("humans", a, "hp", 500)])
        self.assertEqual([(s.kind, s.reason) for s in report.skipped], [("Set", "out_of_bounds")])
        self.assertEqual(w.table("humans").get(a, "type"), 1.0)
        self.assertEqual(w.table("humans").get(a, "hp"), 100.0)  # clamped, not rejected

    def test_non_finite_and_unknown_targets_are_skipped_not_applied(self):
        w, (a, *_rest) = small_world()
        report = w.apply([fx.delta("humans", a, "hunger", float("nan")), fx.delta("humans", "h_999999", "hunger", 1),
                          fx.delta("nope", a, "hunger", 1), fx.delta("humans", a, "nofield", 1)])
        self.assertEqual(sorted(s.reason for s in report.skipped), ["non_finite", "unknown_id", "unknown_table_or_field", "unknown_table_or_field"])
        self.assertEqual((w.revision, report.changed, w.table("humans").get(a, "hunger")), (0, False, 50.0))

    def test_reused_slot_is_not_mistaken_for_the_old_entity(self):
        w, (a, b, *_rest) = small_world()
        w.apply([fx.despawn("humans", a)])
        newcomer = w.apply([fx.Spawn("humans", {"type": 1, "x": 1, "y": 1, "hunger": 7})]).spawned[0][1]
        self.assertNotEqual(newcomer, a)
        report = w.apply([fx.delta("humans", a, "hunger", 30)])  # an effect planned against the dead resident
        self.assertEqual([s.reason for s in report.skipped], ["unknown_id"])
        self.assertEqual(w.table("humans").get(newcomer, "hunger"), 7.0)

    def test_dead_but_present_row_is_skipped_as_not_live(self):
        w, (a, *_rest) = small_world()
        w.table("humans").tensor[w.table("humans").slot_of(a), 0] = 0.0  # type 0 = empty, id still attached
        report = w.apply([fx.delta("humans", a, "hunger", 1)])
        self.assertEqual([s.reason for s in report.skipped], ["not_live"])

    def test_position_writes_are_clamped_to_finite_bounds_and_reindexed(self):
        w, (a, *_rest) = small_world(frame=SpaceFrame(bounds=(0, 0, 100, 100)))
        w.apply([fx.set_("humans", a, "x", 5000), fx.delta("humans", a, "y", -5000)])
        self.assertEqual((w.table("humans").get(a, "x"), w.table("humans").get(a, "y")), (100.0, 0.0))
        self.assertEqual(w.within("humans", 100, 0, 1), [a])

    def test_unbounded_world_allows_far_positions(self):
        w, (a, *_rest) = small_world()
        w.apply([fx.set_("humans", a, "x", 5_000_000)])
        self.assertEqual(w.table("humans").get(a, "x"), 5_000_000.0)


class SpawnDespawnTests(unittest.TestCase):
    def test_spawn_assigns_id_slot_index_and_validates(self):
        w, _ids = small_world()
        report = w.apply([fx.Spawn("humans", {"type": 1, "x": 200, "y": 200, "hp": 60})])
        (table_name, new_id), = report.spawned
        self.assertEqual((table_name, w.table("humans").get(new_id, "hp")), ("humans", 60.0))
        self.assertEqual(w.within("humans", 200, 200, 5), [new_id])
        self.assertEqual([s.reason for s in w.apply([fx.Spawn("humans", {"x": 1})]).skipped], ["missing_type"])
        self.assertEqual([s.reason for s in w.apply([fx.Spawn("humans", {"type": 1}, id=new_id)]).skipped], ["duplicate_id"])

    def test_table_full_is_reported(self):
        w = World.synthetic(humans=2)
        w.apply([fx.Spawn("humans", {"type": 1}), fx.Spawn("humans", {"type": 1})])
        self.assertEqual([s.reason for s in w.apply([fx.Spawn("humans", {"type": 1})]).skipped], ["table_full"])

    def test_despawn_clears_row_id_and_index(self):
        w, (a, *_rest) = small_world()
        w.apply([fx.despawn("humans", a)])
        self.assertIsNone(w.table("humans").slot_of(a))
        self.assertEqual(w.within("humans", 10, 10, 1), [])
        self.assertEqual([s.reason for s in w.apply([fx.despawn("humans", a)]).skipped], ["unknown_id"])


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.w = World.synthetic(items=DictItemStore(capacity_per_owner=10))
        self.w.items.add("a", "bread", 6)

    def test_transfer_moves_items_and_conserves_the_total(self):
        report = self.w.apply([fx.Transfer("bread", 4, "a", "b")])
        self.assertEqual((self.w.items.quantity("a", "bread"), self.w.items.quantity("b", "bread"), self.w.items.total("bread")), (2, 4, 6))
        self.assertEqual((report.created, report.destroyed, report.ok), ({}, {}, True))

    def test_insufficient_and_no_room_are_rejected_without_side_effects(self):
        self.w.items.add("full", "stone", 10)
        report = self.w.apply([fx.Transfer("bread", 7, "a", "b"), fx.Transfer("bread", 1, "a", "full")])
        self.assertEqual([s.reason for s in report.skipped], ["insufficient", "no_room"])
        self.assertEqual((self.w.items.quantity("a", "bread"), self.w.items.total("bread")), (6, 6))

    def test_creation_and_destruction_need_permission_and_are_counted(self):
        denied = self.w.apply([fx.Transfer("bread", 1, None, "a")])
        self.assertEqual([s.reason for s in denied.skipped], ["creation_not_allowed"])
        w = World.synthetic(allow_item_creation=True)
        w.items.add("a", "bread", 3)
        report = w.apply([fx.Transfer("coin", 5, None, "a"), fx.Transfer("bread", 2, "a", None)])
        self.assertEqual((report.created, report.destroyed, w.items.total("coin"), w.items.total("bread")), ({"coin": 5}, {"bread": 2}, 5, 1))

    def test_bad_quantities_and_endpoints(self):
        report = self.w.apply([fx.Transfer("bread", 0, "a", "b"), fx.Transfer("bread", -1, "a", "b"), fx.Transfer("bread", 1, None, None)])
        self.assertEqual([s.reason for s in report.skipped], ["invalid_quantity", "invalid_quantity", "no_endpoints"])

    def test_a_buggy_store_that_loses_items_is_caught(self):
        class LeakyStore(DictItemStore):
            def add(self, owner, item, qty):
                super().add(owner, item, qty - 1)   # silently drops one
                return qty
        w = World.synthetic(items=LeakyStore())
        w.items._held["a"]["bread"] = 5
        with self.assertRaises(fx.ConservationError):
            w.apply([fx.Transfer("bread", 3, "a", "b")])


class AtomicAndPreviewTests(unittest.TestCase):
    def test_atomic_applies_nothing_if_anything_is_invalid(self):
        w, (a, *_rest) = small_world()
        effects = [fx.delta("humans", a, "hunger", -10), fx.delta("humans", "h_999999", "hunger", 1)]
        report = w.apply(effects, atomic=True)
        self.assertTrue(report.rolled_back)
        self.assertEqual((w.table("humans").get(a, "hunger"), w.revision), (50.0, 0))
        self.assertEqual([s.reason for s in w.effects.validate(effects)], ["unknown_id"])

    def test_atomic_transfer_validation_tracks_running_balances(self):
        w = World.synthetic()
        w.items.add("a", "bread", 5)
        problems = w.effects.validate([fx.Transfer("bread", 3, "a", "b"), fx.Transfer("bread", 3, "a", "c")])
        self.assertEqual([p.reason for p in problems], ["insufficient"])
        self.assertEqual(w.items.quantity("a", "bread"), 5)  # validate never mutates
        self.assertEqual(w.apply([fx.Transfer("bread", 3, "a", "b"), fx.Transfer("bread", 2, "a", "c")], atomic=True).ok, True)

    def test_clean_atomic_apply_succeeds(self):
        w, (a, b, *_rest) = small_world()
        report = w.apply([fx.delta("humans", [a, b], "hunger", -5)], atomic=True)
        self.assertEqual((report.ok, report.rolled_back, w.revision), (True, False, 1))


class EventTests(unittest.TestCase):
    def test_emit_effect_records_event_with_witnesses_by_radius_and_actors(self):
        w, (a, b, c, d) = small_world()   # x = 10, 15, 20, 25
        w.apply([fx.set_("humans", d, "x", 600)])
        report = w.apply([fx.Emit("gift", actors=(a,), place=(10, 10), radius=12)], cause="test")
        event = report.events[0]
        self.assertEqual((event.type, event.witnesses, event.cause, event.tick), ("gift", (a, b, c), "test", 0))
        self.assertEqual(w.events.witnessed_by(d), [])

    def test_visibility_global_and_private(self):
        w, (a, b, c, d) = small_world()
        everyone = w.events.emit("earthquake", visibility="global")
        private = w.events.emit("secret", actors=(a,), visibility="private")
        self.assertEqual(everyone.witnesses, (a, b, c, d))
        self.assertEqual(private.witnesses, (a,))
        with self.assertRaises(ValueError):
            w.events.emit("x", visibility="loud")

    def test_event_id_is_idempotent_and_adds_only_new_witnesses(self):
        w, (a, b, *_rest) = small_world()
        first = w.events.emit("gift", place=(10, 10), radius=1, event_id="g_1")
        again = w.events.emit("gift", place=(15, 10), radius=1, event_id="g_1")
        self.assertIs(first, again)
        self.assertEqual(first.witnesses, (a, b))
        self.assertEqual(len(w.events.events(type="gift")), 1)

    def test_subscribers_run_once_in_order_after_dispatch(self):
        w, (a, *_rest) = small_world()
        log = []
        w.events.subscribe(lambda e: log.append(("all", e.id)))
        w.events.subscribe(lambda e: log.append(("gift", e.id)), types=["gift"])
        w.events.emit("gift", actors=(a,))
        w.events.emit("other")
        self.assertEqual(log, [])          # nothing before dispatch
        self.assertEqual(w.events.dispatch(), 2)
        self.assertEqual(log, [("all", "ev_000001"), ("gift", "ev_000001"), ("all", "ev_000002")])
        self.assertEqual(w.events.dispatch(), 0)

    def test_queries_history_limit_and_persistence_round_trip(self):
        w, (a, b, *_rest) = small_world()
        w.events.emit("gift", actors=(a,), place=(10, 10), payload={"n": 1})
        w.clock.advance(5)
        w.events.emit("theft", actors=(b,), place=(15, 10), payload={"n": 2})
        self.assertEqual([e.type for e in w.events.events(since_tick=3)], ["theft"])
        self.assertEqual([e.type for e in w.events.events(actor=a)], ["gift"])
        restored = EventLedger.from_dict(w.events.to_dict())
        self.assertEqual([e.to_dict() for e in restored.events()], [e.to_dict() for e in w.events.events()])
        self.assertEqual(restored.new_id(), "ev_000003")
        small = EventLedger(history=3)
        for i in range(5):
            small.emit("t")
        self.assertEqual([e.id for e in small.events()], ["ev_000003", "ev_000004", "ev_000005"])
        self.assertIsNone(small.get("ev_000001"))


if __name__ == "__main__":
    unittest.main()
