# 1010 Auxiliary Resident Hot-State Storage Architecture ([GAP] R6.13, Harness/Engine Plane)

**Author:** Antigravity (Repaired Architecture Specification for Root / Orchestrator Review)  
**Date:** 2026-10-10 (Toronto)  
**Status:** REPAIRED FOUNDATION ARCHITECTURE SPECIFICATION — PENDING ROOT VERIFICATION (Pure storage foundation repaired after root review repros; DR22 remains OPEN; no engine/vitals/persistence hooks)  
**Governing Roadmap Item:** `1009roadmap.md` R6.13 ("Aux tensor for hot per-resident state (only human column 31 is free)")  
**Traceability:** `1008decisions.md` (PART2-DEC item 2), `1008expandtools_instincts.md` (sections 2.0, 2.A2, 2.E1), `1008_instincts_wiring_gap.md`, `1008_dormancy_gap.md`, `1008_spaces_p4_p5_gap.md`.

---

## 1. Executive Summary & Problem Scope

### 1.1 Scope Clarification: Storage Architecture First
Roadmap item **R6.13** explicitly mandates:
> *"Aux tensor for hot per-resident state (only human column 31 is free) — design needed before any new per-resident column."*

This is an architectural requirement for **bounded hot-state storage infrastructure**, **NOT** the introduction of new biological, psychological, or cognitive gameplay mechanics. All uncalibrated gameplay formulas and unmeasured performance guarantees have been retracted.

This repaired specification establishes:
1. **Preserves Primary Tensor Invariants**: Human column 31 in `h_tensor` remains strictly reserved (`H_RESERVED_31 = 31`) and untouched.
2. **Decouples Hot Storage from Gameplay Semantics**: Configurable, statically bounded auxiliary tensor schema (`cfg.MAX_HUMANS` capacity, ceiling of 16 columns) without hardcoded gameplay fields.
3. **Encapsulation & Private Implementation Storage**: Storage tensors `_tensor` and `_slot_gen` are private implementation details. Normal public properties `.tensor` and `.slot_gen` return defensive clones, and metadata (`schema`, `capacity`, `device`, `dtype`) cannot be reassigned through normal public APIs to bypass validation. Note: Python private attributes are an implementation encapsulation boundary, not a security sandbox boundary.
4. **Rejects Out-of-Bounds Candidates (No Clamping)**: Candidate values outside declared bounds $[min\_value, max\_value]$ are strictly rejected (returning `None`), preserving entire storage on bad batches without silent clamping.
5. **Float32 Conversion and Boundary Rounding Validation**: Validates actual float32 conversion and rounded value vs declared bounds for defaults, mutations, and rebuilds, so finite Python values that store outside declared ranges (including narrow boundary-crossing rounding) are rejected.
6. **Frozen Slot Mutation Rejection & Distinct Lifecycle Reset**: Dormant frozen rows strictly reject value mutation through public `clear_slot` / `clear_aux_slot` (`FrozenRowMutationError`) as well as `apply_mutations`. Identity invalidation (`recycle_slot`) and `bind_slot` explicitly reset storage internally via dedicated lifecycle operations, preventing partial commitment.
7. **Strict Token Validation (No bool 0/1 Aliases)**: Strict type checking prevents `bool` values from aliasing generation counts (`expected_gen=True/False`) or UIDs.
8. **Engine Authority Validation**: Caller-supplied engine instances are strictly validated (checking `_human_uid_by_slot` structure and active state) without silently skipping validation when a caller supplies a malformed engine.
9. **DR22 Status**: Accepts `DERIVED_CACHE` field specs only; `AUTHORITATIVE` field specs remain rejected pending supported persistence (DR22 is OPEN).
10. **Scope Boundary**: Pure service storage foundation and unit tests only. No actual engine births, dormancy, window rebase, or save persistence integration coverage is claimed in this step.

---

## 2. Authoritative Codebase Audit & Existing State

### 2.1 The Current `h_tensor` Column Allocation
Authoritative inspection of `at_the_beginning/genesis_config.py:47-49, 70-117` establishes the concrete layout of the human tensor:
* **Dimensions & Type**: `(MAX_HUMANS, HUMAN_TENSOR_COLS) = (100, 32)`, contiguous `torch.float32`.
* **Allocated Columns**:
  - `0..3` (Shared): `X=0`, `Y=1`, `TYPE=2`, `HP=3`.
  - `4..9` (Character): `H_STRENGTH=4`, `H_FERTILITY=5`, `H_AGGRESSION=6`, `H_STAMINA=7`, `H_INFECTION=8`, `H_SHELTER=9`.
  - `10..18` (Life & Vitals): `H_SEX=10`, `H_AGE=11`, `H_LIFE_EXP=12`, `H_COOLDOWN=13`, `HUNGER=14`, `THREAT=15`, `MOOD=16`, `CRITICAL_HEALTH=17`, `ESCALATION_FLAG=18`.
  - `19` (Instinct Mask Word 0): `ACQUIRED_INSTINCT_MASK=19` (bits 0..23).
  - `20..24` (Social/Carry & Needs): `H_CARRYING=20`, `H_SKILL=21`, `H_TRIBE=22`, `H_PARENT_INSTINCTS=23` (bits 0..23), `THIRST=24`.
  - `25..28` (Precision Split Words): `ACQUIRED_INSTINCT_MASK_1=25` (bits 24..47), `ACQUIRED_INSTINCT_MASK_2=26` (bits 48..63), `H_PARENT_INSTINCTS_1=27`, `H_PARENT_INSTINCTS_2=28` (`G-D0-2` precision fix).
  - `29`: `H_SPACE=29` (first-class space identity for interiors, Stage 2 P2/P3, `D-001`).
  - `30`: `H_RESTRAINED=30` (combat restraint tick counter, Defend Phase 1, `c2cabe8`).
  - `31`: **`# 31 reserved`** (`genesis_config.py:116`).

**Invariant**: Column 31 is the single remaining unallocated slot in `h_tensor`. R6.13 requires that column 31 NOT be consumed by any single subsystem, preserving it as a global reserve while providing an extensible auxiliary hot-state plane.

### 2.2 Actual Existing Wounds and Health State
Inspection of `at_the_beginning/harness/wounds.py:1-215`:
* Authoritative health (`HP`), infection (`H_INFECTION`), hunger (`HUNGER`), thirst (`THIRST`), and stamina (`H_STAMINA`) already have authoritative homes and established lifecycle mechanics in `h_tensor`.
* The auxiliary storage architecture does NOT duplicate, displace, or redefine existing health semantics without a designated consumer/owner.

### 2.3 Semantic Disk Record vs Hot Tensor Storage
Inspection of `at_the_beginning/runtime/resident_store.py:42-50, 620-650`:
* `ResidentAgentStore` manages persistent JSON records under `.runtime/.../ResidentAgents/{human_id}.json`.
* Hot State Need: High-frequency per-tick numerical operations require bounded contiguous memory, but performance claims must remain unasserted until measured in an isolated benchmarking environment (`MEASURE` lock protocol).

---

## 3. State Ownership: Derived Cache vs Authoritative State

```
+---------------------------------------------------------------------------------------------------+
|                                     STATE CLASSIFICATION TAXONOMY                                 |
+-------------------------------------------------+-------------------------------------------------+
|          DERIVED RECOMPUTABLE CACHE             |            AUTHORITATIVE HOT STATE              |
+-------------------------------------------------+-------------------------------------------------+
| Definition:                                     | Definition:                                     |
| Values strictly computable from existing        | Ground truth numerical state not present in     |
| authoritative sources (primary h_tensor, map    | h_tensor, resident records, or world geometry.  |
| contracts, active modifiers, or resident JSON). |                                                 |
|                                                 | Persistence Requirement:                        |
| Persistence Requirement:                        | Must be persisted with validated schema.        |
| Safe to drop or recalculate on load. Zero risk  | If loaded by older/incompatible reader, dropping|
| of permanent data loss.                         | this state is PERMANENT DATA LOSS.              |
|                                                 |                                                 |
| Rebuild Contract:                               | Refusal Contract:                               |
| Recomputes cleanly upon engine start or wake;   | Incompatible reader must refuse load before     |
| legacy saves boot cleanly with zero migration.  | mutating or resetting world state.              |
|                                                 |                                                 |
| Status in this Foundation: ACCEPTED             | Status in this Foundation: REJECTED (DR22 OPEN) |
+-------------------------------------------------+-------------------------------------------------+
```

### 3.1 Classification Rules for the Auxiliary Plane
1. **Rule of Single Authority**: A semantic quantity must have exactly ONE authoritative owner.
2. **Rebuildability Guarantee**: Any field designated as *derived cache* must provide a registered deterministic rebuild function `rebuild_fn(engine, slot) -> float`.
3. **Pending Consumer Policy (DR22 OPEN)**: Authoritative field specs remain strictly rejected pending supported persistence. This foundation accepts `DERIVED_CACHE` specs only.

---

## 4. Bounded Hot-State Storage Architecture

### 4.1 Storage Dimensions and Resource Ceilings
* **Capacity**: Exactly `cfg.MAX_HUMANS = 100` rows (`genesis_config.py:47`).
* **Column Extensibility**: Configurable column allocation bounded by `MAX_AUX_COLS = 16`.
* **Data Type**: `torch.float32` contiguous tensor.
* **Device**: Statically bound to `engine.state.h_tensor.device` (CPU or CUDA).
* **Memory Footprint**: $100 \times 16 \times 4\text{ bytes} = 6,400\text{ bytes}$ (~6.25 KiB).
* **Import Allocation Correction**: Importing a Python module is not literally zero heap allocation, as Python interpreter module imports naturally allocate module, type, and function objects on the interpreter heap. The relevant architectural guarantee is that **no table, singleton, or tensor storage allocation occurs at module import time**; allocation is strictly explicit and caller-instantiated.
* **Float32 Underflow Policy**: Subnormal float32 values underflowing to zero are governed by standard IEEE 754 float32 semantics and are not treated as errors. Underflow-to-zero is not claimed as rejected without an implemented, documented refusal policy. Finite Python values whose float32 rounded conversion crosses declared schema boundaries are strictly validated and rejected.

### 4.2 Exact Integer Generation & Slot Tokens
Slot generation counters are stored as exact integers:
* Held on `AuxStateTable` as a dedicated 64-bit integer tensor: `_slot_gen = torch.zeros(capacity, dtype=torch.int64, device=dev)`.
* Eliminates IEEE 754 float32 mantissa truncation/aliasing beyond $2^{24} = 16,777,216$.
* Detects `MAX_INT64` exhaustion (`9223372036854775807`) rather than overflowing.
* Strict token typing: rejects `bool` values (no `bool=0/1` token alias).

---

## 5. Concrete Framework APIs & Mutation Pipeline

All operations on the auxiliary tensor follow a defensive, staged mutation pipeline:

```
+---------------------------------------------------------------------------------------------------+
|                                 AUXILIARY STORAGE MUTATION PIPELINE                               |
|                                                                                                   |
|  1. Candidate Mutation Request                                                                    |
|     (slot, field_idx, candidate_value, expected_uid, expected_gen)                                |
|                      |                                                                            |
|                      v                                                                            |
|  2. Pure Validation & Planning: plan_mutation(...)                                                |
|     - Check slot bounds: 0 <= slot < table.capacity                                               |
|     - Check slot active: table.is_active(slot)                                                    |
|     - Reject frozen slot: not table.is_frozen(slot)                                               |
|     - Verify UID match: table.get_uid(slot) == expected_uid                                       |
|     - Verify generation match: table.get_gen(slot) == expected_gen                                |
|     - Validate engine authority (if supplied): check _human_uid_by_slot, no silent skipping       |
|     - Validate candidate bounds: reject out-of-bounds (NO CLAMPING; returns None)                 |
|     - Validate float32 rounding: reject if rounded float32 stores outside declared bounds         |
|                      |                                                                            |
|                      v                                                                            |
|               AuxMutationDraft (Immutable staged draft, f32 validated)                            |
|                      |                                                                            |
|                      v                                                                            |
|  3. Atomic Batch Commit: apply_mutations(drafts)                                                  |
|     - Phase 1: Target deduplication (rejects duplicate slot, col targets)                         |
|     - Phase 2: Revalidate all drafts against live state; stage converted float32 values           |
|     - Phase 3: Atomic commit if all pass; on ANY failure, commit 0 and leave storage unchanged    |
+---------------------------------------------------------------------------------------------------+
```

### 5.1 Type Definitions and Primitives

```python
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional, Sequence, Any
import math
import torch
import genesis_config as cfg

class FieldOwnership(Enum):
    """Ownership category determining persistence and lifecycle semantics."""
    AUTHORITATIVE = auto()  # Ground truth; must be saved (DR22 remains OPEN)
    DERIVED_CACHE = auto()  # Recomputable; can rebuild on boot/wake; safe to drop

@dataclass(frozen=True)
class AuxFieldSpec:
    name: str
    column: int
    min_value: float
    max_value: float
    default_value: float
    ownership: FieldOwnership
    rebuild_fn: Optional[Callable[[Any, int], float]] = None

@dataclass(frozen=True)
class AuxSchema:
    cols: int
    fields: tuple[AuxFieldSpec, ...]

@dataclass(frozen=True)
class AuxMutationDraft:
    slot: int
    column: int
    value: float
    expected_uid: str
    expected_gen: int

class AuxStateTable:
    def __init__(
        self,
        schema: AuxSchema,
        capacity: int = cfg.MAX_HUMANS,
        device: Optional[torch.device] = None,
        dtype: torch.dtype = torch.float32,
    ):
        self._schema = schema
        self._capacity = capacity
        self._device = device if device is not None else torch.device("cpu")
        self._dtype = dtype
        self._tensor = torch.zeros((capacity, schema.cols), dtype=dtype, device=self._device)
        self._slot_gen = torch.zeros(capacity, dtype=torch.int64, device=self._device)
        self._uids: list[Optional[str]] = [None] * capacity
        self._active: list[bool] = [False] * capacity
        self._frozen: list[bool] = [False] * capacity
        for field in schema.fields:
            self._tensor[:, field.column] = field.default_value

    @property
    def schema(self) -> AuxSchema: return self._schema
    @property
    def capacity(self) -> int: return self._capacity
    @property
    def device(self) -> torch.device: return self._device
    @property
    def dtype(self) -> torch.dtype: return self._dtype
    @property
    def tensor(self) -> torch.Tensor: return self._tensor.clone()
    @property
    def slot_gen(self) -> torch.Tensor: return self._slot_gen.clone()
```

### 5.2 Key Behavioral Contracts
1. **Encapsulation**: Public access to `.tensor` and `.slot_gen` returns defensive clones. In-place writes to clones do not modify internal state. Reassignment of metadata raises `AttributeError`.
2. **Out-of-Bounds Rejection (No Clamping)**: `plan_mutation` returns `None` if the candidate value is outside `[min_value, max_value]` or if float32 rounding causes it to cross declared boundaries.
3. **Frozen Row Mutation Rejection**: `clear_slot` raises `FrozenRowMutationError` when called on a frozen row. `apply_mutations` commits 0 and preserves storage if any draft targets a frozen row.
4. **Distinct Lifecycle Reset**: Internal storage reset (`_reset_slot_storage_internal`) is used during `bind_slot` and `recycle_slot` to reset storage to schema defaults unconditionally without being blocked by frozen/inactive checks, preventing partial commits.
5. **No Bool Aliasing**: `expected_gen` strictly rejects `bool` (`True`/`False`), preventing `bool=0/1` aliasing against generation tokens.
6. **Engine Authority Validation**: If an `engine` is passed, the table strictly validates `engine._human_uid_by_slot` and active state without silently skipping authority checks.

---

## 6. Lifecycle Traceability & Pending Integration Seams

```
+---------------------------------------------------------------------------------------------------+
|                                  ENGINE LIFECYCLE HOOK TRACEABILITY                               |
+------------------------------+-----------------------------------+--------------------------------+
| Lifecycle Event              | Authoritative Code Reference      | Auxiliary State Storage Action |
+------------------------------+-----------------------------------+--------------------------------+
| 1. Engine & State Allocation | map_test.py:400-405 (WorldState)  | When EDEN_AUX_STATE=1:         |
|                              | map_test.py:464-475 (reset_state) | Allocate table; bind to state; |
|                              |                                   | initialize _slot_gen to 0.     |
+------------------------------+-----------------------------------+--------------------------------+
| 2. Human Spawn & Birth       | map_test.py:5056-5066 (spawn)     | When slot k claimed:           |
|                              | instincts_and_tools.py:993 (born) | bind_slot(k, uid);             |
|                              |                                   | retain exact generation.       |
+------------------------------+-----------------------------------+--------------------------------+
| 3. Human Death & Eviction    | instincts_and_tools.py:1148 (die) | When slot k dies:              |
|                              | map_test.py:4220-4289 (sync_slot) | recycle_slot(k) (bumps gen;    |
|                              |                                   | resets row internally).        |
+------------------------------+-----------------------------------+--------------------------------+
| 4. Window Re-base            | harness/window_manager.py:303-350 | INVARIANT: Coordinate-free;    |
|                              | systems/actions/rebase.py:1-115   | zero shift applied to h_aux.   |
+------------------------------+-----------------------------------+--------------------------------+
| 5. Dormancy Freeze & Thaw    | harness/dormancy.py:122-133       | freeze: freeze_slot(k);        |
|                              | harness/dormancy.py:135-154       | thaw: bit-identical values.    |
+------------------------------+-----------------------------------+--------------------------------+
| 6. Dormancy Wake             | harness/dormancy.py:156-170       | wake_slot(k, engine) rebuilds  |
|                              |                                   | derived cache atomically.      |
+------------------------------+-----------------------------------+--------------------------------+
```

> [!IMPORTANT]
> **Integration Disclaimer**: The hook points above document the target architecture for subsequent engine integration phases. **This foundation step does NOT claim or implement engine lifecycle integration**: births, deaths, dormancy freeze/thaw, window rebase, and save snapshot persistence remain unintegrated in this step. Current fields contain no authoritative state (DERIVED_CACHE only; DR22 remains OPEN).

---

## 7. Persistence Architecture & Older-Reader Analysis

### 7.1 Formal Withdrawal of Prior Option B
Silently dropping saved hot state that contains authoritative simulation data results in irreversible data loss. Prior Option B is retracted.

### 7.2 Persistence Policy Based on State Ownership

| Scenario | State Nature | Save / Load Contract | Compatibility Action |
|---|---|---|---|
| **Scenario 1: Pure Derived Cache** | All auxiliary columns are recomputable from `h_tensor` and resident JSON | Not saved in world snapshot, or saved as non-essential cache payload | Older readers can drop without loss; new builds recompute cleanly on boot via `rebuild_fn`. No format bump. |
| **Scenario 2: Authoritative Hot State** | Auxiliary columns contain ground-truth values not stored elsewhere | Must be persisted in snapshot payload with exact UID mapping | Older readers or flag-off builds CANNOT silently drop. Requires compatible validated persistence or **explicit refusal** before reset. (DR22 OPEN). |

---

## 8. Framework Implementation Phases

```
+---------------------------------------------------------------------------------------------------+
|                                  FRAMEWORK IMPLEMENTATION PHASES                                  |
+-------------------+-------------------------------------------------------------------------------+
| Phase             | Concrete Deliverables (No Invented Gameplay)                                  |
+-------------------+-------------------------------------------------------------------------------+
| Phase 1: Storage  | - AuxSchema, AuxFieldSpec, AuxStateTable in harness/aux_state.py.             |
| Primitives        | - Private implementation storage, defensive clones, read-only metadata.       |
| (THIS STEP)       | - Out-of-bounds rejection (no clamping), float32 rounding crossing validation.|
|                   | - Frozen row mutation rejection, distinct internal lifecycle reset.           |
|                   | - Strict token typing (no bool 0/1 alias), engine authority validation.       |
|                   | - Verified by 27 pure service unit tests in test_harness_aux_state_1010.py.    |
+-------------------+-------------------------------------------------------------------------------+
| Phase 2: Lifecycle| - Wire clear_aux_slot into instinct_born and Engine.spawn.                    |
| Synchronization   | - Wire exact integer _aux_slot_gen increment into _sync_slot_ids_and_events.  |
| (PENDING)         | - Add auxiliary tensor to freeze/thaw in harness/dormancy.py.                 |
+-------------------+-------------------------------------------------------------------------------+
| Phase 3: Validated| - Validated payload serialization behind EDEN_AUX_STATE flag.                 |
| Persistence Seam  | - Wire Root-approved refusal or rebuild policy (settling DR22).               |
| (PENDING)         |                                                                               |
+-------------------+-------------------------------------------------------------------------------+
| Phase 4: Consumer | - EXPLICITLY PENDING: Wounds, temperature, and drive consumers are NOT        |
| Integration       |   assigned or implemented until designated by Root / Orchestrator.            |
+-------------------+-------------------------------------------------------------------------------+
```

---

## 9. Verification Matrix

| Test Suite / Area | Harness / Runner | Scope / Scenarios | Status |
|---|---|---|---|
| Pure Service Foundation | `tests/test_harness_aux_state_1010.py` | 27 focused unit tests: allocation, schema validation, DERIVED_CACHE enforcement, float32 bounds and rounding-crossing rejection, private implementation storage and clone encapsulation, frozen slot mutation rejection, internal lifecycle reset, strict token types without bool alias, engine authority validation, and atomic batch preservation. | **Implemented & Repaired** (Root verification pending) |
| Engine Lifecycle Hooks | Engine step / dormancy runners | Live engine births, deaths, dormancy freeze/thaw, and window rebase integration. | **Pending Phase 2** |
| Persistence & Snapshots | Save/load roundtrip runners | World snapshot roundtrip and older-reader compatibility. | **Pending Phase 3 (DR22 OPEN)** |
| Strict Goldens | `tools/golden_trace.py --check --strict` | Flag-off identity verification across all 11 checkpoints under `EDEN_AUX_STATE=0`. | **Preserved** (Unchanged flag-off baseline) |

---

## 10. Summary for Root / Orchestrator Review

1. **Storage-First Foundation Repaired**: Out-of-bounds candidates are strictly rejected rather than silently clamped. Internal tensors are encapsulated in private storage, public accessors return defensive clones, and metadata is read-only.
2. **Lifecycle & Mutation Integrity**: Frozen slots reject public clear and apply operations. Lifecycle reset during bind and recycle operates internally, eliminating partial commit hazards.
3. **Numeric & Token Rigor**: Float32 rounding that crosses declared schema boundaries is strictly rejected. Integer tokens reject bool aliasing. Malformed engine authority arguments are validated without silent skipping.
4. **False Claims Corrected**: Corrected claims regarding import heap allocation, float32 underflow-to-zero, and engine integration coverage.
5. **DR22 Status**: Accepts `DERIVED_CACHE` field specs only; `AUTHORITATIVE` field specs remain rejected pending supported persistence. DR22 remains OPEN. Root verification is pending.
