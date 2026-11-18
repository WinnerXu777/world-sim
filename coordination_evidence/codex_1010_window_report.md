# Codex R6.6 repair — 2026-10-10

Implementation complete; focused tests pass. Strict-golden/full-suite/live acceptance remains for coordinated heavy validation. This supersedes the failed AGY caller-introspection/consumed-boolean implementation.

## Wire contract and actual integration

`window_wire.stamp(engine)` is pure and returns only `window_origin` and `window_epoch` when enabled. No caller-name inspection, global consumed bit, or literal dotted JSON key remains. `integrated_block` sorts numerical int64 `(cx, cy)` pairs deterministically and returns `{"window": {"integrated": ["cx:cy", ...]}}`.

Entity export explicitly captures the integrated-set snapshot beside its coordinate stamp. Map delta construction compares that snapshot with its last exported set; a set-only add/remove advances `state_version` without inventing entity or geometry changes. The versioned incremental delta carries nested `window.integrated` when the set changes. Unchanged current-version deltas omit it. Full/reconnect/stale-version snapshots always include the captured current set. Bootstrap includes it under `world.window.integrated`, matching exported stamp/rows. Frame/bootstrap reads never consume another consumer's update. The latest changed delta survives intervening unchanged builds, so TWO consumers with identical old versions receive the same update. Protocol/world initialization resets the new snapshot/cache state.

Origin or chunk-digest changes alone do not report an integrated-set change. Existing movement-contract revision/digest semantics stay unchanged. EDEN_WINDOW off creates no new wire fields, no new snapshot state, and no set-only version increment.

## Files

- `at_the_beginning/harness/window_wire.py`: pure stamp and explicit snapshot helpers, nested bootstrap representation.
- `at_the_beginning/harness/window_manager.py`: removed AGY global consumed/digest-change flag (final file matches its tracked baseline).
- `at_the_beginning/map_test.py`: small flag-gated protocol reset, export, delta/version and full-snapshot hooks only.
- `tests/test_window_r66.py`: genuine unittest classes with environment cleanup inherited from established isolated fixtures; removed missing pytest import and bare test functions.

## Actual checks

- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_window_r66.py` — **7 tests OK**, final source.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_harness_window_wire.py` — **7 tests OK**, including flag-off key sets, stamped epochs and real request 409 behavior; rerun after reset hook passed.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_map_wire.py` — **11 tests OK** with normal temporary-file access; rerun after reset hook passed. Sandbox-only first run had one existing Temp-directory PermissionError, rather than an assertion failure; escalated focused execution passed.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_harness_creature_store.py` — **14 tests OK** (spawn quota, real tensor population, stable-ID unload/reintegrate, catch-up, rebase and save repopulation).

The new R6.6 tests use real Engine `_export_map_entities`, `_build_map_delta_payload`, `get_map_delta_for`, frame and bootstrap paths. Set-only tests isolate manager chunk membership from entity diffs; a separate real generator integration/unload test checks actual resource upserts/removals. Coverage includes two consumers after empty ticks, reconnect/full/empty sets, numeric sort including negative and 2**40-scale coordinates, origin/digest churn, flag off and protocol reset. A creature lifecycle regression exercises actual frame animal rows before spawn-window unload and after re-integration; stable IDs return once. No hasattr-based lifecycle claim remains.

## Limits and coordination

No new creature behavior was implemented: R6.6 c2 is existing lifecycle behavior now validated by substantive store and real-export tests, not new ecology or production sprites. No defaults, goldens or external APIs changed. No roadmap/decision register edits, commits, pushes, installs or destructive operations. Heavy lock belongs to the economy worker; short focused tests ran under NORMAL as explicitly clarified by the coordinator. Full strict goldens/live tests remain owed, not claimed as passed.
