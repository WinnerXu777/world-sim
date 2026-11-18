# Web Frontend Implementation Plan

## Purpose

This document defines how to build a browser-based frontend for the Eden world
simulator while keeping the Python backend authoritative.

The main goals are:

- make the project easier to iterate on than a traditional engine-first client
- preserve the existing simulation, orchestration, memory, and control systems
- support a strong `god view` first
- support a later `human mode` if desired
- target `2D` or `2.5D` presentation that works well on the web

The core architectural decision is:

- the browser owns `presentation`
- the Python backend owns `truth`


## Short Version

Yes, the web stack is a good fit for this project if the visual target is:

- `2D`
- or `2.5D`
- or `high-angle semantic world rendering`

The web stack is especially strong for this project because the backend already
exports semantic JSON over HTTP rather than requiring engine-native scene state.

The recommended first stack is:

- `React`
- `TypeScript`
- `Vite`
- `Three.js`

Why this stack:

- React is very good for tool-heavy UI, panels, feeds, inspector views, and
  operator controls
- Three.js is very good for a hybrid world renderer with real 3D terrain,
  buildings, props, depth, lighting, and camera transforms
- 2D or 2.5D humans and creatures can still be rendered efficiently as
  billboards or lightweight sprite cards inside the 3D scene
- Vite keeps local iteration fast and simple
- TypeScript helps keep the protocol contract sane as the client grows

Important distinction:

- `npm` is the package manager and project tooling path
- `PixiJS` or `Three.js` would be the rendering engine


## Recommended Product Direction

Do not try to replicate the full current Godot 3D ambition in phase 1.

The strongest web version of this project is:

- a simulation-first strategy and control client
- a readable god view
- a rich inspector and timeline UI
- a responsive selection and command model
- a hybrid presentation with 3D world geometry and 2D or 2.5D actors

This means the browser client should prioritize:

- map readability
- entity readability
- fast camera movement
- high signal overlays
- control responsiveness
- debugging visibility
- good tooling around decrees, control, and inspection

This is a much better fit for the current backend than trying to begin with:

- complex skeletal 3D characters
- heavy animation trees
- third-person embodied action feel
- engine-specific scene authoring pipelines


## Main Rule

### Backend owns truth

The Python backend remains authoritative for:

- simulation ticks
- human and animal state
- map entity state
- combat legality and outcomes
- inventory truth
- memory and relationship state
- orchestration
- talk results
- structured world actions

The browser must not invent real outcomes.

### Frontend owns presentation

The web client should own:

- rendering
- interpolation
- camera movement
- selection UX
- hover states
- highlights
- overlays
- panel layout
- timeline and event feed display
- optimistic presentation where appropriate

The browser may predict how things should look.
The backend still decides what actually happened.


## Why Web Is A Good Fit Here

The current backend already has the right shape for a web client.

It already exposes:

- `GET /bootstrap`
- `GET /frame`
- `GET /map_delta`
- `POST /control/claim`
- `POST /control/release`
- `POST /control/input`
- `POST /control/event`
- `POST /god_decree`

That means the rendering layer is already decoupled from the simulation layer.

This is the most important reason the web path is viable.

The frontend does not need to understand:

- raw tensors
- internal Python movement systems
- resident memory storage internals
- tool registry execution internals

It only needs stable semantic payloads.


## Why Not Start With A Full Game Engine

A traditional engine is still valid, but it introduces extra complexity early:

- scene import and asset pipeline complexity
- engine-specific scripting and tooling
- runtime/editor mismatch
- 3D camera and animation tuning overhead
- more work to build rich sim-debugging UI

For this project, the hard problem is not:

- drawing triangles

The hard problem is:

- making a simulation-heavy world readable and operable
- exposing AI, control, memory, and event state clearly
- iterating quickly on the frontend/backend contract

The browser is excellent at those tasks.


## Why 2D Or 2.5D Is The Right Scope

`2D` is the safest and most productive scope.

Benefits:

- fastest implementation
- easiest readability
- simplest hit testing and selection
- easiest asset strategy
- lowest client complexity
- easiest UI composition

`2.5D` is also reasonable if handled carefully.

A good 2.5D version would mean:

- top-down or angled camera
- sprites or lightweight 3D-ish cards
- layered depth sorting
- height hints where useful
- simple building silhouettes
- optional tilt and shadow for depth cues

A strong hybrid version would mean:

- real 3D ground, cliffs, buildings, and large props
- a constrained high-angle camera rather than a free exploration camera
- humans and creatures rendered as billboard sprites or lightweight 2.5D cards
- selection, hover, command, and state overlays rendered clearly above the world
- consistent scale, lighting direction, and shadow treatment between 3D and 2D layers

Avoid in phase 1:

- full free-camera 3D exploration
- heavy skeletal animation dependence
- first-person immersion as the main product


## Chosen Frontend Stack

## Core stack

- `Vite`
- `React`
- `TypeScript`
- `Three.js`

## Supporting libraries

- `zustand` for app state
- `@tanstack/react-query` for request orchestration where useful
- `zod` for runtime payload validation
- `clsx` for UI class composition

Optional:

- `@react-three/fiber` for React-friendly scene composition if desired
- `@react-three/drei` for helpers and camera controls
- `immer` if state update ergonomics become painful


## Why Three.js First For The World

Three.js is the best first world renderer here if the project wants:

- real 3D terrain and structure rendering
- camera transforms
- glTF or mesh-based buildings and props
- depth, occlusion, and lighting cues
- 2D or 2.5D characters placed into a readable high-angle world
- semantic overlays
- good performance without full game-engine overhead

Three.js is a rendering engine, not a full gameplay framework.
That is a strength for this project because gameplay truth already lives in the
Python backend.

The frontend does not need:

- physics as source of truth
- full local world simulation
- a large built-in gameplay runtime

It needs a world renderer that can mix real 3D scenery with lightweight actor
presentation and simulation UI.


## When To Use Phaser Instead

Phaser would make sense if the browser client becomes more game-like and needs:

- built-in scene management
- built-in physics helpers
- stronger sprite animation tooling
- a more traditional game-loop API

For the current project, Phaser is not the first recommendation because:

- the app is simulation-first and UI-heavy
- React + Pixi gives a cleaner split between app UI and world canvas
- the backend already owns most domain logic


## How To Use Three.js Safely

Three.js should be used with these constraints:

- angled 2.5D environments with real meshes
- imported glTF buildings and props
- billboarding in real 3D space for humans and creatures
- lighting and depth cues that 2D fakes do not cover well
- a mostly fixed or constrained camera angle

Recommended rules:

1. keep the camera high-angle and readable
2. use 3D for terrain, buildings, trees, and large props
3. use 2D or 2.5D sprite cards for humans, animals, and creatures
4. do not depend on skeletal rigs for the first playable version
5. keep the React app shell and backend contract intact

This gives the project depth and atmosphere without forcing a full character
animation pipeline on day one.


## Repo Layout

Create the frontend as its own project:

```text
game_frontend/
  implement.md
  package.json
  tsconfig.json
  vite.config.ts
  index.html
  src/
    main.tsx
    app/
      App.tsx
      providers.tsx
      router.tsx
    game/
      world/
        WorldCanvas.tsx
        ThreeWorld.tsx
        camera.ts
        layers/
          terrainLayer.ts
          structureLayer.ts
          mapEntityLayer.ts
          humanBillboardLayer.ts
          animalBillboardLayer.ts
          overlayLayer.ts
      protocol/
        api.ts
        schema.ts
        types.ts
        polling.ts
      state/
        uiStore.ts
        simStore.ts
        selectionStore.ts
        controlStore.ts
      controls/
        input.ts
        commandBuilder.ts
      ui/
        panels/
          statusPanel.tsx
          inspectPanel.tsx
          decreePanel.tsx
          eventFeed.tsx
          controlPanel.tsx
          inventoryPanel.tsx
        hud/
          topBar.tsx
          bottomBar.tsx
          modeTabs.tsx
      utils/
        colors.ts
        geometry.ts
        ids.ts
        time.ts
```

Important design rule:

- keep protocol, renderer, and UI as separate layers

Do not mix:

- raw fetch code
- world state normalization
- canvas rendering logic
- panel rendering logic

inside one component.


## Frontend Architecture

## Layer 1: Protocol layer

This layer is responsible for:

- calling backend endpoints
- validating payloads
- normalizing shape differences
- tracking versions
- exposing typed results to the rest of the client

Files:

- `src/game/protocol/api.ts`
- `src/game/protocol/schema.ts`
- `src/game/protocol/types.ts`
- `src/game/protocol/polling.ts`

Rules:

- never let rendering code depend on loose `any` payloads
- validate backend payloads at the edge
- convert payloads into stable client-side types immediately


## Layer 2: Simulation view state

This is the frontend-side mirror of what is currently visible.

It should contain:

- current world dimensions
- current frame id
- current map version
- humans by id
- animals by id
- map entities by id
- visible events
- current control session state
- current inventory focus payload
- current talk feed payload

This layer should not duplicate backend truth beyond what is needed for view.

It is a cache and presentation state layer, not a second simulation engine.


## Layer 3: Renderer

The renderer is responsible for:

- drawing terrain or semantic map cells
- drawing map entities
- drawing humans
- drawing animals
- drawing overlays
- camera pan and zoom
- interpolation between server frames
- hit testing for click and hover

Renderer rules:

- renderer reads normalized state only
- renderer does not fetch directly
- renderer does not own business logic
- renderer does not own command semantics


## Layer 4: UI shell

The React app shell handles:

- top bars
- tabs
- panels
- event feed
- decree entry
- inspector
- inventory
- talk panel
- debug controls

This layer should be conventional React UI and should not know Pixi internals.


## Data Contract Strategy

The current backend contract is already close to enough for phase 1.

The frontend should treat these payload families as separate concerns:

### Bootstrap payload

Used for:

- world size
- initial map entities
- initial versions
- startup render parameters
- initial feature flags

### Frame payload

Used for:

- humans
- animals
- despawns
- control state
- events
- inventory focus
- talk feed
- status snapshots

### Map delta payload

Used for:

- map entity upserts
- removals
- version increments

Important rule:

- static-ish world data and fast actor data should remain separate

That is already a good design choice and should be kept.


## Protocol Types To Define First

The web client should define stable TypeScript types for:

- `WorldInfo`
- `BootstrapPayload`
- `FramePayload`
- `MapDeltaPayload`
- `HumanView`
- `AnimalView`
- `MapEntityView`
- `ControlSessionView`
- `EventView`
- `InventoryFocusView`
- `TalkFeedView`

Then add `zod` schemas beside them.

Reason:

- backend shape drift is one of the most common causes of frontend pain
- runtime validation catches issues early
- typed normalized models make rendering code much simpler


## Backend Changes Recommended Before Or During Web Migration

The backend can already support a first web client, but a few upgrades will
make the migration smoother.

## 1. Add CORS

If the frontend runs on a different dev port, the browser will need CORS.

Add:

- `CORSMiddleware`

Dev allowance can be broad at first.
Later, tighten allowed origins.


## 2. Add explicit protocol versioning

Keep or strengthen:

- protocol version string
- payload version markers if needed

The frontend should be able to fail clearly if the contract changes.


## 3. Add timestamps to frame payloads

If not already present everywhere needed, make sure frame payloads include:

- server tick
- server time or monotonic time
- frame id

This helps interpolation and stale frame handling.


## 4. Prefer stable render hints

For actors, the frontend benefits from consistent fields such as:

- `id`
- `kind`
- `name`
- `x`
- `y`
- `vx`
- `vy`
- `moving`
- `facing`
- `action`
- `locomotion`
- `hp`
- `max_hp`
- `selected`
- `claimed`

The browser can infer some of this, but stable hints reduce visual noise.


## 5. Consider WebSocket or SSE later

Phase 1 can use polling.

That is fine.

But later, a push channel would help with:

- lower-latency updates
- better event streaming
- fewer redundant requests
- smoother possession and control responsiveness

Do not block phase 1 on this.


## Rendering Plan

## Phase 1 visual style

Phase 1 should use a clean simulation map style, not ambitious character art.

Recommended style:

- simple low-detail 3D terrain or large ground planes
- readable 3D buildings and props with restrained geometry
- simple humans and animals as billboard sprites or lightweight 2.5D cards
- lightweight shadows
- clear labels on hover or selection
- strong overlay colors for important state

This will let the project succeed quickly.


## Camera behavior

The world view needs:

- pan
- zoom
- smooth follow when controlling a human
- reset-to-fit
- optional selection focus

Use world coordinates consistently.

Never let rendering invent its own coordinate system unrelated to backend space.


## Layer plan inside the world renderer

Recommended draw order:

1. terrain
2. static structures
3. resource props and large map entities
4. animals
5. humans
6. labels
7. overlays
8. selection and command indicators

This keeps the view readable.


## Interpolation plan

The renderer should interpolate actor motion between authoritative frames.

Basic strategy:

1. store previous authoritative snapshot
2. store latest authoritative snapshot
3. on each render frame, interpolate positions by local render time
4. snap only when the error exceeds a threshold

This is enough for phase 1.

Do not begin with heavy prediction logic for all actors.

For the locally controlled human later:

- allow local presentation prediction
- reconcile to backend truth


## Input And Control Plan

The frontend should support two major operating modes:

- `god view`
- `human control`

Both modes should live inside the same web app.

Important rule:

- do not build two separate clients

Instead build:

- one shared protocol layer
- one shared world state store
- one shared renderer
- two camera and input modes
- mode-specific overlays and panels


## Human mode is fully viable in web

The browser can support `human mode` well as long as expectations are correct.

The web version of human mode should be:

- simulation-authoritative
- presentation-responsive
- semantically driven

That means:

- the browser should make movement and actions feel immediate
- the backend should still decide what actually happened

This is already aligned with the current backend design.

The browser client does not need to become a second gameplay engine.

It needs to do these things well:

- follow the controlled actor
- capture input cleanly
- send intent to the backend
- render anticipation and feedback
- reconcile to authoritative results


## Mode switching contract

Switching between `god view` and `human control` should be treated as a
frontend mode change plus, when needed, a control-session change on the
backend.

The browser should always know:

- current view mode
- current claimed target id
- current claimed target kind
- whether claim is pending
- whether release is pending
- whether local input is enabled

Recommended frontend mode enum:

- `god`
- `human`

Recommended frontend control state:

- `unclaimed`
- `claiming`
- `claimed`
- `releasing`
- `claim_failed`


## God-to-human switch flow

The switch from god mode into human mode should work like this:

1. user is in `god` mode
2. user selects a human actor
3. user clicks `Claim` or `Enter Human Mode`
4. frontend calls `POST /control/claim`
5. backend confirms claim or rejects it
6. if confirmed, frontend sets mode to `human`
7. camera begins following the claimed actor
8. input routing changes from map navigation to actor control

Important rule:

- do not switch the app into true control mode until the backend confirms claim

The frontend may show a temporary claiming state, but it should not pretend the
control session is real before confirmation.


## Human-to-god switch flow

The switch back to god mode should work like this:

1. user presses `Escape`, clicks `Release`, or chooses `Return to God View`
2. frontend calls `POST /control/release`
3. frontend clears local human-control-specific UI state
4. app returns to `god` mode
5. camera either stays centered on the actor briefly or returns to prior god
   camera state

Recommended camera behavior:

- store the last god-mode camera position and zoom
- restore that state when returning from human mode

This makes switching feel deliberate rather than jarring.


## Shared renderer, different camera behavior

The same world renderer should serve both modes.

What changes by mode is:

- camera target
- zoom level
- input mapping
- overlay emphasis
- visible UI chrome

In `god` mode:

- the camera is free
- zoom range is broad
- overlays emphasize world state and selection
- panels emphasize inspection and world management

In `human` mode:

- the camera follows the controlled actor
- zoom range is tighter
- overlays emphasize nearby targets, actions, and interaction opportunities
- panels emphasize control, talk, interaction, and inventory


## Human mode rendering plan

Human mode in the browser should not begin as a full 3D embodiment layer.

The right first version is:

- close-follow top-down or slightly angled view
- controlled human clearly highlighted
- nearby interactables readable
- immediate input responsiveness
- target and action cues rendered clearly

This gives a convincing playable mode without requiring:

- skeletal rigs
- complex authored animation trees
- engine-level character controllers

The controlled human can still be a billboard or 2.5D card inside a 3D world.


## Input mapping by mode

The app should route the same hardware inputs differently depending on mode.

### God mode input map

- `left click` = select actor or entity
- `drag` = pan camera
- `wheel` = zoom
- `double click` = focus actor or entity
- `hotkeys` = open decree, status, inspect, filter, follow

### Human mode input map

- `WASD` = movement intent
- `Shift` = sprint intent if supported
- `left click` = select or context target
- `hotkeys` = attack, talk, interact, inventory, release control
- `Escape` = release control or open pause/control menu

Important rule:

- keep mode-specific keybinds visible in the UI

Do not rely on the user memorizing invisible state changes.


## God view input

God view should support:

- click selection
- drag pan
- wheel zoom
- box select later if needed
- issue decree through panel
- click-based semantic actions where useful

Likely first commands:

- inspect entity
- follow actor
- claim control target
- send decree


## Human control input

Human control can be added after god view is solid.

Inputs should map to backend semantic control rather than local gameplay logic.

Use the existing control endpoints:

- `POST /control/claim`
- `POST /control/input`
- `POST /control/event`
- `POST /control/release`

The browser should send:

- movement intent
- sprint or action buttons
- click-target semantic actions
- talk commands
- interact commands

The browser should not decide:

- whether the action succeeded
- damage
- interaction legality


## Human mode interaction loop

The frontend human-mode loop should be:

1. read raw input every render frame
2. convert raw input into semantic intent
3. update local presentation immediately
4. send intent through `/control/input` or `/control/event`
5. receive authoritative frame updates
6. reconcile local presentation against backend truth

This is the correct browser equivalent of the intended Godot control split.


## Action rendering model

Actions in the browser should be rendered through three different channels:

1. persistent actor state
2. short-lived action cues
3. authoritative event confirmation

Using all three is important.

If the app only uses actor state, actions will feel vague.
If the app only uses events, actions will feel delayed.
If the app only uses frontend anticipation, actions will feel fake.


## 1. Persistent actor state

Each visible actor should expose state that informs continuous rendering.

Examples:

- `idle`
- `moving`
- `talking`
- `attacking`
- `interacting`
- `damaged`
- `dead`

These should drive:

- icon or sprite choice
- facing direction
- locomotion appearance
- health bars
- nameplate treatment
- selection treatment


## 2. Short-lived action cues

These are brief visual effects that make actions legible immediately.

Examples:

- attack wind-up ring
- slash arc
- target outline
- hit flash
- speech bubble
- interaction pulse
- path preview
- ground reticle
- damage number
- status icon pop

These cues are presentation-only.

They should make the action readable, but they should not invent backend truth.


## 3. Authoritative event confirmation

The frontend should also render the backend-confirmed outcome.

Examples:

- event feed entry
- combat result text
- talk transcript line
- opened inventory panel
- state change icon
- death marker

This layer is what makes the simulation feel real rather than purely cosmetic.


## Action rendering by action family

### Movement

Movement should be rendered using:

- interpolated actor position
- facing direction
- locomotion marker or animation state
- optional predicted movement for the locally controlled actor

For non-player actors:

- use interpolation only

For the locally controlled actor:

- allow modest local prediction
- reconcile gently when backend truth arrives


### Attack

Attack should be rendered in stages:

1. immediate target highlight
2. immediate attacker wind-up cue
3. optional slash arc or swing effect
4. backend-confirmed hit or miss result
5. confirmed target flash, damage number, or death marker

Important rule:

- only render confirmed damage after backend confirmation

The browser may anticipate the swing.
The browser should not invent the hit result.


### Talk

Talk should be rendered using:

- target highlight
- speech indicator on speaker
- talk panel update
- reply display only after backend response exists

Useful cues:

- speech bubble glyph
- temporary line ribbon over the actor
- conversation linking line for targeted speech


### Interact

Interact actions should be rendered using:

- hover affordance on interactable object
- interaction pulse or ring
- short progress cue if needed
- result panel only when backend confirms validity

Examples:

- open storage
- inspect object
- craft at station
- use door


### Damage and death

Damage and death need especially clear rendering because they carry major
consequence.

Recommended cues:

- hit flash
- health bar reduction
- damage number
- knockback or shake cue if available
- death tint or collapse marker
- event feed confirmation


## Render hints the backend should export for action readability

For the browser to render actions well, actor payloads should consistently
include the best available action-facing fields.

Recommended fields:

- `id`
- `x`
- `y`
- `vx`
- `vy`
- `moving`
- `facing`
- `direction_world`
- `locomotion`
- `action`
- `action_started_tick`
- `target_id`
- `hp`
- `max_hp`
- `is_controlled`
- `is_selected`

Not every field is mandatory on day one, but the browser should move toward
depending on explicit render hints instead of ad hoc inference.


## Action overlay system

The renderer should implement overlays as a separate layer rather than baking
them into actor sprites.

Suggested overlay categories:

- selection overlays
- hover overlays
- command previews
- combat cues
- talk cues
- interaction cues
- status markers

Why:

- overlays have different lifetimes than actors
- overlays often need independent fade timing
- overlays are easier to debug when isolated


## Event-driven visual effects

Some effects should be spawned from backend events rather than actor state.

Good candidates:

- damage pop
- death marker
- relationship change icon
- task completion pulse
- decree impact highlight

This allows a short-lived effect to appear even if the underlying state moves
on quickly.


## Human mode UI additions

When in `human` mode, the UI should shift emphasis.

Recommended human-mode HUD elements:

- controlled actor badge
- current target badge
- action hotbar or command strip
- quick talk input
- nearby interaction hint
- compact health and status display
- release-control button

Recommended behavior:

- keep the HUD compact
- keep the world readable
- avoid covering the center of the screen with large panels


## First browser version of human mode

The first human-mode implementation should aim for:

1. claim a human
2. camera follow
3. render controlled actor differently
4. send movement intent
5. send semantic click actions
6. render attack, talk, and interact cues
7. release back to god mode cleanly

That is enough to prove the concept.

Do not wait for:

- full animation sets
- complex sprite atlases
- deep inventory polish
- dialogue cinematics

before shipping the first human-mode pass.


## UI Plan

The browser version should lean into what the web is best at:

- dense but readable tool UI
- side panels
- inspector panels
- searchable lists
- event timelines
- debug overlays
- status dashboards

Recommended phase 1 panels:

- `Status`
- `Inspector`
- `Events`
- `God Decree`
- `Control`

Recommended phase 2 panels:

- `Inventory`
- `Talk`
- `Memory / Relationship`
- `Task Queue`
- `Orchestrator`


## The Minimum Viable Web Client

The MVP should not try to do everything.

The MVP should do these things well:

1. connect to backend
2. fetch bootstrap
3. poll frame
4. poll map delta
5. render map entities
6. render humans and animals
7. support pan and zoom
8. support selection
9. show a status panel
10. show an inspect panel
11. show recent events
12. send a god decree

If these twelve things work well, the web migration is already a success.


## Phase Breakdown

## Phase 0: Scaffold

Create:

- Vite app
- React app shell
- Pixi canvas mount
- base directory layout
- API client
- environment config

Deliverable:

- blank app that can talk to backend health or status endpoint


## Phase 1: Protocol and state

Implement:

- typed API client
- bootstrap fetch
- frame polling
- map delta polling
- normalized stores

Deliverable:

- frontend logs and stores valid world data


## Phase 2: Readable god view

Implement:

- world canvas
- map entities
- humans and animals
- camera pan and zoom
- selection and hover
- status and inspect panels
- event feed

Deliverable:

- usable sim viewer for the live backend


## Phase 3: God controls

Implement:

- decree panel
- entity selection actions
- claim target
- release target
- follow target

Deliverable:

- usable world-operator client


## Phase 4: Human control

Implement:

- claim and release control
- movement input
- semantic action events
- local camera follow
- action feedback

Deliverable:

- browser-based incarnation prototype


## Phase 5: Polish and hybrid uplift

Implement selectively:

- sprite upgrades
- depth cues
- richer 3D buildings and props
- better overlays
- animation hints
- optional angled presentation

Deliverable:

- visually richer web client without changing backend authority


## 2.5D Upgrade Path

If the team wants a stronger hybrid identity after the first playable version,
do it in this order:

1. add better actor sprites or 2.5D cards
2. add shadows and elevation hints
3. add roof fade, occlusion rules, and depth sorting
4. add richer 3D buildings and terrain variation
5. add stronger lighting and atmospheric depth without changing backend truth

This avoids a premature full-character-3D jump.


## Performance Strategy

The frontend should assume the world may grow.

Performance rules:

- normalize all entities by id
- avoid full React rerenders for every frame tick
- keep mesh, material, and sprite reuse high
- separate static map rendering from dynamic actor rendering
- update only changed map entities on map deltas
- batch overlay redraws where possible

Do not push every actor update through deep React component trees.

React should own UI.
Three.js should own world drawing.


## Error Handling Strategy

The frontend should gracefully handle:

- backend offline
- malformed payloads
- protocol mismatch
- stale map versions
- control claim failure
- slow frame polling

User-visible states should include:

- connecting
- connected
- degraded
- disconnected
- protocol error


## Asset Strategy

Do not block the frontend on final art.

Phase 1 assets should be:

- simple 3D buildings and terrain pieces
- generated shapes or low-detail props
- simple actor sprites or silhouette cards
- simple icons and overlays

Phase 2 can add:

- stylized unit sprites
- improved 3D structures and props
- item icons
- state icons

The product should succeed visually through clarity first, not asset volume.


## Testing Strategy

The frontend should be testable without relying on manual visual guessing alone.

Recommended test layers:

- type and schema validation tests
- protocol normalization tests
- store update tests
- command-builder tests
- a few browser smoke tests

Add Playwright later for:

- app boots against backend
- bootstrap renders visible actors
- selection works
- decree submit works


## Risks

## Risk 1: Backend payload drift

If payload shapes change frequently without version discipline, frontend work
will become frustrating.

Mitigation:

- define TypeScript schemas early
- version payloads
- keep normalization isolated


## Risk 2: Trying to build both 2D and 3D at once

Mitigation:

- keep the world/actor split disciplined
- use 3D only for environment readability and depth
- keep humans and creatures lightweight in phase 1


## Risk 3: Mixing frontend app logic with renderer logic

Mitigation:

- keep React UI separate from Three.js world code
- keep protocol code separate from both


## Risk 4: Overbuilding local simulation in the browser

Mitigation:

- keep the client as presentation and control only
- do not duplicate backend world rules


## Risk 5: Polling limits smoothness

Mitigation:

- use interpolation first
- add push transport later only if needed


## Final Recommendation

The project should move forward with:

- `Python + FastAPI` as the backend authority
- `game_frontend/` as a new browser client
- `React + TypeScript + Vite + Three.js` as the first implementation stack
- `hybrid god view` with 3D world rendering and 2D or 2.5D actors as the first product target

Then later:

- add browser-based human control
- add richer actor art and hybrid polish if the simpler version proves useful

This path is the best balance of:

- implementation speed
- maintainability
- readability
- backend reuse
- low migration risk


## Immediate Next Steps

The next implementation step after this document should be:

1. scaffold the Vite frontend
2. add backend CORS support
3. define TypeScript protocol types and schemas
4. connect to `/bootstrap`, `/frame`, and `/map_delta`
5. render a simple hybrid god view with a 3D world, actor billboards, pan,
   zoom, and selection

If those steps are completed, the web migration is officially underway in a
sound way.
