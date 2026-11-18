# Eden Design Logic

This folder is a repo-local reminder for future LLM work.

The goal is not just to make the current feature work.
The goal is to build reusable systems that can support strange future inputs without rewriting the architecture.

## Core Rule

Prefer:

- semantic high-level tools
- generic runtime channels
- target-specific adapters

Avoid:

- hardcoding one device or one control style into the world model API
- making render JSON the source of truth
- baking temporary UX choices into permanent instincts


## Authority Split

### Python backend is authoritative

The live simulation state lives in:

- `h_tensor`
- `m_tensor`
- runtime state such as control sessions, queues, and pending events

The backend decides what actually happens.

### JSON is a semantic protocol, not the source of truth

`/bootstrap`, `/frame`, and `/map_delta` exist for rendering and inspection.

Do not implement a feature by "overriding JSON."
Instead:

1. accept input or tools
2. apply them to live runtime or tensors
3. export the updated semantic snapshot


## Reusability Pattern

When designing a new feature, try to fit it into this shape:

### 1. Semantic tool layer

Use tools for high-level intent.

Examples:

- `tool_assign_control_target`
- `tool_release_control_target`
- `tool_set_control_target_mode`
- `tool_enter_vehicle`
- `tool_exit_vehicle`
- `tool_grant_instinct`

These are good world-model outputs because they describe **what** should happen, not device details.

### 2. Generic runtime channel

Use a runtime channel for fast, local, device-shaped input.

Examples:

- `POST /control/input`
- `POST /control/event`

These are good for:

- `WASD`
- mouse clicks
- analog movement
- throttle / brake / steer
- gesture-like control later

This channel should stay generic enough for future targets such as:

- humans
- cars
- boats
- mounts
- turrets
- machines

### 3. Target-specific adapter

The same input channel can mean different things for different controlled targets.

Examples:

- human adapter: move vector directly changes walking motion
- car adapter: input becomes steering + acceleration
- horse adapter: input becomes direction + stamina-aware speed
- crane adapter: input maps to joint or arm commands

This is the right place to specialize behavior.


## Instinct Design Rule

Do not create instincts named after devices or UI events.

Bad examples:

- `instinct_wasd`
- `instinct_on_click`
- `instinct_mouse_attack`

Better:

- `instinct_player_control_override`
- `instinct_vehicle_control`
- `instinct_mount_control`
- `instinct_manual_interaction_override`

Instinct names should describe simulation behavior, not the keyboard or mouse.


## New Skill / Instinct Generation Rule

Only generate a new instinct or tool after all three checks:

1. the execution agent verifies the requested behavior is not already in the registry
2. existing deterministic code paths are insufficient
3. the generated code passes validation and runtime loading

Then:

1. load/register it
2. assign or grant it through normal tools
3. add it to LightRAG only after it is real and usable

This avoids polluting the system with duplicate or imaginary skills.


## Generated Tool Rule

For generated code, prefer this pipeline:

1. semantic tool wrapper
2. domain resolver
3. domain `ops` helper import
4. shared low-level mutation helper behind the ops layer

Good generated code should usually import from:

- `systems.health.ops`
- `systems.nature.ops`
- `systems.construction.ops`
- `systems.movement.ops`
- `systems.perception.ops`
- `systems.combat.ops`
- `systems.social.ops`
- future `systems.inventory.ops`
- future `systems.interaction.ops`

Reason:

- smaller open-source models are better at composing a few stable helpers
- they are worse at inventing safe tensor math from scratch
- the `ops` layer gives a narrow, reusable API surface

### Prefer this

```python
from systems.health.ops import apply_plague

def tool_poison_cloud(ctx, h_tensor, mask=None, **_):
    h_mask = ctx["h_mask"]
    affected = (mask & h_mask) if mask is not None else h_mask
    if not affected.any():
        return {}
    apply_plague(affected, h_tensor, decay_rate=4.0, infection_gain=12.0)
    return {}
```

### Avoid this

```python
h_tensor[affected, 3] -= 4.0
h_tensor[affected, 8] += 12.0
h_tensor[affected, 15] += 10.0
```

The second version is harder to validate, easier to break, and much worse for weaker models.


## Ops-First Rule

When adding a new reusable behavior:

1. first ask whether an existing domain `ops` helper already covers it
2. if not, add or extend a helper in the right domain
3. then make the tool/instinct call that helper

This is better than generating one-off tensor logic inside every new tool.

### Good progression

1. add `systems.health.ops.damage_humans`
2. add `systems.nature.ops.trigger_storm`
3. generate a new tool that composes those helpers

### Bad progression

1. generate a new tool
2. embed raw tensor writes in it
3. repeat with slightly different raw writes in the next tool

The good version builds a reusable library. The bad version creates drift and duplication.


## Small-Model Rule

Assume future code generation may use sub-30B open-source models.

That means:

- keep helper names regular and obvious
- keep signatures short
- prefer domain-specific verbs over clever abstractions
- prefer composition over custom tensor logic
- keep examples and templates close to the repo

If a small model can solve the task by copying a nearby pattern and changing 2-3 values,
the design is likely good.


## Control Design Rule

Do not make raw keypresses into world-model tools.

Bad:

- `tool_wasd_move`
- `tool_spacebar_attack`

Good:

- `tool_assign_control_target`
- runtime input snapshot `{move, buttons, aim_world}`

Reason:

- world models should reason semantically
- render/input clients should speak in local device events
- backend runtime should translate those events into simulation effects


## Click Command Rule

Do not create one-off click tools such as:

- `tool_click_move`
- `tool_click_attack`
- `tool_click_interact`

Instead:

1. keep clicks on the runtime event channel
2. send explicit semantic click actions like `move`, `attack`, `interact`, `select`
3. include optional `world` and target metadata
4. let the target adapter decide how to apply that action

Example runtime event payload:

```json
{
  "event": "click_command",
  "action": "move",
  "button": "right",
  "world": {"x": 420.0, "y": 180.0},
  "target_kind": "entity",
  "target_id": "e_000042",
  "target_name": "horse"
}
```

This keeps the protocol reusable for:

- click-to-move
- click-to-attack
- click-to-interact
- click-to-follow
- click-to-harvest
- click-to-build


## Future-Proof Input Rule

When adding a new input feature, ask:

1. Can this be represented as a generic control field?
2. Can this be reused by more than one target type?
3. Can the target-specific meaning live in an adapter instead of the protocol?

Examples:

- `move` can work for humans, animals, drones, boats
- `aim_world` can work for combat, harvesting, construction, cameras
- `buttons.attack` can later become target-specific primary action
- `buttons.interact` can later become enter/use/pickup/talk depending on target


## Dynamic Entity Rule

For new entities:

- create semantic metadata first
- register type IDs and art metadata
- keep the execution/runtime interface stable

Avoid wiring new entity behavior directly into the frontend first.
Backend semantics should come first.


## Good Default Mental Model

Use this stack:

1. decree or prompt chooses a semantic goal
2. world model emits semantic JSON
3. execution agent validates against local truth
4. runtime applies the result to tensors or session state
5. frontend renders exported semantic snapshots

For live possession:

1. world model or UI claims control semantically
2. Godot sends generic control input
3. backend adapter applies it to the controlled target
4. tensors update
5. `/frame` reflects the result


## Short Checklist

Before implementing a feature, prefer "yes" to these:

- Is the feature semantic at the tool layer?
- Is the fast input path generic?
- Is specialization pushed into an adapter/runtime?
- Does the backend remain authoritative?
- Can the same design work for a future non-human target?
- Can the same protocol survive a different renderer or camera mode?

If not, redesign before hardcoding.
