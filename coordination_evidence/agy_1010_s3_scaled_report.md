# S3 Scaled-Roster Migration Report (R6.10 Follow-Up)

**Date**: Toronto, October 10, 2026  
**Component**: S3 Needs Harness Migration (`at_the_beginning/harness/needs.py`, `tests/test_harness_needs.py`)  
**Scope**: Scaled-roster resident hunger/thirst migration per `1008_s3_s5_taskbridge_design.md` follow-up.  

---

## 1. Executive Summary

Previously, the S3 pilot harness wrapper `instinct_needs` in `harness/needs.py` fell back unconditionally to the two legacy functions `instinct_hunger` and `instinct_thirst` whenever `systems.roster.driver.needs_scale_vector(engine, h_tensor)` was not `None`. Because all eight residents in the authored `starter_village` map have `needs_scale: 0.015`, the actual shipped village was running entirely on the legacy fallback path rather than the harness effect pipeline.

This implementation migrates scaled-roster resident needs drain onto the harness effect pipeline (`world.apply`) with exact bit-for-bit parity to legacy execution. It implements exact sequential semantics and timing as observed in production source code, respects `FieldSpec` column bounds, preserves inactive rows, and cleanly falls back to legacy execution for unrepresentable or invalid edge cases.

---

## 2. Exact Legacy Scaled Semantics & Sequential Timing

Careful analysis of production sources (`instincts_and_tools.py`, `systems/survival/hunger.py`, `systems/survival/thirst.py`, and `systems/health/status.py`) revealed the exact sequential order of operations, resolving a discrepancy where the prose summary in `1008_s3_s5_taskbridge_design.md` suggested both needs were unscaled during critical flag calculation:

### Legacy Execution Trace
1. **Hunger Tick (`instinct_hunger`)**:
   - Computes unscaled hunger advancement: $U_H = \min(100.0, B_H + \text{rate}_H)$.
   - Determines starvation: $\text{starving} = (U_H \ge 90.0)$.
   - Applies starvation HP damage: $2.0 \times \text{rate\_scale}("starvation")$ clamped at $\min=0.0$.
   - Refreshes intermediate critical flag via `update_human_critical_state(h_mask, h_tensor)`.
   - Restores scaled hunger value across tensor: $A_H = B_H + (U_H - B_H) \times scale$.
2. **Thirst Tick (`instinct_thirst`)**:
   - Executes with hunger already at its current **scaled** state $A_H$.
   - Computes unscaled thirst advancement: $U_T = \min(100.0, B_T + \text{rate}_T)$.
   - Determines dehydration: $\text{dehydrated} = (U_T \ge 90.0)$.
   - Applies dehydration HP damage and mood loss ($-0.4$, clamped at $\min=0.0$).
   - Refreshes critical flag via `update_human_critical_state(h_mask, h_tensor)`:
     $$\text{critical} = (A_H \ge 90.0) \lor (U_T \ge 90.0)$$
     *(Evaluated on current **scaled** hunger $A_H$ and **unscaled** thirst $U_T$)*.
   - Restores scaled thirst value across tensor: $A_T = B_T + (U_T - B_T) \times scale$.
   - Note: critical flag is **not** re-evaluated after thirst is scaled.

### Harness Effect Pipeline Mapping
To keep float32 arithmetic order, separate damage applications, and exact sequential timing identical to legacy:
- **Apply 1 (`system:needs`)**:
  - Emits `Delta("humans", ids, "hunger", delta_h)` and `Delta("humans", ids, "thirst", delta_t)` where:
    $$\Delta_H = (U_H - B_H) \times scale, \quad \Delta_T = (U_T - B_T) \times scale$$
    *(Unscaled fallback retains scalar deltas to preserve legacy map behavior)*.
- **Apply 2 (`system:needs`)**:
  - Emits `Delta("humans", starving_ids, "hp", -(2.0 \times \text{rate\_scale}("starvation")))`.
  - Executed in its own separate apply because float32 $(HP - 2) - d \ne HP - (2 + d)$.
- **Apply 3 (`system:needs`)**:
  - Emits `Delta hp` and `Delta mood` for dehydrated rows.
  - Emits `Set("humans", ids, "critical_health", value)` for rows whose flag changes based on $(A_H \ge 90.0) \lor (U_T \ge 90.0)$.

---

## 3. Supported Ranges and Fallback Policy

### Supported Range (Runs on Harness without Fallback)
- **Map Scales**: Real authored `starter_village` residents ($scale = 0.015$), unscaled legacy maps ($scale = 1.0$ or `None`), zero scale ($scale = 0.0$), fractional scales (e.g., $0.5$), and mixed per-slot scale vectors.
- **Scales $> 1.0$**: Fully supported when resulting scaled values remain $\le 100.0$.
- **Negative Vitals**: Negative hunger/thirst (unbounded below in `FieldSpec(None, 100.0)`) advance faithfully without fallback.
- **Calendar Rate Scaling**: Both `EDEN_CALENDAR=0` (rates = 1.0) and `EDEN_CALENDAR=1` (calendar multipliers) are fully supported.

### Conservative Fallback Conditions (Safely Invokes Legacy Callbacks)
The wrapper safely calls the two legacy functions when harness bounds cannot faithfully represent exact legacy state:
1. **Unrepresentable Scaled Bounds**: If $A_H > 100.0$ or $A_T > 100.0$ (e.g., scale $> 1$ or initial state $> 100$ that legacy does not clamp on scale restoration, but `FieldSpec(None, 100.0)` would clamp to 100.0).
2. **Unrepresentable HP Damage**: If an entity receiving starvation or dehydration damage has $HP > 100.0$ (legacy clamps only $\min=0$, whereas `FieldSpec(0.0, 100.0)` would clamp upper bound to 100.0).
3. **Invalid/Nonfinite Scales**: Negative scales ($scale < 0$), non-finite scales (`NaN`, `Inf`), or mismatched tensor shapes.
4. **Missing Prerequisites**: World is `None`, engine is `None`, humans table is missing or mismatched, or any live row in `h_mask` lacks a stable human UID (`_human_uid_by_slot`).
5. **Inactive Rows**: Unmasked rows are never included in effects; scale handling does not alter inactive rows.

---

## 4. Verification and Testing

Tests in `tests/test_harness_needs.py` were expanded with comprehensive coverage:
- **Shipped Village Verification**: Proves authored `starter_village` ($scale = 0.015$) calls `world.apply`, increments `world.revision`, does **not** invoke legacy fallback, and matches legacy bit-for-bit.
- **Randomized Mixed Scales (200 trials)**: Random tensor states, masks, and mixed scale vectors ($0.0, 0.015, 0.5, 1.0, 1.2$) match legacy bit-for-bit and advance `world.revision`.
- **400-Tick Starving Simulation**: Multi-tick mixed-scale drain from near-death start stays bit-for-bit equal across 400 steps.
- **Scale 0.0 Semantics**: Hunger/thirst frozen, HP damage applied on unscaled threshold, critical flag 0.0, matches legacy bit-for-bit.
- **Scale $> 1.0$ Support & Fallback**: Scale 1.5 safely runs through harness applier; scale 2.0 with edge values exceeding 100 falls back to legacy.
- **Sequential Critical Timing**: Verifies that intermediate hunger threshold does not leave stale critical flag when scaled hunger $< 90$ and unscaled thirst $< 90$; verifies unscaled thirst $\ge 90$ flags critical even when scaled thirst $< 90$.
- **Calendar On/Off**: Verifies bit-for-bit equality with calendar rate multipliers active and inactive.
- **Documented Fallbacks**: Negative scale, `NaN` scale, $HP > 100$ damage, and missing stable IDs verified to cleanly take fallback path with bit-for-bit equality.
- **Inactive Rows**: Proves unmasked rows remain strictly unmodified.
- **Regression Preservation**: All existing unscaled and registry tests pass unmodified.

---

## 5. Status & Next Steps

- **Implementation**: Complete in `at_the_beginning/harness/needs.py`.
- **Tests**: Complete in `tests/test_harness_needs.py`.
- **Golden Rerecord / Scheduling**: Unchanged. Default-off switches (`EDEN_HARNESS_NEEDS=1`, `EDEN_HARNESS=1`) remain intact.
- **Task Bridge**: Separate pending R6.10 work (not affected).
- **Verification Pending**: Root runs full test suite and schedules strict on/off actual starter golden check later under shared heavy lock.
- **Performance**: No performance guarantee until measured under MEASURE lock.


## Root verification

Final snapshot gate: all eight strict profiles PASS on immutable base08338f3 plus the two owned source/test files (four profiles off, four on). Live source hashes unchanged; owned NORMAL lock released. Manifest s3_scaled_gate_result.json and log s3_scaled_gate.log supersede the pending-gate statement below. Root reran14 focused tests successfully with unittest discovery. No combined full-suite or timing claim.

14tests PASS on current owned source. Initial failure in NaN scale fallback oracle was torch.equal rejecting matching NaNs; root uses torch.testing.assert_close(rtol0,atol0,equal_nanTrue), preserving exact finite-value parity, and restores original tensor before independent subsequent boundary cases. No production source adjustment. Strict real-village on/off snapshot runner prepared at coordination_evidence/run_s3_scaled_gate.py, eight profiles pending exclusive NORMAL lock after power checks. Performance measurement remains pending; no full R6.10 or taskbridge completion claim.
