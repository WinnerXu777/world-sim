# R6.8 first mind/body power ports

Status: COMPLETE for these three ports; focused tests and strict flag-off goldens verified. Only `at_the_beginning/harness/powers.py`, `tests/test_power_ports_1010.py` and this report are changed for this slice. This ports three tools, not all R6.8.

## Behavior and integration

At registry construction, explicit `EDEN_GOD_POWER_PORTS=1` adds `set_threat`, `set_aggression`, and `reset_cooldown` to the real harness power registry. Default-off registry names/schema remain the original ten powers. Flags are configuration at registry construction/import; changing environment later requires constructing a new registry, as tested. No god endpoint or engine-hook wiring is added; a caller uses the existing `powers.call`/`plan`/`apply` API and an enabled registry.

Threat supports required value and set/add/multiply, bounded to 0..100. Aggression supports those modes, defaults value to 1, and bounds to 0..1. Reset clears only the reproduction cooldown column, defaults to all selected live rows, and leaves stamina, masks and every other column alone. Both adjustments require explicit human typed selectors; reset's selector is optional, matching legacy defaults.

Each power resolves stable IDs, plans `Set` and witnessed private `Emit` effects without mutation, and reports before/after values plus affected IDs. Existing atomic apply, FieldSpec policies, world revision replan and receipts remain authoritative. A stale explicit victim ID cannot affect a replacement occupying its slot. Unknown/all-empty selectors refuse through existing selector semantics; mixed ID selectors follow existing resolution behavior.

## Legacy characterization

Actual current legacy functions are `instincts_and_tools.py:tool_set_threat`, `tool_set_aggression`, `tool_reset_cooldown`. Threat and aggression currently call `harness.clamp.clamp_rows_`; the brief's historical fancy-index clamp bug is already repaired in these functions. Valid-input equivalence tests compare entire real-layout tensors across all adjustment modes and masked/default cooldown reset. No legacy tool is edited.

New wrappers refuse schema-invalid or non-finite input, invalid target types/fields, missing required columns, non-finite current adjustment state and arithmetic overflow. They intentionally provide structured refusals where legacy code has no such contract. World FieldSpec rejection remains atomic and produces no event. Standard bounds match the current legacy code.

## Validation

Clean archive base `b555adc33776696f529ae9e4047c88acdb42f408` plus only the two owned power source/test files passed 46 tests: 11 dedicated, 12 existing harness powers, 23 batch-two powers. Commands were `.venv/Scripts/python.exe -m unittest discover -s tests -p <module.py>` for `test_power_ports_1010.py`, `test_harness_powers.py`, `test_harness_powers_batch2.py`.

All four strict flag-off goldens passed with no drift at 11 checkpoints each: `.venv/Scripts/python.exe tools/golden_trace.py --check --strict`, additionally `--resources`, `--spaces`, `--window-hook` (69.6 / 81.1 / 72.9 / 85.6 seconds). The runner exited 0 and released only its token-owned lock. Commands, completed exits and source hashes are in `power_ports_1010_manifest.json`; output is in `power_ports_1010_checks.log`.

While that immutable archive ran, review added a structured refusal for oversized integers that cannot convert to finite floats. This changes only the flagged adjustment branch. After the goldens finished, the same base archive received the final two files and all 11 dedicated tests passed again, including the new oversized-integer case. Exact final hashes/command/exit are in `power_ports_1010_final_tests_manifest.json` and output in `power_ports_1010_final_tests.log`. Root explicitly allowed this short test under its NORMAL S3 gate; its lock was untouched. The original golden snapshot predates only this opt-in conversion guard and its test; no flag-off path changed. No repeat of unchanged flag-off goldens was needed. Final owned source hashes match live files, and owned `git diff --check` passes. Root's combined current-HEAD integration gate remains separate.

Root moved HEAD to `08338f3` for the frozen economy topic while the archive ran. That commit is deliberately absent from this earlier power snapshot; provenance is preserved rather than claiming a combined gate. The first dedicated test attempt atomically probed `.runtime/fullsuite.lock` and found `NORMAL root-r06-market`; it aborted without deleting or modifying root's lock. That initial abort was followed by the successful validation above.

Dedicated coverage: flag-off registry and existing output, flag-on default dispatch, selected rows and exact cooldown field, dry-run preview/purity, modes/bounds/defaults, invalid/non-finite targets and values, missing columns, non-finite state/overflow, stale replan and recycled IDs, atomic FieldSpec refusal, valid legacy tensor equivalence. Environment/global registry changes are isolated and restored.

## Limits

No defaults, calendar, acquired masks, API/client/backend adapters, counters, balance, files owned by AGY or other workers, commits, pushes, dependencies or golden fixtures changed. AGY's `harness/needs.py`, `tests/test_harness_needs.py`, and map_test movement block remain read-only. Human-killer identity follows this handoff and requires coordination around map_test. Remaining R6.8 tools, endpoint integration, new powers and roads remain outside this slice.
