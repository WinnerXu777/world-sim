"""1008 dormant structure store (EDEN_STRUCTURE_STORE, design 1008_structure_store_gap.md): a structure the game built leaves the tensors with its
chunk and comes back with it (same uid, same row values, geometry, container inventory), decays by a floored closed form while away, and a world
holding any is saved as world format 4 (tests/test_harness_save_format4.py)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
import map_geo  # noqa: E402
from harness import structure_store as store  # noqa: E402
from instincts_and_tools import entity_born  # noqa: E402
from systems.worldgen.rings import ChunkCoord  # noqa: E402

COORD = ChunkCoord(3, 3)
UID = "e_900001"


class StoreFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_STRUCTURE_STORE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(30)                                           # the 5 x 5 ring around chunk (2, 2), chunk (3, 3) included
        self.assertIn(COORD, self.manager.chunks)

    def build(self, uid=UID, x=800.0, y=800.0, durability=80.0, m_type=cfg.M_HOUSE):
        engine = self.engine
        slot = entity_born(engine.state.m_tensor, engine._entity_count_ref, x, y, m_type, hp=100.0, scale=20.0, register_geo=True,
                           col_vals={cfg.S_DURABILITY: durability, cfg.S_SHELTER_CAP: 4.0, cfg.S_BUILD_PROGRESS: 100.0})
        engine._entity_uid_by_slot[slot] = uid
        return slot

    def slot_of(self, uid):
        return self.engine._entity_uid_by_slot.index(uid)

    def cycle(self, coord=COORD):
        self.manager.unload(coord)
        self.manager.integrate(coord, self.service.peek(coord))


class StashRestoreTests(StoreFixture):
    async def test_a_built_structure_leaves_the_tensors_and_comes_back_bit_for_bit(self):
        slot = self.build()
        before = self.engine.state.m_tensor[slot].tolist()
        self.manager.unload(COORD)
        self.assertNotIn(UID, self.engine._entity_uid_by_slot)
        self.assertEqual(self.manager.structures.count(), 1)
        self.assertEqual(self.manager.structures.estimate(COORD), 1)
        self.assertNotIn(slot, map_geo.MAP_GEO, "its geometry went with the row")
        self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertEqual(self.manager.structures.count(), 0)
        back = self.slot_of(UID)
        row = self.engine.state.m_tensor[back].tolist()
        for col in range(len(row)):
            if col != cfg.M_GEN:
                self.assertEqual(row[col], before[col], f"column {col}")
        self.assertIn(back, map_geo.MAP_GEO)
        self.assertEqual(map_geo.MAP_GEO[back]["r"], 20.0)
        self.assertNotIn(back, self.manager.allocator.owned, "a built structure is not one of the window's generated rows")

    async def test_generated_rows_and_the_chunk_delta_are_untouched(self):
        self.build()
        generated = [u for u in self.manager.chunks[COORD].uids]
        self.manager.unload(COORD)
        self.assertNotIn(COORD, self.manager.deltas, "the structure is not recorded as a change to a generated row")
        self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertEqual(self.manager.chunks[COORD].uids, generated)

    async def test_flag_off_the_structure_stays_where_it_was(self):
        self.build()
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_STRUCTURE_STORE")
            self.manager.unload(COORD)
            self.assertIn(UID, self.engine._entity_uid_by_slot)
            self.assertEqual(self.manager.structures.count(), 0)
            self.assertEqual(self.manager.structures.estimate(COORD), 0)

    async def test_only_structures_inside_the_chunk_move(self):
        self.build(UID, 800.0, 800.0)
        self.build("e_900002", 300.0, 300.0)                          # another chunk
        self.manager.unload(COORD)
        self.assertIn("e_900002", self.engine._entity_uid_by_slot)
        self.assertNotIn(UID, self.engine._entity_uid_by_slot)

    async def test_container_inventory_and_seeding_markers_survive(self):
        self.build(m_type=cfg.M_STORAGE_CASE)
        container = self.engine._storage_case_inventory_record(UID)
        container["marker"] = "kept"
        self.engine._inventory_seeded_containers.add(UID)
        self.manager.unload(COORD)
        self.assertNotIn(UID, self.engine._inventory_seeded_containers)
        self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertIn(UID, self.engine._inventory_seeded_containers)
        self.assertEqual(self.engine._storage_case_inventory_record(UID).get("marker"), "kept")

    async def test_a_rebase_while_away_keeps_the_absolute_position(self):
        slot = self.build()
        absolute = float(self.engine.state.m_tensor[slot, cfg.CX]) + 0.0
        self.manager.unload(COORD)
        self.manager.rebase((1, 0))
        self.manager.integrate(COORD, self.service.peek(COORD))
        back = self.slot_of(UID)
        self.assertEqual(float(self.engine.state.m_tensor[back, cfg.CX]), absolute - 256.0)
        self.assertEqual(float(self.engine.state.m_tensor[back, cfg.CY]), 800.0)
        self.assertEqual(map_geo.MAP_GEO[back]["cx"], absolute - 256.0)

    async def test_the_row_estimate_counts_stored_structures(self):
        self.build()
        self.build("e_900002", 820.0, 820.0)
        self.manager.unload(COORD)
        self.assertEqual(self.manager.structures.estimate(COORD), 2)
        self.assertEqual(self.manager.structures.estimate(ChunkCoord(0, 0)), 0)


class CatchUpTests(StoreFixture):
    async def test_decay_is_closed_form_and_floored(self):
        slot = self.build(durability=80.0)
        self.manager.unload(COORD)
        self.engine.tick += int(store._calendar.active().day_ticks) * 4
        with mock.patch.object(store, "DECAY_PER_DAY", 10.0):
            self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertEqual(float(self.engine.state.m_tensor[self.slot_of(UID), cfg.S_DURABILITY]), 40.0)
        self.manager.unload(COORD)
        self.engine.tick += int(store._calendar.active().day_ticks) * 400
        with mock.patch.object(store, "DECAY_PER_DAY", 10.0):
            self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertEqual(float(self.engine.state.m_tensor[self.slot_of(UID), cfg.S_DURABILITY]), 4.0, "never below 10% of what it left with")

    async def test_no_decay_rule_yet_means_no_change(self):
        self.build(durability=80.0)
        self.manager.unload(COORD)
        self.engine.tick += int(store._calendar.active().day_ticks) * 50
        self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertEqual(float(self.engine.state.m_tensor[self.slot_of(UID), cfg.S_DURABILITY]), 80.0)


class SaveTests(StoreFixture):
    async def test_a_snapshot_carries_the_store_only_while_it_holds_structures(self):
        self.build()
        self.assertNotIn("structures", self.manager.snapshot())      # nothing stored: the window section is what it always was
        self.manager.unload(COORD)
        state = self.manager.snapshot()                               # world format 4 (tests/test_harness_save_format4.py): the records are in it
        self.assertEqual([(x, y, [r["uid"] for r in items]) for x, y, items in state["structures"]], [(COORD.x, COORD.y, [UID])])
        self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertNotIn("structures", self.manager.snapshot())      # back in the tensors

    async def test_flag_off_snapshot_has_no_store_in_it(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_STRUCTURE_STORE")
            self.assertNotIn("structures", self.manager.snapshot())


class FarResidentTests(StoreFixture):
    async def test_a_resident_whose_home_is_a_stored_structure_does_not_crash_and_resumes(self):
        self.build()
        resident = {"construction_projects": [{"id": "p1", "building_kind": "personal_shelter", "status": "completed", "metadata": {"owner_human_id": "h_t1"},
                                               "site": {"entity_id": UID}}]}
        home = self.engine._resident_home_structure_record("h_t1", resident)
        self.assertEqual(home["entity_id"], UID)
        self.manager.unload(COORD)
        self.assertIsNone(self.engine._resident_home_structure_record("h_t1", resident), "stored: no home to walk to, and no error")
        self.manager.integrate(COORD, self.service.peek(COORD))
        again = self.engine._resident_home_structure_record("h_t1", resident)
        self.assertEqual((again["entity_id"], again["x"], again["y"]), (UID, 800.0, 800.0))


class BootTests(unittest.TestCase):
    def test_the_store_without_the_window_refuses_to_boot(self):
        from harness import engine_hooks as eh, spaces
        from simulation.dispatch import Dispatcher
        with mock.patch.dict(os.environ, {"EDEN_STRUCTURE_STORE": "1"}):
            os.environ.pop("EDEN_WINDOW", None)
            with self.assertRaises(spaces.SpaceConfigError) as caught:
                eh.install(Dispatcher())
            self.assertIn("EDEN_STRUCTURE_STORE", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
