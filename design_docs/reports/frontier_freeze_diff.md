# D-005 golden re-record: what `instinct_frontier_expand` did in the 3600-tick run

Seed 1008, 3600 ticks, the authored starter village (8 residents), 11 checkpoints, measured on `git archive` extracts of HEAD 73487f9 (ignored dirs copied in), `tools/golden_trace.py`. Scripts: scratch only (`frontier_diff.py`, a wrapper that logs every call of the instinct).

## Result

- Before D-005 the golden file was recorded with the legacy frontier instinct registered. Running HEAD with `genesis_config.FREEZE_LEGACY_FRONTIER = False` reproduces the old golden file **exactly** (`golden_trace.compare(strict=True)`: 0 differences). So the whole drift of the strict check is the freeze, nothing else (7757b94 is the first red commit, as bisected by 2f0fd3).
- With the freeze on (the default) the strict check against the old file had **176 differences**. The new golden file was recorded from that tree and reproduces: a second run (`--check --strict`) gave no drift, and an independent third run compared strict against the new file gave 0 differences.

## What the instinct created (freeze off, 3600 calls, it changed state on 2 of them)

| tick (engine) | rows created | kinds | edge | where |
| --- | --- | --- | --- | --- |
| 0 (first step) | 7 (slots 27-33) | 5 x type 2 (forest), 2 x type 6 (grass) | north (first expansion) | x 146 to 1049, y 61 to 151 |
| 89 | 12 (slots 34-45) | 11 x type 2 (forest), 1 x type 6 (grass) | west (first expansion) | x 0 to 132, y 100 to 413 |

Total 19 new natural entities (27 -> 34 at tick 1, 34 -> 46 by tick 100; 46 for the rest of the run). The call result lists several expansions per call; my log truncates the result text to 200 characters, so the per-expansion edge list is incomplete, the row counts above are exact (diff of the type column around the call). No other tensor row was changed by the instinct (rows changed = rows created in both calls).

## The 176 differences, by cause

All 176 follow from those 19 rows (the same cause); nothing else differs:

| field | count | meaning |
| --- | --- | --- |
| `entities`, `entity_types.2`, `entity_types.6` | 10 each | the 19 extra rows (27 vs 46 entities from tick 100; from tick 1 the first 7) |
| `m_sums.cx`, `cy`, `hp`, `food` | 10 each | sums over the extra rows (food 480 at tick 1, 1525 at tick 300) |
| `m_sha256` | 10 | the extra rows |
| `h_sha256` | 6 | human tensor differs because of the resident positions below (ticks 600 and later; earlier checkpoints equal) |
| `residents.<name>.x` / `.y` | 45 + 45 | **position only**, all 8 residents, first at tick 600 (tick 300 and earlier identical); differences are small, e.g. Brann x 696.0167 vs 696.986, Elsa 152.07 vs 153.40 |

Identical in all 11 checkpoints for all 8 residents: `hp`, `hunger`, `thirst`, `stamina`, `mood`, `goal`, `at_anchor`, and the human count. There is no difference in needs, goals, commissions or the smith loop state in this run (the golden does not carry commissions or the smith loop; those are covered by their own suites, listed below).

Why the positions move by up to about 1.5 units from tick 600 is isolated in the probe section below (the food of the extra natural rows; the reading code was not located). It is a consequence of the world containing the extra rows, which the freeze removes on purpose.

## Decision recorded

Intended (D-005: the legacy frontier tools are not used). Golden re-recorded in its own commit; the old file is recoverable with `git show 73487f9:tests/golden/trace_seed1008.json`. `tests/test_harness_golden.py` compares against the new file. Anyone with local baselines recorded at or before 73487f9 (the agent-driver equivalence baselines of 2f0fd3) must re-baseline on this commit.

## Probe: why resident positions move from tick ~600 (added after the D-005 and resources goldens both showed it)
Method: record the rows the legacy frontier creates (freeze off: 7 rows at tick 0, 12 at tick 89, with their `MAP_GEO` circles), then run the default (frozen) world and re-insert them from a priority-84 registry entry at the same ticks (where the legacy instinct sits), changing one thing per run. Seed 1008, 600 ticks, `golden_trace.snapshot` at tick 600 compared with the legacy (unfrozen) run, extract of 662de1f. "Equal" means all resident x/y and both `h_sha256` and `m_sha256` identical.

| variant | equals the legacy unfrozen run? |
| --- | --- |
| frozen, nothing inserted | no (max 1.5 units) |
| rows inserted WITH their geo circles | yes, bit-for-bit |
| rows inserted WITHOUT geo circles | yes, bit-for-bit |
| rows inserted, `_entity_count_ref` NOT raised | yes |
| only the count raised, no rows | no |
| same rows with type 26 (inert) | no (equals frozen) |
| same rows, type/position/scale kept, every other column 0 | no (equals frozen) |
| zeroed rows with only column 3 (hp) restored | no |
| zeroed rows with only column 6 (fertility) restored | yes |
| zeroed rows with only column 10 (food) restored | yes |

So the cause is NOT the random stream (no draw of the legacy instinct is replayed), NOT the `MAP_GEO` circles and NOT the entity count. It needs the rows to be natural-type rows (the same columns under type 26 do not reproduce it) AND to hold food (zeroed rows do not; fertility alone is enough because the regrow entry turns fertility into food in the next ticks). The rows' positions were not varied. Where it first shows: a per-registry-entry hash of `h_tensor` is identical for 394 ticks and first differs at engine tick 395, in the first write of that tick (before or in the first registry entry, i.e. the roster step hook region); the one resident that differs is slot 6 (h_000007) by about 1 unit, in the same tick its `at_anchor` flag differs (goal 'work' in both). Everything after that is the trajectory of that resident and the ones it interacts with.
Not found: which code reads those food values with no geometry. Searches of `M_RESOURCE_FOOD` reads in survival, tasks, roster, movement and perception found only per-entity reads after a geo lookup, so the reader is either an aggregate over `m_tensor` I did not locate or code that reaches the rows by another path (`entity_radial_ids` scans all rows by position, for example). Consequence for planning: a world change far from every resident (food on a distant entity) can change when a resident arrives at its anchor, so goldens that include any new entity row will move residents even when no resident can see it. This is a sensitivity to be aware of for agent-driven residents; it is not shown to be a bug.

## Reader located (added 2026-10-08, measured on an extract of HEAD 6666075, seed 1008, 400 ticks, lock held 15:06 to 15:13)
Method: two runs, frozen (default) and "nogeo" (the 19 recorded frontier rows re-inserted into the tensor only, from a priority-84 entry at ticks 0 and 89), with `sys.setprofile` recording (a) a hash of the ordered Python call sequence per tick and (b) the RETURN VALUE of every call of the candidate readers (`nearest_entity`, `entity_radial_ids`, `agent_radial_mask`, `nearby_entity_ids`, `best_resource_entity`, `nearest_entity_from_ids`). Scripts: scratch only (`drift_probe6.py`, `drift_probe7.py`).

- **The reader is `runtime/common.py:nearest_entity`, called from `runtime/human_runtime.py:_build_case` (lines 506-533: food, water, shelter, hazard, predator queries).** It loops over every live row of `m_tensor` (`torch.where(M_TYPE > 0)`), filters by type set and `resource_col > min_resource`, and returns the globally nearest by Euclidean distance: no perception radius, no space, no reachability.
- In the 400-tick run `_build_case` is called once (tick 394, 5 `nearest_entity` calls, the first escalation of a resident at x 302.157, y 128.589). It is the **first and only differing return value of all 6405 recorded reader returns**: the food query returns `(-1, inf)` frozen and `(32, 116.1)` with the extra rows (slot 32 is one of the re-inserted forest rows, 116 units away). Everything earlier is identical.
- `_build_case` then calls `resident_store.remember_resource(..., "known_food_sources", food_eid, (x, y), tick)`, so the resident's memory (and the decision case it hands to Tier 1) differs; in the same tick the resident's position differs (302.157 vs 301.251 in the next `nearest_geo_entity` call), which is the drift the goldens show from tick 600.
- Call sequence evidence: first differing call is inside `ResidentAgentStore._prune_resident_memory` -> `_resource_policy` / `_apply_memory_policy` (an extra resource-memory entry exists in the run with the rows), call index 1943 of tick 395's list.
- **`entity_radial_ids`, `agent_radial_mask` and `best_resource_entity` are not involved**: they were called 0 times on this path in the 400 ticks (only `nearby_entity_ids` via `nearest_geo_entity`, 6400 calls, returns identical lists until the resident has moved). My earlier guess in the probe section above is withdrawn.
- Strict golden check on the same extract (includes 4843cfa, the item kinds): default `--check --strict` no drift (11 checkpoints, 41.2 s); `--resources --check --strict` no drift (44.3 s).

**Should it be perception-bounded? Yes.** Residents must not be moved, or have their memory written, by rows they cannot perceive. As written, a resident "knows" the nearest food row anywhere in the world; in the infinite window it would know rows 50 chunks away if they are loaded, and in an interior space (D1) it would see the overworld. Recommended change (not made, legacy file `runtime/common.py` and `runtime/human_runtime.py` belong to nobody in this round): give `nearest_entity` an optional `max_distance` and `space`, and have `_build_case` pass the resident's perception radius and its `H_SPACE`; default arguments reproduce today's behaviour, so goldens stay bit-identical with the arguments omitted. Correction after implementing it (c9d81e9, `EDEN_PERCEPTION_BOUNDED`): the food/water/shelter queries use `SURVIVAL_SCAN_RADIUS = 220`, hazard `HAZARD_AVOID_RADIUS = 120`, predator `PREDATOR_ALERT_RADIUS = 90`. The 116-unit row of this run is INSIDE 220, so bounding does not remove that particular drift (the resident legitimately perceives a forest 116 units away); it guarantees only that rows beyond the radius, and rows in another space, cannot change a resident's case, memory or decision (tested with a row 420 units away). The hazard and predator radii equal the thresholds `_decide` already reacts to, so bounding those two cannot change a decision, only what `remember_threat` records. A second consequence: `remember_resource` stores `entity_id` as a tensor slot (an int), which is the slot-as-identity hazard for chunk streaming (see the spaces/window design).
