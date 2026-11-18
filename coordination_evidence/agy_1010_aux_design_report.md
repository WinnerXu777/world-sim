# Coordination Evidence Report: Auxiliary Resident Hot-State Storage Architecture (R6.13)

**Document Reference:** `coordination_evidence/agy_1010_aux_design_report.md`  
**Companion Technical Specification:** `1010_aux_state_gap.md`  
**Author / Session:** Antigravity (Design Review & Architectural Re-alignment)  
**Date:** 2026-10-10 (Toronto)  
**Scope & Authority:** Authorized under R6.13 roadmap directive ("Prepare source-grounded design in 1010_aux_state_gap.md and coordination_evidence/agy_1010_aux_design_report.md ONLY. Native bounded reads/file writes ONLY, no RunCommand/shell/tests/Git/source changes"). Source sharing authorized today Toronto Oct 10.  
**Status:** REVISED DESIGN PROPOSAL — PENDING ROOT / ORCHESTRATOR INSPECTION.  
*(Notice: The initial design draft was NOT accepted, authoritative, or ready for implementation. It overstepped R6.13 by inventing gameplay mechanics and unmeasured performance claims instead of establishing a bounded hot-state storage architecture. This report documents the complete architectural correction.)*

---

## 1. Executive Summary & Architectural Scope Re-alignment

### 1.1 Corrective Mandate
Roadmap item **R6.13** (`1009roadmap.md:185, 253`) specifies:
> *"Aux tensor for hot per-resident state (only human column 31 is free) — design needed before any new per-resident column."*

R6.13 is an infrastructure requirement for a **bounded hot-state storage architecture before new columns are added**. It is **not** an authorization to invent new biological, cognitive, or psychological gameplay systems.

### 1.2 Summary of Architectural Corrections
In response to authoritative inspection, the following corrections have been executed across `1010_aux_state_gap.md` and this report:
1. **Purged Invented Gameplay**: Completely removed invented bleed half-life integrals, HP damage formulas, ambition/temperature/fear rates, and offscreen wake damage-capping rules (`safe_hp = max(...)`). Existing authoritative health, mood, and needs mechanics remain intact and unmutated.
2. **Purged Unmeasured Performance Claims**: Removed the invented "0.15 ms" tick overhead guarantee and unmeasured claims regarding cold-store dictionary performance. All future performance characterizations must be measured using the repository's `MEASURE` lock protocol.
3. **Preserved Human Column 31**: Preserved column 31 in `h_tensor` strictly as `H_RESERVED_31 = 31` (`genesis_config.py:116`). No single subsystem consumes column 31.
4. **Corrected Slot Generation & Identity Tokens**: Corrected the proposal to store slot generation counters in a float32 column (`H_AUX_GEN`). Float32 (IEEE 754) has only 24 bits of significand and loses integer identity beyond $2^{24} = 16,777,216$. Generation tokens are mandated as exact integers in a dedicated `int64` tensor or bounded Python metadata.
5. **Configurable Schema Framework (No Hardcoded 16 Gameplay Columns)**: Replaced the silently designated 16 gameplay fields with a configurable, explicit schema registry (`AuxSchema`, `AuxFieldSpec`) operating over a bounded row capacity of `cfg.MAX_HUMANS = 100`. Future consumers remain **explicitly pending**.
6. **Formally Withdrawn Data-Loss Default (Option B)**: Formally withdrew prior Option B, which recommended silently ignoring saved hot state in flag-off builds. Analyzed older-reader silent-drop behavior and delineated derived recomputable cache from authoritative hot state. Presented unresolved persistence choices for Root settlement without prematurely approving refusal strings or format bumps.
7. **Grounded Test Matrix in Real Harnesses**: Grounded all test specifications in existing unittest suites and golden trace tools (`tools/golden_trace.py --check --strict` via `tests/test_harness_golden.py`). Purged non-existent modules (`test_golden_strict.py`, `600tickcheck`).

---

## 2. Authoritative Source Evidence & Line Citations

Every element of the revised architecture is directly substantiated by authoritative codebase references:

| Subsystem / Invariant | Authoritative Source File & Lines | Inspected Architectural Reality | Corrected Design Contract |
|---|---|---|---|
| **Human Tensor Shape & Allocation** | `at_the_beginning/genesis_config.py:47-49, 70-117` | `MAX_HUMANS = 100`, `HUMAN_TENSOR_COLS = 32`. Cols `0..30` actively allocated (vitals, masks, `H_SPACE=29`, `H_RESTRAINED=30`). Col 31 is explicitly `# 31 reserved`. | `h_tensor` shape remains strictly `(100, 32)`. Column 31 remains untouched and reserved. Auxiliary state is held in a separate bounded table. |
| **Float32 Mantissa Limit** | `at_the_beginning/genesis_config.py:105-107` (`G-D0-2`) | Codebase precedent: `ACQUIRED_INSTINCT_MASK` was split into 24-bit words because float32 loses integer precision beyond $2^{24}$. | Rejects float32 column `H_AUX_GEN`. Slot generation counters MUST be exact integers in separate `int64` tensor or bounded metadata. |
| **Existing Wounds Prototype** | `at_the_beginning/harness/wounds.py:1-215` | Prototype operates via `engine._wounds[uid]` mirrored to `resident["wound"]`, advancing on cadence 20 and mutating `h_tensor[:, HP]` and `h_tensor[:, H_INFECTION]`. | Health/infection semantics are owned by existing authoritative vitals. R6.13 does not displace, duplicate, or alter wound mechanics without a designated consumer. |
| **Engine State & Slot Lifecycle** | `at_the_beginning/map_test.py:400-405, 464-475, 4220-4289` | `WorldState` instantiates `h_tensor`. `reset_protocol_state` initializes `_human_uid_by_slot = [None] * MAX_HUMANS`. Death sync in `_sync_slot_ids_and_events` resets slot to `None`. | Auxiliary storage capacity matches `cfg.MAX_HUMANS = 100`. Cleared on death and spawn; generation counter increments on death. |
| **Window Re-base Invariance** | `at_the_beginning/harness/window_manager.py:303-350`, `at_the_beginning/systems/actions/rebase.py:1-115` | `WindowManager.rebase` shifts spatial coordinates `(dx, dy)` in local space for positions in `h_tensor[:, :2]`. | Auxiliary fields represent intrinsic biological or mental states; they are purely scalar and strictly invariant to window rebases ($\partial h_{\text{aux}} / \partial x = 0$). |
| **Dormancy Lifecycle** | `at_the_beginning/harness/dormancy.py:1-170` | `freeze` copies dormant rows; `thaw` writes them back bit-identical. `wake` applies closed-form catch-up to hunger, thirst, age, stamina, threat. | Auxiliary state of dormant residents is frozen and thawed bit-for-bit. Wake preserves existing catch-up without invented offscreen damage immunity. |
| **Persistence Validator & Refusals** | `at_the_beginning/persistence/world_snapshot.py:1-326` | `validate` enforces tensor shape and dtype equality. Spaces (format 2), window (format 3), structure store (format 4), and calendar each refuse incompatible older/differing sessions before mutating the world. | Silent drop of authoritative state is rejected as data loss. Framework requires compatible validated persistence or explicit refusal for authoritative fields. |
| **Deterministic Golden Harness** | `tools/golden_trace.py:1-250`, `tests/test_harness_golden.py:1-67` | Golden traces check 11 checkpoints (seed 1008, 3600 ticks). Flag-off runs (`EDEN_AUX_STATE=0`) must match sha256 exactly. | Flag-off builds allocate no auxiliary state, run zero auxiliary hooks, and maintain 100% bit-identical golden traces. |

---

## 3. State Ownership: Authoritative State vs Derived Cache

A central requirement of the revision is distinguishing **derived recomputable cache** from **authoritative state**:

```
+--------------------------------------------------------------------------------------------------+
|                                     STATE OWNERSHIP ANALYSIS                                     |
+-------------------------------------------------+------------------------------------------------+
|          DERIVED RECOMPUTABLE CACHE             |            AUTHORITATIVE HOT STATE             |
+-------------------------------------------------+------------------------------------------------+
| Definition:                                     | Definition:                                    |
| Numerical fields that can be deterministically  | Numerical fields that represent primary ground |
| reconstructed from authoritative sources:       | truth that exists nowhere else:                |
| - Primary vitals in h_tensor (HP, stamina, etc.)| - Acute bleed rate (if not in resident JSON)   |
| - Map context, active structures, shelter       | - Acute thermal deviation                      |
| - Resident JSON records (profile, traits)       | - Acute uncommitted drive levels               |
|                                                 |                                                |
| Persistence & Recovery:                         | Persistence & Recovery:                        |
| - Safe to discard on world save.                | - MUST be saved in world snapshot.             |
| - Older readers / flag-off builds can drop with | - Older readers / flag-off builds CANNOT drop; |
|   zero data loss.                               |   doing so causes permanent data loss!         |
| - Automatically recomputed on engine boot via   | - Requires compatible validated persistence    |
|   registered rebuild_fn(engine, slot).          |   or explicit user-approved refusal.           |
+-------------------------------------------------+------------------------------------------------+
```

### 3.1 Preservation of Existing Health Semantics
* **Authoritative Health Owner**: `h_tensor[:, HP]` (column 3), `h_tensor[:, H_INFECTION]` (column 8), and `at_the_beginning/harness/wounds.py` currently manage health and injury progression.
* **No Premature Displacement**: The auxiliary storage framework provides an extensible numerical storage plane. It does **not** move, alter, or duplicate health semantics without a designated consumer formally assigned by Root / Orchestrator.
* **Pending Consumers**: Specific consumer systems (wounds, temperature, drives) remain **explicitly pending**.

---

## 4. Architectural Risk Analysis & Validated Mitigations

| Identified Hazard | Prior Draft Flaw | Root Cause Analysis | Corrected Mitigation in Revised Design |
|---|---|---|---|
| **Float32 Mantissa Overflow** | Proposed `H_AUX_GEN = 12` in float32 tensor. | Float32 mantissa has only 24 bits ($2^{24} = 16,777,216$). Higher integer values lose precision and identity, corrupting slot recycling. | Slot generation counters are stored as **exact integers** in a separate `int64` tensor (`_aux_slot_gen`) or bounded Python metadata. UID tokens use exact strings in `_human_uid_by_slot`. |
| **Data Loss via Silent Drop** | Recommended Option B (silently ignore saved aux state when flag is off). | If a save containing authoritative state is opened in a flag-off build and re-saved, that authoritative state is permanently lost. | **Option B is withdrawn.** Established strict distinction: derived cache can be dropped/rebuilt safely; authoritative state requires validated persistence or explicit refusal before reset. |
| **Premature Gameplay Invention** | Hardcoded 16 specific columns with invented bleed integrals, drive rates, and wake damage caps. | Overstepped R6.13 mandate by designing uncalibrated gameplay instead of a bounded storage architecture. | Retracted all invented gameplay. Established configurable schema framework (`AuxSchema`, `AuxFieldSpec`) with `cfg.MAX_HUMANS = 100` capacity. Consumers explicitly pending. |
| **Unmeasured Performance Guarantees** | Claimed "added tick latency $< 0.15\text{ ms}$" and made unmeasured claims about dictionaries. | Unverified performance assertions absent isolated timing benchmarks violate project empirical standards. | Removed all unmeasured claims. Benchmark protocols must follow repository's `MEASURE` lock protocol. |
| **Unsubstantiated Test Modules** | Invented `tests/test_golden_strict.py` and a 600-tick check. | Invented non-existent test modules instead of referencing actual test harnesses. | Grounded verification strictly in existing tools: `tests/test_harness_golden.py` (`tools/golden_trace.py --check --strict`), `tests/test_harness_window_saves.py`, `tests/test_harness_dormancy.py`. |
| **Mutation Corruption & Nonfinite Values** | Direct in-place writes without pre-validation. | `NaN` or `Inf` values or mismatched slot references corrupt contiguous tensor state mid-tick. | Implemented pure `plan_aux_mutation` (rejects nonfinite, bounds violations, UID/generation mismatches) and atomic `apply_aux_mutations` staged commit. |

---

## 5. Verification Strategy Grounded in Existing Tools

All verification requirements are grounded directly in existing test harnesses:

### Gate 1: Strict Flag-Off Golden Trace (Zero Regression)
* **Tool**: `tools/golden_trace.py --check --strict` (invoked via `tests/test_harness_golden.py`).
* **Requirement**: With `EDEN_AUX_STATE=0` (default), all 11 checkpoints across historical golden traces must produce 100% bit-identical SHA-256 hashes.
* **Grounding**: Proves that zero hooks, allocations, or state mutations leak into the default simulation path.

### Gate 2: Full Unit Suite Preservation
* **Command**: `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'`
* **Requirement**: All existing tests pass with zero failures and zero errors.

### Gate 3: Auxiliary Storage Unit Suite (`tests/test_harness_aux_state.py`)
* Patterned on existing unit tests:
  - `TEST-AUX-01`: Static allocation, shape `(100, cols)`, dtype `torch.float32`, column 31 in `h_tensor` untouched.
  - `TEST-AUX-02`: Slot recycling, exact integer `int64` generation counter increment, zeroing on birth/death, stale UID rejection.
  - `TEST-AUX-03`: Pure planning rejection of `NaN`, `Inf`, out-of-range slots, mismatched UIDs, and stale generations; staged atomic batch commit.
  - `TEST-AUX-04`: Dormancy freeze and thaw bit-identity (patterned on `tests/test_harness_dormancy.py`).
  - `TEST-AUX-05`: Window rebase scalar invariance (patterned on `tests/test_harness_window_manager.py`).
  - `TEST-AUX-06`: Save and restore roundtrip with validated schema (patterned on `tests/test_harness_window_saves.py`).
  - `TEST-AUX-07`: Backward compatibility on legacy formats 1..4 (patterned on `tests/test_harness_window_saves.py`).

---

## 6. Unresolved Persistence Choices for Root Settlement

In accordance with project governance, Antigravity does **not** unilaterally select save formats or approve user-facing refusal text. We present the architectural choices grounded in state ownership for Root settlement:

### Architectural Context
* Under `at_the_beginning/persistence/world_snapshot.py`, incompatible changes that introduce authoritative state that cannot be simulated or preserved in older/different sessions explicitly **refuse** continuation:
  - `REFUSAL_FORMAT_1_WITH_SPACES` / `REFUSAL_FORMAT_2_WITHOUT_SPACES` (Spaces, format 2).
  - `REFUSAL_FORMAT_12_WITH_WINDOW` / `REFUSAL_FORMAT_3_WITHOUT_WINDOW` (Streaming window, format 3).
  - `REFUSAL_FORMAT_4_UNSUPPORTED` (Dormant structure store, format 4).
  - `REFUSAL_CALENDAR_LONG_WITHOUT` / `REFUSAL_CALENDAR_SHORT_WITH` (Calendar C4).

### The Real Persistence Policy Choices

#### Choice A: Pure Recomputable Cache Architecture (Zero Save Format Impact)
* **Premise**: The auxiliary tensor is designated exclusively as an in-memory execution cache for fast per-tick evaluation.
* **Persistence Handling**:
  - `h_aux` is NOT captured in world snapshots (or captured as an optional disposable cache).
  - On world load: All auxiliary fields are recomputed from primary vitals in `h_tensor` and resident JSON records via registered `rebuild_fn(engine, slot)`.
  - Older readers and flag-off sessions can safely ignore any cache data with zero data loss.
* **Trade-offs**:
  - *Pros*: Zero save format bumps; zero backward compatibility friction; works seamlessly on historical saves (formats 1..4).
  - *Cons*: Cannot store new ground-truth state that exists nowhere else.

#### Choice B: Authoritative Extension with Required-Feature Refusal
* **Premise**: Auxiliary columns contain ground-truth authoritative simulation state not represented elsewhere.
* **Persistence Handling**:
  - `h_aux` is serialized into world snapshots as a validated section.
  - An older reader or a session running without `EDEN_AUX_STATE=1` **refuses** to continue the save, preventing silent data loss before the world is mutated or reset.
* **Trade-offs**:
  - *Pros*: Full simulation expressiveness for new authoritative physical/mental state.
  - *Cons*: Introduces a save compatibility boundary; requires Root / User approval of format versioning and exact refusal strings.

**Status**: Antigravity presents these choices objectively. Root / User will record the necessary persistence decision when authoritative consumers are assigned.

---

## 7. Conclusion & Review Status

1. **Revised Specification Ready**: `1010_aux_state_gap.md` has been completely restructured into an actionable, bounded hot-state storage architecture.
2. **Strict Adherence to R6.13**: Invented gameplay, uncalibrated formulas, and unmeasured performance claims have been eliminated.
3. **No Code / Source Edits**: All work was conducted strictly via native bounded reads and document writes. No production source code, shell commands, or git commands were executed.
4. **Pending Root Review**: Both documents are submitted for Root / Orchestrator inspection prior to any implementation assignment.
