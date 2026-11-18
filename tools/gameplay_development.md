# Current gameplay development workflow

This is an intermediate development build. Gameplay starts at New Game / Continue; connecting does not create a world. F6 opens the save menu. A selected world autosaves every 60 seconds when its tick has changed; normal server shutdown also saves after stopping the simulation and draining an active writer. Force-killing the process can lose changes since the last complete checkpoint. Manual Save remains available. Restart with the **same data root** to see your saves, then select Continue. The original `Data_Storage` resident/save data is not used by the new launch configuration.

From the repository root, launch a fresh isolated gameplay backend:

```powershell
$env:EDEN_PROFILE = 'gameplay'
$env:EDEN_PORT = '8012'
$env:EDEN_DATA_ROOT = Join-Path (Get-Location) ('.runtime/playtest-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe at_the_beginning/map_test.py
```

In another terminal, launch the normal 3D scene:

```powershell
godot --path godot_client --log-file C:/Users/Rita/Desktop/world_simulator/.tmp/gameplay.log -- --profile=gameplay --backend-url=http://127.0.0.1:8012
```

Press Enter to control a nearby resident. WASD moves; Shift sprints; V changes perspective; T opens conversation; I toggles inventory. The current HUD still includes some development labels that will be replaced during UI work. Gameplay F5 cannot reset the world, and QA pose controls are inactive.

Inspect the active profile, timing, and save errors:

```powershell
Invoke-RestMethod http://127.0.0.1:8012/status
```

Run focused regressions and an isolated backend timing sample:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
.\.venv\Scripts\python.exe tools/measure_simulation.py --seconds 10
```

Capture opening, physical-key walking, and camera orbit against the isolated backend:

```powershell
godot --path godot_client --log-file C:/Users/Rita/Desktop/world_simulator/.tmp/gameplay_capture.log --resolution 1400x980 --script res://tests/gameplay_capture.gd -- --profile=gameplay --backend-url=http://127.0.0.1:8012 --create-test-world
```

Evidence is written under `.tmp/implementation_0905/`. This is an integration capture, not the QA virtual motor or a performance benchmark. Existing PNGs at those evidence paths are replaced by a new capture.

The explicit `--create-test-world` flag lets the capture create a world when the backend is empty. Use only isolated data. `res://tests/session_menu_smoke.gd` instead exercises the New/Save/Continue menu callbacks against a fresh isolated gameplay backend; its captures are `session_menu.png` and `session_village.png`.

World checkpoints use compressed, data-only JSON generations with SHA-256 validation and an atomically replaced manifest. They include tensors, stable IDs, inventory, resident records, runtime tasks/queues, geometry, tick, and RNG state. A corrupt latest generation falls back to an earlier complete generation. Restoring clears control ownership and creates a fresh world epoch. Legacy save import, comprehensive migration validation, asynchronous resident sidecar writes, and the command authority protocol remain in progress.

Control clients must send `protocol_version: 1`, the current `world_epoch`, and the `possession_epoch` returned by claim or the control snapshot on `/control/input` and `/control/event`. Movement also identifies its controlled `target_kind` and `target_id`; event target fields refer to the interaction target. Both Godot clients supply these fields. Older external clients need updating. `last_input_seq` means received; `last_applied_input_seq` means a movement snapshot has been consumed by a completed simulation tick. It does not acknowledge successful execution of a discrete action. Full prediction replay and command-result tracking remain pending.

Movement and discrete events share a maximum 64-command ingress queue per possession and are consumed in sequence order at tick boundaries. `last_consumed_command_seq` reports consumption of either type, not a successful domain outcome. Excess requests are rejected. After 0.75 seconds without accepted input, controls neutralize; after five seconds, possession releases. These are wall-clock deadlines. A disconnected client must poll and explicitly reclaim a resident after release; stale possession tokens cannot resume control.

`/inventory/transfer` and `/inventory/equip_main_hand` now require a canonical UUID `command_id` plus protocol/world/possession/controller fields. They return HTTP 202 with `status: received`; poll `/commands/{command_id}` for `applied` or `rejected`. Retry the identical payload and ID to retrieve the same receipt/result. Never invent a new ID merely because the response was lost. Both Godot clients generate an ID and wait for the final result. A transfer is allowed only between the controlled resident and a live container within the current provisional 30-unit reach. `res://tests/inventory_command_smoke.gd` verifies client result polling against a fresh isolated server.

For the separate visual QA workflow, start the backend with `EDEN_PROFILE=render_fixture` and a fresh data root, then use `--profile=animation_qa` or the existing explicit QA capture arguments. The explicit QA capture may reset that development fixture; never point it at a world you want to retain. Model-provider integration and TTS remain deferred. Lexical retrieval is the default and does not load pretrained weights.

Gameplay now advances `scripts/app/ground_player_motor.gd` in `_physics_process`; render updates do not integrate the controlled actor. It reads walk/sprint speed and swept obstacle bounds from the server contract. Version 1 uses immediate input velocity, matching `systems/movement/manual.py`, and does not carry position corrections into momentum. The character node presents motor position and facing. The old acceleration/export settings apply only to animation QA. Missing spatial contracts hold at the authoritative position. Replacing a possession/world epoch resets prediction even when the resident ID is unchanged.

Reconciliation still uses temporary position correction toward snapshots; applied-input replay and a separate interpolated visual correction remain unfinished. `tests/ground_player_motor_validation.gd` checks motor speeds, stopping, collision, render independence, and epoch reset. `tests/gameplay_capture.gd` records short movement timing/error samples; these are diagnostics, not a 20–30 minute performance benchmark. Check the actual viewport/capture dimensions rather than assuming a requested window resolution was honored.

Authoritative manual movement is integrated once by `instinct_move`; the later manual-action phase executes interactions/combat only. The speed regression exercises real ticks in both runtime profiles. Gameplay frames the camera once when taking control, so a held movement key cannot be redirected by repeatedly selecting a nearby startup interest point. User mouse orbit remains available. Capture diagnostics include applied input sequence, last input result, sent direction and snapshot age to support the remaining reconciliation work.

Control sessions now include `committed_state` with protocol/world/possession/target identity, full-precision position, `last_applied_input_seq`, and `completed_tick` (zero-based tick just executed). This is captured after collision and only replaced at tick commit. Before the first tick after claim it is null. Root `last_input_seq` can advance when packets arrive; it must not be paired with the committed position for replay. Godot validates snapshot identity/order and uses its exact position. A held input can advance several committed ticks with one applied sequence, so dropping/replaying history solely by sequence is not yet a complete reconciliation algorithm.

The current replay path additionally uses `input_applied_seconds`: simulated held duration of the active movement sequence at commit. It trims that portion of the client's recorded physics samples and resimulates all remaining movement through the shared collision contract. Direction/sprint changes issue an immediate request; periodic input remains a heartbeat. History is capped at 128 samples/0.75 seconds, and concurrent movement requests at eight. If history fills, local prediction holds until newer snapshots arrive. Old servers without the duration field use the interim correction path. A separate visual correction interpolator and full delayed reconnect/action validation remain unfinished.

Run `res://tests/movement_history_validation.gd` headlessly for replay regression checks. For a live test against isolated backend data, add `--test-250ms-rtt --create-test-world` after `--` to `tests/gameplay_capture.gd`: this uses a test-only subclass with 125 ms delay each way and records three seconds of ordinary movement. It creates a fresh test world explicitly. Capture data distinguishes raw snapshot distance from replay correction; neither this short test nor unit-test delay injection certifies the complete gameplay/network gate.

Player presentation now smooths replay corrections independently of the motor. `player_presentation.gd` accumulates a visual offset, decays it at 12 Hz, clears it for corrections over three units or a changed possession, and clips it against the shared walls/bounds. The character node and following camera use this visual position; the motor, replay and control calculations keep corrected simulation position. `tests/player_presentation_validation.gd` checks continuity, frame-rate independence and clipping. This is correction smoothing, not full interpolation between physics steps.

Third-person camera placement now sweeps against the shared wall volumes and ground, pulling inward immediately and recovering outward smoothly. Near-plane padding prevents the lens from crossing the wall; wall height allows a clear view above it. The camera does not hide surrounding actors/chunks. Objects with no shared geometry remain outside this coverage. Run `tests/camera_obstruction_validation.gd` headlessly; for explicit geometric comparison screenshots, run it with a renderer and append `-- --capture-camera`. That fixture is separate from the ordinary gameplay capture.

Normal gameplay now exports dirty residents through a background writer: at most 16 serialized resident copies per wall-clock second, with revision-aware acknowledgment and retry. A completed old revision cannot clear newer changes. New/Continue share the writer's lock; shutdown drains a started disk job before writing the final world checkpoint. Per-resident write failures remain in `/status` persistence errors. Retry timing does not depend on simulation ticks, so a paused world can recover from a transient file lock. Development profiles retain synchronous exports. Coherent checkpoint generations remain the source for loading a complete world; individual resident exports do not constitute a world transaction.

Local mutation authorization and discrete event retry behavior are documented in [local_control_protocol.md](local_control_protocol.md). Manual POST requests now require the bootstrap capability header. Add `--test-event-retry` to the isolated gameplay capture to verify event ID generation and consumed-receipt reuse through Godot.

Human combat now checks the same live wall boxes used by movement/replication. A closed ground-plane segment from attacker to target cannot intersect or touch a wall, including when an endpoint is embedded. Blocked attempts spend no combat stamina and apply no damage; identified manual attacks return `blocked`. Destroyed walls stop blocking. This does not cover decorative props without shared collision data, height-dependent attacks or arbitrary 3D line of sight.

Animal visual assets now fit their imported rest-mesh bounds to `projection.height` in meters, with a ground-centered anchor and uniform scale on an outer `MeterScale` node. Animation resources and rig transforms are preserved. This replaces source-size-dependent species multipliers. Current backend projection heights are still broad categories (ordinary animals 1.05 m, predators 1.25 m), not a completed species sizing policy. Heights include the full rest-mesh envelope, including antlers; shoulder heights and animated bounds need separate metadata if introduced.

Run `res://tests/animal_scale_validation.gd` headlessly for source-asset rest-bound checks. `res://tests/animal_scale_capture.gd` is a separate GPU fixture with a 1.8 m reference column; it is not ordinary gameplay evidence.
