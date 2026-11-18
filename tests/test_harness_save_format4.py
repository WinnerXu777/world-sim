"""1008 USER-DEC-6: world format 4 (the dormant structure store is saved, only when something is stored) and the optional ``calendar`` key of the world format (only under
EDEN_CALENDAR=1), with their approved refusal texts.

Format 4 = format 3 plus ``window["structures"]``: an empty store saves as format 3, byte for byte as before; a non-empty one round-trips (the structure comes back with
its uid and row values, at its chunk-relative position, also when the window was re-based between the save and the load); a session that cannot load it (store flag off,
or no window) refuses with the approved text before anything changes; a malformed section is refused. The calendar key makes a long-calendar save refuse in a session
without EDEN_CALENDAR and a short-calendar save refuse in a session with it."""
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_saves import SaveFixture  # noqa: E402
from test_harness_structure_store import COORD, UID  # noqa: E402
import genesis_config as cfg  # noqa: E402
import map_geo  # noqa: E402
from harness import structure_store as store  # noqa: E402
from instincts_and_tools import entity_born  # noqa: E402
from persistence import codec, world_snapshot  # noqa: E402

TEXT_4 = ("This save contains buildings stored away from the player (the dormant structure store), which this build cannot load, so it cannot be continued. "
          "Use a build with EDEN_STRUCTURE_STORE support, or start a new world. The save file has not been changed.")
TEXT_CAL_LONG = ("This save was made with the long calendar (a game day is 12000 ticks, EDEN_CALENDAR=1), but this session runs without it, so it cannot be continued. "
                 "Start the game with EDEN_CALENDAR=1 to continue it. The save file has not been changed.")
TEXT_CAL_SHORT = ("This save was made with the original short calendar (a game day is 2400 ticks), whose hunger, growth, weather and ageing rates differ from the long "
                  "calendar (EDEN_CALENDAR=1), so it cannot be continued in this session. Start a new world, or start the game without EDEN_CALENDAR=1 to continue the save. "
                  "The save file has not been changed.")


class FormatFourFixture(SaveFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_STRUCTURE_STORE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("EDEN_CALENDAR", None)          # R0.6: the session is the short calendar unless a case sets EDEN_CALENDAR=1 itself
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(30)
        self.assertIn(COORD, self.manager.chunks)

    def build(self, uid=UID, x=800.0, y=800.0):
        engine = self.engine
        slot = entity_born(engine.state.m_tensor, engine._entity_count_ref, x, y, cfg.M_HOUSE, hp=100.0, scale=20.0, register_geo=True,
                           col_vals={cfg.S_DURABILITY: 80.0, cfg.S_SHELTER_CAP: 4.0, cfg.S_BUILD_PROGRESS: 100.0})
        engine._entity_uid_by_slot[slot] = uid
        return slot

    def stored_payload(self):
        self.build()
        self.manager.unload(COORD)
        self.assertEqual(self.manager.structures.count(), 1)
        return self.payload()

    def row_of(self, uid):
        """The row without the generation column (the slot's own counter, which a stash/restore cycle advances by design)."""
        row = self.engine.state.m_tensor[self.engine._entity_uid_by_slot.index(uid)].tolist()
        row[cfg.M_GEN] = 0.0
        return row


class FormatFourTests(FormatFourFixture):
    async def test_refusal_text_is_the_approved_one_verbatim(self):
        self.assertEqual(world_snapshot.REFUSAL_FORMAT_4_UNSUPPORTED, TEXT_4)

    async def test_an_empty_store_saves_as_format_3_exactly_as_before(self):
        payload = self.payload()
        self.assertEqual(payload["schema"], 3)
        self.assertEqual(payload["world_format"]["format"], 3)
        self.assertNotIn("structures", payload["window"])
        self.assertNotIn("calendar", payload["world_format"])

    async def test_a_store_with_structures_saves_as_format_4(self):
        payload = self.stored_payload()
        self.assertEqual(payload["schema"], 4)
        self.assertEqual(payload["world_format"]["format"], 4)
        (entry,) = payload["window"]["structures"]
        self.assertEqual(entry[:2], [COORD.x, COORD.y])
        (record,) = entry[2]
        self.assertEqual(record["uid"], UID)
        self.assertEqual(world_snapshot.current_format(), 3, "the session format (listings) stays 3")
        world_snapshot.validate(payload, self.engine)

    async def test_round_trip_gives_the_structure_back_at_its_position(self):
        self.build()
        before = self.row_of(UID)
        self.manager.unload(COORD)
        saved = self.payload()
        self.manager.integrate(COORD, self.service.peek(COORD))               # the uninterrupted run
        uninterrupted = self.row_of(UID)
        self.assertEqual(uninterrupted, before)
        self.manager.unload(COORD)
        self.restore(codec.loads(codec.dumps(saved)))
        self.manager = self.engine._window
        self.assertEqual(self.manager.structures.count(), 1)
        self.assertNotIn(UID, self.engine._entity_uid_by_slot)
        self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertEqual(self.row_of(UID), before, "same uid, same row values, same position")
        self.assertEqual(self.manager.structures.count(), 0)
        self.assertIn(self.engine._entity_uid_by_slot.index(UID), map_geo.MAP_GEO, "its geometry came back with it")

    async def test_a_rebase_between_the_save_and_the_load_changes_nothing(self):
        self.build()
        before = self.row_of(UID)
        self.manager.unload(COORD)
        saved = codec.loads(codec.dumps(self.payload()))
        self.manager.rebase((2, 1))                                           # the live window moves; the save keeps the old frame
        self.restore(saved)
        self.manager = self.engine._window
        self.assertEqual(self.manager.frame.origin, (0, 0))
        self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertEqual(self.row_of(UID), before)

    async def test_a_save_made_after_a_rebase_restores_into_the_same_frame(self):
        self.manager.rebase((2, 1))
        self.build(x=800.0 - 512.0, y=800.0 - 256.0)                         # the same world spot in the new frame
        before = self.row_of(UID)
        self.manager.unload(COORD)
        saved = codec.loads(codec.dumps(self.payload()))
        self.restore(saved)
        self.manager = self.engine._window
        self.assertEqual(self.manager.frame.origin, (2, 1))
        self.manager.integrate(COORD, self.service.peek(COORD))
        self.assertEqual(self.row_of(UID), before)


class FormatFourRefusalTests(FormatFourFixture):
    async def test_a_session_without_the_store_refuses_with_the_approved_text(self):
        payload = self.stored_payload()
        before = self.engine.state.m_tensor.clone()
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_STRUCTURE_STORE")
            with self.assertRaises(world_snapshot.SaveFormatError) as caught:
                world_snapshot.validate(payload, self.engine)
            self.assertEqual(str(caught.exception), TEXT_4)
            with self.assertRaises(world_snapshot.SaveFormatError):
                self.restore(payload)
        self.assertTrue(torch.equal(before, self.engine.state.m_tensor), "nothing changed")

    async def test_a_session_without_the_window_refuses_with_the_window_text(self):
        payload = self.stored_payload()
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "0"}):
            with self.assertRaises(world_snapshot.SaveFormatError) as caught:
                world_snapshot.validate(payload, self.engine)
            self.assertEqual(str(caught.exception), world_snapshot.REFUSAL_FORMAT_3_WITHOUT_WINDOW)

    async def test_a_malformed_structures_section_is_refused(self):
        good = self.stored_payload()
        record = lambda p: p["window"]["structures"][0][2][0]                 # noqa: E731
        mutations = {
            "missing key": lambda p: record(p).pop("geo"),
            "extra key": lambda p: record(p).update(extra=1),
            "not a structure type": lambda p: record(p).update(type=float(cfg.M_GRASS)),
            "column out of range": lambda p: record(p)["cols"].update({999: 1.0}),
            "non-finite value": lambda p: record(p)["cols"].update({cfg.S_DURABILITY: float("nan")}),
            "offset shape": lambda p: record(p).update(offset=[1.0]),
            "duplicate uid": lambda p: p["window"]["structures"][0][2].append(copy.deepcopy(record(p))),
            "empty chunk entry": lambda p: p["window"]["structures"].append([9, 9, []]),
            "section removed": lambda p: p["window"].pop("structures"),
            "not a list": lambda p: p["window"].update(structures={}),
        }
        for name, mutate in mutations.items():
            bad = copy.deepcopy(good)
            mutate(bad)
            with self.assertRaises(ValueError, msg=name):
                world_snapshot.validate(bad, self.engine)

    async def test_a_format_3_save_may_not_carry_a_structures_section(self):
        good = self.payload()
        bad = copy.deepcopy(good)
        bad["window"]["structures"] = []
        with self.assertRaises(ValueError):
            world_snapshot.validate(bad, self.engine)

    async def test_a_format_3_save_loads_in_a_session_with_the_store_on(self):
        world_snapshot.validate(self.payload(), self.engine)


class CalendarKeyTests(FormatFourFixture):
    async def test_refusal_texts_are_the_approved_ones_verbatim(self):
        self.assertEqual(world_snapshot.REFUSAL_CALENDAR_LONG_WITHOUT, TEXT_CAL_LONG)
        self.assertEqual(world_snapshot.REFUSAL_CALENDAR_SHORT_WITH, TEXT_CAL_SHORT)

    async def test_flag_off_has_no_calendar_key_flag_on_has_the_three_numbers(self):
        self.assertNotIn("calendar", self.payload()["world_format"])
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            payload = self.payload()
            self.assertEqual(payload["world_format"]["calendar"], {"profile": "user", "day_ticks": 12000, "year_ticks": 96000})
            self.assertEqual(payload["schema"], 3, "no format number changes")
            world_snapshot.validate(payload, self.engine)

    async def test_a_long_calendar_save_refuses_in_a_session_without_it(self):
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            long_save = self.payload()
        with self.assertRaises(world_snapshot.SaveFormatError) as caught:
            world_snapshot.validate(long_save, self.engine)
        self.assertEqual(str(caught.exception), TEXT_CAL_LONG)

    async def test_a_short_calendar_save_refuses_in_a_session_with_it(self):
        short_save = self.payload()
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            with self.assertRaises(world_snapshot.SaveFormatError) as caught:
                world_snapshot.validate(short_save, self.engine)
        self.assertEqual(str(caught.exception), TEXT_CAL_SHORT)

    async def test_two_different_long_calendars_refuse_without_the_approved_texts(self):
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            payload = self.payload()
            payload["world_format"]["calendar"]["day_ticks"] = 6000
            with self.assertRaises(ValueError) as caught:
                world_snapshot.validate(payload, self.engine)
            self.assertIsInstance(caught.exception, world_snapshot.SaveFormatError)
            self.assertIn("calendar", str(caught.exception))

    async def test_a_format_1_world_gets_a_world_format_only_under_the_flag(self):
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "0", "EDEN_SPACES": "0"}):
            self.assertEqual(world_snapshot.current_format(), 1)
            self.assertNotIn("world_format", self.payload())
            with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
                payload = self.payload()
                self.assertEqual(payload["world_format"]["format"], 1)
                self.assertEqual(payload["world_format"]["calendar"]["profile"], "user")
                with mock.patch.dict(os.environ):
                    os.environ.pop("EDEN_CALENDAR")
                    with self.assertRaises(world_snapshot.SaveFormatError) as caught:
                        world_snapshot.validate(payload, self.engine)
                    self.assertEqual(str(caught.exception), TEXT_CAL_LONG)

    async def test_format_4_and_the_calendar_key_together(self):
        with mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"}):
            payload = self.stored_payload()
            self.assertEqual((payload["schema"], payload["world_format"]["format"], payload["world_format"]["calendar"]["profile"]), (4, 4, "user"))
            world_snapshot.validate(payload, self.engine)


if __name__ == "__main__":
    unittest.main()
