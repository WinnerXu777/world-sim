# Gate H acceptance plan

Coordinator working plan, 2026-10-07. This is a verification plan, not a completion report. The 1006 rebaseline and active goal remain authoritative.

## Current evidence (coordinator review, 2026-10-07 22:47)

- Eight residents and four authored maps are integrated. Coordinator previously validated map registration, all resident bindings and the art handoff. The current import lock has 47 assets, four maps and 20 copied provenance records; its SHA256 is `5a8828df3d066e876ae221848a229e8f16925b01e5c76b06cfd301ed8d5c7f20`, matching the final recording.
- Claude reports 557 backend tests and 13 live Godot checks passing after the fixes in C-024/C-025. Coordinator has read current live pass markers; independent backend verification ran all 557 tests in 280.116 seconds with no assertion failures and 13 sandbox PermissionErrors across ten cases. Those ten affected cases passed in 0.531 seconds when rerun outside the sandbox; this is split verification, not a single clean unsandboxed full-suite run. Historical 529/535-test failures remain historical evidence, not current results.
- Final recording attempt 3 is under `godot_client_2d/evidence/gate_h/final/20261007-153224/`: 1207.73 seconds of video against 1207.75 seconds of bot elapsed time, 12 segments and 101 passing checks, normal 45-second forge, gameplay profile, rules provider, actual process restart and Continue. Coordinator inspected the report, structured results, recorder configuration and representative video-decoded refusal/Continue frames; coordinator has not independently decoded the complete video.
- The run delivers three legitimately commissioned swords across two customers, with repeated collection returning a duplicate receipt. Exactly-once applies to each order, rather than requiring the whole world to contain only one sword.
- Heal remains a full-health no-op: receipt `healed=0`, `hp_before=hp_after=100`, `god_event_id=null`. Actual restoration and a resulting heal memory/reaction remain unverified. The recording passes its own checks but does not close all Gate H requirements.
- Sustained outage, map-revision refusal and transient recovery have separate harness evidence; the final recording contains restart recovery. Asset release rights and credits are under review, including A3 additions omitted from the older 33-asset audit. No public release clearance is claimed.
- Claude retains client/backend implementation ownership per C-024. Coordinator owns verification/communication; Codex workers have bounded provenance and read-only healing/recovery reviews, with no overlapping client edits.

## Evidence required before recording

1. Validate every authored map together, including all portal targets, sprite references and resident anchor bindings. Check registered origins and stable IDs against the actual launch configuration.
2. In the actual Godot game, see eight named residents with distinct portraits and four or five body templates. Confirm usable interiors, nearest filtering, foot Y sorting, integer zoom and essential idle/walk/talk/attack/hit/down presentation. Simple effects are acceptable where the rebaseline permits them.
3. Possess, walk and sprint; stop flush against a wall; enter and leave interiors. Release possession and observe at least three scheduled NPCs reaching different anchors without uncommanded teleports or persistent wall stalls.
4. Use normal recipe duration for the final smith loop: real-state refusal, acceptance, resource reservation, work, one delivery and remembered outcome. Save and restart the backend, Continue, then verify the same order and exactly one sword. Attempt repeated collection through the normal command path and verify no second delivery.
5. Exercise heal, resource spawn and weather through UI. Observe authoritative state changes and a later NPC response. Enter and leave god mode and verify possession ownership.
6. Exercise an active temporary outage and process restart through the supported launch/recovery path. Check held poses, suspended intent, fresh capability/bootstrap/maps, cleared state on a new epoch, explicit save selection where needed and no automatic replay of mutations.
7. Confirm New/Continue, onboarding/help, inventory, dialogue, refusal reasons and Save and quit. Preserve existing saved-world behavior; explain any authored-map revision limitations.
8. Inspect asset provenance and credits. Resolve or replace uncertain release assets; a local evaluation build and a distributable release have different proof requirements.

## Recorded 20-30 minute run

Use the actual Godot client and Python backend, a fresh isolated data root, gameplay profile and normal time/recipe settings. Capture the game over the full run, with timestamps and backend/client logs. Do not substitute a headless tick soak, montage or still screenshots for temporal recording.

Suggested sequence: New and onboarding; village movement and scheduled NPC observation; smith refusal and accepted work; delivery; god powers and NPC response; Save, backend restart and Continue; confirm no duplicate delivery; visit the expanded interiors; release/repossess; save and exit. Include normal uninterrupted play between checks. Keep actual elapsed time between 20 and 30 minutes.

Record the launched configuration and /status model_mode. Confirm no external model handlers are configured and the commission DecisionService uses RulesDecisionProvider. Mock deterministic fallback flags may be true; do not confuse those names with an enabled external model. Capture representative frame and backend tick timing once.

Final report must identify exact launch command, data root/save ID, map revisions/hashes, client/backend versions, recording path and duration, test commands/results, verified behaviors and remaining limitations. Leave Gate H incomplete if any required behavior or evidence is missing.

## Recording method audit (2026-10-07)

Coordinator inspected installed Godot 4.6.2 help: `--write-movie` forces fixed FPS and `--fixed-fps` disables real-time synchronization. Official [Godot 4.6 movie documentation](https://docs.godotengine.org/en/4.6/tutorials/animation/creating_movies.html) permits near-real-time capture and documents OGV in editor builds, AVI's 4 GB limit, and graceful quitting to finalize containers. These establish candidate methods, not installed codec capability or recording acceptance.

Before the final run, pilot the chosen recorder for actual GPU gameplay, file size, supported container, frame rate, wall-clock pacing and graceful completion. A MovieWriter fallback must retain normal backend wall-clock progression and prove monotonic elapsed 20–30 minutes with matching video duration; fixed-delta animation timers alone cannot prove this. OBS/ffmpeg absent from PATH and standard Program Files top-level checks; no exhaustive disk search or installation performed. Actual live client control-path automation is acceptable; mocked frames and direct authoritative-state manipulation are not final playthrough evidence.
