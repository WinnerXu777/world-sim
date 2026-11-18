# Codex client implementation — 2026-10-10

Status: implementation and focused verification complete for this handoff; Gate F and live acceptance remain owed. No roadmap status or decision register edits were made.

## Implemented

- R5.1: real game enables streaming only for explicit client opt-in plus bootstrap `world.infinite`; loader uses the actual configured backend URL and resets cache identity/center on world change. Chunk addressing adds int64 window chunk origin to local camera/actor chunk offsets. Ground placement subtracts int64 chunk origin before any Vector2 conversion, including near the 2**40 range. Missing palette art never creates an invalid TileMap cell. Existing nearest filtering retained.
- Decorative `data.props` uses the actual generator `prop_palette`, imported sprite pivots, and the authored overworld foot-depth root. Chunk replacement/unload retires its decorative root. `data.spawns` and chunk entity descriptions never instantiate local interactive rows or actors: authoritative animals/residents continue to come from frames and entity state from map delta.
- DR-3 handoff is IMPLEMENTED and focused-tested: loader preserves descriptor `placement_origin_absolute_units`; a pinned map already in bootstrap reuses its verified MapView. Otherwise ground uses the explicit absolute-unit pair (integer subtraction before floats, including a non-chunk-aligned remainder), one stable map-ID view, and reference-based unloading across repeated descriptors. No guessed origin. Standalone pinned views are ground-only, not a new interactive map registration or production-art claim.
- R5.2: window stamps are validated, initialized from bootstrap, and reset explicitly even without tick rollback. Rebase shifts only space-0 histories, map roots, cached presented positions, authoritative entity anchors/shape points, and the overworld camera. Interior pockets keep their layout coordinates. Chunks reproject to current origin. Free camera focus, portal/nearby entity anchors, attack wall checks and space-local conversion use shifted origins. Opted-in infinite overworld removes finite map clamp/void mask; finite worlds and interior clamps stay intact.
- 409 `stale_window_epoch`: one bounded/coalesced GET refresh emits a frame consumed by the game, checks connection generation, and never replays the refused mutation. An independent late refresh cannot look like world rollback. Late map-delta rows are translated from their payload stamp into the current frame. Existing mutation epoch plumbing in possession/portal/commission/god paths was inspected and retained.
- R5.4: actual CanvasModulate uses bounded finite light and season colors, restores white when calendar block is absent, and stays separate from HUD CanvasLayers.

## Files

Edited: `godot_client_2d/scripts/game/game.gd`, `scripts/net/chunk_loader.gd`, `scripts/net/frame_ingest.gd`, `scripts/net/world_client.gd`, `scripts/net/map_sync.gd`, `scripts/net/space_view.gd`, and `godot_client_2d/tests/test_r5_regression.gd`. Existing AGY registration of that regression in `c2_checks/run_spaces.py` retained. Existing panel/possession epoch additions inspected. No portal-worker files or chunk backend files edited by this chat.

## Actual verification

Commands used installed console via `EDEN_GODOT=C:/Users/Rita/Downloads/Godot_v4.6.2-stable_win64.exe/Godot_v4.6.2-stable_win64_console.exe`:

- `.venv/Scripts/python.exe godot_client_2d/c2_checks/run_spaces.py` — exit 0, `C2_SPACES_PASS`, `FRAME_INGEST_PASS`, `SNAPSHOT_BUFFER_PASS`, `R5_REGRESSION_PASS` on final client source. Evidence: `godot_client_2d/c2_checks/test_r5_regression.out.txt` and corresponding per-script logs/output files.
- `.venv/Scripts/python.exe godot_client_2d/tests/run_chunk_loader_test.py` — `CHUNK_LOADER_PASS`, exit 0, including the final rerun after cache-metadata changes.
- Godot `--check-only` on `res://tests/test_r5_regression.gd` — exit 0.

The R5 regression exercises real game scene coordinate consumers and actual canvas colors, negative/rebased positions, fixed interior histories, far-origin chunk and pinned placement, malformed window rejection/reset, finite/interior camera clamp, unknown terrain cells, real imported prop sprite/pivot/depth parent and replacement cleanup, map-ID dedupe/reference unload, descriptor origin preservation, no local actors from spawn descriptions, late map delta translation, late refresh suppression, stale input and portal command POST non-replay, and concurrent refresh coalescing.

Initial regression execution found a missing `props_root` metadata read on ground-only pinned unload; fixed with `has_meta` and the full focused runner then passed. Godot's sandbox emits the already documented Windows root-certificate-store diagnostic for these HTTP-only checks; runners explicitly allow only that diagnostic. A first manual parse call without a workspace `--log-file` crashed because `user://logs` was inaccessible; subsequent calls use workspace logs.

## Remaining evidence / scope

No real backend Godot window walk, portal_spaces live runner, seam screenshot, production/collision-art acceptance, FPS measurement, or strict golden/full suite was run here. A heavy lock take aborted without tests; other worker owns `.runtime/fullsuite.lock` (NORMAL baseline/after sweep). The coordinator clarified that short targeted tests are allowed under NORMAL, so the checks above ran without overriding its lock. Heavy live validation remains for the next lock owner.

R5.1 remains PARTIAL/DONE* for acceptance: decorative scatter and authoritative actor streaming are wired; new interactive chunk-resource sprite/depletion presentation and standalone pinned authored decoration/footprint layers are not delivered by this ground-only path. Missing production terrain/art and mixed-biome seam decisions are not silently resolved. R5.2/R5.4 are implemented and focused-tested, but live/visual acceptance is owed.

Exact existing user questions to carry through the coordinator if needed: DR-14, “Which target machine and frame-rate target should Gate F acceptance use?” DR-5, “Which mixed-biome tile junction priority should be used, and are visual seam masks needed?” No OPEN decision was taken here. No defaults changed, no installs, no commits/pushes, no destructive Git or cleanup operations.
