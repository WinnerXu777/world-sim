# Unit-scale constants audit and per-map actor radius — 2026-10-06

Read-only audit by session 1006implementation2 for C-008 in `1006_communication_scratchpad.md`. **Agreed values evaluated here:** 48 px tiles, 8 backend units per tile (6 px/unit), walk 20 u/s, sprint 30 u/s, per-map `actor_radius` **2.4 u (14.4 px)** for 2D maps; legacy maps and the frozen 3D client keep 0.35. (The earlier "2.4–3" range was narrowed to 2.4; §§5-8 are the concrete decisions, §§1-4 are the supporting survey.)

**What was executed:** nothing in the repo (no tests, backend or Godot). The only code I ran was a throw-away Python script in the session scratchpad that imports `systems/movement/spatial.slide` (pure function) to measure gap behavior for §6; it wrote nothing to the repo. Everything else is from reading source; speeds in particular are derived, not measured. Conversions used below: tiles = units / 8, px = units × 6, per-second = per-tick × 20 (`TICK_RATE_HZ`, `genesis_config.py:55`).

## 0. Answers in brief

1. **A per-map radius is feasible without changing legacy defaults**, and it is a small change, because `spatial.slide` already reads the radius from the contract dict (`systems/movement/spatial.py:62-76`). Only `world_contract` hard-codes it (`spatial.py:6`, `:50`). Radius alone is not enough: `world_contract` also takes **boxes** from the entity tensor and **bounds** from `genesis_config`, so a 2D map's authored walls and size need the same override (§1.3).
2. **Do not put the radius in `persistence/world_snapshot.py::ENGINE_FIELDS`.** `validate()` requires `set(payload["engine"]) == set(ENGINE_FIELDS)` (`world_snapshot.py:46`), so adding a field makes every existing save fail with "World state schema mismatch". Derive the radius from `engine._map_name` (already persisted) through a registry instead (§4, E1-E2).
3. **Most "same units as walk speed" constants are not wrong at 8 u/tile; the real mismatches are NPC/animal speeds, which are 2–10× the player's walk speed, the 30-unit inventory reach that ignores walls, and `BUILD_RADIUS` (70 u = 8.75 tiles).** Hunger/thirst/stamina are per tick, not per distance, so they do not depend on the unit scale (§2).
4. **0.1-unit rounding (0.6 px) is fine for interpolation.** It is applied in `map_test.py:4342-4343`, `4392-4393`, `4425-4426`; the controlled player's `committed_state` is unrounded (§3).

## 1. Actor radius: every place it is used or implied

### 1.1 Production code
| Location | What | Notes |
| --- | --- | --- |
| `systems/movement/spatial.py:6` `RADIUS = 0.35` | the only definition | Imported by `world_map/validate.py:18` (`default_actor_radius`) — another session's file, do not touch. |
| `spatial.py:50` `world_contract(engine)` | exports `"actor_radius": RADIUS` in `/bootstrap` (`map_test.py:5198`), `/human_view/window` (`map_test.py:917`) and the per-tick step (`map_test.py:4723`) | **The single injection point.** All three call sites go through this function. |
| `spatial.py:62-76` `slide(start, desired, contract)` | `radius = contract["actor_radius"]`; inflates every wall box by `radius` (square footprint), clamps to `[bounds+radius, bounds-radius]` | Already per-contract. No code change. |
| `map_test.py:4772-4781` end-of-step reconcile | `spatial_slide(start, desired, spatial)` for **every** human (players and NPCs), using the contract computed once at step start (`4723`) | NPCs get the same radius as the player. **Animals are not slid at all** (`animal_instinct_move`, `instincts_and_tools.py:1648-1720`, only clamps to `MAP_WIDTH/HEIGHT`), so animals walk through walls today. |
| `systems/combat/resolver.py:99, 128` | `walls = wall_boxes(m_tensor)`, `segment_blocked(start, end, walls)` | **Does not use the radius.** Line-of-attack is tested against raw (uninflated) wall boxes, center to center. Unaffected by a larger radius, but it reads boxes from the tensor, not from the contract (see §1.3). |
| `systems/combat/queries.py:12-31` | `math.hypot` center-to-center distance, no radius subtraction | Attack range 14 u is center-to-center; with r = 2.4 two touching actors are 4.8 u apart, leaving 9.2 u of reach beyond contact. Fine. |
| `simulation/inventory_commands.py:44` | `math.hypot(...) > 30` → `container_out_of_reach` | Center-to-center, no wall check, no radius. Hard-coded literal 30. |
| `godot_client/scripts/app/spatial_contract.gd:8` | `radius = float(contract["actor_radius"])` | Already reads the contract; no hard-coded 0.35. `ground_player_motor.gd` and the 3D scripts also take it from the contract (my grep of `human_mode_3d.gd`/`incarnation_human.gd`/`main.gd` for `0.35`/`actor_radius` found only unrelated timers/lerp weights). |
| `game_frontend/src` | no `actor_radius` or collision use found | |

No other hard-coded 0.35 is a radius. Other `0.35` hits are unrelated: `SALVAGE_RETURN_FRACTION` (`genesis_config.py:555`), relationship weight (`map_test.py:4065`), signal default (`control_runtime.py:341`), map-generation ranges (`initial_map_design.py:174-175,323,400`), `instincts_and_tools.py:2814,2823`.

### 1.2 Tests and tools that bake in 0.35 (default must stay 0.35 for these to keep passing)
| Location | Dependence |
| --- | --- |
| `tests/test_spatial_contract.py:29` (`"actor_radius": .35` in a hand-built contract), `:32` (21.35), `:34` ((.35,.35)), `:51` (`wall["min"][1]-.35+.0001` against the real engine contract) | Line 51 is the only one that goes through `world_contract(engine)`; it relies on the default staying 0.35. |
| `tests/test_control_protocol.py:100`-area and `:241` (`wall["min"][1] - .35 + .0001`); `:234`, combat tests use offsets `.4`/`.5` from a wall | Rely on default radius < 0.4 (actor not embedded). |
| `tests/test_world_map.py:20` (`RADIUS = 0.35`), `:45-65`, `:193-199`, `:289-296` | Other session's tests; `test_converted_contract_blocks_slide_and_default_radius_matches_spatial` asserts `default_actor_radius() == spatial.RADIUS`. Passes as long as the constant `RADIUS` keeps its value. |
| `tools/generate_spatial_cases.py:12` (`"actor_radius": .35`) → `.tmp/implementation_0905/spatial_cases.json` → `godot_client/tests/spatial_parity.gd` | Fixture only. Parity at another radius is **not covered** today (§4, E7). |
| `tests/test_combat_walls.py` | Uses `wall_boxes`/`segment_blocked` only; radius-independent. |

### 1.3 What else `world_contract` takes from global state (needed for a real 2D map)
* **Boxes** (`spatial.py:9-22`): derived from `M_WALL` rows of `m_tensor` as `x ± max(SCALE, 2.0)`, `y ± 0.6` — **always horizontal, 1.2 units thick**. The authored map's walls (`world_map/spatial_bridge.py:to_wall_boxes`) are arbitrary axis-aligned rectangles. They cannot be expressed as tensor `M_WALL` rows, so a 2D map must supply boxes to the contract directly. `to_movement_contract(world_map, actor_radius)` returns only `{actor_radius, bounds, boxes}` (the subset `slide` reads), not the full contract (`version`, `revision`, `world_epoch`, `walk_speed`, `sprint_multiplier`, `units_per_meter`, `surface_id`, `height`), and `slide` in Godot requires `version == 1` (`spatial_contract.gd:5`). It should be merged into `world_contract`, not replace it.
* **Bounds** (`spatial.py:50`): `[0, 0, cfg.MAP_WIDTH, cfg.MAP_HEIGHT]` = 1200×900 units (150×112.5 tiles at 8 u/tile). A smaller 2D map needs its own bounds; humans are bounded by `slide`, but the tensor clamps (`instincts_and_tools.py:929-930, 1488-1489, 1712-1713` for animals/flee; `map_test.py:3237-3238`) and ~98 other `MAP_WIDTH/MAP_HEIGHT` references use the global. A 2D map that fits inside 1200×900 can ignore this for humans.
* **Revision** (`spatial.py:46-48`): sha256 of the box list only. Radius is not in the hash. If the radius becomes variable, include it in the hash **only when non-default** so legacy revisions are unchanged.
* **Combat walls** (`resolver.py:99`): must read the same box list, or 2D walls would not block attacks. It has no engine reference; add an optional `walls=` parameter whose default is `wall_boxes(m_tensor)`.

### 1.4 Smallest change that works
A static registry `MAP_CONTRACTS: dict[map_name, {"actor_radius", "bounds", "boxes"}]` (new module, e.g. `systems/movement/map_contract.py`) and, in `world_contract`, one lookup on `engine._map_name`:
```python
override = MAP_CONTRACTS.get(engine._map_name)   # None for every legacy map
radius   = override["actor_radius"] if override else RADIUS
```
then merge the override's `bounds`/`boxes` over the tensor-derived ones. No change to `Engine`, `ENGINE_FIELDS`, saves, `slide`, the Godot `slide`, or any legacy map. The 3D client would simply receive `actor_radius` from the contract as it does now. The 2D map loader registers its map under its name when loaded (or `create_genesis` does for its map).

## 2. Distance-based constants

Rule of thumb for the verdict column: **OK** = sensible at 8 u/tile and 6 px/u; **LARGE/SMALL/FAST/SLOW** = flagged. "Used where" is the primary reference.

### 2.1 Speeds (per tick × 20 = per second)
| Constant | Value | Location | Tiles / px | Verdict |
| --- | --- | --- | --- | --- |
| Player walk (`MOVE_STEP`) | 1.0 u/tick = **20 u/s** | `genesis_config.py:66`; contract `spatial.py:51` | 2.5 t/s, 120 px/s | OK |
| Sprint multiplier | ×1.5 = 30 u/s | `spatial.py:51`, `manual.py:44` default | 3.75 t/s, 180 px/s | OK |
| NPC random walk noise | uniform ±1.0 u/tick **per axis** | `instincts_and_tools.py:1436` | ±120 px/s per axis, zero-mean | **JITTER**: at 20 Hz an NPC will vibrate visibly; needs smoothing or a different NPC mover for 2D |
| Schedule nav bias | 0.42–0.88 u/tick (`ROUTINE_WEIGHT`) | `systems/schedule/navigation.py:67-79` | 8–18 u/s, 1–2.2 t/s | OK (but never "arrives", see 2.3) |
| Survival nav weight | 7.0 × (0.3–1.6), safe-seek 8.5; hazard flee 10.0 × up to 2.0 per tick | `genesis_config.py:495-496`; `systems/survival/navigation.py:127-155` | up to 10–20 u/tick = **200–400 u/s = 25–50 t/s = 1,200–2,400 px/s** | **FAST** (teleport-like for a hungry/thirsty/threatened NPC). Sums with noise; no displacement cap anywhere. |
| Social nav weight | 2.5 (crowd repel ×1.5) | `genesis_config.py:497`; `systems/social/grouping.py:88,95` | 50–75 u/s, 6–9 t/s | **FAST** (2.5–3.75× player walk) |
| Flee repulsion | `MOVE_STEP × 3.0` = 60 u/s; human_runtime `MOVE_STEP × (1.8–3+caution)` | `instincts_and_tools.py:929`; `runtime/human_runtime.py:649-728`; `talk_runtime.py:636` | 7.5 t/s, 360 px/s | FAST for walking NPCs, borderline OK for a flee animation |
| Baseline gather step | 2.4 u/tick = 48 u/s | `map_test.py:347` (used `1744,1766,1801,3587`) | 6 t/s, 288 px/s | **FAST** (2.4× player) |
| Animal steps | sheep 2.0, deer 3.5, tiger 4.0, wolf 3.5, fish 1.5 u/tick, random ±step per axis; predators add `+step` toward prey (up to ~8 u/tick for tiger) | `genesis_config.py:394-400`; `instincts_and_tools.py:1648-1720` | 30–160 u/s, 4–20 t/s, 180–960 px/s | **FAST and jittery**; not collision-checked against walls |

Summary: the player at 20 u/s is slow relative to every autonomous mover. For P3 ("NPCs move between anchors without teleporting") autonomous humans need either a per-tick displacement cap or a dedicated anchor mover. The existing end-of-step loop (`map_test.py:4772-4781`) already has each human's start and resolved positions, so a per-map cap (e.g. 1.5 × `MOVE_STEP` = sprint speed) fits there with no effect on legacy if defaulted off. **Unverified** at runtime: I did not measure actual NPC speeds.

### 2.2 Ranges and reaches (all center-to-center unless noted)
| Constant | Value | Location | Tiles / px | Verdict |
| --- | --- | --- | --- | --- |
| Actor radius (proposed 2D) | 0.35 → 2.4 | `spatial.py:6` | 0.044 → 0.3 t; 2.1 → 14.4 px half-width (hitbox 28.8 px wide) | 2.4 OK; 3.0 gives a 36 px (0.75-tile) hitbox, too fat for 1-tile doors (see 2.4) |
| Attack range | 14.0 | `genesis_config.py:476`; `combat/queries.py`; `map_test.py:3165` | 1.75 t, 84 px | OK |
| Retreat distance | `max(ATTACK_RANGE × 3.4, 18)` = 47.6 | `systems/tasks/families/combat.py:30` | 6 t, 285 px | OK |
| Inventory transfer reach | 30 | `simulation/inventory_commands.py:44` (literal) | 3.75 t, 180 px | **LARGE, and ignores walls**: reachable through a wall/room. Make it a per-map value (suggest ≈ 16, 2 tiles) and optionally test `segment_blocked`. |
| Storage-case visual radius | `scale=14.0`; nearby-container search radius 72 | `map_test.py:1147`; `_nearby_accessible_storage_records` `map_test.py:~960` | 1.75 t radius (3.5 t wide); 9 t search | **LARGE** as a prop. 2D maps author containers in the map file; the engine-side `_spawn_storage_case_at` should not be used there. |
| Direct talk hearing / ambient / NPC chat | 14 / 24 / 16 (schema 14 / 24 / 18) | `runtime/talk_runtime.py:63-65`; `systems/talk/schema.py:23-25` | 1.75 / 3 / 2–2.25 t | OK. Note the two files disagree on NPC chat (16 vs 18). |
| TTS audible distances | 16 / 18 / 12 | `systems/talk/effects.py:32-34` | 2 / 2.25 / 1.5 t | OK |
| Social approach / follow / mate | 8 / 10 / 8 | `systems/tasks/families/social.py:52-53`; `genesis_config.py:466` | 1 / 1.25 / 1 t | OK for r = 2.4 (contact at 4.8 u); would be tight for a 3.0 radius with walls between |
| Threat proximity / infection / crowding | 15 / 10 / 18 (limit 4) | `genesis_config.py:467,504,499` | 1.9 / 1.25 / 2.25 t | OK |
| Drink proximity | 24 | `genesis_config.py:528` | 3 t | OK |
| Build radius | **70** | `genesis_config.py:546`; `map_test.py:1743,1800,2947,3009` | 8.75 t, 420 px | **LARGE** (can build/repair from nearly across a village). Build arrival radius is 12 (`families/construction.py:22`, 1.5 t) — inconsistent with 70. |
| Gather radius | 24 | `map_test.py:346` | 3 t | OK |
| Resolver search radii | help 72, support 96, shelter 132, farm 144, settlement 196, resource/place 220–240 | `map_test.py:1288,1332,1548-1549,1643,3577,3689-3709` | 9–30 t | LARGE vs a ~40×30-tile map: "nearest within 220" covers the whole map. Not wrong, but residents will see everything. |
| Survival / migration / hazard / predator scan | 220 / 480 / 120 / 90 | `genesis_config.py:488-491` | 27.5 / 60 / 15 / 11 t | Same: larger than a small village. Predator prey-detection is `ANIMAL_PREDATOR_RANGE × 3` = 60 (`genesis_config.py:406`, 7.5 t). |
| Tribe cohesion | 70 | `genesis_config.py:498` | 8.75 t | OK |
| Animal mate radius | 12 | `genesis_config.py:409` | 1.5 t | OK |
| Fire spread / volcano / storm | 80 / 60–160 / 50 | `genesis_config.py:428,457-458,452` | 10 / 7.5–20 / 6 t | Not relevant to the starter village; sized for the 1200×900 world |
| Chunk size / default 3D view | 240 / 180×130 | `map_test.py:344-345`; `map_test.py:782` | 30 t / ~22×16 t | Only the 3D `/human_view/window`; a 2D client does not need chunks |

### 2.3 Structures, spawns, arrival
| Constant | Value | Location | Tiles / px | Verdict |
| --- | --- | --- | --- | --- |
| Entity wall box (tensor-derived) | half-length `max(SCALE, 2.0)`, half-thickness 0.6 (1.2 thick), horizontal only | `spatial.py:19-20` | thickness 0.15 t, 7.2 px (+2r after inflation: 1.9 u / 11 px at r = 0.35; **6.0 u / 36 px at r = 2.4**) | **SMALL** as a visual; horizontal-only is a legacy limitation. Authored 2D walls must come from the map file. |
| Runtime-built walls | half-length `max(18, scale or 30)`, polygon thickness `max(8, scale×0.35)` | `systems/map/create.py:665-690` | ≥ 4.5 t long, ≥ 1 t thick polygon | **MISMATCH**: the collision box is 1.2 u thick and axis-aligned, the polygon may be 8 u thick and rotated. Pre-existing; not a 2D-map concern unless players build walls. |
| Starter villager spawns | center ± (6–18) of `MAP_WIDTH/2, MAP_HEIGHT/2` | `map_test.py:5059-5064` | ±2 t | **Wrong source for 2D**: hard-coded to the global map center; a 2D map must spawn at anchors that pass `is_standable` with the map radius, else a spawn inside an inflated wall box is frozen (`spatial.py:68-69` "embedded" rule). |
| Incarnation spawn jitter | ±12 / ±10, edge margin 20 | `map_test.py:4866-4870` | 1.5 / 1.25 t, 2.5 t | Same: needs anchor-based spawn for 2D |
| Adam/Eve offset | +5 | `map_test.py:5067-5068` | 0.6 t | Legacy only |
| Anchor arrival tolerance | **none**: schedule steering points toward the nearest entity within 220 and never stops (`schedule/navigation.py:170-190`). Per-task arrivals exist (build 12, social 8, follow 10, gather 24) | listed above | 1–3 t | **Missing for anchors.** A new anchor mover needs a tolerance ≥ one step (1 u at walk speed; suggest 2 u ≈ 12 px) or it will oscillate. |
| Input/possession timeouts | 0.75 s / 5 s | `control_runtime.py:44-45` | wall-clock, not distance | Not unit-dependent |

### 2.4 Per-tick (not per-distance) rates — unaffected by unit scale
`HUNGER_TICK_RATE` 0.05, `THIRST_TICK_RATE` 0.07 (`genesis_config.py:469-470`, applied per tick in `systems/survival/hunger.py:33`, `thirst.py:46`), stamina `+STAMINA_RECOVER_RATE − STAMINA_DRAIN_MOVE` = +1.3 per tick unconditionally (`instincts_and_tools.py:1085`; "drain move" is not tied to movement), `TICKS_PER_YEAR` 600 (`genesis_config.py:54`, 30 s of wall time per game year). These depend on tick rate, not distance, so C-008's concern that stamina/hunger rates "depend on distance per tick" is **not borne out** by the code I read. (They may still need a separate review for pacing, which is outside this audit; **unverified** by running.)

Door width check: passable center-path width through a gap `g` between wall boxes is `g − 2r`. At r = 2.4, a 1-tile door (8 u) leaves a 3.2 u (19 px) corridor for the actor's center; at r = 3.0 it leaves 2.0 u (12 px). Recommend 1.5–2-tile doorways, or r ≈ 2.0–2.4. The map validator already checks gaps against `2r` (`tests/test_world_map.py:211`), which is the right place to enforce it.

## 3. Position rounding (0.1 unit)

| Where | What |
| --- | --- |
| `map_test.py:4342-4343` `_export_human` | `x`, `y` rounded to 1 decimal |
| `map_test.py:4392-4393` `_export_animal` | same |
| `map_test.py:4425-4426` `_export_map_entity` anchor; `4429-4431` shape `r`/`points` | same |
| `map_test.py:4304` `_coerce_value` | schema state values to 1 decimal |
| `map_test.py:4991-4992` | incarnation spawn result |
| `map_test.py:4237-4240, 4277-4280` | render hints: velocity 3 decimals, direction 4 decimals (computed from unrounded tensors, so not degraded) |
| `control_runtime.py:1008` `committed_state.position` | **unrounded floats** |

At 6 px/unit, 0.1 u = 0.6 px, so the maximum quantization error is 0.3 px (0.9 px at 3× zoom). Walk speed is 6 px per tick, so 0.3 px is 5% of one step: invisible in interpolation, and below the 1 px of snap if the client rounds to whole pixels. **Acceptable; no backend change needed.** Two cautions: (1) use `committed_state` for the player's own sprite and the `/frame` rounded position only for others, so one actor never mixes sources; (2) at ≥ 4× integer zoom the error would reach ~1.2 px, still sub-sprite; if that matters, change `round(…, 1)` to `round(…, 2)` in three places — but check that no test asserts the exact rounded string (not verified). NPC jitter (§2.1) is a far larger visual error than rounding.

## 4. Recommendation and backend edits (safe order)

**Recommendation:** adopt the per-map contract override, keyed by map name, with default behaviour untouched. Set the 2D radius to **2.4** (hitbox ≈ 29 px, 0.6 tile) rather than 3.0 unless doors are authored ≥ 1.5 tiles. Keep 8 u/tile and 20 u/s. Treat NPC speed, inventory reach, build radius and spawn/arrival as separate per-map or per-system changes, not as part of the radius change.

Each step is independent and leaves legacy behaviour byte-identical.

| # | Edit | Proof (test to add or run) |
| --- | --- | --- |
| E1 | New `systems/movement/map_contract.py` with `MAP_CONTRACTS = {}` and `register_map_contract(name, actor_radius, bounds, boxes)`. No callers yet. | New `tests/test_map_contract.py`: registry empty by default; registering and unregistering does not leak between tests. |
| E2 | `world_contract(engine)` (`spatial.py:45-52`): look up `engine._map_name`; if registered, override `actor_radius`, `bounds`, and merge map boxes; add radius to the `revision` hash only when non-default. Do **not** touch `ENGINE_FIELDS`. | (a) Golden test: for every legacy map name the contract equals the pre-change contract exactly (capture the dict, including `revision`, before editing). (b) With a registered 2D map, `slide` stops at `wall.min − 2.4` and still slides tangentially. (c) Re-run `tests/test_spatial_contract.py`, `test_control_protocol.py`, `test_world_map.py` unchanged. |
| E3 | `resolver.py:99`: `resolve_human_attack_intents(..., walls=None)`; default `wall_boxes(m_tensor)`; engine passes the contract boxes when a map override exists (callers `map_test.py:2908, 3132`). | Extend `tests/test_combat_walls.py`: an authored wall box blocks an attack; default call is unchanged. |
| E4 | Snapshot compatibility check (no code change): save/restore a 2D-map world and confirm the radius is re-derived from `_map_name` and an old legacy save still validates. | New case in `tests/test_checkpoints.py` / `test_session_lifecycle.py`. |
| E5 | 2D spawn: place residents at map spawn anchors (or any `is_standable` point) instead of `MAP_WIDTH/2 ± …` (`map_test.py:5059-5064`, `4866-4870`). | New test: every spawn passes `world_map.validate.is_standable` with the map radius; an embedded spawn is rejected. |
| E6 | Per-map autonomy limits, default off: displacement cap in the end-of-step loop (`map_test.py:4772-4781`) and an anchor mover with arrival tolerance ≥ 2 u. | Tests: a hungry NPC with a huge survival bias moves ≤ cap per tick on the 2D map; legacy maps keep current displacement. |
| E7 | Per-map interaction values: inventory reach (`inventory_commands.py:44`, default 30), optional wall test with `segment_blocked`, build radius. | Existing `tests/test_inventory_commands.py` unchanged; new reach tests per map. |
| E8 | Parity at the new radius: extend `tools/generate_spatial_cases.py` to emit a second fixture (contract radius 2.4, thicker box) without altering the first, and have `godot_client/tests/spatial_parity.gd` loop over both (the future 2D project copies it). | `godot --headless --path <project> --script res://tests/spatial_parity.gd` prints `SPATIAL_PARITY_PASS` for both fixtures. |

Existing tests expected to be affected by E1-E4: **none**, because they use the default radius and legacy maps. The ones that would break if the default changed are listed in §1.2.

## 5. Concrete decisions at 48 px / 8 u per tile / 6 px per u / r = 2.4 / 20–30 u/s

Legend: **keep** = no change; **change** = proposed per-map (2D) value, legacy default unchanged. "Contact" distance between two actor centers is 2r = 4.8 u (0.6 t, 28.8 px). Actors do **not** collide with each other (`slide` only tests wall boxes), so the radius is a wall hitbox only.

| Constant | Today (value → tiles → px) | Verdict at agreed scale | Proposed change |
| --- | --- | --- | --- |
| Actor radius | 0.35 → 0.04 t → 2.1 px | 0.35 is **too small** (hitbox 4 px wide on a 48 px sprite) | **2.4** per map (28.8 px hitbox, 0.6 tile) |
| Walk / sprint | 20 / 30 u/s → 2.5 / 3.75 t/s → 120 / 180 px/s | OK | keep |
| Per-tick step | 1.0 / 1.5 u → 6 / 9 px per tick | OK; tunnelling impossible (step ≪ 2r + wall) | keep |
| NPC random-walk noise | ±1.0 u/tick per axis → ±120 px/s | **too jittery** | 2D: no noise for anchor-driven residents (anchor mover instead) |
| Nav bias: schedule | 0.4–0.9 u/tick → 8–18 u/s | OK | keep |
| Nav bias: survival / hazard / social | 7–10 (×≤2) / 2.5–3.75 u/tick → up to 400 u/s | **too fast** (up to 50 t/s) | per-map displacement cap = sprint (1.5 u/tick) |
| Baseline gather step | 2.4 u/tick → 48 u/s → 288 px/s | **too fast** | cap 1.0 (walk) on 2D maps |
| Animal steps | 1.5–4 u/tick (+ chase) → 30–160 u/s | **too fast/jittery**, no wall collision | per-map: cap at sprint; add wall slide for animals if any are placed (none in the starter village plan) |
| Attack range | 14 → 1.75 t → 84 px; 9.2 u (1.15 t) beyond contact | OK | keep |
| Entity interact / work-on-target range | `max(BUILD_RADIUS, 1.5×ATTACK_RANGE)` = **70** → 8.75 t → 420 px (`map_test.py:2947, 3009`) | **too big** (the real interaction range, larger than the 30 inventory reach) | 2D: **16** (2 t, 96 px) + wall check |
| Inventory transfer reach | 30 → 3.75 t → 180 px (`inventory_commands.py:44`) | **too big**; no wall check | 2D: **16** + wall check |
| Nearby storage search (resident) | 72 → 9 t (`map_test.py` `_nearby_accessible_storage_records`) | **too big** | 2D: 24 (3 t) |
| Build radius / arrival | 70 → 8.75 t / 12 → 1.5 t | **radius too big**, arrival OK | 2D: radius 24 (3 t), arrival keep |
| Gather radius | 24 → 3 t | OK | keep |
| Talk: direct / ambient / NPC chat | 14 / 24 / 16 (schema 18) → 1.75 / 3 / 2 t | OK distances; **no wall test** | keep values; unify NPC chat to 16; optional wall test for direct and NPC chat (not ambient) |
| TTS audible | 16 / 18 / 12 | OK | keep |
| Social approach / follow / mate | 8 / 10 / 8 → ≈1 t | OK (contact is 4.8; leaves 3.2 u gap) | keep |
| Drink proximity | 24 → 3 t | OK | keep |
| Crowding / infection / threat | 18 / 10 / 15 | OK | keep |
| Scan radii (survival / migration / hazard / predator) | 220 / 480 / 120 / 90 → 27–60 t | **too big for a ~40×30-tile map** (sees everything) | per-map scale or leave if "omniscient residents" is acceptable |
| Storage-case radius (engine spawn) | `scale=14` → 1.75 t radius | **too big** (3.5 tiles wide) | do not use engine spawn on 2D maps; author footprint (e.g. 8 u box) |
| Tensor wall box | half-length `max(SCALE, 2)`, half-thickness 0.6 | n/a for 2D | authored boxes only (thickness ≥ 2 u; see §6) |
| Door / opening | planned 8 u → 1 t | passable band = 8 − 4.8 = **3.2 u (19 px, ±9.6 px)** | **keep 8 u only if** clicking/steering is the norm; use **10 u** for main doors and aisles (band 5.2 u, ±15.6 px) |
| Aisle | planned 10 u → 1.25 t | band 5.2 u (31 px) | OK |
| Map edge | center clamped to `[r, size − r]` | 2.4 u = 14 px dead band | keep |
| Spawn / anchor distance from walls | none enforced in engine | **spawn within r + wall of a box freezes the actor** (§6) | validator: every spawn/anchor ≥ `r + 1 u` from every box |
| Anchor arrival tolerance | none | n/a | 2 u (12 px) ≥ 1 step; per-task arrival radii stay |
| Hunger / thirst / stamina / timeouts | per tick or wall clock | unit-independent | keep |

## 6. Passage clearance: how `slide` behaves in 8 u doors and 10 u aisles at r = 2.4

Rule: each wall box is inflated by r on all sides and the actor center is a point, so the **passable center band through a gap `g` is `g − 4.8`**, centered on the gap. Measured by calling the real `spatial.slide` (script in the session scratchpad; wall thickness 1.2 and 8; steps 1.0 and 1.5 u/tick; **not** a repo test):

| Opening | Center band | Straight walk (no steering), lateral offset that passes | Aimed walk (steering at a point beyond the door) |
| --- | --- | --- | --- |
| 8 u door | 3.2 u (19.2 px) | passes at offsets 0, 1.0, 1.6; **blocked at 2.0, 3.2, 4.0** | passes from every tested start (offsets up to 30 u, diagonal approaches) |
| 10 u door / aisle | 5.2 u (31.2 px) | passes at 0–2.0; blocked at 3.2, 4.0 | passes from every tested start |
| 4.8 u (exact minimum) | 0 | passes **only at exactly 0 offset** | not tested beyond center |
| 4.79 u | none | blocked even at offset 0 | n/a |

* Behavior in the gap is exact, not sticky: no snagging on jambs when the center is inside the band. Wall thickness (1.2 vs 8) does not change which offsets pass, and sprint steps (1.5 u) do not tunnel.
* A straight (keyboard) approach that is outside the band stops flush against the wall at `wall edge + 2.4`; it does not funnel toward the door. A diagonal approach slides along the wall face (tangent slide), so a player who holds a diagonal key keeps sliding past the door, not into it. For WASD play on 8 u doors the lateral tolerance is **±9.6 px (≈ 0.2 tile)**; on 10 u it is ±15.6 px. That is workable but tight; 10 u (1.25 t) is the safer door width, or use r = 2.0 (band 4.0 u for an 8 u door).
* **Minimum clearance is `2r = 4.8 u` plus margin.** The exact-minimum gap works only on the center line and leaves no tolerance; the validator should require `gap ≥ 2r + 1 u` (and an anchor in a doorway must lie in the band). `tests/test_world_map.py:211` already checks gaps against `2r`.
* **Embedded actors never move.** A start strictly inside an inflated box returns the start unchanged for any desired position (`spatial.py:68-69`); measured: `slide((100, 89.0), (100, 95))` with a box whose inflated y range is 87.6–93.4 returned `(100, 89.0)`. There is no depenetration, so any spawn/anchor/teleport (portal exit anchors, god-mode spawn) inside `r` of a box permanently traps the actor. Aisle test: a start at the wrong side of the band (y = 58 in a 10 u aisle whose band is 52.4–57.6) is frozen; starts inside the band cross the aisle.
* NPCs steering with the schedule bias (`navigation.py`) point at an entity and have no path-finding, so they will press against walls and slide, not find doors. For P3 the anchor mover needs waypoints through doors.

## 7. (a) Reach and range checks: line-of-sight / wall tests

| Check | Distance test | Wall / LOS test | Reference |
| --- | --- | --- | --- |
| Attack | `target_in_range` ≤ 14 (center-to-center) | **Yes**: `segment_blocked(start, end, wall_boxes(m_tensor))` → reason `blocked` | `resolver.py:60-66, 99, 128`; receipt mapping `map_test.py:3165-3170` |
| Inventory transfer | `hypot > 30` → `container_out_of_reach` | **No** | `simulation/inventory_commands.py:44` |
| Interact / work on target (select container/structure, work) | `> max(BUILD_RADIUS 70, 1.5×14)` → `out_of_range` | **No** | `map_test.py:2947, 3009` |
| Resident access to storage | radius 72 | **No** | `map_test.py` `_nearby_accessible_storage_records` (~960), `_resident_accessible_storage_records` |
| Ambient talk, NPC chat | `AMBIENT_HEARING_RADIUS` 24, `NPC_CHAT_RADIUS` 16 | **No** | `runtime/talk_runtime.py:180, 257, 267` |
| TTS audibility | 16 / 18 / 12 | **No** | `systems/talk/effects.py:32-47` |
| Direct talk radius | `DIRECT_HEARING_RADIUS = 14` is **defined but I found no use of it** (grep of the package; only the definition lines `talk_runtime.py:63`, `schema.py:23`) | **No** | **Unverified** that a player's direct talk has no distance limit; I did not trace `drain_talk_events` end to end |

So combat is the only check that tests walls, and it tests raw boxes (no radius). **Where to add one:** a single helper in `systems/movement/spatial.py`, e.g. `line_clear(start, end, boxes, ignore_ids=())` wrapping `segment_blocked`, called with the contract boxes (so authored 2D walls are included) from: `inventory_commands.py:44` (after the distance test), `map_test.py:2947` and `:3009` (interact/work), `_nearby_accessible_storage_records`, and optionally `talk_runtime.py:257/267`. Two caveats:

1. `segment_blocked` counts contact and embedding as blocked (`tests/test_combat_walls.py` asserts it), so a chest or forge whose **footprint is itself a collision box** would block every reach to its own center. The helper must skip the target entity's own box (`ignore_ids` by box `id`) or test to the nearest point on that box's boundary.
2. An actor standing against a wall (center 2.4 u from its face) has a clear line to a target on the same side; a target on the far side of a 1.2 u wall is blocked even at 5 u. That matches the player's expectation.

Reach values should become per-map numbers read next to the radius (§8), defaulting to 30 / 70 / 72 for legacy maps.

## 8. (c) Injection point for the per-map radius (consistent with the sibling `world_map/`)

Session 1006implementation's `world_map/` already carries the radius separately: `to_movement_contract(world_map, actor_radius)` takes it as an argument and `validate.default_actor_radius()` returns `spatial.RADIUS`; it is adding an optional file-level `actor_radius`. I did not edit any of it. The backend side, smallest and safe for saves:

1. **`systems/movement/spatial.py:world_contract(engine)`** — the only place the engine contract is built (called from `/bootstrap` `map_test.py:5198`, `/human_view/window` `:917`, step `:4723`). Add a lookup keyed by `engine._map_name`; if a 2D contract is registered, override `actor_radius`, `bounds`, `boxes` (and optionally the reach values), merging into the existing dict so `version`, `revision`, `world_epoch`, `walk_speed`, `sprint_multiplier` stay. Radius enters the `revision` hash only when non-default so legacy revisions are unchanged.
2. **Registry** — new module `systems/movement/map_contract.py` (`MAP_CONTRACTS`, `register_map_contract`). The 2D map loader (or `create_genesis` for that map name) registers `world_map.actor_radius` (file value, else the agreed 2.4) and `to_wall_boxes(world_map)`.
3. **Combat wall check** — `systems/combat/resolver.py:99`: add an optional `walls=None` parameter (default `wall_boxes(m_tensor)`); the engine passes the contract boxes for registered maps (callers `map_test.py:2908`, `3132`). Same boxes everywhere: movement, combat, reach checks.
4. **Do not** touch `persistence/world_snapshot.py:ENGINE_FIELDS` (adding a field makes every existing save fail validation, `world_snapshot.py:46`); the radius is re-derived from `_map_name`, which is persisted.
5. **Parity tests** — `slide` in Python and Godot already takes the radius from the contract dict, so parity code needs no change; add a second fixture instead of changing the first: `tools/generate_spatial_cases.py` (hard-codes `.35` at line 12) emits an additional contract with `actor_radius` 2.4 and 8-unit door gaps, and `godot_client/tests/spatial_parity.gd` (and the 2D project's copy) loops over both. Run: `godot --headless --path <project> --script res://tests/spatial_parity.gd`.

**Existing tests affected by steps 1-4: none**, provided the default stays 0.35: `tests/test_spatial_contract.py:29,32,34,51`, `tests/test_control_protocol.py:241` (and the `.4`/`.5` wall offsets near `:234`), `tests/test_combat_walls.py`, and `tests/test_world_map.py:20,45-65,193-199,289-296` (those use the constant `RADIUS` or pass the radius explicitly). **New tests to add:** golden legacy contract equality including `revision`; registered map → contract radius 2.4 and `slide` stops at `wall.min − 2.4`; door-gap cases from §6 (8 u band ±1.6 passes, 4.79 u blocked, embedded start frozen); combat/interact blocked by an authored wall; reach helper ignores the target's own footprint; save/restore keeps the 2D radius via `_map_name`.

## 9. Not verified

* No repo test, backend or Godot run. "Not affected" claims are by reading. The §6 gap measurements come from calling the real `spatial.slide` in a scratchpad script on hand-built boxes; they were not run through the engine, the Godot port, or an authored map file.
* Speeds in §2.1 are derived from per-tick formulas; real NPC displacement also depends on clamping, nav-bias overlap and slide. Worth measuring with `tools/measure_simulation.py` or a short script before choosing caps.
* `round(…, 2)` safety against existing tests was not checked.
* Whether anything outside `at_the_beginning/` reads `world.tile_size` (8) as a pixel value for the 2D client was not checked; `world.tile_size` is an unrelated "px per background tile" in `/bootstrap`.
* I read `world_map/spatial_bridge.py` and `validate.py` for how they call the radius; I did not modify or review the rest of `world_map/`.
