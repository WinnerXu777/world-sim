# HumanMode3D Visual QA

This project needs the Python backend before `HumanMode3D` can populate chunks,
actors, inventory, and render-test village data.

## Backend

From the repository root:

```powershell
.\.venv\Scripts\python.exe .\at_the_beginning\map_test.py
```

The backend should answer:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/bootstrap -TimeoutSec 5
```

## Godot MCP Loop

Use Funplay MCP in this order:

1. `install_runtime_bridge` with `save=true` if capture/query tools need it.
2. `enter_play_mode` with `mode="main"` and `restart_if_running=true`.
3. Wait 10-15 seconds for `/testing/render_test_village` and `/human_view/window`.
4. `get_runtime_bridge_status`; verify `node_count` is much larger than the base
   20-node scene and that `TerrainRoot` / `ActorRoot` are populated.
5. `capture_runtime_view` to `res://human_mode_runtime_capture_XXs.png`.
6. `get_console_logs` with `severity="error"`.
7. Repeat captures at roughly 0s, 5s, 15s, and 30s when checking animation or
   camera behavior over time.

## Fallback Godot Capture Loop

If the editor is open but Funplay tools are not exposed to Codex, use the
main-scene capture pass to verify the backend-populated player camera:

```powershell
godot --path godot_client --resolution 1400x980 res://scenes/HumanMode3D.tscn -- --human-mode-qa-capture
```

This saves a clean player-camera sequence:

- `godot_client/human_mode_auto_00_opening.png`
- `godot_client/human_mode_auto_01_walk_forward.png`
- `godot_client/human_mode_auto_02_walk_diagonal.png`
- `godot_client/human_mode_auto_03_talk.png`
- `godot_client/human_mode_auto_04_attack.png`
- `godot_client/human_mode_auto_05_hit.png`
- `godot_client/human_mode_auto_06_fall.png`
- `godot_client/human_mode_auto_07_get_up.png`

The same pass also saves front/side animator-inspection frames for the core
gesture states:

- `godot_client/human_mode_auto_03b_talk_front.png`
- `godot_client/human_mode_auto_03c_talk_side.png`
- `godot_client/human_mode_auto_04b_attack_front.png`
- `godot_client/human_mode_auto_04c_attack_side.png`
- `godot_client/human_mode_auto_05b_hit_front.png`
- `godot_client/human_mode_auto_05c_hit_side.png`
- `godot_client/human_mode_auto_06b_fall_front.png`
- `godot_client/human_mode_auto_06c_fall_side.png`
- `godot_client/human_mode_auto_07b_get_up_front.png`
- `godot_client/human_mode_auto_07c_get_up_side.png`

Use the dedicated human animation lane to verify bodies and gestures directly in
Godot from a wider inspection camera:

```powershell
godot --path godot_client --resolution 1400x980 res://scenes/HumanVisualQA.tscn -- --human-visual-qa-capture
```

This opens a short windowed run, saves:

- `godot_client/human_visual_qa_auto_00_overview.png`
- `godot_client/human_visual_qa_auto_01_upper_body_locomotion_talk.png`
- `godot_client/human_visual_qa_auto_02_reactions_attack_fall_getup.png`

and then quits. The overview keeps labels visible; the two detail captures hide
labels so arm, shoulder, spine, head, and reaction poses can be inspected without
text covering the body.

## Runtime Input

For WASD movement checks through Funplay, send physical key events. In testing,
raw `key="W"` did not affect `Input.is_physical_key_pressed(KEY_W)`, while
`physical_key="W"` moved the controlled actor.

If window focus or key-hold state is flaky, use the file-driven virtual
controller instead. This is intended for visual QA only: it moves the local
predicted presentation/camera without sending movement to the backend control
endpoint, so it can inspect animation and framing without changing backend
truth.

```json
// godot_client/visual_qa_controller.json
{
  "enabled": true,
  "move": { "x": 0.0, "y": 1.0 },
  "sprint": false,
  "move_nonce": 1,
  "move_duration_msec": 900,
  "action": "",
  "action_nonce": 0,
  "clean_view": false,
  "hide_ui": true
}
```

For repeatable captures, increment `move_nonce` and set `move_duration_msec`
between 700 and 1200. The virtual move self-expires after that window even if
the file remains enabled, which makes it safe to capture walking frames over
time without manually racing to reset the file. Set `move_duration_msec` to `0`
when you want the old manual `enabled=true/false` behavior. The file is polled
by `HumanMode3D` at runtime. Virtual movement is deliberately scaled down by
`visual_qa_virtual_move_speed_scale` in `human_mode_3d.gd` so short captures stay
inside the authored inspection area. Use real WASD / physical-key input when you
need to verify backend-authoritative control packets.

To trigger one-shot controlled-human animations in the real scene, set
`action` to one of `talk`, `attack`, `pain`, `fall`, `get_up`, or `idle`, then
increment `action_nonce`. Example:

```json
{
  "enabled": false,
  "move": { "x": 0.0, "y": 0.0 },
  "sprint": false,
  "move_nonce": 1,
  "move_duration_msec": 0,
  "action": "attack",
  "action_nonce": 3,
  "clean_view": false,
  "hide_ui": true
}
```

Useful checks:

- Capture a baseline frame after the village loads, then write a timed virtual
  move with `move_nonce += 1`, capture during the 700-1200 ms window, and capture
  once more after it expires.
- Trigger a gesture by changing `action` and incrementing `action_nonce`, then
  capture immediately and again after 1-2 seconds.
- Reset `enabled=false`, `move={ "x": 0.0, "y": 0.0 }`,
  `move_duration_msec=0`, and `action=""` before ending the test.
- Press physical `W` for 2-3 seconds, release it, then query
  `/root/HumanMode3D/ActorRoot/h_000001.position`.
- Capture before and after movement to verify the camera follows and the walk/run
  animation stays upright.

## Current Priority Checks

- The first third-person view is not inside trees, props, or terrain.
- The controlled human is readable within the first few seconds.
- Walk/run/talk/attack/fall/get-up can be triggered and visually captured.
- Runtime logs stay free of Godot script errors.
