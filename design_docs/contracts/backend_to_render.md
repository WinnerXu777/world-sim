# Backend To Render

Status: current architecture note for the `at_the_beginning` backend and the
Godot 3D projection layer.

This document explains:

- what the backend is already doing well
- what the current backend-to-render limitations are
- why walking / hit / attack / incarnation feel have been difficult
- what the recommended implementation path is while preserving the memtensor
  interaction core

## Short Version

The current backend is not "just memtensor."

It already has:

- tensor simulation state
- semantic control routing
- resident memory / relationship state
- task execution
- orchestrator packet handling

The main weak point is the projection from backend truth into 3D presentation.

The biggest current limitation is:

- authoritative state is updated in backend ticks
- the client still has to reconstruct smooth motion and animation from those
  snapshots
- if rendering reads raw backend updates too directly, motion looks tick-like
  and animation becomes unstable

So the main redesign goal is:

- keep backend truth authoritative
- make the client render a smoother presentation layer on top of that truth

## Current Backend Design

The backend stack is already layered.

### 1. Simulation substrate

Core world truth lives in the tensor state:

- `m_tensor`
- `h_tensor`

This is the authoritative source for:

- world positions
- HP / threat / combat truth
- resources / map entities
- physically meaningful state shared across all residents

Relevant files:

- `at_the_beginning/map_test.py`
- `at_the_beginning/systems/movement/manual.py`

### 2. Semantic control layer

The game does not only receive raw input. It already has a semantic control
path that normalizes player actions into meaningful commands such as:

- `move`
- `attack_target`
- `talk_command`
- `interact_target`

Relevant files:

- `at_the_beginning/systems/control/router.py`
- `at_the_beginning/runtime/control_runtime.py`
- `../archive/implement_control.md`

### 3. Resident memory / relationship layer

Residents are not only driven by tensor values. There is already a memory and
relationship store above the raw sim.

This supports:

- remembered events
- remembered threats
- relationship updates
- resident-local history beyond a single tick

Relevant file:

- `at_the_beginning/runtime/resident_store.py`

### 4. Task and execution layer

Tasks and domain actions are already expressed above raw movement.

This includes things like:

- combat task execution
- work / gather / build tasks
- target-aware actions

Relevant files:

- `at_the_beginning/systems/tasks/catalog.py`
- `at_the_beginning/systems/tasks/families/combat.py`

### 5. Orchestrator layer

The orchestrator already exists as a packet and escalation layer.

This means the architecture already has a place for:

- packet intake
- semantic reasoning handoff
- richer consequence pipelines

Relevant files:

- `at_the_beginning/orchestrator/runtime.py`
- `at_the_beginning/orchestrator/intake.py`
- `at_the_beginning/orchestrator/design.md`

## Current Rendering Design

The 3D client is mostly runtime-built and backend-driven.

### Static world / map

The map is not primarily authored as a hand-built Godot scene.

Instead:

- backend map data is generated in Python
- the Godot client loads that world data
- terrain, structures, and actors are instantiated at runtime

This is why the editor 3D viewport does not show a faithful preview of the
full map by default.

Relevant files:

- `at_the_beginning/initial_map_design.py`
- `godot_client/scripts/human_mode_3d.gd`

### Actor rendering

The client currently builds actor visuals dynamically and then tries to animate
them from backend state.

Relevant files:

- `godot_client/scripts/human_mode_3d.gd`
- `godot_client/scripts/incarnation_human.gd`

The current render path now has a first pass of backend render hints:

- `server_tick`
- `server_time`
- `velocity_world`
- `speed`
- `moving`
- `direction_world`
- `facing_yaw`
- `locomotion`
- `action`
- `action_started_tick`

These are generated in:

- `at_the_beginning/map_test.py`

And consumed in:

- `godot_client/scripts/human_mode_3d.gd`

## Current Backend-To-Render Limitation

The main limitation is not the memtensor idea itself.

The main limitation is that the client still has to turn discrete authoritative
state into continuous visible motion.

### 1. Backend truth arrives at tick cadence

The authoritative world state updates on backend ticks, not every render frame.

That is correct for world truth, but it means visible motion must be rebuilt on
the client.

If the client renders directly from those updates, you get:

- jitter
- recentering
- tick-like stop/start motion
- awkward camera follow

### 2. NPC walking is inferred, not authored

For residents, the client still has to infer locomotion from:

- snapshot positions
- exported velocity hints
- facing hints

That is much harder than a local-only character controller.

Simple demos usually look better because they use:

- one clean local velocity source
- one authored rig
- one stable animation tree

This project is harder because the client is reconstructing motion after the
fact from authoritative world updates.

### 3. Incarnation still shares the authoritative world loop

The controlled human is special, but the backend still commits its row in the
same authoritative tick loop as everyone else.

That is correct for world consistency, but it means the incarnation can still
feel tick-bound unless the client strongly predicts and smooths presentation.

Important distinction:

- player input decides the intended change
- backend still commits the real tensor row

So the incarnation must be rendered differently from ordinary residents:

- residents: interpolated from backend snapshots
- incarnation: locally predicted, then reconciled to backend truth

### 4. Animation currently depends on a fragile bridge layer

The animation problem is not mainly "the clips are bad."

The hard part is the bridge:

- runtime-assembled characters
- retargeted Mixamo clips
- animation chosen from reconstructed motion state
- one-shot actions competing with locomotion updates

Walking is the hardest state because it exposes every weakness in:

- speed estimation
- facing estimation
- transition stability
- clip selection
- blend timing

One-shot clips like attack or pain are easier to fake than stable walking.

### 5. Map rendering is semantic, not authored

The backend exports abstract world meaning such as:

- `house`
- `village`
- `forest`
- `storage_case`

The Godot side then approximates that with assets at runtime.

This is flexible, but it makes visual polish harder because the renderer is
still doing interpretation, not loading a fully authored finished level.

### 6. Render events are still not yet rich enough

The render hint path is moving in the right direction, but it still needs to be
treated as a proper presentation contract rather than just a loose extra field.

For example, the client benefits from explicit and stable action semantics such
as:

- attack started
- hit reaction
- downed
- get up
- flee
- talk

instead of guessing too much from HP deltas or movement alone.

## What Is Already Good

The backend design is good for the core simulation goal:

- many residents
- no per-resident always-on LLM
- non-hardcoded interactions
- shared authoritative truth

That is exactly where a memtensor-style substrate helps.

The architecture should be preserved in principle.

The thing that needs redesign is not the interaction core. It is the
presentation contract between backend and client.

## Recommended Rendering Architecture

The recommended design is a 4-layer client rendering model.

### 1. Authoritative snapshot state

This is the raw backend payload.

It should be stored, but not rendered directly.

Contains:

- positions
- HP
- threat
- render hints
- task/combat/talk truth

### 2. Presentation state

This is the render-facing state per actor.

It should contain values such as:

- `render_position`
- `render_velocity`
- `render_facing_yaw`
- `render_locomotion`
- `render_action`
- `render_action_started_tick`

This is what meshes, camera rigs, and animation controllers should read.

### 3. Local intent state

This is mainly for the incarnation.

Contains:

- current move input
- sprint intent
- camera yaw / pitch
- attack intent
- talk intent

This should drive local prediction immediately.

### 4. Event state

This is for one-shot visual reactions.

Examples:

- attack landed
- hit reaction
- downed
- get up
- flee start
- talk start

These should trigger one-shot animation or FX explicitly, not be inferred from
noisy motion data.

## Recommended Backend Contract

The backend should keep ownership of truth, but it should export a cleaner
render contract.

### Keep authoritative in backend

These should stay backend-authoritative:

- movement validity
- actual position truth
- HP / damage / death
- talk outcome
- interaction outcome
- task consequences
- resident memory / relationship updates
- orchestrated follow-up behavior

### Export render-friendly hints

The backend should continue exporting and gradually standardize:

- `server_tick`
- `server_time`
- `velocity_world`
- `speed`
- `facing_yaw`
- `locomotion`
- `action`
- `action_started_tick`

Recommended next additions:

- `state_flags`
  - `downed`
  - `getting_up`
  - `fleeing`
  - `talking`
  - `attacking`
- `action_seq`
  - monotonic event sequence for repeated one-shots
- `target_id`
  - current semantic focus for attack / talk / flee readability
- `control_owner`
  - whether this actor is the locally controlled incarnation

These do not weaken the memtensor core. They are just render projections of
authoritative truth.

## Recommended Client Implementation

### A. Incarnation

The incarnation should not visually behave like a normal resident.

Recommended behavior:

- predict local movement every frame from `WASD`
- drive camera from predicted render position
- drive animation from predicted velocity and intent
- reconcile gently to backend authoritative state
- snap only on large desync

This preserves backend truth while removing the shared-tick feel.

Recommended animation inputs for the incarnation:

- `move_speed`
- `move_direction_local`
- `is_sprinting`
- `is_attacking`
- `is_hit`
- `is_downed`
- `is_getting_up`
- `is_talking`

### B. Residents / NPCs

Residents should use buffered interpolation from backend snapshots.

Recommended behavior:

- buffer snapshots using `server_time`, not only packet arrival time
- render slightly behind authoritative time
- interpolate position, velocity, and facing
- only extrapolate a little
- drive locomotion from smoothed presentation velocity, not raw backend deltas

Recommended animation inputs for residents:

- `speed`
- `facing_yaw`
- `locomotion`
- `action`
- `state_flags`

### C. Animation system

The current clip bridge should evolve into one canonical humanoid controller.

Recommended long-term structure:

- one clean animated humanoid scene
- one stable rig
- one locomotion state machine
- one-shot reaction channel for:
  - attack
  - pain
  - down
  - get up
  - talk

Important rule:

- walk should not rely on hard one-shot locks
- attack / pain / down / get-up should use protected one-shot locks

### D. Map rendering

The map can stay backend-driven, but the renderer should become more authored.

Recommended direction:

- keep semantic backend map generation
- map semantic entity kinds to better curated prefab sets
- optionally support a preview/bake path in Godot for test maps
- stop treating every structure as only a generic runtime approximation

This preserves systemic map generation while improving visual readability.

## Recommended Implementation Order

This is the recommended order of work.

### Phase 1. Stabilize the render contract

- keep current render hint export
- add stable `action_seq` / stronger state flags
- standardize the backend render payload as an explicit contract

### Phase 2. Separate authoritative state from presentation state

- keep raw snapshots
- maintain per-actor presentation state on the client
- stop driving animation from raw payload deltas

### Phase 3. Finish incarnation prediction

- make camera depend only on predicted render state
- make incarnation animation depend only on predicted motion / action intent
- keep backend reconciliation gentle and mostly invisible

### Phase 4. Rebuild humanoid animation control cleanly

- use one canonical animated character controller
- make locomotion use stable speed / direction inputs
- make attack / pain / down / get up event-driven

### Phase 5. Improve map embodiment

- better semantic-to-prefab mapping
- more authored asset placement rules
- optional editor preview or baked preview for test maps

## Recommended Immediate Next Steps

These are the best near-term tasks from the current state.

1. Turn the render payload into a stable documented contract.
2. Add `action_seq` or equivalent monotonic action trigger ids.
3. Keep using `server_time` for snapshot interpolation.
4. Push incarnation camera and animation fully onto predicted render state.
5. Simplify resident locomotion so it reads from smoothed presentation
   velocity and explicit locomotion hints only.
6. Build one reliable humanoid animation controller before trying to polish all
   residents equally.

## Design Rule Going Forward

The guiding rule should be:

- backend decides what is true
- client decides how to visually get there

Or more concretely:

- backend owns truth
- client owns feel

That is the design that preserves the memtensor interaction core while making
the game readable and smooth enough to play.
