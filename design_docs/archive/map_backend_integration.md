# Loading an authored WorldMap into the live backend: design note

Author: session 1006implementation, 2026-10-06. Design only; no existing file was changed.
Builds on `at_the_beginning/world_map/` (format `0.1-draft`, not yet confirmed by Codex) and addendum `../designs/implementation_1006_2d_rebaseline.md` sections 4-5 (P1-P3).

Marks: **[V]** = read in code this session. **[U]** = unverified inference or guess, check before relying on it.

## 0. Findings that shape everything

1. **The M_WALL tensor row cannot express an authored box.** `spatial.wall_boxes` [V] derives a box from `(CX, CY, SCALE)` only: x half-extent `max(SCALE, 2.0)`, y half-extent a fixed `0.6`, height `2.4`. An authored wall `[min, max]` of arbitrary width and depth needs two more numbers on the row.
2. **Entity IDs are not stable today.** `Engine._make_entity_id` [V] hands out `e_000001, e_000002, ...` in slot order inside `_assign_missing_ids`, which only fills slots whose uid is `None`. Map-file IDs therefore need to be written into `_entity_uid_by_slot` before that runs (see 1.3).
3. **Nothing consumes anchors yet.** Schedule navigation (`systems/schedule/navigation.py::build_schedule_navigation_bias` [V]) picks targets by M_TYPE sets (`PLACE_TAG_TYPES`, `ROUTINE_DEFAULT_TYPES`) via `nearest_geo_entity(..., radius=220.0)`, then applies a straight-line unit vector with no pathfinding. Walls are only resolved afterwards by `spatial.slide` per tick (`Engine.step`, `map_test.py` ~4779 [V]). Straight-line bias plus slide gets NPCs stuck behind a building. P3 ("NPCs move between anchors without teleporting") needs path planning.
4. **Unit system is inconsistent and constrains the pixel factor** (section 7). The world is `MAP_WIDTH x MAP_HEIGHT = 1200 x 900` [V], walk speed is 20 units/s (`MOVE_STEP=1.0` x `TICK_RATE_HZ=20`), actor radius 0.35, but a house is `scale 6` (12 wide) and reach/attack distances are 30 and 14.
5. **Snapshot validation is strict.** `persistence/world_snapshot.py::validate` [V] requires `set(payload["engine"]) == set(ENGINE_FIELDS)`; adding a saved engine field makes every existing save fail with "World state schema mismatch" unless validation is made tolerant (section 4).

## 1. Walls -> M_WALL tensor entities, and ID mapping

### 1.1 Representing the box
Add two structure columns in the reserved range (`genesis_config.py` says 13-31 are reserved [V]; `MAP_TENSOR_COLS` stays 32, so snapshot tensor shape is unchanged):

```
S_FOOTPRINT_HALF_X = 13   # authored half-width in backend units; 0 = legacy derivation
S_FOOTPRINT_HALF_Y = 14
```
`spatial.wall_boxes` change (the only behavioural edit): if `row[S_FOOTPRINT_HALF_X] > 0`, use `x ± half_x`, `y ± half_y`; else the existing `max(scale, 2.0)` / `±0.6` formula. Height stays `2.4` unless a `S_FOOTPRINT_HEIGHT` is wanted (2D client ignores height; leave it).
Legacy rows have 0 in those columns, so `test_combat_walls` (`wall_boxes(m)[0]["min"] == [98, 99.4]`) and existing saves behave identically. Old checkpoints load unchanged.

### 1.2 Instantiation
New file `at_the_beginning/world_map/instantiate.py` (no edit to existing files), function `instantiate_map(engine, world_map, origin=(0.0, 0.0))`. For each wall:
- `idx = entity_born(m_tensor, entity_count_ref, cx, cy, M_WALL, hp=AUTHORED_WALL_HP, scale=max(half_x, half_y), register_geo=False, col_vals={S_DURABILITY:..., S_FOOTPRINT_HALF_X: half_x, S_FOOTPRINT_HALF_Y: half_y})` (`instincts_and_tools.py:992` [V]; `col_vals` takes arbitrary columns).
- Register geometry as a rectangle polygon via `map_geo.register_entity(idx, "polygon", cx, cy, points=[four corners])` as `systems/map/create.py` does for player-built walls [V; `register_entity` accepts `shape="polygon"` + `points`]. This keeps `TILE_TO_ENTITY`, `/map_delta` shape export and the legacy 3D client consistent with the authored box. (`entity_born(register_geo=True)` only registers circles [V].)
- `cx = (min_x + max_x) / 2`, `half_x = (max_x - min_x) / 2`, same for y, plus `origin`.

### 1.3 IDs
Rule: **the map-file id is the backend entity id.** After `entity_born`, set `engine._entity_uid_by_slot[idx] = wall.id` before `prime_protocol_state()` runs `_assign_missing_ids` (which skips slots already holding a uid [V]).
- Needs no new saved field: `_entity_uid_by_slot` is already in `ENGINE_FIELDS` [V], so ids survive Save/Continue.
- `_sync_slot_ids_and_events` clears the uid when a slot empties [V], which is correct for a destroyed wall.
- Collision rule to add to the validator (my files): map ids must not match `^e_\d{6}$`, the generated namespace. The parser already makes wall and entity ids share one namespace.
- Entities (chests, forge) use the same mechanism with `entity_born` and a kind->M_TYPE table (1.4).

### 1.4 Entity kinds
`entities[].kind` needs a map to `M_TYPE`: chest -> `M_STORAGE_CASE` (25), building -> `M_HOUSE` (20), well -> `M_WELL` (23). **No forge type exists** [V: types 20-25 only], and P4 needs one: add `M_FORGE` to `genesis_config.py` plus a `MAP_SCHEMA` entry [V: `MAP_SCHEMA` holds `label`/`attrs` per type]. Decorative (`interactive:false`) entities are **not** instantiated into the tensor at all; they stay in the map file and go to the client via the file (section 3). This keeps `MAX_ENTITIES=1024` free.
`Engine.prime_protocol_state` calls `_spawn_starter_storage_case` [V] and would add a second chest; when a map provides a container entity, skip it (small edit, or let the map set `_starter_storage_case_entity_id` first [U: check the function's early-return condition]).

### 1.5 Destructibility
`wall_boxes` ignores rows with `M_HP <= 0` and the combat test destroys walls [V]. Authored structural walls should not be removable in v1: use a very large HP [U: whether combat can damage `M_WALL` at all was not traced]. Add a test that attacking an authored wall leaves `world_contract` boxes unchanged.

## 2. Anchors -> schedules, work/talk targets, interaction range

Anchors are not tensor entities; they are an engine-side lookup built from the loaded map.

- Registry: `engine._map_anchors: dict[id, (x, y, kind, map_id)]`, rebuilt from the map manifest on load and Continue. Not saved (derived), so no snapshot change.
- Residents: store `home_anchor`, `work_anchor`, `talk_anchor` ids in the resident record (`runtime/resident_store.py`; `schedule_state` already lives there [V]). Assigned at map instantiation for the named villagers (today they are four hard-coded spawns in `create_genesis` at `cx_px +- ~18` [V]; the map's `spawn` anchors replace them).
- Schedule targets: in `build_schedule_navigation_bias`, before the `nearest_geo_entity` fallback, resolve `routine_kind -> anchor kind`: `sleep/stay_home/return_home -> sleep|door`, `work_site -> work`, `socialize -> talk`, and use the resident's assigned anchor, else the nearest anchor of that kind. Else fall back to the old type-based lookup, which keeps playable_village behaviour.
- Pathing: add `systems/movement/pathing.py` (new) built on `world_map.validate.walkable_grid` (the same inflated-box grid the validator uses, so reachability proven by the validator is exactly what NPCs can walk). A* over the grid gives a waypoint list; the bias vector points at the next waypoint instead of the final anchor. Cache per `(from_cell, anchor_id)`; recompute when `world_contract["revision"]` changes. Without this P3 will visibly fail at the first building [U: not yet exercised].
- Player interaction range: today reach is hard-coded (container reach `30` in `simulation/inventory_commands.py` [V], `ATTACK_RANGE = 14.0` [V]). Add an optional `interact_radius` to map entities (draft-schema addition, default stays the current constants) and have the container check use `engine.map_entity_interact_radius(entity_id)`; the 2D client shows the prompt using the same number from the map file. Anchors of kind `talk` get a fixed default radius constant (decide with units, section 7).
- Anchors double as spawn points: `create_genesis` branch for authored maps places residents on `spawn` anchors and skips the hard-coded list.

## 3. Bootstrap / view fields and how the client gets tiles and sprites

Additive only; no existing key changes meaning.

`GET /bootstrap` (`map_test.py:5196` [V]) merges `engine._bootstrap_payload` with `world_epoch`, `spatial`, `launch`, `session`. Add (only when a map file is loaded, omitted otherwise so the 3D client sees nothing new):

```json
"map_file": {
  "format_version": "0.1-draft", "map_id": "village", "revision": 3, "sha256": "<of canonical JSON>",
  "units_per_tile": <from file>, "tile_size_px": 48, "size_tiles": [w, h],
  "origin": [0, 0], "url": "/map_file/village",
  "portals": [{"id": "...", "from_anchor": "...", "to_map": "..."}]
}
```
and in `world_contract(engine)` add `map_id`, `map_revision`, `units_per_tile` (keep `version: 1`; the Godot `spatial_contract.gd::slide` [V] only reads `version`, `actor_radius`, `boxes`, `bounds`). Do **not** reuse the key `revision`: `world_contract["revision"]` is already the wall-box hash [V].
Naming trap: `world.tile_size` in `_world_payload` is the legacy 8 px background tile [V: `TILE_SIZE = 8`]. The new block uses `tile_size_px` and lives under `map_file`.

Tile data: not in bootstrap (a 200x200 map with three layers is large and bootstrap is polled). New route `GET /map_file/{map_id}` returns the validated map as JSON from the in-memory `WorldMap` (re-serialised; never a file path from the request, so no traversal). The client compares `revision`/`sha256` from bootstrap with what it cached and refetches on mismatch. This is read-only and falls under the existing local-session GET rule [V: `LocalSessionBoundary` only gates non-GET].
Sprites: the backend does **not** serve images. `sprite` references are relative paths resolved against the client's own asset root (Godot `res://` copy of `myassets/`); the validator's `--base-dir` check is what guarantees the files exist at author time. Open question for Codex: that root path.
Per-frame: add `map_id` of each actor's region and a `teleport_seq` counter on `/frame` actor entries (section 4), additive.
The browser `game_frontend` zod schema (`schema.ts` [V] uses `.catch` defaults) tolerates extra keys, so diagnostics keep working.

## 4. Portals, interior maps, saves, epochs

### 4.1 Recommended model: one world, many placed regions
Instantiate every map file the save needs into the single tensor world, each at a distinct `origin` in the 1200x900 frame; a portal is an actor teleport to the target anchor's world position. Reasons:
- `world_epoch` (`Engine.reset_world`, `snapshot.restore` regenerate it [V]) and `possession_epoch` (`control_runtime.py` ~539 [V]) stay **unchanged** by walking through a door, so command ids, claims and in-flight commands are not invalidated. Swapping the active map instead would force a new world_epoch (rejecting every pending command with `stale_world_epoch` [V `CommandInbox.authorize`]) or a bespoke partial reset.
- Residents, inventory, memory, schedules and checkpoints already assume one tensor world; interior NPCs keep ticking.
- Cost: interiors must sit far enough from the village that perception/nearest-entity radii do not cross (`nearest_geo_entity` radius `220` [V]; attack range 14). With a 1200x900 world, place interiors in a strip > 220 from any village entity [U: depends on final village extent]. The bounds in the spatial contract become the union of placed maps, so interior walls (not bounds) keep actors in. A sealed room needs a bounding wall ring in its map file; add a validator warning when a portal-target map has walkable space open to its own bounds edge... (nice-to-have).
- Alternative (separate world per interior) is rejected for v1 because of the epoch cost above.

### 4.2 Portal use
Add a command through the existing queue so it is idempotent and epoch-checked: `CommandInbox.submit(engine, "portal", payload)` -> executor. Today `drain(engine, execute_inventory_command)` runs inventory actions only [V `Engine.step`]; generalise the executor to a small dispatcher (`simulation/commands.py` untouched, new `simulation/portal_commands.py`). Server checks: the controlled human is within the portal's `from_anchor` interact radius, target map is loaded, then sets `h_tensor[slot, X/Y]` to the target anchor world position. The per-tick `slide` start position must be reset in the same tick, otherwise `Engine.step`'s `movement_starts` (captured at tick start [V]) makes the displacement look like a huge move. Mark a `teleport_seq` on that actor in the next frame so the 2D client snaps instead of interpolating, and swaps the visible map by `map_id`.
NPCs use portals the same way when a schedule anchor lives in another map (path to the door anchor, then teleport) [U: P6 scope].

### 4.3 Saves
- Add `_map_manifest` (list of `{map_id, revision, sha256, origin}`) to the world snapshot. Because `validate` requires an exact field set, change it to: required fields as today, plus optional fields (default `[]`) so schema-1 saves still load. Prefer this to bumping `schema` to 2, since `schema` 1 files exist in `.runtime/` [U] and the checkpoint manifest also carries `schema: 1` [V].
- Walls and entities already persist through `m_tensor`/`_entity_uid_by_slot`/`MAP_GEO` [V], so a save is self-consistent even if the map file later changes.
- Continue with a changed file (revision or sha mismatch): policy. Gameplay profile: refuse with a clear error naming old/new revision (safe, matches "client can detect mismatch"). Development profile: re-apply static layer by id (update footprint, add new, remove ids no longer in file, keep HP/state of survivors). Needs its own tests; do not build the re-apply path before it is needed.
- `GameSessions.new` hard-codes `map_name="playable_village"` [V `persistence/sessions.py:114`]; make it use the configured map.
- Checkpoint paths: the two `test_checkpoints` failures are the ~262-char Windows path [V by world-simulator-1b]; map data adds no files to the checkpoint directory.

## 5. Files to edit, and the smallest safe sequence

Each step is independently shippable and leaves the legacy path unchanged. Test file named per step.

| Step | Edit | Test |
| --- | --- | --- |
| S1 | `genesis_config.py`: add `S_FOOTPRINT_HALF_X/Y = 13/14`. `systems/movement/spatial.py::wall_boxes`: honour them when > 0. | `tests/test_spatial_contract.py`/`test_combat_walls.py` unchanged and green; new: row with footprint -> exact box, legacy row -> legacy box, `world_contract` revision stable for legacy worlds. |
| S2 | `spatial.world_contract`: `bounds` from `engine._map_bounds` if set, optional `map_id/map_revision/units_per_tile`. | Contract dict byte-identical when no map loaded; with map, bounds equal `world_map.bounds`. |
| S3 | NEW `world_map/instantiate.py` (+ id-namespace rule in `parse.py`). No existing file touched. | In an isolated data root (as `test_startup_preservation.py` does [V]): instantiate fixture; `world_contract(engine)["boxes"] == to_wall_boxes(map)` (ids, min, max); `slide` parity; `reset_world` clears. |
| S4 | `launch_config.py`: optional `map_file`; `map_test.py::create_genesis`: authored branch; `persistence/sessions.py:114`: use configured map. | `test_launch_config.py` (status keys); new world from the fixture; default still `playable_village`; `test_session_lifecycle.py` green. |
| S5 | `map_test.py`: `/bootstrap` `map_file` block, `/map_file/{map_id}`. | Block present iff authored; 404 on unknown id; payload equals the loaded file; `test_control_protocol.py`/`test_local_session.py` green. |
| S6 | `persistence/world_snapshot.py`: optional `_map_manifest` field + restore reconciliation. | Old-format snapshot loads; round trip keeps wall ids and boxes; revision-mismatch refusal; `test_resident_persistence.py`. |
| S7 | `systems/schedule/navigation.py`: anchor targets; NEW `systems/movement/pathing.py`; `runtime/resident_store.py`: anchor assignment. | Resident at night heads to its sleep anchor; path routes around a wall; playable_village schedule behaviour unchanged. |
| S8 | NEW `simulation/portal_commands.py`; `map_test.py` drain dispatcher; frame `teleport_seq`. | Portal moves actor to target anchor in the same `world_epoch`/`possession_epoch`; duplicate `command_id` is idempotent; out-of-range rejected; no slide artefact on the teleport tick. |

S1-S3 are enough for P1's exit test on the backend side ("same file produces matching walls on both sides" needs S5 and the Godot loader as well).

## 6. playable_village and the legacy 3D client

- `initial_map_design.map_playable_village` / `map_render_test_village` and `MAP_REGISTRY` stay untouched; they remain the default (`LaunchConfig.map_name`) and what `test_spatial_contract.py` uses [V]. The authored map is selected only when `map_file` is configured, so no existing profile changes behaviour.
- `/set_map/{name}` and `/testing/render_test_village` keep working [V route list]; authored loading is a separate path, not a registry entry (a registry entry would run through `pick_map` without the instantiate/manifest hooks).
- 3D client compatibility: `spatial` only gains keys; `/bootstrap` gains a block only for authored maps; map entities for authored walls are polygon M_WALL like player-built walls, which the client already receives via `/map_delta` [V shape export]. Whether the 3D client renders polygon walls acceptably was not checked [U]. No 3D file needs editing.
- Add a regression test that boots `playable_village` and compares the whole bootstrap/contract key set before and after S1-S5.

## 7. Risks and the unit reconciliation

### 7.1 Legacy wall unit
`wall_boxes` = `x ± max(SCALE, 2.0)`, `y ± 0.6`, always axis-aligned, regardless of the polygon actually registered for player-built walls [V `systems/map/create.py` builds rotated polygons, `wall_boxes` ignores them]. So today's collision and the drawn polygon already disagree for rotated built walls. Plan: leave legacy behaviour for rows with zero footprint columns (back-compat, save-compat) and let authored walls opt out via the footprint columns (1.1). Do not "fix" the legacy formula in this work; rotated built walls remain a separate bug [U: severity unknown].
Also `genesis_config.py` documents `CX/CY` and `SCALE` as "px" [V] while the 3D contract says `units_per_meter: 1.0` [V]; treat backend units as unitless and let `units_per_tile` define the scale to art.

### 7.2 Choosing `units_per_tile` (needs Codex/user decision)
Facts [V]: walk 20 u/s, sprint 30, `RADIUS` 0.35, attack range 14, container reach 30, schedule search radius 220, world 1200x900, house width 12.
Tiles per second at walk speed = 20 / upt:

| upt | walk tiles/s | attack range (tiles) | reach (tiles) | world (tiles) | radius 0.35 in px (48 px tile) |
| --- | --- | --- | --- | --- | --- |
| 1 | 20 | 14 | 30 | 1200x900 | 17 |
| 2 | 10 | 7 | 15 | 600x450 | 8 |
| 4 | 5 | 3.5 | 7.5 | 300x225 | 4 |
| 6 | 3.3 | 2.3 | 5 | 200x150 | 2.8 |
| 8 | 2.5 | 1.75 | 3.75 | 150x113 | 2.1 |

Reading: legacy distances (attack ~2 tiles, reach ~4-5 tiles, 3 tiles/s walk) are sensible only around **upt 6-8**. But at that scale 0.35 is a 2-3 px foot radius, too small for a 128 px sprite with a foot pivot [V `myassets/manifest.json` per X-002; sprite foot width unverified]. Recommendation: pick **upt around 6** for speed/range, and add an **optional file-level `actor_radius`** (draft-schema addition, backend units) that overrides `spatial.RADIUS` in the contract (`world_contract` builds `actor_radius` from the module constant and the Godot slide reads it from the contract [V], so a per-map value flows through with no client change; validator already takes the radius as a parameter, I would make it default to the file's value). A radius near 0.8-1.0 unit (about 0.15 tile) keeps door gaps of 1 tile (6 units) comfortably passable. Alternative (upt 2 plus slowing `MOVE_STEP` to ~0.3 and rescaling every range constant) touches movement tests and combat; not recommended.
Either way, document `units_per_tile` in the map file only; nothing else should hardcode a pixel factor (client converts `pos_px = pos_units * tile_size_px / units_per_tile`).

### 7.3 Other risks
- **Straight-line NPC bias** will wedge NPCs on walls until S7 pathing lands (finding 3).
- **Snapshot strictness** (finding 5): any new saved field without the tolerant-validate change locks out existing saves.
- **`/map_file` size and caching**: use `sha256` + `revision` for client cache validation; do not push tiles through `/map_delta`.
- **Interior regions in the 1200x900 frame** rely on distance for isolation; a future cross-region perception bug (NPCs "seeing" through rooms) is plausible [U]. A per-actor `map_id` filter in `nearest_geo_entity` is the fix if it appears.
- **`MAP_GEO` tile grid** is 8-unit background tiles over the 1200x900 world [V]; polygons for thin walls (1 unit thick) rasterise to few or zero tiles, so `TILE_TO_ENTITY` lookups ("which entity am I standing in") will be unreliable for authored walls. Collision uses `wall_boxes`, not `TILE_TO_ENTITY`, so this affects only perception/schedule queries [U].
- **`_spawn_starter_storage_case`** duplicate chest (1.4).
- **Hard-coded `map_name="playable_village"`** in `create_genesis` villager list and `GameSessions.new` (S4).
- **Draft schema changes this note depends on** (all in my files, cheap): optional `actor_radius`, optional per-entity `interact_radius`, id-namespace rule, and a validator warning for unsealed interior bounds. Not added yet; they wait on Codex's answers to C-005/C-006.

## 8. Decisions needed before S4+
1. `units_per_tile` (7.2) and whether the file may carry `actor_radius`.
2. Interiors as placed regions in one world (recommended) vs separate worlds.
3. Mismatched-revision policy on Continue (refuse in gameplay profile, re-apply in development).
4. M_TYPE for the forge and other P4 objects.
5. Whether authored walls are indestructible in v1.

## 10. Status of S1-S8 as built (2026-10-07)

| Step | Status | Where |
| --- | --- | --- |
| S1 footprint columns for authored walls | **Not built, by design.** Authored walls are contract boxes (`world_contract` / `map_contract`), not tensor `M_WALL` rows, so the tensor columns were not needed. | `systems/movement/map_contract.py`, `spatial.py` |
| S2 contract bounds/radius override | Built (radius, union bounds, boxes, containment slabs, `map_id/map_revision/units_per_tile`) | `spatial.world_contract`, `map_contract.compose_group` |
| S3 entity instantiation | Built (map-file ids are backend ids; storage -> `M_STORAGE_CASE`, other interactive kinds -> inert `M_MAP_OBJECT`) | `systems/map/authored.py` |
| S4 launch/session wiring | Built (`EDEN_MAP`, `EDEN_MAP_FILES`, `EDEN_MAP_ORIGINS`; New Game uses the launch map; Continue refuses unregistered maps) | `launch_config`, `persistence/sessions.py`, `world_snapshot._require_known_map` |
| S5 bootstrap `maps[]`, `/map_file/{id}` | Built per `../contracts/map_wire_contract.md` | `map_test.py` routes |
| S6 snapshot manifest | **Not built.** Nothing was added to `ENGINE_FIELDS`; the world re-derives its contract from the saved `_map_name` and refuses a map that is not registered. A changed map file is not detected (open). | `world_snapshot.py` |
| S7 anchors/schedules | Built for roster residents (`systems/roster/`, `AnchorMover`, `pathing.py`) | `driver.py`, `anchor_mover.py` |
| S8 portals | Built (`POST /control/portal`, `teleport_seq`, same epochs) plus `simulation/dispatch.py` hooks | `simulation/portal_commands.py` |
| Smith loop (P4) | Built: decision seam, work orders with escrow, `/commission/*`, live-verified | `systems/decision/`, `systems/commission/` |
