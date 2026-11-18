# 1008 spaces and window design (WS-D integration: D1, D6, D7, D8; design only, no code before the orchestrator's OK)

Written 2026-10-08 by the Harness worker [837dca]. Input: decision D-001 (interiors become separate spaces; old Stage 1 saves refused by Continue), `1008implementation.md` WS-D (D1, D2, D4, D6, D7, D8, D10, D11), `1008_d0_audit.md`, `1008_worldgen.md` (generator, rings and `ChunkService` are built by 2f0fd3), the harness `SpaceFrame` / `SpatialIndex` / `World` (built), and the engine files named below.

Labels: **read** = from reading the named code; **measured** = a script was run (scratch, not committed; the two capacity scripts are described in section 4.3); **inference** = reasoning, not run. Sizes of legacy edits are inferences.

Nothing here is implemented. Every legacy-file edit below needs the orchestrator's explicit authorisation per phase (section 9).

## 0. Verdict

1. The work splits into **three independent flags**, all default off, in this dependency order: `EDEN_PERCEPTION_BOUNDED` (already authorised, section 5), `EDEN_SPACES` (D1), `EDEN_WINDOW` (D6, D7; requires both others, the boot refuses `EDEN_WINDOW=1` without them). Routes (D8) have their own flag `EDEN_CHUNK_ROUTES` and need no engine change, so the client work can start first.
2. The invasive part is not the chunk streaming; it is **making every proximity and wall query space-aware and slot-reuse-safe**. The streaming itself is mostly new files (a window manager in `harness/`) plus a hook in the tick.
3. Window-relative positions with a re-base every 2 chunks of travel keep tensor magnitudes at today's 1200-unit scale (section 4.1). That means **the legacy collision tolerances behave as they do in Stage 1** and need no change; the cost is that all position-bearing state must survive a re-base (list in section 4.1, three of them are known bugs-in-waiting).
4. Capacity measured on the real generator (section 4.3): the 5 x 5 simulation ring needs on average 133 chunk entities plus up to 148 animals; the 7 x 7 keep ring on average 261 plus 289. Wall boxes must **not** be tensor rows (mean 115 boxes in 5 x 5, max 228). A row budget guard is required; 1024 rows is enough for the 5 x 5 ring, not for a fully loaded 7 x 7 ring.
5. Highest risk: slot allocation with unload (P5) and dormant residents (P6). Lowest: routes and the pure window manager (P0, P1). The flag-off goldens (default and `--resources`) must stay bit-identical after every phase; that is the standing gate.

## 1. D1 spaces

> **Superseded in part by Option L (approved by the orchestrator, built in P3; see section 1.5).** Sections 1.1 to 1.4 describe the first design, in which interiors get coordinates starting at (0, 0). Under Option L interiors keep their disjoint **layout** regions in the one tensor frame (`EDEN_MAP_ORIGINS`, the 220-unit isolation check and the containment slabs all stay, in P3 and flag on), and the space is an identity carried by the `M_SPACE` / `H_SPACE` columns, the wire and the save. Where 1.1 to 1.4 and 1.5 differ, 1.5 is what the code does.

### 1.1 Model [SUPERSEDED by 1.5, Option L]
- A **space** is a coordinate system with its own bounds and walls. Space `0` is the overworld. Every interior is its own space with local coordinates starting at `(0, 0)` (no origin offset, no 220-unit separation, no containment slabs).
- Columns: `H_SPACE = 29` (h_tensor), `M_SPACE = 31` (m_tensor), plus `M_GEN = 30` (m_tensor, generation counter, section 4.4). **read:** `h_tensor` 25 to 28 are taken (instinct-mask words, `genesis_config.py`), 29 to 31 are free; `m_tensor` 13 to 16 are the resource-node columns (G-005), animals document 13 to 31 as "reserved for species attrs" but nothing allocates past 12; a grep found no use of columns 29, 30 or 31 anywhere outside `genesis_config`. A new test asserts that no two column constants collide (a column ledger), so species attrs are later allocated from 17 to 29 only.
- Value `0` is the overworld and every existing row already holds 0 in these columns, so **flag-off and old-save semantics are unchanged by construction**.
- **Space registry** (new, `harness/spaces.py`, pure): `SpaceRegistry` maps `space_id <-> {map_id, kind (overworld | interior), bounds, actor_radius, revision, sha256, entry_portals}`. Ids are allocated in the registration order of the primary map's group and written into the save (section 1.4), never recomputed from file order. The overworld is id 0. The existing `map_contract` registry keeps keying contracts by map name; the registry adds the `space_id -> map name` link.
- Portals: `POST /control/portal` and `simulation/portal_commands.py` (read) already find the portal and teleport inside the same frame. With spaces the target is `(space, local x, y)`: the command writes `H_SPACE` and the position together, in one tick, after `is_standable_point` against the **target space's** contract. `PORTAL_REACH = 16` and `find_portal` are unchanged.

### 1.2 What goes away (flag on) [SUPERSEDED by 1.5, Option L]
`map_contract.ISOLATION_DISTANCE = 220` and `validate_placement` (maps no longer share a frame), `compose_group` / `containment_slabs` for the interiors (each space has its own bounds), and `EDEN_MAP_ORIGINS` (read in `map_contract.py` and four tools). Flag off they stay exactly as they are; the origin code path is untouched.

### 1.3 Space-aware queries (the invasive part) [SUPERSEDED by 1.5, Option L]
**read:** all legacy proximity goes through one helper since D-006: `harness.numerics.pairwise_distances`, called at 10 sites in 5 files (`instincts_and_tools.py` 872, 927, 1516, 1856, 1872, 1911; `systems/map/create.py` 438; `systems/nature/disasters.py` 206; `systems/nature/hazards.py` 93; `systems/perception/queries.py` 98, 115). Radial helpers on top: `entity_radial_ids`, `agent_radial_mask`, `nearby_entity_ids` (27 lines in 7 files), `map_geo.entities_in_radius`, `runtime/common.nearest_entity` and `nearest_human`. Design:
- `pairwise_distances(a, b, *, space_a=None, space_b=None)`: with spaces given, entries whose spaces differ are returned as `+inf` (a large finite value, no NaN). With both omitted the function is bit-identical to today. Each of the 10 sites passes the two space column slices it already has rows for: one extra argument per site (about 10 lines in total, inference), and a test per site that equal-space results are unchanged and a cross-space pair is never within any radius.
- The radial helpers get the same optional argument; `nearest_entity` / `nearest_human` get `space` (and, authorised by the orchestrator, `max_distance`; section 5).
- **Space-blind spots found while doing P2 (not `pairwise_distances`, so not covered by it; P3 must handle them):** the human damage of `apply_fire_tick` and `apply_flood` looks up the human's tile with `map_geo._px_to_tile_idx` and compares it with the tile masks of burning/flooded entities, so an interior position that coincides numerically with an overworld fire tile would be burned; the tile index must become per space (section 4.6 does that for the window, the space key is added there). The mate-attraction fallback in `instinct_move` is covered by review, not by a test (it needs a whole tick). `animal_instinct_move` and the other per-animal loops use no distance helper.
- Walls and the movement contract: `systems/movement/spatial.world_contract(engine)` becomes `world_contract(engine, space=None)`; `None` keeps today's behaviour (the primary space). **read:** it is called in `Engine.step` (once per tick), `map_test.py` at 4 places, `portal_commands.py:35`, and `systems/roster/{apply,driver,motion}.py`. The roster motion code groups its residents by space (typically 1 to 3 groups) and asks the contract per group. The wall list for a space is the `M_WALL` rows whose `M_SPACE` equals it (+ chunk wall boxes in window mode, section 4.5).
- Frames: `World.reindex` already reads `table.space_col`; the adapter's `ENTITY_COLUMNS` / `HUMAN_COLUMNS` gain `space`, and `SpatialIndex` is already keyed `(space, cx, cy)` (**read**). `World.frame` stays the overworld frame; a `frames: dict[space -> SpaceFrame]` is added with interiors as finite frames with `origin (0,0)` and `bounds` from the map.
- Wire: `/frame` and map entity exports carry `space` per entity (additive key; absent flag off); `/bootstrap` gains a `spaces` block (id, map_id, bounds, revision, sha256, `/map_file/<id>` already serves the bytes). The client draws the space of the controlled actor.

### 1.4 Save-format change and the Continue refusal [SUPERSEDED by 1.5, Option L]
**read:** `persistence/world_snapshot.py` writes `schema: 1`, `ENGINE_FIELDS` (a fixed tuple; `validate` requires `set(payload["engine"]) == set(ENGINE_FIELDS)`), the full tensors, `geometry` (`MAP_GEO` including every tile mask, `TILE_TO_ENTITY`), residents, runtimes, RNG. `validate` runs before `restore` mutates anything. `sessions.continue_world` calls `read` -> `loads` -> `validate` -> `restore`; `_session_operation` turns `ValueError` into HTTP 400 with `str(exc)` as detail. `map_guard.check` refuses (gameplay profile) a changed map file, with a message naming old and new revision and sha256.

Proposal:
- **Versioning by flag, not by build.** With `EDEN_SPACES` off the code writes exactly what it writes today (`schema: 1`), so existing saves keep working and the golden/save tests are untouched. With `EDEN_SPACES=1` (and `EDEN_WINDOW`) it writes `schema: 2` and an additional block `world_format = {"spaces": 1, "window": 0|1, "generator_version": ..., "world_seed": "<decimal string>"}`; `ENGINE_FIELDS` gains `_spaces` (the registry), `_window` (origin, loaded chunk set, slot allocator state) and `_world_seed`. `ENGINE_FIELDS_V2 = ENGINE_FIELDS + (...)`; `validate` picks the tuple from `schema`.
- **Refusals** (new `SaveFormatError(ValueError)`, raised from `validate` before anything is changed, so the running world is untouched; the file is never modified):
  - schema 1 save, flag on: `This save was made by an earlier version of the game (world format 1), in which interiors shared the overworld's coordinate frame. This version keeps interiors as separate spaces (world format 2), so the save cannot be continued. Start a new world; the old save file has not been changed or deleted.`
  - schema 2 save, flag off: `This save was made with separate interior spaces (world format 2, EDEN_SPACES=1), but this session runs without them, so it cannot be continued. Start the game with EDEN_SPACES=1 to continue it. The save file has not been changed.`
  - schema 2 with a different `generator_version` or `world_seed` than the running generator: same wording as the `map_guard` message (names saved and running `generator_version`), refused in the gameplay profile, overridable by `EDEN_ALLOW_MAP_MISMATCH=1` in development profiles like maps are.
  - An old build reading a schema 2 save already fails with the existing `Unsupported world schema; migration required`.
- **List before click.** `CheckpointStore.list_saves` returns `{save_id, name, id, sha256, tick, saved_at}`; I propose `commit` also stores `world_format` in the generation entry and `list_saves` returns `compatible: bool` (false when the entry's format differs from the running flags; entries without the key count as format 1). The client can grey the save out instead of letting the player hit the refusal. Additive; manifest `schema` stays 1.
- **Migration worth doing: none.** A format-1 save could in principle be converted (move the interior rows from their origin into local space coordinates, set `M_SPACE`, drop the slabs, rebuild the registry), but it would convert a world that has no chunk deltas, no generator seed and whose interiors may have been edited at origins; D-001 already accepted the refusal and the user has no saves outside development. I recommend writing the refusal and nothing else. If a migration is ever wanted, the converter is a pure function over the payload (the pickled `humans`/`entities` tensors and `geometry`), testable offline.
- `map_guard`: manifest entries replace `origin` by `space` when spaces are on; `mismatches` compares `space` instead of origin.
- Size of the save change: `world_snapshot.py` about 40 lines, `sessions.py` 0, `checkpoints.py` about 10 (inference).

### 1.5 As built in P3 (Option L)
**Registry.** `harness/spaces.py`, derived from `map_contract.placed_group(engine._map_name)` and stored nowhere: space 0 is the primary map, 1.. the secondaries in registration order. `space_table(engine)` rows: `space, map_id, kind, bounds, origin, revision, sha256` (layout frame). `space_at(engine, x, y)`: the interior whose rectangle contains the point (closed; lowest id wins), else 0. Legacy worlds (no authored maps): empty table, space 0 everywhere. `point_space(x, y)` is the same lookup for geometry code without an engine (None when the flag is off or there is no interior, meaning: do not filter).
**What stays (flag on).** `ISOLATION_DISTANCE`, `validate_placement`, `EDEN_MAP_ORIGINS`, `compose_group` / `containment_slabs`, the union `world_contract`. Pockets from a pool outside the window range arrive in P5.
**Columns kept current.** `M_SPACE` stamped on authored rows at creation (`systems/map/authored.py`); `H_SPACE` written by the portal command in the tick of the teleport; and a refresh of both columns from positions (float64 comparison against the interior rectangles, `spaces.refresh`) in a post-step hook `harness_spaces`, a genesis hook, and after a harness power. Measured cost of one refresh over both tensors in the golden world: 158 microseconds (design target was 100; not reduced). A move by any other path (direct write, god command) is seen by the systems one tick late.
**Queries.** The leak test (`tests/test_harness_spaces_leak.py`) showed that disjoint coordinates alone are not enough: a query radius above the 236 units between the village and an interior reaches across, and an area entity's tile mask can cover tiles of another space. Fixes, all keyed on the space of the query *point* so no caller changes: `map_geo.entities_in_radius` drops rows of other spaces (covers `nearby_entity_ids`, `nearest_geo_entity`, `best_resource_entity` and the direct users); `map_geo.register_entity` clips an area entity's tile mask to the tiles of its own space (covers `entity_at`, the animal eat path, and the tile-based human damage of fire and flood); `agent_radial_mask` / `entity_radial_ids` default `space` to the point's space; the escalation signals read threats of the resident's own space.
**Wire.** `space` on humans, animals and map entities (absent flag off), `space` on every `maps[]` entry, `spaces` in `/bootstrap` (authored worlds only). Positions stay in the layout frame; `spaces[].origin` converts to space-local.
**Save.** Flag off: schema 1, exactly as before. Flag on: schema 2 plus `world_format = {"format": 2, "spaces": [{space, map_id, origin}, ...]}` (no new engine fields: the registry is derived, so `ENGINE_FIELDS` is unchanged). `validate` refuses a save of the other format with `SaveFormatError` (texts in 1.4, verbatim) and a schema 2 save whose layout differs from the registered maps with a plain `ValueError`. Manifest generation entries carry `world_format` only when it is not 1; `list_saves` adds `compatible` when the flag is on or the save is format 2 (absent means compatible).
**Boot.** `EDEN_SPACES=1` without `EDEN_PERCEPTION_BOUNDED=1` raises `SpaceConfigError` from `engine_hooks.install` (at import of `map_test`).

## 2. Flags (all default off, read at call time through a function, the established pattern; remember the bare versus package import duplication, so each flag lives in one module and is read through `os.environ` at call time)

| Flag | Meaning | Requires |
| --- | --- | --- |
| `EDEN_PERCEPTION_BOUNDED` | `nearest_entity`, `_build_case` and the radial helpers honour `max_distance` and `space` (section 5) | none (usable alone) |
| `EDEN_SPACES` | `H_SPACE`/`M_SPACE` filters, per-space contracts and portals, no isolation rule, schema 2 | `EDEN_PERCEPTION_BOUNDED=1` (boot refuses otherwise) |
| `EDEN_WINDOW` | infinite overworld: chunks integrated into the tensors, re-base, void walls, dormant residents | `EDEN_SPACES=1` |
| `EDEN_CHUNK_ROUTES` | `/chunks` and `/chunk/{cx}/{cy}` served from a `ChunkService` | none (engine-independent) |

`EDEN_HARNESS_*` flags are unchanged. Combinations not listed are refused at boot with a message naming the missing flag.

## 3. D8 routes

**read:** `map_test.py` has `@app.get("/bootstrap")` and `/map_file/{map_id}` with `_etag_matches` and `ETag: "<sha256>"`, `Cache-Control: no-cache`, 304 on match; model routes are mounted with `app.include_router(build_model_router(lambda: engine))`.

- New file `api/chunk_routes.py` with `build_chunk_router(get_service)`; **legacy edit: one line** in `map_test.py` (`app.include_router(...)` guarded by the flag), plus moving `_etag_matches` into a shared helper is optional (the router can carry its own 5-line copy to avoid touching it).
- `GET /chunks?cx0=&cy0=&cx1=&cy1=` -> `{"world_seed", "generator_version", "chunk_tiles": 32, "units_per_tile": 8, "chunks": [{"chunk_id": "cx:cy", "revision": int, "sha256": str|null, "url": "/chunk/cx/cy", "state": "ready"|"pending"|"pinned_map", "pinned_map": id?}]}`. `chunk_id` uses the existing `ChunkCoord.chunk_id` form `x:y` (**read**, `systems/map/chunking.py`). Rectangle limit 15 x 15 chunks (400 `{"ok": false, "reason": "window_too_large"}` above). `sha256` is `null` while pending (computing 225 hashes on demand costs about 1 s at 4.5 ms per chunk, measured by 2f0fd3; the route must not do it inline). A request raises the priority of the chunks it lists (`ChunkService.request`).
- `GET /chunk/{cx}/{cy}` -> exact payload bytes (`Chunk.payload`, canonical JSON), `ETag: "<sha256>"`, 304 on `If-None-Match`, `Cache-Control: no-cache` (or `immutable` per revision when D5 deltas exist; decision open). Not ready: wait on the pool result up to 2 s (async, `asyncio.wrap_future`, never in the tick thread), else `503 {"ok": false, "reason": "chunk_pending"}` with `Retry-After: 1`. Integer overflow and absurd coordinates: coordinates are Python ints (generator accepts int64 and beyond, tested by 2f0fd3); the route bounds them to `abs <= 2**40` and answers 400 otherwise.
- **Revision.** Pristine chunk: `revision = 0` and the `sha256` of the generated bytes. After a D5 delta (a placed structure, a depleted node) the revision bumps and the served document is generated bytes + overlay, so the sha256 is always of the bytes served. D5 is not built; until then every revision is 0.
- Pinned chunks answer `state: "pinned_map"` with the authored map id; the client loads `/map_file/<id>` (already served).
- `/bootstrap` (flag `EDEN_WINDOW`): additive `world: {"infinite": true, "chunk_tiles": 32, "units_per_tile": 8, "generator_version": "...", "world_seed": "<string>", "window_origin": [ox, oy], "window_epoch": n}`; flag off the bootstrap key set is unchanged (a test pins the key set).
- **Removals / unload in the frame stream.** Chunk entity rows flow through the existing map export (`_export_map_entities` / `get_map_delta_for`, **read**) keyed by stable id, so an unload is an ordinary removal. **[GAP]** the chunk document also lists `entities` (aggregated features). To avoid drawing every feature twice the client should take tiles, props and the visual layers from `/chunk` and **entity state only from the map delta** (depletion lives only in the tensor). Needs the Godot owner's agreement.
- **Re-base on the wire.** Every frame / map payload carries `window_origin` (two ints) and `window_epoch`; positions are window-local floats. The client converts to absolute as `origin * 256 + local` in its own int64/float64. When the server re-bases, the epoch increments in the same payload in which all positions have shifted, so no frame mixes epochs. This is a client contract; proposal only.

## 4. D6 window, D2 coordinates, D7 dormancy

### 4.1 Coordinates and re-base
- Tensor positions are float32 offsets from the window's integer chunk origin (`SpaceFrame.origin`); absolute positions exist only as `AbsPos(chunk_x, chunk_y, x, y)` at the persistence and wire boundaries (built).
- **Re-base policy:** when the anchor (the possessed actor; with several, the first by id) is more than `REBASE_AT = 2` chunks from the origin chunk, move the origin to the anchor's chunk. The anchor's chunk index is then within +/-2 of the origin and rows inside the keep ring (radius 3) are within +/-5 chunks, so local coordinates stay in `[-1280, 1536)` (**arithmetic**). Magnitudes up to 1536 sit in the float32 binade `[1024, 2048)` (ulp 1.2e-4), the same worst case the Stage 1 frame already has between 1024 and 1200, so the tolerances in `spatial.py` / `pathing.py` (`EMBED_TOL = 1e-4`, snap margin 0.001) are no worse than in Stage 1 (they are already below one ulp there, D0 audit G-D0-2; fixing that is a separate item). `REBASE_AT = 1` would give `[-1024, 1280)` at twice the re-base rate. At walking speed (20 u/s) a re-base happens about every 25 s.
- A re-base adds a whole multiple of 256 to X/Y of all live rows (`SpaceFrame.rebase`, built): the only error is float32 re-quantisation at the new magnitude (at most half an ulp of the destination, 6.1e-5 in the top binade; **inference**). Trajectories are therefore **not bit-identical across re-bases**; tests compare positions with a tolerance of 1e-3 and discrete state (goals, hp, needs, anchors) exactly.
- **State that holds positions and must be shifted or made absolute** (found by reading; each needs a test): the two tensors (X/Y, CX/CY); `MAP_GEO` shapes (`cx`, `cy`, polygon points) and their tile masks / the tile index; `engine._actor_prev_positions`; resident records' `x`, `y` (`_snapshot_from_tensor` rewrites them from the tensor on sync, but **memory entries** `known_food_sources` etc. store `x`, `y` once at write time, `resident_store.remember_resource`, **read**: they go stale at the first re-base); task and commission targets (**not verified**, I have not read the task state fields); roster anchors (authored positions in the overworld frame; they are re-based as pinned-area content); pathing caches (rebuilt per contract revision); `_view_window_state`. Rule: anything that persists a position across a re-base stores an `AbsPos` (or a `(window_epoch, local)` pair that the loader converts), not a bare local pair.

### 4.2 Rings mapped to the engine (built by 2f0fd3: `rings.plan_stream`, radii 2/+2/+2 lead/+1 hysteresis; `blocked_by_void`)
| Ring (chunks) | Engine meaning |
| --- | --- |
| simulation, radius 2 (5 x 5) | rows in `m_tensor`, wall boxes in the contract, residents and animals run Tier 0; must be integrated (void wall until then) |
| unload hysteresis, radius 3 (7 x 7) | an integrated chunk stays until it leaves radius 3 |
| prefetch (+2, lead +2) | `ChunkService` cache only: bytes, no rows |
| render | client only; the server never sees it except as `window` requests to raise priority |

### 4.3 Capacity (measured on the real generator)
Script: seed 1008, village pinned, 961 chunks (31 x 31 around the origin), `generate_chunk(...).document`. Scratch only.
| Per chunk | mean | p95 | p99 | max |
| --- | --- | --- | --- | --- |
| feature entities (cap 16) | 5.10 | 11 | 12 | 15 |
| wall boxes | 4.71 | 18 | 27 | 34 |
| animal spawn slots (cap 4 entries) | 5.59 | - | - | 10 |

| Window | entities mean / p95 / max | wall boxes mean / p95 / max | animal slots mean / max |
| --- | --- | --- | --- |
| 5 x 5 (25 chunks) | 133 / 189 / 240 | 115 / 185 / 228 | 148 / 218 |
| 7 x 7 (49 chunks) | 261 / 356 / 418 | 228 / 338 / 415 | 289 / 418 |

Reading: `m_tensor` has 1024 rows; the authored world uses 27 at the start (golden `entities`). A 5 x 5 window with every animal slot materialised averages 133 + 148 = 281 rows (upper bound at the maxima 458, not simultaneous), a full 7 x 7 averages 550 (bound 836). Plus built structures, dropped items nobody tracks as rows, and nodes created at runtime. So:
- wall boxes **must not** be rows (they would add 115 to 415 rows); they live in a per-chunk box list consumed by the contract (4.5);
- animals are materialised only within the 3 x 3 chunks around an actor (lazily), the rest stay as spawn-table entries (they are exactly that in the chunk document anyway);
- a **row budget guard** `WINDOW_ROW_BUDGET = 800` (configurable): integration of a chunk is deferred while `rows_used + chunk_rows > budget`, nearest chunk first, and the deferral is counted in the metrics; the void wall holds the actor in, so nothing breaks, it only slows the world's growth. The budget is tested by a stress case with a seed chosen for density.
- `MAX_HUMANS = 100` stays the active-resident cap; D7 is how the population exceeds it.

### 4.4 Slot allocation and the slot-as-identity hazard
**read:** slot is identity: `MAP_GEO` and `TILE_TO_ENTITY` are keyed by `m_tensor` row, `engine._entity_uid_by_slot[slot]` maps the row to the public id, a freed row (`M_TYPE == 0`) is reused at once (`entity_born` takes the first free row), and **resident memory stores `entity_id` as the integer slot** (`ResidentAgentStore.remember_resource(human_id, bucket, entity_id: int, pos, tick)`; the call site in `human_runtime._build_case` passes `food_eid` straight from `nearest_entity`). After chunk unload, a remembered slot would silently name a different entity.
Design:
- A `SlotAllocator` (new, `harness/window.py`) hands out rows, keeps a per-chunk list of rows, and on unload releases them through **one function** `release_slots(engine, slots)` which: zeroes the row, `map_geo.unregister_entity(slot)`, clears `_entity_uid_by_slot[slot]`, removes the harness index entry, clears the `stock:<id>` marker in `_inventory_seeded_containers` (G-005 seeding marker), and increments `M_GEN` **of the freed row before zeroing the type** (the generation survives the release so a reused slot has a different generation).
- Chunk entities get ids `c<cx>_<cy>:<kind><n>` (worldgen spec; never `e_NNNNNN`), stored in `_entity_uid_by_slot` like any other string.
- Resident memory in window mode stores the **uid string and an `AbsPos`** (`{"uid", "chunk": [cx, cy], "x", "y"}`), with the old `entity_id` slot field kept for flag-off entries. Legacy edit: `resident_store.remember_resource` plus its readers (**not yet enumerated**: a grep of readers of `known_food_sources` / `known_water_sources` is the first task of P5). The `entity_id` slot is also what `_build_case` feeds the Tier 1 case, so the case builder gets the uid too.
- Other holders of a slot across ticks that I have **not verified** and that P5 must audit: god-power selectors, the world-agent selector resolvers (two copies, `world_runtime.py` and `execution_selectors.py`), `_prev_entity_mask`, task/commission targets, `_incarnated_human_by_controller`, structures in `systems/construction`.
- Allocation is deterministic: lowest free row first, chunks integrated in plan order (nearest first, ties by `(cx, cy)`), entities in document order.

### 4.5 Walls, void barrier, contract
- Chunk walls (already clipped boxes, same keys as `spatial.wall_boxes`) go into a per-chunk list in the window manager, translated to local coordinates on integration and on re-base. `world_contract(engine, space)` composes: tensor `M_WALL` rows of the space + the chunk boxes of the integrated chunks + void boxes.
- **Void boxes:** for every integrated chunk edge whose neighbour is not integrated, one wall box along that edge (thickness 2 units outside, so the existing `slide` handles it with no new code). Recomputed only when the integrated set changes (the same moment as integration or unload). This implements "never walk into the void" without touching `slide`.
- **Revision hash:** `world_contract` currently rebuilds the box list and a sha256 every tick (**read**; measured 0.43 ms per call, p99 0.77, in `1008_tick_profile.md`); with 115 to 415 extra boxes that grows. Compose the revision from `(sorted chunk revisions, tensor wall hash, void hash)` and cache it until the integrated set or a wall row changes. Box count to the actors' `slide` is an O(boxes) Python loop (**read**, D0 audit): measure before adding a broadphase (P4 gate); if over budget, pass each actor only the boxes of its chunk and the 8 neighbours.
- Pathing (D10): the lattice is built from the contract bounds with `MAX_CELLS = 1_500_000`; in window mode the bounds are the bounding box of the integrated chunks (at most 7 x 7 chunks = 224 x 224 tiles), within the limit. Cross-chunk journeys beyond the window are not pathed: the actor is dormant on those (4.6).

### 4.6 `map_geo` and the tile index
**read:** one process-wide `MAP_GEO` / `TILE_TO_ENTITY` with a full-frame `GRID_H x GRID_W` bool mask per entity (16 800 bytes each, 0.18 to 0.43 ms to build), position -> tile index clamps to the frame, `entities_in_radius` iterates every entity. Window mode:
- `map_geo` gains `configure_window(tiles_w, tiles_h, origin_tile)` (default = legacy constants, bit-identical); `_px_to_tile_idx` uses module variables instead of the imported `GRID_W/H` constants; masks are computed over the shape's **bounding box only** and stored with their box, not as full-frame tensors. A 7 x 7 window is 224 x 224 tiles = 50 176 indices, so masks must be sparse (400 rows x 50 KB would be 20 MB).
- Re-base shifts `cx`, `cy` of every shape and the tile origin; `TILE_TO_ENTITY` keys are window-grid indices, so they are rebuilt from the shapes on re-base (O(rows), once per ~25 s).
- Size: `map_geo.py` about 60 changed lines, `world_snapshot.py` geometry section (save without masks, rebuild from shapes on restore) about 20 (inference). The pickled geometry shrinks from O(entities x frame) to O(entities).

### 4.7 Integration step (one hook, no change to `Engine.step`)
**As built:** a step hook `harness_window` (`engine_hooks.window_hook`, registered with `DISPATCH.register_step_hook`). Step hooks have no priority: `Engine.step` runs them once per tick after the reconcile (`map_test.py` `DISPATCH.run_step_hooks`), so the "priority 81, before resource regrow" placement below was not used. Original design text:
A `window_integrate` step hook registered through the existing hook mechanism (**read:** `engine_hooks`, `simulation.dispatch.DISPATCH`) at priority 81, before resource regrow (82), the water cycle (83) and the dispatch (90). Per tick: (1) every `PLAN_EVERY_TICKS` (4) or when the anchor's chunk or heading octant changes, call `plan_stream(...)` (**measured by 2f0fd3:** planning every tick costs p99 3.1 ms, so plan on change); (2) `pump()` the service; (3) integrate at most **one** chunk whose bytes are ready (the rows are written with one vectorised assignment; geo, walls, index, ids), or unload at most one; (4) re-base if due. Integration cost target below 2 ms per tick (**design target, not measured**; measuring it is the Gate E of P5).
Replay and determinism: the tick at which a chunk becomes available depends on worker timing, so live runs are not reproducible by tick. Rule: every integration, unload and re-base is appended to the event ledger as `window_integrate(chunk, tick)`, and a replay feeds these instead of asking the service. Tests use an inline service (`workers=0`, a chunk is ready the moment it is requested) so integration ticks are a pure function of the plan.

### 4.8 D7 dormant residents
**read:** `capture` already saves every resident record, including offscreen and dead ones (`resident_store.root_dir/*.json` + `_cache`); `sync_live_population(ids_by_slot, h_mask, ...)` iterates only live `h_mask` slots; the records carry `x`, `y`, `slot`.
- A dormant resident is a record only (no `h_tensor` row, `_human_uid_by_slot` entry cleared). The record gains `space`, `abs: {chunk: [cx, cy], x, y}`, `dormant: true`, `schedule_cursor`. `harness.world.World.residents` already holds records by stable id, which is the harness view.
- Activation rule: a resident is active iff its chunk is in the simulation ring of an anchor, or it is in an interior space that has a possessed actor or an active resident. Going dormant: write back (`abs`), release the `h_tensor` row; waking: take a free row, write the position from `abs` (placed along the schedule's expected route, section D7 of the plan).
- Dormant step: once per game minute (1200 ticks at 20 Hz is **inference**: check `TICK_RATE_HZ` and the game-minute constant), vectorised over the dormant set; needs advance by the same per-minute deltas as active residents, the schedule cursor moves them between their anchors by the shortest legal route length / speed, no per-tick movement. The **same rules** requirement is the risk: the Tier 0 needs system (`instinct_needs`, S3 pilot) must expose a "step n ticks" form; the S3 pilot `harness/needs.py` is a per-tick instinct (`instinct_needs(ctx, h_tensor)` wrapping the legacy hunger/thirst rates, **read**), not a function of elapsed time, so the dormant step needs a new `advance(n_ticks)` form of the same rates (a loop of `n` vectorised steps is exact, a closed form is faster but must match to float tolerance), and an equivalence test (active 1200 ticks versus one dormant minute, no events) pins it.
- Dormant residents beyond `MAX_HUMANS` need records beyond the 100-slot arrays; the arrays `_human_uid_by_slot`, `_pending_*_by_slot` are sized to 100 and stay so (dormant residents are not in them).
- **Not verified:** how far Tier 1 per-resident state (task, plan, goal, commission) survives leaving and re-entering the tensor; it lives in the resident record (so should persist), but the runtimes (`human_agent` and friends) keep per-slot dicts that must be dropped on release. P6 starts with a read-only audit of `vars(human_agent)`.

### 4.9 Harness mapping (what exists, what is added)
| Engine thing | Harness thing | Change |
| --- | --- | --- |
| `h_tensor` / `m_tensor` | `Table` over the tensor, `ids` from `_*_uid_by_slot` | adapter `ENTITY_COLUMNS` / `HUMAN_COLUMNS` gain `space`, `gen` |
| window origin | `World.frame` (`SpaceFrame`, origin, rebase) | `World.frames[space]`; adapter keeps `frame.origin` in sync with `engine._window.origin` |
| `MAP_GEO` / tile index | `SpatialIndex` (per space, per chunk buckets) | the legacy index stays for legacy code; new code uses the harness index; both rebuilt on re-base |
| slot allocation | `Table.free_slot` | `SlotAllocator` + `release_slots` (above) |
| dormant resident | `World.residents[id]` | `Resident.abs`, `dormant` flag; `WindowManager.wake/sleep` |
| chunk bytes | `ChunkService` (2f0fd3) | `WindowManager` wraps it; the engine side never imports `systems/worldgen` directly except through this adapter |
Effect system: spawn / despawn effects for chunk entities are issued by the window manager through `EffectApplier` where possible (`Spawn` with a given id), so the Table, the event ledger and the index stay consistent; the legacy mirror (`map_geo`, `_entity_uid_by_slot`) is updated by the adapter's hook, as for the G-005 nodes.

## 5. Perception bounding (authorised, part of the flag set)
`EDEN_PERCEPTION_BOUNDED` (default off). `runtime/common.py:nearest_entity(..., max_distance=None, space=None, entity_spaces=None)` and `_build_case` pass the resident's perception radius and `H_SPACE`. Evidence and reasoning in `1008_frontier_freeze_diff.md` (reader located, 8886996). Included here because the window and the spaces both make the unbounded behaviour wrong (any loaded row, any space). Default off keeps the goldens bit-identical.

## 6. Legacy files that must change (each needs authorisation; sizes are inferences)
| File | Change | Size | Phase | Flag-off effect |
| --- | --- | --- | --- | --- |
| `genesis_config.py` | `H_SPACE = 29`, `M_SPACE = 31`, `M_GEN = 30`, flag-free constants | 4 lines | P2 | none |
| `harness/numerics.py` (mine) | `pairwise_distances(..., space_a, space_b)` | 15 lines | P2 | none (defaults) |
| 10 `pairwise_distances` call sites in 5 files | pass the two space slices | 1 line each | P2 | none (when the flag is off the arguments are `None`) |
| `runtime/common.py`, `runtime/human_runtime.py` | bounded `nearest_entity`, `_build_case` | 30 lines | P2 (authorised) | none |
| `systems/perception/queries.py` | space argument on the radial helpers | 15 lines | P2 | none |
| `map_contract.py`, `systems/movement/spatial.py` | per-space contract, no isolation rule under the flag | 60 lines | P3 | none |
| `simulation/portal_commands.py` | `(space, x, y)` target, contract of the target space | 25 lines | P3 | none |
| `systems/roster/{motion,driver,apply}.py` | group by space for contract lookup | 30 lines | P3 | none |
| `persistence/world_snapshot.py`, `checkpoints.py`, `map_guard.py` | schema 2, refusals, `compatible` | 70 lines | P3 | none (schema 1 written) |
| `map_geo.py` | `configure_window`, sparse masks, re-base | 60 lines | P4 | none |
| `map_test.py` | register hook, router include, bootstrap `world` block, `window_origin` in payloads | 30 lines | P1, P5 | none |
| `runtime/resident_store.py` | `remember_resource` with uid + `AbsPos`, `dormant` records | 40 lines | P5, P6 | none |
Everything else (window manager, registry, allocator, dormant stepper, routes) is new files under `harness/` and `api/`. `systems/actions/` (2f0fd3) is not touched.

## 7. Proof plan
**Standing gate (every phase, every commit that touches a legacy file):** `tools/golden_trace.py --check --strict` default and `--resources` on a `git archive` extract, both bit-identical; the suites of every touched module; `tests/test_harness_golden*.py`.

| Phase | Additional proof |
| --- | --- |
| P0 | unit tests on a synthetic `World`: window manager, allocator (load/unload cycles leave tensors, index and id lists identical to the start), rebase round trip within tolerance, row-budget deferral, replay of a recorded integration log |
| P1 | route tests with an inline service: ETag/304, `/chunks` descriptor shape and window limit, pending state, 400 on huge coordinates, flag-off 404; byte equality with `ChunkService` payload; cross-check sha256 against 2f0fd3's golden hashes |
| P2 | per call site: equal-space results unchanged to the bit, cross-space never inside a radius; the unbounded/bounded equivalence tests ordered by c3; goldens identical |
| P3 | a **flag-on spaces golden** `tests/golden/trace_seed1008_spaces.json` (new `--spaces` option in `golden_trace.py`, like `--resources`), plus a test that it differs from the default golden only by the documented rows (interior rows: `cx`, `cy` sums, `M_SPACE`), all resident fields except positions unchanged if the residents never enter an interior; save/restore round trip with flag on; the two refusal messages verbatim; portal in/out across spaces with contracts of the target space |
| P4 | map_geo window mode on the **finite** world (window = the whole frame): **bit-identical to the default golden** (a stronger proof than any new golden); contract box count and `slide` cost measured against the tick profile |
| P5 | **flag-on window trace** `tests/golden/trace_window_walk.json`: scripted anchor walking 5000 units along a fixed route over seed 1008 with an inline service; checkpoints record origin, loaded chunk set hash, rows used, the multiset of entity ids with absolute positions (so independent of re-base), void hits; run twice (determinism) and with the start origin shifted by 100 chunks (origin invariance within 1e-3 and exact discrete state); save at a re-base boundary, restore, continue: identical to the uninterrupted run; unload/reload keeps an edit; Gate E metrics (tick p99 within 2 ms of the no-streaming baseline while walking, void hits 0) under a MEASURE lock |
| P6 | active versus dormant equivalence (no events), 100 residents over 200 chunks within the tick budget, wake placement, resident memory with uid survives a re-base and an unload |
Determinism of live (async) runs is not claimed; the integration log makes them replayable (4.7).

## 8. Risks (ordered)
1. **Slot reuse after unload** (4.4): silent wrong-entity references. Mitigation: one release function, `M_GEN`, uid in memory, an audit task listing every slot holder before P5 starts.
2. **Re-base correctness**: any position-bearing state missed shows as a one-time teleport every 25 s of walking. Mitigation: the list in 4.1 turned into a test that scans the engine's `vars()` for float pairs and for tensors with position columns; origin invariance test.
3. **Dormant equivalence**: the coarse step drifting from the Tier 0 rules. Mitigation: the equivalence test; dormant stepping reuses the same function with `n`.
4. **Row pressure**: dense seeds near 1024 rows. Mitigation: budget guard, lazy animals, merge features (generator cap), metric.
5. **Per-space contract in roster/motion**: a resident in an interior using the overworld contract would walk through walls. Mitigation: space is part of every contract lookup; a test per mover (anchor mover, manual player, portal).
6. **Client contract** (re-base epoch, entity source, `space` key): not mine; needs the Godot owner.
7. **Cost of `world_contract` revision and `slide` with 100 to 400 more boxes**: measured only in the tick profile for the Stage 1 village. Gate in P4.

## 9. Phases (build order; risk rank in brackets, 1 = lowest)
| Phase | Content | Owner | Needs from orchestrator |
| --- | --- | --- | --- |
| P0 [1] | `harness/spaces.py`, `harness/window.py` (manager, allocator, rebase, budget, integration log, `release_slots` against a synthetic World), tests | Harness | nothing (new files, no legacy edits) |
| P1 [1] | `api/chunk_routes.py`, `EDEN_CHUNK_ROUTES`, one include line in `map_test.py`, tests; unblocks the Godot chunk loader | Harness (needs a go-ahead for the `map_test.py` line) | OK for 1 line; Model plane owns `ChunkService` |
| P2 [2] | columns, `pairwise_distances` space args + 10 call sites, bounded `nearest_entity` / `_build_case` (authorised), radial helpers | Harness | OK per file list in section 6 |
| P3 [4] | `EDEN_SPACES`: registry, per-space contract, portals, roster grouping, schema 2, refusals, `--spaces` golden | Harness | OK for each file in section 6; the exact refusal messages (1.4) |
| P4 [3] | `map_geo` window mode (sparse masks, re-base), contract revision cache and broadphase if the measurement says so; finite-world bit-identical proof | Harness | OK for `map_geo.py` |
| P5 [5] | `EDEN_WINDOW`: integrate/unload hook, void boxes, slot allocator in the engine, re-base, resident memory with uid/AbsPos, window trace | Harness (+ Model plane for the memory consumers) | OK for the hook and `resident_store.py`; audit result of the slot holders |
| P6 [5] | dormancy and wake, `vars(human_agent)` audit, 100-resident stress | Harness + Model plane (Tier 1 state) | OK |
| P7 [4] | windowed pathing waypoints, long journeys | Model plane | later |
The order is by dependency and by what it unblocks; the risk rank says where to expect the surprises (P5 and P6 together contain the three highest risks above).

## 10. Decisions wanted from the orchestrator
1. Column numbers `H_SPACE = 29`, `M_SPACE = 31`, `M_GEN = 30` (and species attrs from 17 to 29 only).
2. Flag-based schema versioning (schema 1 written whenever `EDEN_SPACES` is off) and the wording of the two refusals in 1.4; `compatible` in the save list.
3. `REBASE_AT = 2` chunks and `WINDOW_ROW_BUDGET = 800` as defaults.
4. Client contract items: entity state only from the map delta, `window_origin` + `window_epoch` in every payload, `space` key per entity; who asks the Godot owner.
5. P1 first (routes before engine work) so the client can start.
6. Authorisation per phase for the legacy edits in section 6 (P2 is already authorised for `runtime/common.py` and `runtime/human_runtime.py`).
