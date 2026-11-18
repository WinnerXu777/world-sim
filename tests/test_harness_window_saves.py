"""1008 WS-D P5 (e): world format 3 under EDEN_WINDOW=1. A save holds the window (origin, epoch, integrated chunks with rows, ids, boxes and generated
values, the chunk deltas, the rows the window owns); restoring it continues exactly as the uninterrupted run would, including a save taken in the tick of a
re-base; a save of another format, seed or generator version is refused before anything changes."""
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import ON, WindowFixture  # noqa: E402
from authored_village import load_village_maps  # noqa: E402
import genesis_config as cfg  # noqa: E402
import map_geo  # noqa: E402
from harness import window, window_manager  # noqa: E402
from persistence import codec, world_snapshot  # noqa: E402
from systems.movement import map_contract  # noqa: E402
from systems.worldgen import GENERATOR_VERSION  # noqa: E402
from systems.worldgen.rings import ChunkCoord  # noqa: E402
from test_startup_preservation import backend  # noqa: E402

TEXT_12_WITH_WINDOW = ("This save was made before the streaming world existed (world format 1 or 2), in which the whole map was one fixed area. "
                       "This session runs the streaming world (world format 3, EDEN_WINDOW=1), so the save cannot be continued. Start a new world, "
                       "or start the game without EDEN_WINDOW=1 to continue the save. The save file has not been changed.")
TEXT_3_WITHOUT_WINDOW = ("This save was made with the streaming world (world format 3, EDEN_WINDOW=1), but this session runs without it, so it cannot "
                         "be continued. Start the game with EDEN_WINDOW=1 and EDEN_SPACES=1 to continue it. The save file has not been changed.")


class SaveFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        map_contract.clear_map_contracts()
        self.addCleanup(map_contract.clear_map_contracts)
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}):
            load_village_maps()
        self.engine._map_name = "starter_village"
        self.addCleanup(setattr, self.engine, "_map_name", "unknown")
        self.manager._set_primary_shift(0.0, 0.0)
        map_geo.configure_pockets(window.POCKET_ORIGINS)

    def payload(self):
        return codec.loads(world_snapshot.capture(self.engine, map_geo))

    def restore(self, payload):
        world_snapshot.restore(payload, self.engine, map_geo, backend.ar.PlayerControlRuntime)

    def state(self):
        e, m = self.engine, self.manager
        return {"h": e.state.h_tensor.clone(), "m": e.state.m_tensor.clone(), "uids": list(e._entity_uid_by_slot), "origin": m.frame.origin, "epoch": m.epoch,
                "chunks": {c: (s.slots, s.uids, s.sha256, s.baseline, s.boxes) for c, s in m.chunks.items()}, "deltas": copy.deepcopy(m.deltas),
                "owned": set(m.allocator.owned), "tiles": dict(map_geo.TILE_TO_ENTITY),
                "shapes": {k: {a: b for a, b in v.items() if a != "tile_box"} for k, v in map_geo.MAP_GEO.items()},
                "boxes": copy.deepcopy(e._window_contract["boxes"]), "shift": list(map_contract.MAP_CONTRACTS["starter_village"].get("window_shift", [0.0, 0.0]))}


class FormatTests(SaveFixture):
    async def test_refusal_texts_are_the_approved_ones_verbatim(self):
        self.assertEqual(world_snapshot.REFUSAL_FORMAT_12_WITH_WINDOW, TEXT_12_WITH_WINDOW)
        self.assertEqual(world_snapshot.REFUSAL_FORMAT_3_WITHOUT_WINDOW, TEXT_3_WITHOUT_WINDOW)

    async def test_the_session_format_and_the_capture(self):
        self.assertEqual(world_snapshot.current_format(), 3)
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "0"}):
            self.assertEqual(world_snapshot.current_format(), 2)
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        payload = self.payload()
        self.assertEqual(payload["schema"], 3)
        fmt = payload["world_format"]
        self.assertEqual((fmt["format"], fmt["generator_version"], fmt["world_seed"], fmt["origin"], fmt["epoch"]), (3, GENERATOR_VERSION, "1008", [0, 0], 0))
        self.assertEqual([s["origin"] for s in fmt["spaces"][1:]], [[1792.0, -2048.0], [1792.0, -1792.0], [1792.0, -1536.0]])
        self.assertEqual(len(payload["window"]["chunks"]), 25)
        self.assertEqual(sorted(payload["window"]["owned"]), sorted(self.manager.allocator.owned))
        self.assertIn("frame", payload["geometry"])
        self.assertIn("pockets", payload["geometry"]["frame"])

    async def test_other_formats_seed_and_generator_are_refused_before_anything_changes(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        good = self.payload()
        before = self.state()
        for schema in (1, 2):
            bad = {**good, "schema": schema}
            with self.assertRaises(world_snapshot.SaveFormatError) as caught:
                world_snapshot.validate(bad, self.engine)
            self.assertEqual(str(caught.exception), TEXT_12_WITH_WINDOW)
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "0"}):
            with self.assertRaises(world_snapshot.SaveFormatError) as caught:
                world_snapshot.validate(good, self.engine)
            self.assertEqual(str(caught.exception), TEXT_3_WITHOUT_WINDOW)
        for key, value, needle in (("world_seed", "7", "world seed"), ("generator_version", "9.9.9", "generator version")):
            bad = {**good, "world_format": {**good["world_format"], key: value}}
            with self.assertRaises(ValueError) as caught:
                world_snapshot.validate(bad, self.engine)
            self.assertIn(needle, str(caught.exception))
        bad = {**good, "window": {**good["window"], "owned": []}}
        with self.assertRaises(ValueError):
            world_snapshot.validate(bad, self.engine)
        broken = copy.deepcopy(good)
        broken["window"]["chunks"][0]["uids"][0] = "someone:else"
        with self.assertRaises(ValueError):
            world_snapshot.validate(broken, self.engine)
        after = self.state()
        self.assertTrue(torch.equal(before["m"], after["m"]) and before["owned"] == after["owned"])


class RoundTripTests(SaveFixture):
    def script(self, ticks, rebase_at=None):
        for t in range(ticks):
            self.engine.tick += 1
            self.engine.state.h_tensor[0, cfg.X] += 4.0
            self.manager.tick()

    async def test_restore_gives_back_the_window_and_the_run_continues_identically(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        coord = ChunkCoord(2, 2)
        state = self.manager.chunks[coord]
        self.engine.state.m_tensor[state.slots[1], cfg.M_TYPE] = 0.0          # the game destroys one row
        self.engine.state.m_tensor[state.slots[0], cfg.HP] = 40.0
        self.manager.unload(coord)                                           # its delta is stored
        self.assertIn(coord, self.manager.deltas)
        self.engine.state.h_tensor[0, cfg.X] = 3 * 256 + 100.0                # past REBASE_AT: the next tick re-bases
        self.run_ticks(1)
        self.assertEqual(self.manager.frame.origin, (3, 2))
        saved = self.payload()                                                # saved in the tick of the re-base
        saved_state = self.state()
        self.script(60)
        uninterrupted = self.state()
        self.restore(codec.loads(codec.dumps(saved)))
        self.assertIsNot(self.engine._window, self.manager)
        self.manager = self.engine._window
        restored = self.state()
        for key in ("h", "m"):
            self.assertTrue(torch.equal(saved_state[key], restored[key]), key)
        for key in ("uids", "origin", "epoch", "chunks", "owned", "tiles", "shapes", "boxes", "shift"):
            self.assertEqual(saved_state[key], restored[key], key)
        self.assertEqual(saved_state["deltas"], restored["deltas"])
        self.assertEqual(restored["shift"], [-768.0, -512.0])
        self.assertEqual(self.engine._window_epoch, 1)
        self.script(60)
        again = self.state()
        for key in ("h", "m"):
            self.assertTrue(torch.equal(uninterrupted[key], again[key]), key)
        for key in ("uids", "origin", "epoch", "chunks", "owned", "tiles", "shapes", "boxes", "shift", "deltas"):
            self.assertEqual(uninterrupted[key], again[key], key)

    async def test_the_primary_map_is_brought_to_the_saved_shift_in_a_fresh_registration(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(3)
        self.manager.rebase((2, 1))
        saved = self.payload()
        bounds_at_save = list(map_contract.MAP_CONTRACTS["starter_village"]["bounds"])
        map_contract.clear_map_contracts()                                    # a new process: the village is registered where its file says
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}):
            load_village_maps()
        self.assertNotEqual(map_contract.MAP_CONTRACTS["starter_village"]["bounds"], bounds_at_save)
        self.restore(codec.loads(codec.dumps(saved)))
        self.assertEqual(map_contract.MAP_CONTRACTS["starter_village"]["bounds"], bounds_at_save)
        self.assertEqual(self.engine._window.frame.origin, (2, 1))


if __name__ == "__main__":
    unittest.main()
