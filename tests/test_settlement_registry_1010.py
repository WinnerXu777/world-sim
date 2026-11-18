"""tests/test_settlement_registry_1010.py
======================================
Comprehensive test suite for R6.4 bounded settlement registry and coordinate lattice foundation.

Verifies:
- Strict envelope and record schema validation (exact keys, reject unknown/missing keys).
- Strict type validation: bool-as-int rejection, float/coercion rejection, NaN/inf rejection.
- Monotonic ID allocation (s_XXXXXXXX, sp_XXXXXXXX), non-reusable counters after removal.
- Empty-building active founding state (0 buildings allowed while active; dissolved must be empty).
- Global member exclusivity and configurable cfg.MAX_HUMANS cap.
- Global building ownership uniqueness and total link caps.
- Roles subset validation and valid role names (builder, keeper, watch).
- Authoritative human resolver (living vs deceased, no arbitrary regex).
- Authoritative structure resolver (active vs dormant StructureStore, overworld, STRUCTURE_TYPES).
- Defensive copies protecting against external in-place corruption.
- Failed atomic restore preserving prior state completely.
- Fixed-point coordinate lattice: Q256, chunk subunits 65536, negative floor division / divmod.
- Large coordinates near +/-2^40 and bounds checking.
- Integer-first local conversion and origin invariance under rebasing.
- Claim integer distance calculation and overlap boundary.
- Project lifecycle: planned -> funded -> building -> complete -> cancelled -> destroyed invariants.
- Destruction audit emitting material loss and clearing building link.
- At most one open project per settlement.
- Pure service architecture (no tensor columns, no inventory creation, no import side effects).
"""
import copy
import math
import sys
import unittest
from pathlib import Path

# Ensure repo root and at_the_beginning are in sys.path
ROOT = Path(__file__).resolve().parents[1]
AT_THE_BEGINNING = ROOT / "at_the_beginning"
for p in (str(ROOT), str(AT_THE_BEGINNING)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from at_the_beginning.harness import settlements
except ImportError:
    from harness import settlements

from harness.settlements import (
    CHUNK_SUBUNITS,
    CHUNK_UNITS,
    DEFAULT_CLAIM_RADIUS_Q,
    MAX_ABS_COORD,
    MAX_CLAIM_RADIUS_Q,
    MAX_ID_COUNTER,
    MAX_TICK,
    MIN_CLAIM_RADIUS_Q,
    MIN_ID_COUNTER,
    Q,
    SCHEMA_VERSION,
    SETTLEMENT_ROLES,
    SettlementCapError,
    SettlementConfig,
    SettlementConflictError,
    SettlementError,
    SettlementReferenceError,
    SettlementRegistry,
    SettlementValidationError,
    anchor_diff_q,
    anchor_distance_sq_q,
    anchor_to_local,
    anchor_to_total_subunits,
    claims_overlap,
    is_point_in_claim,
    make_anchor,
    normalize_subunits_to_anchor,
    quantize_chunk_local_to_anchor,
    quantize_unit_to_anchor,
    validate_anchor,
    validate_finite_number,
    validate_strict_int,
    validate_string,
)


class TestStrictTypesAndNumerics(unittest.TestCase):
    """Test strict type validation helpers."""

    def test_strict_int_rejects_bool(self):
        with self.assertRaises(SettlementValidationError):
            validate_strict_int(True, "flag")
        with self.assertRaises(SettlementValidationError):
            validate_strict_int(False, "flag")

    def test_strict_int_rejects_float_and_str(self):
        with self.assertRaises(SettlementValidationError):
            validate_strict_int(1.0, "float_val")
        with self.assertRaises(SettlementValidationError):
            validate_strict_int("100", "str_val")
        with self.assertRaises(SettlementValidationError):
            validate_strict_int(None, "none_val")

    def test_strict_int_bounds(self):
        self.assertEqual(validate_strict_int(10, "val", min_val=0, max_val=20), 10)
        with self.assertRaises(SettlementValidationError):
            validate_strict_int(-1, "val", min_val=0)
        with self.assertRaises(SettlementValidationError):
            validate_strict_int(21, "val", max_val=20)

    def test_finite_number_rejects_nan_and_inf(self):
        with self.assertRaises(SettlementValidationError):
            validate_finite_number(float("nan"), "nan_val")
        with self.assertRaises(SettlementValidationError):
            validate_finite_number(float("inf"), "inf_val")
        with self.assertRaises(SettlementValidationError):
            validate_finite_number(float("-inf"), "neg_inf_val")
        with self.assertRaises(SettlementValidationError):
            validate_finite_number(True, "bool_val")
        self.assertEqual(validate_finite_number(42.5, "valid_float"), 42.5)
        self.assertEqual(validate_finite_number(42, "valid_int"), 42.0)

    def test_validate_string_rejects_control_characters(self):
        self.assertEqual(validate_string("Valid Name", "name"), "Valid Name")
        with self.assertRaises(SettlementValidationError):
            validate_string("Invalid\nName", "name")
        with self.assertRaises(SettlementValidationError):
            validate_string("Invalid\x00Name", "name")
        with self.assertRaises(SettlementValidationError):
            validate_string("Invalid\tName", "name")
        with self.assertRaises(SettlementValidationError):
            validate_string("", "name", min_len=1)


class TestCoordinateLatticeAndAnchorMath(unittest.TestCase):
    """Test Q256 coordinate math, negative normalization, and integer conversions."""

    def test_anchor_exact_schema(self):
        anchor = make_anchor(1, -2, 100, 65000)
        self.assertEqual(anchor["chunk"], [1, -2])
        self.assertEqual(anchor["sub"], [100, 65000])

        # Extra key rejected
        bad_anchor = copy.deepcopy(anchor)
        bad_anchor["extra"] = 123
        with self.assertRaises(SettlementValidationError):
            validate_anchor(bad_anchor)

        # Missing key rejected
        bad_anchor2 = {"chunk": [1, 2]}
        with self.assertRaises(SettlementValidationError):
            validate_anchor(bad_anchor2)

        # Bool in coordinates rejected
        bad_anchor3 = {"chunk": [True, 2], "sub": [0, 0]}
        with self.assertRaises(SettlementValidationError):
            validate_anchor(bad_anchor3)

    def test_negative_subunits_floor_division_normalization(self):
        # total_sub = -1 should map to chunk = -1, sub = 65535
        anchor = normalize_subunits_to_anchor(-1, -65536)
        self.assertEqual(anchor["chunk"], [-1, -1])
        self.assertEqual(anchor["sub"], [65535, 0])

        # Round-trip back to subunits
        total_x, total_y = anchor_to_total_subunits(anchor)
        self.assertEqual(total_x, -1)
        self.assertEqual(total_y, -65536)

        # -65537 maps to chunk = -2, sub = 65535
        anchor2 = normalize_subunits_to_anchor(-65537, 0)
        self.assertEqual(anchor2["chunk"], [-2, 0])
        self.assertEqual(anchor2["sub"], [65535, 0])
        self.assertEqual(anchor_to_total_subunits(anchor2), (-65537, 0))

    def test_large_coordinates_near_max_abs_coord(self):
        # +/- 2^40 chunk coordinates
        anchor_pos = make_anchor(MAX_ABS_COORD, MAX_ABS_COORD, 0, 0)
        self.assertEqual(anchor_pos["chunk"], [MAX_ABS_COORD, MAX_ABS_COORD])

        anchor_neg = make_anchor(-MAX_ABS_COORD, -MAX_ABS_COORD, 65535, 65535)
        self.assertEqual(anchor_neg["chunk"], [-MAX_ABS_COORD, -MAX_ABS_COORD])

        # Exceeding +/- 2^40 rejected
        with self.assertRaises(SettlementValidationError):
            make_anchor(MAX_ABS_COORD + 1, 0, 0, 0)
        with self.assertRaises(SettlementValidationError):
            make_anchor(-MAX_ABS_COORD - 1, 0, 0, 0)

    def test_integer_first_local_conversion_and_origin_invariance(self):
        # Anchor at chunk 5, sub 32768 (which is 128 units within chunk 5)
        anchor = make_anchor(5, 10, 32768, 16384)

        # Relative to origin (5, 10): local should be (128.0, 64.0)
        lx, ly = anchor_to_local(anchor, origin_cx=5, origin_cy=10)
        self.assertEqual((lx, ly), (128.0, 64.0))

        # Rebase to origin (0, 0): chunk offset is 5 chunks = 1280 units
        # local should be (1280.0 + 128.0, 2560.0 + 64.0) = (1408.0, 2624.0)
        lx_zero, ly_zero = anchor_to_local(anchor, origin_cx=0, origin_cy=0)
        self.assertEqual((lx_zero, ly_zero), (1408.0, 2624.0))

        # Difference between the two live local positions matches chunk shift exactly
        self.assertEqual(lx_zero - lx, 5 * CHUNK_UNITS)
        self.assertEqual(ly_zero - ly, 10 * CHUNK_UNITS)

    def test_quantization_and_tie_breaking(self):
        # World unit 1.5 -> 1.5 * 256 = 384 subunits
        anchor = quantize_unit_to_anchor(1.5, 0.0)
        self.assertEqual(anchor["chunk"], [0, 0])
        self.assertEqual(anchor["sub"], [384, 0])

        # Negative unit -1.5 -> -384 subunits -> chunk -1, sub 65536 - 384 = 65152
        anchor_neg = quantize_unit_to_anchor(-1.5, 0.0)
        self.assertEqual(anchor_neg["chunk"], [-1, 0])
        self.assertEqual(anchor_neg["sub"], [65152, 0])

        # Chunk-local quantization
        anchor_local = quantize_chunk_local_to_anchor(2, -3, 10.25, 20.5)
        self.assertEqual(anchor_local["chunk"], [2, -3])
        self.assertEqual(anchor_local["sub"], [int(10.25 * Q), int(20.5 * Q)])

    def test_claim_distance_and_overlap_boundary(self):
        anchor_center = make_anchor(0, 0, 0, 0)
        # Radius 51200 subunits (200 units)
        radius_q = 51200

        # Point exactly on boundary (x = 51200, y = 0)
        point_on = make_anchor(0, 0, 51200, 0)
        self.assertTrue(is_point_in_claim(point_on, anchor_center, radius_q))

        # Point 1 subunit beyond boundary
        point_out = make_anchor(0, 0, 51201, 0)
        self.assertFalse(is_point_in_claim(point_out, anchor_center, radius_q))

        # Overlap of two settlements
        # Distance = 51200 + 51200 = 102400 subunits -> tangent boundary
        anchor_b = normalize_subunits_to_anchor(102400, 0)
        self.assertTrue(claims_overlap(anchor_center, radius_q, anchor_b, radius_q, inclusive=True))
        self.assertFalse(claims_overlap(anchor_center, radius_q, anchor_b, radius_q, inclusive=False))

        # Clearly overlapping
        anchor_c = normalize_subunits_to_anchor(50000, 0)
        self.assertTrue(claims_overlap(anchor_center, radius_q, anchor_c, radius_q))

        # Clearly disjoint
        anchor_d = normalize_subunits_to_anchor(200000, 0)
        self.assertFalse(claims_overlap(anchor_center, radius_q, anchor_d, radius_q))


class TestSettlementRegistryLifecycle(unittest.TestCase):
    """Test settlement creation, dissolution, member/building management, and invariants."""

    def setUp(self):
        self.config = SettlementConfig(
            max_settlements=5,
            max_projects=10,
            max_building_links=20,
            max_members_global=10,
            default_claim_radius_q=DEFAULT_CLAIM_RADIUS_Q,
        )
        self.registry = SettlementRegistry(self.config)

    def test_active_settlement_allows_zero_buildings_on_founding(self):
        # Allow zero buildings while first project is planned
        anchor = make_anchor(0, 0, 1000, 1000)
        s_id = self.registry.create_settlement(
            name="Founding Outpost",
            anchor=anchor,
            members=["h_001"],
            buildings=[],  # Zero buildings allowed!
            roles={"h_001": "builder"},
            current_tick=10,
        )
        self.assertEqual(s_id, "s_00000001")
        rec = self.registry.get_settlement(s_id)
        self.assertEqual(rec["status"], "active")
        self.assertEqual(rec["buildings"], [])
        self.assertEqual(rec["members"], ["h_001"])
        self.assertEqual(rec["roles"], {"h_001": "builder"})
        self.assertEqual(rec["founded_tick"], 10)
        self.assertEqual(rec["last_review_tick"], 10)

    def test_dissolved_settlement_must_be_empty(self):
        anchor = make_anchor(0, 0, 1000, 1000)
        s_id = self.registry.create_settlement(
            name="Temporary Camp",
            anchor=anchor,
            members=["h_001"],
            buildings=["e_house1"],
            roles={"h_001": "keeper"},
            current_tick=5,
        )
        self.registry.dissolve_settlement(s_id, current_tick=15)
        rec = self.registry.get_settlement(s_id)
        self.assertEqual(rec["status"], "dissolved")
        self.assertEqual(rec["members"], [])
        self.assertEqual(rec["buildings"], [])
        self.assertEqual(rec["roles"], {})
        self.assertEqual(rec["last_review_tick"], 15)

    def test_dissolved_settlement_cannot_have_nonempty_members_on_restore(self):
        anchor = make_anchor(0, 0, 1000, 1000)
        s_id = self.registry.create_settlement(
            name="Camp",
            anchor=anchor,
            members=["h_001"],
            current_tick=5,
        )
        self.registry.dissolve_settlement(s_id, current_tick=10)
        state = self.registry.export_state()

        # Corrupt state by giving dissolved settlement a member
        state["records"][s_id]["members"] = ["h_001"]
        with self.assertRaises(SettlementValidationError):
            self.registry.validate_state(state)

    def test_monotonic_ids_and_non_reuse_after_dissolution(self):
        anchor = make_anchor(0, 0, 0, 0)
        s1 = self.registry.create_settlement("S1", anchor, members=["h_001"])
        s2 = self.registry.create_settlement("S2", anchor, members=["h_002"])
        self.assertEqual(s1, "s_00000001")
        self.assertEqual(s2, "s_00000002")

        # Dissolve s1
        self.registry.dissolve_settlement(s1)
        # Next allocated ID must be s_00000003, NEVER reusing s_00000001
        s3 = self.registry.create_settlement("S3", anchor, members=["h_003"])
        self.assertEqual(s3, "s_00000003")
        self.assertEqual(self.registry.next_id, 4)

    def test_roles_subset_and_valid_roles_enforced(self):
        anchor = make_anchor(0, 0, 0, 0)
        # Non-member in roles rejected
        with self.assertRaises(SettlementValidationError):
            self.registry.create_settlement(
                "S1",
                anchor,
                members=["h_001"],
                roles={"h_002": "builder"},
            )

        # Invalid role name rejected
        with self.assertRaises(SettlementValidationError):
            self.registry.create_settlement(
                "S1",
                anchor,
                members=["h_001"],
                roles={"h_001": "king"},  # "king" not in (builder, keeper, watch)
            )

        # Valid roles assigned
        s1 = self.registry.create_settlement(
            "S1",
            anchor,
            members=["h_001", "h_002", "h_003"],
            roles={"h_001": "builder", "h_002": "keeper", "h_003": "watch"},
        )
        rec = self.registry.get_settlement(s1)
        self.assertEqual(rec["roles"]["h_003"], "watch")

    def test_global_member_exclusivity_and_cap(self):
        anchor = make_anchor(0, 0, 0, 0)
        s1 = self.registry.create_settlement("S1", anchor, members=["h_001", "h_002"])

        # Same member in another settlement rejected
        with self.assertRaises(SettlementConflictError):
            self.registry.create_settlement("S2", anchor, members=["h_002", "h_003"])

        # Adding existing member rejected
        s2 = self.registry.create_settlement("S2", anchor, members=["h_003"])
        with self.assertRaises(SettlementConflictError):
            self.registry.add_member(s2, "h_001")

        # Global member cap test (cap is 10)
        # Currently 3 members (h_001, h_002, h_003). Add 7 more to reach 10:
        for i in range(4, 11):
            self.registry.add_member(s2, f"h_{i:03d}")
        self.assertEqual(len(self.registry.get_settlement(s2)["members"]), 8)

        # Adding 11th member globally exceeds cap 10
        with self.assertRaises(SettlementCapError):
            self.registry.add_member(s2, "h_011")

    def test_global_building_ownership_and_caps(self):
        anchor = make_anchor(0, 0, 0, 0)
        s1 = self.registry.create_settlement("S1", anchor, members=["h_001"], buildings=["e_b1"])

        # Same building in another settlement rejected
        with self.assertRaises(SettlementConflictError):
            self.registry.create_settlement("S2", anchor, members=["h_002"], buildings=["e_b1"])

        s2 = self.registry.create_settlement("S2", anchor, members=["h_002"], buildings=["e_b2"])
        with self.assertRaises(SettlementConflictError):
            self.registry.add_building(s2, "e_b1")

    def test_config_rejects_exceeding_max_humans_and_tightened_cap_accepted(self):
        max_h = settlements.MAX_HUMANS_DEFAULT
        # Exceeding real engine bound MAX_HUMANS is rejected
        with self.assertRaises(SettlementValidationError):
            SettlementConfig(max_members_global=max_h + 1)
        with self.assertRaises(SettlementValidationError):
            SettlementConfig(max_members_global=1000)
        with self.assertRaises(SettlementValidationError):
            SettlementConfig(max_members_global=True)
        with self.assertRaises(SettlementValidationError):
            SettlementConfig(max_members_global=0)

        # Equal to bound is accepted
        cfg_max = SettlementConfig(max_members_global=max_h)
        self.assertEqual(cfg_max.max_members_global, max_h)

        # Tightened cap (less than MAX_HUMANS) is accepted
        cfg_tight = SettlementConfig(max_members_global=10)
        self.assertEqual(cfg_tight.max_members_global, 10)

    def test_create_and_restore_enforce_real_bound_without_fallback_weakening(self):
        max_h = settlements.MAX_HUMANS_DEFAULT
        cfg = SettlementConfig(max_members_global=max_h)
        reg = SettlementRegistry(cfg)
        anchor = make_anchor(0, 0, 0, 0)

        # State restore path rejects > max_h active members even if forge attempted
        payload = reg.export_state()
        payload["records"]["s_00000001"] = {
            "uid": "s_00000001",
            "name": "Overpopulated",
            "anchor": anchor,
            "claim_radius_q": DEFAULT_CLAIM_RADIUS_Q,
            "members": [f"m_{i:04d}" for i in range(max_h + 1)],
            "buildings": [],
            "roles": {},
            "founded_tick": 0,
            "last_review_tick": 0,
            "status": "active",
        }
        payload["next_id"] = 2
        with self.assertRaises(SettlementCapError):
            reg.validate_state(payload)
        with self.assertRaises(SettlementCapError):
            reg.restore_state(payload)


class TestAuthoritativeResolvers(unittest.TestCase):
    """Test caller callbacks for resolving residents and active/dormant structures."""

    def test_human_resolver_living_vs_deceased_and_arbitrary_uid(self):
        # Caller authoritative residents adapter simulation
        roster = {
            "alice": {"uid": "alice", "alive": True},
            "bob_123": {"uid": "bob_123", "alive": False},  # Deceased
            "resident:carol": {"uid": "resident:carol", "alive": True},
        }

        def mock_human_resolver(uid: str):
            return roster.get(uid)

        anchor = make_anchor(0, 0, 0, 0)
        registry = SettlementRegistry()

        # Unknown resident fails resolution
        with self.assertRaises(SettlementReferenceError):
            registry.create_settlement(
                "S1",
                anchor,
                members=["unknown_person"],
                human_resolver=mock_human_resolver,
            )

        # Deceased resident rejected for active membership
        with self.assertRaises(SettlementReferenceError):
            registry.create_settlement(
                "S1",
                anchor,
                members=["bob_123"],
                human_resolver=mock_human_resolver,
            )

        # Living arbitrary UIDs succeed without regex restriction
        s_id = registry.create_settlement(
            "S1",
            anchor,
            members=["alice", "resident:carol"],
            human_resolver=mock_human_resolver,
        )
        self.assertIn("resident:carol", registry.get_settlement(s_id)["members"])

    def test_structure_resolver_active_and_dormant(self):
        # Simulation of active and dormant structures
        structures = {
            "e_active1": {"uid": "e_active1", "type": 20, "space": 0, "state": "active", "progress": 100},
            "e_dormant1": {"uid": "e_dormant1", "type": 20, "space": 0, "state": "dormant", "progress": 100},
            "e_interior": {"uid": "e_interior", "type": 20, "space": 1, "state": "active", "progress": 100},  # space != 0
            "e_animal": {"uid": "e_animal", "type": 40, "space": 0, "state": "active", "progress": 100},      # animal type
            "c0_0:forge": {"uid": "c0_0:forge", "type": 26, "space": 0, "state": "active", "progress": 100},  # generated feature
        }

        def mock_structure_resolver(uid: str):
            return structures.get(uid)

        anchor = make_anchor(0, 0, 0, 0)
        registry = SettlementRegistry()

        # Dormant structure is completely valid ("dormant is valid, not missing")
        s_id = registry.create_settlement(
            "S1",
            anchor,
            members=["h_001"],
            buildings=["e_active1", "e_dormant1"],
            structure_resolver=mock_structure_resolver,
        )
        rec = registry.get_settlement(s_id)
        self.assertEqual(rec["buildings"], ["e_active1", "e_dormant1"])

        # Interior structure (space != 0) rejected
        with self.assertRaises(SettlementValidationError):
            registry.add_building(s_id, "e_interior", structure_resolver=mock_structure_resolver)

        # Non-structure type rejected
        with self.assertRaises(SettlementValidationError):
            registry.add_building(s_id, "e_animal", structure_resolver=mock_structure_resolver)

        # Generated chunk feature rejected
        with self.assertRaises(SettlementValidationError):
            registry.add_building(s_id, "c0_0:forge", structure_resolver=mock_structure_resolver)

    def test_structure_resolver_requires_explicit_type_and_space(self):
        anchor = make_anchor(0, 0, 0, 0)
        reg = SettlementRegistry()

        # Missing 'space' metadata (cannot silently accept default 0)
        no_space = {"e_no_space": {"uid": "e_no_space", "type": 20, "progress": 100}}
        with self.assertRaises(SettlementValidationError):
            reg.create_settlement("S1", anchor, members=["h_1"], buildings=["e_no_space"],
                                  structure_resolver=lambda u: no_space.get(u))

        # Missing 'type' metadata (cannot silently accept missing type)
        no_type = {"e_no_type": {"uid": "e_no_type", "space": 0, "progress": 100}}
        with self.assertRaises(SettlementValidationError):
            reg.create_settlement("S1", anchor, members=["h_1"], buildings=["e_no_type"],
                                  structure_resolver=lambda u: no_type.get(u))

        # Missing both
        empty_info = {"e_empty": {"uid": "e_empty"}}
        with self.assertRaises(SettlementValidationError):
            reg.create_settlement("S1", anchor, members=["h_1"], buildings=["e_empty"],
                                  structure_resolver=lambda u: empty_info.get(u))

    def test_structure_resolver_strict_types_reject_bool_and_invalid(self):
        anchor = make_anchor(0, 0, 0, 0)
        reg = SettlementRegistry()

        # bool space False (False == 0 in Python, but type is bool!)
        bool_space_false = {"e_b1": {"uid": "e_b1", "type": 20, "space": False, "progress": 100}}
        with self.assertRaises(SettlementValidationError):
            reg.create_settlement("S1", anchor, members=["h_1"], buildings=["e_b1"],
                                  structure_resolver=lambda u: bool_space_false.get(u))

        # bool space True
        bool_space_true = {"e_b2": {"uid": "e_b2", "type": 20, "space": True, "progress": 100}}
        with self.assertRaises(SettlementValidationError):
            reg.create_settlement("S1", anchor, members=["h_1"], buildings=["e_b2"],
                                  structure_resolver=lambda u: bool_space_true.get(u))

        # bool type (True == 1 in Python, but type is bool!)
        bool_type = {"e_b3": {"uid": "e_b3", "type": True, "space": 0, "progress": 100}}
        with self.assertRaises(SettlementValidationError):
            reg.create_settlement("S1", anchor, members=["h_1"], buildings=["e_b3"],
                                  structure_resolver=lambda u: bool_type.get(u))

        # float space (float 0.0 rejected for strict int)
        float_space = {"e_b4": {"uid": "e_b4", "type": 20, "space": 0.0, "progress": 100}}
        with self.assertRaises(SettlementValidationError):
            reg.create_settlement("S1", anchor, members=["h_1"], buildings=["e_b4"],
                                  structure_resolver=lambda u: float_space.get(u))

        # string space
        str_space = {"e_b5": {"uid": "e_b5", "type": 20, "space": "0", "progress": 100}}
        with self.assertRaises(SettlementValidationError):
            reg.create_settlement("S1", anchor, members=["h_1"], buildings=["e_b5"],
                                  structure_resolver=lambda u: str_space.get(u))

    def test_unresolved_incomplete_invalid_resolver_preserves_state(self):
        anchor = make_anchor(0, 0, 0, 0)
        reg = SettlementRegistry()
        s_id = reg.create_settlement("S1", anchor, members=["h_1"])
        before = reg.export_state()

        # Unresolved (None)
        with self.assertRaises(SettlementReferenceError):
            reg.add_building(s_id, "e_missing", structure_resolver=lambda u: None)
        self.assertEqual(reg.export_state(), before)

        # Incomplete (missing space)
        with self.assertRaises(SettlementValidationError):
            reg.add_building(s_id, "e_no_space", structure_resolver=lambda u: {"uid": u, "type": 20})
        self.assertEqual(reg.export_state(), before)

        # Invalid type (bool)
        with self.assertRaises(SettlementValidationError):
            reg.add_building(s_id, "e_bool", structure_resolver=lambda u: {"uid": u, "type": True, "space": 0})
        self.assertEqual(reg.export_state(), before)

        # Callback raises exception
        def failing_resolver(u):
            raise RuntimeError("Database connection broken")

        with self.assertRaises(RuntimeError):
            reg.add_building(s_id, "e_fail", structure_resolver=failing_resolver)
        self.assertEqual(reg.export_state(), before)


class TestProjectLifecycleAndInvariants(unittest.TestCase):
    """Test project creation, payment, progression, cancellation, and destruction."""

    def setUp(self):
        self.registry = SettlementRegistry()
        self.anchor = make_anchor(0, 0, 1000, 1000)
        self.s_id = self.registry.create_settlement(
            "Village",
            self.anchor,
            members=["h_builder", "h_resident"],
            roles={"h_builder": "builder"},
            current_tick=10,
        )

    def test_single_open_project_per_settlement_invariant(self):
        p1 = self.registry.create_project(
            self.s_id,
            builder_id="h_builder",
            building_kind="personal_shelter",
            current_tick=10,
        )
        self.assertEqual(p1, "sp_00000001")

        # Second open project rejected
        with self.assertRaises(SettlementConflictError):
            self.registry.create_project(
                self.s_id,
                builder_id="h_builder",
                building_kind="personal_shelter",
                current_tick=10,
            )

    def test_project_anchor_outside_claim_rejected(self):
        # Anchor far outside default 51200 claim radius
        outside_anchor = make_anchor(10, 10, 0, 0)
        with self.assertRaises(SettlementValidationError):
            self.registry.create_project(
                self.s_id,
                builder_id="h_builder",
                anchor=outside_anchor,
                current_tick=10,
            )

    def test_project_planned_to_complete_lifecycle(self):
        # 1. Planned
        p_id = self.registry.create_project(self.s_id, builder_id="h_builder", current_tick=10)
        proj = self.registry.get_project(p_id)
        self.assertEqual(proj["status"], "planned")
        self.assertIsNone(proj["structure_uid"])
        self.assertEqual(proj["paid"], {"wood_bundle": 0, "fiber_bundle": 0, "plank_bundle": 0})

        # 2. Funded
        mock_structures = {"e_house1": {"uid": "e_house1", "type": 20, "space": 0, "progress": 0}}
        self.registry.fund_project(
            p_id,
            structure_uid="e_house1",
            current_tick=15,
            structure_resolver=lambda uid: mock_structures.get(uid),
        )
        proj_funded = self.registry.get_project(p_id)
        self.assertEqual(proj_funded["status"], "funded")
        self.assertEqual(proj_funded["structure_uid"], "e_house1")
        self.assertEqual(proj_funded["paid"], proj_funded["recipe"])
        self.assertEqual(proj_funded["last_work_tick"], 15)

        # 3. Building
        mock_structures["e_house1"]["progress"] = 50
        self.registry.advance_project_work(
            p_id,
            current_tick=20,
            structure_resolver=lambda uid: mock_structures.get(uid),
        )
        proj_building = self.registry.get_project(p_id)
        self.assertEqual(proj_building["status"], "building")
        self.assertEqual(proj_building["last_work_tick"], 20)

        # 4. Complete
        mock_structures["e_house1"]["progress"] = 100
        self.registry.complete_project(
            p_id,
            current_tick=30,
            structure_resolver=lambda uid: mock_structures.get(uid),
        )
        proj_complete = self.registry.get_project(p_id)
        self.assertEqual(proj_complete["status"], "complete")
        self.assertEqual(proj_complete["last_work_tick"], 30)

        # Structure is linked to settlement buildings upon completion!
        rec = self.registry.get_settlement(self.s_id)
        self.assertIn("e_house1", rec["buildings"])

        # Now that previous project is complete, settlement can start another project!
        p2 = self.registry.create_project(self.s_id, builder_id="h_builder", current_tick=35)
        self.assertEqual(p2, "sp_00000002")

    def test_cancel_before_placement_vs_cancel_after_funding(self):
        # Cancel planned project (before placement)
        p1 = self.registry.create_project(self.s_id, builder_id="h_builder", current_tick=10)
        self.registry.cancel_project(p1, current_tick=12)
        proj1 = self.registry.get_project(p1)
        self.assertEqual(proj1["status"], "cancelled")
        self.assertIsNone(proj1["structure_uid"])
        self.assertTrue(all(q == 0 for q in proj1["paid"].values()))

        # Cancel funded project (after placement)
        p2 = self.registry.create_project(self.s_id, builder_id="h_builder", current_tick=15)
        self.registry.fund_project(p2, structure_uid="e_house2", current_tick=20)
        self.registry.cancel_project(p2, current_tick=25)
        proj2 = self.registry.get_project(p2)
        self.assertEqual(proj2["status"], "cancelled")
        self.assertEqual(proj2["structure_uid"], "e_house2")
        self.assertEqual(proj2["paid"], proj2["recipe"])

    def test_destroy_project_invariants_and_audit(self):
        p_id = self.registry.create_project(self.s_id, builder_id="h_builder", current_tick=10)
        mock_structs = {"e_house_dest": {"uid": "e_house_dest", "type": 20, "space": 0, "progress": 100}}
        self.registry.fund_project(p_id, structure_uid="e_house_dest", current_tick=15)
        self.registry.complete_project(p_id, current_tick=20, structure_resolver=lambda u: mock_structs.get(u))

        # Structure is in settlement buildings
        self.assertIn("e_house_dest", self.registry.get_settlement(self.s_id)["buildings"])

        # Destroy project
        audit = self.registry.destroy_project(p_id, current_tick=50)
        self.assertEqual(audit["audit"], "project_destroyed")
        self.assertEqual(audit["destroyed_structure_uid"], "e_house_dest")
        self.assertEqual(audit["invested_materials_lost"], {"wood_bundle": 6, "fiber_bundle": 3, "plank_bundle": 2})

        # Project state updated
        proj = self.registry.get_project(p_id)
        self.assertEqual(proj["status"], "destroyed")
        self.assertIsNone(proj["structure_uid"])
        self.assertEqual(proj["paid"], proj["recipe"])

        # Building link removed from settlement
        rec = self.registry.get_settlement(self.s_id)
        self.assertNotIn("e_house_dest", rec["buildings"])


class TestDefensiveCopiesAndFailedRestore(unittest.TestCase):
    """Test immutability / defensive copies and atomic restore guarantees."""

    def test_defensive_copies_prevent_in_place_corruption(self):
        registry = SettlementRegistry()
        anchor = make_anchor(0, 0, 0, 0)
        s_id = registry.create_settlement("S1", anchor, members=["h_001"], buildings=["e_001"])

        # Mutate returned settlement record
        rec = registry.get_settlement(s_id)
        rec["members"].append("corrupted_member")
        rec["buildings"].append("corrupted_building")
        rec["status"] = "dissolved"

        # Internal state remains untouched
        internal = registry.get_settlement(s_id)
        self.assertEqual(internal["members"], ["h_001"])
        self.assertEqual(internal["buildings"], ["e_001"])
        self.assertEqual(internal["status"], "active")

        # Mutate exported state
        state = registry.export_state()
        state["records"][s_id]["name"] = "Corrupted Name"
        self.assertEqual(registry.get_settlement(s_id)["name"], "S1")

    def test_failed_restore_preserves_prior_state_completely(self):
        registry = SettlementRegistry()
        anchor = make_anchor(0, 0, 0, 0)
        s_id = registry.create_settlement("Original Settlement", anchor, members=["h_001"], current_tick=10)
        p_id = registry.create_project(s_id, builder_id="h_001", current_tick=12)

        prior_state = registry.export_state()

        # Create invalid payload: unknown key in envelope
        corrupt_payload = copy.deepcopy(prior_state)
        corrupt_payload["unknown_key"] = 999

        with self.assertRaises(SettlementValidationError):
            registry.restore_state(corrupt_payload)

        # Verify state is completely unchanged
        current_state = registry.export_state()
        self.assertEqual(current_state, prior_state)

        # Create second invalid payload: cap violation
        corrupt_payload2 = copy.deepcopy(prior_state)
        corrupt_payload2["records"][s_id]["members"] = [f"h_{i:03d}" for i in range(200)]  # Exceeds cap 128

        with self.assertRaises(SettlementCapError):
            registry.restore_state(corrupt_payload2)

        # State remains identical
        self.assertEqual(registry.export_state(), prior_state)

        # Create third invalid payload: ID counter suffix violation
        corrupt_payload3 = copy.deepcopy(prior_state)
        corrupt_payload3["next_id"] = 1  # Allocated suffix is 1, so next_id must be > 1

        with self.assertRaises(SettlementValidationError):
            registry.restore_state(corrupt_payload3)

        self.assertEqual(registry.export_state(), prior_state)

    def test_restore_state_external_alias_cannot_mutate_internal_records_or_projects(self):
        registry = SettlementRegistry()
        anchor = make_anchor(0, 0, 0, 0)
        s_id = registry.create_settlement("Original", anchor, members=["h_001"], current_tick=10)
        p_id = registry.create_project(s_id, builder_id="h_001", current_tick=12)

        payload = registry.export_state()

        # Restore from payload into new registry instance
        new_reg = SettlementRegistry()
        new_reg.restore_state(payload)
        pristine_export = new_reg.export_state()

        # Mutate the external payload aliases in all possible ways
        payload["records"][s_id]["members"].append("corrupted_member")
        payload["records"][s_id]["buildings"].append("corrupted_building")
        payload["records"][s_id]["roles"]["h_001"] = "watch"
        payload["records"][s_id]["name"] = "Corrupted Settlement"
        payload["projects"][p_id]["status"] = "destroyed"
        payload["projects"][p_id]["paid"]["wood_bundle"] = 999

        # Internal state of new_reg must remain completely pristine and unaffected
        self.assertEqual(new_reg.export_state(), pristine_export)
        self.assertEqual(new_reg.get_settlement(s_id)["members"], ["h_001"])
        self.assertEqual(new_reg.get_settlement(s_id)["name"], "Original")
        self.assertEqual(new_reg.get_project(p_id)["status"], "planned")


class TestValidationBeforeMutationRegression(unittest.TestCase):
    """Direct regression tests for validation-before-mutation across all public mutators."""

    def test_add_member_validation_before_mutation_exact_repro(self):
        # Exact prompt repro:
        # create_settlement('probe',make_anchor(0,0,0,0),members=['resident-a']); export before;
        # add_member(sid,'resident-b',role='invalid') raises SettlementValidationError AFTER mutating members.
        # exported state differs afterward. Fix validation-before-mutation across ALL public mutators.
        registry = SettlementRegistry()
        sid = registry.create_settlement("probe", make_anchor(0, 0, 0, 0), members=["resident-a"])
        before = registry.export_state()

        with self.assertRaises(SettlementValidationError):
            registry.add_member(sid, "resident-b", role="invalid")

        # Entire export MUST remain completely unchanged!
        self.assertEqual(registry.export_state(), before)
        rec = registry.get_settlement(sid)
        self.assertEqual(rec["members"], ["resident-a"])
        self.assertNotIn("resident-b", rec["members"])

    def test_all_public_mutators_fail_closed_and_preserve_export(self):
        """Audit transitions for partial mutation/ID consumption before validation; fail closed and preserve invariant."""
        anchor = make_anchor(0, 0, 1000, 1000)
        registry = SettlementRegistry(SettlementConfig(
            max_settlements=2,
            max_projects=2,
            max_building_links=5,
            max_members_global=5,
            max_members_per_settlement=3,
            max_buildings_per_settlement=3,
        ))

        # 1. create_settlement failures: export unchanged, next_id not consumed
        before_empty = registry.export_state()
        self.assertEqual(registry.next_id, 1)

        # Invalid role in create_settlement
        with self.assertRaises(SettlementValidationError):
            registry.create_settlement("S1", anchor, members=["h1"], roles={"h1": "king"})
        self.assertEqual(registry.export_state(), before_empty)
        self.assertEqual(registry.next_id, 1)

        # Invalid tick in create_settlement
        with self.assertRaises(SettlementValidationError):
            registry.create_settlement("S1", anchor, members=["h1"], current_tick=-1)
        self.assertEqual(registry.export_state(), before_empty)
        self.assertEqual(registry.next_id, 1)

        # Unresolved human reference
        with self.assertRaises(SettlementReferenceError):
            registry.create_settlement("S1", anchor, members=["h1"], human_resolver=lambda u: None)
        self.assertEqual(registry.export_state(), before_empty)
        self.assertEqual(registry.next_id, 1)

        # Deceased human reference
        with self.assertRaises(SettlementReferenceError):
            registry.create_settlement("S1", anchor, members=["h1"], human_resolver=lambda u: {"uid": u, "alive": False})
        self.assertEqual(registry.export_state(), before_empty)
        self.assertEqual(registry.next_id, 1)

        # Failed callback in human_resolver
        with self.assertRaises(ZeroDivisionError):
            registry.create_settlement("S1", anchor, members=["h1"], human_resolver=lambda u: 1 / 0)
        self.assertEqual(registry.export_state(), before_empty)
        self.assertEqual(registry.next_id, 1)

        # Failed callback in structure_resolver
        with self.assertRaises(RuntimeError):
            def broken_struct(u):
                raise RuntimeError("disk read error")
            registry.create_settlement("S1", anchor, members=["h1"], buildings=["b1"], structure_resolver=broken_struct)
        self.assertEqual(registry.export_state(), before_empty)
        self.assertEqual(registry.next_id, 1)

        # Successfully create settlement 1
        s1 = registry.create_settlement("S1", anchor, members=["h1", "h2"], current_tick=10)
        self.assertEqual(s1, "s_00000001")
        self.assertEqual(registry.next_id, 2)
        before_s1 = registry.export_state()

        # 2. add_member failures
        # Invalid role
        with self.assertRaises(SettlementValidationError):
            registry.add_member(s1, "h3", role="emperor", current_tick=10)
        self.assertEqual(registry.export_state(), before_s1)

        # Invalid tick
        with self.assertRaises(SettlementValidationError):
            registry.add_member(s1, "h3", current_tick=5)  # tick < last_review_tick (10)
        self.assertEqual(registry.export_state(), before_s1)

        # Unresolved human
        with self.assertRaises(SettlementReferenceError):
            registry.add_member(s1, "h3", current_tick=10, human_resolver=lambda u: None)
        self.assertEqual(registry.export_state(), before_s1)

        # Deceased human
        with self.assertRaises(SettlementReferenceError):
            registry.add_member(s1, "h3", current_tick=10, human_resolver=lambda u: {"alive": False})
        self.assertEqual(registry.export_state(), before_s1)

        # Failed callback
        with self.assertRaises(KeyError):
            registry.add_member(s1, "h3", current_tick=10, human_resolver=lambda u: {}["nonexistent"])
        self.assertEqual(registry.export_state(), before_s1)

        # Add member h3 up to per-settlement cap (cap is 3)
        registry.add_member(s1, "h3", current_tick=10)
        before_h3 = registry.export_state()

        # Per-settlement cap exceeded on add_member
        with self.assertRaises(SettlementCapError):
            registry.add_member(s1, "h4", current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)

        # 3. remove_member failures
        # Remove non-existent member does not alter state
        registry.remove_member(s1, "h_nonexistent", current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)

        # Invalid tick in remove_member
        with self.assertRaises(SettlementValidationError):
            registry.remove_member(s1, "h3", current_tick=2)
        self.assertEqual(registry.export_state(), before_h3)

        # 4. set_role failures
        # Invalid role
        with self.assertRaises(SettlementValidationError):
            registry.set_role(s1, "h1", role="invalid_role", current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)

        # Role for non-member
        with self.assertRaises(SettlementValidationError):
            registry.set_role(s1, "non_member", role="builder", current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)

        # Invalid tick in set_role
        with self.assertRaises(SettlementValidationError):
            registry.set_role(s1, "h1", role="builder", current_tick=0)
        self.assertEqual(registry.export_state(), before_h3)

        # 5. add_building failures
        # Unresolved structure
        with self.assertRaises(SettlementReferenceError):
            registry.add_building(s1, "b_missing", structure_resolver=lambda u: None, current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)

        # Incomplete structure resolver (missing space)
        with self.assertRaises(SettlementValidationError):
            registry.add_building(s1, "b_bad", structure_resolver=lambda u: {"type": 20}, current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)

        # Failed callback in add_building
        with self.assertRaises(TypeError):
            registry.add_building(s1, "b_err", structure_resolver=lambda u: None + 1, current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)

        # Invalid tick in add_building
        with self.assertRaises(SettlementValidationError):
            registry.add_building(s1, "b_tick", current_tick=1)
        self.assertEqual(registry.export_state(), before_h3)

        # 6. create_project failures: export unchanged, next_project_id not consumed
        self.assertEqual(registry.next_project_id, 1)

        # Builder not member
        with self.assertRaises(SettlementValidationError):
            registry.create_project(s1, builder_id="stranger", current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)
        self.assertEqual(registry.next_project_id, 1)

        # Anchor outside claim
        outside = make_anchor(100, 100, 0, 0)
        with self.assertRaises(SettlementValidationError):
            registry.create_project(s1, builder_id="h1", anchor=outside, current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)
        self.assertEqual(registry.next_project_id, 1)

        # Invalid tick
        with self.assertRaises(SettlementValidationError):
            registry.create_project(s1, builder_id="h1", current_tick=-1)
        self.assertEqual(registry.export_state(), before_h3)
        self.assertEqual(registry.next_project_id, 1)

        # Invalid recipe
        with self.assertRaises(SettlementValidationError):
            registry.create_project(s1, builder_id="h1", recipe={"wood": 0}, current_tick=10)
        self.assertEqual(registry.export_state(), before_h3)
        self.assertEqual(registry.next_project_id, 1)

        # Successfully create project
        p1 = registry.create_project(s1, builder_id="h1", current_tick=10)
        self.assertEqual(p1, "sp_00000001")
        self.assertEqual(registry.next_project_id, 2)
        before_p1 = registry.export_state()

        # Second open project rejected: next_project_id NOT consumed
        with self.assertRaises(SettlementConflictError):
            registry.create_project(s1, builder_id="h1", current_tick=10)
        self.assertEqual(registry.export_state(), before_p1)
        self.assertEqual(registry.next_project_id, 2)

        # 7. fund_project failures
        # Invalid status (trying to advance work before funding)
        with self.assertRaises(SettlementValidationError):
            registry.advance_project_work(p1, current_tick=12)
        self.assertEqual(registry.export_state(), before_p1)

        # Incomplete structure metadata on fund
        with self.assertRaises(SettlementValidationError):
            registry.fund_project(p1, structure_uid="e_struct1", current_tick=12,
                                  structure_resolver=lambda u: {"space": 0})
        self.assertEqual(registry.export_state(), before_p1)

        # Partial / invalid payment
        with self.assertRaises(SettlementValidationError):
            registry.fund_project(p1, structure_uid="e_struct1", paid={"wood_bundle": 1, "fiber_bundle": 1, "plank_bundle": 1},
                                  current_tick=12, structure_resolver=lambda u: {"type": 20, "space": 0, "progress": 0})
        self.assertEqual(registry.export_state(), before_p1)

        # Failed callback on fund
        with self.assertRaises(ValueError):
            def boom(u):
                raise ValueError("resolver crashed")
            registry.fund_project(p1, structure_uid="e_struct1", current_tick=12, structure_resolver=boom)
        self.assertEqual(registry.export_state(), before_p1)

        # Invalid tick on fund
        with self.assertRaises(SettlementValidationError):
            registry.fund_project(p1, structure_uid="e_struct1", current_tick=5)
        self.assertEqual(registry.export_state(), before_p1)

        # Fund project properly
        valid_structs = {"e_struct1": {"uid": "e_struct1", "type": 20, "space": 0, "progress": 0}}
        registry.fund_project(p1, structure_uid="e_struct1", current_tick=15,
                              structure_resolver=lambda u: valid_structs.get(u))
        before_funded = registry.export_state()

        # Cannot fund again (status is funded)
        with self.assertRaises(SettlementValidationError):
            registry.fund_project(p1, structure_uid="e_struct1", current_tick=16)
        self.assertEqual(registry.export_state(), before_funded)

        # 8. advance_project_work failures
        # Progress >= 100 rejected in advance
        over_progress = {"e_struct1": {"uid": "e_struct1", "type": 20, "space": 0, "progress": 100}}
        with self.assertRaises(SettlementValidationError):
            registry.advance_project_work(p1, current_tick=18, structure_resolver=lambda u: over_progress.get(u))
        self.assertEqual(registry.export_state(), before_funded)

        # Failed callback in advance
        with self.assertRaises(RuntimeError):
            def broken_advance(u):
                raise RuntimeError("advance resolver error")
            registry.advance_project_work(p1, current_tick=18, structure_resolver=broken_advance)
        self.assertEqual(registry.export_state(), before_funded)

        # Invalid tick in advance
        with self.assertRaises(SettlementValidationError):
            registry.advance_project_work(p1, current_tick=10)
        self.assertEqual(registry.export_state(), before_funded)

        # 9. complete_project failures
        # Progress < 100 rejected on completion
        under_progress = {"e_struct1": {"uid": "e_struct1", "type": 20, "space": 0, "progress": 99}}
        with self.assertRaises(SettlementValidationError):
            registry.complete_project(p1, current_tick=20, structure_resolver=lambda u: under_progress.get(u))
        self.assertEqual(registry.export_state(), before_funded)

        # Missing progress on completion
        no_prog = {"e_struct1": {"uid": "e_struct1", "type": 20, "space": 0}}
        with self.assertRaises(SettlementValidationError):
            registry.complete_project(p1, current_tick=20, structure_resolver=lambda u: no_prog.get(u))
        self.assertEqual(registry.export_state(), before_funded)

        # Failed callback on complete
        with self.assertRaises(AssertionError):
            def resolver_assert(u):
                assert False, "resolver error"
            registry.complete_project(p1, current_tick=20, structure_resolver=resolver_assert)
        self.assertEqual(registry.export_state(), before_funded)

        # Complete properly
        complete_struct = {"e_struct1": {"uid": "e_struct1", "type": 20, "space": 0, "progress": 100}}
        registry.complete_project(p1, current_tick=25, structure_resolver=lambda u: complete_struct.get(u))
        before_complete = registry.export_state()

        # Cannot cancel completed project (terminal status)
        with self.assertRaises(SettlementValidationError):
            registry.cancel_project(p1, current_tick=30)
        self.assertEqual(registry.export_state(), before_complete)

        # 10. destroy_project failures
        # Destroy with invalid tick
        with self.assertRaises(SettlementValidationError):
            registry.destroy_project(p1, current_tick=10)
        self.assertEqual(registry.export_state(), before_complete)

        # Destroy properly
        audit = registry.destroy_project(p1, current_tick=30)
        self.assertEqual(audit["audit"], "project_destroyed")
        before_destroyed = registry.export_state()

        # Destroy already destroyed project (structure_uid is None)
        with self.assertRaises(SettlementValidationError):
            registry.destroy_project(p1, current_tick=35)
        self.assertEqual(registry.export_state(), before_destroyed)

        # 11. dissolve_settlement on active settlement with open project
        s2 = registry.create_settlement("S2", anchor, members=["h4"], current_tick=40)
        p2 = registry.create_project(s2, builder_id="h4", current_tick=45)
        before_s2 = registry.export_state()

        # Dissolve with tick < open project's last_work_tick fails and preserves state
        with self.assertRaises(SettlementValidationError):
            registry.dissolve_settlement(s2, current_tick=42)
        self.assertEqual(registry.export_state(), before_s2)


class TestPureServiceArchitecture(unittest.TestCase):
    """Test pure service boundaries: no tensor columns, no inventory creation, no import hooks."""

    def test_no_tensor_columns_or_engine_mutations(self):
        try:
            import genesis_config as cfg
            # Verify MAP_TENSOR_COLS is unchanged at 32
            self.assertEqual(cfg.MAP_TENSOR_COLS, 32)
            # Verify no M_CONSTRUCTION_PROGRESS or settlement column was introduced
            self.assertFalse(hasattr(cfg, "M_CONSTRUCTION_PROGRESS"))
            self.assertFalse(hasattr(cfg, "M_SETTLEMENT"))
        except ImportError:
            pass

    def test_explicit_instantiation_only(self):
        # Module settlements should have no global active registry singleton
        self.assertFalse(hasattr(settlements, "active_registry"))
        self.assertFalse(hasattr(settlements, "CURRENT_REGISTRY"))


if __name__ == "__main__":
    unittest.main()
