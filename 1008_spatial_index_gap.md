# 1008 Spatial index at 100 residents ([GAP] with measurements, harness plane, 2026-10-09)

Author: 8d998a ("1008latenight"). Status: findings and a proposal, no code changed. Reviewer: c3. Question: what does the tick cost at 100 residents in the streaming window, and is a chunk-keyed spatial index (`1008implementation.md`, "Spatial index") what fixes it?

## 1. Method

`spatial_probe.py` (scratch, not in the tree yet; will go to `tools/` if you want it kept): the real engine on the starter village with the window flags (`EDEN_WINDOW`, `SPACES`, `PERCEPTION_BOUNDED`, `MAP_RESOURCES`, real `ChunkService` with `workers=0`, 30 to 54 chunks integrated, 128 to 245 entity rows), N humans (the 8 roster residents plus clones of a resident row scattered within 220 units of the village centre; no player, no models), 40 warm-up ticks, then 150 ticks timed with `tools/profile_tick.py`'s per-part timers (and cProfile for the call counts). The clones have no roster binding, so they run the legacy managed-task path: that is the worst case for the loops below, and the loops are the same ones real autonomous residents use. The machine was shared with another session's run (`NORMAL` lock held by latenight2), so read the absolute numbers as upper bounds and the ratios as solid.

## 2. Result: the tick is far over budget at 100, and the cost is quadratic in residents, not in map size

| residents | whole tick mean (ms) | `_sync_slot_ids_and_events` (ms) | `process_escalations` | `_current_masks` |
| --- | --- | --- | --- | --- |
| 8 | 19.4 | 5.6 | 2.8 | 0.4 |
| 50 | 200 | 154 | 19.6 | 12.9 |
| 100 | 515 | 435 | 39.9 | 26.3 |

(The budget is 50 ms.) Inside `_sync_slot_ids_and_events` it is `_sync_occupation_provisioning` -> `_sync_managed_resident_tasks`, once per resident per tick. cProfile at 100 residents, per tick:

| function (map_test.py) | calls/tick | cumulative ms/tick | what it does |
| --- | --- | --- | --- |
| `_resolve_mate_candidate` | 73 | 189 (cProfile) | for each ready resident, a Python loop over every human, each iteration reading 9 scalars from the tensor in `_slot_ready_for_mating` |
| `_slot_ready_for_mating` | 7 300 | 163 | the 9 scalar `float(tensor[slot, col])` reads; this is the O(N^2) core (219 000 calls in 30 ticks) |
| `_resolve_nearby_help_target` | 100 | 73 | the same shape: loop over all humans, scalar reads, a distance test |
| `_current_masks` | 62 | 25 | builds the animal mask with a Python loop over the 40 animal types, one tensor op each (0.4 ms per call), called by many helpers |
| `entities_in_radius` / `nearby_entity_ids` | 474 | 85 (cProfile; 0.076 ms/call measured without profiler) | one gather over `MAP_GEO` per call |
| `ensure_resident` | 300 | 92 | per-resident bookkeeping, three calls per resident per tick |

`_resolve_*` and `_current_masks` account for roughly 70 percent of the tick at 100 residents.

## 3. What the chunk-keyed spatial index would and would not fix

* **Entity queries** (`entities_in_radius`, `nearest_geo_entity`, wall probes): measured 0.076 ms per call at 148 geo entities with the existing vectorised pre-filter (`_radius_candidates`). With 474 calls per tick that is about 36 ms at the profiler's call rate; a per-chunk index would make each call cheaper, but the window holds at most about 400 rows, so the pre-filter is already within a small factor of what an index can do. **Not the bottleneck now**; keep the per-chunk index for when animals and structures raise the row count (P5 c2, the structure store), and decide with this probe at 400 rows.
* **Human to human queries** (mate, help, support, talk, guard, ...): a chunk index does nothing for them. They are plain O(N) loops with scalar tensor reads, repeated per resident per tick. **This is the cost**, and the fix is "read the tensor once per tick, answer from arrays".

## 4. Proposal (small, behaviour-preserving, in order of payoff)

1. **One per-tick human snapshot** (`HumanView`: numpy arrays of slot, x, y, hp, threat, sex, age, cooldown, hunger, thirst, stamina, uid presence, built lazily the first time a resolver asks in a tick, dropped at the next `step()`), and rewrite `_resolve_mate_candidate`, `_resolve_nearby_help_target`, `_resolve_support_target` and the `2522` loop as masked numpy over it, with the same tie-breaks. A prototype of the help-target query on the live engine at 100 residents: **50.2 ms -> 2.0 ms for all 100 calls (snapshot 0.23 ms), answers identical in 100 of 100**. Mating is the larger one (272 ms for 100 calls today). Expected result at 100 residents: `_sync_managed_resident_tasks` from about 280 ms to a few ms.
2. **`_current_masks`**: build the animal mask once (`torch.isin` or a precomputed range test), 0.4 ms -> about 0.02 ms per call; no behaviour change.
3. **`ensure_resident` in the sync loop**: skip the call when the resident record already exists and nothing changed (needs a look at `_ensure_behavior_state` at 1.6 s per 6 000 calls; not yet analysed).
4. Then re-measure; only if entity queries remain above 5 ms per tick at 400 rows, add the per-chunk tile map.

All of 1 to 3 are edits in `map_test.py` (legacy file, not mine). **I need your decision to touch them**: either I do 1 and 2 under the usual strict-golden gate (default, `--resources`, `--spaces`, window-hook must stay bit-identical: the rewrite must return the same candidate, same tie-breaks), or latenight2 does them as part of the model plane. I recommend me, because the goldens are mine and the change is pure equivalence.

## 5. Not measured

Residents running the agent driver and the tier-3 model plane (no models in the probe); a player connection (frame payload at 100 residents is 2.4 ms of the 515); dormancy at 100 (dormant residents leave `h_mask` and would shrink these loops, see `1008_dormancy_gap.md`); the same run without the window (the loops are not window-specific, so expect the same quadratic cost on the legacy world: this is a general scaling debt).

## 6. Result of the resolver rewrite (c4e5d36..4db4965 plus 6dded33, c3-approved)

`harness/human_query.py`: `humans_within` (vector pre-filter returning a superset of the humans within the radius, ascending slot order; each resolver then runs its ORIGINAL body on those rows only, so candidates, tie-breaks and floats cannot differ) and `animal_mask` (one `isin`). Applied to `_resolve_mate_candidate`, `_resolve_nearby_help_target`, `_resolve_support_target`, `_resolve_autonomous_human_attack_target` and `_current_masks`, one commit each. `tests/test_harness_human_query.py` keeps the old implementations verbatim and compares them with the new ones over randomized worlds (equal distances, ties, dead rows, missing/duplicate ids, other spaces, NaN and inf positions, empty world, masks): 9 tests. Strict goldens default / `--resources` / `--spaces` / window-hook and window-walk are bit-identical on c0b35d9 (which includes all of it); s1 digests steal+reputation a2fcc8cbdd7143c8 and trade f83fed5436dd08fe unchanged.

Paired probe (`tools/spatial_probe.py N 150 window`, old = 5d045af, new = c0b35d9, same machine within minutes, another session's run in the background so absolutes are upper bounds), whole tick mean in ms:

| residents | before | after |
| --- | --- | --- |
| 8 | 17.5 | 19.7 (17.9 on an idler machine; no change expected) |
| 50 | 190 | 132 |
| 100 | 471 | 277 (264 idler) |

Not under the 50 ms budget at 100. Remaining top three (100 residents, after): `_sync_slot_ids_and_events` 195 ms, of which `_sync_managed_resident_tasks` -> `_execute_resident_task_step` (task step execution per resident, includes about 60 `designate_construction_project` calls per tick from the clones, which have no roster) about 40 percent, `ensure_resident` (three calls per resident per tick, each re-running `_ensure_behavior_state`: personality, occupation, schedule, crafting, construction, tasks, pressures, goals, plans, with dict copies and comparisons) about 30 percent, and `entities_in_radius` / `nearby_entity_ids` (about 470 calls per tick, 0.08 ms each) about 15 percent; then `human_agent.process_escalations` 40 ms; then `world_agent.process_queues` 9 ms. None of them is a human-to-human scan any more.
