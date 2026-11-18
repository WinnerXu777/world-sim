# Eden 2D re-baseline — October 6, 2026

Addendum to `implementation_0905.md`. That plan targeted a 3D Godot village. The project is moving to a 2D Godot client with generated assets. This document overrides the 0905 plan where they conflict and leaves the rest in force. It does not modify `implementation_0905.md`, `CODEX_IMPLEMENTATION_GOAL.md`, or `IMPLEMENTATION_PROGRESS.md`.

Companion: `1006newdesign.md` (Tier 1 decision model design).

## 1. Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Client | Godot 2D (TileMapLayer, Y-sort, AnimatedSprite2D) | Reuses the session menu, `spatial_contract.gd`, `control_replica.gd`, and transport already built |
| 3D client | Freeze as legacy; do not maintain or delete | Backend protocol tests still run against it; avoids doubling client work |
| World source of truth | One authored map file loaded by both backend and client | Assets are still being generated; a data file decouples layout from art and keeps Python collision and client visuals in agreement |
| Model timing | After Gate H, with a `DecisionProvider` seam built in F | Keeps Stage 1 model-free while making Clef a provider swap later |
| Movement networking | Server-authoritative with client interpolation; drop prediction/replay | Single-player on loopback at 20 Hz does not need it |

## 2. Snapshot before changing direction

Before any 2D work, commit the current tree to a branch and tag it (suggested: `legacy-3d-0912`). The month's backend and 3D work is untracked and uncommitted (last commit is 2026-08-20). Do not start deleting or restructuring until this exists.

## 3. What the 0905 plan keeps, changes, or drops

| 0905 item | Status |
| --- | --- |
| A (profiles, isolation, New/Continue) | Keep. Finish remaining A2/A4 items on the 2D client |
| B1–B2, B4–B5 (mutation owner, scheduler, resident writer, saves) | Keep as built |
| B3 (protocol, receipts) | Keep; stop extending it for replay |
| B6 (local session boundary) | Keep loopback binding and no debug routes in gameplay. Do not add further capability/CORS work |
| C (rig, AnimationTree, clip cache, coverage mask) | Drop for 2D. Replace with section 6 |
| D1 (shared spatial contract) | Keep and reuse. Collision is already ground-plane boxes |
| D2–D3 (physics motor, replay, visual correction) | Drop. Replace with interpolation of server snapshots |
| D4 (camera obstruction) | Drop. 2D camera follow and zoom only |
| E (village content) | Rework around the authored map file (section 4) |
| F (smith loop, residents) | Keep; promote to the first gameplay milestone after the walkable slice |
| G (god mode) | Keep; simpler in 2D (zoomed-out camera plus three powers) |
| H (release) | Keep, with lighter gates (section 7) |
| I (models, TTS) | Unchanged, after H. See `1006newdesign.md` |

## 4. The authored map file

One file defines the playable village. Format is an implementation choice (Tiled-style JSON or a small custom JSON); the requirements are:

- **Units:** declare tile size (48 px for the current `myassets` tiles) and a single backend-unit-to-pixel factor. Backend positions stay in backend units; the client converts.
- **Layers:** terrain tiles; decoration (non-colliding); building and prop footprints.
- **Collision:** wall and obstacle footprints as axis-aligned boxes, exported in the shape `systems/movement/spatial.py` already consumes (`wall_boxes`). The backend loads these; it does not infer them from art.
- **Anchors:** named door, work, talk, sleep and spawn points with stable IDs. NPC movement and player interaction use the same anchors.
- **Entities:** every usable object (chest, forge, door, resource pile) has a stable backend entity ID. Decorative props are explicitly marked noninteractive.
- **Interiors:** a doorway is a portal to a separate small map with its own file and a defined entry/exit anchor pair. No multi-level physics.
- **Versioning:** a map revision field, surfaced in bootstrap so the client can detect mismatch.

Codex's asset generation feeds this file's tile and sprite references; it does not write world state directly. The existing `initial_map_design.py` generators stay available for larger procedural maps and are not the source for the village.

Validation: a script loads the file, checks that every anchor is reachable, no anchor sits inside a collision box, IDs are unique, and referenced sprites exist.

## 5. Revised order

Replace the A→H sequence with this vertical-slice order. Each step has a short exit test; do not wait for evidence packages.

| Step | Deliverable | Exit test |
| --- | --- | --- |
| P0 | Snapshot branch; freeze 3D; confirm Godot 2D project skeleton and `myassets` import | Branch exists; 2D scene opens and shows a tile map |
| P1 | Authored map file loader (backend + client) and unit contract | Same file produces matching walls on both sides; validation script passes |
| P2 | Walkable slice: player claims a resident, moves with server-authoritative movement and interpolation, walls block | Walk the map without crossing a wall; stop and restart cleanly |
| P3 | 3 visible NPCs on schedules using existing systems | NPCs move between anchors without teleporting |
| P4 | F: smith loop with scripted dialogue and the `DecisionProvider` seam (rules provider) | Request → accept/refuse by real state → reserve → work → deliver once → remembered after reload |
| P5 | G: god camera, heal, spawn resource, weather, possession return | A power changes state and one NPC visibly reacts later |
| P6 | E: expand to 8–12 named residents, buildings, interiors, art pass | Village is traversable; usable objects map to entity IDs |
| P7 | H: onboarding, UI, save/reload, short playthrough | A 20–30 minute run completes with models disabled |

## 6. Sprites, animation, and art consistency

- Keep a one-page art bible: sprite size and pivot convention (foot pivot), direction count, palette, outline style, shadow style. Generated assets must conform to it before being used.
- Characters: use 4–5 body templates with palette swaps rather than 12 unique sprite sets. Give each named resident a distinct dialogue portrait; portraits carry identity cheaply.
- Minimum animation set per body: idle, walk (4 directions), talk (can be a portrait-only or small gesture), attack, hit, down/death. Hit, fall and death may use simple frame shifts, tint or tilt effects at first.
- Draw order: sort props and characters by foot Y; terrain first. Use nearest-neighbor filtering and integer zoom.
- Each generated asset records source, prompt/tool, and license in a manifest, matching the existing `myassets/manifest.json` practice.

## 7. Lighter gates

Keep honest evidence, but make exit criteria short and runnable:

- Prefer a single automated check (test or script) per step over recordings.
- A short screen capture is enough for visual steps; full temporal recordings are only required for the final H playthrough.
- Do not block a step on gait calibration, 1080p benchmarks or exhaustive latency matrices. Record frame and tick timing once at P7.

## 8. Backend items still worth finishing

- Domain outcome receipts for non-attack actions (crafting, trade, talk).
- Route remaining direct mutations (inventory spend/spawn, decree/god routes) through the command queue.
- Reconnect handling for the 2D client.

Do not add new protocol surface for client prediction.

## 9. Open items

- Final map file format (JSON flavor and whether to author in Tiled or Godot).
- The backend-units-to-pixels factor, once the art bible fixes sprite scale.
- Whether `game_frontend` (browser) remains a diagnostics-only viewer. Default: yes, unmaintained for parity.
