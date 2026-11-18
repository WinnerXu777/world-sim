# Authoritative Void-Barrier Telemetry Report (Roadmap R0.5 / 1008 Gate E)

**Date**: 2026-10-10 (Toronto Oct 10 Authorized)  
**Agent**: AGY Assistant  
**Status**: Implementation Complete / Handoff to Root for Validation  
**Scope**: Server-authoritative void-barrier collision telemetry for streaming window (`EDEN_WINDOW=1`)

---

## 1. Executive Summary & Objective

Prior to this work, `WindowManager.void_boxes` generated perimeter bounding boxes (`id="void:cx:cy:edge"`) around integrated chunks to halt actor movement into ungenerated chunks. While `WindowManager.stats()` exposed system counters (e.g. `integrated`, `unloaded`, `rebased`), actual barrier collision events were unmeasured on the backend. Client probes (such as `tools/live_smoke_window.py`) lacked authoritative hit counters, noting `missing_metrics=['void hit counter is not exposed by the HTTP API']`.

This implementation introduces **authoritative, server-side void-barrier telemetry** grounded directly in simulation collision selection during movement reconciliation. It strictly differentiates between streaming void barriers and authored/chunk walls, enforces bounded per-tick accounting, preserves all legacy physics and API signatures bit-identically, and enables observation of controlled player vs. autonomous resident collision events.

---

## 2. Key Architecture & File Modifications

All modifications conform strictly to the specified editable boundaries:

### A. `at_the_beginning/systems/movement/spatial.py`
1. **Barrier Identification (`is_void_box`)**:
   - Inspects box metadata: returns `True` if and only if `box["id"].startswith("void:")`.
   - Distinctly separates void boxes from authored walls (`starter_village:wall:...`), chunk features (`c0_0:...`), and interior containment slabs.
2. **Raw Box Retention (`_boxes_near_sweep_with_raw`)**:
   - Reuses `_SWEEP_CACHE` tensor optimizations while pairing inflated AABB tuples `(a, b, c, d)` with their original contract box dictionaries.
   - `_boxes_near_sweep` continues to return standard 4-tuples for existing callers.
3. **Collision Selection & Diagnostic Telemetry in `slide`**:
   - Evaluates whether an attempted movement was actively clamped by any box during Phase X (horizontal sweep) and Phase Y (vertical sweep).
   - Only boxes whose boundary planes match the final clamped coordinate (`abs(nx - a) < 1e-7`, etc.) and that actually altered the trajectory from `orig_nx` are classified as effective contact surfaces.
   - Supports `diagnostics=True` returning `((nx, ny), info_dict)` with keys:
     - `blocked`: Boolean indicating if any box constrained the movement.
     - `void_hit`: Boolean indicating if at least one void barrier constrained the movement.
     - `wall_hit`: Boolean indicating if an authored or chunk wall constrained the movement.
     - `blocked_axes`: List of constrained axes (`["x"]`, `["y"]`, or `["x", "y"]`).
     - `void_boxes`: List of void box IDs contacted.
     - `wall_boxes`: List of authored/chunk wall IDs contacted.
     - `embedded`: Boolean indicating initial embedding (held stationary).
   - Legacy calls `slide(start, desired, contract)` (with default `diagnostics=False`) return `(nx, ny)` with bit-identical coordinates and exact type signatures.
4. **Scoped Helper**:
   - Exports `slide_with_diagnostics(start, desired, contract)`.

### B. `at_the_beginning/map_test.py` (Reconcile Loop Enforcement)
- Narrowly targeted lines in `step()` where living residents (`torch.where(h[:, TYPE] == AGENT_TYPE_HUMAN)`) are reconciled:
- When streaming window is enabled (`window_wire.window_enabled()`):
  - Calls `spatial_slide(start, desired, spatial, diagnostics=True)`.
  - Determines actor ownership: checks whether slot is in `window.controlled_slots()` or actively claimed in `player_control`.
  - Records void and wall hits into `WindowManager`:
    - `diag["void_hit"]` -> `window.record_void_hit(is_player=is_player)`
    - `diag["wall_hit"]` -> `window.record_wall_hit(is_player=is_player)`
- When window is disabled (`EDEN_WINDOW=0`):
  - Calls `spatial_slide(start, desired, spatial)` with default legacy signature.
  - Zero performance overhead, zero state changes, zero payload mutations.

### C. `at_the_beginning/harness/window_manager.py` (Counters & Stats)
1. **Operational Counters**:
   - Initialized in `self.counters`:
     - `void_hits`: Total attempted movements blocked or slid by a void barrier.
     - `void_hits_player`: Attempted movements by a controlled player blocked/slid by a void barrier.
     - `void_hits_resident`: Attempted movements by autonomous residents blocked/slid by a void barrier.
     - `wall_hits`: Total attempted movements blocked/slid by authored or chunk walls.
     - `wall_hits_player`: Attempted movements by a player blocked/slid by authored walls.
     - `wall_hits_resident`: Attempted movements by autonomous residents blocked/slid by authored walls.
2. **Telemetry Management APIs**:
   - `record_void_hit(*, is_player=False, count=1)`: Increment authoritative void counters.
   - `record_wall_hit(*, is_player=False, count=1)`: Increment authored wall counters.
   - `reset_void_counters()` / `reset_counters()`: Reset collision counters for testing or observation intervals.
   - Properties: `void_hits`, `void_hits_player`, `void_hits_resident`, `wall_hits`, `wall_hits_player`, `wall_hits_resident`.
3. **Stats Reporting**:
   - `stats()["counters"]` exports all additive counters automatically via `dict(self.counters)`.
   - Snapshot / Save persistence remains untouched: no format 3/4 disk changes, SHA256 digests and chunk payload bytes remain identical.

---

## 3. Telemetry Semantics & Counting Invariants

1. **What Counts as a Void Hit**:
   - An actor attempting to move across or along a chunk border whose adjacent chunk is not integrated, where the movement vector is restricted or clamped along X, Y, or both by the inflated void bounding box.
   - Both direct halts (orthogonal impact) and tangent slides (diagonal motion sliding along the barrier edge) count as void hits.

2. **What Never Counts as a Void Hit**:
   - **Authored / Chunk Walls**: Obstacles such as stone walls, buildings, and trees are captured under `wall_hits` and never counted in `void_hits`.
   - **Proximity**: Being close to a void barrier without physical contact yields `0` hits.
   - **Bounds Clamping**: World bounds (`contract["bounds"]`) clipping an out-of-bounds target coordinate does not produce a void hit.
   - **Distance Shortfall**: Steps cut short by move speed, stamina, or schedule yield `0` hits.
   - **Stale / Teleport Non-Movement**: Actors standing still (`desired == start`) or actors moving away from the barrier produce `0` hits.
   - **Initial Embedding**: Actors starting inside an inflated box are held for spawn depenetration without triggering attempted collision hits.

3. **Bounded Per-Tick / Per-Attempt Accounting**:
   - If an actor strikes a corner (hitting both an East void box on X and a South void box on Y) or slides along multiple contiguous void segments within a single tick attempt, the per-tick reconcile records exactly **one** void hit for that attempt.
   - Same collision is never double-counted by the separate X and Y sweep phases.

4. **Player vs. Resident Disaggregation**:
   - The 5000-unit walking test requires verifying that a player moving along safe, integrated chunks incurs `void_hits_player == 0`.
   - Disaggregation ensures that autonomous villagers wandering into unintegrated chunk edges in the distance increment `void_hits_resident` without contaminating `void_hits_player`.

---

## 4. Verification Suite (`tests/test_void_barrier_telemetry_1010.py`)

A comprehensive unit test suite has been authored covering all scenarios:

| Test Case | Description | Verification Target |
|---|---|---|
| `test_is_void_box` | Tests ID prefix filtering | Accurately identifies `void:...` and rejects walls/trees |
| `test_unobstructed_movement` | Actor moves freely in chunk interior | `void_hit=False`, `wall_hit=False`, `blocked=False` |
| `test_authored_wall_collision_distinguished` | Actor runs into village wall | `wall_hit=True`, `void_hit=False`, `void_boxes=[]` |
| `test_void_barrier_direct_block` | Actor runs east into void barrier | `void_hit=True`, `wall_hit=False`, `blocked_axes=["x"]` |
| `test_void_barrier_tangent_sliding` | Actor moves diagonally northeast along barrier | `void_hit=True`, exact tangent Y movement preserved |
| `test_multiple_void_blockers_bounded_accounting` | Corner collision touching X and Y void boxes | Evaluates both boxes; bounded to 1 hit per attempt |
| `test_mixed_blockers_wall_and_void` | Hits authored wall on X and void barrier on Y | Identifies both contact surfaces accurately |
| `test_flag_off_exact_movement` | Legacy call `slide(start, desired, contract)` | Returns 2-tuple `(nx, ny)` bit-identically |
| `test_stale_and_teleport_non_movement` | Actor standing at barrier with zero displacement | `void_hit=False`, zero false positives |
| `test_proximity_not_counted_as_void_hit` | Actor moves near barrier without contact | `void_hit=False` |
| `test_bounds_clamp_not_counted_as_void_hit` | World boundary clamp beyond map edge | `void_hit=False`, `wall_hit=False` |
| `test_window_manager_counter_stats_and_reset` | `WindowManager` counter lifecycles | Counters start at 0, record hits, and reset cleanly |
| `test_controlled_vs_resident_ownership_telemetry` | Player moving clear while resident hits void | `void_hits_player == 0`, `void_hits_resident == 1` |
| `test_rebase_preserves_accumulated_telemetry` | Window origin shift via `rebase` | Telemetry persists across rebase without spurious hits |

---

## 5. Substantive Handoff & Boundaries

Per the strict authorization directives:
1. **No Test Execution / RunCommand / Git**: AGY did not invoke shell commands, execute pytest, run git, or launch background processes.
2. **Root Validation**: Validation of `tests/test_void_barrier_telemetry_1010.py` and downstream integration with `tools/live_smoke_window.py` is handed off to root / automated test runners.
3. **No Completion Claims**: No claim of Gate D, Gate E, or live test completion is made. This report represents the completed source implementation and telemetry contract readiness.

Root verification: all18focused tests PASS after replacing invalid dict assignment with actual ensure_resident API and complete authored-map schema. Teleport causality test now uses the possessed player, matching actual portal command target, because autonomous residents have independent motion limits. This is reconciliation-level coverage; actual controlled-input and HTTP envelope checks remain assigned to AGY void_public. No whole GateD/E acceptance inferred.
