# 1008 D0 audit: what the tensor engine assumes about space (read-only)

Written 2026-10-08 by the Harness worker for plan item WS-D / D0 (`../designs/implementation.md`). **Nothing in the repo code was changed.** Method: `grep` of every name below over `at_the_beginning/`, each hit mapped to its enclosing function with `ast` (script in the session scratchpad), plus four throw-away measurement scripts (scratchpad, not committed) run with the repo `.venv` (torch 2.11.0+cpu, Windows). Everything marked **measured** was run; everything marked **reading** is from reading code only; **inference** is reasoning.

## 0. Verdict (details and evidence in sections 1 to 6)

1. **The infinite map is invasive but not a rewrite.** The hard-coded frame appears in 20 files / 216 lines, but 90 percent are the same three idioms: clamp to `[0, MAP_WIDTH] x [0, MAP_HEIGHT]` (about 35 sites), "map centre" defaults (about 30 sites), and fixed-size `MAX_ENTITIES` scans (about 25 sites). Each is a mechanical change once there is **one** `World`/frame object that answers "bounds", "centre", "is this slot live" instead of module constants. The real design work is in four places: `map_geo.py` (global tile grid), `systems/movement/spatial.py` + `map_contract.py` (bounds, walls, per-tick contract), the slot-as-identity convention, and persistence (`world_snapshot.py`).
2. **Recommended path: do not take the "larger fixed frame" fallback; build chunked space behind the World facade, in two steps.** Step A (cheap, safe): replace the constants by `World.bounds()` / `World.centre()` accessors so the frame can be any size while still finite; this alone removes the 30 "centre" and 35 "clamp" sites from the problem. Step B: make the spatial index (`map_geo`) per-chunk and windowed. The fallback is only worth it if Step B slips, because a larger frame does not remove `MAX_ENTITIES = 1024`, the per-tick O(N) scans, or the float32 problems (section 5), and it still needs streaming to be cheap.
3. **Two things the plan did not know (these change the plan):**
   - **G-D0-1 (measured, correctness today): `torch.cdist` on float32 positions is inexact when either side has more than 25 rows.** PyTorch switches to a matrix-multiply formulation above 25 rows; at coordinates near 1000 the error is up to 0.78 units (section 5.2). That is already inside the current 1200 x 900 frame for any entity query (`entity_radial_ids`, `nearest_geo_entity`, hazards: up to 1024 rows) and for any human proximity pass with 26 or more residents (the 100-resident target). With larger coordinates the error grows roughly linearly (6 units at 10,000, 60 units at 100,000, 500 units at 1,000,000). The fix is trivial (`compute_mode="donot_use_mm_for_euclid_dist"` or window-relative coordinates) but must be done before chunked space or the 100-resident target.
   - **G-D0-2 (reading, structural): spatial position is global float32 in `h_tensor`/`m_tensor`, and several tolerances are below float32 resolution beyond small coordinates** (section 5.1): the wall-embed tolerance `EMBED_TOL = 1e-4` is below one float32 ulp for `|x| >= 1024`, and the 0.001 snap margin for `|x| >= 16384`. The plan's "fine to about +/-100k" (D2) is too optimistic for the collision code as written; a **window-relative origin** (positions in the tensor are relative to a per-window origin kept as float64/int chunk coordinates) is the robust fix and is cheap if done through the World facade.
4. **D1 (interiors as spaces) needs less than expected**: columns exist (`h_tensor` 25 to 31, `m_tensor` 13 to 31 reserved, `genesis_config.py:105,138`) but nothing filters on space; every perception function takes positions only. The 220-unit isolation rule lives in one function (`map_contract.validate_placement`) and `EDEN_MAP_ORIGINS` in three tools, so retiring it is local. The cost is that **all** proximity code (11 `cdist` sites plus `entity_radial_ids`, `find_entities_in_radius`, combat, trade, talk) must gain an equal-space mask; that is the invasive part of D1, not the placement code.
5. **Hard caps already equal the plan's targets**: `MAX_HUMANS = 100` is exactly the "100 residents" target, and `MAX_ENTITIES = 1024` is the whole window budget (D11 estimates about 400 rows for the simulation ring plus animals, structures and authored areas). Both need to become dynamic or be raised, and the 100-resident target cannot be reached by dormancy alone (dormant residents still need records; they would have to live outside `h_tensor`).

## 1. The constants and the module global (call-site table)

Definitions (all in `at_the_beginning/genesis_config.py`): `MAP_WIDTH = 1200`, `MAP_HEIGHT = 900` (36-37), `TILE_SIZE = 8` (38), `GRID_W = 150`, `GRID_H = 112` (39-40; note 900/8 = 112.5 truncated, so the last half tile row is outside the grid), `MAX_BG_TILES = 16800` (41, only imported by `map_geo.py:37`, never used otherwise), `MAX_ENTITIES = 1024` (46), `MAX_HUMANS = 100` (47). `HUMAN_TENSOR_COLS`/`MAP_TENSOR_COLS = 32`.

### 1.1 `map_geo.py` (the spatial index): the central problem
`map_geo` keeps three module-level globals: `MAP_GEO` (entity row index -> shape and a **full-frame** `tile_mask` bool tensor of `GRID_H x GRID_W` = 16,800 bytes each), `TILE_TO_ENTITY` (flat tile index -> entity row index, last writer wins), `geo_version`.

| Where | What it assumes | Needed for chunked / unbounded space | Needed for per-space interiors |
| --- | --- | --- | --- |
| `map_geo.py:71-77` `_px_to_tile_idx` | clamps the pixel to `[0, GRID-1]`, so a position outside the frame silently maps to the edge tile (entity lookup returns the edge entity, not "none") | key by `(space, tile_x, tile_y)` integers, no clamp; outside any loaded chunk return -1 | space id in the key |
| `map_geo.py:80-137` `_compute_circle_mask`, `_compute_polygon_mask`, `_add_to_/_remove_from_tile_lookup` | dense `GRID_H x GRID_W` mask per entity; `register_entity` builds a meshgrid over the whole frame (measured **0.18 to 0.43 ms** per call, r = 10 to 300 units, plus a Python loop over every covered tile: 4,406 tiles at r = 300) | compute only the tiles the shape covers (bounding box in tile coordinates), store sparse per-chunk; cost becomes proportional to shape size, independent of world size | none |
| `map_geo.py:47,59` globals | one process-wide index: two worlds in one process are impossible; `map_test.py:499-501` clears them on every `reset_world` | instance on the `World` object (per-chunk dicts) | one index per space |
| `map_geo.py:229-253` `entities_in_radius` | iterates all of `MAP_GEO` in Python and reads `m_tensor` per entity (O(entities), used by `perception/queries.py:80`, `systems/map/create.py:185`, 4 tools) | candidate lookup through the chunk and its 8 neighbours | equal-space filter |
| `map_geo.py:256-273` `background_tile_types`, `276-293` `get_geo_json` | whole-frame grid and whole `MAP_GEO` export (the wire format of the legacy `/get_map`) | replace by the chunk protocol (D8); legacy path stays for finite worlds | per-space export |
| `map_geo.py:238` `from genesis_config import ... MAX_ENTITIES` | skips `eid >= MAX_ENTITIES` | dynamic capacity | |
| `map_geo.py:37` bare `from genesis_config import` | import by bare name, so `map_geo` only works with `at_the_beginning/` on `sys.path` | see 1.5 | |

Users of the map_geo globals (outside `map_geo.py`): `instincts_and_tools.py` 377, 382, 410, 508-509, 1029, 1252, 1269, 1274, 1771, 2416, 2571, 2601, 2839, 2864, 2887, 3083, 3115; `map_test.py` 499-501, 4535, 4568, 4766-4833, 5156, 5160, 5316 (`GameSessions(engine, map_geo, ...)`); `persistence/world_snapshot.py` 33-34, 102-106, 121; `runtime/execution_selectors.py` 99; `systems/construction/repair.py` 152-153; `systems/map/authored.py` 55; `systems/map/create.py` 185; `systems/nature/disasters.py` 137, 208-248; `systems/nature/hazards.py` 104-168; `systems/perception/queries.py` 69, 80; `systems/survival/navigation.py` 100. That is 12 files and 48 references to `MAP_GEO` alone.

### 1.2 Clamps, centres and bounds (`MAP_WIDTH` / `MAP_HEIGHT`)
All of these assume a closed rectangle `[0, W] x [0, H]` anchored at the origin. For chunked space each must call `world.clamp(x, y)` (no-op or window-limited) and `world.centre()` (the player's or camera's position).

| File:line (function) | Assumption | Change |
| --- | --- | --- |
| `instincts_and_tools.py:333-334` (`_clamp_point`) | clamp for tools placing things | `world.clamp` |
| `instincts_and_tools.py:932-933` (`instinct_flee`), `1521-1522` (`instinct_move`), `2789-2790` (`tool_migration`) | human step clamped to the frame (so humans cannot leave it by moving) | clamp to loaded window or none; `instinct_move` is the unified-mover target anyway |
| `instincts_and_tools.py:1742-1743, 1753-1754` (`animal_instinct_move`) | animals clamped to the frame | window clamp; the animals that leave the window go dormant (D7) |
| `systems/nature/disasters.py:167-168` (`apply_storm`), `systems/social/mating.py:109-110` (`resolve_human_reproduction`) | child/storm positions clamped | `world.clamp` |
| `map_test.py:1554-1555` (`_clamp_world_point`), `2588-2589` (`_attempt_task_mating`), `3354-3355` (`_move_human_toward_point`), `5007-5008` (`_player_incarnation_spawn_point`), `1295-1296` (`_spawn_starter_storage_case`) | spawn / move / placement clamps | `world.clamp` |
| `runtime/common.py:86-87, 96-97` (`move_toward`, `move_away`) | LLM-tool movement clamps | `world.clamp` |
| `systems/movement/spatial.py:49` (`_compose`) | `bounds = [0, 0, MAP_WIDTH, MAP_HEIGHT]` for legacy maps; authored maps use the union of placed rectangles | bounds come from the World; unbounded space = no bounds, only walls |
| `systems/movement/map_contract.py:180-181` (`validate_placement`) | placed maps must fit inside the 1200 x 900 frame | goes away with D1 (separate spaces) |
| `systems/map/expand.py:44,48,72,76,111,115,173-178,190,194` and `chunk_generation.py:117-132` | **the frontier expander** (`instinct_frontier_expand`, registry priority 84): triggers when a human is within a margin of the frame edge and grows features into a band at the edge **inside the same frame** | retire (decision D-005 keeps it frozen until Gate D); its `random.uniform` calls (expand.py 173-178) are also global-RNG users |
| `systems/map/create.py:455-456, 535-536` and `428` | default search centre = frame centre; `create.py:428` slices `m_tensor[:MAX_ENTITIES]` | `world.centre()`; dynamic capacity |
| `initial_map_design.py:155,213,265,315,373,419,472` | the 7 built-in generators lay out on `W, H = MAP_WIDTH, MAP_HEIGHT` | stay as finite legacy generators; the new chunk generator replaces them for infinite worlds |
| `runtime/world_runtime.py:448-469` (`_region_center`), `833, 872` (selector `center` default), `runtime/execution_selectors.py:26, 667, 719` | world agent's region names (north/south/east/west quarter) and default centres are fractions of the frame | "region" must become relative to the player/window or an explicit chunk range; note `world_runtime.py` and `execution_selectors.py` contain **two copies** of the selector resolver (`_resolve_human_selector`, `_resolve_entity_selector`), both need the change (or be unified, which WS-H selectors do) |
| `map_test.py:875-876, 5982-5983` (`get_human_view_window`, `view_window`), `5969-5970` (`inventory_spawn_storage_case`), `5226-5227` (`create_genesis`) | default view/spawn centre = frame centre | `world.centre()` |
| `map_test.py:975-976, 4580-4581, 4638-4639, 4679-4680` | `width`/`height` exported to the client in `/bootstrap`, map payloads (`tile_size`: 4582, 4640, 4681) | `world.infinite: true`, `chunk_tiles`, `units_per_tile` (D8); legacy finite worlds keep the old keys |
| `map_test.py:3804-3805` (`_execute_resident_task_step`) | passes `map_width/map_height` to `plan_path`/roster motion | pass the contract bounds (already bound to the map) |

Not frame-dependent but in the same family: `systems/movement/pathing.py` rasterises a lattice over the contract bounds (`MAX_CELLS = 1_500_000`, `DEFAULT_MAX_EXPANSIONS = 250_000`); its docstring says it is meant for "bounds in the hundreds of units". With no bounds it cannot build a global lattice: it needs a **windowed** lattice (the plan's D10 already says "within a chunk window use the existing grid pathing"; this audit confirms it is mandatory, not optional).

### 1.3 Capacity assumptions (`MAX_ENTITIES`, `MAX_HUMANS`, slot indices)
| File:line | What | Change |
| --- | --- | --- |
| `map_test.py:383-384` (`WorldState`) | `h_tensor (100, 32)`, `m_tensor (1024, 32)`, allocated once, `device` cuda-if-available | capacity becomes a World parameter; grow-on-demand or fixed larger window |
| `map_test.py:449-450, 472-474, 4137` | per-slot Python lists and masks sized to the caps | derived from World capacity |
| `instincts_and_tools.py:958` (`instinct_born`) `pop_count_ref[0] >= MAX_HUMANS`; `1010-1012` (`entity_born`): first free row by `torch.where(M_TYPE == 0)[0]` | slot allocation = first free row | allocator object with generation counters (below) |
| `instincts_and_tools.py:2543, 2562, 2577` (`tool_drought`, `tool_regrow_forest`, `tool_seed_world`) and `systems/nature/ecology.py:85,105,151`, `hazards.py:76,145`, `perception/queries.py:108-109`, `survival/shelter.py:62` | `n = MAX_ENTITIES` / `m_tensor[:MAX_ENTITIES]` full scans | operate on a live-slot index list (`live = M_TYPE > 0` nonzero) or the chunk's slots |
| `systems/map/chunk_generation.py:155`, `systems/map/expand.py:182-186` | scans all rows | same |
| `map_test.py:4589-4590, 4614, 4651, 4743, 5473-5475` | `agent_cap`, `entity_cap`, `cap` sent to clients | dynamic |

**Slot is identity (reading, 1,268 lines mention `slot` in 69 files).** `MAP_GEO` is keyed by the `m_tensor` row index; `TILE_TO_ENTITY` stores row indices; `_human_uid_by_slot` (77 lines, 14 files) and `_entity_uid_by_slot` (36 lines, 11 files) map row to a public id, and a slot is reused as soon as its row is freed (`M_TYPE == 0`). Today that is manageable because rows change rarely. With chunk load/unload, a row will be reused for a different entity, so any structure that stores a row index across ticks (`MAP_GEO`, `TILE_TO_ENTITY`, the world-snapshot `geometry`, god-power selectors, memory/commission records that cache slots) can silently refer to the wrong entity. Required: persistent entity ids as the key in the index and in saves, slot only as a transient cache invalidated by a per-slot generation counter. This is the single biggest source of subtle bugs for D6.

Reserved columns: `h_tensor` 25-31 (7), `m_tensor` 13-31 (19) are free, so `H_SPACE`/`M_SPACE` and a `generation` column fit without changing tensor shape. **Float32 caveat:** a space id stored as float32 is exact to 2^24 = 16.7M, fine.

### 1.4 Movement, collision and the per-tick contract (reading, plus the 1006 audit)
| Where | Assumption | Change |
| --- | --- | --- |
| `spatial.py:9-22` `wall_boxes` | every live `M_WALL` row in the whole tensor becomes a box, **every call** | windowed: only walls in loaded chunks (per-chunk box list, cached) |
| `spatial.py:82-95` `world_contract`, called in `Engine.step` once per tick (`map_test.py:4850`) and from `map_test.py` (1008, 4852, 5379), `simulation/portal_commands.py:35`, `systems/roster/{apply,driver,motion}.py` and `spatial.py` itself | builds the full box list and its sha256 revision **every tick** (O(walls) + JSON dump) | revision per chunk, composed by hash of chunk revisions; contract holds only the window. Cost to be quantified in `./tick_profile.md` (R1-H2) |
| `spatial.py:128-190` `slide`, `snap_to_standable`, `is_standable_point` | O(boxes) Python loops; bounds clamp | broadphase by chunk/cell; bounds optional |
| `map_contract.py` (`compose_group`, `containment_slabs`) | maps placed in one frame; blocking slabs fill the gap so actors can't leave a map | disappears with D1 spaces (each space has its own bounds); slabs only exist because of the shared frame |
| `map_contract.py:28 ISOLATION_DISTANCE = 220` and `EDEN_MAP_ORIGINS` (`tools/soak_headless.py:39`, `restart_probe.py:39`, `smoke_common.py:6`, `tests/authored_village.py:10`, `systems/movement/map_contract.py:17,29`) | interiors must be 220+ units apart so residents "cannot perceive" across maps | replaced by the space-equality filter |
| `combat/resolver.py:99,128` (`wall_boxes(m_tensor)`, `segment_blocked`) | reads tensor walls, uses no contract radius | uses the windowed box source |
| `animal_instinct_move` (`instincts_and_tools.py:1742`) | animals are clamped, **not slid**, so they walk through walls (1006 audit, kept true) | not a D0 issue; note for WS-H unified mover |

### 1.5 Hazard: two import identities for the same module (measured)
`map_geo` is imported **by bare name** (`import map_geo`, with `at_the_beginning/` on `sys.path`) in `map_test.py:145`, `instincts_and_tools.py:41`, `systems/nature/*`, and **by package name** as the `except ImportError` fallback in `systems/*` (for example `systems/perception/queries.py:8,33`, `systems/survival/navigation.py:6,43`, `systems/construction/repair.py:8,35`, `systems/map/create.py:11,14`). **Measured:** `map_geo` and `at_the_beginning.map_geo` are two distinct module objects with separate `MAP_GEO` / `TILE_TO_ENTITY` globals (likewise `genesis_config`). Today every process puts `at_the_beginning/` first on `sys.path`, so the bare import always wins and the fallback never executes; but any code path that imports `at_the_beginning.<x>` first, or a launcher that changes `sys.path`, would silently create a second, empty spatial index. This is exactly why the World facade must own the index (an instance, not a module global), and it is the strongest argument for the packaging cleanup (D-003) coming right after characterization.

## 2. Tensor-index and layout assumptions

- `h_tensor` is `(100, 32)` float32, `m_tensor` `(1024, 32)` float32 (`WorldState`); positions are float32 in columns `X, Y` / `CX, CY` (`genesis_config.py:75-76, 116-117`). Everything numeric (HP, hunger, ids of types, flags, the 64-bit `ACQUIRED_INSTINCT_MASK` stored **as a float32 column**, `genesis_config.py:94-99`) shares float32. **Measured (a latent bug independent of the map):** `ACQUIRED_INSTINCT_MASK` is stored in a float32 column and updated as `(current.long() | (1 << bit)).float()` (`instincts_and_tools.py` 2735-2736, 2741-2742, 2750-2751, 2808-2809, read at 3269). Granting bit 3, then bit 30, then bit 40 leaves bits `[30, 40]`: **bit 3 is silently lost** once a higher bit is set, because float32 keeps only 24 significant bits. Only grants within one 24-bit window are safe, so the effective capacity is far below the documented 64 (plan finding 14). The harness should store grants as a set of ids (as the plan's triage already proposes) and the mask must not be relied on above bit 23 until then.
- Types are `M_TYPE` integers in a float column; `0` means "free slot". `ANIMAL_TYPES = range(40, 80)`, `STRUCTURE_TYPES = range(20, 40)`, `NATURAL_TYPES = range(1, 20)`; `80+` unassigned.
- `H_SPACE`/`M_SPACE` do not exist. No code filters by space (grep `space` in `genesis_config.py`: no match).
- `h_mask`/`a_mask` boolean masks of size `MAX_HUMANS`/`MAX_ENTITIES` are rebuilt every tick (`map_test.py:4133-4140`, a Python loop over `ANIMAL_TYPES` = 40 `|=` ops on 1024-element masks; the cost is for the profile).
- `Engine` is a **module-level singleton** (`map_test.py` `engine = Engine()`, passed to `GameSessions` at 5316); `map_geo` and `genesis_config` are process globals. Several engines per process (evaluation, `EdenEnv`, synthetic tiny worlds) are not possible today without refactoring. **For R1-H3 this means the World facade can only wrap the single existing engine; a second world must be built from the new pieces (tensors, index, RNG) without the legacy `Engine`.**
- Persistence (`persistence/world_snapshot.py:31-37, 102-106`): the snapshot pickles the whole `h_tensor`, `m_tensor`, and `geometry` (`MAP_GEO` including **every tile mask tensor** and the whole `TILE_TO_ENTITY` dict, plus `random`/`numpy`/`torch` global RNG state). Save size is O(entities x frame), not O(edits); restore asserts `set(payload["engine"]) == set(ENGINE_FIELDS)` (1006 audit), so any new field breaks old saves (consistent with D-001). For D5 (deltas only) the geometry section must be removed or replaced; masks are derivable from shape + position and need not be saved.

## 3. Random number use (WS-H finding 8, re-counted)
`random.` appears on 114 lines in 20 files, `torch.rand` on 5 lines in 4 files, `np.random` on 4 lines in 2 files (counts of lines, not calls). Snapshots save the global RNG state as a workaround. For chunk generation this is irrelevant (a pure function of `(seed, cx, cy)` needs its own primitive); for replay and golden traces it matters now: the golden trace in R1-H2 must run each case in a **fresh process with explicit seeding** because the globals leak across tests.

## 4. What the D0 audit says about each plan item
| Plan item | Finding |
| --- | --- |
| D1 spaces | Columns available. No existing filter; every proximity function needs an equal-space mask (11 `cdist` sites in 5 files, `perception/ops.py`, combat, talk). Retire `ISOLATION_DISTANCE` and `EDEN_MAP_ORIGINS` (5 files). Stage 1 saves refused (D-001). |
| D2 chunk coordinates | Float32 limits in section 5 argue for chunk coordinates as **integers** plus window-relative float positions in the tensor, not global float32. |
| D4/D5 generator and deltas | `systems/map/chunking.py` is pure (no cfg use) and reusable. `chunk_generation.py` depends on `cfg.MAP_WIDTH/HEIGHT` and `random`; it is a reference only (as the plan already says). Snapshot geometry section must change. |
| D6 activation window | Slot reuse hazard (1.3); dynamic capacity; `m_tensor` is allocated once with `device` cuda-if-available. |
| D7 dormancy | Residents live in `h_tensor` rows with `ResidentStore` records; dormant residents must live outside the 100-row tensor to exceed 100 residents. `MAX_HUMANS = 100` is also the cap on `resident_store` slot sync (`sync_live_population`). |
| D8 protocol | `/bootstrap`, map payloads and `agent_cap`/`entity_cap` carry the old constants (table 1.2/1.3). |
| D10 pathing | `pathing.py` is windowed-capable (it takes a contract) but its lattice is bounded by `MAX_CELLS` and assumes bounds in the hundreds of units: use per-window contracts. |

## 5. Float32 precision limits (measured)

`h_tensor` and `m_tensor` are float32 (`torch.zeros(...)` with no dtype in `WorldState`).

### 5.1 Position resolution (ulp of float32)
| \|x\| | ulp | consequence |
| --- | --- | --- |
| 1,200 (today's frame) | 0.000122 | fine |
| 1,024 and up | > 1e-4 | `pathing.EMBED_TOL = 1e-4` and `slide`'s `0.0001` embed tolerance are below one ulp: a position resting exactly on an inflated wall face can classify as embedded/not embedded inconsistently |
| 8,192 | 0.00098 | step increments of 0.001 vanish |
| 16,384 and up | > 1e-3 | `snap_to_standable` margin `0.001` (spatial.py) is below one ulp: pushing out of a box can land back inside |
| 100,000 | 0.0078 | the plan's D2 "+/-100k is fine" is about the ulp being 0.008 units (0.05 px at 6 px/unit): visually fine, but see the next two rows |
| 131,072 | > 0.01 | walking-step increments below 0.01 are lost |
| 524,288 | > 0.05 | a 0.05-unit step (3 px/s at 20 Hz) stops moving the actor: **measured** accumulation of 100 x 0.05 at offset 1e5 gives 4.69 instead of 5.0, and 6.25 at 1e6 (round-to-even drift) |
| 16.7 M | 2.0 | integers stop being exact |

Walk speed is 1.0 unit/tick (`MOVE_STEP`), so full steps survive to roughly |x| = 1.6e7; it is the sub-unit steps (arrival slowdowns, slide corrections, separation pushes, `repulsion`) that break first. **Inference:** the engine would still run at 1e5 but with visibly different collision and arrival behaviour, which breaks golden-trace comparisons across origins.

### 5.2 Distances: `torch.cdist` (11 call sites in 5 files)
`torch.cdist` uses `||a||^2 + ||b||^2 - 2a.b` (matmul) when either side has more than 25 rows. **Measured** (positions confined to a 40-unit square at the given offset; error is max absolute difference to a float64 reference computed from the same float32 inputs):

| Offset | position quantisation | `cdist` default (>25 rows) | `cdist` with `compute_mode="donot_use_mm_for_euclid_dist"` |
| --- | --- | --- | --- |
| 0 | 1.8e-6 | 1.5e-4 | 3.8e-6 |
| 1,000 | 6.1e-5 | 0.29 | 3.8e-6 |
| 10,000 | 4.9e-4 | 6.1 | 3.8e-6 |
| 100,000 | 3.9e-3 | 62 | 3.8e-6 |
| 1,000,000 | 3.1e-2 | 510 | 0 |

Threshold check at offset 1000: (25 x 25) error 3.8e-6; (26 x 25) 0.058; (25 x 26) 0.115; (1024 x 1) 0.78. Radii in use: mating 8, infection 10, threat 15, crowding 18, drink 24 (`genesis_config.py`), so **already today an entity query at x near 1000 can mis-rank by up to 0.8 units and a 100-resident proximity pass by about 0.3**. Sites: `instincts_and_tools.py` 860, 915, 1504, 1843, 1859, 1898; `systems/map/create.py:434`; `systems/nature/disasters.py:198`; `systems/nature/hazards.py:89`; `systems/perception/queries.py` 94, 111. At 8 residents (Stage 1) the human passes are below the 25-row threshold, which is why Stage 1 never saw it.

### 5.3 Recommended handling (for the World facade, not implemented here)
(a) Always call `cdist` with `compute_mode="donot_use_mm_for_euclid_dist"` or compute `diff = a[:,None]-b[None]` explicitly (cost is trivial at N <= 1024). (b) Store tensor positions **relative to a per-window origin** (integer chunk anchor kept in float64/Python ints), so values stay within a few thousand units; convert at the API boundary. (c) Keep authoritative global coordinates as `(chunk_x, chunk_y, local_x, local_y)` or float64 in the delta store. (d) Add a test that moves the whole scenario by an offset (for example 100,000 units) and requires identical relative behaviour.

## 6. Order of work implied (for the orchestrator to assign; none started)
1. (Harness, now) World facade owns bounds/centre/clamp/index/RNG; legacy code reads through it (adapters). Fix `cdist` mode behind one helper (new `harness` function; the 11 call sites to switch need a go-ahead because they are in files owned by others).
2. (Round 2) Spatial index as an instance with sparse per-chunk storage and persistent-id keys; `world_contract` per window; windowed pathing lattice.
3. (Round 2) `H_SPACE`/`M_SPACE` and an equal-space mask in every proximity function.
4. (Round 2+) Snapshot without tile masks; deltas.

## 7. What this audit did NOT do
- It did not run the whole engine under a profiler (that is `./tick_profile.md`), so the per-tick cost of `world_contract` / `_current_masks` is reading-based here.
- It did not enumerate the 120 legacy functions individually; call-site tables are by grep for the named constants and `map_geo` names. Positions are also reached through `h_tensor[:, :2]` slices that never mention a constant (for example `instinct_proximity` and the pairwise pass at `instincts_and_tools.py:826-915`): those are not frame-dependent but are precision-dependent (section 5.2).
- The Godot client, `game_frontend/` and `myassets/` were not read (out of ownership); the client consequences of `width`/`height`/`tile_size` in the protocol are listed from the backend side only.
