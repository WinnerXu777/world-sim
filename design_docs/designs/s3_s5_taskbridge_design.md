# S3, S5 and the Task bridge: designs (NO CODE; written while the clean suite runs, outside the watched directories)

Author: harness worker (837dca). Follows `./scheduler_design.md`. Everything here is proposal; sections 1, 2 and 3 each end with the decision or check I need.

## 1. S3: first migrated system, hunger and thirst

### What the legacy code does (read from the source)
`default_registry_entries` has `instinct_hunger` (priority 15) and `instinct_thirst` (16), adjacent with nothing between them.
* `instinct_hunger(ctx, h_tensor)`: on roster maps only, scales the change by `needs_scale_vector(engine, h_tensor)` (None on every legacy map); then `apply_hunger_tick(ctx["h_mask"], h)`:
  `hunger += 0.05` for the masked rows, clamped to at most 100 (no lower clamp); rows with `hunger >= 90` lose `2.0` hp (floored at 0); then `update_human_critical_state` (critical_health = 1 if hunger >= 90 or thirst >= 90, else 0).
* `instinct_thirst`: same shape with `thirst += 0.07`, clamp 100; rows with `thirst >= 90` lose `THIRST_DAMAGE_RATE` hp (floored at 0) and `0.4` mood (floored at 0); then the same critical-state refresh.
* The mask is `ctx["h_mask"]` as it stands in the registry loop (earlier entries may have changed it, e.g. the player-incarnation exemption), not "all live humans".

### Design: replace the two registry entries by one wrapper, no Engine.step edit
With the flag on, the genesis hook (`harness_world`) does `engine.unregister(instinct_hunger)`, `engine.unregister(instinct_thirst)` and `engine.register(harness_needs, priority=15)`. `harness_needs(ctx, h_tensor, **_)` is a legacy-shaped function that:
1. returns immediately (calls the two original functions) when `needs_scale_vector(...)` is not None, i.e. on roster maps: the migration covers legacy maps only until the scaling is expressed as data (declared limitation);
2. otherwise reads `ctx["h_mask"]`, maps slots to stable ids, builds the effects `Delta(humans, ids, hunger, +HUNGER_TICK_RATE)`, `Delta(thirst, +THIRST_TICK_RATE)`, `Delta(hp, -2.0)` for the rows that are at or above 90 AFTER the increment (computed from the post-increment values, as legacy does), the thirst equivalents including `Delta(mood, -0.4)`, and `Set(critical_health, 0|1)`, then applies them in one `EffectApplier` run (`cause="system:needs"`), returns None.
Because `register` sorts by priority and `S2` re-records the order, the registry loop itself is the scheduler: this stage needs no `Engine.step` edit (this is also why S5 is optional, section 2).

### Exactness conditions (each is a test)
* float32: legacy `tensor += 0.05` adds `float32(0.05)`; the applier builds float32 tensors, sums per slot with `index_add_` then adds to the column, so one Delta per tick per field is bit-identical; two Deltas to the same field in a tick are summed first (differs by float rounding), so the system emits exactly one Delta per field.
* bounds: needs `FieldSpec(hi=100.0)` on `hunger` and `thirst` (clamp max only; legacy has no lower clamp). The adapter currently declares no spec for them: added in the S3 commit, with a test that the legacy and harness paths agree for values above 100 and below 0.
* hp: the adapter's `hp` spec is `0..100`; legacy clamps only the lower side. They differ only for rows with hp > 100 (not reachable except through the old out-of-range bugs); the test covers hp 100 and below, and states the limitation.
* order: one combined system at priority 15, thirst at 16 (nothing sits between them), so the final tensors match; `critical_health` is computed once from the final hunger and thirst (the legacy value after the second refresh).
* equivalence test: 3600 ticks of the real engine twice from the same seed, flag on and off, `h_tensor` and `m_tensor` hashes equal at every checkpoint (this is exactly `tools/golden_trace.py --check --strict`, run with `EDEN_HARNESS_NEEDS=1`), plus a randomised unit test of the wrapper against the legacy functions on random `h_tensor` states, masks and rates.

### Cost and acceptance
The applier path costs more than three tensor statements. The acceptance you set (strict golden identical on and off, plus per-tick timing) stays; my prediction, to be measured in MEASURE mode: +0.3 to 1.0 ms mean per tick (id mapping, `torch.unique`, `index_add_`). If that exceeds 1 ms I will report it and propose a vectorised slot-keyed fast path inside the applier (not by-id), keeping the result identical, before enabling the stage.
Flag: a second switch `EDEN_HARNESS_NEEDS=1` (needs `EDEN_HARNESS=1`), default off, so S0-S2/S4 stay independent of S3.
Files: `harness/needs.py` (system + wrapper), `harness/engine_hooks.py` (swap in the genesis hook), `harness/adapter.py` (specs), tests `tests/test_harness_needs.py`. No legacy file edit.

Decision/check needed: none beyond your earlier OK; I need the clean suite to finish before I start.

## 2. S5: the Engine.step edit (exact diff, NOT applied) and why I recommend skipping it for now
`Engine.step` runs the registry with:
```
            for entry in self._registry:
                result = entry["fn"](ctx, **{**kwargs, **entry["kwargs"]})
```
Given S3's mechanism (the registry list is mutated at genesis and S2 keeps the record in step), the registry loop already is a scheduler whose order the harness controls. A real `Engine.step` edit only becomes necessary if the order must come from harness declarations (phases, reads/writes, `after`) instead of `priority`, or if systems must run in a batch with one `EffectApplier` run per tick instead of one per system. If you want that, the minimal diff is two hunks in `map_test.py`:
```
@@ class Engine
+    def _tick_registry(self):
+        """Entries run by step(), in order. The harness may substitute its schedule (EDEN_HARNESS)."""
+        return self._registry
@@ def step
-            for entry in self._registry:
+            for entry in self._tick_registry():
                 result = entry["fn"](ctx, **{**kwargs, **entry["kwargs"]})
```
`_tick_registry` returns `self._registry` unless the harness hook replaced the method on the instance (`engine._tick_registry = runtime.schedule`), so the flag-off path is the same list object and the golden cannot move. Risks: the method call per tick (about 0.1 microseconds), and anything that mutates `self._registry` during a tick (none today).
Recommendation: do not apply S5 until a system exists whose ordering cannot be expressed as a priority number. Decision needed: confirm S5 stays deferred (recommended), or approve this exact diff.

## 3. Bridging the harness Task store to the legacy `resident["tasks"]` queue (design [GAP])
### Legacy shape (systems/tasks/ops.py, schema.py)
A resident record holds `tasks` (list of task dicts: `id` like `task_000001` from a process-global counter, `task_kind`, `status` in queued/active/paused/completed..., `priority` 0..1, `source`, `summary`, target fields, `required_item`, `requested_quantity`, `created_tick`, `expires_tick`, `metadata`) and `task_state` (`current_task`, `current_task_id`, `paused_tasks`, `queue_revision`, `last_completed_task`, `blocked_reason`, ...). Operations: `queue_resident_task` (appends, bumps `queue_revision`, auto-starts if idle), `start_next_resident_task` (sorts by priority then created tick; marks the head `active`), `complete_current_task`, `interrupt_current_task`, `replace_resident_tasks`, `clear_resident_tasks`. Resident records are persisted by `resident_store` (dirty sets, background writes).

### Mapping
| harness (`Task` effect) | legacy |
|---|---|
| create (owner given) | `queue_resident_task(resident, task_kind=kind, priority, source="harness", metadata={"harness_args": args, "duration": d}, expires...)` |
| assign | move the record from the old owner's queue to the new owner's (remove + queue), keeping `id`; harness `owner` = resident id |
| cancel | remove from `tasks` and `paused_tasks`; if it was the current task: `complete_current_task(outcome="cancelled", reason=...)` so `start_next_resident_task` runs |
| complete | `complete_current_task(outcome="completed")` when it is the current task, otherwise remove with status completed |
| status pending (no owner) | not representable (legacy tasks always belong to a resident): kept in the harness store only |
| kind | harness `kind` must be a legacy `task_kind` in `TASK_KIND_DEFS` (catalog); unknown kinds are refused with `invalid_task` on a bridged world |

### Options
A. `LegacyTaskStore` (like `LegacyItemStore`): implements the store interface over `engine.resident_store` using the ops above; the `Task` effect needs no change. Cost: owner-less tasks need a side dict; ids come from the legacy counter (non-deterministic across processes), so the store maps harness ids to legacy ids in a side table that is saved with the resident (`metadata["harness_id"]`). Exactness: queue order and `queue_revision` come from the legacy ops, so the legacy runtime sees exactly what it sees today.
B. Effects carry a `RecordOp` that the actions runner already executes (the current Model-plane path). No store change, but the Task effect and the legacy queue can disagree and the harness store is no longer the source of truth.
C. Replace the legacy queue by the harness store: large, touches `systems/tasks`, the prompt views and persistence; not recommended before Gate D.
Recommendation: A, in two steps: (1) read-only mirror (harness store reflects legacy tasks, nothing writes through) with tests, then (2) write-through for create/cancel/complete behind a flag, with a regression test that every legacy op sequence yields the same `resident["tasks"]` and `task_state` as direct calls.

### Hazards
* `_TASK_COUNTER` is process-global, so legacy task ids are not reproducible between runs; goldens only hash tensors, but replay tests must not compare ids.
* `queue_revision` and resident dirty flags: every write-through must go through the ops functions (they bump the revision); the store must call `resident_store._mark_dirty` the same way the ops callers do (to be confirmed in the read-only step).
* `systems/tasks` and `systems/actions` are other workers' territory: the bridge lives in `harness/` and calls the ops functions; no edit there.
* Owner despawn: the harness cancels the owner's tasks (done); the legacy path clears a dead resident's record elsewhere; the bridge must not double-cancel.

Decision needed: A, two steps, as above?

## 4. Status after implementation (S3 pilot, bridge step 1)

### 2026-10-10 scaled S3 verification (supersedes the pilot limitation below)

The opt-in needs wrapper now expresses valid per-resident scaled deltas through the existing EffectApplier. Damage preserves legacy unscaled threshold timing and sequential float32 subtraction; the final critical flag preserves the legacy scaled-hunger/unscaled-thirst rule. Inactive rows remain unchanged. Invalid/non-finite/negative scales, absent stable ids, scaled values outside FieldSpec bounds, and damaged HP above the table bound retain the exact legacy fallback.

Root verified 14 focused tests, including actual authored scaled residents and applier effects. An immutable archive of `08338f3` plus only `harness/needs.py` and its tests passed all eight strict golden checks: default, resources, spaces and window-hook, each flags off and `EDEN_HARNESS=1 EDEN_HARNESS_NEEDS=1`. Source hashes were unchanged throughout. Evidence: `coordination_evidence/s3_scaled_gate_result.json`, `s3_scaled_gate.log`, and `agy_1010_s3_scaled_report.md`. This is a scoped correctness gate; performance under a MEASURE lock, task bridge step 2, and the combined current-HEAD full suite remain pending. Defaults and goldens were not changed.

### S3: implemented as a PILOT, not live in the shipped village
* Code: `harness/needs.py` (`instinct_needs`, `install`), swapped in by the genesis hook when `EDEN_HARNESS=1` and `EDEN_HARNESS_NEEDS=1`. Specs added to the humans table: `hunger` and `thirst` hi=100 (no lower bound), `mood` lo=0.
* It differs from section 1 in one point: the drain is applied in up to THREE applier runs per tick, not one, because float32 `(hp - 2) - d` is not always `hp - (2 + d)`: (1) hunger and thirst Deltas; (2) hp damage for rows with hunger >= 90; (3) hp, mood and the changed `critical_health` Sets. Runs 2 and 3 are skipped when empty.
* Equivalence (tests/test_harness_needs.py): 200 random states (edge values 89.9, 89.99, 90, 99.96, 100, 120, -3) and a 400-tick starving run are bit-for-bit equal to the two legacy entries; a mutation (hunger damage 2.001) fails the test.
* **The shipped starter_village does not take this path.** Its eight residents have `needs_scale` 0.015, so `needs_scale_vector` is non-None and `instinct_needs` calls the two legacy functions. S3 is therefore a pilot until the scaling is expressed as data.

* Evidence on an extract of 08087b0 (seed 1008, 3600 ticks, golden_trace; ignored dirs copied in):
  * `--unscaled` (needs scaling removed so the wrapper runs in full), flags off vs `EDEN_HARNESS=1 EDEN_HARNESS_NEEDS=1`: strict compare 0 differences at all 11 checkpoints (h_sha256 and m_sha256 equal). The wrapper is registered in the on run (`instinct_needs` present, `instinct_hunger` and `instinct_thirst` absent) and not in the off run.
  * Default (scaled) run with the flags on: `--check --strict` against the new golden, no drift.
  * Cost, three interleaved rounds of one process each, `step()` only, ticks 100 to 3600, MEASURE lock held (mean ms off / on): unscaled 11.40 / 12.14, 11.36 / 11.80, 11.56 / 11.74 (on minus off +0.74, +0.44, +0.17; medians +0.59, +0.39, +0.37); scaled (legacy fallback) 11.05 / 11.03, 10.95 / 11.01, 10.88 / 11.24 (-0.03, +0.06, +0.36). So about +0.4 ms mean per tick when the wrapper runs, and under 0.4 ms with the fallback; both below the 1 ms line.
### Follow-up: what it takes to cover `needs_scale_vector` maps
1. Legacy semantics: `after = tick(before)` (unscaled, clamped at 100); damage and the critical flag are computed from the UNSCALED intermediate; then `hunger = before + (after - before) * scale` for every row (scale 1.0 for rows without a roster).
2. Emit per-id Delta amounts `(after - before) * scale` computed in float32 (same operation order as legacy, so `before + amount` is bit-identical), and take the starving/dehydrated sets from the unscaled `after` (not from the table after the write).
3. Rows with scale > 1 could end above 100: the table's `hi=100` clamp would change the result. Either assert scale <= 1 in the system (fall back otherwise) or give Delta an optional per-effect bound override.
4. Cost: `needs_scale_vector` loops over every human slot and calls `roster_of` each tick (legacy calls it twice, the wrapper once); keep it, or cache per `roster` revision (separate measured item).
5. Tests: random scales (including 0.015 and 1.0 mixed), strict golden on the UNMODIFIED starter_village, on/off.

### Bridge step 1: implemented, read-only
`harness/legacy_tasks.py`, `EngineWorld.legacy_tasks`. The `Task` effect still writes to `world.tasks` (DictTaskStore); nothing is swapped yet. Limits found while reading `systems/tasks/ops.py`: legacy keeps only the LATEST closed task per resident (`task_state["last_completed_task"]`), so closed history is not available through the view; completed tasks are removed from `resident["tasks"]`. Step 2 (write-through) waits for review.

## 5. D-005 notes
* Caveat (no code change, training is out of scope): the dataset and prompt scripts under `models/` (`generate_dataset.py`, `generate_sft_ds.py`, `prompt_generator.py`, ...) import `TIER_A/TIER_B/TIER_C` from `models/tools_and_instincts_registry.py` directly. `tool_expand_world_edge` is flagged `legacy_frozen` there and `build_registry_string()` skips it, but a script that iterates `TIER_B` itself can still sample it as a training example. Add the same skip there if training data is regenerated.
* Runs from a `git archive` extract need the git-ignored directories copied in: `myassets/` and `tests/fixtures/maps/sprites/`.
