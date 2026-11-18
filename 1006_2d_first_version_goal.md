# Proposed goal — first playable Eden 2D version

Draft only. The user will activate this goal explicitly.

```text
/goal Coordinate Codex and Claude Code to deliver the first playable Eden game in Godot 2D, following implementation_1006_2d_rebaseline.md through P0–P7 / Gate H, with models disabled.

Act as the Codex orchestrator, without personally implementing game code or generating assets. Direct the authorized Codex worker chat “Start game with 2D assets” (local thread 01a1142d-cf61-7233-b42c-370b0be61166) on assets, authored world construction, Godot 2D presentation and client integration. Claude Code owns backend simulation, Python map loading/validation and authoritative gameplay. Coordinate through 1006_communication_scratchpad.md, respecting documented file ownership and avoiding overlapping edits. You are authorized to message the Codex worker and retrieve its reports throughout this goal.

Read the whole active scratchpad at the start and end of each work chunk. Keep detailed reports and verbatim archived entries in 1006megathread.md. Trim the active scratchpad regularly after archiving; preserve rules, settled decisions, ownership, unanswered questions, blockers and current handoffs. Keep entry IDs monotonically increasing across rotations. Relay material changes once, label worker claims versus verified results, and record open decisions explicitly.

First settle C-002/C-003 with Claude: sprite conventions, backend units/pixel scale, walk speed and actor radius, authored collision footprints, shared JSON schema, stable sprite/entity/anchor IDs, portals, map revision and file location. Existing suggestions are proposals, not approvals. Codex owns art references and authored map content; Claude owns Python schema/loader/validation. Respect Claude's reserved paths listed in the scratchpad. Verify the user's snapshot confirmation before large restructuring, deletion or commits; do independent bounded work while that gate is pending.

Deliver in tested increments: a Godot 2D scene importing myassets; one shared authored village map with matching backend/client collision; server-authoritative player possession and movement with interpolation; three scheduled NPCs; a scripted smith request→accept/refuse→reserve→work→deliver loop that persists without duplication, using a rules-only DecisionProvider seam; god camera, heal, resource spawn, weather and possession return; then a coherent village with 8–12 named residents, usable buildings/interiors, portraits and essential animations; finally onboarding, New/Continue, UI, save/reload, reconnect handling and a reproducible launch path.

Prefer the user's local voiceimage generator for asset batches, review candidates in the game, and record source, tool/model, prompt/settings and license status in manifests. Reuse suitable existing art; replace or resolve uncertain-license assets before release. Keep a consistent art bible, foot pivots, four-direction movement, Y sorting, nearest filtering and integer zoom.

Preserve the frozen 3D client, web viewer and existing Arcade exploration. Do not maintain their feature parity or port Arcade's local authoritative simulation into production. Add no prediction/replay, camera-obstruction work or model-driven NPC decisions before Gate H. The 1006 addendum overrides conflicting older plans.

Completion requires the actual Godot client connected to the actual Python backend: map/anchor/portal validation passes; walls block movement; NPC schedules run; the smith loop succeeds and survives reload exactly once; god powers change authoritative state; save/continue and reconnect work; and a recorded 20–30 minute playthrough completes with models disabled. Use proportionate automated checks and real visual verification, report limitations honestly, and provide launch instructions and a concise final evidence report. Do not declare success based only on prototype tests, mocked backend checks or screenshots. Ask the user only for unresolved decisions or required approvals; continue independent authorized work while waiting.
```
