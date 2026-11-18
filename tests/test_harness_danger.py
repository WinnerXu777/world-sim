"""1008 Part 2.A3 (1008_instincts_wiring_gap.md step 4): EDEN_DANGER, the danger ledger on the resident record.

The writer (a hit becomes a ``predator`` or ``hazard`` entry of ``memory.last_threats``), the readers, the re-base (an entry keeps its absolute place), the flag combinations and the
registration. Uses the engine's real ``ResidentAgentStore`` so the entries have exactly the shape the model plane reads."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import danger, engine_hooks, wounds  # noqa: E402
from systems.creatures import table  # noqa: E402


class DangerFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_DANGER": "1", "EDEN_WOUNDS": "1", "EDEN_CREATURES": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        engine = self.engine
        self.addCleanup(lambda: [engine.__dict__.pop(k, None) for k in ("_wounds", "_wound_hp")])
        self.addCleanup(setattr, engine, "_queue_event", engine._queue_event)
        engine._queue_event = lambda *a, **k: None
        danger.install()
        self.addCleanup(danger.uninstall)
        engine.tick = 1000
        self.uid = "h0"
        self.place_human(0, 520.0, 520.0)
        engine.state.h_tensor[0, cfg.HP] = 100.0
        engine.state.h_tensor[0, cfg.H_SEX] = 1.0
        engine._human_uid_by_slot[0] = self.uid
        self.addCleanup(engine._human_uid_by_slot.__setitem__, 0, None)
        engine.resident_store.ensure_resident(self.uid, 0, engine.state.h_tensor, engine.tick)
        self.addCleanup(lambda: engine.resident_store._cache.pop(self.uid, None))

    def creature(self, species, x, y, hp=50.0):
        row = table.CREATURES[species]
        (slot,) = self.manager.allocator.allocate([f"c2_2:fauna:{species}9"], [row["id"]], [x], [y], {cfg.M_HP: [hp], cfg.SCALE: [4.0]})
        self.manager.allocator.owned.discard(slot)
        return slot

    def bite(self, damage=15.0):
        wounds.step(self.engine)                                        # baseline
        self.engine.state.h_tensor[0, cfg.HP] -= damage
        self.engine.tick += 1
        wounds.step(self.engine)

    def threats(self):
        return self.engine.resident_store.get(self.uid)["memory"]["last_threats"]


class WriterTests(DangerFixture):
    async def test_a_bite_by_a_nearby_hostile_creature_is_remembered_where_the_creature_stood(self):
        self.creature("skeleton", 540.0, 520.0)
        self.bite()
        (entry,) = self.threats()
        self.assertEqual(entry["kind"], "predator")
        self.assertEqual((entry["x"], entry["y"]), (540.0, 520.0))
        self.assertAlmostEqual(entry["distance"], 20.0)
        self.assertEqual(entry["tick"], 1001)

    async def test_a_hit_with_no_creature_near_is_a_hazard_at_the_residents_own_place(self):
        self.creature("skeleton", 900.0, 900.0)
        self.bite()
        (entry,) = self.threats()
        self.assertEqual((entry["kind"], entry["x"], entry["y"]), ("hazard", 520.0, 520.0))

    async def test_a_friendly_creature_is_never_the_source(self):
        self.creature("rabbit", 525.0, 520.0)
        self.bite()
        self.assertEqual(self.threats()[0]["kind"], "hazard")

    async def test_the_bleed_is_kept_only_with_the_wounds_flag(self):
        self.creature("skeleton", 540.0, 520.0)
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_WOUNDS")
            self.bite()
        self.assertEqual(wounds.bleed_of(self.engine, self.uid), 0.0)
        self.assertEqual(len(self.threats()), 1, "the place is remembered all the same")

    async def test_a_resident_without_a_record_is_skipped_quietly(self):
        self.engine.resident_store._cache.pop(self.uid)
        self.assertIsNone(danger.remember(self.engine, 0, self.uid, 10.0))


class ReaderTests(DangerFixture):
    async def test_places_near_danger_and_pressure(self):
        self.creature("skeleton", 540.0, 520.0)
        self.bite()
        self.assertEqual(len(danger.places(self.engine, self.uid)), 1)
        self.assertTrue(danger.near_danger(self.engine, self.uid, 545.0, 520.0))
        self.assertFalse(danger.near_danger(self.engine, self.uid, 700.0, 520.0))
        close, far = danger.danger_pressure(self.engine, self.uid, 540.0, 520.0), danger.danger_pressure(self.engine, self.uid, 580.0, 520.0)
        self.assertGreater(close, far)
        self.assertGreater(far, 0.0)
        self.assertEqual(danger.danger_pressure(self.engine, self.uid, 900.0, 520.0), 0.0)
        self.assertEqual(danger.places(self.engine, "nobody"), [])

    async def test_an_expired_entry_is_not_a_place(self):
        self.creature("skeleton", 540.0, 520.0)
        self.bite()
        self.threats()[0]["expires_tick"] = self.engine.tick - 1
        self.assertEqual(danger.places(self.engine, self.uid), [])


class RebaseTests(DangerFixture):
    async def test_a_place_keeps_its_absolute_position_when_the_window_rebases(self):
        self.creature("skeleton", 540.0, 520.0)
        self.run_ticks(2)
        self.bite()
        ox, oy = self.manager.frame.origin
        (entry,) = self.threats()
        absolute = (entry["x"] + ox * 256.0, entry["y"] + oy * 256.0)
        self.manager.rebase((ox + 1, oy + 2))
        nx, ny = self.manager.frame.origin
        (entry,) = self.threats()
        self.assertEqual((entry["x"] + nx * 256.0, entry["y"] + ny * 256.0), absolute)
        self.assertEqual((entry["x"], entry["y"]), (540.0 - 256.0, 520.0 - 512.0))


class RegistrationTests(DangerFixture):
    async def test_the_boot_subscribes_the_writer_and_installs_the_detector_for_either_flag(self):
        from simulation.dispatch import DISPATCH
        self.addCleanup(engine_hooks.uninstall, DISPATCH)
        for flags in ({"EDEN_DANGER": "1"}, {"EDEN_WOUNDS": "1"}):
            with mock.patch.dict(os.environ, flags, clear=False):
                for name in ("EDEN_DANGER", "EDEN_WOUNDS"):
                    if name not in flags:
                        os.environ.pop(name, None)
                engine_hooks.uninstall(DISPATCH)
                engine_hooks.install(DISPATCH)
                self.assertIn("harness_wounds", {n for n, _ in DISPATCH.post_step_hooks}, flags)
                self.assertEqual(danger._INSTALLED["callback"] is not None, "EDEN_DANGER" in flags)
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_DANGER")
            os.environ.pop("EDEN_WOUNDS")
            engine_hooks.uninstall(DISPATCH)
            engine_hooks.install(DISPATCH)
            self.assertNotIn("harness_wounds", {n for n, _ in DISPATCH.post_step_hooks})
            self.assertIsNone(danger._INSTALLED["callback"])


if __name__ == "__main__":
    unittest.main()
