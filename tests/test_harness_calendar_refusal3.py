"""R0.4: a checkpoint can continue only with the long calendar that made it."""
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

from test_harness_window_saves import SaveFixture, backend

import map_geo
from harness import calendar
from persistence import world_snapshot
from persistence.sessions import GameSessions


REFUSAL_TEXT = (
    "This save was made with a long calendar whose game day is {saved_day} ticks and whose year is {saved_year} ticks, "
    "but this session's long calendar has a game day of {now_day} ticks and a year of {now_year} ticks, so hunger, growth, weather and ageing "
    "would run at different rates and the save cannot be continued. Use the build the save was made with, or start a new world. "
    "The save file has not been changed."
)


class CalendarRefusalTests(SaveFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        flags = mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"})
        flags.start()
        self.addCleanup(flags.stop)
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.sessions = GameSessions(self.engine, map_geo, backend.ar.PlayerControlRuntime, root, create_world=None, seed=1008)
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(1)
        self.saved_tick = self.engine.tick
        self.save_id = "a" * 32
        entry = self.sessions.store.commit(
            self.save_id, "Long calendar", self.saved_tick, world_snapshot.capture(self.engine, map_geo), world_snapshot.current_format()
        )
        directory = self.sessions.store.directory(self.save_id)
        self.save_path = directory / f"{entry['id']}.json.gz"
        self.manifest_path = directory / "manifest.json"

    async def test_different_long_calendar_refuses_without_changing_the_save(self):
        before = self.save_path.read_bytes()
        manifest_before = self.manifest_path.read_bytes()
        different = replace(calendar.USER, day_ticks=6000, year_ticks=48000, life_year_ticks=6000.0)
        with mock.patch.object(calendar, "USER", different):
            with self.assertRaises(world_snapshot.SaveFormatError) as caught:
                await self.sessions.continue_world(self.save_id)
        self.assertEqual(str(caught.exception), REFUSAL_TEXT.format(saved_day=12000, saved_year=96000, now_day=6000, now_year=48000))
        self.assertEqual(self.save_path.read_bytes(), before)
        self.assertEqual(self.manifest_path.read_bytes(), manifest_before)

    async def test_same_long_calendar_loads(self):
        self.engine.tick += 1
        result = await self.sessions.continue_world(self.save_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["active_save_id"], self.save_id)
        self.assertEqual(self.engine.tick, self.saved_tick)
