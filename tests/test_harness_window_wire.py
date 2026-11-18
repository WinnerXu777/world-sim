"""1008 WS-D P5 (f): the wire of the streaming window (client contract section 4). Flag off: every payload has exactly its old key set. Flag on: /frame,
/map_delta and /bootstrap carry window_origin and window_epoch of the positions they hold (stamped when built, so a payload never mixes epochs),
/bootstrap ``world`` gains the infinite-world block, and a request naming an older epoch is answered 409 stale_window_epoch."""
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
import genesis_config as cfg  # noqa: E402
import map_geo  # noqa: E402
from harness import engine_hooks as eh, window_manager, window_wire  # noqa: E402
from simulation.dispatch import DISPATCH  # noqa: E402
from systems.worldgen import GENERATOR_VERSION  # noqa: E402
from systems.worldgen.service import ChunkService  # noqa: E402
from systems.worldgen import PinnedSet, starter_village_area  # noqa: E402

ON = {"EDEN_WINDOW": "1", "EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1", "EDEN_MAP_RESOURCES": "1"}
WINDOW_KEYS = {"window_origin", "window_epoch"}


class Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class WireFixture(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        DISPATCH.clear()

    async def asyncTearDown(self):
        eh.uninstall(DISPATCH)
        DISPATCH.clear()
        map_geo.reset_window()
        await super().asyncTearDown()

    async def world(self, on):
        patcher = mock.patch.dict(os.environ, ON if on else {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        if not on:
            for key in ON:
                os.environ.pop(key, None)
        else:
            map_geo.MAP_GEO.clear(); map_geo.TILE_TO_ENTITY.clear()
            eh.install(DISPATCH)
        engine = await real_world()
        if on:
            service = ChunkService(1008, pinned=PinnedSet([starter_village_area()]), workers=0)
            self.addCleanup(service.close)
            window_manager.WindowManager(engine, service)
            self.addCleanup(lambda: (setattr(engine, "_window", None), setattr(engine, "_window_contract", None)))
        return engine

    def rebuild(self, engine):
        h_mask, a_mask, _ = engine._current_masks()
        engine._build_frame_payload(h_mask, a_mask)
        engine._build_map_delta_payload()


class FlagOffTests(WireFixture):
    async def test_no_window_key_anywhere(self):
        engine = await self.world(False)
        self.rebuild(engine)
        self.assertEqual(window_wire.stamp(engine), {})
        self.assertEqual(window_wire.world_block(engine), {})
        self.assertIsNone(window_wire.stale_epoch(engine, {"window_epoch": 5}))
        for payload in (engine._frame_payload, engine._map_delta_payload, engine.get_map_delta_for(None, None), json.loads((await backend.bootstrap()).body)):
            self.assertFalse(WINDOW_KEYS & set(payload))
        self.assertNotIn("infinite", engine._bootstrap_payload["world"])
        result = json.loads((await backend.human_view_window(Request({"center_x": 100.0, "center_y": 100.0}))).body)
        self.assertFalse(WINDOW_KEYS & set(result))


class FlagOnTests(WireFixture):
    async def test_payloads_carry_the_origin_and_epoch_they_were_built_in(self):
        engine = await self.world(True)
        engine._force_map_refresh = True
        self.rebuild(engine)
        self.assertEqual((engine._frame_payload["window_origin"], engine._frame_payload["window_epoch"]), ([0, 0], 0))
        self.assertEqual((engine._map_delta_payload["window_origin"], engine._map_delta_payload["window_epoch"]), ([0, 0], 0))
        boot = json.loads((await backend.bootstrap()).body)
        self.assertEqual((boot["window_origin"], boot["window_epoch"]), ([0, 0], 0))
        world = boot["world"]
        self.assertTrue(world["infinite"])
        self.assertEqual((world["chunk_tiles"], world["units_per_tile"], world["generator_version"], world["world_seed"]), (32, 8, GENERATOR_VERSION, "1008"))
        self.assertEqual((world["window_origin"], world["window_epoch"]), ([0, 0], 0))
        engine._window.rebase((1, 2))
        self.assertEqual(engine._frame_payload["window_epoch"], 0, "a payload built before the re-base keeps the epoch of its positions")
        self.assertEqual(engine._bootstrap_payload["window_epoch"], 0)
        self.rebuild(engine)
        self.assertEqual((engine._frame_payload["window_origin"], engine._frame_payload["window_epoch"]), ([1, 2], 1))
        self.assertEqual((engine._map_delta_payload["window_origin"], engine._map_delta_payload["window_epoch"]), ([1, 2], 1))
        full = engine.get_map_delta_for(None, None)
        self.assertEqual((full["window_origin"], full["window_epoch"], full["replace_all"]), ([1, 2], 1, True))
        boot = json.loads((await backend.bootstrap()).body)
        self.assertEqual((boot["window_origin"], boot["window_epoch"], boot["world"]["window_epoch"]), ([1, 2], 1, 1))

    async def test_a_map_delta_after_a_rebase_carries_the_shifted_positions(self):
        engine = await self.world(True)
        engine._force_map_refresh = True
        self.rebuild(engine)
        before = {e["id"]: e["anchor"] for e in engine._last_exported_map_entities.values()}
        engine._window.rebase((1, 0))
        self.rebuild(engine)
        moved = {u["id"]: u["anchor"] for u in engine._map_delta_payload["upserts"]}
        self.assertTrue(moved)
        for uid, anchor in moved.items():
            if uid in before and before[uid] != anchor:
                self.assertAlmostEqual(anchor["x"], before[uid]["x"] - 256.0, places=3)

    async def test_maps_and_spaces_expose_the_window_shift_of_the_primary_map(self):
        from systems.movement.map_contract import maps_block
        from harness.spaces import space_table
        engine = await self.world(True)
        self.assertTrue(all(m["window_shift"] == [0.0, 0.0] for m in maps_block(engine)))
        engine._window.rebase((2, 1))
        maps, spaces = maps_block(engine), space_table(engine)
        self.assertEqual(maps[0]["window_shift"], [-512.0, -256.0])
        self.assertEqual(maps[0]["origin"], [0.0, 0.0], "the registration origin is unchanged")
        self.assertTrue(all(m["window_shift"] == [0.0, 0.0] for m in maps[1:]))
        self.assertEqual([s["window_shift"] for s in spaces], [m["window_shift"] for m in maps])
        self.assertEqual(spaces[0]["bounds"][0], -512.0)

    async def test_flag_off_maps_have_no_window_shift(self):
        from systems.movement.map_contract import maps_block
        from harness.spaces import space_table
        engine = await self.world(False)
        self.assertTrue(all("window_shift" not in m for m in maps_block(engine)))
        self.assertTrue(all("window_shift" not in s for s in space_table(engine)))

    async def test_requests_naming_an_older_epoch_get_409_and_the_current_frame(self):
        engine = await self.world(True)
        engine._window.rebase((1, 0))
        for handler, body in ((backend.view_window, {"center_x": 10.0, "center_y": 10.0, "view_world_w": 100.0, "view_world_h": 80.0, "window_epoch": 0}),
                              (backend.human_view_window, {"center_x": 10.0, "center_y": 10.0, "window_epoch": 0}),
                              (backend.control_input, {"controller_id": "c", "window_epoch": 0})):
            response = await handler(Request(body))
            self.assertEqual(response.status_code, 409)
            self.assertEqual(json.loads(response.body), {"ok": False, "reason": "stale_window_epoch", "window_origin": [1, 0], "window_epoch": 1})
        current = await backend.view_window(Request({"center_x": 10.0, "center_y": 10.0, "view_world_w": 100.0, "view_world_h": 80.0, "window_epoch": 1}))
        self.assertEqual(current.status_code, 200)
        self.assertEqual(json.loads(current.body)["window_epoch"], 1)
        absent = await backend.view_window(Request({"center_x": 10.0, "center_y": 10.0, "view_world_w": 100.0, "view_world_h": 80.0}))
        self.assertEqual(absent.status_code, 200, "a request without window_epoch counts as current")
        result = json.loads((await backend.human_view_window(Request({"center_x": 10.0, "center_y": 10.0, "window_epoch": 1}))).body)
        self.assertEqual((result["window_origin"], result["window_epoch"]), ([1, 0], 1))


class ServiceFactoryTests(unittest.TestCase):
    def test_the_routes_share_the_window_service_only_under_the_flag(self):
        from api import chunk_routes
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}):
            self.assertIs(window_wire.chunk_service_factory(), window_manager.shared_service)
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "0"}):
            self.assertIs(window_wire.chunk_service_factory(), chunk_routes.default_service)
            with mock.patch.object(window_manager, "close_service") as closed:
                window_wire.close_chunk_service()
            closed.assert_not_called()
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}), mock.patch.object(window_manager, "close_service") as closed:
            window_wire.close_chunk_service()
        closed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
