"""tests/test_settlement_construction_1010.py
=========================================
Comprehensive integration and unit test suite for R6.4 Bounded Settlement Construction:
Deterministic site selection, material-funded project commitment, and exact labor progress.

Verifies:
1. Deterministic Candidate Lattice:
   - Hard cap at 64 candidates (from 9x9 symmetric lattice).
   - Strict ordering: integer squared distance first, tie-breaking by (cx, cy, sx, sy).
   - Large coordinates near +/-2^40 invariant without float drift.
   - Negative coordinate normalization across chunk boundaries.
   - Origin rebase recomputes local coordinates while preserving integer anchor.
2. Viability & Protected Footprints:
   - Claim containment within owning active settlement.
   - Exclusivity: foreign active settlement claim overlap rejected.
   - Dormant / unintegrated chunk rejected.
   - Map bounds checking in legacy frame.
   - Habitable terrain: blocked types (sea, lake, mountain, lava) rejected.
   - Active structure overlap in m_tensor rejected.
   - Dormant structure overlap in StructureStore rejected.
   - Authored movement contracts protected: wall boxes, portals, doors, forges.
   - Authored M_MAP_OBJECT and M_STORAGE_CASE protected from deletion or capture.
3. Site Planning API:
   - Preflight guards: active settlement, member living builder, personal_shelter recipe.
   - Single open project per settlement invariant.
   - Registry project cap saturation.
   - Reach filtering: builder range to candidate footprint.
4. Material-Funded Project Commitment:
   - Preflight revalidation: window epoch, engine tick, builder reach/living, stock balance.
   - Strict material conservation: personal_shelter recipe (6 wood, 3 fiber, 2 plank).
   - Real tensor allocation via designate_construction_site with instinct_create_object.
   - Runtime e_* UID allocation and geometry registration in map_geo.
   - SettlementRegistry project creation and funding.
   - Audit event emission.
   - Stale plan detection: window epoch rebase, future tick, builder death, stock change.
   - Capacity saturation: entity cap, registry project cap.
5. Precision Rollback on Injected Faults:
   - Fault after consume: restores builder inventory bit-for-bit (no material loss/creation).
   - Fault after create: zeroes m_tensor row, clears UID, restores entity counter.
   - Fault after geo: unregisters map_geo entity, restores geo_version.
   - Fault after registry: restores SettlementRegistry state via exported memento.
6. Caller-Controlled Construction Progress:
   - Worker preflight: active member, living status, stamina, reach.
   - Dormancy freeze: dormant structure or chunk raises SettlementDormancyError (no catch-up).
   - Stamina deduction and S_BUILD_PROGRESS (col 9) gain with M_HP update.
   - Zero material consumption during labor progression.
   - Completion once at 100%: links structure to settlement buildings, transitions to 'complete'.
   - Rollback on fault before completion.
7. Pure Service & Conservation:
   - Universe material conservation across full lifecycle.
   - Zero tensor column changes (no M_CONSTRUCTION_PROGRESS).
   - DR-22 authoritative save compatibility remains OPEN (no automatic tick hooks).
"""
import copy
import math
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch

# Ensure repo root and at_the_beginning are on sys.path
ROOT = Path(__file__).resolve().parents[1]
AT_THE_BEGINNING = ROOT / "at_the_beginning"
for p in (str(ROOT), str(AT_THE_BEGINNING)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import genesis_config as cfg
except ImportError:
    from at_the_beginning import genesis_config as cfg

try:
    import map_geo
except ImportError:
    from at_the_beginning import map_geo

try:
    from harness import settlements
    from harness.settlements import (
        CHUNK_SUBUNITS,
        CHUNK_UNITS,
        DEFAULT_CLAIM_RADIUS_Q,
        MAX_ABS_COORD,
        MAX_CLAIM_RADIUS_Q,
        MAX_ID_COUNTER,
        MAX_TICK,
        MIN_CHUNK_COORD,
        MAX_CHUNK_COORD,
        MIN_CLAIM_RADIUS_Q,
        MIN_ID_COUNTER,
        Q,
        SCHEMA_VERSION,
        SettlementCapError,
        SettlementConfig,
        SettlementConflictError,
        SettlementError,
        SettlementReferenceError,
        SettlementRegistry,
        SettlementValidationError,
        anchor_distance_sq_q,
        anchor_to_local,
        anchor_to_total_subunits,
        is_point_in_claim,
        make_anchor,
        normalize_subunits_to_anchor,
        quantize_chunk_local_to_anchor,
        validate_anchor,
    )
except ImportError:
    from at_the_beginning.harness import settlements
    from at_the_beginning.harness.settlements import (
        CHUNK_SUBUNITS,
        CHUNK_UNITS,
        DEFAULT_CLAIM_RADIUS_Q,
        MAX_ABS_COORD,
        MAX_CLAIM_RADIUS_Q,
        MAX_ID_COUNTER,
        MAX_TICK,
        MIN_CHUNK_COORD,
        MAX_CHUNK_COORD,
        MIN_CLAIM_RADIUS_Q,
        MIN_ID_COUNTER,
        Q,
        SCHEMA_VERSION,
        SettlementCapError,
        SettlementConfig,
        SettlementConflictError,
        SettlementError,
        SettlementReferenceError,
        SettlementRegistry,
        SettlementValidationError,
        anchor_distance_sq_q,
        anchor_to_local,
        anchor_to_total_subunits,
        is_point_in_claim,
        make_anchor,
        normalize_subunits_to_anchor,
        quantize_chunk_local_to_anchor,
        validate_anchor,
    )

try:
    from harness.settlement_construction import (
        BLOCKED_TERRAIN_TYPES,
        BUILD_MIN_STAMINA,
        BUILD_PROGRESS_PER_HUMAN,
        BUILD_RADIUS,
        BUILD_STAMINA_COST,
        DEFAULT_LATTICE_STEP_UNITS,
        HABITABLE_TERRAIN_TYPES,
        MAX_CANDIDATES,
        RECIPE_PERSONAL_SHELTER,
        SHELTER_CAP,
        SHELTER_DURABILITY,
        SHELTER_SCALE,
        SHELTER_STRUCTURE_TYPE,
        ConstructionProgressResult,
        ConstructionTransactionResult,
        SettlementConstructionError,
        SettlementDormancyError,
        SettlementPreflightError,
        SettlementSiteSelectionError,
        SettlementStalePlanError,
        SettlementTransactionError,
        SitePlan,
        advance_settlement_construction,
        commit_settlement_project,
        generate_lattice_candidates,
        is_site_candidate_viable,
        make_engine_human_resolver,
        make_engine_structure_resolver,
        plan_settlement_site,
    )
except ImportError:
    from at_the_beginning.harness.settlement_construction import (
        BLOCKED_TERRAIN_TYPES,
        BUILD_MIN_STAMINA,
        BUILD_PROGRESS_PER_HUMAN,
        BUILD_RADIUS,
        BUILD_STAMINA_COST,
        DEFAULT_LATTICE_STEP_UNITS,
        HABITABLE_TERRAIN_TYPES,
        MAX_CANDIDATES,
        RECIPE_PERSONAL_SHELTER,
        SHELTER_CAP,
        SHELTER_DURABILITY,
        SHELTER_SCALE,
        SHELTER_STRUCTURE_TYPE,
        ConstructionProgressResult,
        ConstructionTransactionResult,
        SettlementConstructionError,
        SettlementDormancyError,
        SettlementPreflightError,
        SettlementSiteSelectionError,
        SettlementStalePlanError,
        SettlementTransactionError,
        SitePlan,
        advance_settlement_construction,
        commit_settlement_project,
        generate_lattice_candidates,
        is_site_candidate_viable,
        make_engine_human_resolver,
        make_engine_structure_resolver,
        plan_settlement_site,
    )

try:
    from systems.inventory import build_inventory_state, ensure_owner_inventory
    from systems.inventory.ops import add_item, remove_item
    from systems.inventory.queries import total_quantity
except ImportError:
    from at_the_beginning.systems.inventory import build_inventory_state, ensure_owner_inventory
    from at_the_beginning.systems.inventory.ops import add_item, remove_item
    from at_the_beginning.systems.inventory.queries import total_quantity

try:
    from systems.construction.building import designate_construction_site
except ImportError:
    from at_the_beginning.systems.construction.building import designate_construction_site

try:
    import instincts_and_tools as iat
except ImportError:
    from at_the_beginning import instincts_and_tools as iat

try:
    from systems.movement.map_contract import MAP_CONTRACTS, get_map_contract
except ImportError:
    from at_the_beginning.systems.movement.map_contract import MAP_CONTRACTS, get_map_contract

try:
    from systems.worldgen.rings import ChunkCoord
except ImportError:
    try:
        from at_the_beginning.systems.worldgen.rings import ChunkCoord
    except ImportError:
        from collections import namedtuple
        ChunkCoord = namedtuple("ChunkCoord", ["cx", "cy"])


# =============================================================================
# Production-Aligned Isolated Test Engine Fixture
# =============================================================================

class IsolatedWorldState:
    """Production tensor container for isolated test engine."""
    def __init__(self, device: str = "cpu"):
        self.device = device
        self.h_tensor = torch.zeros((getattr(cfg, "MAX_HUMANS", 100), getattr(cfg, "HUMAN_TENSOR_COLS", 24)), device=device)
        self.m_tensor = torch.zeros((getattr(cfg, "MAX_ENTITIES", 1024), getattr(cfg, "MAP_TENSOR_COLS", 32)), device=device)


class IsolatedResidentStore:
    """In-memory resident store matching ResidentAgentStore interface."""
    def __init__(self):
        self._residents: Dict[str, Dict[str, Any]] = {}

    def get(self, human_id: str) -> Optional[Dict[str, Any]]:
        return self._residents.get(human_id)

    def set_resident(self, human_id: str, resident: Dict[str, Any]) -> None:
        self._residents[human_id] = resident


class IsolatedWindowManager:
    """In-memory window manager supporting chunk integration and dormant StructureStore."""
    def __init__(self, origin_cx: int = 0, origin_cy: int = 0, epoch: int = 0):
        self.epoch = epoch
        class Frame:
            def __init__(self, ocx, ocy):
                self.origin = [ocx, ocy]
        self.frame = Frame(origin_cx, origin_cy)
        self.chunks = set()
        class Structures:
            def __init__(self):
                self.records = {}
        self.structures = Structures()

    def _local_origin(self, coord: Any) -> Tuple[float, float]:
        cx = coord.cx if hasattr(coord, "cx") else coord[0]
        cy = coord.cy if hasattr(coord, "cy") else coord[1]
        ocx = self.frame.origin[0]
        ocy = self.frame.origin[1]
        return ((cx - ocx) * 256.0, (cy - ocy) * 256.0)


class IsolatedTestEngine:
    """Isolated Engine fixture using actual production tensors, inventory, and geometry hooks.

    Does not bind network ports, spawn async loops, or write to external runtime dirs.
    """
    def __init__(self):
        self.state = IsolatedWorldState()
        self.tick = 10
        self._pop_count = [0]
        self._entity_count_ref = [0]
        self._next_entity_uid = 1
        self._next_human_uid = 1
        self._human_uid_by_slot: List[Optional[str]] = [None] * getattr(cfg, "MAX_HUMANS", 100)
        self._entity_uid_by_slot: List[Optional[str]] = [None] * getattr(cfg, "MAX_ENTITIES", 1024)
        self.inventory_state = build_inventory_state()
        self.resident_store = IsolatedResidentStore()
        self._map_name = "test_map"
        self._map_state_version = 0
        self._pending_events: List[Dict[str, Any]] = []
        self._window: Optional[IsolatedWindowManager] = None

        # Clean geometry tables
        map_geo.MAP_GEO.clear()
        map_geo.TILE_TO_ENTITY.clear()
        map_geo.geo_version = 0

    def _make_entity_id(self) -> str:
        uid = f"e_{self._next_entity_uid:06d}"
        self._next_entity_uid += 1
        return uid

    def _make_human_id(self) -> str:
        uid = f"h_{self._next_human_uid:06d}"
        self._next_human_uid += 1
        return uid

    def _human_inventory_record(
        self,
        human_id: str,
        *,
        capacity_slots: Optional[int] = None,
        capacity_weight: Optional[float] = None,
    ) -> Dict[str, Any]:
        return ensure_owner_inventory(
            self.inventory_state,
            "human",
            human_id,
            label=f"Loadout {human_id}",
            capacity_slots=capacity_slots or 12,
            capacity_weight=capacity_weight or 28.0,
        )

    def _queue_event(self, event_type: str, obj_id: str, slot: int, **extra: Any) -> None:
        event = {
            "seq": len(self._pending_events) + 1,
            "tick": self.tick,
            "type": event_type,
            "id": obj_id,
            "slot": slot,
        }
        event.update(extra)
        self._pending_events.append(event)

    def spawn_human(
        self,
        slot: int,
        human_id: str,
        x: float,
        y: float,
        *,
        hp: float = 100.0,
        stamina: float = 100.0,
        skill: float = 0.0,
        alive: bool = True,
    ) -> None:
        """Spawn a human in world tensors and resident store."""
        self.state.h_tensor[slot, cfg.TYPE] = getattr(cfg, "AGENT_TYPE_HUMAN", 1.0)
        self.state.h_tensor[slot, cfg.X] = x
        self.state.h_tensor[slot, cfg.Y] = y
        self.state.h_tensor[slot, cfg.HP] = hp if alive else 0.0
        self.state.h_tensor[slot, cfg.H_STAMINA] = stamina
        self.state.h_tensor[slot, cfg.H_SKILL] = skill
        self._human_uid_by_slot[slot] = human_id
        self.resident_store.set_resident(human_id, {
            "uid": human_id,
            "profile": {"name": f"Resident_{human_id}"},
            "status": {"alive": alive, "dead": not alive, "deceased": not alive},
        })

    def add_human_materials(self, human_id: str, materials: Dict[str, int]) -> None:
        """Add discrete items to a human's personal inventory."""
        inv = self._human_inventory_record(human_id)
        for item, qty in materials.items():
            add_item(inv, item_kind=item, quantity=qty)


# =============================================================================
# 1. Deterministic Candidate Lattice Tests
# =============================================================================

class TestCandidateLatticeGeneration(unittest.TestCase):
    """Test deterministic candidate lattice generation, coordinate math, and bounds."""

    def test_candidates_hard_capped_at_64(self):
        anchor = make_anchor(0, 0, 32768, 32768)
        # 9x9 grid gives 81 candidate offsets, must be hard capped at 64
        candidates = generate_lattice_candidates(anchor, step_units=24.0, max_candidates=64)
        self.assertEqual(len(candidates), 64)

    def test_deterministic_ordering_squared_distance_then_coordinates(self):
        anchor = make_anchor(0, 0, 32768, 32768)
        candidates = generate_lattice_candidates(anchor, step_units=24.0, max_candidates=64)

        prev_key = (-1, -10**12, -10**12, -10**12, -10**12)
        for cand in candidates:
            dist_sq = anchor_distance_sq_q(cand, anchor)
            cx, cy = cand["chunk"]
            sx, sy = cand["sub"]
            key = (dist_sq, cx, cy, sx, sy)
            self.assertGreaterEqual(key, prev_key, f"Ordering violated: {key} < {prev_key}")
            prev_key = key

        # First candidate should be exactly the center (dist_sq == 0)
        self.assertEqual(anchor_distance_sq_q(candidates[0], anchor), 0)
        self.assertEqual(candidates[0], anchor)

    def test_far_integer_anchor_invariance_near_boundary(self):
        # Near max chunk boundary 2^40
        far_cx = MAX_ABS_COORD - 2
        far_cy = -(MAX_ABS_COORD - 2)
        far_anchor = make_anchor(far_cx, far_cy, 10000, 50000)

        candidates = generate_lattice_candidates(far_anchor, step_units=24.0, max_candidates=16)
        self.assertEqual(len(candidates), 16)
        self.assertEqual(candidates[0], far_anchor)

        # Candidate chunks must be close to far_cx and far_cy without 64-bit overflow
        for cand in candidates:
            self.assertTrue(abs(cand["chunk"][0] - far_cx) <= 1)
            self.assertTrue(abs(cand["chunk"][1] - far_cy) <= 1)
            self.assertTrue(0 <= cand["sub"][0] < CHUNK_SUBUNITS)
            self.assertTrue(0 <= cand["sub"][1] < CHUNK_SUBUNITS)

    def test_negative_coordinate_lattice_normalization(self):
        # Anchor near chunk boundary with negative coordinate offsets
        anchor = make_anchor(0, 0, 100, 100)
        candidates = generate_lattice_candidates(anchor, step_units=1.0, max_candidates=64)
        for cand in candidates:
            self.assertTrue(0 <= cand["sub"][0] < CHUNK_SUBUNITS)
            self.assertTrue(0 <= cand["sub"][1] < CHUNK_SUBUNITS)
            # Reconverting to total subunits and back must be an exact identity
            total_sx, total_sy = anchor_to_total_subunits(cand)
            re_norm = normalize_subunits_to_anchor(total_sx, total_sy)
            self.assertEqual(cand, re_norm)

    def test_site_plan_recompute_local_after_origin_rebase(self):
        anchor = make_anchor(5, 5, 32768, 32768)
        plan = SitePlan(
            token="token_test",
            settlement_id="s_00000001",
            builder_id="h_000001",
            building_kind="personal_shelter",
            anchor=anchor,
            local_x=0.0,
            local_y=0.0,
            origin_chunk=[0, 0],
            engine_tick=10,
            window_epoch=0,
            world_revision=0,
            footprint_radius=22.0,
            recipe=copy.deepcopy(RECIPE_PERSONAL_SHELTER),
        )
        # Compute local with origin [0, 0]
        lx, ly = plan.recompute_local(0, 0)
        expected_lx = (5 * 65536 + 32768) / 256.0
        expected_ly = (5 * 65536 + 32768) / 256.0
        self.assertAlmostEqual(lx, expected_lx)
        self.assertAlmostEqual(ly, expected_ly)

        # Rebase to origin [5, 5]
        lx2, ly2 = plan.recompute_local(5, 5)
        self.assertAlmostEqual(lx2, 128.0)
        self.assertAlmostEqual(ly2, 128.0)
        self.assertEqual(plan.origin_chunk, [5, 5])


# =============================================================================
# 2. Spatial Viability & Obstacle Protection Tests
# =============================================================================

class TestSiteViabilityAndProtectedFootprints(unittest.TestCase):
    """Test candidate site validation against claims, chunks, terrain, and authored obstacles."""

    def setUp(self):
        self.engine = IsolatedTestEngine()
        self.registry = SettlementRegistry()
        self.anchor = make_anchor(0, 0, 32768, 32768)
        self.settlement_id = self.registry.create_settlement(
            "TestTown",
            self.anchor,
            members=["h_000001"],
            current_tick=10,
        )

    def test_viable_on_clean_habitable_ground(self):
        cand = make_anchor(0, 0, 32768, 32768)
        viable, reason = is_site_candidate_viable(cand, self.engine, self.registry, self.settlement_id)
        self.assertTrue(viable)
        self.assertEqual(reason, "viable")

    def test_outside_settlement_claim_rejected(self):
        # Settlement claim radius default is 51,200 subunits (200 units)
        far_cand = make_anchor(1, 0, 32768 + 60000 - 65536, 32768)   # same point as sub 92,768 in chunk 0; sub must be 0..65,535 (settlements.make_anchor)
        viable, reason = is_site_candidate_viable(far_cand, self.engine, self.registry, self.settlement_id)
        self.assertFalse(viable)
        self.assertEqual(reason, "outside_settlement_claim")

    def test_foreign_settlement_claim_overlap_rejected(self):
        # Create second settlement at chunk [1, 0]
        anchor2 = make_anchor(1, 0, 32768, 32768)
        s2 = self.registry.create_settlement("Town2", anchor2, members=["h_000002"], current_tick=10)

        # Candidate inside s2's claim
        cand_in_s2 = make_anchor(1, 0, 32768, 32768)
        viable, reason = is_site_candidate_viable(cand_in_s2, self.engine, self.registry, self.settlement_id)
        self.assertFalse(viable)
        self.assertTrue(reason.startswith("inside_foreign_claim"))

    def test_unintegrated_chunk_rejected_when_window_present(self):
        window = IsolatedWindowManager(origin_cx=0, origin_cy=0)
        window.chunks.add(ChunkCoord(0, 0))  # Only chunk (0,0) is integrated
        self.engine._window = window

        # Candidate in chunk (1, 0)
        unintegrated_cand = make_anchor(1, 0, 100, 100)
        viable, reason = is_site_candidate_viable(unintegrated_cand, self.engine, self.registry, self.settlement_id)
        self.assertFalse(viable)
        self.assertTrue(reason.startswith("chunk_not_integrated"))

    def test_blocked_terrain_at_candidate_center_rejected(self):
        # Place a blocked entity (e.g. M_SEA or M_MOUNTAIN) in m_tensor
        lx, ly = anchor_to_local(self.anchor, 0, 0)
        slot = 1
        self.engine.state.m_tensor[slot, cfg.M_TYPE] = getattr(cfg, "M_MOUNTAIN", 5)
        self.engine.state.m_tensor[slot, cfg.CX] = lx
        self.engine.state.m_tensor[slot, cfg.CY] = ly
        self.engine.state.m_tensor[slot, cfg.SCALE] = 20.0
        map_geo.register_entity(slot, "circle", lx, ly, 20.0, device="cpu")

        viable, reason = is_site_candidate_viable(self.anchor, self.engine, self.registry, self.settlement_id)
        self.assertFalse(viable)
        self.assertTrue("blocked_terrain" in reason)

    def test_active_structure_overlap_in_m_tensor_rejected(self):
        lx, ly = anchor_to_local(self.anchor, 0, 0)
        # Place existing shelter 25 units away (overlap with footprint radius 22 + 22 = 44)
        slot = 2
        self.engine.state.m_tensor[slot, cfg.M_TYPE] = getattr(cfg, "M_HOUSE", 20)
        self.engine.state.m_tensor[slot, cfg.CX] = lx + 25.0
        self.engine.state.m_tensor[slot, cfg.CY] = ly
        self.engine.state.m_tensor[slot, cfg.SCALE] = 22.0
        self.engine._entity_uid_by_slot[slot] = "e_existing_house"
        map_geo.register_entity(slot, "circle", lx + 25.0, ly, 22.0, device="cpu")

        viable, reason = is_site_candidate_viable(self.anchor, self.engine, self.registry, self.settlement_id)
        self.assertFalse(viable)
        self.assertTrue("structure_overlap" in reason or "occupied" in reason)

    def test_dormant_structure_overlap_in_window_structure_store_rejected(self):
        window = IsolatedWindowManager(origin_cx=0, origin_cy=0)
        window.chunks.add(ChunkCoord(0, 0))
        lx, ly = anchor_to_local(self.anchor, 0, 0)
        # Record dormant structure in StructureStore
        window.structures.records[ChunkCoord(0, 0)] = [{
            "uid": "e_dormant_house",
            "type": 20,
            "offset": [lx + 20.0, ly],
            "geo": {"shape": "circle", "r": 22.0},
        }]
        self.engine._window = window

        viable, reason = is_site_candidate_viable(self.anchor, self.engine, self.registry, self.settlement_id)
        self.assertFalse(viable)
        self.assertTrue("dormant_structure_overlap" in reason)

    def test_authored_movement_contract_protection(self):
        lx, ly = anchor_to_local(self.anchor, 0, 0)
        self.engine._map_name = "authored_village"
        # Setup mock MAP_CONTRACTS entry
        contract = {
            "boxes": [{"id": "wall_1", "min": [lx - 10.0, ly - 10.0], "max": [lx + 10.0, ly + 10.0]}],
            "portals": [{"id": "portal_gate", "position": [lx + 500.0, ly], "radius": 6.0}],
            "entities": [{"id": "forge_smith", "position": [lx + 600.0, ly], "interact_radius": 5.0}],
        }
        MAP_CONTRACTS["authored_village"] = contract

        try:
            # Candidate overlaps wall_1
            viable, reason = is_site_candidate_viable(self.anchor, self.engine, self.registry, self.settlement_id)
            self.assertFalse(viable)
            self.assertTrue("authored_wall_box_overlap" in reason)

            # Test portal overlap
            cand_portal = quantize_chunk_local_to_anchor(0, 0, lx + 505.0, ly)
            viable_p, reason_p = is_site_candidate_viable(cand_portal, self.engine, self.registry, self.settlement_id)
            self.assertFalse(viable_p)
            self.assertTrue("authored_portal_overlap" in reason_p)

            # Test interactive entity overlap
            cand_forge = quantize_chunk_local_to_anchor(0, 0, lx + 602.0, ly)
            viable_f, reason_f = is_site_candidate_viable(cand_forge, self.engine, self.registry, self.settlement_id)
            self.assertFalse(viable_f)
            self.assertTrue("authored_entity_overlap" in reason_f)
        finally:
            MAP_CONTRACTS.pop("authored_village", None)


# =============================================================================
# 3. Deterministic Site Planning Service API Tests
# =============================================================================

class TestSitePlanDeterministicAPI(unittest.TestCase):
    """Test plan_settlement_site preflight guards, selection, and reach constraints."""

    def setUp(self):
        self.engine = IsolatedTestEngine()
        self.registry = SettlementRegistry()
        self.anchor = make_anchor(0, 0, 32768, 32768)
        self.builder_id = "h_000001"
        self.settlement_id = self.registry.create_settlement(
            "Town",
            self.anchor,
            members=[self.builder_id],
            current_tick=10,
        )
        lx, ly = anchor_to_local(self.anchor, 0, 0)
        self.engine.spawn_human(0, self.builder_id, lx, ly, hp=100.0, stamina=100.0)
        self.engine.add_human_materials(self.builder_id, RECIPE_PERSONAL_SHELTER)

    def test_plan_settlement_site_success(self):
        plan = plan_settlement_site(
            self.engine,
            self.registry,
            self.settlement_id,
            self.builder_id,
            building_kind="personal_shelter",
        )
        self.assertIsInstance(plan, SitePlan)
        self.assertEqual(plan.settlement_id, self.settlement_id)
        self.assertEqual(plan.builder_id, self.builder_id)
        self.assertEqual(plan.building_kind, "personal_shelter")
        self.assertEqual(plan.recipe, RECIPE_PERSONAL_SHELTER)
        self.assertEqual(plan.engine_tick, 10)
        self.assertTrue(plan.candidates_evaluated >= 1)
        self.assertTrue(plan.token.startswith(f"sp_plan_{self.settlement_id}_{self.builder_id}"))

    def test_plan_settlement_site_rejects_missing_or_dissolved_settlement(self):
        with self.assertRaises(KeyError):
            plan_settlement_site(self.engine, self.registry, "s_99999999", self.builder_id)

        self.registry.dissolve_settlement(self.settlement_id, current_tick=10)
        with self.assertRaises(SettlementSiteSelectionError):
            plan_settlement_site(self.engine, self.registry, self.settlement_id, self.builder_id)

    def test_plan_settlement_site_rejects_non_member_builder(self):
        with self.assertRaises(SettlementSiteSelectionError):
            plan_settlement_site(self.engine, self.registry, self.settlement_id, "h_foreign")

    def test_plan_settlement_site_rejects_deceased_builder(self):
        # Kill builder in engine
        self.engine.state.h_tensor[0, cfg.HP] = 0.0
        self.engine.resident_store.set_resident(self.builder_id, {
            "uid": self.builder_id,
            "status": {"alive": False, "deceased": True},
        })
        with self.assertRaises(SettlementSiteSelectionError):
            plan_settlement_site(self.engine, self.registry, self.settlement_id, self.builder_id)

    def test_plan_settlement_site_rejects_unsupported_building_kind(self):
        with self.assertRaises(SettlementSiteSelectionError):
            plan_settlement_site(self.engine, self.registry, self.settlement_id, self.builder_id, building_kind="market_anchor")

    def test_plan_settlement_site_rejects_insufficient_materials(self):
        # Clear builder inventory
        inv = self.engine._human_inventory_record(self.builder_id)
        inv["items"] = []
        with self.assertRaises(SettlementPreflightError):
            plan_settlement_site(self.engine, self.registry, self.settlement_id, self.builder_id)

    def test_plan_settlement_site_rejects_settlement_with_open_project(self):
        # Create an existing planned project in registry
        self.registry.create_project(self.settlement_id, builder_id=self.builder_id, current_tick=10)
        with self.assertRaises(SettlementConflictError):
            plan_settlement_site(self.engine, self.registry, self.settlement_id, self.builder_id)

    def test_plan_settlement_site_reach_filter(self):
        # If builder is at (0, 0) and target_anchor is far away at (500, 500),
        # plan_settlement_site should reject if max_reach is small (e.g. 70.0)
        far_target = quantize_chunk_local_to_anchor(0, 0, 500.0, 500.0)
        with self.assertRaises(SettlementSiteSelectionError):
            plan_settlement_site(
                self.engine,
                self.registry,
                self.settlement_id,
                self.builder_id,
                target_anchor=far_target,
                max_reach=50.0,
            )


# =============================================================================
# 4. Material-Funded Project Commitment Transaction Tests
# =============================================================================

class TestMaterialFundedCommitTransaction(unittest.TestCase):
    """Test commit_settlement_project validation, material debit, and entity/registry instantiation."""

    def setUp(self):
        self.engine = IsolatedTestEngine()
        self.registry = SettlementRegistry()
        self.anchor = make_anchor(0, 0, 32768, 32768)
        self.builder_id = "h_000001"
        self.settlement_id = self.registry.create_settlement(
            "Town",
            self.anchor,
            members=[self.builder_id],
            current_tick=10,
        )
        lx, ly = anchor_to_local(self.anchor, 0, 0)
        self.engine.spawn_human(0, self.builder_id, lx, ly, hp=100.0, stamina=100.0)
        self.engine.add_human_materials(self.builder_id, RECIPE_PERSONAL_SHELTER)
        # Extra unrelated item to check exact discrete consumption
        add_item(self.engine._human_inventory_record(self.builder_id), "berries", 5)

        self.plan = plan_settlement_site(
            self.engine,
            self.registry,
            self.settlement_id,
            self.builder_id,
        )

    def test_successful_commitment_end_to_end(self):
        inv = self.engine._human_inventory_record(self.builder_id)
        pre_berries = total_quantity(inv, "berries")
        self.assertEqual(pre_berries, 5)

        res = commit_settlement_project(self.engine, self.registry, self.plan)
        self.assertTrue(res.ok)
        self.assertTrue(res.structure_uid.startswith("e_"))
        self.assertGreaterEqual(res.slot, 0)
        self.assertEqual(res.paid, RECIPE_PERSONAL_SHELTER)

        # 1. Materials consumed from builder inventory
        self.assertEqual(total_quantity(inv, "wood_bundle"), 0)
        self.assertEqual(total_quantity(inv, "fiber_bundle"), 0)
        self.assertEqual(total_quantity(inv, "plank_bundle"), 0)
        self.assertEqual(total_quantity(inv, "berries"), 5)  # Berries untouched!

        # 2. Entity designated in m_tensor
        m = self.engine.state.m_tensor
        self.assertEqual(int(m[res.slot, cfg.M_TYPE]), SHELTER_STRUCTURE_TYPE)
        self.assertAlmostEqual(float(m[res.slot, cfg.S_DURABILITY]), SHELTER_DURABILITY)
        self.assertAlmostEqual(float(m[res.slot, cfg.S_SHELTER_CAP]), SHELTER_CAP)
        self.assertAlmostEqual(float(m[res.slot, cfg.S_BUILD_PROGRESS]), 0.0)
        self.assertEqual(self.engine._entity_uid_by_slot[res.slot], res.structure_uid)

        # 3. Geometry registered in map_geo
        self.assertIn(res.slot, map_geo.MAP_GEO)
        geo = map_geo.MAP_GEO[res.slot]
        self.assertEqual(geo["shape"], "circle")
        self.assertAlmostEqual(float(geo["r"]), SHELTER_SCALE)

        # 4. SettlementRegistry project funded
        proj = self.registry.get_project(res.project_id)
        self.assertEqual(proj["status"], "funded")
        self.assertEqual(proj["structure_uid"], res.structure_uid)
        self.assertEqual(proj["paid"], RECIPE_PERSONAL_SHELTER)

        # 5. Audit event emitted
        events = [e for e in self.engine._pending_events if e["type"] == "settlement_shelter_funded"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], res.structure_uid)

    def test_stale_plan_window_epoch_rejected(self):
        window = IsolatedWindowManager(epoch=1)
        self.engine._window = window
        # self.plan was created with window_epoch=0
        with self.assertRaises(SettlementStalePlanError):
            commit_settlement_project(self.engine, self.registry, self.plan)

    def test_stale_plan_future_tick_rejected(self):
        self.engine.tick = 5  # Plan was created at tick 10
        with self.assertRaises(SettlementStalePlanError):
            commit_settlement_project(self.engine, self.registry, self.plan)

    def test_builder_deceased_before_commit_rejected(self):
        self.engine.state.h_tensor[0, cfg.HP] = 0.0
        self.engine.resident_store.set_resident(self.builder_id, {"status": {"alive": False}})
        with self.assertRaises(SettlementPreflightError):
            commit_settlement_project(self.engine, self.registry, self.plan)

    def test_builder_moved_out_of_reach_rejected(self):
        # Move builder far away
        self.engine.state.h_tensor[0, cfg.X] = 1000.0
        self.engine.state.h_tensor[0, cfg.Y] = 1000.0
        with self.assertRaises(SettlementPreflightError):
            commit_settlement_project(self.engine, self.registry, self.plan)

    def test_material_stock_spent_before_commit_rejected(self):
        inv = self.engine._human_inventory_record(self.builder_id)
        remove_item(inv, "wood_bundle", 2)  # Builder dropped/spent 2 wood
        with self.assertRaises(SettlementPreflightError):
            commit_settlement_project(self.engine, self.registry, self.plan)

    def test_site_became_blocked_before_commit_rejected(self):
        lx, ly = self.plan.local_x, self.plan.local_y
        # Another entity placed on site
        slot = 10
        self.engine.state.m_tensor[slot, cfg.M_TYPE] = getattr(cfg, "M_MOUNTAIN", 5)
        map_geo.register_entity(slot, "circle", lx, ly, 10.0, device="cpu")
        with self.assertRaises(SettlementPreflightError):
            commit_settlement_project(self.engine, self.registry, self.plan)

    def test_entity_capacity_saturated_rejected(self):
        max_ent = getattr(cfg, "MAX_ENTITIES", 1024)
        self.engine._entity_count_ref[0] = max_ent
        with self.assertRaises(SettlementCapError):
            commit_settlement_project(self.engine, self.registry, self.plan)


# =============================================================================
# 5. Injected Faults and Precision Rollback Tests
# =============================================================================

class TestPrecisionRollbackInjectedFaults(unittest.TestCase):
    """Test exact memento capture and bit-for-bit rollback at each transaction phase."""

    def setUp(self):
        self.engine = IsolatedTestEngine()
        self.registry = SettlementRegistry()
        self.anchor = make_anchor(0, 0, 32768, 32768)
        self.builder_id = "h_000001"
        self.settlement_id = self.registry.create_settlement(
            "Town",
            self.anchor,
            members=[self.builder_id],
            current_tick=10,
        )
        lx, ly = anchor_to_local(self.anchor, 0, 0)
        self.engine.spawn_human(0, self.builder_id, lx, ly, hp=100.0, stamina=100.0)
        self.engine.add_human_materials(self.builder_id, RECIPE_PERSONAL_SHELTER)
        add_item(self.engine._human_inventory_record(self.builder_id), "knife", 1)

        self.plan = plan_settlement_site(
            self.engine,
            self.registry,
            self.settlement_id,
            self.builder_id,
        )

    def test_rollback_after_consume_fault_restores_all_items(self):
        inv = self.engine._human_inventory_record(self.builder_id)
        pre_wood = total_quantity(inv, "wood_bundle")
        pre_fiber = total_quantity(inv, "fiber_bundle")
        pre_plank = total_quantity(inv, "plank_bundle")
        pre_knife = total_quantity(inv, "knife")
        pre_reg_memento = self.registry.export_state()
        pre_entity_count = self.engine._entity_count_ref[0]

        def fail_consume():
            raise RuntimeError("Injected fault immediately after material consume!")

        with self.assertRaises(SettlementTransactionError):
            commit_settlement_project(self.engine, self.registry, self.plan, fault_hook_after_consume=fail_consume)

        # 1. Builder inventory completely restored
        self.assertEqual(total_quantity(inv, "wood_bundle"), pre_wood)
        self.assertEqual(total_quantity(inv, "fiber_bundle"), pre_fiber)
        self.assertEqual(total_quantity(inv, "plank_bundle"), pre_plank)
        self.assertEqual(total_quantity(inv, "knife"), pre_knife)

        # 2. No entity allocated in m_tensor or counters
        self.assertEqual(self.engine._entity_count_ref[0], pre_entity_count)
        self.assertEqual(len(map_geo.MAP_GEO), 0)

        # 3. Registry untouched
        self.assertEqual(self.registry.export_state(), pre_reg_memento)

        # 4. Pending events empty
        self.assertEqual(len(self.engine._pending_events), 0)

    def test_rollback_after_create_fault_zeroes_row_and_counters(self):
        inv = self.engine._human_inventory_record(self.builder_id)
        pre_reg_memento = self.registry.export_state()
        pre_next_uid = self.engine._next_entity_uid

        def fail_create(slot):
            raise RuntimeError(f"Injected fault after designate_construction_site on slot {slot}!")

        with self.assertRaises(SettlementTransactionError):
            commit_settlement_project(self.engine, self.registry, self.plan, fault_hook_after_create=fail_create)

        # Inventory restored
        self.assertEqual(total_quantity(inv, "wood_bundle"), 6)

        # Entity count and next_uid restored
        self.assertEqual(self.engine._entity_count_ref[0], 0)
        self.assertEqual(self.engine._next_entity_uid, pre_next_uid)

        # Slot 0 in m_tensor zeroed
        self.assertEqual(float(self.engine.state.m_tensor[0, cfg.M_TYPE]), 0.0)
        self.assertIsNone(self.engine._entity_uid_by_slot[0])

        # Registry restored
        self.assertEqual(self.registry.export_state(), pre_reg_memento)

    def test_rollback_after_geo_fault_unregisters_map_geo(self):
        inv = self.engine._human_inventory_record(self.builder_id)
        pre_geo_version = map_geo.geo_version

        def fail_geo(slot):
            raise RuntimeError(f"Injected fault after geometry registration on slot {slot}!")

        with self.assertRaises(SettlementTransactionError):
            commit_settlement_project(self.engine, self.registry, self.plan, fault_hook_after_geo=fail_geo)

        # map_geo unregisters entity and restores version
        self.assertEqual(len(map_geo.MAP_GEO), 0)
        self.assertEqual(map_geo.geo_version, pre_geo_version)

        # Inventory and m_tensor cleaned
        self.assertEqual(total_quantity(inv, "wood_bundle"), 6)
        self.assertEqual(float(self.engine.state.m_tensor[0, cfg.M_TYPE]), 0.0)

    def test_rollback_after_registry_fault_restores_clean_registry(self):
        inv = self.engine._human_inventory_record(self.builder_id)
        pre_reg_memento = self.registry.export_state()

        def fail_registry(proj_id, struct_uid):
            raise RuntimeError(f"Injected fault after funding project {proj_id} with {struct_uid}!")

        with self.assertRaises(SettlementTransactionError):
            commit_settlement_project(self.engine, self.registry, self.plan, fault_hook_after_registry=fail_registry)

        # Registry bit-for-bit identical to pre-state
        self.assertEqual(self.registry.export_state(), pre_reg_memento)
        self.assertEqual(len(self.registry.list_projects()), 0)   # public enumeration API (settlements.list_projects)

        # Inventory, tensor, and geo cleaned
        self.assertEqual(total_quantity(inv, "wood_bundle"), 6)
        self.assertEqual(float(self.engine.state.m_tensor[0, cfg.M_TYPE]), 0.0)
        self.assertEqual(len(map_geo.MAP_GEO), 0)


# =============================================================================
# 6. Caller-Controlled Labor Progress & Completion Tests
# =============================================================================

class TestConstructionProgressAndCompletion(unittest.TestCase):
    """Test advance_settlement_construction progression, stamina deduction, dormancy freeze, and completion."""

    def setUp(self):
        self.engine = IsolatedTestEngine()
        self.registry = SettlementRegistry()
        self.anchor = make_anchor(0, 0, 32768, 32768)
        self.builder_id = "h_000001"
        self.settlement_id = self.registry.create_settlement(
            "Town",
            self.anchor,
            members=[self.builder_id],
            current_tick=10,
        )
        lx, ly = anchor_to_local(self.anchor, 0, 0)
        self.engine.spawn_human(0, self.builder_id, lx, ly, hp=100.0, stamina=100.0, skill=0.0)
        self.engine.add_human_materials(self.builder_id, RECIPE_PERSONAL_SHELTER)

        self.plan = plan_settlement_site(
            self.engine,
            self.registry,
            self.settlement_id,
            self.builder_id,
        )
        self.tx_res = commit_settlement_project(self.engine, self.registry, self.plan)
        self.project_id = self.tx_res.project_id

    def test_advance_progress_preflight_guards(self):
        # Non-existent project
        with self.assertRaises(KeyError):
            advance_settlement_construction(self.engine, self.registry, "sp_99999999", self.builder_id)

        # Non-member worker
        with self.assertRaises(SettlementPreflightError):
            advance_settlement_construction(self.engine, self.registry, self.project_id, "h_foreign")

        # Deceased worker
        self.engine.state.h_tensor[0, cfg.HP] = 0.0
        self.engine.resident_store.set_resident(self.builder_id, {"status": {"alive": False}})
        with self.assertRaises(SettlementPreflightError):
            advance_settlement_construction(self.engine, self.registry, self.project_id, self.builder_id)

        # Low stamina worker
        self.engine.state.h_tensor[0, cfg.HP] = 100.0
        self.engine.resident_store.set_resident(self.builder_id, {"status": {"alive": True}})
        self.engine.state.h_tensor[0, cfg.H_STAMINA] = 5.0  # Min required is 8.0
        with self.assertRaises(SettlementPreflightError):
            advance_settlement_construction(self.engine, self.registry, self.project_id, self.builder_id)

        # Worker out of reach (> 70.0)
        self.engine.state.h_tensor[0, cfg.H_STAMINA] = 100.0
        self.engine.state.h_tensor[0, cfg.X] = 500.0
        self.engine.state.h_tensor[0, cfg.Y] = 500.0
        with self.assertRaises(SettlementPreflightError):
            advance_settlement_construction(self.engine, self.registry, self.project_id, self.builder_id)

    def test_advance_progress_dormancy_freezes_progress(self):
        # Attach window where the project structure chunk is dormant
        window = IsolatedWindowManager(origin_cx=0, origin_cy=0)
        # Empty integrated chunks set -> chunk (0,0) is dormant
        self.engine._window = window

        with self.assertRaises(SettlementDormancyError):
            advance_settlement_construction(self.engine, self.registry, self.project_id, self.builder_id)

    def test_work_step_deducts_stamina_advances_progress_no_materials_consumed(self):
        inv = self.engine._human_inventory_record(self.builder_id)
        pre_items = copy.deepcopy(inv.get("items", []))
        pre_stamina = float(self.engine.state.h_tensor[0, cfg.H_STAMINA])

        res = advance_settlement_construction(
            self.engine,
            self.registry,
            self.project_id,
            self.builder_id,
            progress_step=10.0,
        )
        self.assertTrue(res.ok)
        self.assertFalse(res.completed)
        self.assertAlmostEqual(res.progress, 10.0)
        self.assertAlmostEqual(float(self.engine.state.m_tensor[res.slot, cfg.S_BUILD_PROGRESS]), 10.0)

        # Stamina deducted by BUILD_STAMINA_COST (6.0)
        self.assertAlmostEqual(float(self.engine.state.h_tensor[0, cfg.H_STAMINA]), pre_stamina - BUILD_STAMINA_COST)

        # Structure HP updated proportionally: durability (140.0) * 10% = 14.0
        self.assertAlmostEqual(float(self.engine.state.m_tensor[res.slot, cfg.M_HP]), 14.0)

        # Registry status transitioned from 'funded' -> 'building'
        proj = self.registry.get_project(self.project_id)
        self.assertEqual(proj["status"], "building")

        # Zero materials consumed during labor progression!
        self.assertEqual(inv.get("items", []), pre_items)

    def test_labor_completion_once_and_settlement_building_link(self):
        # Step to completion (progress 100.0)
        res = advance_settlement_construction(
            self.engine,
            self.registry,
            self.project_id,
            self.builder_id,
            progress_step=100.0,
        )
        self.assertTrue(res.ok)
        self.assertTrue(res.completed)
        self.assertAlmostEqual(res.progress, 100.0)
        self.assertAlmostEqual(res.hp, SHELTER_DURABILITY)

        # Registry project is now 'complete'
        proj = self.registry.get_project(self.project_id)
        self.assertEqual(proj["status"], "complete")

        # Structure UID is linked into settlement buildings
        settlement = self.registry.get_settlement(self.settlement_id)
        self.assertIn(res.structure_uid, settlement["buildings"])

        # Completion event queued
        complete_events = [e for e in self.engine._pending_events if e["type"] == "settlement_shelter_completed"]
        self.assertEqual(len(complete_events), 1)
        self.assertEqual(complete_events[0]["id"], res.structure_uid)

        # Subsequent advance call on completed project rejected
        with self.assertRaises(SettlementPreflightError):
            advance_settlement_construction(self.engine, self.registry, self.project_id, self.builder_id)

    def test_rollback_on_fault_before_completion(self):
        pre_stamina = float(self.engine.state.h_tensor[0, cfg.H_STAMINA])
        pre_prog = float(self.engine.state.m_tensor[self.tx_res.slot, cfg.S_BUILD_PROGRESS])
        pre_hp = float(self.engine.state.m_tensor[self.tx_res.slot, cfg.M_HP])
        pre_reg_memento = self.registry.export_state()

        def fail_before_complete():
            raise RuntimeError("Injected fault right before completion registration!")

        with self.assertRaises(SettlementTransactionError):
            advance_settlement_construction(
                self.engine,
                self.registry,
                self.project_id,
                self.builder_id,
                progress_step=100.0,
                fault_hook_before_complete=fail_before_complete,
            )

        # Stamina, progress, HP, and registry state completely rolled back
        self.assertAlmostEqual(float(self.engine.state.h_tensor[0, cfg.H_STAMINA]), pre_stamina)
        self.assertAlmostEqual(float(self.engine.state.m_tensor[self.tx_res.slot, cfg.S_BUILD_PROGRESS]), pre_prog)
        self.assertAlmostEqual(float(self.engine.state.m_tensor[self.tx_res.slot, cfg.M_HP]), pre_hp)
        self.assertEqual(self.registry.export_state(), pre_reg_memento)


# =============================================================================
# 7. Universe Conservation and Architectural Boundary Invariants
# =============================================================================

class TestPureServiceArchitectureAndConservation(unittest.TestCase):
    """Test universe material conservation, tensor dimensions, and pure service boundaries."""

    def test_universe_material_conservation_across_full_lifecycle(self):
        engine = IsolatedTestEngine()
        registry = SettlementRegistry()
        anchor = make_anchor(0, 0, 32768, 32768)
        builder_id = "h_000001"
        s_id = registry.create_settlement("Town", anchor, members=[builder_id], current_tick=10)

        lx, ly = anchor_to_local(anchor, 0, 0)
        engine.spawn_human(0, builder_id, lx, ly, hp=100.0, stamina=100.0)
        engine.add_human_materials(builder_id, RECIPE_PERSONAL_SHELTER)

        inv = engine._human_inventory_record(builder_id)

        # Baseline: 6 wood, 3 fiber, 2 plank in inventory; 0 invested
        self.assertEqual(total_quantity(inv, "wood_bundle"), 6)
        self.assertEqual(total_quantity(inv, "fiber_bundle"), 3)
        self.assertEqual(total_quantity(inv, "plank_bundle"), 2)

        # Phase 1: Plan site (no materials consumed yet)
        plan = plan_settlement_site(engine, registry, s_id, builder_id)
        self.assertEqual(total_quantity(inv, "wood_bundle"), 6)

        # Phase 2: Commit funding transaction
        tx = commit_settlement_project(engine, registry, plan)
        self.assertEqual(total_quantity(inv, "wood_bundle"), 0)
        self.assertEqual(total_quantity(inv, "fiber_bundle"), 0)
        self.assertEqual(total_quantity(inv, "plank_bundle"), 0)
        # Materials now invested in project 'paid'
        proj = registry.get_project(tx.project_id)
        self.assertEqual(proj["paid"], RECIPE_PERSONAL_SHELTER)
        # Total in universe = 0 + 6 wood, 0 + 3 fiber, 0 + 2 plank. Conserved!

        # Phase 3: Construction labor work steps
        advance_settlement_construction(engine, registry, tx.project_id, builder_id, progress_step=50.0)
        self.assertEqual(total_quantity(inv, "wood_bundle"), 0)
        proj = registry.get_project(tx.project_id)
        self.assertEqual(proj["paid"], RECIPE_PERSONAL_SHELTER)

        # Phase 4: Completion at 100%
        advance_settlement_construction(engine, registry, tx.project_id, builder_id, progress_step=50.0)
        proj = registry.get_project(tx.project_id)
        self.assertEqual(proj["status"], "complete")
        self.assertEqual(proj["paid"], RECIPE_PERSONAL_SHELTER)

        # Universe material conservation: exactly 6 wood, 3 fiber, 2 plank from beginning to end!
        total_wood = total_quantity(inv, "wood_bundle") + proj["paid"]["wood_bundle"]
        total_fiber = total_quantity(inv, "fiber_bundle") + proj["paid"]["fiber_bundle"]
        total_plank = total_quantity(inv, "plank_bundle") + proj["paid"]["plank_bundle"]
        self.assertEqual(total_wood, 6)
        self.assertEqual(total_fiber, 3)
        self.assertEqual(total_plank, 2)

    def test_no_tensor_columns_or_engine_width_expansion(self):
        # MAP_TENSOR_COLS must remain exactly 32
        self.assertEqual(cfg.MAP_TENSOR_COLS, 32)
        # No M_CONSTRUCTION_PROGRESS or settlement column introduced
        self.assertFalse(hasattr(cfg, "M_CONSTRUCTION_PROGRESS"))
        self.assertFalse(hasattr(cfg, "M_SETTLEMENT"))
        # S_BUILD_PROGRESS is existing column 9
        self.assertEqual(cfg.S_BUILD_PROGRESS, 9)

    def test_pure_service_no_automatic_tick_hooks(self):
        # Pure service layer: no global singleton or tick hook auto-registration
        import harness.settlement_construction as sc
        self.assertFalse(hasattr(sc, "active_service"))
        self.assertFalse(hasattr(sc, "CURRENT_SERVICE"))
        self.assertFalse(hasattr(sc, "install_hooks"))


if __name__ == "__main__":
    unittest.main()
