# R6.9 human-killer identity

Status: kernel helper and eight dedicated tests written; engine hook integration and validation pending. Root requires all `map_test.py` to remain read-only while AGY's native whole-file writer is live. No map_test edit has been made for this slice.

## Implementation so far

`kernel.record_killer` records a lethal, known creature victim only when `EDEN_CREATURES=1`, binding the slot record to the current victim UID and killer UID. The first attacker for a victim UID wins; reuse of that slot replaces stale attribution for a new victim. Already emitted victim IDs refuse new recording.

The existing creature `_attack` path uses this same binding while preserving its damage/feed behavior. `_scan_kills` consumes the slot record but emits a killer only when its bound victim UID matches the current row. Its once-only stable victim ID set and existing event remain authoritative. No new loot/feed/event/counter/save field is introduced.

Planned engine integration is restricted to the existing `_record_combat_outcomes` entity branch: after the real resolver reports a successful lethal hit and a valid stable attacker/victim ID, call this helper under the creature flag. The actual resolver order is retained, matching its first-attacker convention. Rejected/nonlethal and environmental deaths retain no attribution. The damage resolver itself remains unchanged.

## Tests prepared, not run

`test_creature_human_killer_1010.py` uses the real window-engine fixture, creature install/uninstall, real `resolve_human_attack_intents`, actual engine outcome hook and actual kill scan. Eight cases cover manual/rules lethal kills once, nonlethal then environmental death, wall-rejected hit, two attackers in non-slot order, recycled slot with environmental death, recycled slot with a new lethal human, existing creature killer/feed path, and flag-off hook identity. Fixture caches, environment and unrelated orchestration are isolated/restored; no model API is used.

Full integration tests are intentionally pending the engine hook; no pass is claimed. Root's S3 heavy gate currently owns the shared lock. No new heavy lock or suite was started.

## Ownership and limits

Only `at_the_beginning/systems/creatures/kernel.py`, the dedicated new test and this report have been edited. Once root confirms AGY terminal handoff, the only engine edit will be `_record_combat_outcomes`; all movement, void telemetry, R6.6 window hooks, resolver, table/balance/reproduction/inventory/save schema remain untouched. This is one R6.9 component, not all creature extensions. Root owns commits and coordination ledger/roadmap updates.
