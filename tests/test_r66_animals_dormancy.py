"""R6.6 (animals c2 with the dormancy test for ANIMAL_TYPES; the ``window.integrated`` wire lag), 1119: characterisation of code that exists.

Creatures (``EDEN_CREATURES``, ``harness/creature_store.py``) and interim dormancy (``EDEN_WINDOW_DORMANCY``, ``harness/dormancy.py``) were each tested alone;
these tests run them together, in the order ``Engine.step`` runs them (refresh -> freeze -> step hooks incl. the window hook -> thaw):

* a creature standing outside every integrated chunk is frozen bit for bit until the wanderer sweep stores it, and ``thaw`` does not write it back into the released row;
* walking away and back returns the same creatures once, and no creature in an integrated chunk is dormant;
* the dormancy wake catch-up is for humans only (stored creatures get the store's own catch-up);
* with creatures off no creature row exists and nothing animal is dormant;
* an integrated-set change that adds no rows does not force a map refresh: it reaches ``window.integrated`` at the next periodic rebuild (``MAP_DELTA_EVERY``).
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
from test_harness_creature_store import CreatureFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import creature_store, dormancy  # noqa: E402
from systems.creatures import table  # noqa: E402
from systems.worldgen.rings import ChunkCoord  # noqa: E402

SIZE = 256.0
FAR = ChunkCoord(7, 2)          # never integrated around a resident at (520, 520)
CREATURE_IDS = {r["id"] for r in table.CREATURES.values()}


def _clear_dormancy_state(engine):
    for key in ("_dormant_since", "_dormancy_log", "_outside_since"):
        engine.__dict__.pop(key, None)


class CombinedFixture(CreatureFixture):
    """Creatures populated around a resident (CreatureFixture), then interim dormancy switched on."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_WINDOW_DORMANCY": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        _clear_dormancy_state(self.engine)
        self.addCleanup(_clear_dormancy_state, self.engine)
        self.addCleanup(lambda: setattr(self.engine, "_dormant_h", None))
        self.addCleanup(lambda: setattr(self.engine, "_dormant_a", None))

    def step_like_engine(self):
        """One tick in Engine.step's order for these two features: refresh, freeze, the window hook, thaw."""
        self.engine.tick += 1
        dormant_h, dormant_a = dormancy.refresh(self.engine)
        frozen = dormancy.freeze(self.engine, dormant_h, dormant_a)
        self.manager.tick()
        dormancy.thaw(self.engine, frozen)
        return dormant_a

    def to_tick_before_sweep(self):
        """Leave the clock so that the next ``step_like_engine`` is NOT a sweep tick."""
        every = creature_store.SWEEP_EVERY
        while (self.engine.tick + 1) % every == 0 or (self.engine.tick + 2) % every == 0:
            self.engine.tick += 1

    def move_out(self, slot):
        m = self.engine.state.m_tensor
        ox, oy = self.manager.frame.origin
        m[slot, cfg.CX] = (FAR.x - ox) * SIZE + 40.0
        m[slot, cfg.CY] = (FAR.y - oy) * SIZE + 90.0

    def frame_animal_ids(self):
        h, a, _ = self.engine._current_masks()
        self.engine._build_frame_payload(h, a)
        return [row["id"] for row in self.engine._frame_payload["animals"]]


class FrozenUntilSweptTests(CombinedFixture):
    async def test_creature_outside_integrated_set_is_frozen_until_swept(self):
        slots = self.creature_slots()
        self.assertTrue(slots, "the ring holds creatures")
        slot = slots[0]
        uid = self.engine._entity_uid_by_slot[slot]
        self.assertNotIn(FAR, self.manager.chunks)
        self.move_out(slot)
        m = self.engine.state.m_tensor
        self.to_tick_before_sweep()
        self.engine.tick += 1
        dormant_h, dormant_a = dormancy.refresh(self.engine)
        self.assertTrue(bool(dormant_a[slot]), "an animal outside the integrated chunks is dormant at once (no grace for animals)")
        before = m[slot].clone()
        frozen = dormancy.freeze(self.engine, dormant_h, dormant_a)
        m[slot, cfg.CX] += 5.0                                         # a legacy animal loop moved it
        m[slot, cfg.M_HP] -= 3.0                                       # something bit it
        self.manager.tick()                                            # not a sweep tick: it stays a row
        dormancy.thaw(self.engine, frozen)
        self.assertTrue(torch.equal(m[slot], before), "a dormant creature row is bit-identical across the tick")
        self.assertEqual(self.engine._entity_uid_by_slot[slot], uid)
        while (self.engine.tick + 1) % creature_store.SWEEP_EVERY:
            self.step_like_engine()
            self.assertTrue(torch.equal(m[slot], before))
        self.step_like_engine()                                        # the sweep tick: stored and released between freeze and thaw
        self.assertNotIn(uid, self.uids())
        self.assertEqual(float(m[slot, cfg.M_TYPE]), 0.0, "thaw did not write the stored creature back into its released row")
        self.assertNotEqual(self.engine._entity_uid_by_slot[slot], uid)
        self.assertEqual(self.manager.creatures.index[uid], FAR)
        self.assertEqual([r["uid"] for r in self.manager.creatures.records[FAR]], [uid])
        self.assertEqual(self.manager.creatures.records[FAR][0]["offset"], [40.0, 90.0])


class WalkAwayAndBackTests(CombinedFixture):
    def a_chunk_with_creatures(self):
        m = self.engine.state.m_tensor
        for coord in self.manager.chunks:
            bx, by = self.manager._local_origin(coord)
            inside = [s for s in self.creature_slots() if bx <= float(m[s, cfg.CX]) < bx + SIZE and by <= float(m[s, cfg.CY]) < by + SIZE]
            if inside:
                return coord, inside
        self.fail("no chunk of the ring has a creature")

    async def test_no_creature_in_an_integrated_chunk_is_dormant(self):
        for _ in range(creature_store.SWEEP_EVERY + 1):
            dormant_a = self.step_like_engine()
        self.assertTrue(self.creature_slots())
        self.assertEqual(int(dormant_a.sum()), 0, "every creature row stands in an integrated chunk")

    async def test_walk_away_and_back_returns_same_creatures_once(self):
        coord, inside = self.a_chunk_with_creatures()
        before = {self.engine._entity_uid_by_slot[s] for s in inside}
        everyone = self.uids()
        self.manager.unload(coord)
        self.engine.tick += 1
        _, dormant_a = dormancy.refresh(self.engine)                   # no window tick here: the plan would integrate the chunk again at once
        self.assertTrue(before.isdisjoint(self.uids()), "stored, not dormant rows")
        self.assertEqual(int(dormant_a.sum()), 0)
        self.manager.integrate(coord, self.service.peek(coord))
        dormant_a = self.step_like_engine()
        self.assertEqual(self.uids(), everyone, "the same creatures, none doubled by the plan")
        self.assertEqual(int(dormant_a.sum()), 0)
        ids = self.frame_animal_ids()
        self.assertEqual(len(ids), len(set(ids)), "no duplicate animal ids in /frame")
        self.assertTrue(before <= set(ids))


class WakeIsForHumansTests(CombinedFixture):
    async def test_dormancy_wake_does_not_touch_creature_rows(self):
        slot = self.creature_slots()[0]
        uid = self.engine._entity_uid_by_slot[slot]
        m = self.engine.state.m_tensor
        home = (float(m[slot, cfg.CX]), float(m[slot, cfg.CY]))
        self.move_out(slot)
        self.engine.tick += 1
        _, dormant_a = dormancy.refresh(self.engine)
        self.assertTrue(bool(dormant_a[slot]))
        m[slot, cfg.CX], m[slot, cfg.CY] = home                          # back inside before any sweep
        self.engine.tick += 4000
        before = m[slot].clone()
        _, dormant_a = dormancy.refresh(self.engine)
        self.assertFalse(bool(dormant_a[slot]))
        self.assertTrue(torch.equal(m[slot], before), "no dormancy catch-up on an animal row")
        self.assertNotIn(uid, self.engine._dormant_since)
        self.assertFalse([e for e in self.engine._dormancy_log if e[2] == uid])


class FlagCombinationTests(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        _clear_dormancy_state(self.engine)
        self.addCleanup(_clear_dormancy_state, self.engine)
        self.addCleanup(lambda: setattr(self.engine, "_dormant_h", None))
        self.addCleanup(lambda: setattr(self.engine, "_dormant_a", None))
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(30)

    def creature_rows(self):
        m = self.engine.state.m_tensor
        ids = torch.tensor(sorted(float(i) for i in CREATURE_IDS))
        return int(torch.isin(m[:cfg.MAX_ENTITIES, cfg.M_TYPE], ids).sum())

    async def test_dormancy_on_creatures_off_has_no_animal_rows_and_nothing_animal_dormant(self):
        self.assertNotEqual(os.environ.get("EDEN_CREATURES"), "1")
        with mock.patch.dict(os.environ, {"EDEN_WINDOW_DORMANCY": "1"}):
            _, dormant_a = dormancy.refresh(self.engine)
        self.assertEqual(self.creature_rows(), 0)
        self.assertEqual(int(dormant_a.sum()), 0)
        self.assertEqual(self.manager.creatures.counters["populated"], 0)

    async def test_both_off_gives_no_masks(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_WINDOW_DORMANCY", None)
            os.environ.pop("EDEN_CREATURES", None)
            self.assertEqual(dormancy.refresh(self.engine), (None, None))
        self.assertEqual(self.creature_rows(), 0)


class IntegratedWireLagTests(WindowFixture):
    """G2 of the R6.6 plan (ruled: document, no code)."""

    async def test_a_set_change_without_rows_waits_for_the_periodic_rebuild(self):
        self.engine._build_map_delta_payload()
        base = (self.engine._map_state_version, self.engine._map_geo_version_sent)
        self.engine._force_map_refresh = False
        self.manager.chunks = {ChunkCoord(3, -1): SimpleNamespace(boxes=[], sha256="empty")}   # integrated, no rows (open water)
        self.manager._publish()
        self.assertFalse(self.engine._force_map_refresh, "publishing the set does not force a map rebuild")
        self.assertEqual(cfg.MAP_DELTA_EVERY, 20)
        self.engine._build_map_delta_payload()                                                   # the tick % MAP_DELTA_EVERY == 0 rebuild
        delta = self.engine.get_map_delta_for(*base)
        self.assertEqual(delta["window"], {"integrated": ["3:-1"]})
        self.assertEqual(delta["upserts"], [])

    async def test_a_set_change_with_rows_forces_the_rebuild(self):
        self.engine._force_map_refresh = False
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(1)
        self.assertTrue(self.manager.chunks)
        self.assertTrue(self.engine._force_map_refresh, "allocating the chunk's rows forces the rebuild the same tick")


if __name__ == "__main__":
    unittest.main()
