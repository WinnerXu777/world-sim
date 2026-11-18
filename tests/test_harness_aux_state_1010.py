"""Tests for R6.13 Auxiliary Resident Hot-State Storage Foundation.

Governing Architecture: 1010_aux_state_gap.md
Scope: Pure service unit tests for explicitly instantiated bounded storage table
and validated schema.
Note: Does NOT claim production engine lifecycle integration (births, deaths,
dormancy, window rebase, save persistence remain unwired in this foundation step).
Uses standard library unittest and installed torch (no pytest dependency).
Uses deterministic synthetic DERIVED_CACHE field specs only; zero invented gameplay meanings.
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import torch

# Ensure at_the_beginning is available on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
AT_THE_BEGINNING = REPO_ROOT / "at_the_beginning"
if str(AT_THE_BEGINNING) not in sys.path:
    sys.path.insert(0, str(AT_THE_BEGINNING))

import genesis_config as cfg
from harness import aux_state as A


class AuxStateFoundationTests(unittest.TestCase):
    """Pure service unit tests for R6.13 storage foundation."""

    def _make_synthetic_derived_schema(self, cols: int = 2) -> A.AuxSchema:
        """Create a deterministic synthetic schema with DERIVED_CACHE fields only."""
        f0 = A.AuxFieldSpec(
            name="synth_metric_alpha",
            column=0,
            min_value=-100.0,
            max_value=100.0,
            default_value=12.5,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda engine, slot: 25.0,
        )
        fields = [f0]
        if cols >= 2:
            f1 = A.AuxFieldSpec(
                name="synth_metric_beta",
                column=1,
                min_value=0.0,
                max_value=50.0,
                default_value=5.0,
                ownership=A.FieldOwnership.DERIVED_CACHE,
                rebuild_fn=lambda engine, slot: 10.0,
            )
            fields.append(f1)
        return A.AuxSchema(cols=cols, fields=fields)

    def test_no_import_allocation_or_singleton(self):
        """Verify module import does not allocate storage tables, tensors, or global singletons."""
        self.assertFalse(hasattr(A, "h_aux"))
        self.assertFalse(hasattr(A, "_global_aux_table"))
        self.assertFalse(hasattr(A, "TABLE"))

    def test_schema_bounded_columns_ceiling_and_strict_integer_types(self):
        """Verify columns bounded to MAX_AUX_COLS (16) and strict int validation."""
        self.assertEqual(A.MAX_AUX_COLS, 16)

        # Valid 16-column schema
        specs = [
            A.AuxFieldSpec(
                name=f"synth_col_{i}",
                column=i,
                min_value=0.0,
                max_value=10.0,
                default_value=0.0,
                ownership=A.FieldOwnership.DERIVED_CACHE,
                rebuild_fn=lambda eng, s: 0.0,
            )
            for i in range(16)
        ]
        schema16 = A.AuxSchema(cols=16, fields=specs)
        self.assertEqual(schema16.cols, 16)
        self.assertEqual(len(schema16.fields), 16)

        # Exceeding infrastructure ceiling (17 cols) must raise InvalidSchemaError
        with self.assertRaises(A.InvalidSchemaError):
            A.AuxSchema(cols=17, fields=specs)

        # Non-positive or zero columns
        with self.assertRaises(A.InvalidSchemaError):
            A.AuxSchema(cols=0, fields=[])

        with self.assertRaises(A.InvalidSchemaError):
            A.AuxSchema(cols=-1, fields=[])

        # Strict integer check: bool (True/False) must be rejected
        with self.assertRaises(A.InvalidSchemaError):
            A.AuxSchema(cols=True, fields=[])  # type: ignore

    def test_ownership_rejects_authoritative_specs_pending_persistence_dr22(self):
        """Verify authoritative specs are rejected pending supported persistence (DR22)."""
        with self.assertRaises(A.UnsupportedOwnershipError) as cm:
            A.AuxFieldSpec(
                name="synth_authoritative_field",
                column=0,
                min_value=0.0,
                max_value=100.0,
                default_value=50.0,
                ownership=A.FieldOwnership.AUTHORITATIVE,
                rebuild_fn=None,
            )
        self.assertIn("DR22 remains OPEN", str(cm.exception))
        self.assertIn("rejected pending supported persistence", str(cm.exception))

    def test_schema_duplicates_detection(self):
        """Verify schema rejects duplicate field names and duplicate column indices."""
        f0 = A.AuxFieldSpec(
            name="duplicate_name",
            column=0,
            min_value=0.0,
            max_value=10.0,
            default_value=0.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 0.0,
        )
        f1 = A.AuxFieldSpec(
            name="duplicate_name",
            column=1,
            min_value=0.0,
            max_value=10.0,
            default_value=0.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 0.0,
        )
        with self.assertRaises(A.DuplicateFieldError):
            A.AuxSchema(cols=2, fields=[f0, f1])

        f2 = A.AuxFieldSpec(
            name="different_name",
            column=0,  # duplicate column 0
            min_value=0.0,
            max_value=10.0,
            default_value=0.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 0.0,
        )
        with self.assertRaises(A.DuplicateFieldError):
            A.AuxSchema(cols=2, fields=[f0, f2])

    def test_rebuild_fn_required_and_callable_for_derived(self):
        """Verify derived cache field requires a callable rebuild function."""
        with self.assertRaises(A.InvalidSchemaError):
            A.AuxFieldSpec(
                name="no_rebuild",
                column=0,
                min_value=0.0,
                max_value=10.0,
                default_value=0.0,
                ownership=A.FieldOwnership.DERIVED_CACHE,
                rebuild_fn=None,
            )

        with self.assertRaises(A.InvalidSchemaError):
            A.AuxFieldSpec(
                name="unusable_rebuild",
                column=0,
                min_value=0.0,
                max_value=10.0,
                default_value=0.0,
                ownership=A.FieldOwnership.DERIVED_CACHE,
                rebuild_fn="not_callable",  # type: ignore
            )

    def test_numeric_bounds_defaults_and_bool_rejection(self):
        """Verify strict float32 validation: rejects bool, NaN, Inf, and float32 overflow."""
        # Bool rejection in bounds
        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, True, 10.0, 0.0, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)  # type: ignore

        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, 0.0, False, 0.0, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)  # type: ignore

        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, 0.0, 10.0, True, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)  # type: ignore

        # NaN / Inf rejection
        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, float("nan"), 10.0, 0.0, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)

        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, 0.0, float("inf"), 0.0, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)

        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, 0.0, 10.0, float("-inf"), A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)

        # Float32 overflow rejection (1e39 is finite in Python float64, overflows IEEE 754 float32)
        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, 0.0, 1e39, 0.0, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)

        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, 0.0, 10.0, 1e200, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)

        # min > max
        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, 50.0, 10.0, 20.0, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)

        # default out of bounds
        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec("test", 0, 0.0, 10.0, 15.0, A.FieldOwnership.DERIVED_CACHE, lambda e, s: 0.0)

    def test_table_bounded_capacity_and_bool_rejection(self):
        """Verify table capacity bounded by cfg.MAX_HUMANS and rejects bool."""
        schema = self._make_synthetic_derived_schema()
        self.assertEqual(cfg.MAX_HUMANS, 100)

        # Default capacity is cfg.MAX_HUMANS
        table = A.AuxStateTable(schema=schema)
        self.assertEqual(table.capacity, 100)
        self.assertEqual(table.tensor.shape, (100, 2))

        # Capacity exceeding cfg.MAX_HUMANS
        with self.assertRaises(ValueError):
            A.AuxStateTable(schema=schema, capacity=cfg.MAX_HUMANS + 1)

        # Non-positive capacity
        with self.assertRaises(ValueError):
            A.AuxStateTable(schema=schema, capacity=0)

        # Bool rejected for capacity
        with self.assertRaises(TypeError):
            A.AuxStateTable(schema=schema, capacity=True)  # type: ignore

    def test_defaults_initialized_not_zero_blindly(self):
        """Verify table tensor and clear_slot initialize to schema defaults, not 0.0 blindly."""
        schema = self._make_synthetic_derived_schema()  # default 12.5 and 5.0
        table = A.AuxStateTable(schema=schema, capacity=10)

        # All rows should have 12.5 and 5.0 upon initialization
        self.assertTrue(torch.all(table.tensor[:, 0] == 12.5).item())
        self.assertTrue(torch.all(table.tensor[:, 1] == 5.0).item())

        # Bind slot 3 and apply a valid mutation
        table.bind_slot(3, "uid_3")
        draft0 = table.plan_mutation(3, 0, 99.0, "uid_3", 0)
        draft1 = table.plan_mutation(3, 1, 42.0, "uid_3", 0)
        self.assertIsNotNone(draft0)
        self.assertIsNotNone(draft1)
        committed = table.apply_mutations([draft0, draft1])
        self.assertEqual(committed, 2)
        self.assertEqual(table.get_field(3, 0, "uid_3", 0), 99.0)
        self.assertEqual(table.get_field(3, 1, "uid_3", 0), 42.0)

        # Clear slot 3 resets back to defaults
        table.clear_slot(3)
        self.assertEqual(table.get_field(3, 0, "uid_3", 0), 12.5)
        self.assertEqual(table.get_field(3, 1, "uid_3", 0), 5.0)

    def test_exact_generation_beyond_2_to_24(self):
        """Verify slot generation tracking beyond 2^24 uses exact int64 without float32 aliasing."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=5)
        slot = 2

        # 2^24 = 16,777,216. In float32: 16777216.0 == 16777217.0
        gen_2_24 = 16777216
        gen_2_24_plus_1 = 16777217

        # Bind slot
        table.bind_slot(slot, "resident_deep_time")
        # Clearly private fixture setup for generation boundary testing
        table._set_slot_gen_for_test(slot, gen_2_24_plus_1)

        # Read with stale expected generation (16777216) must fail
        with self.assertRaises(A.StaleGenerationError):
            table.get_field(slot, column=0, expected_gen=gen_2_24)

        # Read with exact expected generation (16777217) must succeed
        val = table.get_field(slot, column=0, expected_gen=gen_2_24_plus_1)
        self.assertEqual(val, 12.5)

        # Planning mutation with stale gen fails
        draft_stale = table.plan_mutation(
            slot=slot,
            column=0,
            candidate_value=20.0,
            expected_uid="resident_deep_time",
            expected_gen=gen_2_24,
        )
        self.assertIsNone(draft_stale)

        # Planning mutation with exact gen succeeds
        draft_exact = table.plan_mutation(
            slot=slot,
            column=0,
            candidate_value=20.0,
            expected_uid="resident_deep_time",
            expected_gen=gen_2_24_plus_1,
        )
        self.assertIsNotNone(draft_exact)

    def test_stale_draft_after_recycle(self):
        """Verify recycling increments generation and invalidates previously staged drafts."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=5)
        slot = 1
        uid_0 = "resident_initial"

        gen_0 = table.bind_slot(slot, uid_0)
        self.assertEqual(gen_0, 0)

        # Plan draft under gen_0
        draft = table.plan_mutation(
            slot=slot,
            column=0,
            candidate_value=45.0,
            expected_uid=uid_0,
            expected_gen=gen_0,
        )
        self.assertIsNotNone(draft)

        # Recycle slot on resident death
        gen_1 = table.recycle_slot(slot)
        self.assertEqual(gen_1, 1)
        self.assertFalse(table.is_active(slot))
        self.assertIsNone(table.get_uid(slot))

        # Attempting to apply stale draft fails completely (commits 0)
        committed = table.apply_mutations([draft])
        self.assertEqual(committed, 0)
        self.assertEqual(table.tensor[slot, 0].item(), 12.5)

        # Re-bind to new resident under gen_1
        uid_1 = "resident_newborn"
        gen_reb = table.bind_slot(slot, uid_1)
        self.assertEqual(gen_reb, 1)

        # Old draft still fails
        committed = table.apply_mutations([draft])
        self.assertEqual(committed, 0)
        self.assertEqual(table.tensor[slot, 0].item(), 12.5)

    def test_failed_batch_with_valid_earlier_draft_leaves_no_partial_writes(self):
        """Verify atomic commit: any invalid draft in a batch leaves table wholly unchanged."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=5)
        slot0, slot1 = 0, 1

        table.bind_slot(slot0, "uid_0")
        table.bind_slot(slot1, "uid_1")

        # Draft 1 is completely valid
        draft1 = table.plan_mutation(
            slot=slot0,
            column=0,
            candidate_value=77.0,
            expected_uid="uid_0",
            expected_gen=0,
        )
        self.assertIsNotNone(draft1)

        # Draft 2 targets stale generation (invalid)
        draft2 = A.AuxMutationDraft(
            slot=slot1,
            column=0,
            value=88.0,
            expected_uid="uid_1",
            expected_gen=999,  # Mismatched generation
        )

        # Apply batch [draft1, draft2]
        committed = table.apply_mutations([draft1, draft2])
        self.assertEqual(committed, 0)

        # Verify draft1 was NOT partially applied
        self.assertEqual(table.tensor[slot0, 0].item(), 12.5)
        self.assertEqual(table.tensor[slot1, 0].item(), 12.5)

    def test_duplicate_targets_in_batch_rejected(self):
        """Verify batches containing duplicate (slot, column) targets are rejected atomically."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=5)
        slot = 0
        table.bind_slot(slot, "uid_0")

        draft_a = A.AuxMutationDraft(slot=slot, column=0, value=30.0, expected_uid="uid_0", expected_gen=0)
        draft_b = A.AuxMutationDraft(slot=slot, column=0, value=40.0, expected_uid="uid_0", expected_gen=0)

        committed = table.apply_mutations([draft_a, draft_b])
        self.assertEqual(committed, 0)
        self.assertEqual(table.tensor[slot, 0].item(), 12.5)

    def test_repeated_invalidations_and_max_int64_exhaustion(self):
        """Verify exact int64 generation detects MAX_INT64 exhaustion rather than overflowing."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=3)
        slot = 0

        table.bind_slot(slot, "uid_initial")
        # Clearly private fixture setup for MAX_INT64 testing
        table._set_slot_gen_for_test(slot, A.MAX_INT64)

        # Invalidation via recycle must detect exhaustion and raise GenerationExhaustionError
        with self.assertRaises(A.GenerationExhaustionError):
            table.recycle_slot(slot)

        # Re-binding must also detect exhaustion and raise
        with self.assertRaises(A.GenerationExhaustionError):
            table.bind_slot(slot, "uid_next")

    def test_frozen_dormant_mutation_rejection(self):
        """Verify dormant frozen rows reject mutation planning and applying until wake."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=5)
        slot = 2

        table.bind_slot(slot, "resident_sleeper")
        table.freeze_slot(slot)
        self.assertTrue(table.is_frozen(slot))

        # Planning mutation targeting frozen slot returns None
        draft = table.plan_mutation(
            slot=slot,
            column=0,
            candidate_value=50.0,
            expected_uid="resident_sleeper",
            expected_gen=0,
        )
        self.assertIsNone(draft)

        # Staged draft created prior to freeze fails to apply while frozen
        raw_draft = A.AuxMutationDraft(
            slot=slot,
            column=0,
            value=50.0,
            expected_uid="resident_sleeper",
            expected_gen=0,
        )
        committed = table.apply_mutations([raw_draft])
        self.assertEqual(committed, 0)
        self.assertEqual(table.tensor[slot, 0].item(), 12.5)

    def test_wake_rebuild_success(self):
        """Verify wake recomputes derived cache fields atomically and unfreezes row."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=5)
        slot = 2

        table.bind_slot(slot, "resident_wake")
        table.freeze_slot(slot)

        # Wake slot
        table.wake_slot(slot)
        self.assertFalse(table.is_frozen(slot))

        # Field 0 rebuild_fn returns 25.0, Field 1 returns 10.0
        self.assertEqual(table.tensor[slot, 0].item(), 25.0)
        self.assertEqual(table.tensor[slot, 1].item(), 10.0)

    def test_failed_wake_rebuild_atomicity(self):
        """Verify failed rebuild leaves row state wholly unchanged and row remains frozen."""
        f0 = A.AuxFieldSpec(
            name="synth_good",
            column=0,
            min_value=0.0,
            max_value=100.0,
            default_value=10.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 50.0,
        )

        def bad_rebuild(engine, slot):
            raise RuntimeError("Synthetic rebuild explosion")

        f1 = A.AuxFieldSpec(
            name="synth_failing",
            column=1,
            min_value=0.0,
            max_value=100.0,
            default_value=20.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=bad_rebuild,
        )
        schema = A.AuxSchema(cols=2, fields=[f0, f1])
        table = A.AuxStateTable(schema=schema, capacity=5)
        slot = 1

        table.bind_slot(slot, "resident_atomic")
        draft0 = table.plan_mutation(slot, 0, 15.0, "resident_atomic", 0)
        draft1 = table.plan_mutation(slot, 1, 25.0, "resident_atomic", 0)
        self.assertIsNotNone(draft0)
        self.assertIsNotNone(draft1)
        table.apply_mutations([draft0, draft1])
        table.freeze_slot(slot)

        with self.assertRaises(A.AuxWakeRebuildError):
            table.wake_slot(slot)

        # Values must remain strictly identical to pre-wake state
        self.assertEqual(table.tensor[slot, 0].item(), 15.0)
        self.assertEqual(table.tensor[slot, 1].item(), 25.0)
        # Slot must remain frozen
        self.assertTrue(table.is_frozen(slot))

    def test_defensive_copies_prevent_external_corruption(self):
        """Verify get_tensor_copy, get_row_copy, and public tensor/slot_gen properties return defensive clones."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=5)

        # Table tensor clone
        t_copy = table.get_tensor_copy()
        t_copy[0, 0] = 999.0
        self.assertNotEqual(table.tensor[0, 0].item(), 999.0)
        self.assertEqual(table.tensor[0, 0].item(), 12.5)

        # Row clone
        r_copy = table.get_row_copy(0)
        r_copy[0] = 888.0
        self.assertNotEqual(table.tensor[0, 0].item(), 888.0)
        self.assertEqual(table.tensor[0, 0].item(), 12.5)

        # Generation clone
        g_copy = table.get_slot_gen_copy()
        g_copy[0] = 777
        self.assertNotEqual(table.slot_gen[0].item(), 777)
        self.assertEqual(table.slot_gen[0].item(), 0)

        # Public properties return defensive clones
        prop_t = table.tensor
        prop_t[0, 0] = 666.0
        self.assertEqual(table.tensor[0, 0].item(), 12.5)

        prop_g = table.slot_gen
        prop_g[0] = 555
        self.assertEqual(table.slot_gen[0].item(), 0)

    def test_unknown_and_unregistered_fields(self):
        """Verify unknown column and invalid slot accesses raise appropriate errors."""
        schema = self._make_synthetic_derived_schema(cols=2)
        table = A.AuxStateTable(schema=schema, capacity=5)
        table.bind_slot(0, "uid_0")

        # Unknown column raises KeyError
        with self.assertRaises(KeyError):
            table.get_field(slot=0, column=5, expected_uid="uid_0", expected_gen=0)

        # Out-of-bounds slot raises InvalidSlotError
        with self.assertRaises(A.InvalidSlotError):
            table.get_field(slot=10, column=0)

        with self.assertRaises(A.InvalidSlotError):
            table.freeze_slot(10)

        with self.assertRaises(A.InvalidSlotError):
            table.clear_slot(-1)

    def test_functional_apis_and_engine_device_check(self):
        """Verify functional APIs conform to 1010_aux_state_gap.md specifications."""
        schema = self._make_synthetic_derived_schema()
        table = A.allocate_aux_state(schema=schema, capacity=cfg.MAX_HUMANS)

        # Mock engine with primary h_tensor
        fake_engine = SimpleNamespace(
            state=SimpleNamespace(
                h_tensor=torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS), dtype=torch.float32),
                h_aux=None,
            ),
            _human_uid_by_slot=[None] * cfg.MAX_HUMANS,
        )

        A.bind_aux_state(fake_engine, table)
        self.assertIs(fake_engine.state.h_aux, table)

        # Device mismatch verification: engine on a different mock device raises ValueError
        mismatched_engine = SimpleNamespace(
            state=SimpleNamespace(
                h_tensor=SimpleNamespace(device=torch.device("meta") if hasattr(torch, "device") else "meta"),
                h_aux=None,
            ),
        )
        if table.device != mismatched_engine.state.h_tensor.device:
            with self.assertRaises(ValueError):
                A.bind_aux_state(mismatched_engine, table)

        # Verify column 31 in h_tensor remains untouched
        fake_engine.state.h_tensor = torch.zeros((cfg.MAX_HUMANS, cfg.HUMAN_TENSOR_COLS), dtype=torch.float32)
        A.bind_aux_state(fake_engine, table)
        self.assertTrue(torch.all(fake_engine.state.h_tensor[:, 31] == 0.0).item())

        # Functional bind, plan, apply, read, freeze, wake, recycle
        fake_engine._human_uid_by_slot[0] = "h_uid_0"
        gen = A.bind_aux_slot(table, 0, "h_uid_0")
        self.assertEqual(gen, 0)

        draft = A.plan_aux_mutation(fake_engine, table, 0, 0, 42.0, "h_uid_0", 0)
        self.assertIsNotNone(draft)

        committed = A.apply_aux_mutations(fake_engine, table, [draft])
        self.assertEqual(committed, 1)

        val = A.get_aux_field(fake_engine, table, 0, 0, expected_uid="h_uid_0", expected_gen=0)
        self.assertEqual(val, 42.0)

        A.freeze_aux_slot(table, 0)
        self.assertTrue(table.is_frozen(0))

        A.wake_aux_slot(table, 0, fake_engine)
        self.assertFalse(table.is_frozen(0))

        gen_recy = A.recycle_aux_slot(table, 0)
        self.assertEqual(gen_recy, 1)

        # Primary column 31 still completely untouched
        self.assertTrue(torch.all(fake_engine.state.h_tensor[:, 31] == 0.0).item())

    # --- Root Review Regression Tests ---

    def test_regression_plan_mutation_rejects_out_of_bounds_no_clamping(self):
        """Root repro: plan_mutation rejects candidates outside declared range rather than clamping."""
        spec = A.AuxFieldSpec(
            name="bounded_field",
            column=0,
            min_value=0.0,
            max_value=10.0,
            default_value=2.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 2.0,
        )
        table = A.AuxStateTable(schema=A.AuxSchema(cols=1, fields=[spec]), capacity=5)
        table.bind_slot(0, "a")

        # Candidate 999 is outside [0, 10]: must return None, NOT a draft silently clamped to 10.0
        draft_999 = table.plan_mutation(0, 0, candidate_value=999.0, expected_uid="a", expected_gen=0)
        self.assertIsNone(draft_999)

        # Candidate -1.0 is below min_value 0.0: must return None
        draft_neg = table.plan_mutation(0, 0, candidate_value=-1.0, expected_uid="a", expected_gen=0)
        self.assertIsNone(draft_neg)

        # Candidate 10.0001 is above max_value 10.0: must return None
        draft_above = table.plan_mutation(0, 0, candidate_value=10.0001, expected_uid="a", expected_gen=0)
        self.assertIsNone(draft_above)

        # Candidate 7.5 within [0, 10]: returns valid draft with exactly 7.5
        draft_valid = table.plan_mutation(0, 0, candidate_value=7.5, expected_uid="a", expected_gen=0)
        self.assertIsNotNone(draft_valid)
        self.assertEqual(draft_valid.value, 7.5)

    def test_regression_public_tensor_and_slot_gen_cannot_corrupt_internal_storage(self):
        """Root repro: public tensor[0,0]=9 or slot_gen mutation must not alter internal state or bypass validation."""
        spec = A.AuxFieldSpec(
            name="bounded_field",
            column=0,
            min_value=0.0,
            max_value=10.0,
            default_value=2.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 2.0,
        )
        table = A.AuxStateTable(schema=A.AuxSchema(cols=1, fields=[spec]), capacity=5)
        table.bind_slot(0, "a")

        # Mutating table.tensor clone must not mutate internal storage
        table.tensor[0, 0] = 9.0
        self.assertEqual(table.get_field(0, 0, "a", 0), 2.0)

        # Mutating table.slot_gen clone must not mutate internal generation
        table.slot_gen[0] = 999
        self.assertEqual(table.get_gen(0), 0)

        # Read-only properties cannot be reassigned through public APIs
        with self.assertRaises(AttributeError):
            table.tensor = torch.zeros((5, 1))  # type: ignore

        with self.assertRaises(AttributeError):
            table.slot_gen = torch.zeros(5, dtype=torch.int64)  # type: ignore

        with self.assertRaises(AttributeError):
            table.schema = None  # type: ignore

        with self.assertRaises(AttributeError):
            table.capacity = 10  # type: ignore

        with self.assertRaises(AttributeError):
            table.device = torch.device("cpu")  # type: ignore

        with self.assertRaises(AttributeError):
            table.dtype = torch.float32  # type: ignore

    def test_regression_frozen_slot_rejects_clear_slot(self):
        """Root repro: freeze_slot(0); clear_slot(0) must reject mutation and preserve row."""
        spec = A.AuxFieldSpec(
            name="bounded_field",
            column=0,
            min_value=0.0,
            max_value=10.0,
            default_value=2.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 2.0,
        )
        table = A.AuxStateTable(schema=A.AuxSchema(cols=1, fields=[spec]), capacity=5)
        table.bind_slot(0, "a")

        # Mutate row to 7.0
        draft = table.plan_mutation(0, 0, 7.0, "a", 0)
        self.assertIsNotNone(draft)
        table.apply_mutations([draft])
        self.assertEqual(table.get_field(0, 0, "a", 0), 7.0)

        # Freeze slot
        table.freeze_slot(0)
        self.assertTrue(table.is_frozen(0))

        # Public clear_slot on frozen slot must raise FrozenRowMutationError
        with self.assertRaises(A.FrozenRowMutationError):
            table.clear_slot(0)

        # Storage must remain 7.0, not reverted back to default 2.0
        self.assertEqual(table.get_field_snapshot(0, 0), 7.0)

    def test_regression_recycle_and_bind_internal_reset_on_frozen_or_inactive(self):
        """Verify lifecycle operations recycle_slot and bind_slot internally reset frozen/inactive rows safely."""
        spec = A.AuxFieldSpec(
            name="bounded_field",
            column=0,
            min_value=0.0,
            max_value=10.0,
            default_value=2.0,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 2.0,
        )
        table = A.AuxStateTable(schema=A.AuxSchema(cols=1, fields=[spec]), capacity=5)
        table.bind_slot(0, "a")

        # Mutate to 7.0 and freeze
        draft = table.plan_mutation(0, 0, 7.0, "a", 0)
        table.apply_mutations([draft])
        table.freeze_slot(0)

        # recycle_slot must reset frozen row internally without raising FrozenRowMutationError
        gen_1 = table.recycle_slot(0)
        self.assertEqual(gen_1, 1)
        self.assertFalse(table.is_active(0))
        self.assertFalse(table.is_frozen(0))
        self.assertIsNone(table.get_uid(0))
        # Internal storage safely reset to default 2.0
        self.assertEqual(table.get_field_snapshot(0, 0), 2.0)

        # bind_slot must reset inactive row internally without failing
        gen_new = table.bind_slot(0, "b")
        self.assertEqual(gen_new, 1)
        self.assertTrue(table.is_active(0))
        self.assertEqual(table.get_field(0, 0, "b", 1), 2.0)

    def test_regression_narrow_nonrepresentable_bound_and_rounding_crossing_boundary(self):
        """Verify float32 conversion rounding that crosses declared bounds is strictly rejected."""
        # In IEEE 754 float32, the gap above 1.0 is 2^-23 (~1.192092896e-7).
        # Python float 1.00000007 is between 1.0 and 1.0 + 2^-23, with midpoint 1.0 + 2^-24 (~1.0000000596).
        # Because 1.00000007 > midpoint, float32 conversion rounds UP to 1.0000001192092896.
        # If declared max_value is 1.00000008, 1.00000007 is strictly < max_value in Python float64,
        # but rounds to 1.0000001192092896 which crosses max_value in float32 storage!

        # 1. Spec default_value rounding crossing boundary must raise InvalidNumericValueError
        with self.assertRaises(A.InvalidNumericValueError):
            A.AuxFieldSpec(
                name="narrow_upper",
                column=0,
                min_value=0.0,
                max_value=1.00000008,
                default_value=1.00000007,
                ownership=A.FieldOwnership.DERIVED_CACHE,
                rebuild_fn=lambda e, s: 0.5,
            )

        # Valid spec with safe default
        valid_spec = A.AuxFieldSpec(
            name="narrow_upper_valid",
            column=0,
            min_value=0.0,
            max_value=1.00000008,
            default_value=0.5,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 1.00000007,  # Bad rebuild returning rounding-crossing value
        )
        table = A.AuxStateTable(schema=A.AuxSchema(cols=1, fields=[valid_spec]), capacity=3)
        table.bind_slot(0, "narrow_user")

        # 2. plan_mutation with candidate whose float32 rounded value crosses max_value returns None
        draft = table.plan_mutation(0, 0, candidate_value=1.00000007, expected_uid="narrow_user", expected_gen=0)
        self.assertIsNone(draft)

        # 3. Wake rebuild returning value whose float32 rounded value crosses max_value raises AuxWakeRebuildError
        table.freeze_slot(0)
        with self.assertRaises(A.AuxWakeRebuildError):
            table.wake_slot(0)
        self.assertTrue(table.is_frozen(0))

        # 4. Lower boundary rounding-crossing:
        # This value rounds down to the float32 immediately below 1.0.
        # It is in the declared Python bounds, but its stored value is below min.
        lower_spec = A.AuxFieldSpec(
            name="narrow_lower",
            column=0,
            min_value=0.999999965,
            max_value=2.0,
            default_value=1.5,
            ownership=A.FieldOwnership.DERIVED_CACHE,
            rebuild_fn=lambda e, s: 1.5,
        )
        table_lower = A.AuxStateTable(schema=A.AuxSchema(cols=1, fields=[lower_spec]), capacity=3)
        table_lower.bind_slot(0, "lower_user")
        lower_candidate = 0.99999997
        self.assertGreaterEqual(lower_candidate, lower_spec.min_value)
        self.assertLess(float(torch.tensor(lower_candidate, dtype=torch.float32)), lower_spec.min_value)
        draft_lower = table_lower.plan_mutation(0, 0, candidate_value=lower_candidate, expected_uid="lower_user", expected_gen=0)
        self.assertIsNone(draft_lower)

    def test_regression_no_bool_token_alias(self):
        """Verify bool tokens cannot alias integers (bool=0/1 token alias rejected)."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=3)
        slot = 0

        # Bind under gen 0
        gen_0 = table.bind_slot(slot, "uid_bool_test")
        self.assertEqual(gen_0, 0)

        # bool False == 0 in Python: passing expected_gen=False must raise TypeError
        with self.assertRaises(TypeError):
            table.get_field(slot, column=0, expected_gen=False)

        # Recycle bumps to gen 1
        table.recycle_slot(slot)
        table.bind_slot(slot, "uid_bool_test")
        self.assertEqual(table.get_gen(slot), 1)

        # bool True == 1 in Python: passing expected_gen=True must raise TypeError
        with self.assertRaises(TypeError):
            table.get_field(slot, column=0, expected_gen=True)

        # bool passed for expected_uid must raise TypeError
        with self.assertRaises(TypeError):
            table.get_field(slot, column=0, expected_uid=True)  # type: ignore

        with self.assertRaises(TypeError):
            table.get_field(slot, column=0, expected_uid=False)  # type: ignore

        # plan_mutation rejects bool tokens
        self.assertIsNone(table.plan_mutation(slot, 0, 10.0, expected_uid="uid_bool_test", expected_gen=True))
        self.assertIsNone(table.plan_mutation(slot, 0, 10.0, expected_uid=True, expected_gen=1))  # type: ignore

        # AuxMutationDraft rejects bool tokens in constructor
        with self.assertRaises(A.InvalidSchemaError):
            A.AuxMutationDraft(slot=slot, column=0, value=10.0, expected_uid="uid_bool_test", expected_gen=True)  # type: ignore

        with self.assertRaises(A.InvalidSchemaError):
            A.AuxMutationDraft(slot=slot, column=0, value=10.0, expected_uid=True, expected_gen=1)  # type: ignore

    def test_regression_malformed_engine_authority_validation(self):
        """Verify caller-supplied engine is strictly validated without silently skipping authority."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=3)
        slot = 0
        table.bind_slot(slot, "authoritative_uid")

        draft = table.plan_mutation(slot, 0, 20.0, "authoritative_uid", 0)
        self.assertIsNotNone(draft)

        # Malformed engine lacking _human_uid_by_slot must raise ValueError in get_field
        malformed_engine = SimpleNamespace()
        with self.assertRaises(ValueError):
            table.get_field(slot, column=0, expected_uid="authoritative_uid", expected_gen=0, engine=malformed_engine)

        # plan_mutation rejects malformed engine
        self.assertIsNone(table.plan_mutation(slot, 0, 20.0, "authoritative_uid", 0, engine=malformed_engine))

        # apply_mutations rejects malformed engine
        self.assertEqual(table.apply_mutations([draft], engine=malformed_engine), 0)

        # Engine with mismatched UID
        mismatched_engine = SimpleNamespace(_human_uid_by_slot=["different_uid", None, None])
        with self.assertRaises(A.StaleIdentityError):
            table.get_field(slot, column=0, expected_uid="authoritative_uid", expected_gen=0, engine=mismatched_engine)

        self.assertIsNone(table.plan_mutation(slot, 0, 20.0, "authoritative_uid", 0, engine=mismatched_engine))
        self.assertEqual(table.apply_mutations([draft], engine=mismatched_engine), 0)

    def test_regression_atomic_batch_commit_preserves_whole_storage_on_bad_draft(self):
        """Verify batch commit preserves entire storage wholly unchanged if any draft is out of bounds."""
        schema = self._make_synthetic_derived_schema()
        table = A.AuxStateTable(schema=schema, capacity=3)
        table.bind_slot(0, "u0")
        table.bind_slot(1, "u1")

        # Valid draft for slot 0
        draft_valid = table.plan_mutation(0, 0, 33.0, "u0", 0)
        self.assertIsNotNone(draft_valid)

        # Malformed draft with out-of-bounds value (150.0 > max_value 100.0)
        draft_bad = A.AuxMutationDraft(slot=1, column=0, value=150.0, expected_uid="u1", expected_gen=0)

        # Applying batch [draft_valid, draft_bad] must fail completely
        committed = table.apply_mutations([draft_valid, draft_bad])
        self.assertEqual(committed, 0)

        # Entire storage remains unchanged at defaults
        self.assertEqual(table.get_field(0, 0, "u0", 0), 12.5)
        self.assertEqual(table.get_field(1, 0, "u1", 0), 12.5)


if __name__ == "__main__":
    unittest.main()
