"""Calendar override saves retain state and reject incompatible loads."""
import os
import unittest
from unittest import mock

from test_startup_preservation import backend
from harness import calendar
from persistence import codec, world_snapshot


class CalendarOverrideSaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.flags = mock.patch.dict(os.environ, {"EDEN_GOD_NEW_TOOLS": "1"})
        self.flags.start()
        backend.engine.reset_world()
        backend.engine._god_calendar_overrides = {}
        await backend.create_genesis(backend.engine, map_name="render_test_village")

    async def asyncTearDown(self):
        backend.engine._god_calendar_overrides = {}
        self.flags.stop()

    def capture(self):
        return codec.loads(world_snapshot.capture(backend.engine, backend.map_geo))

    def restore(self, payload):
        world_snapshot.restore(payload, backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime)

    async def test_round_trip_both_overrides(self):
        calendar.set_override(backend.engine, "season", "winter")
        calendar.set_override(backend.engine, "time", "night")
        saved = self.capture()
        calendar.set_override(backend.engine, "season", "summer")
        calendar.set_override(backend.engine, "time", None)
        self.restore(saved)
        view = calendar.for_world(backend.engine)
        self.assertEqual((view.season_for_tick(0), view.block_for_tick(0)), ("winter", "night"))
        self.assertIs(backend.engine.resident_store._god_calendar_owner, backend.engine)

    async def test_missing_key_clears_previous_world_overrides(self):
        saved = self.capture()
        self.assertNotIn("calendar_overrides", saved)
        calendar.set_override(backend.engine, "season", "winter")
        self.restore(saved)
        self.assertIsNone(calendar.for_world(backend.engine).season_override)

    async def test_flag_off_refuses_before_mutation(self):
        calendar.set_override(backend.engine, "time", "dusk")
        saved = self.capture()
        epoch = backend.engine.world_epoch
        with mock.patch.dict(os.environ, {"EDEN_GOD_NEW_TOOLS": "0"}):
            with self.assertRaises(world_snapshot.SaveFormatError):
                self.restore(saved)
        self.assertEqual(epoch, backend.engine.world_epoch)

    async def test_bad_sections_are_rejected_before_mutation(self):
        saved = self.capture()
        epoch = backend.engine.world_epoch
        for bad in ({}, {"season": "fog"}, {"time": None}, {"time": "day", "other": "night"}, []):
            saved["calendar_overrides"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.restore(saved)
            self.assertEqual(epoch, backend.engine.world_epoch)

    async def test_flag_off_ignores_stale_override_for_byte_identity(self):
        with mock.patch.dict(os.environ, {"EDEN_GOD_NEW_TOOLS": "0"}):
            backend.engine._god_calendar_overrides = {}
            baseline = world_snapshot.capture(backend.engine, backend.map_geo)
            backend.engine._god_calendar_overrides = {"season": "winter"}
            actual = world_snapshot.capture(backend.engine, backend.map_geo)
        self.assertEqual(baseline, actual)
