"""Focused authoritative void-barrier telemetry tests (Roadmap R0.5/1008 GateE).

Tests cover:
- Collision classification (is_void_box distinguishing void barrier vs authored/chunk walls)
- Unobstructed movement in chunk interior (zero hits)
- Authored wall collision vs void barrier collision (strict differentiation)
- Direct blocking by void barriers
- Tangent sliding along void barriers (preserving exact tangent physics)
- Multiple blockers / corner collisions with bounded per-attempt accounting
- Flag-off exact movement (legacy return signature and bit-identical coordinates)
- Stale and teleport non-movement (zero hits when standing still or moving away)
- Proximity and world-bounds clamps not misclassified as void hits
- WindowManager counter stats export, reset, and rebase continuity
- Real Engine and WindowManager movement path integration (player vs resident attribution,
  teleport/stale non-movement causality, and once-per-attempt accounting)
"""
from __future__ import annotations

import collections
import os
import sys
import unittest
from pathlib import Path

import torch

# Ensure repository root and at_the_beginning are in sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ATB = ROOT / "at_the_beginning"
if str(ATB) not in sys.path:
    sys.path.insert(0, str(ATB))

from systems.movement.spatial import (
    RADIUS,
    is_void_box,
    slide,
    slide_with_diagnostics,
)
from systems.movement.map_contract import MAP_CONTRACTS, clear_map_contracts
from systems.worldgen.rings import ChunkCoord, RingConfig
from harness.window_manager import WindowManager, ChunkState
from harness.frame import SpaceFrame
from map_test import Engine, AGENT_TYPE_HUMAN, X, Y, TYPE, HP
from genesis_config import H_LIFE_EXP, H_AGE, H_STAMINA


def _make_contract(boxes, actor_radius=RADIUS, bounds=None):
    if bounds is None:
        bounds = [-1000.0, -1000.0, 1000.0, 1000.0]
    return {
        "actor_radius": actor_radius,
        "bounds": bounds,
        "boxes": boxes,
    }


class _MockChunkService:
    def __init__(self, seed: int = 1008):
        self.world_seed = seed

    def stats(self) -> dict:
        return {"service": "mock"}

    def close(self) -> None:
        pass


# ----------------------------------------------------------------------
# 1. Box classification
# ----------------------------------------------------------------------

class TestVoidBoxClassification(unittest.TestCase):
    def test_is_void_box(self):
        self.assertTrue(is_void_box({"id": "void:0:0:w"}))
        self.assertTrue(is_void_box({"id": "void:1:-2:e"}))
        self.assertTrue(is_void_box({"id": "void:-5:3:s"}))
        self.assertTrue(is_void_box({"id": "void:0:0:n"}))

        # Authored walls and chunk features must not be classified as void
        self.assertFalse(is_void_box({"id": "starter_village:wall:perimeter_1"}))
        self.assertFalse(is_void_box({"id": "wall:1"}))
        self.assertFalse(is_void_box({"id": "c0_0:tree1"}))
        self.assertFalse(is_void_box({"id": "smith_interior:wall:front"}))
        self.assertFalse(is_void_box({"id": ""}))
        self.assertFalse(is_void_box({}))
        self.assertFalse(is_void_box(None))


# ----------------------------------------------------------------------
# 2. Spatial slide diagnostics unit tests
# ----------------------------------------------------------------------

class TestSpatialSlideDiagnostics(unittest.TestCase):
    def test_unobstructed_movement(self):
        boxes = [
            {"id": "void:0:0:e", "min": [256.0, 0.0], "max": [258.0, 256.0], "height": 2.4},
            {"id": "starter_village:wall:1", "min": [10.0, 10.0], "max": [12.0, 20.0], "height": 2.4},
        ]
        contract = _make_contract(boxes)

        start = (100.0, 100.0)
        desired = (105.0, 102.0)

        # Legacy slide call
        legacy_res = slide(start, desired, contract)
        self.assertEqual(legacy_res, (105.0, 102.0))

        # Diagnostic call
        resolved, diag = slide_with_diagnostics(start, desired, contract)
        self.assertEqual(resolved, legacy_res)
        self.assertFalse(diag["blocked"])
        self.assertFalse(diag["void_hit"])
        self.assertFalse(diag["wall_hit"])
        self.assertEqual(diag["void_boxes"], [])
        self.assertEqual(diag["wall_boxes"], [])
        self.assertEqual(diag["blocked_axes"], [])

    def test_authored_wall_collision_distinguished(self):
        authored_box = {"id": "starter_village:wall:house_north", "min": [50.0, 40.0], "max": [52.0, 60.0], "height": 2.4}
        void_box = {"id": "void:0:0:e", "min": [256.0, 0.0], "max": [258.0, 256.0], "height": 2.4}
        contract = _make_contract([authored_box, void_box])

        start = (40.0, 50.0)
        desired = (60.0, 50.0)

        resolved, diag = slide_with_diagnostics(start, desired, contract)

        # Stopping position clamped by authored box left edge (50.0 - RADIUS = 49.65)
        expected_x = 50.0 - RADIUS
        self.assertAlmostEqual(resolved[0], expected_x, places=6)
        self.assertAlmostEqual(resolved[1], 50.0, places=6)

        self.assertTrue(diag["blocked"])
        self.assertTrue(diag["wall_hit"])
        self.assertFalse(diag["void_hit"])
        self.assertIn("starter_village:wall:house_north", diag["wall_boxes"])
        self.assertEqual(diag["void_boxes"], [])
        self.assertEqual(diag["blocked_axes"], ["x"])

    def test_void_barrier_direct_block(self):
        void_box = {"id": "void:0:0:e", "min": [256.0, 0.0], "max": [258.0, 256.0], "height": 2.4}
        contract = _make_contract([void_box])

        start = (250.0, 100.0)
        desired = (260.0, 100.0)

        resolved, diag = slide_with_diagnostics(start, desired, contract)

        expected_x = 256.0 - RADIUS
        self.assertAlmostEqual(resolved[0], expected_x, places=6)
        self.assertAlmostEqual(resolved[1], 100.0, places=6)

        self.assertTrue(diag["blocked"])
        self.assertTrue(diag["void_hit"])
        self.assertFalse(diag["wall_hit"])
        self.assertEqual(diag["void_boxes"], ["void:0:0:e"])
        self.assertEqual(diag["wall_boxes"], [])
        self.assertEqual(diag["blocked_axes"], ["x"])

    def test_void_barrier_tangent_sliding(self):
        void_box = {"id": "void:0:0:e", "min": [256.0, 0.0], "max": [258.0, 256.0], "height": 2.4}
        contract = _make_contract([void_box])

        start = (250.0, 100.0)
        desired = (260.0, 115.0)

        resolved, diag = slide_with_diagnostics(start, desired, contract)

        expected_x = 256.0 - RADIUS
        self.assertAlmostEqual(resolved[0], expected_x, places=6)
        # Y axis continues freely tangent to the void wall
        self.assertAlmostEqual(resolved[1], 115.0, places=6)

        self.assertTrue(diag["blocked"])
        self.assertTrue(diag["void_hit"])
        self.assertFalse(diag["wall_hit"])
        self.assertEqual(diag["void_boxes"], ["void:0:0:e"])
        self.assertEqual(diag["blocked_axes"], ["x"])

        # Verify exact match with default slide return signature
        legacy_res = slide(start, desired, contract)
        self.assertEqual(legacy_res, resolved)

    def test_multiple_void_blockers_bounded_accounting(self):
        east_void = {"id": "void:0:0:e", "min": [256.0, 0.0], "max": [258.0, 256.0], "height": 2.4}
        south_void = {"id": "void:0:0:s", "min": [0.0, 256.0], "max": [256.0, 258.0], "height": 2.4}
        contract = _make_contract([east_void, south_void])

        # Actor near the SE corner moving diagonal outwards
        start = (255.0, 255.0)
        desired = (260.0, 260.0)

        resolved, diag = slide_with_diagnostics(start, desired, contract)

        expected_x = 256.0 - RADIUS
        expected_y = 256.0 - RADIUS
        self.assertAlmostEqual(resolved[0], expected_x, places=6)
        self.assertAlmostEqual(resolved[1], expected_y, places=6)

        # Both X and Y axes contacted void barriers
        self.assertTrue(diag["void_hit"])
        self.assertFalse(diag["wall_hit"])
        self.assertEqual(set(diag["void_boxes"]), {"void:0:0:e", "void:0:0:s"})
        self.assertEqual(set(diag["blocked_axes"]), {"x", "y"})

    def test_mixed_blockers_wall_and_void(self):
        authored_wall = {"id": "starter_village:wall:west", "min": [10.0, 0.0], "max": [12.0, 256.0], "height": 2.4}
        north_void = {"id": "void:0:0:n", "min": [0.0, -2.0], "max": [256.0, 0.0], "height": 2.4}
        contract = _make_contract([authored_wall, north_void])

        # Moving northwest: X blocked by authored wall, Y blocked by north void barrier
        start = (15.0, 5.0)
        desired = (8.0, -5.0)

        resolved, diag = slide_with_diagnostics(start, desired, contract)

        expected_x = 12.0 + RADIUS  # right edge of wall
        expected_y = 0.0 + RADIUS   # bottom edge of north void box
        self.assertAlmostEqual(resolved[0], expected_x, places=6)
        self.assertAlmostEqual(resolved[1], expected_y, places=6)

        self.assertTrue(diag["void_hit"])
        self.assertTrue(diag["wall_hit"])
        self.assertIn("void:0:0:n", diag["void_boxes"])
        self.assertIn("starter_village:wall:west", diag["wall_boxes"])

    def test_nearer_wall_occluding_further_void_not_counted_as_void_hit(self):
        # A nearer authored wall occludes a further void barrier along the movement ray.
        # Both boxes overlap the sweep bounding box, but only the nearer binding wall must be counted.
        authored_wall = {"id": "starter_village:wall:front", "min": [15.0, 0.0], "max": [17.0, 100.0], "height": 2.4}
        further_void = {"id": "void:0:0:e", "min": [25.0, 0.0], "max": [27.0, 100.0], "height": 2.4}
        contract = _make_contract([authored_wall, further_void])

        start = (10.0, 50.0)
        desired = (30.0, 50.0)

        resolved, diag = slide_with_diagnostics(start, desired, contract)

        expected_x = 15.0 - RADIUS
        self.assertAlmostEqual(resolved[0], expected_x, places=6)
        self.assertAlmostEqual(resolved[1], 50.0, places=6)

        self.assertTrue(diag["blocked"])
        self.assertTrue(diag["wall_hit"])
        self.assertFalse(diag["void_hit"])
        self.assertEqual(diag["wall_boxes"], ["starter_village:wall:front"])
        self.assertEqual(diag["void_boxes"], [])

    def test_flag_off_exact_movement(self):
        wall = {"id": "wall_1", "min": [20.0, 20.0], "max": [24.0, 24.0], "height": 2.4}
        contract = _make_contract([wall])

        start = (10.0, 22.0)
        desired = (30.0, 22.0)

        # Calling slide with default arguments returns a standard 2-tuple of floats
        result = slide(start, desired, contract)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(v, float) for v in result))
        self.assertAlmostEqual(result[0], 20.0 - RADIUS, places=6)
        self.assertAlmostEqual(result[1], 22.0, places=6)

    def test_stale_and_teleport_non_movement(self):
        void_box = {"id": "void:0:0:e", "min": [256.0, 0.0], "max": [258.0, 256.0], "height": 2.4}
        contract = _make_contract([void_box])

        # Case A: Actor standing right against void boundary, but desired == start (idle/stale)
        standing_pos = (256.0 - RADIUS, 100.0)
        resolved, diag = slide_with_diagnostics(standing_pos, standing_pos, contract)
        self.assertEqual(resolved, standing_pos)
        self.assertFalse(diag["void_hit"])
        self.assertFalse(diag["wall_hit"])
        self.assertFalse(diag["blocked"])

        # Case B: Actor standing against void boundary, moving away from barrier (west)
        moving_away = (250.0, 100.0)
        resolved, diag = slide_with_diagnostics(standing_pos, moving_away, contract)
        self.assertEqual(resolved, moving_away)
        self.assertFalse(diag["void_hit"])
        self.assertFalse(diag["wall_hit"])

        # Case C: Teleport target is standable, no slide displacement occurs
        teleport_target = (128.0, 128.0)
        resolved, diag = slide_with_diagnostics(teleport_target, teleport_target, contract)
        self.assertEqual(resolved, teleport_target)
        self.assertFalse(diag["void_hit"])

    def test_proximity_not_counted_as_void_hit(self):
        void_box = {"id": "void:0:0:e", "min": [256.0, 0.0], "max": [258.0, 256.0], "height": 2.4}
        contract = _make_contract([void_box])

        # Actor moves near the barrier (ending at 254.0, which is within 2 units of 256.0, but not touching 255.65)
        start = (240.0, 100.0)
        desired = (254.0, 100.0)

        resolved, diag = slide_with_diagnostics(start, desired, contract)
        self.assertEqual(resolved, desired)
        self.assertFalse(diag["void_hit"])
        self.assertFalse(diag["blocked"])

    def test_bounds_clamp_not_counted_as_void_hit(self):
        # Only world bounds clamp [0, 0, 1000, 1000], no void box near endpoint
        contract = _make_contract([], bounds=[0.0, 0.0, 1000.0, 1000.0])

        start = (990.0, 500.0)
        desired = (1050.0, 500.0)

        resolved, diag = slide_with_diagnostics(start, desired, contract)
        # Clamped to bounds[2] - RADIUS = 1000.0 - 0.35 = 999.65
        self.assertAlmostEqual(resolved[0], 999.65, places=6)
        self.assertAlmostEqual(resolved[1], 500.0, places=6)
        # Must NOT count as void hit or wall hit
        self.assertFalse(diag["void_hit"])
        self.assertFalse(diag["wall_hit"])
        self.assertFalse(diag["blocked"])


# ----------------------------------------------------------------------
# 3. WindowManager counter stats, export, reset, and rebase continuity
# ----------------------------------------------------------------------

class _MockEngine:
    def __init__(self):
        self.world_epoch = 1
        self.tick = 0
        self._window_contract = None
        self._entity_uid_by_slot = []
        self._human_uid_by_slot = []
        self._map_name = "starter_village"


class TestWindowManagerTelemetry(unittest.TestCase):
    def test_window_manager_counter_stats_and_reset(self):
        engine = _MockEngine()
        service = _MockChunkService()
        wm = WindowManager(engine, service)

        # Initial counters must all be 0
        stats = wm.stats()
        counters = stats["counters"]
        self.assertEqual(counters["void_hits"], 0)
        self.assertEqual(counters["void_hits_player"], 0)
        self.assertEqual(counters["void_hits_resident"], 0)
        self.assertEqual(counters["wall_hits"], 0)
        self.assertEqual(counters["wall_hits_player"], 0)
        self.assertEqual(counters["wall_hits_resident"], 0)

        # Record resident void hit
        wm.record_void_hit(is_player=False)
        self.assertEqual(wm.void_hits, 1)
        self.assertEqual(wm.void_hits_resident, 1)
        self.assertEqual(wm.void_hits_player, 0)

        # Record player void hit
        wm.record_void_hit(is_player=True)
        self.assertEqual(wm.void_hits, 2)
        self.assertEqual(wm.void_hits_resident, 1)
        self.assertEqual(wm.void_hits_player, 1)

        # Record authored wall hit
        wm.record_wall_hit(is_player=False)
        self.assertEqual(wm.wall_hits, 1)
        self.assertEqual(wm.wall_hits_resident, 1)
        self.assertEqual(wm.wall_hits_player, 0)

        # Stats reflects updated counters
        stats = wm.stats()
        counters = stats["counters"]
        self.assertEqual(counters["void_hits"], 2)
        self.assertEqual(counters["void_hits_player"], 1)
        self.assertEqual(counters["void_hits_resident"], 1)
        self.assertEqual(counters["wall_hits"], 1)

        # Reset counters
        wm.reset_counters()
        stats = wm.stats()
        counters = stats["counters"]
        self.assertEqual(counters["void_hits"], 0)
        self.assertEqual(counters["void_hits_player"], 0)
        self.assertEqual(counters["void_hits_resident"], 0)
        self.assertEqual(counters["wall_hits"], 0)

    def test_rebase_preserves_accumulated_telemetry(self):
        """Rebase shifts window origin and boxes without clearing or corrupting counters."""
        engine = _MockEngine()
        service = _MockChunkService()
        wm = WindowManager(engine, service)

        # Accumulate hits
        wm.record_void_hit(is_player=False)
        wm.record_void_hit(is_player=True)
        wm.record_wall_hit(is_player=True)

        self.assertEqual(wm.void_hits, 2)
        self.assertEqual(wm.void_hits_player, 1)

        # Shift origin via rebase_shift
        shift_dx, shift_dy = wm.frame.rebase_shift((1, 0))
        wm.frame.rebase((1, 0))

        # Counters must remain intact after rebase
        stats = wm.stats()
        counters = stats["counters"]
        self.assertEqual(counters["void_hits"], 2)
        self.assertEqual(counters["void_hits_player"], 1)
        self.assertEqual(counters["void_hits_resident"], 1)
        self.assertEqual(counters["wall_hits"], 1)


# ----------------------------------------------------------------------
# 4. Real Engine and WindowManager movement path integration tests
# ----------------------------------------------------------------------

class TestEngineMovementPathIntegration(unittest.TestCase):
    """Integration tests running through the real Engine.step() reconcile loop.

    Verifies:
    - Real spatial_slide integration with Engine reconcile
    - Player vs resident collision attribution via Engine session runtime
    - Teleport non-movement causality (zero hits)
    - Stale / stationary actor causality (zero hits)
    - Moving away from void barriers (zero hits)
    - Once-per-attempt accounting under corner/multi-barrier contacts
    """

    def setUp(self):
        self._saved_env = dict(os.environ)
        os.environ["EDEN_WINDOW"] = "1"
        self._saved_contracts = dict(MAP_CONTRACTS)
        clear_map_contracts()

        self.engine = Engine()
        self.engine.reset_world()
        self.engine.world_loaded = True
        self.engine._runtime_profile = "render_test"

        # Register map contract so anchor_driven_rows activates
        self.engine._map_name = "test_window_map"
        MAP_CONTRACTS["test_window_map"] = {
            "actor_radius": RADIUS,
            "bounds": [-1000.0, -1000.0, 1000.0, 1000.0],
            "boxes": [],
            "anchors": [],
            "entities": [],
        }

        # Attach real WindowManager with mock chunk service
        self.service = _MockChunkService()
        self.wm = WindowManager(self.engine, self.service)

        # Integrate chunk (0, 0) so void barriers exist along boundaries (e.g. at x = 256.0)
        chunk_coord = ChunkCoord(0, 0)
        self.wm.chunks[chunk_coord] = ChunkState(
            coord=chunk_coord,
            sha256="chunk_0_0_test",
            slots=[],
            uids=[],
            boxes=[],
            baseline=[],
        )
        self.wm._publish()

        self.engine._pop_count[0] = 2

        # Slot 0: autonomous resident with healthy vitals and anchor roster driver
        self.engine.state.h_tensor[0, TYPE] = AGENT_TYPE_HUMAN
        self.engine.state.h_tensor[0, HP] = 100.0
        self.engine.state.h_tensor[0, H_LIFE_EXP] = 100.0
        self.engine.state.h_tensor[0, H_AGE] = 20.0
        self.engine.state.h_tensor[0, H_STAMINA] = 100.0
        self.engine._human_uid_by_slot[0] = "h_resident_0"
        resident = self.engine.resident_store.ensure_resident(
            "h_resident_0", 0, self.engine.state.h_tensor, self.engine.tick
        )
        resident["roster"] = {"driver": "anchor", "anchors": {}}
        self.engine.state.h_tensor[0, X] = 250.0
        self.engine.state.h_tensor[0, Y] = 50.0
        self.engine._actor_prev_positions["h_resident_0"] = (250.0, 50.0)

        # Slot 1: controlled player with healthy vitals
        self.engine.state.h_tensor[1, TYPE] = AGENT_TYPE_HUMAN
        self.engine.state.h_tensor[1, HP] = 100.0
        self.engine.state.h_tensor[1, H_LIFE_EXP] = 100.0
        self.engine.state.h_tensor[1, H_AGE] = 20.0
        self.engine.state.h_tensor[1, H_STAMINA] = 100.0
        self.engine._human_uid_by_slot[1] = "h_player_1"
        self.engine.resident_store.ensure_resident(
            "h_player_1", 1, self.engine.state.h_tensor, self.engine.tick
        )
        self.engine.state.h_tensor[1, X] = 250.0
        self.engine.state.h_tensor[1, Y] = 100.0
        self.engine._actor_prev_positions["h_player_1"] = (250.0, 100.0)

        # Establish player session on slot 1 via claim_target with long possession timeout
        self.engine.player_control.possession_timeout = 3600.0
        self.engine.player_control.claim_target(
            self.engine,
            controller_id="controller_1",
            target_kind="human",
            target_id="h_player_1",
            mode="possess",
        )

        # Clear initial counters
        self.wm.reset_counters()

    def tearDown(self):
        self.wm.close()
        self.engine.reset_world()
        clear_map_contracts()
        MAP_CONTRACTS.update(self._saved_contracts)
        os.environ.clear()
        os.environ.update(self._saved_env)

    def test_real_engine_unobstructed_movement(self):
        # Both actors move within interior of chunk (0, 0)
        self.engine.state.h_tensor[0, X] = 252.0
        self.engine.state.h_tensor[0, Y] = 50.0
        self.engine.state.h_tensor[1, X] = 252.0
        self.engine.state.h_tensor[1, Y] = 100.0

        self.engine.step()

        self.assertEqual(self.wm.void_hits, 0)
        self.assertEqual(self.wm.void_hits_resident, 0)
        self.assertEqual(self.wm.void_hits_player, 0)
        self.assertAlmostEqual(float(self.engine.state.h_tensor[0, X]), 252.0, places=4)
        self.assertAlmostEqual(float(self.engine.state.h_tensor[1, X]), 252.0, places=4)

    def test_real_engine_player_and_resident_hit_attribution(self):
        # Resident (slot 0) moves into east void barrier (x = 256.0), player (slot 1) moves unobstructed
        self.engine.state.h_tensor[0, X] = 260.0  # blocked by void:0:0:e
        self.engine.state.h_tensor[0, Y] = 50.0
        self.engine.state.h_tensor[1, X] = 252.0  # free
        self.engine.state.h_tensor[1, Y] = 100.0

        self.engine.step()

        expected_clamped = 256.0 - RADIUS
        self.assertAlmostEqual(float(self.engine.state.h_tensor[0, X]), expected_clamped, places=4)
        self.assertAlmostEqual(float(self.engine.state.h_tensor[1, X]), 252.0, places=4)

        # Attribution: exactly 1 hit for resident, 0 for player
        self.assertEqual(self.wm.void_hits, 1)
        self.assertEqual(self.wm.void_hits_resident, 1)
        self.assertEqual(self.wm.void_hits_player, 0)

        # Next tick: Resident is stationary at barrier; player moves into east void barrier
        # (resident does not move -> desired == start)
        self.engine.state.h_tensor[1, X] = 260.0  # player now contacts barrier
        self.engine.state.h_tensor[1, Y] = 100.0

        self.engine.step()

        self.assertAlmostEqual(float(self.engine.state.h_tensor[1, X]), expected_clamped, places=4)
        # Attribution: player gets 1 hit, resident gets 0 hits this tick (stale/stationary)
        self.assertEqual(self.wm.void_hits, 2)
        self.assertEqual(self.wm.void_hits_resident, 1)
        self.assertEqual(self.wm.void_hits_player, 1)

    def test_real_engine_teleport_and_stale_non_movement(self):
        # Resident standing right against void boundary
        self.engine.state.h_tensor[0, X] = 256.0 - RADIUS
        self.engine.state.h_tensor[0, Y] = 50.0
        self.engine._actor_prev_positions["h_resident_0"] = (float(self.engine.state.h_tensor[0, X]), 50.0)

        # Step where desired == start (idle/stale resident)
        self.engine.step()
        self.assertEqual(self.wm.void_hits, 0)

        # Teleport the possessed player, matching the portal command's target.
        # Autonomous authored residents also have a separate motion limiter.
        new_teleport_pos = (256.0 - RADIUS, 80.0)
        self.engine._tick_teleports.append((1, new_teleport_pos[0], new_teleport_pos[1]))
        self.engine.state.h_tensor[1, X] = new_teleport_pos[0]
        self.engine.state.h_tensor[1, Y] = new_teleport_pos[1]

        self.engine.step()
        # Teleport must not be misclassified as a void hit
        self.assertEqual(self.wm.void_hits, 0)
        self.assertAlmostEqual(float(self.engine.state.h_tensor[1, X]), new_teleport_pos[0], places=4)
        self.assertAlmostEqual(float(self.engine.state.h_tensor[1, Y]), new_teleport_pos[1], places=4)

        # Moving away from barrier (west) must produce zero hits
        self.engine.state.h_tensor[1, X] = 240.0
        self.engine.step()
        self.assertEqual(self.wm.void_hits, 0)
        self.assertAlmostEqual(float(self.engine.state.h_tensor[1, X]), 240.0, places=4)

    def test_real_engine_once_per_attempt_corner_accounting(self):
        # Move resident near the SE corner
        self.engine.state.h_tensor[0, X] = 255.0
        self.engine.state.h_tensor[0, Y] = 255.0
        self.engine.step()
        self.wm.reset_counters()

        # Resident attempts diagonal move into the SE corner (contacting both east and south void boxes)
        self.engine.state.h_tensor[0, X] = 260.0
        self.engine.state.h_tensor[0, Y] = 260.0

        self.engine.step()

        expected_clamped = 256.0 - RADIUS
        self.assertAlmostEqual(float(self.engine.state.h_tensor[0, X]), expected_clamped, places=4)
        self.assertAlmostEqual(float(self.engine.state.h_tensor[0, Y]), expected_clamped, places=4)

        # Once-per-attempt bounded accounting: exactly 1 hit recorded, not 2
        self.assertEqual(self.wm.void_hits, 1)
        self.assertEqual(self.wm.void_hits_resident, 1)
        self.assertEqual(self.wm.void_hits_player, 0)


if __name__ == "__main__":
    unittest.main()
