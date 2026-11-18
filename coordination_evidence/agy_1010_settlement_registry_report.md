# R6.4 Bounded Settlement Registry and Coordinate Lattice Foundation Report

- **Date:** 2026-10-10
- **Track:** Harness / Engine Service Foundation (R6.4 Phase 1)
- **Reference Design:** `1010_settlement_gap.md`
- **Implemented Modules:**
  - `at_the_beginning/harness/settlements.py` (New service module)
  - `tests/test_settlement_registry_1010.py` (New comprehensive unittest suite)
  - `coordination_evidence/agy_1010_settlement_registry_report.md` (This document)
- **Status:** **Foundation Implemented; Pending Site/Transaction/Persistence/Growth Integration**. No production hooks, action verbs, persistence formats, or source files modified. DR-22 remains OPEN.

---

## 1. Architectural Boundary and Scope

This work delivers the foundational data structures, validation rules, coordinate math, and state lifecycle for the R6.4 Bounded Settlement Registry as specified in `1010_settlement_gap.md` Section 2 and Section 3.

### Key Architectural Constraints Preserved:
1. **Pure Engine Service:** `SettlementRegistry` is an independent engine service, not an `m_tensor` row or `StructureStore` field.
2. **Zero Tensor Width / Column Changes:** No `M_CONSTRUCTION_PROGRESS` or settlement columns were added. Existing constants (`MAP_TENSOR_COLS=32`, `M_GEN=30`, `M_SPACE=31`, `S_BUILD_PROGRESS=9`) remain unaltered.
3. **Explicit Instance Creation Only:** No module-level singleton or import side-effects. Callers explicitly instantiate `registry = SettlementRegistry(config)`.
4. **No Inventory Mutations:** The registry tracks accounting records (`paid`, `recipe`, `status`); item transfers (`Transfer`, `ItemPermit`) and physical resource consumption remain isolated within transaction commits.
5. **Read-Only Existing Lifecycle:** No modifications were made to `persistence/world_snapshot.py`, `harness/structure_store.py`, `genesis_config.py`, or existing systems.

---

## 2. Coordinate Lattice and Math

The spatial foundation implements fixed-point subunit quantization to guarantee origin invariance and eliminate accumulated floating-point drift across large world coordinates.

### Specifications:
- **Quantization:** $Q = 256$ subunits per world unit.
- **Chunk Geometry:** 256 world units per chunk = $65,536$ subunits per chunk ($256 \times 256$).
- **Coordinate Schema:** Exact dictionary `{"chunk": [cx, cy], "sub": [sx, sy]}`.
  - Chunk components: strict Python integers in $[-2^{40}, 2^{40}]$ (matching `chunk_routes.MAX_ABS_COORD`).
  - Sub components: strict Python integers in $[0, 65535]$.
- **Negative Floor Normalization:** Subunit positions are mapped using mathematical floor division (`divmod(total_sub, 65536)`).
  - For example, subunit coordinate $-1$ normalizes to `chunk = -1, sub = 65535`.
  - Subunit coordinate $-65536$ normalizes to `chunk = -1, sub = 0`.
  - Subunit coordinate $-65537$ normalizes to `chunk = -2, sub = 65535`.
  - Total subunits round-trip bit-for-bit across negative space without sign flipping.
- **Integer-First Live Local Conversion:**
  $$\text{local\_x} = \frac{(cx - \text{origin\_cx}) \times 65536 + sx}{256.0}$$
  Integer subtraction is performed *first*, followed by integer multiplication and addition, with float division occurring only as the final step. Re-basing the origin shifts local positions by exact multiples of $256.0$, preserving origin invariance without loss of precision.
- **Claims and Overlap:**
  - Claim radius is stored in subunits ($1 \le \text{claim\_radius\_q} \le 131072$, default $51200$ representing 200 world units).
  - Claim containment and overlap checks evaluate exact integer squared distances:
    $$dx_q = (cx_a - cx_b) \times 65536 + (sx_a - sx_b)$$
    $$dy_q = (cy_a - cy_b) \times 65536 + (sy_a - sy_b)$$
    $$\text{dist\_sq\_q} = dx_q^2 + dy_q^2$$
    Containment: $\text{dist\_sq\_q} \le \text{claim\_radius\_q}^2$.
    Overlap: $\text{dist\_sq\_q} < (\text{radius\_a\_q} + \text{radius\_b\_q})^2$ (or $\le$ when tangent inclusion is enabled).

---

## 3. Schemas, Invariants, and Finite Caps

### 3.1 State Envelope
Exact dictionary `{"schema_version", "next_id", "next_project_id", "records", "projects"}`:
- `schema_version`: strict integer `1`.
- `next_id`, `next_project_id`: strict monotonic integers in $[1, 100000000]$.
- ID counters are strictly greater than every allocated suffix and are never decremented or reused when records are dissolved or removed.

### 3.2 Settlement Record
Exact dictionary `{"uid", "name", "anchor", "claim_radius_q", "members", "buildings", "roles", "founded_tick", "last_review_tick", "status"}`:
- `uid`: `s_` followed by 8 decimal digits (`s_00000001` .. `s_99999999`).
- `name`: nonempty string, $\le 80$ Unicode characters, no control characters.
- `anchor`: exact anchor dictionary.
- `claim_radius_q`: integer in $[1, 131072]$.
- `status`: `"active"` or `"dissolved"`.
- **Empty-Building Active Founding Clarification:**
  - Active settlements allow $0 \le \text{len(buildings)} \le 128$. Zero buildings is valid upon initial founding while the first shelter project is being planned.
  - Active settlements require $1 \le \text{len(members)} \le 128$.
  - Dissolved settlements must have empty collections: `members = []`, `buildings = []`, `roles = {}`.
- `roles`: dictionary mapping member UIDs to `"builder"`, `"keeper"`, or `"watch"`. Role keys must be a subset of settlement members.
- `founded_tick`, `last_review_tick`: strict integers in $[0, 2^{63}-1]$ with $\text{founded\_tick} \le \text{last\_review\_tick} \le \text{engine.tick}$.

### 3.3 Project Record
Exact dictionary `{"id", "settlement_id", "builder_id", "building_kind", "anchor", "structure_uid", "status", "created_tick", "last_work_tick", "recipe", "paid"}`:
- `id`: `sp_` followed by 8 decimal digits (`sp_00000001` .. `sp_99999999`).
- `settlement_id`: references an active settlement.
- `builder_id`: valid resident string ($\le 128$ characters).
- `building_kind`: initially `"personal_shelter"`.
- `anchor`: exact anchor dictionary, validated to lie inside the owning settlement's claim.
- `status`: `"planned"`, `"funded"`, `"building"`, `"complete"`, `"cancelled"`, `"destroyed"`.
- **Cross-Field Payment and Structure Invariants:**
  - `"planned"`: `structure_uid is None` and all `paid` quantities are $0$.
  - `"funded"` / `"building"`: resolving `structure_uid` is linked, `paid == recipe`, structure progress $< 100$.
  - `"complete"`: resolving `structure_uid` is linked, `paid == recipe`, structure progress $== 100$, structure UID added to settlement `buildings`.
  - `"cancelled"`:
    - Cancelled before placement: `structure_uid is None` and `paid` is zero.
    - Cancelled after funding: retains `structure_uid` and `paid == recipe` (materials remain invested; no automatic refund).
  - `"destroyed"`: `structure_uid is None`, `paid == recipe` (retained for loss accounting), unlinks building from settlement `buildings`, emits structured audit record.
- **Single Open Project Invariant:** At most one project in status `{"planned", "funded", "building"}` per settlement at any time.

### 3.4 Finite Caps & Exclusivity
- **Max Settlements:** 32 (configurable).
- **Max Retained Projects:** 64 (configurable).
- **Max Building Links:** 1024 (configurable).
- **Global Member Cap:** `cfg.MAX_HUMANS` (default 100, configurable).
- **Member Exclusivity:** A living resident can belong to at most one active settlement globally.
- **Building Exclusivity:** A runtime structure UID can belong to at most one settlement globally.

---

## 4. Authoritative Resolvers and Decoupled Lifecycle

The registry does not cache transient tensor slots (`slot_id`) across ticks. All external identity verification is delegated to caller-provided callbacks:

1. **`human_resolver(human_uid: str) -> dict | bool`:**
   - Validates existence in authoritative resident store.
   - Enforces living status for active settlement membership and new project planning.
   - Deceased residents remain valid historical references for completed/terminal projects.
   - Never enforces hardcoded regex patterns on resident UIDs.
2. **`structure_resolver(structure_uid: str) -> dict | bool`:**
   - Validates existence across active rows (`m_tensor`) or dormant store records (`StructureStore`). Dormant structures are valid, not missing.
   - Verifies overworld location (`space == 0`).
   - Verifies structure classification (`type in STRUCTURE_TYPES`).
   - Rejects generated chunk features (`c...:...`).
   - Verifies progress criteria ($100$ for completion, $< 100$ for ongoing construction).

---

## 5. Defensive Copies and Atomic Staged Restore

- **Immutability Protection:** Every read accessor (`get_settlement`, `get_project`, `list_settlements`, `list_projects`, `export_state`) returns deep copies. Mutating returned data structures has zero impact on internal state.
- **Atomic Restoration:** `restore_state(payload, ...)` stages complete structural, cap, reference, and cross-field invariant validation before applying state. If any validation step fails, the prior registry state is guaranteed 100% untouched.

---

## 6. Exact API Reference

The module `at_the_beginning.harness.settlements` exposes:

### Classes:
- `SettlementRegistry(config: SettlementConfig | None = None)`
- `SettlementConfig(...)`
- `SettlementError(Exception)`
- `SettlementValidationError(SettlementError)`
- `SettlementCapError(SettlementValidationError)`
- `SettlementReferenceError(SettlementValidationError)`
- `SettlementConflictError(SettlementValidationError)`

### Spatial and Validation Functions:
- `make_anchor(chunk_x, chunk_y, sub_x, sub_y) -> dict`
- `validate_anchor(anchor, name="anchor") -> dict`
- `normalize_subunits_to_anchor(total_sub_x, total_sub_y) -> dict`
- `quantize_unit_to_anchor(world_x, world_y) -> dict`
- `quantize_chunk_local_to_anchor(chunk_x, chunk_y, local_x, local_y) -> dict`
- `anchor_to_total_subunits(anchor) -> tuple[int, int]`
- `anchor_to_local(anchor, origin_cx, origin_cy) -> tuple[float, float]`
- `anchor_diff_q(anchor_a, anchor_b) -> tuple[int, int]`
- `anchor_distance_sq_q(anchor_a, anchor_b) -> int`
- `is_point_in_claim(point_anchor, claim_anchor, claim_radius_q) -> bool`
- `claims_overlap(anchor_a, radius_a_q, anchor_b, radius_b_q, inclusive=True) -> bool`
- `validate_strict_int(val, name, min_val=None, max_val=None) -> int`
- `validate_finite_number(val, name) -> float`
- `validate_string(val, name, min_len=1, max_len=128, allow_control=False) -> str`
- `require_exact_keys(d, expected, context) -> None`

### Registry Instance Methods:
- `create_settlement(name, anchor, claim_radius_q=None, members=(), buildings=(), roles=None, current_tick=0, human_resolver=None, structure_resolver=None) -> str`
- `dissolve_settlement(settlement_id, current_tick=0) -> None`
- `add_member(settlement_id, human_uid, role=None, current_tick=0, human_resolver=None) -> None`
- `remove_member(settlement_id, human_uid, current_tick=0) -> None`
- `set_role(settlement_id, human_uid, role, current_tick=0) -> None`
- `add_building(settlement_id, structure_uid, structure_resolver=None, current_tick=0) -> None`
- `remove_building(settlement_id, structure_uid, current_tick=0) -> None`
- `create_project(settlement_id, builder_id, building_kind="personal_shelter", anchor=None, recipe=None, current_tick=0, human_resolver=None) -> str`
- `fund_project(project_id, structure_uid, paid=None, current_tick=0, structure_resolver=None) -> None`
- `advance_project_work(project_id, current_tick=0, structure_resolver=None) -> None`
- `complete_project(project_id, current_tick=0, structure_resolver=None) -> None`
- `cancel_project(project_id, current_tick=0) -> None`
- `destroy_project(project_id, current_tick=0) -> dict`
- `get_settlement(uid) -> dict`
- `has_settlement(uid) -> bool`
- `list_settlements(status=None) -> list[dict]`
- `get_project(project_id) -> dict`
- `has_project(project_id) -> bool`
- `list_projects(settlement_id=None, status=None) -> list[dict]`
- `get_open_project(settlement_id) -> dict | None`
- `find_settlement_by_member(human_uid) -> str | None`
- `find_settlement_by_building(structure_uid) -> str | None`
- `export_state() -> dict`
- `validate_state(payload, human_resolver=None, structure_resolver=None, current_tick=None) -> None`
- `restore_state(payload, human_resolver=None, structure_resolver=None, current_tick=None) -> None`

---

## 7. Test Suite Verification Matrix

The test suite in `tests/test_settlement_registry_1010.py` comprises 20 rigorous test cases verifying:
1. `test_strict_int_rejects_bool`: Rejection of `True`/`False` as integers.
2. `test_strict_int_rejects_float_and_str`: Rejection of float, string, None.
3. `test_strict_int_bounds`: Enforcement of lower and upper numeric boundaries.
4. `test_finite_number_rejects_nan_and_inf`: Rejection of NaN, Infinity, -Infinity.
5. `test_validate_string_rejects_control_characters`: Rejection of `\x00`, `\n`, `\t`.
6. `test_anchor_exact_schema`: Strict enforcement of exact `{"chunk", "sub"}` keys.
7. `test_negative_subunits_floor_division_normalization`: Bit-exact divmod floor normalization.
8. `test_large_coordinates_near_max_abs_coord`: Validation at and beyond $\pm 2^{40}$.
9. `test_integer_first_local_conversion_and_origin_invariance`: Exact preservation of coordinates across origin shifts.
10. `test_quantization_and_tie_breaking`: Snapping to grid with half-up tie resolution.
11. `test_claim_distance_and_overlap_boundary`: Exact boundary evaluation at distance $R$ vs $R+1$.
12. `test_active_settlement_allows_zero_buildings_on_founding`: Empty building founding state verified.
13. `test_dissolved_settlement_must_be_empty`: Strict enforcement of empty collections on dissolution.
14. `test_dissolved_settlement_cannot_have_nonempty_members_on_restore`: Rejection of corrupted dissolved records.
15. `test_monotonic_ids_and_non_reuse_after_dissolution`: Strict monotonicity of `s_` and `sp_` IDs.
16. `test_roles_subset_and_valid_roles_enforced`: Role membership subset and allowed role names.
17. `test_global_member_exclusivity_and_cap`: Single-membership enforcement and `cfg.MAX_HUMANS` cap.
18. `test_global_building_ownership_and_caps`: Single-ownership enforcement and total link caps.
19. `test_human_resolver_living_vs_deceased_and_arbitrary_uid`: Living status check without regex limits.
20. `test_structure_resolver_active_and_dormant`: Dormant store support, overworld space, and type checks.
21. `test_single_open_project_per_settlement_invariant`: Enforcing max 1 open project.
22. `test_project_anchor_outside_claim_rejected`: Rejection of project outside settlement boundary.
23. `test_project_planned_to_complete_lifecycle`: Full project state transitions and structure linkage.
24. `test_cancel_before_placement_vs_cancel_after_funding`: Divergent cancellation semantics verified.
25. `test_destroy_project_invariants_and_audit`: Building unlinking and material loss audit emission.
26. `test_defensive_copies_prevent_in_place_corruption`: Deep copy immutability protection.
27. `test_failed_restore_preserves_prior_state_completely`: Atomic staging rollback verification.
28. `test_no_tensor_columns_or_engine_mutations`: Zero tensor pollution assertion.
29. `test_explicit_instantiation_only`: Absence of global singletons assertion.

---

## 8. Handoff for Codex and Pending Integration Work

This delivery provides the authoritative foundation. The following integration layers remain pending for downstream implementation:

1. **Site Candidate Search (`plan_settlement_site`):**
   - Integration with `systems/construction/sites.py` (`find_buildable_site`).
   - Finite lattice/ring candidate search (capped at 64 candidates, ordered deterministically by integer squared distance, then chunk/sub coordinates).
   - Dormant structure footprint checking against `StructureStore`.
   - Protection checking for authored obstacles (`M_MAP_OBJECT`, portals, doors, forges).
2. **Transaction Boundary & Material Payment (`commit_settlement_project`):**
   - Discrete item consumption from builder inventory (`Transfer(item, qty, builder_uid, None)` via `ItemPermit.consume`).
   - Full synchronous atomic staging and multi-row tensor rollback on fault injection.
   - Runtime structure instantiation (`create_object`, `_make_entity_id`).
3. **Persistence Integration & Save Compatibility (DR-22 OPEN):**
   - Top-level `settlement_state` in world memento envelope.
   - Required features versioning (`required_features={"settlement": 1}`).
   - Reader refusal contract: older readers without settlement support must refuse saves bearing non-empty settlement state before mutation, rather than silently stripping the state.
   - **DR-22 remains OPEN** for approved user refusal wording and version bump policy.
4. **Action Verbs & Resident Drivers:**
   - New Action verbs `settle_site` and `migrate_group` under `systems/actions/verbs/`.
   - Decision-driven resident execution integrating with Tier 1/2/3 action pipelines.
5. **Growth & Dormant Catch-up (R6.5):**
   - Periodic daily review linked to `harness/calendar.py` day boundaries.
   - Conserved resource consumption and birth/labor accounting (no synthetic population or material generation).


## Root verification of repaired foundation

2026-10-10:37unittest tests PASS. Initial repair test run had one fixture error: settlement created attick10 but later reference-failure probes omitted current_tick and therefore refused tick0 before reaching callback. Root supplied current_tick10 to those four intended role/reference cases, preserving assertions and implementation guards. Original invalidrole partial-member-write and oversized globalmember cap are fixed; strict structuretype/space metadata and staged copied restore covered. This verifies pure registry foundation, not live site/material/construction/save/growth. Next actual engine construction service assigned toAGY.
