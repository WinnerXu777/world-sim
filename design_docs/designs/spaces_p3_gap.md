# 1008 spaces P3: plan and one design revision (GAP; docs only, no code until the orchestrator answers)

Written 2026-10-08 by the Harness worker [837dca] after P1 and P2 (HEAD 0273c95). It refines `./spaces_window_design.md` section 1 and asks for one decision (section 1). Labels: **read** = from code, **measured** = run, **inference** = reasoning.

## 0. Evidence from P2 that changes the plan
P2 made the 10 `pairwise_distances` sites space-aware. Reading the rest of the proximity code to plan P3 showed that the other spatial queries are **position-based and global**, and that they are what keeps the current multi-map worlds correct today:
- `map_geo.entities_in_radius` iterates all of `MAP_GEO` and reads `m_tensor` per entity (no space notion); callers: `nearby_entity_ids` (27 lines, 7 files), `nearest_geo_entity` (20 lines, 7 files), `best_resource_entity`, 3 more direct uses in `instincts_and_tools.py` / `systems/map/create.py`. **read**
- `map_geo.entity_at` and `TILE_TO_ENTITY` (one flat tile index for the whole frame, last writer wins): readers `instincts_and_tools.py:1794`, `perception/queries.py:73`, the tile-based human damage in `nature/hazards.py` (2 places) and `nature/disasters.py` (1). **read**
- Today these are correct for interiors only because the maps sit at disjoint coordinates in one frame (`EDEN_MAP_ORIGINS`) at least `ISOLATION_DISTANCE = 220` apart (`map_contract.validate_placement`); the engine's golden world registers the smith, lodge and west-cottage interiors at `[620, 0]`, `[620, 400]`, `[960, 160]` (`harness/headless.py`). **read**
- `world_contract(engine)` is called without any actor at 14 sites (`map_test.py` 3, `spatial.py` 3, `portal_commands` 1, `roster/{apply,driver,motion}` 5, `affordance/services` 1, `agent_driver` 1); the union contract (all maps + containment slabs) is correct for every actor because coordinates are disjoint. **read**

## 1. The decision: two ways to make interiors "separate spaces"
**Option S (true per-space coordinates, what section 1 of the design assumed).** Interior coordinates start at (0, 0); every geometry query gets a space argument: `entities_in_radius`, `entity_at`, tile keys in `TILE_TO_ENTITY`, ~30 callers in about 12 files, 17 contract call sites, the snapshot geometry. Large, invasive, and every miss is a silent cross-space leak (an interior rim position is numerically a village position).

**Option L (layout pockets; recommended).** A space is a first-class identity (id, map, bounds, revision, sha256) and every row/human carries it (`M_SPACE`, `H_SPACE`), but the engine keeps placing each interior at its **own disjoint region of the tensor coordinate frame** (its layout origin, today `EDEN_MAP_ORIGINS`). Geometry queries stay correct because coordinates are disjoint; proximity masks (P2) make the isolation a guarantee instead of a distance assumption; the wire and the save carry the space and its layout origin so a client can show space-local coordinates (`local = layout - origin`, the `maps[].origin` it already receives). For the infinite window (P5) the pockets come from a **pool** in a fixed layout region outside the window's coordinate range (section 5), so a window re-base never moves an interior and interiors can be of any size up to the pocket size.
- Why recommended: touches none of the ~25 geometry callers or the 14 contract sites; flag-off stays bit-identical by construction; a flag-on run differs from flag-off only in the two new columns (testable, section 4); the window needs disjoint coordinates anyway.
- What is given up: "coordinates start at (0, 0) inside the engine" (the wire can still present them that way) and the removal of `ISOLATION_DISTANCE` as a *distance* rule: P3 keeps the check because the position-based queries still rely on it; P5's pocket pool guarantees it by construction (pockets are separated by more than the largest query radius, `MIGRATION_SCAN_RADIUS = 480`).
- The orchestrator's D-001 wording ("interiors become separate spaces") is met at the identity, wire, save and proximity levels; the coordinate frame is an implementation detail Option L keeps.
**Question 1 for the orchestrator: Option L (recommended) or Option S?** If S, P3 becomes a multi-step phase of its own (geometry first) and I would write a second GAP with the caller list.

## 2. P3 under Option L: what it contains (all behind `EDEN_SPACES=1`, default off)
| Step | Change | Files (legacy ones marked *) | Size (inference) |
| --- | --- | --- | --- |
| P3a registry | `space` id per registered map: primary 0, secondaries 1.. in registration order; `info["space"]`; `maps_block` carries it only under the flag; `space_of_map`, `map_of_space`; a pure resolver `space_at(engine, x, y)`: the registered map whose bounds contain the point (closed), else 0 | `harness/spaces.py` (new), `systems/movement/map_contract.py`* | 10 lines + new file |
| P3b columns kept current | rows created from a map get `M_SPACE`; humans get `H_SPACE` from `space_at` at spawn, after a portal use (the portal command writes it explicitly) and by a cheap post-step refresh over the live humans (a few comparisons per human against the placed bounds, no tensor math); the refresh makes the column robust to every other mover (teleport powers, god commands, spawns) | `systems/map/authored.py`*, `simulation/portal_commands.py`*, a post-step hook in `harness/engine_hooks.py` | 25 lines |
| P3c queries | callers that already hold the actor pass its space where P2 added the argument (`agent_radial_mask`, `entity_radial_ids`, bounded `nearest_entity` already takes `space`/`space_col`); no change to `map_geo` | `systems/perception/*`*, `runtime/human_runtime.py`* | 15 lines |
| P3d wire | `space` per entity/human in frame and map payloads, `spaces` in `/bootstrap` (id, map_id, bounds, origin, revision, sha256); additive keys, flag-gated; key sets pinned by tests | `map_test.py`* (export functions) | 20 lines |
| P3e save format | schema 2 under the flag with the `world_format` block and `_spaces`; `SaveFormatError`; the two refusal messages as approved (SPACES-DEC 2); `compatible` in `GET /session`; `map_guard` unchanged (the origin comparison stays meaningful under Option L) | `persistence/world_snapshot.py`*, `checkpoints.py`*, `sessions.py`* (none) | 70 lines |
| P3f proof | `--spaces` golden, tests below | `tools/golden_trace.py`, `tests/golden/trace_seed1008_spaces.json`, `tests/test_harness_spaces_*.py` | tests |
Movement contracts stay the union contract (correct because coordinates are disjoint); a per-space `world_contract(engine, space)` is optional and deferred to P5, where the window needs it.

## 3. Flag-on semantics, concretely
- `EDEN_SPACES=1` requires `EDEN_PERCEPTION_BOUNDED=1` (design section 2); the boot refuses otherwise with a message naming the missing flag.
- A resident in an interior sees (bounded perception) only rows of its own space; two residents in different spaces never attract, infect, attack or mate (P2 masks); the 220-unit placement check stays.
- Wire space-local coordinates are **not** introduced in P3 (positions stay in the layout frame the client already handles through `maps[].origin`); the contract document will say so.

## 4. Proof plan for P3
1. Standing gate after each commit that touches a legacy file: golden `--check --strict`, default and `--resources`, on a `git archive` extract: bit-identical (flag off). Full suite once at the end of P3 (553 s at P2).
2. New `tools/golden_trace.py --spaces` and `tests/golden/trace_seed1008_spaces.json` (EDEN_SPACES=1 and EDEN_PERCEPTION_BOUNDED=1; bounded perception is itself a flag, so I will also record which differences come from which flag by running the flag combinations separately and reporting the table, as in the frontier-freeze document). Test: against the default golden, every field is identical except `m_sha256` and `h_sha256` (new columns), and resident fields that bounded perception legitimately changes are listed explicitly (expected: none in this world, to be measured).
3. Per step: registry ids stable across a restart (registration order), `space_at` on the boundary points of the 4 maps and a point in no map, `M_SPACE` of every authored row, `H_SPACE` after a portal round trip and after a teleport power, the post-step refresh equals a recomputation from positions on random states, wire key sets with the flag off equal today's (pinned), refusal messages verbatim, schema 1 saves still load with the flag off, schema 2 refused with the flag off and the other way round, `list_saves` `compatible` per format, snapshot round trip with the flag on is equal to the live state (tensors, `_spaces`).
4. Behaviour test: a resident in the smith interior with a village resident 4 units away numerically (forced by a test fixture that violates isolation on purpose) does not attract, attack or infect (the P2 masks), and the bounded `_build_case` ignores the other space's food row.

## 5. How P5 builds on it (preview, not asked now)
Interior pockets come from a pool: a fixed pocket region in the layout frame beyond the window's range (window-local coordinates stay inside `[-1280, 1536)`, section 4.1 of the design; pockets in `[4096, 8192)` in steps of 1024, ulp at most 4.9e-4), each interior space assigned a free pocket when it is activated (someone inside or scheduled to be) and released when empty. A window re-base shifts only rows with `M_SPACE == 0`. Under the pool the layout origin of a space is no longer a registry constant but part of the saved `_spaces` state.

## 6. Risks and unknowns specific to P3
- The post-step `H_SPACE` refresh costs a loop over live humans per tick (100 at most); to be measured against the tick profile (design target below 0.1 ms; **not measured**).
- `space_at` is ambiguous where bounds touch; closed rectangles, lowest space id wins, and registration refuses overlapping rectangles already (`validate_placement`), so the ambiguity needs a gap of at least the isolation distance and cannot occur.
- Resident records and Tier 1 memory store positions in layout coordinates; under Option L they stay valid across spaces (only a window re-base changes overworld coordinates, P5).
- I did not read the Godot client; whether it can use `space` and `maps[].origin` as proposed is for the client owner (`../contracts/client_contract.md` section 5 is updated to say that positions stay in the layout frame under P3).

## 7. What I will do on the orchestrator's answer
Option L approved: start P3a with tests, one commit per step (a to f), strict golden after each legacy-file commit, then send `[DONE]` with the gate results, then P3 [GAP] satisfied and the next [GAP] is for P4.
Option S chosen: stop, write the geometry caller list and a stepwise plan before any code.
