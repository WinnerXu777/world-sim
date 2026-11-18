# R5.3 creature client handoff — 2026-10-10

Status: renderer/ingest/index plumbing implemented and focused-tested. Actual local H008 bundle publication is owned by the coordinator/importer; live and visual acceptance remain owed. Prior R5 client/rebase/409 fixes preserved. R5.8 portal files untouched.

## Actual edits

Only `godot_client_2d/scripts/game/actor_view.gd`, `scripts/net/frame_ingest.gd`, `scripts/game/game.gd`, new `tests/test_creatures_client.gd`, and this report.

- Ingest deep-copies the whole animals[].creature dictionary into actor information AND snapshot metadata, retaining species, sprite, footprint, state and variant. Invalid/non-dictionary blocks are ignored. Legacy animals still have no creature field. Existing space/rebase history behavior remains intact.
- Game reads `data/production_index.json` only when its exact SHA-256 matches `import_lock.production_index_sha256`. It consumes the documented assets dictionary: source_set, resource_path, pivot, render_scale and original metadata. It selects matching H008 species and variant, idle south/east and actual `dead/side` poses; canonical side becomes the renderer's dead_e. West mirrors east. It never loads arbitrary wire paths; frozen wire sprites can fall back only through existing imported asset_index entries.
- Actor renderer keeps root at authoritative contact position and uses manifest pivots at display scale. West mirroring adjusts the offset for asymmetric pivots, preserving contact. Motion uses one static directional pose plus at most 0.6 display-pixel body bob; root/collision positions do not move. Idle/rest/dead stop bob. Actual dead art stays full size rather than the resident down squash. No fake walking frames, physics, species-ID changes or alpha-derived collision.
- Absent/missing art displays a species/variant-labelled footprint placeholder. Legacy animal placeholders and resident art behavior are preserved. Snapshot presentation updates species/variant art selection as needed; space filtering, Y-depth parents and origin shifts stay in the established game path.

## Focused validation actually run

Installed console: `C:/Users/Rita/Downloads/Godot_v4.6.2-stable_win64.exe/Godot_v4.6.2-stable_win64_console.exe`.

- `--headless --path godot_client_2d --log-file coordination_evidence/codex_creatures_client.log --script res://tests/test_creatures_client.gd` — exit 0, **CREATURES_CLIENT_PASS**.
- `EDEN_GODOT=<console> .venv/Scripts/python.exe godot_client_2d/c2_checks/run_spaces.py` — exit 0, **C2_SPACES_PASS**, **FRAME_INGEST_PASS**, **SNAPSHOT_BUFFER_PASS**, **R5_REGRESSION_PASS** after renderer edits.
- Godot `--check-only` on `res://scripts/game/game.gd` — exit 0.

New test covers full metadata roundtrip/deep copy, malformed/absent creature block, negative overworld rebase versus fixed interior histories, static south/east/west poses, asymmetric contact pivot on west mirroring, body-only bob bounds, rest/dead no bob, vertical heading retaining side dead pose, nearest filter, missing-art species/footprint labels, legacy fallback, real game space filtering, production side-pose schema consumption, index hash binding prerequisite and untrusted wire-path rejection.

Direction/pose tests use in-memory textures; the production-index consumption test uses a known imported texture as a MOCK entry, not proof that H008 art is published. First run assumed frozen sheep art was in the current default bundle and failed; inspection confirmed it is absent. The corrected test verifies known imported-reference fallback independently and missing-art behavior honestly. The first failed script was stopped, a watchdog was added, and final tests passed. The known sandbox Windows root-certificate-store diagnostic appears for headless HTTP-only checks; no other engine/script errors remain.

## Art handoff / remaining evidence

At initial mock validation, the default import bundle had no published H008 production index. The coordinator has since published the hash-bound local bundle and imported it through Godot. This chat added a conditional real-resource integration check to the existing creature test and reran it: exit 0, CREATURES_CLIENT_PASS, log `coordination_evidence/codex_creatures_published.log`. With the real index present it checks wolf south/east/dead loading, actual mirrored east texture for west, and actual corpse texture on death; absent publication prints an explicit mock-only notice. The coordinator separately verified all 33 poses/all ten species. Frozen sheep art is still absent from the legacy asset_index. No PNG/manifest/import_lock/production_index was written by this chat. Root's local static review/selection remains distinct from motion/collision/public-release acceptance; canonical art manifests and frozen backend sprite contract remain unchanged.

No live Godot walk, screenshot/readability, direction-lighting consistency, corpse/asleep readability, performance/target-machine or collision-art acceptance was run here. DR-7 remains OPEN: “Which walking animation approach and budget should be used?” Existing static direction/bob behavior does not decide that art spend. R5.8 runner and portal tests remain owned by the prior portal worker/coordinator. No defaults, installs, commits, pushes or backend/art edits.
