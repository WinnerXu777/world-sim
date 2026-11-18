# Client / Backend Boundary

This note defines the practical split for the incarnation path.

The goal is:

- keep the backend as the source of truth for world simulation
- let Godot own responsiveness and game feel
- preserve `m_tensor`, resident state, smart interactions, and orchestration

The short rule is:

- client may predict `presentation`
- backend must commit `truth`

That means:

- client can start movement, camera motion, target highlights, and animation immediately
- backend still decides what actually happened in the world

## Main Rule

### Client owns feel

The Godot client should own:

- keybinds and raw input sampling
- camera motion
- cursor capture and release
- local movement prediction
- interpolation and reconciliation
- animation choice and blending
- target assist and click forgiveness
- UI feedback such as highlights, reticles, hit flashes, and wind-up cues

### Backend owns truth

The backend should own:

- `m_tensor` and authoritative world state
- resident and animal positions
- legal movement resolution
- combat results
- HP, death, knockdown, and aftermath
- talk outcomes
- smart interaction results
- memory, planning, and orchestrator consequences

## What Must Stay Backend-Authoritative

These should never become client-decided:

- damage dealt
- whether an attack hit
- whether a target was in range
- whether a container actually opened
- whether a resident accepted, ignored, feared, or escalated a talk line
- inventory transfer truth
- plot, memory, goal, and consequence updates

The client can show likely motion or anticipation, but it cannot invent a real outcome.

## Current Project Hooks

Current live hooks already support this split:

- continuous control snapshots:
  - `godot_client/scripts/human_mode_3d.gd`
  - `POST /control/input`
- discrete semantic actions:
  - `godot_client/scripts/human_mode_3d.gd`
  - `POST /control/event`
- backend application:
  - `at_the_beginning/map_test.py`
  - `at_the_beginning/systems/movement/manual.py`

That means the project already has the right seam. The next step is to use it more deliberately.

## Ownership By Feature

### WASD movement

Client should own:

- reading `WASD`
- converting input to camera-relative motion
- locally moving the incarnation immediately
- smoothing camera follow
- blending idle, walk, run, start, stop, and turn animations

Backend should own:

- applying the true move to the controlled resident
- rejecting invalid movement if needed
- writing the real position into simulation state
- exposing the authoritative result in frame/view payloads

### Attack

Client should own:

- `H + click` targeting UX
- target highlight and target assist
- immediate wind-up / swing animation
- facing the target
- hit spark / anticipation feedback

Backend should own:

- deciding whether the target is valid
- distance / legality checks
- damage and death
- retaliation and social consequence logic
- orchestration packets and resident reaction follow-through

### Talk

Client should own:

- `T` input box
- `T + click` direct-target UX
- opening and closing the talk panel
- showing outgoing and incoming lines in the panel

Backend should own:

- who the actual target is
- whether the line is direct or ambient
- resident reply generation
- social consequence, memory, and escalation

### Interact / loot / store

Client should own:

- selection and hover/readability
- inventory window feel
- container panel transitions
- drag/drop and button UX

Backend should own:

- whether the target is interactable
- true inventory contents
- transfer legality
- crafting/storage consequences

## Example 1: WASD

This is the desired live contract for movement.

### Client-side sequence

1. Read `WASD` every frame.
2. Convert to camera-relative intent.
3. Move the incarnation locally for feel.
4. Blend the right animation.
5. Send the intent to the backend.

Current snapshot shape already looks like this:

```json
{
  "controller_id": "local_player",
  "target_kind": "human",
  "target_id": "h_000001",
  "seq": 128,
  "context": "human_tps",
  "view_style": "third_person",
  "move": {
    "x": 0.18,
    "y": 0.98
  },
  "buttons": {
    "attack": false,
    "interact": false,
    "sprint": true
  }
}
```

### Backend-side sequence

1. Receive `/control/input`.
2. Store it in the control runtime.
3. Build tick context.
4. Apply movement through manual control systems.
5. Update the resident's authoritative position.
6. Return that authoritative state in the next frame/window payload.

### What the client is allowed to fake

- start moving instantly
- show run animation instantly
- keep the camera smooth

### What the client is not allowed to fake

- the final authoritative position
- collision truth
- world consequences caused by reaching a spot

## Example 2: Attack

This is the desired contract for `H + click`.

### Client-side sequence

1. Player holds `H`.
2. Player clicks a resident.
3. Client uses target assist to pick the intended visible target.
4. Client highlights that target immediately.
5. Client starts attack anticipation animation immediately.
6. Client sends the semantic action to the backend.

Current event shape is already close:

```json
{
  "controller_id": "local_player",
  "seq": 204,
  "context": "human_tps",
  "view_style": "third_person",
  "event": "click_command",
  "action": "attack",
  "button": "left",
  "target_kind": "human",
  "target_id": "h_000004",
  "target_name": "Mara",
  "world": {
    "x": 512.0,
    "y": 488.0
  }
}
```

The stable semantic meaning behind that should be:

- `attack_target(target_kind, target_id)`

### Backend-side sequence

1. Validate the target.
2. Resolve whether the actor is in range or must move first.
3. Apply real combat logic.
4. Update HP / death / aftermath.
5. Emit combat and orchestrator outcomes.
6. Let resident reaction systems process the consequence.

### What the client is allowed to fake

- target highlight
- wind-up
- early swing animation
- temporary attack intent indicator

### What the client is not allowed to fake

- hit confirmation
- damage
- knockdown
- death
- resident emotional / social follow-through

## Practical Rule For This Game

Because the simulation is the main fun of the game, the safest split is:

- backend owns all meaningful world logic
- client owns readability and responsiveness

This is especially important for:

- resident memory
- revenge and escalation
- mock tiny-model social output
- mock reasoning output
- task and orchestrator follow-through

Those should remain backend-authored even if the front end becomes much smoother.

## Recommended Next Implementation Steps

### Near-term client improvements

- make targeting more forgiving in screen space
- keep polishing local movement prediction
- separate animation state selection from simulation state
- add cleaner hit feedback and target highlighting

### Near-term backend improvements

- keep semantic action packets explicit
- keep `/control/input` for continuous intent only
- keep `/control/event` for discrete semantic actions only
- preserve backend authority for smart interaction outcomes

## Safe Decision Test

When deciding whether logic belongs on client or backend, use this test:

- if it changes how the game `feels`, it can probably live on the client
- if it changes what is `true in the world`, it should live on the backend

For this project:

- smooth movement: client
- camera: client
- animation: client
- targeting assist: client
- attack result: backend
- inventory truth: backend
- resident reaction: backend
- memory / plot / orchestration: backend
