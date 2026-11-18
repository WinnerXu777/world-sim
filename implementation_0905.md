# Eden implementation plan — September 5, 2026

This is the execution plan for `CODEX_IMPLEMENTATION_GOAL.md`. Read `ENGINEERING_REVIEW.md` for evidence and rationale, then follow the dependency order and acceptance gates here. The review describes a particular working tree: relocate functions by name and revalidate findings before editing. This document specifies future work; it does not claim that any milestone has been implemented.

## 1. Outcome and scope

Deliver a coherent 3D medieval village in the existing Godot client, with Python owning authoritative world state. The player can explore, interact with 8–12 named residents, establish relationships through remembered actions, request a real crafted item, enter god mode, change the world, and return to human control. Saves preserve those consequences.

The first complete experience lasts 20–30 minutes. Its core sequence is: enter the village, meet the smith, negotiate a sword, obtain or supply materials, observe work, receive the item, intervene as a god, observe residents react, and reload the same world.

Keep the existing tensor-backed simulation and domain systems. Start with ground-plane movement in a 3D environment, shared collision/height data, and explicit surfaces or portals if an interior requires them. Full multi-level physics, free climbing, jumping, multiplayer, armies, open-world expansion, and model training are later work. Defer model-provider integration and the TTS adapter until the playable-game gate passes; advanced lip sync and player speech recognition are later extensions. This staging does not change the long-term 3D medieval game vision.

## 2. Working rules and document ownership

- Preserve unrelated user edits. Record the working-tree baseline; never reset or overwrite current resident data for testing.
- Use dedicated test save roots and explicit seeded fixtures. Import or migrate existing saves only through a backed-up, documented operation.
- Follow this document for execution order and detailed contracts; use the goal for the overall outcome and the review for diagnostic context. Current user instructions take precedence. If current code invalidates a finding, document the evidence and adapt the implementation rather than recreating obsolete work.
- Proposed filenames below are module boundaries, not a mandatory mass rename. Reuse equivalent existing components. Extract code incrementally, keeping compatibility adapters until callers migrate.
- Make ordinary reversible implementation decisions autonomously. Do not stop at every milestone to request approval. Record decisions that affect architecture or compatibility.
- Maintain `IMPLEMENTATION_PROGRESS.md`: ticket, status, changed paths, verification command, evidence location, remaining defects. Mark a ticket complete only when its gate passes. Use statuses `pending`, `in_progress`, `verified`, or `blocked_external`.
- Capture fresh visual evidence after animation/scene changes. A still image cannot prove smooth movement or stable transitions. QA lanes supplement gameplay recordings.

## 3. Target component boundaries

| Area | Suggested boundary | Responsibility |
| --- | --- | --- |
| Godot startup | `scripts/app/game_session.gd` | New/Continue, connection, world epoch, mode changes |
| Transport | `scripts/net/world_client.gd` | Requests/stream, decoding, reconnect, protocol compatibility |
| Replication | `scripts/net/world_replica.gd` | Authoritative snapshots, revisions, stable entity lookup |
| Player | `scripts/player/player_motor.gd` | Fixed-step input, collision, pending-input replay |
| Camera | `scripts/player/player_camera.gd` | Human/god camera, obstruction, interpolation |
| Animation | `scripts/characters/character_animator.gd` | One animation graph, state priorities, visual action timing |
| Character assets | `scripts/characters/character_factory.gd` | Validated rig, outfit, skin, animation resource assembly |
| World | `scripts/world/world_stream.gd` | Stable chunk/entity creation and incremental updates |
| Interactions/UI | `scripts/ui/` and `scripts/interaction/` | Target selection, conversation, inventory, god powers |
| Simulation | `at_the_beginning/simulation/` | Engine ownership, scheduler, command application, snapshots |
| Transport | `at_the_beginning/api/` | Typed request/response adapters; no direct world mutation |
| Persistence | `at_the_beginning/persistence/` | Save generations, migration, recovery, persistence health |
| NPC jobs | `at_the_beginning/runtime/` | Extend existing model runtimes with jobs/provider adapters |
| Domain behavior | existing `at_the_beginning/systems/` | Reuse combat, inventory, crafting, tasks, schedules, memory |
| Shared contracts | `contracts/` | Protocol examples/schema, movement config, geometry format |

`human_mode_3d.gd` should become scene composition and high-level coordination. `incarnation_human.gd` should delegate asset assembly and animation. `map_test.py` should eventually remain a compatibility launcher, not the home of new systems.

## 4. Execution order

Stage 1 (game first): follow A → B → C → D → E → F → G → H with deterministic NPC decisions and scripted/templated dialogue. Stage 2: only after Gate H passes, implement I (multi-tier LLM integration), then optional TTS. No model credentials, inference service, or TTS provider is required to complete Stage 1. Keep existing model seams compatible, but do not build provider infrastructure before the game works. A minimum fixed-world fixture in A supports early verification; polish its village content in E. B establishes the backend/protocol foundation needed by movement reconciliation in D. C proves the rig before animation is coupled to movement. Do not wait for full art polish to repair persistence.

### A — Trustworthy gameplay baseline

**A1: Inventory and baseline.** Inspect `project.godot`, `HumanMode3D.tscn`, `HumanVisualQA.tscn`, the character scene, `map_test.py`, `initial_test.py`, `client_backend_boundary.md`, and existing QA instructions. Identify installed Godot/Python versions, asset dependencies, startup overrides, and any live backend. Establish a separate test port/save directory. Record current frame/tick behavior and capture a short ordinary-input movement sequence.

**A2: Explicit launch profiles.** Introduce one configuration path for `gameplay`, `animation_qa`, and `render_fixture`. Gameplay must run normal world, talk, and human-agent processing. Test fixtures are opt-in. Remove the implicit render-village reset from client startup; New Game creates a selected save, Continue loads it, and reconnect only synchronizes. Fix the invalid ignore glob while establishing artifact/save locations.

**A3: Fixed gameplay scene.** Move the player-following ground, paths, context props, virtual QA controller, and forced pose holds to the QA path. Remove broad nearby-actor/chunk visibility suppression from gameplay. Create one small fixed floor, wall, doorway, usable prop, player, and two NPCs as the baseline fixture. Do not compensate for missing streamed content with camera-following geometry.

**A4: Isolation and observability.** Add separate runtime data roots, deterministic fixture seeds, a basic health/status view, and exact launch instructions. Surface the active profile and model mode. Keep the fixture independent of production resident JSON and RAG files.

**Gate A:** Start, disconnect, and reconnect twice; stable IDs, inventory, and world epoch remain unchanged. Verify the normal full simulation processes a talk event and a decree using deterministic adapters. Move/orbit the player and compare world transforms: the floor, prop, and NPCs remain fixed. Record a fresh gameplay capture.

### B — Backend ownership, protocol, and persistence

**B1: One mutation owner.** Extract a callable simulation step from `Engine.run_loop`. HTTP handlers validate the envelope and enqueue commands. Model workers return proposals. Only the simulation owner applies state changes. Keep reads on immutable published snapshots. Adapt direct inventory/control/decree routes first; inventory transfer and crafting completion must not bypass the queue.

**B2: Fixed-step scheduling.** Retain the initial 20 Hz target and measure simulation work separately from sleep. Schedule against monotonic deadlines and cap catch-up steps. Report overruns instead of allowing unlimited catch-up. Separate simulation time from wall time: pause/time scale changes world progression while transport, UI, health, and job cancellation remain responsive. Track the loop task and drain/cancel it during shutdown.

**B3: Protocol contract.** Extend existing semantic payloads rather than exposing tensors. Specify the following fields and their meanings:

| Message | Required semantics |
| --- | --- |
| Bootstrap | Protocol version, world ID/epoch, server tick, geometry revision, movement settings, supported capabilities |
| Movement input | Session/control epoch, controlled actor ID, monotonic input sequence, bounded duration or target step, normalized axes, buttons |
| Discrete command | Unique command ID, session/world epoch, actor/target IDs, allowed action, typed arguments |
| Command acknowledgment | Received/rejected status; reception is not proof of application |
| Snapshot | Server tick, state revision, authoritative position/velocity/action, last movement input actually consumed |
| Applied result/event | Stable event ID, originating command ID, applied/rejected outcome, reason, authoritative consequences |

Keep continuous movement and discrete command sequencing separate or explicitly define how they share ordering. The existing `last_input_seq` check must not accidentally discard an attack because a later movement snapshot arrived first. Decide whether input messages contain finite simulation steps or persistent control state, and make acknowledgments match that choice. Clamp client-provided duration; never accept it as authority for speed or elapsed world time.

Publish contract fixtures for duplicated input, stale world epoch, possession change, invalid action, and reconnect. Start with existing HTTP transport if adequate. If replacing polling, implement a persistent stream with bounded outbound queues and snapshot resync; do not treat a transport change as a substitute for sequencing correctness.

**B4: Immediate save repair.** Make resident writes return success or raise a handled failure. Clear dirty state only after successful persistence. Preserve updates made after a snapshot was captured: acknowledge a resident revision, not just an ID. Remove the unsafe silent direct-overwrite fallback. Retry outside the simulation step and expose degraded save status.

**B5: Coherent save generations.** Implement versioned saves with resident/task/inventory/event state in SQLite and tensor snapshots referenced by a committed manifest, or document an equally crash-consistent simpler format. Capture one immutable world generation at a tick boundary, including stable IDs and RNG state. Write new snapshot files under unique generation names; flush and validate them before committing database rows and the manifest reference together. Do not rewrite files referenced by the previous committed generation. On load, validate references/checksums and recover the latest complete generation. Unreferenced files are recoverable garbage, not the active save.

Include world generation ID, schema version, tick/time, tensors, ID mappings/counters, residents, inventory/equipment, reservations, tasks, schedules/goals, relevant events, and deterministic RNG state. Explicitly resolve pending control ownership and in-flight model jobs on load; discard stale external jobs and regenerate eligible work. Derive MemoryRAG from authoritative state. Keep old save generations until the new one is verified.

**B6: Development boundary.** Bind loopback by default. Restrict reset/fixture endpoints to development. Use a session capability for human/god control; a caller-supplied controller name alone must not authorize mutations. This is a local single-player boundary, not a multiplayer authentication project.

**Gate B:** Tests show duplicate transfer/attack commands have one effect, stale epochs are rejected, canceled possession input cannot move the replacement actor, and received-but-not-applied inputs are not acknowledged as applied. Inject a slow model, a locked save, and failures before/after manifest commit. The simulation stays responsive and loads a complete save; dirty revisions remain pending until successfully written. Test shutdown during queued work.

### C — Character assets and animation

**C1: Supported asset manifest.** Select one complete existing character/outfit first. Record paths, license/source notes, required plugin versions, skeleton hierarchy, rest pose, scale, forward axis, root bone, skin bindings, and animation names. Inspect body coverage under clothing. Confirm the same skin binds to the same skeleton across all supported parts. Missing body geometry must be fixed as an asset problem.

**C2: Normalize once.** Build a repeatable import/retarget process compatible with the installed Godot version. Cache normalized animation libraries. Verify every required bone track resolves, locomotion is in place, and intended vertical motion in falls/get-up remains intact. Do not blanket-strip all translation tracks. Keep import-time repair separate from runtime presentation. Use the official references linked in the review, checking version-specific API details during implementation.

**C3: One animation owner.** Build one AnimationTree backed by validated AnimationPlayer resources. Use actual local velocity for idle/walk/run blending. Set a documented priority policy: death overrides living actions; knockdown overrides attack/talk; hit interruption depends on the action phase; talk gestures may layer over compatible locomotion. A dead character cannot transition to get-up without a new authoritative resurrection state, which is outside the initial heal power.

Represent combat action phases explicitly: wind-up, active, recovery. The backend determines hit/damage and action legality. Animation markers drive presentation timing and feedback, not damage authorization. Repeated snapshots of the same action ID do not restart a clip. Leaving/entering a state clears obsolete timers and offsets.

**C4: Remove competing paths.** Replace manual stop/seek/restart transitions and idle freezing for the supported rig. Remove old root/facing/gesture corrections only when the replacement passes. Keep any necessary look-at or foot adjustment in a single documented post-animation stage. Validate two different outfit/body instances to detect mutation of shared resources.

**Gate C:** Run idle→walk→run→stop, turn, talk, attack, hit during attack, fall→downed→get-up, and death sequences. Capture front/side and ordinary gameplay video. Verify no missing parts, exploding skin, unexpected rest pose, repeated state restart, or locomotion drift attributable to root motion. Record which assets/clips are supported; do not claim arbitrary asset compatibility.

### D — Responsive movement and a stable camera

**D1: Shared spatial contract.** Define units, axes, actor radius/height, movement speed, acceleration, collision layers, and supported surfaces in `contracts/`. Author simple geometry proxies shared by Python and Godot: height/surface data and obstacle footprints. Backend movement validates swept motion against these proxies; do not rely only on checking an endpoint across a thin wall. Document unsupported geometry.

**D2: Fixed-step motor.** Move input processing into a physics-step player component. Keep the visual skeleton under a separate presentation node. Client prediction uses the same movement parameters and compatible collision rules. Godot visual/physics helpers must not introduce unmodeled authoritative movement. If agreement cannot be achieved with the selected proxy format, simplify the supported geometry before adopting another physics service.

**D3: Reconciliation.** Keep a bounded history of pending movement inputs and their simulation steps. On a newer snapshot, restore authoritative motor state, remove consumed inputs, replay the rest, and smooth the rendered correction independently. NPCs use buffered interpolation with bounded extrapolation. Reset histories on world/control epoch changes. Track correction distance and snap frequency. Avoid resetting visual child yaw every frame as a substitute for correct import axes.

**D4: Camera.** Implement human follow/orbit and god overhead/free modes with separate state. Use a collision query between subject and desired camera position; shorten the camera arm or fade only actual occluders where necessary. Restore faded objects on mode/target changes. Input focus in conversation UI must suppress movement and accidental attacks.

**Gate D:** Test walls, corners, diagonal input, stop/restart, doorway traversal, camera orbit near a building, and possession switching. Inject 100–250 ms latency plus duplicate/reordered messages in a test adapter. The authoritative actor does not cross a wall, repeat an action, or teleport on ordinary reconnect. Measure local response and reconciliation error; record fresh gameplay rather than virtual QA movement.

### E — A village with usable places and objects

**E1: Content data.** Define a seeded village layout with fixed transforms and stable IDs for the square, smithy, tavern, farm, homes, forest path, and landmark. Use complete assembled building prefabs. Standardize scale, material treatment, and collision. Put navigation/work/door/conversation anchors in content data, not scattered hard-coded script offsets.

**E2: Interactive objects.** Every usable chest, forge, resource pile, door, or station maps to a backend entity and available actions. Keep decorative props explicitly noninteractive. Query affordances and show range/availability feedback; backend validation remains authoritative. Use the same anchors for NPC movement and player interaction.

**E3: Streaming.** Preserve nodes by stable ID, patch changed revisions, and remove only deleted/unloaded entities. Avoid replacing an entire chunk for one changed chest. Cache scene resources and measure loading/build costs. Add instancing/LOD only where the measurements justify it. Keep distant decoration separate from simulation relevance.

**E4: Readability.** Establish one coherent lighting setup, readable silhouettes, sensible fog, and recognizable destinations. Add footsteps and interaction/hit feedback. Keep terrain fixed and continuous at visible chunk boundaries. Test the camera inside the intended navigable spaces.

**Gate E:** Walk the entire village route with two NPCs moving between work anchors. Interact with a real chest and forge. Load/unload/reload a chunk: IDs, inventory, tasks, and fixed transforms remain consistent. Record frame timing at 1080p on named hardware.

### F — Deterministic residents and the complete task loop

Use existing rules, schedules, memory, and typed commands with scripted dialogue choices or templates. The smith accepts/refuses according to real state; this is functional game logic, not a placeholder that fabricates outcomes. Store consequential events and relationships now so models can use them later. Free-form conversation is not required in Stage 1.

**F1: Smith interaction.** Wire existing inventory/crafting/tasks/schedule/memory together. Acceptance creates one persistent work order with customer, recipe, station, price/material requirements, and state. Suggested lifecycle: offered → accepted → awaiting_materials → reserved → working → ready → delivered, with canceled/failed branches. Reservations prevent duplicate consumption. Work progress uses simulation time and station availability. Delivery transfers the actual output exactly once. Destruction/unavailability of the forge interrupts or replans with a committed reason the NPC can explain.

**F2: Other residents.** Add 8–12 named residents with distinct roles and schedules using existing domain systems. Give several different responses to the same request based on knowledge, trust, occupation, and available resources. Prioritize believable behavior continuity over verbose dialogue.

**Gate F:** With every model provider disabled, complete the sword request, material reservation, work, delivery, and remembered follow-up. Test insufficient resources, duplicate acceptance/delivery, damaged forge, canceled work, and save/reload during crafting. The real inventory/task systems must produce each effect exactly once. Verify distinct resident routines and event-driven reactions using deterministic decisions and dialogue.

### G — God mode and visible consequences

**G1: Mode state machine.** Support embodied → releasing → god → possessing → embodied, including failure recovery. Clear held input when releasing. Transfer control only after authoritative acknowledgment; retain a usable god camera if a possession attempt fails. Released residents resume autonomous behavior with their existing tasks.

**G2: Initial powers.** Implement heal, spawn an allowed resource, and change weather through the existing validated decree/execution seam. Heal respects living status and maximum health. Spawn validates resource type, quantity, and location. Weather changes supported state and feeds existing ecology/schedule logic. Return accepted/rejected/applied results and correlate them to the UI. Do not silently implement resurrection as healing.

**G3: Time and inspection.** Provide pause/resume and conservative time scales. Separate simulated time from real deadlines so pausing does not freeze transport or hang model requests. Decide explicitly which god edits may apply while paused; process those at a controlled boundary without advancing ordinary simulation. Show selected resident role, needs, current task, relationships, and a concise explanation of recent behavior.

**G4: Consequences.** Publish intervention events to relevant perceivers. NPCs update memory, task review, and behavior through the existing systems. Do not tell all NPCs about an unwitnessed event automatically. In Stage 1 use explicit UI controls and typed commands for powers. Natural-language decrees are added in Stage 2 and compile into those same allowed powers; unsupported requests return a clear limitation. For broad changes, preview area/targets; preserve a checkpoint before irreversible effects.

**Gate G:** Leave a working resident, change weather or supply a needed resource, observe an affected resident react, possess again, and discuss the event. Verify pause/resume, failed possession, stale input rejection, duplicate power handling, and save/reload. A camera mode without authoritative consequences is not complete god mode.

### H — Integration, performance, and delivery

**H1: Onboarding/UI.** Make New/Continue, movement, talk, inventory, and god-mode controls discoverable. Show selected targets, pending actions, dialogue status, save failures, and provider fallback in appropriate UI. Keep debugging details in a diagnostics panel.

**H2: Regression suite.** Establish runnable focused tests under a conventional test directory. Cover startup preservation, input/command sequencing, collision authority, animation state identity, atomic inventory/task effects, stale model jobs, save recovery, and possession. Use isolated save roots and deterministic providers. Avoid external paid calls in ordinary automated tests; document a separate live-provider smoke test.

**H3: Performance evidence.** Record hardware, resolution, actor count, scene/profile, provider, capture duration, and cold/warm loading conditions. Proposed initial targets: 60 FPS at 1080p, 20 Hz simulation with work p95 below 50 ms, local movement visible within two rendered frames, and conversation response within five seconds or a clear fallback. Track frame/tick percentiles, overruns, queue age, model latency/token use, save failures, chunk build cost, and correction distance. Treat these as targets until measured.

**H4: Final playthrough.** Perform the full 20–30 minute village loop in normal gameplay with full simulation. Include the sword request, real work/delivery, meaningful dialogue follow-up, three god powers, possession return, and save/reload. Retain timestamped recordings and test reports outside active user saves. Document exact launch commands and required assets/configuration.

**Gate H — playable-game release:** All Stage 1 criteria pass with model/TTS providers disabled. Scripted dialogue drives real tasks, persistent memory, and god consequences. Model/voice credentials are not blockers for this gate. Missing gameplay assets or broken mechanics remain incomplete. Record Stage 1 as verified before beginning I; passing H does not claim that Stage 2 LLM integration is finished. Final delivery includes changed components, tests run/results, current limitations, performance results, and a playable launch path.

### I — Later integration: multi-tier LLMs, then optional TTS

Begin only after Gate H is verified. Keep Stage 1 playable with providers disabled. Replace decision/dialogue adapters incrementally; retain the authoritative tasks, events, saves, and god-power commands already proven.

**I0: Explicit multi-tier model architecture.** Implement separate logical roles, prompts, context access, output schemas, queues, and budgets. Roles may initially use the same configured model through different adapters; allow an independent provider/model per role without changing domain code. Different tiers do not require training separate models.

| Tier | Responsibility and context | Invocation and allowed output |
| --- | --- | --- |
| World model | World-level reasoning, god decrees, regional events, and coordination across residents using an appropriate aggregate world snapshot | On a decree or significant world event, plus a configurable slow review cadence; proposes validated world operations and objectives, not per-frame movement |
| Agent/resident model | One NPC's decisions: priorities, goals, commitments, negotiation, and replanning using personality, perceived facts, memories, relationships, and current tasks | On significant personal events, failed plans, or scheduled review; proposes that resident's goals/tasks and decisions, not unrestricted world mutations |
| Fast interaction model | Short dialogue wording, ambient barks, and optional contextual reaction selection within the resident's current intentions and approved capabilities | On interaction or a relevant local event; bounded speech/reaction proposals. Cannot independently accept obligations or overwrite a resident plan; escalate those decisions to the resident tier |
| Deterministic execution | Validates and applies world commands, NPC plans, movement, combat, crafting, inventory, schedules, and immediate survival behavior | Runs without an LLM dependency; commits outcomes and publishes events back to the model tiers |
| TTS service | Converts approved NPC dialogue into audio with a stable per-resident voice | Runs after a dialogue line is accepted; outputs audio and optional timing metadata, never gameplay decisions |

Use `world_runtime.py` for the world adapter, the existing resident/human planning seams for agent decisions, and `tiny_runtime.py` / `talk_runtime.py` for fast interaction. Inspect the existing `resident_model_handler` hook and connect it explicitly where appropriate. Do not collapse all reasoning into the tiny dialogue callback simply because it is already convenient to invoke.

Routing example: a god decree supplies iron → deterministic world execution adds resources and emits an event → the smith perceives it → the resident model decides whether to resume the sword task → the deterministic task system reserves iron and performs work → the fast interaction model explains the accepted decision → TTS speaks that line. Simple dialogue can bypass world/resident inference when no decision is needed. Do not force every utterance through a serial chain of all models.

World-generated objectives enter each resident's normal goal arbitration rather than replacing personality or agency indiscriminately. NPCs receive only perceivable consequences of world reasoning, not an omniscient copy of its context. Use causal event IDs, cooldowns, and bounded escalation depth to prevent world/agent callbacks from triggering an infinite reasoning loop. Measure latency, queue age, token use, timeout/fallback rate, and model mode separately per tier. A slow world job must not starve player dialogue or deterministic execution.

**I1: Provider and job boundary.** Extend `tiny_runtime.py`, `world_runtime.py`, `talk_runtime.py`, and related adapters rather than adding a parallel NPC stack. Configure a real provider through environment/config and retain a deterministic test provider. Never embed credentials in saves or logs. Expose provider/model status as live, mock, or fallback.

Create immutable jobs containing job ID, NPC ID, world/control epoch, relevant state revisions, conversation/turn ID, deadline, priority, context, and allowed action schemas. Use bounded concurrency and queue length. Prioritize player conversations, then significant replanning; low-priority ambient chatter may be dropped. Routine schedules and urgent deterministic reactions never wait for inference.

**I2: Grounded context.** Assemble role/personality, perceived nearby facts, relationship summary, current task, and a bounded set of relevant memories. Label rumors and uncertainty. Exclude private facts the NPC could not know. Summarize old conversation turns and retain consequential events with provenance. Apply relationship updates once per committed event ID.

**I3: Structured output.** Use a schema equivalent to:

```json
{
  "job_id": "job-123",
  "npc_id": "h_000002",
  "speech": "I can make that if you bring the iron.",
  "speech_act": "offer",
  "proposals": [
    {
      "action": "offer_crafting_job",
      "arguments": {"recipe_id": "sword_basic", "customer_id": "h_000001"}
    }
  ]
}
```

Names here are proposed contract examples; map them to existing validated task/crafting operations. Enforce text length, enum/schema, ID, and tool limits. Model text cannot grant god capabilities or execute code. Revalidate job freshness, target liveness, materials, relationship conditions, ownership, and range where relevant at application time. A state change need not invalidate unrelated context; define which dependencies each job/action requires.

**I4: Turn/result lifecycle.** Keep drafted speech distinct from confirmed outcomes. A model may offer work before approval, but cannot report successful transfer until the task/transfer commits. Correlate late responses to the correct conversation turn. Timeout produces a visible fallback and closes or retries the job under a bounded policy; ignore late duplicate results. Background work continues during provider outages.

**I5: Optional spoken NPC dialogue.** After the text/action loop passes, implement a provider-neutral TTS adapter with off/mock/live modes and configurable per-resident voice IDs. Keep subtitles available immediately while audio is generated asynchronously. Correlate each audio job with world epoch, conversation ID, turn ID, speaker ID, and accepted dialogue ID. Cancel or discard stale audio when a conversation ends, the speaker dies, or the world changes. Permit player skip/mute and prioritize direct conversation over ambient chatter. Use positional playback for NPCs, a bounded cache keyed by text/voice/provider settings, and limits on concurrent synthesis/playback. Provider failure falls back to text without affecting tasks or decisions. Optional timing data may drive simple mouth motion later; audio playback must not commit gameplay effects. Keep player speech-to-text as a separate future input adapter.

**Gate I:** Test successful sword delivery, insufficient iron, forged item requests, a duplicate reply, death/world reload during inference, canceled conversation, broken forge, and unavailable provider. Save/reload while work is active and after delivery. Verify a memory-grounded follow-up and real configured-provider runs through both world and resident decision tiers. Include routing tests that show fast dialogue cannot issue a world power or create an unapproved commitment. Mock success alone cannot pass the live-LLM gate. TTS follows successful multi-tier text integration and is optional for Stage 2; implement its adapter/configuration when starting voice work; when enabled, verify stable voice identity, subtitles, interruption, stale-audio rejection, and text fallback. Report live TTS as unverified if no provider is configured.

## 5. First implementation session

Begin with A1–A4. Produce an isolated launch fixture and a regression showing that ordinary client connection cannot reset it. Remove QA scenery/visibility behavior from the gameplay path and capture the fixed scene with ordinary input. Update the progress log with evidence, then continue to B. Do not stop after creating a plan or scaffold; proceed through the remaining milestones within the active implementation request.

## 6. Completion checklist

- [ ] A: Gameplay startup preserves worlds; QA is isolated.
- [ ] B: Command ownership, scheduling, protocol, and durable saves are verified.
- [ ] C: Supported character assets and animation sequences pass visual checks.
- [ ] D: Movement, collision, camera, and reconciliation pass ordinary and delayed-input checks.
- [ ] E: The fixed village is traversable and its usable objects match authoritative entities.
- [ ] F: Deterministic NPC decisions and scripted dialogue drive a real persistent task and memory loop.
- [ ] G: God powers and possession produce durable, perceivable consequences.
- [ ] H: Full playthrough, regression results, performance measurements, and launch documentation are delivered.

- [ ] I (Stage 2, after H): World/resident/fast-interaction model routes pass live integration tests; optional TTS is separately tracked.
