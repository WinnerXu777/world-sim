# Control Implementation

Status: first semantic-control pass is now live.

Implemented baseline:
- `systems/control/` now exists as the semantic action layer
- `runtime/control_runtime.py` now delegates event normalization and
  command-state mutation to it
- semantic fields like `pending_semantic_action`, `control_context`, and
  `view_style` are now exposed alongside legacy control fields
- Godot now sends context/view-style hints with control snapshots and talk/click
  events
- legacy `pending_action` compatibility is intentionally preserved for existing
  runtime/UI consumers

This document defines the next control architecture for the incarnation /
human-mode path.

The main design choice is:

- Godot owns raw input, keybinds, mouse behavior, cursor mode, and camera feel
- `systems/control` owns semantic control actions and action routing
- runtime/backend owns authoritative execution

So the control module should not care whether an action came from:

- keyboard
- mouse
- rebinding
- future gamepad support

It should only care about semantic actions such as:

- `move`
- `look`
- `select_target`
- `attack_target`
- `work_on_target`
- `talk_command`
- `interact_target`
- `switch_mode`

## Core Split

### Godot / client layer

The client should keep ownership of:

- keybind mapping
- mouse sensitivity
- cursor capture / release
- first-person vs third-person camera feel
- god-mode map camera feel
- UI focus rules
- key rebinding persistence

This means the following stay client-side:

- `WASD`
- `Space`
- `G`
- `V`
- `T`
- mouse move
- wheel zoom
- modifier keys
- click combinations

### Control module

`systems/control` should convert raw input snapshots and click events into:

- semantic actions
- target-aware action selection
- mode-aware action resolution
- safe action payloads for the runtime

### Runtime / backend

The backend should remain authoritative over:

- whether an action is legal
- what the selected target really is
- what effect the action has
- how control actions map into task or immediate execution

## Current Base

The current project already has the start of this split:

- Godot input handling exists in:
  - `godot_client/scripts/main.gd`
  - `godot_client/scripts/human_mode_3d.gd`
- runtime control ownership already exists in:
  - `at_the_beginning/runtime/control_runtime.py`

Current live control/runtime support already includes:

- target claim / release
- manual movement submission
- manual event submission
- selected target tracking
- talk command submission
- camera mode switching on the client
- first-person / third-person toggling on the client

So this document is not inventing control from zero.
It is refining the control layer so it becomes explicit and modular.

## Main Goal

The control module should become the semantic action layer for the incarnation.

It should answer:

- what action does the player mean?
- which target should that action apply to?
- does the current mode allow that action?
- is this an immediate action, a task trigger, or a talk command?

## Control Contexts

The first important concept is `control context`.

The same raw input should mean different things depending on context.

### `god_context`

Used when the player is in god mode.

Allowed emphasis:

- map exploration
- free camera movement
- target inspection
- god decree targeting
- selecting entities or residents

Typical semantic actions:

- `pan_camera`
- `zoom_camera`
- `select_target`
- `inspect_target`
- `switch_mode`
- later `issue_decree`

### `human_fps_context`

Used in human mode with first-person camera.

Allowed emphasis:

- embodied movement
- look
- attack / work / interact
- talk
- target focus

Typical semantic actions:

- `move`
- `look`
- `jump`
- `select_target`
- `attack_target`
- `work_on_target`
- `interact_target`
- `talk_command`
- `switch_view`
- `switch_mode`

### `human_tps_context`

Same semantic action set as `human_fps_context`, but with a different camera rig
and aim interpretation.

### `talk_context`

Used while the player is actively typing or speaking.

Allowed emphasis:

- submit line
- cancel line
- preserve selected talk target

Gameplay motion and attack should be suppressed or softened here.

### `inventory_context`

Used while inventory or container UI is active.

Allowed emphasis:

- transfer
- equip
- drop
- inspect
- close UI

Regular embodied combat/work input should not fire through this context.

## Semantic Actions

The control module should normalize input into a stable set of semantic actions.

### Core movement / view

- `move`
- `look`
- `jump`
- `sprint`
- `pan_camera`
- `zoom_camera`

### Mode / camera

- `switch_mode`
- `switch_view`
- `toggle_cursor_capture`

### Targeting

- `select_target`
- `clear_selection`
- `focus_world_point`
- `inspect_target`

### Human embodied actions

- `attack_target`
- `work_on_target`
- `interact_target`
- `pickup_target`
- `use_item`
- `talk_command`

### Future manual actions

- `drop_item`
- `open_inventory`
- `open_container`
- `craft_request`
- `build_request`

## Action Families

The control module should also classify semantic actions by execution type.

### Immediate manual actions

These should usually stay outside resident task queues:

- `move`
- `look`
- `jump`
- `pan_camera`
- `zoom_camera`
- `switch_mode`
- `switch_view`

### Immediate embodied interactions

These are still player-driven, but they hit the world directly:

- `attack_target`
- `work_on_target`
- `interact_target`
- `pickup_target`

These should usually resolve through direct runtime handlers first.

### Talk actions

- `talk_command`

These should go through the talk runtime path.

### Task-triggering actions

Some manual actions may later create task requests instead of directly forcing
the result:

- `build_request`
- `craft_request`
- maybe future `follow_me`
- maybe future `deliver_this`

## Click Resolution

The most important part of the design is click resolution.

The control module should not treat click behavior as raw hardcoded buttons.
It should resolve clicks through:

- current context
- active modifier/action mode
- target type
- selected target

### Base rule

Left click without modifier should mostly mean:

- `select_target`

It should not be overloaded into every action.

This keeps the game readable.

### Force / weapon action

`Q + left click` is a good candidate for a forceful action modifier.

The meaning should be:

- resident / animal -> `attack_target`
- tree / wood source -> `work_on_target` with subtype `lumber`
- stone source later -> `work_on_target` with subtype `mine`
- breakable object later -> `attack_target` or `work_on_target` depending on tag

So `Q` should mean:

- "apply force or tool action"

not specifically:

- "always attack"

### Regular interaction

A separate regular interaction path should remain available.

Recommended semantic action:

- `interact_target`

This should be the path for:

- opening container
- speaking to a neutral target through UI prompt
- using workstation
- looting
- opening door later

### Talk targeting

For talk:

- `T` alone -> ambient talk
- `T` while a resident is selected, or `T + click resident` -> direct talk

So the talk path should preserve:

- `talk_mode`
  - `ambient_talk`
  - `direct_talk`
- `target_kind`
- `target_id`
- `target_name`

## Target Tags

To keep click resolution scalable, target resolution should become tag-based.

The control module should receive or infer target categories like:

- `human`
- `animal`
- `tree`
- `stone`
- `container`
- `structure`
- `resource`
- `ground`

Then action resolution becomes clean:

- `force_action + tree` -> `work_on_target:lumber`
- `force_action + human` -> `attack_target`
- `interact + container` -> `open_container`
- `talk + human` -> `talk_command:direct`
- `select + anything targetable` -> `select_target`

## Default Semantic Input Mapping

These are not final hardcoded keybindings.
They are the default semantic design the client should expose.

### Human mode

- `WASD` -> `move`
- mouse move -> `look`
- `Space` -> `jump`
- `Shift` -> `sprint`
- `V` -> `switch_view`
- `G` -> `switch_mode`
- `T` -> `talk_command`
- `E` -> `interact_target`
- `Q + left click` -> `force_action`
- left click -> `select_target`
- `Esc` -> `toggle_cursor_capture`

### God mode

- `WASD` or drag -> `pan_camera`
- mouse move with visible cursor -> inspection / hover only
- wheel -> `zoom_camera`
- left click -> `select_target`
- `G` -> `switch_mode`

## Suggested Action Payload Shape

The control module should emit normalized payloads like:

```json
{
  "controller_id": "local_player",
  "context": "human_fps",
  "action": "attack_target",
  "target_kind": "human",
  "target_id": "h_000031",
  "target_name": "Elias",
  "world": {"x": 410.2, "y": 288.5},
  "metadata": {
    "source": "force_click",
    "tool_mode": "weapon"
  }
}
```

Or:

```json
{
  "controller_id": "local_player",
  "context": "human_fps",
  "action": "work_on_target",
  "target_kind": "resource",
  "target_id": "entity_000141",
  "world": {"x": 512.0, "y": 302.0},
  "metadata": {
    "work_kind": "lumber"
  }
}
```

Or:

```json
{
  "controller_id": "local_player",
  "context": "human_fps",
  "action": "talk_command",
  "talk_mode": "direct_talk",
  "target_kind": "human",
  "target_id": "h_000044",
  "text": "Stay away from me."
}
```

## Runtime Flow

The desired flow is:

1. Godot reads raw input
2. Godot applies local feel:
   - cursor mode
   - mouse look
   - camera rig
   - rebinding
3. Godot sends normalized control events
4. `systems/control` resolves them into semantic actions
5. runtime applies them through:
   - direct control action path
   - talk runtime
   - task trigger path

So the control module becomes the semantic bridge, not the raw input reader.

## Module Shape

Suggested future structure:

- `systems/control/schema.py`
  - action payloads
  - context enums
  - target tag enums
- `systems/control/contexts.py`
  - valid action sets per context
- `systems/control/router.py`
  - normalize and route client events into semantic actions
- `systems/control/click_resolver.py`
  - target-aware click resolution
- `systems/control/mode_manager.py`
  - god vs human, fps vs tps semantic state
- `systems/control/prompt_view.py`
  - optional export/debug summaries
- `systems/control/ops.py`
  - stable public API

This should work alongside, not replace:

- `runtime/control_runtime.py`

The runtime remains the live owner of control sessions.
`systems/control` becomes the semantic action layer that the runtime can call.

## Current Runtime Relationship

The project already has:

- session ownership
- claim/release
- control event ingestion
- selected target state
- pending action state

So the next refinement should be:

- keep `runtime/control_runtime.py` as the live runtime/session owner
- make `systems/control` the semantic action interpreter

That mirrors the broader architecture:

- reasoning pipeline = intent orchestration
- task pipeline = execution orchestration
- control pipeline = player semantic action orchestration

## Current Boundary

This document does not say:

- how camera smoothing should feel
- how mouse sensitivity should be tuned
- what exact keybind menu UI should look like
- how rebinding persistence should be implemented on the client

Those belong to Godot/client work.

This document defines:

- semantic action vocabulary
- control contexts
- click resolution policy
- backend-facing action payload shape
- where the control module should sit in the architecture

## Recommended Next Step

After this doc, the next implementation pass should be:

1. scaffold `systems/control/`
2. formalize action/context schemas
3. move click/event semantic interpretation out of the ad hoc parts of
   `runtime/control_runtime.py`
4. keep Godot responsible for raw input and rebinding
5. start with:
   - `switch_mode`
   - `switch_view`
   - `select_target`
   - `talk_command`
   - `attack_target`
   - `work_on_target`
   - `interact_target`
