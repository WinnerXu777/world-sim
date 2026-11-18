"""1008 Phase 2 (1008_creatures_gap.md section 6): creatures in the streaming window (EDEN_CREATURES, needs EDEN_WINDOW).

The spawn plan puts the legacy-brain species (sheep, deer, wolf) into integrated chunks within a row quota that is not the window budget; a creature standing in a chunk that
unloads (or outside every integrated chunk) is stored with that chunk and comes back with a closed-form catch-up; nothing of the store is saved (a load repopulates lazily
without doubling the creatures that are alive)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import calendar as calendar_module, creature_store  # noqa: E402
from systems.creatures import spawn, table  # noqa: E402
from systems.worldgen.rings import ChunkCoord  # noqa: E402

CREATURE_IDS = {r["id"] for r in table.CREATURES.values()}
COORD = ChunkCoord(2, 2)


class CreatureFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_CREATURES": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(30)

    def creature_slots(self):
        m = self.engine.state.m_tensor
        return [s for s in range(cfg.MAX_ENTITIES) if int(m[s, cfg.M_TYPE]) in {r["id"] for r in table.CREATURES.values()}]

    def uids(self):
        return {self.engine._entity_uid_by_slot[s] for s in self.creature_slots()}

    def planned(self, coords=None):
        """The uids the plan wants for the integrated chunks."""
        found = set()
        for coord in (coords or self.manager.chunks):
            found.update(rec["uid"] for rec in spawn.plan(self.service.peek(coord).document))
        return found


class PopulateTests(CreatureFixture):
    async def test_the_integrated_chunks_hold_their_planned_creatures(self):
        uids = self.uids()
        self.assertGreater(len(uids), 3)
        self.assertEqual(uids, self.planned() if len(uids) < creature_store.row_quota() else uids)
        self.assertTrue(all(u.split(":")[1] == "fauna" for u in uids))
        m = self.engine.state.m_tensor
        for slot in self.creature_slots():
            self.assertIn(int(m[slot, cfg.M_TYPE]), CREATURE_IDS)
            self.assertGreater(float(m[slot, cfg.M_HP]), 0.0)
            self.assertEqual(float(m[slot, cfg.M_SPACE]), 0.0)
        self.assertEqual(self.engine._entity_count_ref[0], len(self.manager.allocator.owned) + len(uids) + 0)

    async def test_table_brain_species_spawn_now_that_the_kernel_exists(self):
        self.assertEqual(self.manager.creatures.counters["skipped_kernel"], 0)
        brains = {table.by_type(int(self.engine.state.m_tensor[s, cfg.M_TYPE]))["brain"] for s in self.creature_slots()}
        self.assertIn("table", brains)

    async def test_creatures_are_not_rows_of_the_window_budget(self):
        self.assertFalse(set(self.creature_slots()) & self.manager.allocator.owned)

    async def test_the_plan_is_what_populates_not_the_clock(self):
        again = set(self.uids())
        self.run_ticks(60)
        self.assertEqual(self.uids() - again, set(), "no new creature appears in chunks that were populated")

    async def test_the_quota_limits_new_creatures(self):
        coords = list(self.manager.chunks)
        for coord in coords:
            self.manager.unload(coord)
        self.manager.creatures.after_load()
        self.assertEqual(self.creature_slots(), [])
        with mock.patch.dict(os.environ, {creature_store.ROWS_ENV: "3"}):
            for coord in coords:
                self.manager.integrate(coord, self.service.peek(coord))
            self.assertEqual(len(self.creature_slots()), 3)
            self.assertGreater(self.manager.creatures.counters["skipped_quota"], 0)


class FlagOffTests(WindowFixture):
    async def test_flag_off_nothing_is_spawned_and_nothing_is_stored(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(30)
        m = self.engine.state.m_tensor
        ids = torch.tensor([float(r["id"]) for r in table.CREATURES.values()])
        self.assertFalse(bool(torch.isin(m[:cfg.MAX_ENTITIES, cfg.M_TYPE], ids).any()))
        self.assertEqual(self.manager.creatures.counters["populated"], 0)
        self.assertEqual(self.manager.creatures.count(), 0)
        self.assertEqual(self.manager.creatures.estimate(COORD), 0)


class StashRestoreTests(CreatureFixture):
    def stand_in(self, coord):
        m = self.engine.state.m_tensor
        bx, by = self.manager._local_origin(coord)
        return [s for s in self.creature_slots() if bx <= float(m[s, cfg.CX]) < bx + 256.0 and by <= float(m[s, cfg.CY]) < by + 256.0]

    def a_chunk_with_creatures(self):
        for coord in self.manager.chunks:
            if self.stand_in(coord):
                return coord
        self.fail("no chunk of the ring has a creature")

    async def test_unload_stores_the_creatures_and_integrate_brings_them_back(self):
        coord = self.a_chunk_with_creatures()
        slots = self.stand_in(coord)
        before = {self.engine._entity_uid_by_slot[s]: self.engine.state.m_tensor[s].tolist() for s in slots}
        self.manager.unload(coord)
        self.assertEqual(self.stand_in(coord), [])
        self.assertEqual(self.manager.creatures.estimate(coord), len(before))
        self.assertTrue(set(before).isdisjoint(self.uids()))
        self.manager.integrate(coord, self.service.peek(coord))
        self.assertEqual(self.manager.creatures.estimate(coord), 0)
        back = {self.engine._entity_uid_by_slot[s]: self.engine.state.m_tensor[s].tolist() for s in self.stand_in(coord)}
        self.assertEqual(set(back), set(before), "same creatures, none doubled by the plan")
        for uid, row in back.items():
            for col in (cfg.M_TYPE, cfg.CX, cfg.CY, cfg.M_HP, cfg.A_SEX, cfg.A_LIFE_EXP, cfg.A_AGGRESSION):
                self.assertEqual(row[col], before[uid][col], (uid, col))

    async def test_the_catch_up_ages_feeds_and_never_kills_by_hunger(self):
        coord = self.a_chunk_with_creatures()
        slot = self.stand_in(coord)[0]
        uid = self.engine._entity_uid_by_slot[slot]
        m = self.engine.state.m_tensor
        m[slot, cfg.A_HUNGER] = 30.0
        age = float(m[slot, cfg.A_AGE])
        life = float(m[slot, cfg.A_LIFE_EXP])
        self.manager.unload(coord)
        elapsed = 1200                                                  # under the respawn days: a plan refill must not stand in for the restore
        self.engine.tick += elapsed
        self.manager.integrate(coord, self.service.peek(coord))
        if uid not in self.uids():
            self.assertGreater(age + elapsed * calendar_module.age_step(), life, "it is gone only because it died of age")
            return
        back = self.engine._entity_uid_by_slot.index(uid)
        self.assertAlmostEqual(float(m[back, cfg.A_AGE]), age + elapsed * calendar_module.age_step(), places=3)
        self.assertGreater(float(m[back, cfg.A_HUNGER]), 30.0)
        self.assertLessEqual(float(m[back, cfg.A_HUNGER]), creature_store.HUNGER_CAP)

    async def test_a_creature_past_its_life_expectancy_does_not_come_back(self):
        coord = self.a_chunk_with_creatures()
        slot = self.stand_in(coord)[0]
        uid = self.engine._entity_uid_by_slot[slot]
        m = self.engine.state.m_tensor
        m[slot, cfg.A_AGE] = float(m[slot, cfg.A_LIFE_EXP]) - 1e-6
        self.manager.unload(coord)
        self.engine.tick += 100
        self.manager.integrate(coord, self.service.peek(coord))
        self.assertNotIn(uid, self.uids())
        self.assertGreaterEqual(self.manager.creatures.counters["died_away"], 1)

    async def test_a_wanderer_outside_every_integrated_chunk_is_stored_with_the_chunk_it_stands_in(self):
        coord = self.a_chunk_with_creatures()
        slot = self.stand_in(coord)[0]
        uid = self.engine._entity_uid_by_slot[slot]
        m = self.engine.state.m_tensor
        far = ChunkCoord(7, 2)
        m[slot, cfg.CX], m[slot, cfg.CY] = 7 * 256.0 + 40.0, 2 * 256.0 + 90.0
        self.engine.tick += 20 - (self.engine.tick % 20)
        self.manager.creatures.tick()
        self.assertNotIn(uid, self.uids())
        record = self.manager.creatures.records[far][0]
        self.assertEqual(record["uid"], uid)
        self.assertEqual(record["offset"], [40.0, 90.0])
        self.assertEqual(self.manager.creatures.index[uid], far)

    async def test_a_rebase_does_not_move_a_stored_creature(self):
        coord = self.a_chunk_with_creatures()
        slot = self.stand_in(coord)[0]
        uid = self.engine._entity_uid_by_slot[slot]
        self.manager.unload(coord)
        record = [r for r in self.manager.creatures.records[coord] if r["uid"] == uid][0]
        offset = list(record["offset"])
        self.manager.frame.origin = (1, 0)                           # the window moved one chunk east (offsets are chunk-relative)
        self.assertEqual([r for r in self.manager.creatures.records[coord] if r["uid"] == uid][0]["offset"], offset)

    async def test_killed_creatures_return_only_after_the_respawn_days(self):
        coord = self.a_chunk_with_creatures()
        slot = self.stand_in(coord)[0]
        uid = self.engine._entity_uid_by_slot[slot]
        self.manager.allocator.release([slot])                        # killed and gone
        self.manager.unload(coord)
        self.manager.integrate(coord, self.service.peek(coord))
        self.assertNotIn(uid, self.uids(), "soon back: it stays dead")
        self.manager.unload(coord)
        self.engine.tick += creature_store.RESPAWN_DAYS * int(calendar_module.active().day_ticks) + 1
        self.manager.integrate(coord, self.service.peek(coord))
        self.assertIn(uid, self.uids(), "after the respawn days the plan refills it")


class SaveTests(CreatureFixture):
    async def test_a_load_repopulates_without_doubling_and_snapshot_is_not_refused(self):
        before = self.uids()
        state = self.manager.snapshot()                                # creatures never refuse a save
        self.assertNotIn("creatures", state)
        self.manager.creatures.after_load()
        self.assertEqual(self.manager.creatures.count(), 0)
        self.run_ticks(60)                                             # tick() populates the chunks again, one per tick, uid-deduplicated
        self.assertEqual(self.uids(), before)
        uids = [self.engine._entity_uid_by_slot[s] for s in self.creature_slots()]
        self.assertEqual(len(uids), len(set(uids)))


class BootTests(unittest.TestCase):
    def test_creatures_without_the_window_refuse_to_boot(self):
        from harness import engine_hooks as eh, spaces
        from simulation.dispatch import Dispatcher
        with mock.patch.dict(os.environ, {"EDEN_CREATURES": "1"}):
            os.environ.pop("EDEN_WINDOW", None)
            with self.assertRaises(spaces.SpaceConfigError) as caught:
                eh.install(Dispatcher())
            self.assertIn("EDEN_CREATURES", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
