# Eden: engineering review and development direction

Reviewed 2026-09-05 against the current working tree, including uncommitted character and scene changes. This is a source review plus inspection of two existing QA screenshots; it is not a fresh runtime playtest or performance benchmark. No gameplay code or resident data was changed for this review. Existing screenshots may predate the latest edits.

## Recommendation

Keep Godot as the primary game client and Python as the authoritative simulation. Build one coherent, persistent medieval village before expanding the world. The first release target should be a 20–30 minute playable experience: walk through a village, converse with named residents, change their behavior through actions, intervene as a god, return to human form, and see the consequences survive a reload.

The repository already contains useful domain systems: stable resident identities, semantic client payloads, deterministic action validation, inventory, crafting, construction, combat, personality, schedules, goals, planning, memory, and decree orchestration. Preserve and integrate them. The current problem is that the default presentation and runtime profile do not expose those systems as a coherent game.

Treat the browser frontend and Arcade viewer as secondary diagnostic tools unless a concrete product requirement justifies maintaining feature parity. Avoid an engine migration or backend rewrite at this stage.

## Findings grounded in the repository

Paths and line numbers below refer to the reviewed working tree.

| Priority | Evidence | Effect and recommended change |
| --- | --- | --- |
| P0 | `godot_client/scripts/human_mode_3d.gd:65–66` defaults to automatic render-test startup and clean QA view. `_load_render_test_village`, around line 609, calls the testing endpoint. `at_the_beginning/map_test.py:5055` resets the world and selects `render_test`; `run_loop:4698` skips world queues, dialogue processing, and human escalation in that profile. | The normal client startup can reset the connected world and bypass the very NPC systems you want to experience. Separate New Game / Continue from explicit test fixtures. A client connection must never implicitly reset a world. Keep the full simulation enabled for gameplay. `initial_test.py` has a separate full-profile override, so behavior also depends on the launcher. |
| P0 | `human_mode_3d.gd:3389` hides all streamed chunks in clean view; `3419` hides nearby actors. Default clearance radii are 560 for chunks and 160 for actors. | Nearby world content and conversation partners can disappear by design. Remove broad radius-based hiding from gameplay. Use a camera obstruction query and localized treatment of actual occluders. |
| P0 | `human_mode_3d.gd:3521–3553` positions the “real” ground, path, and context props at the player and rotates them with `camera_yaw`; staging does the same around line 3556. | Scenery is attached to presentation rather than fixed world coordinates. This is a direct explanation for a stage-like scene and unreliable sense of traversal. Put QA dressing in the QA scene; place gameplay terrain and buildings at stable world transforms. |
| P1 | `incarnation_human.gd:494` stops, assigns, plays, and seeks to zero when switching clips; `641` can freeze external idle at frame zero. One-shots use locks and timers around `780`; retargeting, rest-pose changes, root-track removal, and gesture offsets coexist. | This is a fragile animation ownership model. Transition snaps, rigid idle, and rig-dependent poses are plausible consequences; they need fresh temporal validation. Normalize one rig and move gameplay state transitions into one AnimationTree. The arm-pose correction function around `1226` is currently disabled; do not mistake its calls for active per-frame arm correction. |
| P1 | `human_mode_3d.gd:1413` predicts movement by integrating position and blending toward server coordinates. Defaults imply 20 world units/second before sprint. It also force-resets visual child yaw. `runtime/control_runtime.py` already rejects stale input sequences. | Extend the existing sequencing into applied-input acknowledgments and replay of pending inputs. Define units, speed, facing, and collision consistently. The inspected prediction path does not use a collision-aware character motor. Do not assume changing smoothing constants resolves disagreement between simulation and presentation. |
| P1 | `map_test.py:4698–4762` executes synchronous simulation/model paths and then sleeps a full `TICK_SLEEP`. `genesis_config.py:55` targets 20 Hz. `runtime/tiny_runtime.py` and `runtime/world_runtime.py` call model handlers synchronously. | Actual tick duration is work time plus 50 ms. Slow inference or disk work can stall requests and simulation. Use deadline-based fixed-step scheduling, bounded workload, and asynchronous model jobs whose results return through a simulation-owned queue. |
| P1 | `runtime/resident_store.py:143` catches a final failed write without reporting failure; `flush_dirty:944` then discards the resident's dirty flag. | A locked file can leave an update unsaved but marked clean. The direct-overwrite fallback also weakens atomicity. Preserve dirty state on failure, report persistence health, retry outside the tick, and introduce coherent world save transactions. |
| P1 | `map_test.py:384–388` initializes model handlers to `None` and enables mock mode; model runtimes provide fallback behavior. | LLM integration seams exist, but default startup is not evidence of live model-powered residents. Add an explicitly configured provider, observable live/mock/fallback status, timeouts, and a real end-to-end dialogue test. |
| P2 | `human_mode_3d.gd` is 4,521 lines; `incarnation_human.gd` is 1,935; `map_test.py` is 5,729. `human_mode_3d.gd:2402` destroys and rebuilds a chunk on each upsert. | These files combine responsibilities that need independent verification. Extract components incrementally and patch changed entities by ID/version. Measure chunk churn before choosing pooling or more complex streaming. |
| P2 | Backend startup binds `0.0.0.0:8002`; inspected mutation routes accept caller-supplied controller IDs and include testing/reset functionality. | For local single-player, bind loopback by default and restrict debug routes to development. If exposed remotely later, add authenticated sessions and capability checks. A controller name is not a permission boundary. |
| P2 | No conventional automated regression suite was found in the scoped source inventory; several `*test.py` files are launchers or scripts. `.gitignore:51` contains an invalid absolute Windows glob. | Add an isolated deterministic test harness and repair repository hygiene. Keep saves, generated captures, licensed source assets, and import caches out of ordinary code changes according to an explicit asset policy. |

The existing opening screenshot shows a sparse, flat arrangement of facade-like structures. The reaction QA image shows visible gaps between several character parts. Those images justify inspecting complete building prefabs and skin/body coverage, but cannot establish current animation timing or prove the cause of a mesh defect.

## Animation and movement implementation

Choose one supported humanoid skeleton and one complete character/outfit first. Record bone hierarchy, rest pose, bind transforms, scale, forward direction, root convention, and clip names in an asset manifest. Audit body visibility beneath modular clothing: a correct animation graph cannot repair missing geometry or mismatched skin binding.

Retarget and validate clips during import/build where possible. Cache the resulting resources rather than repeatedly repairing animation tracks for each actor. Godot's humanoid retargeting workflow provides a useful starting point; validate against the project's pinned 4.6 runtime. [Godot retargeting documentation](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/retargeting_3d_skeletons.html)

Use one AnimationTree for locomotion and action ownership: idle/walk/run blending from actual local velocity, optional upper-body conversation gestures, and explicit attack, hit, fall, downed, get-up, and death transitions. Document which actions interrupt others. Keep clip completion and authoritative action results distinct. Godot supports blend trees and state-machine transitions for this purpose. [AnimationTree documentation](https://docs.godotengine.org/en/stable/tutorials/animation/animation_tree.html)

Start with in-place locomotion and a collision-aware motor; match animation playback rate to measured movement speed. Reserve root-motion movement for an explicit later contract. Keep procedural look-at or foot adjustment in a defined post-animation stage. Remove each old correction only after the replacement passes the same rig/clip tests.

Implement local movement on a fixed physics step. Use server-defined movement parameters and shared collision geometry. Server snapshots should report the last input actually applied, not just received. Restore authoritative state, replay unacknowledged inputs, and smooth only the visual correction. Handle possession changes and world reloads with a new session/world epoch so old inputs cannot affect a new target.

## Scene and spatial design

Build one authored village: a central square, tavern, smithy, farm, houses, forest path, and a landmark such as a small keep. Use complete building assemblies, coherent scale/materials, collision, interaction anchors, doors, and navigable entrances. Add interiors selectively after the exterior loop works. Establish readable sunlight, ambient light, fog distance, and shadows before adding more decoration.

The inspected movement and rendering path maps a planar simulation onto Godot X/Z. Make that limitation explicit. A practical first stage is 3D presentation over authoritative ground-plane movement with shared height and obstacle data. Add surface/level IDs and portals for interiors or stacked floors; do not promise arbitrary stairs, jumping, and multi-level combat from only X/Y tensor coordinates.

Create a versioned world geometry description shared by server and client. Python validates movement and interactions against it; Godot renders it and predicts against matching collision proxies. If later requirements demand complex authoritative 3D physics, evaluate a headless Godot spatial service behind the same command/event boundary. Do not attempt to maintain two unrelated physics implementations accidentally.

Give every visible interactive object a stable backend entity ID. A decorative chest and a usable chest must be distinguishable in the content data. Apply incremental chunk/entity updates; instance repeated noninteractive foliage only after profiling establishes a benefit.

## Backend architecture

Keep a modular monolith with clear boundaries initially:

`Godot input -> protocol adapter -> validated command queue -> simulation tick -> committed events/state -> replication -> Godot presentation`

`Committed perception snapshot -> NPC job scheduler -> model worker -> structured proposal -> live validation -> simulation command queue`

Extract the existing Engine and endpoint code gradually into simulation, transport, persistence, and application bootstrap modules. Preserve the existing systems under `at_the_beginning/systems/` and the deterministic execution validators. Only the simulation owner mutates live world state; HTTP handlers and model workers submit messages. Workers must receive immutable snapshots rather than the live Engine object.

Use separate cadences for controls/combat, ordinary NPC schedules, memory maintenance, and expensive reasoning. Target the existing 20 Hz simulation first, measuring work against its 50 ms budget. Use a monotonic deadline, bounded catch-up, and overload metrics. Slow inference must not run on the event-loop thread; Python documents executors for blocking operations. A process boundary may be appropriate for CPU/GPU-heavy inference. [Python event-loop documentation](https://docs.python.org/3/library/asyncio-eventloop.html)

Version protocol envelopes with world/session epoch, schema version, server tick, command/event ID, actor ID, applied-input sequence, result status, and rejection reason. Keep bootstrap and management over HTTP; add a persistent state/event stream with bounded queues if measurements justify replacing polling. Reconnection requires a full resync and idempotent commands. Preserve the existing semantic JSON boundary.

For local saves, use SQLite transactions for structured resident/inventory/quest/event state, with versioned tensor snapshots associated with a committed manifest. Write and validate snapshot files before atomically committing the manifest; recover the latest complete generation after interruption. Include stable IDs, RNG state, tick, control ownership policy, and schema migrations. Keep MemoryRAG a rebuildable derived index. Back up and migrate existing resident JSON explicitly.

Track tick p50/p95/p99, tick overruns, command-to-ack latency, queue age, reconciliation distance, chunk build time, save failures, model latency, tokens, and fallback rate. Keep raw prompt logging opt-in and bounded.

## Interactive NPCs and god mode

The implementation plan now makes the model hierarchy explicit: world model for world reasoning and decrees, resident model for individual decisions and plans, fast interaction model for dialogue/reactions, and deterministic execution for authoritative effects. Providers and budgets are configurable per tier. Optional TTS is a separate presentation service for accepted dialogue. Per the updated development priority, finish the game with deterministic NPCs and scripted dialogue first (A–H); integrate model tiers and optional TTS afterward. See I0–I5 in `implementation_0905.md` for routing, context boundaries, and voice integration requirements.

An interactive NPC needs observable actions and continuity. For example: the smith remembers that you brought iron, promises a sword, reserves materials, works at the forge, and later gives you the sword. If the forge is destroyed, the job changes and the NPC explains why.

Build this using the existing personality, schedule, goal, task, crafting, inventory, and memory systems. Routine work and immediate reactions remain deterministic. Invoke the LLM for dialogue, unusual negotiations, and significant replanning. Retrieve only facts the NPC knows or perceives; distinguish witnessed facts, rumors, and uncertain beliefs.

Model output should separate speech from proposed actions. Action proposals reference allowed tools and stable entity IDs with typed parameters. Validate range, ownership, materials, target liveness, and job freshness before execution. Reject stale proposals after death, possession changes, or world reload. Dialogue must report actual tool results; promising a sword must not directly create an inventory item.

Use bounded concurrency, per-NPC cooldowns, priority for the player's conversation, deadlines, cancellation, and deterministic fallback replies. A slow or unavailable provider should leave villagers working. Add conversation memory summaries and relationship changes tied to committed events. Evaluate remembering, refusing impossible requests, acting on promises, and responding to player-caused changes. Add voice and lip sync after text interaction works reliably.

God mode should be a gameplay mode sharing the same world: release possession, use an overhead/free camera, inspect a resident's public state, pause or change simulation time, perform a small set of powers, and possess a resident again. Start with heal, spawn an allowed resource, and change weather. Route powers through validated commands and visible results. Natural-language decrees can propose these same operations. For broad effects, show the affected area/entities before applying them; checkpoint before irreversible world-scale changes. Make residents perceive consequences and update behavior/memory through existing events.

An example loop: intervene during a crop shortage, villagers resume work and remember the intervention, then return as a human and hear their reactions. This connects the simulation to the player's experience.

## Delivery order

| Milestone | Deliverable | Exit evidence |
| --- | --- | --- |
| 0: trustworthy baseline | Separate gameplay/QA profiles, New/Continue, isolated saves, reproducible full-simulation fixture, metrics. | Launch/reconnect does not reset a world; full dialogue and decree processing are exercised. |
| 1: physical presence | One correct rig, collision-aware movement, stable ground/buildings, camera obstruction handling, animation graph. | Fresh in-game recordings of movement, turns, talk, attack, hit, fall/get-up; no QA staging masks defects. |
| 2: reliable simulation | Queue-based mutations, fixed-step scheduler, applied-input reconciliation, durable saves, versioned protocol. | Delayed/reordered input, slow model, locked save, interrupted save, and reload tests pass. |
| 3: meaningful residents | 8–12 named NPCs with roles; scripted dialogue and deterministic decisions driving one complete promise-to-action loop. | A resident remembers an interaction after reload and completes or explains failure of a real task. |
| 4: divine consequences | Possession switching, three powers, time controls, inspection UI, event-driven reactions. | God intervention changes authoritative state and NPC behavior; returning to human mode preserves continuity. |
| 5: playable village | Content, audio feedback, onboarding, profiling and defect cleanup. | A documented 20–30 minute playthrough passes with fresh captures and isolated save/reload, with model providers disabled. |
| 6: later model integration | World, resident, and fast-interaction models; optional TTS after text integration. | Live model routes pass without regressing the proven game; voice verification is tracked separately. |

Proposed targets, to validate on a named reference machine: 60 FPS at 1080p for the initial village, simulation work p95 below 50 ms at 20 Hz, local movement visible within two rendered frames, and ordinary dialogue completing within five seconds or yielding a clear fallback. These are acceptance targets, not measured current performance. Test the chosen supported actor count before expanding population or map size.

Defer open-world expansion, multiplayer, bespoke model training, mass-generated quests, and large-scale war until this loop works. The next engineering goal is in `CODEX_IMPLEMENTATION_GOAL.md`.
