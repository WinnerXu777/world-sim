"""1008 calendar C4 (1008_calendar_gap.md section 6, client contract 5c): flag off, the wire has exactly its old key set; flag on, ``/bootstrap`` ``world`` gains ``calendar`` and
every ``/frame`` gains ``time`` (tick, day, day_phase, block, season, season_phase, year, light), and the existing ``ticks_per_year`` and ``year`` carry the long calendar."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from test_map_portals import real_world  # noqa: E402
from harness import calendar, calendar_wire  # noqa: E402

CALENDAR_KEYS = {"enabled", "profile", "day_ticks", "year_ticks", "days_per_year", "season_ticks", "daylight", "ticks_per_second", "life_year_ticks"}
TIME_KEYS = {"tick", "day", "day_phase", "block", "season", "season_phase", "year", "light"}


class WireFixture(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def world(self, on):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ("EDEN_WINDOW", "EDEN_SPACES", "EDEN_PERCEPTION_BOUNDED", "EDEN_MAP_RESOURCES", "EDEN_CALENDAR"):
            os.environ.pop(key, None)
        if on:
            os.environ["EDEN_CALENDAR"] = "1"
        return await real_world()

    def frames(self, engine):
        h_mask, a_mask, _ = engine._current_masks()
        engine._build_frame_payload(h_mask, a_mask)
        return engine._frame_payload, engine._empty_frame_payload()


class FlagOffTests(WireFixture):
    async def test_no_calendar_key_anywhere(self):
        engine = await self.world(False)
        self.assertEqual((calendar_wire.world_block(engine), calendar_wire.time_block(engine)), ({}, {}))
        for payload in self.frames(engine):
            self.assertNotIn("time", payload)
        self.assertNotIn("calendar", engine._world_payload())
        self.assertNotIn("calendar", json.loads((await backend.bootstrap()).body)["world"])
        self.assertEqual(engine._world_payload()["ticks_per_year"], 600)


class FlagOnTests(WireFixture):
    async def test_bootstrap_world_carries_the_calendar(self):
        engine = await self.world(True)
        world = json.loads((await backend.bootstrap()).body)["world"]
        self.assertEqual(set(world["calendar"]), CALENDAR_KEYS)
        facts = world["calendar"]
        self.assertEqual((facts["enabled"], facts["profile"], facts["day_ticks"], facts["year_ticks"], facts["days_per_year"], facts["ticks_per_second"]),
                         (True, "user", 12000, 96000, 8.0, 20))
        self.assertEqual(set(facts["daylight"]), set(calendar.SEASONS))
        self.assertEqual(world["ticks_per_year"], 96000, "the existing key carries the long year")

    async def test_every_frame_carries_the_time_block(self):
        engine = await self.world(True)
        engine.tick = 12000 * 3 + 3480                                          # solar noon of day 3 (sun up for 0.58 of a summer day) (the third day of summer: spring is the first 24000 ticks)
        for payload in self.frames(engine):
            self.assertEqual(set(payload["time"]), TIME_KEYS)
            time = payload["time"]
            self.assertEqual((time["tick"], time["day"], time["day_phase"], time["season"], time["year"]), (engine.tick, 3, 0.29, "summer", 0))
            self.assertEqual(time["block"], "day")
            self.assertGreater(time["light"], 0.9)
            self.assertEqual(payload["year"], round(engine.tick / 96000, 2))

    async def test_the_block_follows_the_calendar_through_a_day_and_a_year(self):
        engine = await self.world(True)
        seen = {}
        for tick, season in ((0, "spring"), (30 * 3000, "summer"), (60 * 3000 + 12000 * 5, "autumn"), (96000 - 100, "winter")):
            engine.tick = tick
            block = calendar_wire.time_block(engine)["time"]
            self.assertEqual(block["season"], calendar.season_for_tick(tick))
            seen[tick] = block
        self.assertEqual(seen[0]["block"], "dawn")
        self.assertEqual(seen[96000 - 100]["block"], "night")
        self.assertLess(seen[96000 - 100]["light"], 0.1)
        self.assertEqual(seen[96000 - 100]["year"], 0)
        engine.tick = 96000
        self.assertEqual(calendar_wire.time_block(engine)["time"]["year"], 1)


if __name__ == "__main__":
    unittest.main()
