"""1008 WS-D P5 (d): the window re-base. When the residents drift more than REBASE_AT chunks from the origin, the origin moves to their chunk
and every space-0 position the engine holds shifts by the same whole number of chunks; absolute positions do not change. The position-holder scan
plants distinctive coordinates, re-bases, and walks the engine's state for any float that still equals an old local coordinate."""
import math
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import ON, WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
import map_geo  # noqa: E402
from harness import window  # noqa: E402
from systems.movement import map_contract  # noqa: E402
from systems.movement.spatial import world_contract  # noqa: E402
from systems.worldgen.rings import ChunkCoord  # noqa: E402


class RebaseFixture(WindowFixture):
    def absolute_positions(self):
        h, m = self.engine.state.h_tensor, self.engine.state.m_tensor
        size, (ox, oy) = 256.0, self.manager.frame.origin
        humans = {s: (ox * size + float(h[s, cfg.X]), oy * size + float(h[s, cfg.Y])) for s in range(8) if float(h[s, cfg.TYPE]) > 0}
        live = torch.nonzero(m[:, cfg.M_TYPE] > 0).flatten().tolist()
        return humans, {s: (ox * size + float(m[s, cfg.CX]), oy * size + float(m[s, cfg.CY])) for s in live}


class RebaseTests(RebaseFixture):
    async def test_a_rebase_shifts_rows_geometry_and_boxes_and_keeps_absolute_positions(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        humans, entities = self.absolute_positions()
        tiles = {eid: map_geo.tiles_of(eid) for eid in entities}
        owners = dict(map_geo.TILE_TO_ENTITY)
        revision = world_contract(self.engine)["revision"]
        boxes = [(b["id"], b["min"], b["max"]) for b in self.engine._window_contract["boxes"]]
        result = self.manager.rebase((2, 2))
        self.assertEqual(result["shift"], [-512.0, -512.0])
        self.assertEqual(self.manager.frame.origin, (2, 2))
        self.assertEqual(self.manager.epoch, 1)
        self.assertEqual(self.engine._window_epoch, 1)
        after_humans, after_entities = self.absolute_positions()
        self.assertEqual(after_humans, humans)
        self.assertEqual(after_entities, entities)
        self.assertEqual(float(self.engine.state.h_tensor[0, cfg.X]), 8.0)
        shift_tiles = -512 // 8
        moved = 0
        for eid, old in tiles.items():
            expected = []
            for ti in old:
                row, col = divmod(ti, map_geo.GRID_W)
                row, col = row + shift_tiles, col + shift_tiles
                if 0 <= row < map_geo.GRID_H and 0 <= col < map_geo.GRID_W:
                    expected.append(row * map_geo.GRID_W + col)
            self.assertEqual(set(expected) - set(map_geo.tiles_of(eid)), set(), eid)     # nothing it owned is lost
            moved += 1
        self.assertGreater(moved, 20)
        for ti, eid in owners.items():
            row, col = divmod(ti, map_geo.GRID_W)
            new_ti = (row + shift_tiles) * map_geo.GRID_W + col + shift_tiles
            if 0 <= row + shift_tiles < map_geo.GRID_H and 0 <= col + shift_tiles < map_geo.GRID_W:
                self.assertEqual(map_geo.TILE_TO_ENTITY.get(new_ti), eid)
        after = {b["id"]: (b["min"], b["max"]) for b in self.engine._window_contract["boxes"]}
        for ident, lo, hi in boxes:
            self.assertEqual(after[ident], ([lo[0] - 512.0, lo[1] - 512.0], [hi[0] - 512.0, hi[1] - 512.0]), ident)
        self.assertNotEqual(world_contract(self.engine)["revision"], revision)
        self.assertEqual(self.engine._window_contract["bounds"], [-512.0, -512.0, 768.0, 768.0])

    async def test_nothing_changes_for_the_same_origin_and_a_round_trip_restores_everything(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        before = (self.engine.state.h_tensor.clone(), self.engine.state.m_tensor.clone(), dict(map_geo.TILE_TO_ENTITY),
                  {e: map_geo.tiles_of(e) for e in map_geo.MAP_GEO}, self.engine._window_contract["boxes"])
        self.assertEqual(self.manager.rebase((0, 0)), {})
        self.manager.rebase((2, 1))
        self.manager.rebase((0, 0))
        self.assertTrue(torch.equal(self.engine.state.h_tensor, before[0]))
        self.assertTrue(torch.equal(self.engine.state.m_tensor, before[1]))
        self.assertEqual(map_geo.TILE_TO_ENTITY, before[2])
        self.assertEqual({e: map_geo.tiles_of(e) for e in map_geo.MAP_GEO}, before[3])
        self.assertEqual(self.engine._window_contract["boxes"], before[4])

    async def test_only_space_zero_rows_move(self):
        self.place_human(0, 520.0, 520.0)
        self.place_human(1, 60.0, 70.0)
        self.engine.state.h_tensor[1, cfg.H_SPACE] = 1.0
        self.run_ticks(5)
        m = self.engine.state.m_tensor
        slot = iat.entity_born(m, self.engine._entity_count_ref, 300.0, 310.0, cfg.M_FOREST, hp=100.0, scale=10.0, register_geo=True,
                               device=self.engine.state.device)
        m[slot, cfg.M_SPACE] = 2.0
        self.manager.rebase((1, 1))
        h = self.engine.state.h_tensor
        self.assertEqual((float(h[0, cfg.X]), float(h[0, cfg.Y])), (264.0, 264.0))
        self.assertEqual((float(h[1, cfg.X]), float(h[1, cfg.Y])), (60.0, 70.0))
        self.assertEqual((float(m[slot, cfg.CX]), float(m[slot, cfg.CY])), (300.0, 310.0))
        self.assertEqual((map_geo.MAP_GEO[slot]["cx"], map_geo.MAP_GEO[slot]["cy"]), (300.0, 310.0))

    async def test_the_registered_primary_map_moves_and_a_placed_interior_does_not(self):
        map_contract.clear_map_contracts()
        self.addCleanup(map_contract.clear_map_contracts)
        map_contract.register_map_contract("wp", 0.4, [0.0, 0.0, 400.0, 300.0], [{"id": "wall", "min": [10.0, 10.0], "max": [20.0, 40.0]}],
                                           anchors=[{"id": "a", "kind": "spawn", "position": [100.0, 120.0]}],
                                           entities=[{"id": "e", "kind": "tree", "interactive": False, "position": [50.0, 60.0]}])
        map_contract.register_map_contract("in", 0.4, [2000.0, 0.0, 2200.0, 100.0], [], world="wp",
                                           anchors=[{"id": "b", "kind": "spawn", "position": [2100.0, 50.0]}])
        self.engine._map_name = "wp"
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(3)
        self.manager.rebase((1, 0))
        primary, interior = map_contract.MAP_CONTRACTS["wp"], map_contract.MAP_CONTRACTS["in"]
        self.assertEqual(primary["bounds"], [-256.0, 0.0, 144.0, 300.0])
        self.assertEqual(primary["boxes"][0]["min"], [-246.0, 10.0])
        self.assertEqual(primary["anchors"][0]["position"], [-156.0, 120.0])
        self.assertEqual(primary["entities"][0]["position"], [-206.0, 60.0])
        self.assertEqual(primary["origin"], [0.0, 0.0], "the registration origin stays; the shift is recorded beside it")
        self.assertEqual(primary["window_shift"], [-256.0, 0.0])
        self.assertEqual(interior["bounds"], [2000.0, 0.0, 2200.0, 100.0])
        self.assertEqual(interior["anchors"][0]["position"], [2100.0, 50.0])

    async def test_resident_memory_view_window_and_pending_event_follow(self):
        store = self.engine.resident_store
        store._cache["h_rebase"] = {"memory": {"berries": [{"uid": "c1_1:b1", "x": 300.0, "y": 400.0, "abs": {"chunk_x": 1, "chunk_y": 1, "x": 44.0, "y": 144.0}},
                                                           {"entity_id": 3, "x": 11.0, "y": 12.0}]}}
        self.addCleanup(store._cache.pop, "h_rebase", None)
        self.engine._view_window_state = {"center_x": 700.0, "center_y": 500.0, "camera_mode": "human"}
        self.engine._nature_state["pending_event"] = {"name": "storm", "center_x": 900.0, "center_y": 600.0}
        self.addCleanup(self.engine._nature_state.pop, "pending_event", None)
        self.place_human(0, 520.0, 520.0)
        self.manager.rebase((1, 2))
        entries = store._cache["h_rebase"]["memory"]["berries"]
        self.assertEqual((entries[0]["x"], entries[0]["y"]), (44.0, -112.0))
        self.assertEqual((entries[1]["x"], entries[1]["y"]), (11.0, 12.0), "a legacy slot-keyed entry has no absolute position and is left alone")
        self.assertEqual((self.engine._view_window_state["center_x"], self.engine._view_window_state["center_y"]), (444.0, -12.0))
        self.assertEqual((self.engine._nature_state["pending_event"]["center_x"], self.engine._nature_state["pending_event"]["center_y"]), (644.0, 88.0))

    async def test_previous_positions_and_the_model_plane_callback(self):
        self.place_human(0, 520.0, 520.0)
        self.engine._human_uid_by_slot[0] = "h_prev"
        self.addCleanup(lambda: self.engine._human_uid_by_slot.__setitem__(0, None))
        self.engine._actor_prev_positions["h_prev"] = (500.0, 510.0)
        self.addCleanup(self.engine._actor_prev_positions.pop, "h_prev", None)
        fake = type(sys)("systems.actions.rebase")
        calls = []
        fake.rebase_model_plane = lambda engine, dx, dy: calls.append((dx, dy)) or {"roster_final_positions": 0}
        with mock.patch.dict(sys.modules, {"systems.actions.rebase": fake}):
            result = self.manager.rebase((1, 1))
        self.assertEqual(self.engine._actor_prev_positions["h_prev"], (244.0, 254.0))
        self.assertEqual(calls, [(-256.0, -256.0)])
        self.assertEqual(result["model_plane"], {"roster_final_positions": 0})

    async def test_the_real_model_plane_callback_is_called_with_the_shift(self):
        self.place_human(0, 520.0, 520.0)
        result = self.manager.rebase((1, 1))
        self.assertEqual(set(result["model_plane"]), {"roster_final_positions", "roster_checkpoint", "mover_plans", "mover_no_path",
                                                      "record_positions", "driver_goals", "ladder_errands"})

    async def test_a_resident_walking_east_triggers_the_rebase_and_the_ring_follows(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        self.assertEqual(self.manager.frame.origin, (0, 0))
        self.engine.state.h_tensor[0, cfg.X] = 3 * 256 + 100.0                     # chunk 3: more than REBASE_AT = 2 from the origin
        self.run_ticks(1)
        self.assertEqual(self.manager.frame.origin, (3, 2))
        self.assertEqual(float(self.engine.state.h_tensor[0, cfg.X]), 100.0)
        self.assertEqual(self.manager.counters["rebased"], 1)
        self.run_ticks(40)
        self.assertEqual(self.manager.frame.origin, (3, 2), "no second re-base while the resident stays")
        self.assertTrue(any(entry[1] == "rebase" for entry in self.manager.log))
        self.assertIn(ChunkCoord(3, 2), self.manager.chunks)
        for coord in self.manager.chunks:
            self.assertTrue(self.manager._in_frame(coord), coord)

    async def test_a_chunk_outside_the_fixed_frame_is_not_integrated(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(2)
        self.assertTrue(self.manager._in_frame(ChunkCoord(5, 5)))
        self.assertFalse(self.manager._in_frame(ChunkCoord(7, 0)))                # local x = 1792 + 256 > 1536
        self.assertFalse(self.manager._in_frame(ChunkCoord(-6, 0)))               # local x = -1536 < -1280

    async def test_a_rebase_leaves_no_positional_delta(self):
        self.place_human(0, 520.0, 520.0)
        self.run_ticks(25)
        self.manager.rebase((1, 1))
        self.manager.unload(ChunkCoord(3, 3))
        self.assertNotIn(ChunkCoord(3, 3), self.manager.deltas)


class PositionHolderScan(RebaseFixture):
    """Plant coordinates no other value in the engine equals, re-base, and look for them anywhere reachable from the engine (tensors excluded: the
    rows are checked above)."""
    SKIP = {"state", "_window", "scheduler", "command_inbox", "_memory_graph_writer", "light_rag", "memory_rag", "_lightrag_module"}

    def scan(self, root, targets, limit=200000):
        hits, seen, stack = [], set(), [("engine", root, 0)]
        while stack and len(seen) < limit:
            path, node, depth = stack.pop()
            if isinstance(node, bool) or node is None or isinstance(node, (str, bytes, int)):
                continue
            if isinstance(node, float):
                if any(math.isclose(node, t, abs_tol=0.006) for t in targets):
                    hits.append((path, node))
                continue
            if isinstance(node, (torch.Tensor, type)) or callable(node) and not hasattr(node, "__dict__"):
                continue
            if id(node) in seen or depth > 7:
                continue
            seen.add(id(node))
            if isinstance(node, dict):
                items = [(f"{path}[{k!r}]", v) for k, v in node.items()]
            elif isinstance(node, (list, tuple, set, frozenset)):
                items = [(f"{path}[{i}]", v) for i, v in enumerate(node)]
            elif hasattr(node, "__dict__"):
                items = [(f"{path}.{k}", v) for k, v in vars(node).items() if not (depth == 0 and k in self.SKIP)]
            else:
                continue
            stack.extend((p, v, depth + 1) for p, v in items)
        return hits

    async def test_no_old_local_coordinate_survives_a_rebase(self):
        engine = self.engine
        x, y = 520.5, 641.25                                                      # a space-0 human in chunk (2, 2): no automatic re-base while the ticks run
        self.place_human(0, x, y)
        engine._human_uid_by_slot[0] = "h_scan"
        self.addCleanup(lambda: engine._human_uid_by_slot.__setitem__(0, None))
        self.run_ticks(25)
        ex, ey = 1001.75, 802.5
        slot = iat.entity_born(engine.state.m_tensor, engine._entity_count_ref, ex, ey, cfg.M_FOREST, hp=100.0, scale=10.0, register_geo=True,
                               device=engine.state.device)
        engine._entity_uid_by_slot[slot] = "scan_tree"
        self.addCleanup(lambda: engine._entity_uid_by_slot.__setitem__(slot, None))
        engine._actor_prev_positions["h_scan"] = (x - 0.5, y)
        self.addCleanup(engine._actor_prev_positions.pop, "h_scan", None)
        store = engine.resident_store
        store._cache["h_scan"] = {"memory": {"berries": [{"uid": "scan_tree", "x": ex, "y": ey, "abs": {"chunk_x": 3, "chunk_y": 3, "x": 233.75, "y": 34.5}}]}}
        self.addCleanup(store._cache.pop, "h_scan", None)
        before = self.scan(engine, [x, y, ex, ey])
        self.assertGreaterEqual(len(before), 3, f"the scan must see the planted holders at all: {before}")
        self.manager.rebase((2, 2))
        after = self.scan(engine, [x, y, ex, ey])
        self.assertEqual(after, [], f"state still holding an old local coordinate after the re-base: {after}")


if __name__ == "__main__":
    unittest.main()
