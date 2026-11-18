"""1008 P5 (b): sources are named by uid, not by slot, wherever a row can be reused while somebody still holds the name.

History. P5 audit (commit ba21bcc) pinned a KNOWN BUG: ``Engine._consume_task_resource`` decrements the food column of whatever row sits in
the slot it is given, with no identity check. Re-reading the call chain for step (b) corrects the audit's description of who holds a
slot: the consumers (``survival.py`` fetch_water / eat_food, ``strategic.py`` gather_food_buffer) take the slot from a target they
resolved *in the same call* (``_resolve_task_resource_target`` scans ``m_tensor``), not from resident memory, so no remembered slot reaches a
consume today. Resident memory (``known_food_sources`` / ``known_water_sources``) is read only by the memory graph and a pressure count. The
hazard is real for the two stores of a slot and one name (memory graph place nodes, ``remember_resource`` matching) once rows are reused
in window mode, and for any future caller that keeps a resolved target across ticks. Step (b) therefore:

* ``_resolve_task_resource_target`` returns the target's ``uid``; ``bridge.consume_resource(..., uid=)`` and ``_consume_task_resource(..., uid=)``
  take nothing when the row holds another entity (a call without ``uid`` is the legacy call, unchanged);
* with ``EDEN_WINDOW=1`` ``remember_resource`` stores ``uid`` and an absolute position and matches entries by uid, and the memory graph names
  the place by uid; without the flag the entry and the node are exactly the legacy ones;
* with ``EDEN_WINDOW=1`` an ``entity_slots`` decree selector is refused (``entity_ids`` is the supported form).

Separate pre-existing defect, fixed in its own commit (``test_harness_gather_food_buffer``): ``strategic.py`` gather_food_buffer passed ``resource.get("entity_id", -1)`` but the resolver's
result has no ``entity_id`` key (it has ``slot``), so the consume always received -1 and returned 0 ("food_source_empty")."""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from test_map_portals import real_world  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
import map_geo  # noqa: E402
from harness import window  # noqa: E402
from harness.frame import SpaceFrame  # noqa: E402
from systems.tasks.contracts import TaskWorldBridge  # noqa: E402


class SlotIdentityTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.engine = await real_world()
        self.m = self.engine.state.m_tensor

    def food_row(self, x, y, food, uid):
        slot = iat.entity_born(self.m, self.engine._entity_count_ref, x, y, cfg.M_FOREST, hp=100.0, scale=10.0, register_geo=True,
                               device=self.engine.state.device, col_vals={cfg.M_RESOURCE_FOOD: food})
        self.assertNotEqual(slot, -1)
        self.addCleanup(map_geo.unregister_entity, slot)
        self.engine._entity_uid_by_slot[slot] = uid
        return slot

    def reuse_slot(self):
        """A food source 'e_remembered' at (50, 50) is freed and another entity ('e_stranger', 250 units away) takes its row."""
        remembered = self.food_row(50.0, 50.0, 40.0, "e_remembered")
        window.release_slots(self.engine, [remembered])
        stranger = self.food_row(300.0, 200.0, 40.0, "e_stranger")
        self.assertEqual(stranger, remembered, "precondition: the freed row is reused at once")
        return remembered

    # -- the consume check ---------------------------------------------------------------------------------------------------
    async def test_a_call_without_uid_is_the_legacy_call_and_still_takes_from_the_row(self):
        slot = self.reuse_slot()
        self.assertEqual(self.engine._consume_task_resource("food", slot, quantity=1), 1)         # legacy semantics, flag-off behaviour kept
        self.assertLess(float(self.m[slot, cfg.M_RESOURCE_FOOD]), 40.0)

    async def test_consume_with_the_uid_of_a_gone_source_takes_nothing(self):
        slot = self.reuse_slot()
        before = float(self.m[slot, cfg.M_RESOURCE_FOOD])
        self.assertEqual(self.engine._consume_task_resource("food", slot, quantity=1, uid="e_remembered"), 0)    # FLIPPED BY (b)
        self.assertEqual(float(self.m[slot, cfg.M_RESOURCE_FOOD]), before)

    async def test_consume_with_the_matching_uid_works(self):
        slot = self.reuse_slot()
        self.assertEqual(self.engine._consume_task_resource("food", slot, quantity=1, uid="e_stranger"), 1)
        self.assertLess(float(self.m[slot, cfg.M_RESOURCE_FOOD]), 40.0)

    async def test_resolved_targets_carry_the_uid_and_the_bridge_passes_it_through(self):
        slot = self.food_row(60.0, 60.0, 40.0, "e_berry")
        hit = self.engine._resolve_task_resource_target(60.0, 62.0, "food", radius=30.0)
        self.assertEqual((hit["slot"], hit["uid"]), (slot, "e_berry"))
        seen = []
        bridge = TaskWorldBridge.__new__(TaskWorldBridge)
        bridge.consume_resource_amount = lambda kind, entity_id, quantity=1, **extra: seen.append((kind, entity_id, quantity, extra)) or 1
        self.assertEqual(bridge.consume_resource("food", 5, 2), 1)
        self.assertEqual(bridge.consume_resource("food", 5, 2, uid="u"), 1)
        self.assertEqual(seen, [("food", 5, 2, {}), ("food", 5, 2, {"uid": "u"})])

    # -- resident memory -----------------------------------------------------------------------------------------------------
    def resident(self):
        human = self.engine._human_uid_by_slot[0]
        self.assertIsNotNone(self.engine.resident_store.get(human))
        for bucket in ("known_food_sources", "known_water_sources"):
            self.engine.resident_store.get(human)["memory"][bucket] = []
        return human

    async def test_legacy_entries_are_unchanged_and_slot_keyed(self):
        human = self.resident()
        store = self.engine.resident_store
        store.remember_resource(human, "known_food_sources", 7, (10.0, 20.0), 5)
        store.remember_resource(human, "known_food_sources", 7, (11.0, 21.0), 6)                # same slot: the same entry (legacy merge)
        entries = store.get(human)["memory"]["known_food_sources"]
        self.assertEqual(len(entries), 1)
        self.assertNotIn("uid", entries[0])
        self.assertNotIn("abs", entries[0])
        self.assertEqual((entries[0]["entity_id"], entries[0]["x"], entries[0]["y"]), (7, 11.0, 21.0))

    async def test_uid_entries_keep_two_sources_apart_when_they_share_a_slot(self):
        human = self.resident()
        store = self.engine.resident_store
        store.remember_resource(human, "known_food_sources", 7, (10.0, 20.0), 5, uid="u_a", abs_pos={"chunk": [1, 2], "x": 3.0, "y": 4.0})
        store.remember_resource(human, "known_food_sources", 7, (90.0, 95.0), 6, uid="u_b")    # the slot was reused by another source
        store.remember_resource(human, "known_food_sources", 9, (12.0, 22.0), 7, uid="u_a")    # u_a is back in another row
        entries = {e["uid"]: e for e in store.get(human)["memory"]["known_food_sources"]}
        self.assertEqual(set(entries), {"u_a", "u_b"})
        self.assertEqual((entries["u_a"]["entity_id"], entries["u_a"]["x"], entries["u_a"]["tick"]), (9, 12.0, 7))
        self.assertEqual(entries["u_a"]["abs"], {"chunk": [1, 2], "x": 3.0, "y": 4.0}, "an update without a position keeps the stored one")
        self.assertEqual((entries["u_b"]["x"], entries["u_b"]["y"]), (90.0, 95.0))

    async def test_memory_graph_names_places_by_uid_only_for_uid_entries(self):
        human = self.resident()
        store = self.engine.resident_store
        store.remember_resource(human, "known_food_sources", 7, (10.0, 20.0), 5)
        store.remember_resource(human, "known_water_sources", 7, (10.0, 20.0), 5, uid="u_w")
        self.engine.sync_memory_graph(human_id=human)
        nodes = self.engine.ensure_memory_rag().nodes
        self.assertIn(f"place:{human}:known_food_sources:7", nodes)
        self.assertIn(f"place:{human}:known_water_sources:u_w", nodes)
        self.assertNotIn(f"place:{human}:known_water_sources:7", nodes)

    async def test_the_case_builder_records_uid_and_absolute_position_only_in_window_mode(self):
        slot = self.food_row(60.0, 60.0, 40.0, "e_berry")
        self.engine.harness = types.SimpleNamespace(world=types.SimpleNamespace(frame=SpaceFrame(256.0, origin=(3, 4))))
        self.addCleanup(lambda: setattr(self.engine, "harness", None))
        runtime = self.engine.human_agent
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDEN_WINDOW", None)
            self.assertEqual(runtime._source_identity(self.engine, slot), {})
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}):
            identity = runtime._source_identity(self.engine, slot)
            self.assertEqual(identity["uid"], "e_berry")
            self.assertEqual(identity["abs_pos"], {"chunk": [3, 4], "x": 60.0, "y": 60.0})
            self.engine._entity_uid_by_slot[slot] = None
            self.assertEqual(runtime._source_identity(self.engine, slot), {}, "a row without a uid is remembered the legacy way")

    async def test_absolute_positions_survive_a_rebase(self):
        frame = SpaceFrame(256.0, origin=(0, 0))
        self.engine.harness = types.SimpleNamespace(world=types.SimpleNamespace(frame=frame))
        self.addCleanup(lambda: setattr(self.engine, "harness", None))
        stored = window.absolute_position(self.engine, 700.0, -30.0)
        self.assertEqual(stored, {"chunk": [2, -1], "x": 188.0, "y": 226.0})
        self.assertEqual(window.local_position(self.engine, stored), (700.0, -30.0))
        frame.rebase((2, 0))                                   # the window origin moves two chunks east
        self.assertEqual(window.local_position(self.engine, stored), (700.0 - 512.0, -30.0))
        self.engine.harness = None
        self.assertIsNone(window.absolute_position(self.engine, 1.0, 2.0))

    # -- decree selectors ----------------------------------------------------------------------------------------------------
    async def test_entity_slots_selectors_are_refused_in_window_mode_and_unchanged_otherwise(self):
        selector = {"kind": "entity_slots", "slots": [self.food_row(60.0, 60.0, 40.0, "e_berry")]}
        for resolver in (self.engine.world_agent._resolve_entity_selector, self.engine.execution_agent._resolve_entity_selector):
            with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}):
                with self.assertRaises(ValueError) as caught:
                    resolver(self.engine, selector)
                self.assertIn("entity_ids", str(caught.exception))
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("EDEN_WINDOW", None)
                self.assertEqual(int(resolver(self.engine, selector).sum()), 1)
            with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}):
                self.assertEqual(int(resolver(self.engine, {"kind": "entity_ids", "ids": ["e_berry"]}).sum()), 1)


if __name__ == "__main__":
    unittest.main()
