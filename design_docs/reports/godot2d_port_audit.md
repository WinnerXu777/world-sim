# Godot 2D port audit and snapshot readiness — 2026-10-06

Read-only audit by session 1006implementation2 for `../designs/implementation_1006_2d_rebaseline.md` (sections 1, 3, 5). No code, git state, or `.gitignore` was changed. Nothing here was executed against a running backend or Godot; every claim is from reading source unless marked **unverified**.

## 0. Headline findings

1. **A 2D client already exists** (`godot_client/scripts/main.gd` + `scenes/Main.tscn`, `Node2D`, "Eden World Viewer"). It is a debug-shape viewer (circles/polygons via `agent_view.gd`, `map_entity_view.gd`) polling `/frame` and `/map_delta`. It has no session menu, no spatial contract, no committed-state handling. Do not build on it, but its `_request_json`, talk/inventory panels and map-delta polling are copyable.
2. **The rebaseline's "reuse" list holds with one correction.** `session_menu.gd`, `launch_profile.gd` and the transport are reusable. `spatial_contract.gd` is reusable only for parity tests and optional client-side checks, because with no prediction the client never calls `slide()`. `control_replica.gd` is reusable with changes (drop the replay clock).
3. **Interpolation is already written, but inline in the 3D file** (`human_mode_3d.gd` lines 1715-1870: `_make_actor_snapshot`, `_append_actor_snapshot`, `_sample_actor_presentation`). It must be extracted into a standalone Vector2 `snapshot_buffer.gd` rather than reused in place.
4. **Unit scale is a real P1 risk.** Backend contract is `walk_speed` 20 u/s (`MOVE_STEP` 1.0 × 20 Hz), `actor_radius` 0.35, wall half-thickness 0.6, map 1200×900, `world.tile_size` 8. Actor positions are exported rounded to 0.1 (`_export_human`/`_export_animal`, `map_test.py` ~4357-4400). With 48 px tiles, a unit→px factor and these constants will not agree without a contract change; 0.1 unit can also be visible jitter. Decide the factor and sprite scale together with the map loader.
5. **Routes live in `at_the_beginning/map_test.py`, not `api/`.** `api/local_session.py` is only the loopback + `X-Eden-Session` capability middleware.

## 1. Part 1 — Godot client audit

Classification: **AS-IS** (usable in 2D unchanged), **CHANGE** (reusable with edits), **3D** (3D-only; dead for 2D).

### 1.1 `godot_client/scripts/app/`

| File | Class | Notes |
| --- | --- | --- |
| `launch_profile.gd` | AS-IS | Pure env/args parsing (`EDEN_PROFILE`, `EDEN_PORT`, `--backend-url=`). Defaults: gameplay → port 8002, others 8012. The `animation_qa` profile is 3D-only and can be dropped. |
| `session_menu.gd` | AS-IS (small CHANGE) | `CanvasLayer` + Controls only. Calls `GET /session`, `POST /session/new`, `/session/continue`, `/session/save`. Needs host methods `_request_json`, `_bootstrap`, `_reset_world_replica`, `_claim_window_focus`. Title text is hard-coded "EDEN · MEDIEVAL VILLAGE". F6 toggle lives in `human_mode_3d.gd:2029`, not in the menu, so the 2D host must bind it. Remaining 0905 A2/A4 items land here. |
| `spatial_contract.gd` | AS-IS (role shrinks) | Pure Vector2, mirrors `systems/movement/spatial.py::slide`. 2D coordinates map directly (backend x,y = Godot 2D x,y; the 3D client mapped y→Z). With server-authoritative movement the client never calls it. Keep it for `tests/spatial_parity.gd`, optional wall-hit feedback, and map-loader parity checks (P1). |
| `control_replica.gd` | CHANGE | Gatekeeper for `controls[].committed_state`: validates protocol, world/possession epoch, target id, monotonic `completed_tick`/`seq`. Keep `accept()` gating. Remove `applied_seq`/`applied_seconds`/`has_consumption_clock` (replay-only), and push accepted `(tick, position)` into the snapshot buffer instead of holding one `position`. `tests/control_replica_validation.gd` asserts the consumption clock and must be edited. |
| `movement_history.gd` | 3D (dead) | Input replay history. Delete from 2D. |
| `ground_player_motor.gd` | 3D (dead) | Local physics motor/prediction. Delete from 2D. |
| `player_presentation.gd` | 3D (dead) | Visual correction offset for prediction error. Replaced by interpolation. |
| `camera_obstruction.gd` | 3D (dead) | Vector3 camera sweep against wall boxes. 2D camera is follow + zoom. |
| `character_animation_graph.gd` | 3D (dead) | `AnimationTree` + blend-space for the 3D rig. 2D uses `AnimatedSprite2D`. |

### 1.2 `godot_client/scripts/` (top level)

| File | Class | Notes |
| --- | --- | --- |
| `human_mode_3d.gd` (4885 lines) | 3D, but **mine for transport and logic** | Not reusable as a file. Extract: `_request_json` (lines 732-789: capability header, 401 handling, `protocol_version/world_epoch/possession_epoch/event_id/command_id` stamping, `/commands/{id}` polling up to 100×0.1 s); `_send_control_event` (2412) incl. attack receipt polling on `/control/event_result`; `_send_control_snapshot` (4671); `_refresh_control_state` (2199) epoch-change reset; snapshot-buffer functions (1715-1870); `_apply_actor_payload` despawn handling; talk/inventory panel logic. |
| `main.gd` (1135 lines) | **Existing 2D viewer**; CHANGE as a source of copy, not a base | Same `_request_json` copy. Uses `/frame`+`/map_delta`+`/view/window`. No `SessionMenu`, no spatial contract. `AgentView.position.lerp(target, delta*10)` is exponential smoothing, not timestamped interpolation. Modified in the working tree (+53/−3). |
| `agent_view.gd`, `map_entity_view.gd` | Placeholder | Debug circle/polygon drawing. Replaced by sprites; `MapEntityView` shape-from-payload logic is moot once the authored map file drives visuals. |
| `incarnation_human.gd`, `human_visual_qa.gd`, `humanizer_incarnation_prototype.gd` | 3D | Rig, humanizer, QA. Dead for 2D. |

### 1.3 Scenes, project, tests

* `scenes/Main.tscn` is the Node2D viewer scene; `HumanMode3D.tscn`, `HumanVisualQA.tscn`, `characters/*` are 3D. `project.godot` main scene is `HumanMode3D.tscn`, features `4.6`, autoloads `HumanizerGlobal` and `FunplayMcpRuntimeBridge`, enables three editor plugins.
* **Tests (godot_client/tests/, all untracked):**
  * Reusable for 2D with edits or as pattern: `control_replica_validation.gd`, `spatial_parity.gd` (needs `.tmp/implementation_0905/spatial_cases.json` generated by `tools/generate_spatial_cases.py`), `session_menu_smoke.gd` (loads `HumanMode3D.tscn`; swap scene), `inventory_command_smoke.gd` (same), `gameplay_capture.gd`, `delayed_gameplay_client.gd` (250 ms RTT wrapper).
  * Dead with the 3D files: `movement_history_validation`, `ground_player_motor_validation`, `player_presentation_validation`, `camera_obstruction_validation`, `measured_motion_routing`, `animation_*`, `build_*`, `bake_*`, `supported_character_validation`, `character_asset_audit`, `animal_scale_*`. Several of these `load("res://scripts/human_mode_3d.gd")` directly.
* **Launching:** `godot` resolves on PATH to `C:\Users\Rita\Downloads\Godot_v4.6.2-stable_win64.exe\godot.bat`, a wrapper for `Godot_v4.6.2-stable_win64_console.exe`. Installed version: **4.6.2.stable.official.71f334935** (matches `config/features 4.6`). Pattern from `tools/gameplay_development.md` and `tools/supported_character.md`:
  * Headless logic test: `godot --headless --path godot_client --log-file <log> --script res://tests/<name>.gd`
  * Backend-integrated: `godot --path godot_client --log-file <log> --resolution 1400x980 --script res://tests/gameplay_capture.gd -- --profile=gameplay --backend-url=http://127.0.0.1:8012 --create-test-world` (user args after `--`).
  * Scripts `extends SceneTree`, run from `_initialize`, call `quit(0|1)`, print a `*_PASS` line. Log/evidence paths in the docs reference the old `C:/Users/Rita/Desktop/world_simulator/` root; the repo now sits at `Desktop/caleb/world_simulator/`. **Unverified:** no test was executed in this audit.

## 2. Backend surface a 2D client needs

All routes are in `at_the_beginning/map_test.py` (line numbers at time of reading). Non-GET requests need header `X-Eden-Session: <capability>` from `/bootstrap` (`api/local_session.py`); loopback host only; origin loopback only.

| Need | Route | Ref | Key fields |
| --- | --- | --- | --- |
| Bootstrap | `GET /bootstrap` | 5196 | `protocol`, `world{map_name,width,height,tile_size,sim_tick_hz,agent_frame_hz,map_delta_hz,…}`, `schema`, `map{geo_version,state_version,entities[]}`, `inventory`, `talk`, `world_epoch`, `spatial` (contract), `launch`, `session{world_loaded,…}`, `session_capability`. Built by `_refresh_bootstrap_payload` (4531). No map revision field exists yet; the P1 map file needs one added here (rebaseline §4). |
| Session | `GET /session`, `POST /session/new {name}`, `/session/continue {save_id}`, `/session/save` | 5203-5234 | status: `active_save_id,name,world_loaded,busy,last_saved_tick,error,autosave_interval_seconds,recovered_previous,world_epoch`; `saves[]`: `save_id,name,tick,saved_at,…` (`persistence/checkpoints.py::list_saves`; lifecycle in `persistence/sessions.py`). Errors return 400/503 with `detail`. |
| Entity frame (all actors, ~every tick while controlled) | `GET /frame` | 5239, builder 4605 | `tick, agents[], animals[], controls[], despawned[], events[], inventory, talk, nature`. Frame rebuilds every `AGENT_FRAME_EVERY`=4 ticks (5 Hz) **or** when forced; every accepted `/control/input` forces a rebuild. **`/frame` has no `spatial`.** |
| Window view | `POST /human_view/window` | 5757, builder `get_human_view_window` 782 | 3D/chunk oriented: `chunk_upserts`, `projection{world_axes x→x,y→z}`, `actors{humans,animals}`, `spatial`, `controls`, `inventory`, `talk`. Computed per call, re-exports map entities. 2D does not need the chunk parts. |
| Map changes | `GET /map_delta?since_state_version&since_geo_version` | 5244 | `upserts[], removed[], replace_all`. Will be superseded by the authored map file, but entity upsert/removal for usable objects likely stays. |
| Actor render hints | in `agents[]/animals[]` and `actors.*[]` as `render` | 4195-4290 | `server_tick, server_time (=tick/20), velocity_world{x,y}, speed, moving, direction_world{x,y}, facing_yaw, locomotion (idle/walk/run/flee), action, action_started_tick`. `facing_yaw = atan2(-dx,-dy)` is a 3D convention; a 2D client should derive 4-way facing from `direction_world`. |
| Claim / release | `POST /control/claim` (target_kind, target_id, controller_id), `/control/release`, `/control/incarnate` | 5482 / 5545 / 5527 | Returns `world_epoch`, `possession_epoch`, target info. |
| Movement | `POST /control/input` | 5564, handler `runtime/control_runtime.py::submit_input` 702 | Required: `protocol_version=1, world_epoch, possession_epoch, controller_id, target_kind, target_id, seq (int, strictly increasing), move{x,y}, buttons{attack,interact,sprint}`. Optional: `look_yaw/pitch, aim_world, intent_state, context, view_style`. Held-input model: server applies the latest move each tick. Queue ≤ 64; stale `seq` rejected. |
| Authoritative state | `controls[].committed_state` in `/frame` and `/human_view/window` | `commit_tick_inputs` 981 | `completed_tick, last_applied_input_seq, input_applied_seconds, position{x,y}` (unrounded floats), plus epoch/target ids. Same tick clock as `render.server_tick` (both set before `tick += 1`, `map_test.py` 4783-4795), so one timeline: `t = tick / 20`. |
| Discrete actions | `POST /control/event`, `GET /control/event_result?controller_id&event_id&world_epoch&possession_epoch` | 5577 / 5595 | Fields incl. `event, action (select/attack/talk), semantic_action, target_kind/id/name, world{x,y}, text, seq, event_id`. Result `status`: consumed/applied/rejected/expired; `reason`: hit, blocked, range, stamina, target_invalid. |
| Command results | `POST /inventory/transfer`, `/inventory/equip_main_hand` → HTTP 202 `status:"received"`; `GET /commands/{command_id}` | 5660-5681; `simulation/commands.py::CommandInbox` | Requires UUID `command_id`, protocol/world/possession/controller. Idempotent retry with same id/payload. Statuses: received → applied/rejected, with `applied_tick`, `event_id`. `/inventory/spend` and `/inventory/spawn_storage_case` (5681, 5695) are not yet queue-routed (rebaseline §8). |
| Talk / inventory | `GET /talk/state`, `/inventory/focus`, `/inventory/owner/{kind}/{id}`, `/inventory/container/{id}` | 5601-5660 | Feeds panels. |
| Resident record | `GET /resident/{human_id}` | 5773 | Profile/status for dialogue UI. |
| Spatial contract | in `/bootstrap` and `/human_view/window` only | `systems/movement/spatial.py::world_contract` | `version, revision (hash of walls), world_epoch, units_per_meter=1.0, actor_radius, bounds[minx,miny,maxx,maxy], walk_speed, sprint_multiplier, boxes[{id,min,max,height}]`. Walls change at runtime (construction/destruction): there is no push; a client that needs it re-fetches and compares `revision`. 2D ignores `height`/`surface_id`. |
| Time/timing | `GET /status` | 5252 | `timing` from `simulation/scheduler.py::FixedStepScheduler.status()` (20 Hz, time_scale). |

Not present for 2D (gaps): map `revision` in bootstrap; a lightweight "actors since tick" endpoint without chunk work; a reconnect/resync route (client must call `/session`, `/bootstrap`, re-claim; possession neutralizes after 0.75 s without accepted input and releases after 5 s).

## 3. Where should the 2D Godot project live?

**Recommendation: new `godot_client_2d/` with its own `project.godot`.**

| | New `godot_client_2d/` | Inside `godot_client/` |
| --- | --- | --- |
| Freeze of 3D (rebaseline §1) | Clean; legacy tree and its tests stay as-is on the snapshot branch | Every 2D change edits a project whose 3D code is meant to be frozen; deleting dead files (`ground_player_motor`, etc.) breaks 3D tests |
| Startup/import cost | Small project: no `.godot` of 3.4 GB, no 407 MB humanizer addon, no 1.25 GB `assets/third_party`, no `HumanizerGlobal`/MCP autoloads | `.godot` cache is 3,458 MB; autoloads and three editor plugins load on every 2D run, including headless tests |
| Test launch | Same command pattern, `--path godot_client_2d` | Same project; 3D tests keep sitting beside 2D ones |
| Shared code | Must copy `launch_profile.gd`, `session_menu.gd`, `spatial_contract.gd`, transport. Drift risk is small (four files) and `spatial_parity.gd` guards the one contract that must not drift | Direct `preload` of `app/*` |
| Assets | `myassets/` is outside any Godot project root, so it cannot be imported by `res://`. Either add an import/copy step from `myassets` (manifest-driven) into `godot_client_2d/assets/`, or make `myassets` a subfolder of the new project. Decide with the art pipeline | Same problem (project root is `godot_client/`) |
| Git | New tracked folder, easy to review | Mixed diffs in a folder that already has 142 tracked screenshots |

Risk of the new folder: two copies of `_request_json`. Mitigate by making the 2D transport a single `eden_client.gd` and not copying the 3D one.

## 4. Interpolated server-authoritative movement: what the client must do

Rule: the client never moves a character by its own physics; it renders the past.

1. **Send input** (`/control/input`) on change **and** as a ≥ 4 Hz heartbeat while a key is held, since the server neutralizes after 0.75 s without accepted input. Monotonic `seq`; cap in-flight requests (3D uses 8); on a `{"ok":false}` reply stop and re-sync, no history to reject.
2. **Poll state** from one source: `/frame` (5 Hz base, per-tick while input flows). `/frame` lacks `spatial`, which is fine because there is no local collision.
3. **One timeline for all actors:** `t = tick / 20`. Controlled actor: `controls[].committed_state{completed_tick, position}` (gated by `ControlReplica.accept`). Others: `render{server_tick, server_time}` with `x,y` from the same payload (rounded to 0.1, see headline 4).
4. **Snapshot buffer per actor** (`snapshot_buffer.gd`, extracted from 3D): append by tick, dedupe same tick, drop out-of-order, trim to about 0.75 s; render at `latest_server_time − delay` with the 3D defaults as a start (delay 0.12 s, extrapolation ≤ 0.10 s, hard-snap when the gap exceeds a threshold, e.g. teleports/respawn). At 16-20 Hz polling with 20 Hz ticks, a 100-150 ms delay is the expected floor; this is the one added latency the player feels. **Unverified:** the right delay needs measurement.
5. **Reset rules:** clear buffers on world-epoch change, possession-epoch change, target change, and `despawned[]`; reject buffers from the old epoch (3D `_refresh_control_state` does this).
6. **Facing/animation from server data:** direction from `render.direction_world`/`velocity_world`, state from `locomotion` and `action`/`action_started_tick`. Do not use `facing_yaw`.
7. **Camera:** `Camera2D` follows the interpolated position (zoom integer, pixel snap); no obstruction logic.
8. **Reconnect:** on 401 or `world_epoch` change from `/bootstrap`, drop all buffers, return to the session menu or re-claim.
9. **Coordinates:** convert backend units → pixels in one place (`WORLD_TO_PX`); keep backend units everywhere else.

### Dead code once this lands (all 3D side)
`movement_history.gd`, `ground_player_motor.gd`, `player_presentation.gd`, `camera_obstruction.gd`, `character_animation_graph.gd` and their five validation tests; in `human_mode_3d.gd` the whole prediction chain (`_update_gameplay_player_motor`, `_update_controlled_actor_prediction`, motor/reconcile/replay in `_refresh_control_state`, `pending_control_requests` bookkeeping). On the backend: `input_applied_seconds` / `last_applied_input_seq` in `committed_state` and `session["active_input_ticks"]` become unnecessary for 2D (harmless; removing them would break `control_replica_validation` for the frozen 3D client, so leave them).

## 5. Part 2 — Snapshot readiness (`legacy-3d-0912`)

Read-only commands only (`status`, `ls-files`, `check-ignore`, `add -n`, `du`, `diff --stat`). HEAD is `88e4882 base0820`, 2026-08-20. `.git` is 235 MB; 10,796 files are tracked (including 9,922 under `game_frontend/node_modules`, already committed before this work).

### 5.1 State
* **Modified tracked: 24 files, 1.06 MB total** (plus 1 deleted). Backend: `map_test.py`, `control_runtime.py`, `resident_store.py`, `combat/resolver.py`, `state_memoryrag.py`, `initial_map_design.py`, `initial_test.py`. Godot: `human_mode_3d.gd`, `human_visual_qa.gd`, `incarnation_human.gd`, `main.gd`, `visual_qa_controller.json`. Frontend: `src/game/protocol/api.ts`, `tsconfig.tsbuildinfo`, `dist/index.html`, and deletion of `dist/assets/index-DRD6_zDH.js`. Docs: `tools/human_mode_visual_qa.md`. **Runtime data churn:** `Data_Storage/MemoryRAG/memory_graph.pkl`, `LightRAG/state_lightrag.py`, `ResidentAgents/h_000001..4.json` (about +1,715/−247 lines).
* **Untracked: 324 files, 130.9 MB** at first look; a later dry run showed 364 adds because session 1006implementation added `at_the_beginning/world_map/`, `tests/test_world_map.py`, `tools/validate_map.py` meanwhile (2D work, not legacy).
  * `game_frontend/dist/`: 117 files, **112.7 MB** (texture copies under `dist/models/`, plus a new hashed `index-RPIoHXmD.js`).
  * `godot_client/` root screenshots + `.import` sidecars: 65 files (about 12 MB); 142 similar PNGs are already tracked.
  * `godot_client/scenes/characters/generated/`: 5 files, 4.6 MB (`FemalePeasant*`).
  * Source worth keeping: `at_the_beginning/{api,persistence,simulation}/`, `launch_config.py`, `systems/movement/spatial.py`, `godot_client/scripts/app/`, `godot_client/tests/`, `tests/` (12 test files + fixtures), `tools/*.py|md`, `../archive/implementation_0905.md`, `1006*.md`, `../archive/CODEX_IMPLEMENTATION_GOAL.md`, `../archive/IMPLEMENTATION_PROGRESS.md`, `../archive/ENGINEERING_REVIEW.md`, `../designs/implementation_1006_2d_rebaseline.md`, this file.
  * 2D prototype material: `myassets/` (49 files, about 5 MB) and `2D1006newstart/` (19 files, about 3 MB; has its own `.gitignore` that appears to keep `game*.log`).

### 5.2 What `.gitignore` excludes today
`.tmp/`, `.runtime/`, `.venv/`, `env/`, `logs/`, `*.jsonl`, `*.db`, `godot_client/.godot/` (3.4 GB), the six top-level asset packs under `godot_client/` (including Fantasy Props MegaKit, 169 MB), `godot_client/assets/third_party/{…}` (1.25 GB incl. blend, medieval_castle), `godot_client/assets/mixamo/raw/`, `godot_client/animal/`, `godot_client/addons/humanizer/` (407 MB), `third_party_archives/`, `game_frontend/assets/`. The uncommitted `.gitignore` edit replaces a broken Windows-path line with `game_frontend/assets/` and adds `.runtime/`.
**Not ignored:** `game_frontend/node_modules` (already tracked, 264 MB on disk), `game_frontend/dist` (109 MB), `godot_client/addons/funplay_mcp` (tracked, 1 MB), generated characters, `myassets/`, root screenshots.

### 5.3 Would a naive `git add -A` pull in large assets?
`git add -n -A` lists 363 adds + 1 remove and **does not include** the Fantasy Props MegaKit, other MegaKits, humanizer addon, `.godot`, `.tmp`, `.runtime`, mixamo raw, animal, or `node_modules` (all ignored or already tracked and unchanged). What it **does** pull: `game_frontend/dist` (**≈113 MB**, 119 entries), 65 screenshot/import files in `godot_client/`, 5 generated character files (4.6 MB), runtime-mutated `Data_Storage` files, plus the 2D prototype folders (`myassets`, `2D1006newstart`) and the other session's new `world_map` files. So the commit would grow `.git` by roughly 130 MB uncompressed, not gigabytes, but most of it is rebuildable `dist` output.

### 5.3a Recommended pathspecs and commit grouping (branch `legacy-3d-0912`, then tag)
Do not stage until the user confirms. Suggested order:

1. **Backend + protocol work** — `git add at_the_beginning/{map_test.py,initial_map_design.py,initial_test.py,launch_config.py,api,persistence,simulation,runtime,systems} tests tools/*.md tools/generate_spatial_cases.py tools/measure_simulation.py`
   *Exclude* `tests/test_world_map.py`, `tools/validate_map.py`, `at_the_beginning/world_map/` (belong to the 2D loader work).
2. **3D Godot client** — `git add godot_client/scripts godot_client/tests godot_client/scenes godot_client/visual_qa_controller.json` (this takes the 4.6 MB generated characters; use `:!godot_client/scenes/characters/generated` to drop them if unwanted).
3. **Frontend source only** — `git add game_frontend/src game_frontend/tsconfig.tsbuildinfo`; for `dist`, either skip the new 112 MB (`:!game_frontend/dist/models`) or add `dist/index.html` and the new hashed JS only. Recommend excluding `dist/models/` (about 105 MB of texture copies derived from ignored packs).
4. **Docs/plans** — `git add 1006*.md CODEX_IMPLEMENTATION_GOAL.md IMPLEMENTATION_PROGRESS.md ENGINEERING_REVIEW.md implementation_0905.md implementation_1006_2d_rebaseline.md 1006_godot2d_port_audit.md .gitignore`
5. **Runtime data (separate, droppable)** — `git add Data_Storage` (pickled memory graph and resident JSON; not source; consider leaving out or committing alone).
6. **Screenshots (optional, separate)** — `git add godot_client/human_*.png godot_client/human_*.png.import` (about 12 MB; 142 are already tracked, so consistency argues for including them but they are evidence, not code).
7. **2D prototype (separate commit or leave for the 2D branch)** — `myassets 2D1006newstart` (8 MB). Not part of "legacy 3D"; commit to the 2D branch instead.

Notes: git warns about LF→CRLF on several files (autocrlf); expect line-ending noise in the diff. `tmp_human_runtime_test*`, `tmp_planning_scaffold_test`, `tmp_reasoning_queue_test` are empty or already tracked and add nothing. Consider tagging `legacy-3d-0912` after the commit, per the rebaseline.

## 6. Unverified / not done
* No Godot or Python test was run; no backend was started.
* Delay/extrapolation values for interpolation (§4) are carried from the 3D defaults, not measured.
* Exact `list_saves` fields beyond `save_id`, `name`, `saved_at` come from the manifest's newest generation; `tick` is used by the menu so it is present.
* Whether `2D1006newstart/.gitignore` excludes its `*.log` files was inferred from the dry-run listing (logs absent), not read.
* The `committed_state` vs `render.server_tick` same-tick claim comes from reading the step order (4783-4795); **unverified** at runtime.
* Sizes are on-disk, not compressed git sizes.
