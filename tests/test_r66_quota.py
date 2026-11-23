"""R66-QUOTA-2: ring-first creature rows (EDEN_CREATURES, with a controlled actor only).

The creature row quota used to go to whichever chunk integrated first, and a chunk it left short stayed short until the respawn days passed,
even when the player stood in it. With a controlled actor: a chunk cannot take rows a strictly nearer short chunk is waiting for; the nearest
short chunk is filled late, one a tick; and a short chunk in the player's inner ring (distance 1) takes rows from creatures standing in chunks
farther than the simulation radius from every controlled actor (they are stashed through the store's own path and come back nearest-first).
With no controlled actor (boot, headless, the balance runs) nothing changes."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_creature_store import CreatureFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import calendar as calendar_module, creature_store  # noqa: E402
from systems.creatures import spawn  # noqa: E402
from systems.worldgen.rings import ChunkCoord  # noqa: E402

PLAYER = ChunkCoord(1, 4)                 # in the 5 x 5 ring the fixture integrates around its resident at chunk (2, 2); the spawn plan puts
                                          # creatures only in chunks (2, 3), (2, 4), (3, 3), (4, 3), (4, 4): two inner, one edge, two far from here
NEW_COUNTERS = ("skipped_quota_near", "populated_late", "restored_late", "evicted_for_ring", "short_rows")


class QuotaFixture(CreatureFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.store = self.manager.creatures

    def control(self, coord=PLAYER, slot=1):
        """A player incarnated in a human standing in the middle of ``coord`` (the resident in slot 0 keeps the ring integrated)."""
        self.place_human(slot, coord.x * 256.0 + 128.0, coord.y * 256.0 + 128.0)
        uids = self.engine._human_uid_by_slot
        saved = uids[slot]
        uids[slot] = "human:r66-quota-player"
        self.addCleanup(lambda: uids.__setitem__(slot, saved))
        patcher = mock.patch.dict(self.engine._incarnated_human_by_controller, {"r66-quota": {"human_id": "human:r66-quota-player"}})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(len(self.manager.controlled_actors()), 1)

    def quota(self, rows):
        patcher = mock.patch.dict(os.environ, {creature_store.ROWS_ENV: str(rows)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def empty_store(self):
        """Every chunk unloaded and the store cleared (nothing saved, as after a load); returns the chunks that were integrated."""
        coords = list(self.manager.chunks)
        for coord in coords:
            self.manager.unload(coord)
        self.store.after_load()
        self.assertEqual(self.creature_slots(), [])
        return coords

    def integrate(self, coord):
        self.manager.integrate(coord, self.service.peek(coord))

    def plan_size(self, coord):
        return len(spawn.plan(self.service.peek(coord).document))

    @staticmethod
    def distance(coord, player=PLAYER):
        return max(abs(coord.x - player.x), abs(coord.y - player.y))

    def pick(self, coords, near, need, exclude=()):
        """The first chunk (in coordinate order) at a distance ``near`` accepts, with at least ``need`` planned creatures."""
        for coord in sorted(coords, key=lambda c: (c.x, c.y)):
            if coord not in exclude and near(self.distance(coord)) and self.plan_size(coord) >= need:
                return coord
        self.fail(f"no chunk with {need} planned creatures at the wanted distance")

    def stand_in(self, coord):
        m = self.engine.state.m_tensor
        bx, by = self.manager._local_origin(coord)
        return [s for s in self.creature_slots() if bx <= float(m[s, cfg.CX]) < bx + 256.0 and by <= float(m[s, cfg.CY]) < by + 256.0]

    def tick(self, n=1):
        for _ in range(n):
            self.engine.tick += 1
            self.store.tick()

    def assert_no_doubles(self):
        live = [self.engine._entity_uid_by_slot[s] for s in self.creature_slots()]
        self.assertEqual(len(live), len(set(live)), "a creature is alive twice")
        self.assertFalse(set(live) & set(self.store.index), "a creature is alive and stored at once")


class StarveThenFillTests(QuotaFixture):
    async def test_the_players_chunk_takes_rows_from_a_chunk_outside_the_players_ring(self):
        self.control()
        coords = self.empty_store()
        self.assertIn(PLAYER, coords)
        far = self.pick(coords, lambda d: d >= 3, need=3)
        inner = self.pick(coords, lambda d: d <= 1, need=3)
        self.quota(3)
        self.integrate(far)
        self.assertEqual(len(self.stand_in(far)), 3)
        self.integrate(inner)
        self.assertEqual(self.stand_in(inner), [], "the quota is full: the chunk next to the player is left short")
        self.assertGreater(self.store.counters["skipped_quota_near"], 0)
        far_uids = {self.engine._entity_uid_by_slot[s] for s in self.stand_in(far)}
        self.tick(3)
        want = min(self.plan_size(inner), 3)
        self.assertEqual(len(self.stand_in(inner)), want, "the chunk next to the player is filled within a few ticks")
        self.assertEqual(self.store.counters["evicted_for_ring"], want)
        self.assertLessEqual(self.store.live_count(), 3)
        stored = {r["uid"] for r in self.store.records.get(far, [])}
        self.assertEqual(len(stored), want, "the evicted creatures are stored with the chunk they stood in")
        self.assertTrue(stored <= far_uids)
        for record in self.store.records[far]:                           # the store's own record shape: nothing new is persisted
            self.assertEqual(set(record), {"uid", "type", "cols", "offset", "tick"})
            self.assertEqual(self.store.index[record["uid"]], far)
        self.assert_no_doubles()

    async def test_a_short_chunk_at_the_edge_of_the_ring_does_not_evict(self):
        self.control()
        coords = self.empty_store()
        far = self.pick(coords, lambda d: d >= 3, need=3)
        edge = self.pick(coords, lambda d: d == 2, need=1)
        self.quota(3)
        self.integrate(far)
        self.integrate(edge)
        self.tick(5)
        self.assertEqual(self.stand_in(edge), [], "only the inner ring (distance <= 1) takes rows from other chunks")
        self.assertEqual(self.store.counters["evicted_for_ring"], 0)
        self.assertEqual(len(self.stand_in(far)), 3)


class PriorityTests(QuotaFixture):
    async def test_a_farther_chunk_cannot_take_rows_a_nearer_short_chunk_waits_for(self):
        self.control()
        coords = self.empty_store()
        far1 = self.pick(coords, lambda d: d >= 3, need=3)
        inner = self.pick(coords, lambda d: d == 1, need=2)
        far2 = self.pick(coords, lambda d: d >= 3, need=1, exclude=(far1,))
        self.quota(3)
        self.integrate(far1)
        self.integrate(inner)
        self.assertEqual(self.stand_in(inner), [])
        self.store._stash(self.stand_in(far1)[:2])                        # two rows free up (the creatures are stored with far1)
        self.integrate(far2)
        self.assertEqual(self.stand_in(far2), [], "the 2 free rows are the inner chunk's")
        self.tick()
        self.assertEqual(len(self.stand_in(inner)), 2)
        self.assertEqual(self.store.counters["populated_late"], 2)
        self.assert_no_doubles()

    async def test_the_nearest_short_chunk_is_filled_first_one_chunk_a_tick(self):
        self.control()
        coords = self.empty_store()
        far = self.pick(coords, lambda d: d >= 3, need=3)
        inner = self.pick(coords, lambda d: d == 1, need=1)
        edge = self.pick(coords, lambda d: d == 2, need=1)
        self.quota(3)
        self.integrate(far)
        self.integrate(edge)
        self.integrate(inner)
        self.assertEqual((self.stand_in(edge), self.stand_in(inner)), ([], []))
        self.manager.unload(far)                                          # three rows free up
        self.tick()
        self.assertEqual(len(self.stand_in(inner)), min(self.plan_size(inner), 3))
        self.assertEqual(self.stand_in(edge), [], "one chunk a tick, the nearest first")
        self.tick()
        self.assertEqual(len(self.stand_in(edge)), min(self.plan_size(edge), 3 - len(self.stand_in(inner))))


class LedgerTests(QuotaFixture):
    async def test_late_fills_never_double_keep_the_respawn_clock_and_bring_evicted_creatures_back(self):
        self.control()
        coords = self.empty_store()
        far = self.pick(coords, lambda d: d >= 3, need=3)
        inner = self.pick(coords, lambda d: d <= 1, need=3)
        self.quota(3)
        self.integrate(far)
        self.integrate(inner)
        clock = dict(self.store.populated)
        self.tick(3)
        evicted = {r["uid"]: r for r in self.store.records.get(far, [])}
        self.assertTrue(evicted)
        ages = {uid: r["cols"][cfg.A_AGE] for uid, r in evicted.items()}
        self.assertEqual(self.store.populated, clock, "a late fill does not move the respawn clock")
        self.manager.unload(inner)                                        # the inner chunk is stored: rows free up for far again
        for _ in range(40):
            self.tick()
            self.assert_no_doubles()
        back = set(evicted) & self.uids()
        self.assertEqual(back, set(evicted), "the evicted creatures come back to their chunk")
        self.assertEqual(self.store.counters["restored_late"], len(evicted))
        for slot in self.stand_in(far):
            uid = self.engine._entity_uid_by_slot[slot]
            if uid in ages:
                self.assertGreater(float(self.engine.state.m_tensor[slot, cfg.A_AGE]), ages[uid], "the store's catch-up aged them")
        self.assertEqual(self.store.populated, clock)

    async def test_killed_creatures_are_not_filled_late(self):
        self.control()
        coords = self.empty_store()
        inner = self.pick(coords, lambda d: d <= 1, need=2)
        self.quota(96)
        self.integrate(inner)
        slots = self.stand_in(inner)
        self.assertTrue(slots)
        killed = self.engine._entity_uid_by_slot[slots[0]]
        self.manager.allocator.release([slots[0]])
        self.tick(10)
        self.assertNotIn(killed, self.uids(), "only the creatures the quota left out are filled late, never the killed ones")
        self.assertEqual(self.store.counters["populated_late"], 0)
        del coords


class NoPlayerTests(QuotaFixture):
    """No controlled actor: the R66-QUOTA-2 branches never run, so headless worlds and B's balance runs are unchanged."""

    async def test_with_no_controlled_actor_the_quota_behaves_as_before(self):
        self.assertEqual(self.manager.controlled_actors(), [])
        coords = self.empty_store()
        self.quota(3)
        for coord in coords:
            self.integrate(coord)
        self.assertEqual(len(self.creature_slots()), 3)
        self.assertGreater(self.store.counters["skipped_quota"], 0)
        before = self.uids()
        for _ in range(60):
            self.tick()
        self.assertEqual(self.uids(), before, "nothing is filled late and nothing is evicted")
        for name in NEW_COUNTERS:
            self.assertEqual(self.store.counters[name], 0, name)
        self.assertEqual(self.store.skipped, {})

    async def test_with_no_controlled_actor_the_first_chunks_keep_their_rows(self):
        coords = self.empty_store()
        self.quota(3)
        first = self.pick(coords, lambda d: d >= 3, need=3)
        later = self.pick(coords, lambda d: d <= 1, need=1)
        self.integrate(first)
        held = set(self.stand_in(first))
        self.integrate(later)
        self.tick(20)
        self.assertEqual(set(self.stand_in(first)), held)
        self.assertEqual(self.stand_in(later), [])


if __name__ == "__main__":
    unittest.main()
