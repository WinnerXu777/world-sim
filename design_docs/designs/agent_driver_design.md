# 1008 - Agent driver design (R3-INT, D-008): every resident on the Tier 0 -> 1 -> 2 -> 3 path

Status (updated 2026-10-08): **BUILT behind flags, all default off.** Sections 0 to 5 are the original design (kept as written, "nothing is built" in section 5 is historical). What exists: `AgentDriver` with `EDEN_ROSTER_DRIVER=anchor|agent`, rules and matrix Tier 1, cadence and interrupts (including the threat-rise interrupt), site trips (see "Implemented" and "Tier 1 acceptance" below); `EDEN_AGENT_ACTIONS` routing through the runner (built in 96ccc7a; the "NOT implemented" heading of that design section is historical, results in `./actions.md` 10.13); `EDEN_AGENT_LADDER` and `EDEN_REPUTATION` (`./market_justice_design.md`). Original header: design written by the Model plane worker from reading the code at `77b6bdc` (`systems/roster/{driver,needs,motion,install}.py`, `Engine.step` and `_move_human_toward_point`/task-family selection in `map_test.py`, `simulation/dispatch.py`, `systems/actions/*`, `systems/affordance/driver.py`). Statements marked *measured* come from a test or probe; everything else is read from code and not yet run.

D-008 (decided): all residents are intelligent. Tier 0 instincts -> Tier 1 matrix by default (no LLM) -> Tier 2 Clef -> Tier 3 LLM on escalation. The roster driver is the **rules baseline** Tier 1 starts from and the fallback when models are off or failing. A per-resident `driver` stays only for rollout/rollback.

## 0. What a "roster resident" means in the engine today

The record key `roster` is read in exactly **four** places, and each one is a separate behaviour:

| # | where | what the key switches |
|---|---|---|
| 1 | `roster/driver.py` `anchor_driven_slots` / `drive_roster_residents` (step hook `roster_driver`) | the schedule picks an anchor key, `AnchorMover` walks there; the food/water trip loop (`roster/needs.py`) pre-empts it; an open commission overrides the goal (`commission_goal_override`) |
| 2 | `roster/motion.py` `move_task_actor`, called from `Engine._move_human_toward_point` | a task's movement step is ignored for a roster resident (non-roster residents walk to the task target with the same `AnchorMover`) |
| 3 | `map_test.py` ~l.1429 (`elif resident.get("roster")`) | no construction/trade/occupation task families are generated for the resident (`reason = "roster_anchor_driven"`) |
| 4 | `affordance/driver.py` (mine) | verdicts of 7 verbs (+ `eat` at a site) become `roster_driven` |

A non-roster resident already moves by tasks + `AnchorMover` through `move_task_actor` (measured earlier: it works, this is the existing legacy path). So "agent path" = switch off 1-3 for the resident, and give it something that does what 1 did (schedule + needs + commission goal) as a *decision input* instead of a hard mover.

## 1. How a Tier 1 decision becomes a running action for every resident each cycle

**Component: `AgentDriver`** (new, `systems/actions/agent_driver.py`, my path; one object per engine, non-saved runtime state like `RosterRuntime`). One builtin **step hook** `agent_driver`, registered after `roster_driver` (hook order is registration order; it is not important that it precedes `motion_checkpoint`, because `apply_motion_limits` reads `final_positions` from the previous tick and only falls back to the checkpoint on a resident's first tick).

Per tick, for each agent-driven resident (record `driver == "agent"`, alive, not player-controlled):

1. **Cadence.** Tier 1 decides when the resident is *due*, not every tick: due = no current action, or current action ended (task left the queue / routine arrived / hold elapsed), or an interrupt (need crossed its threshold, `threat` rose, hp fell, a commission order opened/closed for it, a model result arrived), or `decide_period` ticks elapsed (default 10, staggered by `slot % period` so a population of N costs N/period decisions per tick). The decision is one batched call: `build_features` -> `AffordanceEngine.mask` -> `MatrixPolicy.decide` for the due rows only (measured earlier: warm mask about 10 ms for the 8 residents; cold mask is the cost to watch at 100 residents, about 0.17 s, so the due set must be capped per tick - `max_due_per_tick`, placeholder 16).
2. **Execution** always through `ActionRunner.run(actor, verb, args, proposer="tier1"|"rules")` - the same schema/grounding/legality/rate/risk/audit path as Tier 3. The macro -> verb/args step is a table (`MACRO_TO_VERB`, data) using the mask's `options` to pick args (nearest water, the work anchor, ...). A refusal is a result, not an exception: the resident keeps its previous action and the refusal is counted (`run:failed:<code>`), as the PlanCursor already does.
3. **Ownership.**
   * *Which action runs*: `AgentDriver.current[human_id] = {verb, args, source, started, task_id|None, routine|None}`. One entry per resident, replaced only by a new decision (hysteresis in the matrix keeps it from flapping) or by an interrupt. A Tier 3 `PlanCursor` for the resident is an *override layer*: while a cursor is active the driver does not start a Tier 1 action for that resident (the cursor owns the resident, as in `./actions.md` 10.9); when it ends, Tier 1 resumes.
   * *Movement*: the existing `AnchorMover` stays the single mover. Three action kinds produce a goal point for it: a **routine goal** (an anchor key, same table as `ROUTINE_ANCHOR`), a **site goal** (water/food anchor, with the stand-and-reset of `roster/needs.after_step`), and a **task** (the legacy task system keeps owning movement through `move_task_actor`, now in its non-roster branch). Only one of the three is active per resident, so there is still exactly one mover per resident.
   * *Task state*: unchanged - `record["tasks"]`, `task_state.last_completed_task`; the driver only watches them (same as `PlanCursors.task_status`).
4. **The roster routine becomes the rules scorer's schedule input.** `current_routine()` (schedule/ops, already used by the roster driver) is exposed as features `routine_sleep`, `routine_work`, `routine_talk`, `routine_home` (new columns; **this changes `FEATURE_SCHEMA_VERSION`**, so the weights file version bumps and the golden feature tests are regenerated - flagged, not done). **Caveat: `RulesDecisionProvider` (`decision/providers.py`) scores only the six commission outcomes today, and the matrix's 24 macro weights are placeholders (`matrix.py` docstring). A rules scorer over the macros that reproduces the roster priority order does not exist; it is new work and part of this item.** Its weights give the macro that realises the routine (`sleep`, `work_at_station`, `socialise`, `go_home`) a base score above everything except an unmet need, an open commission and a threat. Then, with Tier 1 = rules:
   * need over threshold -> `eat`/`drink` macro wins (same threshold the needs loop uses: `needs.threshold`), the action is a **site goal**: reproduces the trip, including the `trip_timeout_ticks` ration fallback (which moves into the driver unchanged);
   * open commission for this resident -> the `work_at_station` macro with the commission goal (`commission_goal_override`) -> routine goal "work";
   * else the routine's macro -> routine goal.
   This is the exact priority order of `drive_roster_residents` (need > commission > schedule), written as scores instead of `if`s. Equivalence is a *test* (section 3), not a claim.
5. **Rollback.** Per resident `driver: "anchor" | "agent"` in the roster binding (default `anchor` until the proof passes, then `agent`). `anchor` leaves behaviour byte-identical to today. A model-plane failure never matters here: Tier 1 = rules needs no model; Tier 2/3 off = Tier 1 only; `MatrixPolicy` failure -> the driver falls back to the rules provider for that cycle (`decision/service.py` degrades any provider failure to the fallback provider, which today only covers commission options, so the macro rules scorer above must exist first).

## 2. Verbs that need driver or task fixes on an agent resident

Facts: with `driver == "agent"` the `affordance/driver.py` demotion table is off for that resident (a per-resident `driver_mode`, a 3-line change in my code: `restrict` currently reads engine-wide `config.DRIVER_MODE`). The task system then runs the legacy tasks for it. What each verb needs beyond that:

| verb | today on a roster resident | on an agent resident | fix needed |
|---|---|---|---|
| `eat` at a site/resource | `roster_driven`; the needs loop eats at the site | legacy task `eat_food` finds *entities* (resources), but the roster's food site is a map **anchor**, not necessarily an entity | **driver fix**: `eat` with `source == "site"` returns a *site goal* op (new record op `set_goal`), consumed by `AgentDriver`; pack food is unchanged |
| `drink` | `roster_driven` | same as `eat`: `fetch_water` looks for water entities/tiles; the roster water site is an anchor | **driver fix**: site goal op as above |
| `work_shift` | task stays active and does nothing | the occupation work task runs by itself (smith: `forge_work`?) *unverified for the smith* | **verify** with a probe on a smith agent resident; if the legacy family has no smith task the smith's work stays the commission loop (work anchor + commission tick), i.e. `work_shift` for the smith = the routine goal "work" |
| `gather_resource` | task stays active | `gather_material` walks to the node through `move_task_actor` | none expected; **verify** one gather end to end (an agent resident gathers `wood_bundle`) |
| `follow` | task stays active | `follow_target` walks after the target (`hold_ticks` 20) | none expected; **verify** |
| `attack`, `avoid`, `explore_toward` (batch 1, same table) | `roster_driven` | walking tasks via `move_task_actor` | **verify** `retreat_from_target` really retreats (measured on a roster resident: it completed in about 20 ticks on the driver's own path, so that run proves nothing) |
| routine verbs `sleep`, `flee_to`, `go_to_work`, `seek_shelter` (4 now; c3 counted 3) | `set_routine(...)` consumed by `roster_driver` | nothing reads `set_routine` for movement except the soft navigation bias | **driver fix**: `AgentDriver` consumes the same routine record (`op_set_routine`) as a **routine goal**; `ROUTINE_ANCHOR` is reused as is. For non-roster residents without anchors (`has_work_anchor` false) the existing task branch applies |

So two real fixes (site goal for `eat`/`drink`, routine goal for the routine verbs), both inside the new driver plus one new record op; the rest are verifications. `roster_driven()` refusals in the verb bodies stay as defence for `driver == "anchor"`.

Other roster-only behaviour that must be reproduced for an agent resident (found while reading, all in the roster driver today): portal crossings (`portal_toward`/`use_portal`), `needs_scale`/`age_scale` vectors (read through `roster_of`, independent of the driver, so they keep working if the `roster` binding stays on the record), `motion_limits` (applies to every non-controlled human already).

## 3. Proof plan for Stage 1 on the agent path (Tier 1 = rules)

Switch: env/config `EDEN_ROSTER_DRIVER=anchor|agent` sets the default `driver` for all roster residents at genesis (per-resident value stays overridable). Nothing below edits `tests/test_smith_loop.py`; the existing files run unchanged with the switch set, which is the point.

1. **Trajectory equivalence (new test, mine).** Same seed, 600 ticks, all 8 residents: positions and `at_anchor` per tick, `anchor` vs `agent` with the rules provider. Pass = identical per tick, or an explicit, listed tolerance if the decision cadence delays a goal change by up to `decide_period` ticks (then the test asserts the delay bound, not equality). This is the hard question; it may force `decide_period = 1` for goal changes (interrupts) and 10 only for re-scoring.
2. **Needs loop.** `test_roster_needs.py`, `test_roster_apply.py`, `test_roster.py` with the switch on; plus: hunger and thirst of every resident stay bounded for 3 game days (soak, MEASURE lock), `trips_done > 0`, `rations` count compared with the anchor run.
3. **Smith loop and commission.** `test_smith_loop.py`, `test_smith_ready_hold.py`, `test_commission_*` with the switch on; the golden/acceptance traces under `tests/golden/` (`test_harness_golden.py`) compared byte-for-byte or with the listed tolerance from 1.
4. **Tier 1 = matrix.** Acceptance, not equality: over one game day the smith completes a commission, all residents' needs stay bounded, no resident idles more than N ticks without a reason code, no `run:failed` storm in the audit log.
5. **Failure modes.** model plane off, MatrixPolicy raising, mask raising: the world keeps running on the rules provider; each is one test.
6. **Cost.** `EDEN_GC_FREEZE` cells (Gate A) with all residents on the agent path: the on-minus-off p99 of the tick, and `last_decision_ms` per cycle.

Order: 1 and 2 first (they decide whether the design holds), 3 next, 4-6 last.

## 4. Hook seams and engine edits

* **No `Engine.step` edit is needed.** The driver is a builtin step hook (`DISPATCH.register_step_hook("agent_driver", fn, builtin=True)`, exception-isolated, no-op while no resident has `driver == "agent"`). Install point: `install_smith_loop` (`systems/roster/install.py`, not my path) is where `roster_driver` is registered; the `agent_driver` registration should sit next to it. I can instead register it from `api/model_routes.py` next to the escalation hook (my path, no coordination), but then it is only installed when the model API is mounted, which is wrong for a world that runs without the model plane. **Recommendation: a 2-line addition in `install.py` (837dca) that calls `systems.actions.agent_driver.install(dispatch)`**; to be agreed with 837dca before I write it.
* **Unavoidable edits outside my paths (switching the roster behaviours off per resident):**
  1. `systems/roster/driver.py` `anchor_driven_slots`: skip a resident whose binding has `driver == "agent"` (about 2 lines).
  2. `systems/roster/motion.py` `move_task_actor`: treat the same residents as non-roster (about 2 lines).
  3. `map_test.py` ~l.1429: `elif resident.get("roster")` -> `elif anchor_driven(resident)` so an agent resident gets the normal task families (1 line + an import). This is the only `map_test.py` edit.
  A **zero-edit alternative exists but is not recommended**: let the roster driver run and have `agent_driver` undo its movement afterwards and bypass the `move_task_actor` ignore; it needs a per-tick position snapshot, double-moves the resident and breaks the "one mover" rule.
* My own paths: `affordance/driver.py` (per-resident mode), `actions/agent_driver.py` (new), `actions/recordops.py` (`set_goal` op, `set_routine` consumed), `decision/features.py` (routine features; schema version bump), `actions/catalog`/verbs (site goal for `eat`/`drink`).

## 5. Not done / open questions

* Nothing is built. No probe of `work_shift` for the smith, `gather`, `follow`, `avoid` on a non-roster resident has been run; the table in section 2 marks which rows are unverified.
* Changing feature columns bumps `FEATURE_SCHEMA_VERSION`; the Tier 1 shadow logs and the `tools/` benches that pin v1 need regenerating (list not compiled).
* Whether `decide_period` 10 reproduces the anchor trajectories exactly is unknown (proof step 1 answers it).
* `commission_goal_override` is read from the roster driver's module; the agent driver would call it as a feature source (read-only, no edit) - to confirm it has no side effects.
* Population growth/spawn: `population_fixed` on roster maps means no new residents appear; agent-driven residents spawned by other means (non-roster) are unaffected.
* D-005: the frozen frontier tools are not part of any menu above; the agent driver never emits `explore` beyond `explore_toward` (heading step).

## Implemented: Tier 1 macro scorer, cadence, site trips (commit 4bb11a7)

* `systems/actions/agent_driver.py`: `RulesTier1` (macro = `ROUTINE_MACRO[routine]`, `work_at_station` while a commission is open) and `MatrixTier1` (placeholder matrix scores + `prior_strength` x `rules_prior` (+100 on the rules macro), argmax over the world-judged legality mask restricted to the 24 macros; the rules macro is always permitted as a walk, because "walk to the talk anchor" does not need `socialise` to be a legal action). Select with `EDEN_AGENT_TIER1=rules|matrix` (default rules). `FEATURE_SCHEMA_VERSION` is unchanged (the prior is additive, not a feature column).
* Cadence: re-score at once when the signature `(routine, commission override)` changes or a trip ends; otherwise every `EDEN_AGENT_DECIDE_PERIOD` (10) ticks, staggered by slot. Need trips stay Tier 0 (`needs.plan`) and pre-empt. Goal changes take effect on the same tick.
* A macro with no anchor of its own (eat, drink, avoid, ...) keeps the routine anchor. The rules macro and an open commission always use the routine's own anchor, so Tier 1 = rules is the roster walk exactly.
* `site_trip` RecordOp: starts the needs loop's food/water trip now (refused: `no_roster`, `bad_kind`, `no_site`, `trip_active`); `eat`/`drink` use it for an agent resident at a site; `sleep`/`flee_to`/`seek_shelter`/`go_to_work` use `set_routine` for any resident with a roster binding (`ctx.has_anchors`).
* Proof: `tests/test_agent_driver.py` (tick-by-tick equal to the anchor driver for 2000 ticks with both Tier 1 providers, cadence bound, site_trip op), golden `--check --strict` clean.
* Not done at 4bb11a7: threat-rise interrupt (added later in 9daf163: signature includes THREAT >= 30 and HP drop >= 10), matrix weights are still placeholders, Tier 2 request builder for the macro menu.

## Design: routing Tier 1 macros through ActionRunner (`EDEN_AGENT_ACTIONS`, default off) - implemented later in 96ccc7a (text below is the original design)

Authorised by c3 as a separate item. With the flag off nothing below runs (strict golden identical, as for the rest of the driver).

* **Where.** In `AgentDriver.step`, pass 2, right after `Tier1.decide` returned a macro for a due resident. A lazy per-engine `ActionRunner(world, services, aff=AffordanceEngine(world, services, driver_mode="agent"), record_ops=EngineRecordOps(engine))` (rebuilt when the world epoch changes, like `MatrixTier1._context`; the default registry therefore includes the node verbs while `EDEN_MAP_RESOURCES` is on).
* **Which macros.** `ACTION_MACROS = {eat, rest, gather, socialise, trade, help, work_at_station (only when `resolve` picks craft / store_item / fetch_item), ask_for_help, hide}`; `sleep`, `go_home`, `work_at_station` as a walk, and every site trip remain `AnchorMover` goals (routine / site goals), `flee`/`avoid`/`attack`/`explore` stay out until their executors exist for agent residents. A macro is routed only when it is not the rules macro of the routine (the routine macro is a walk), so Tier 1 = rules with an unchanged scorer routes nothing.
* **How.** `call = aff.resolve(macro, human_id)` (first legal option, nearest first); `None` -> the macro stays a movement goal and `routed_none` is counted; else `runner.run(human_id, call.verb, call.params, proposer="tier1", confidence=...)`. An accepted run is an audit entry with `proposer == "tier1"`; a refusal keeps the previous macro, is counted `run:failed:<code>` (`AgentDriver.routed`), and arms a per-(resident, macro) cooldown of one period so a refused macro is not re-asked every re-score.
* **Rules triggers.** Today the rules scorer only ever emits the routine macro, so there would be no Tier-1 audit entries. The rules need a small action layer: `rest` when stamina is low and nobody is a threat, `eat` from the pack when hunger passes a pack threshold above the trip threshold, `socialise` (greet/chat) at the talk anchor when a neighbour is in range. These are the only places the rules trajectory departs from the anchor driver with the flag on.
* **Yielding.** An accepted task-queuing verb (`rest` -> `sleep` task, `greet` -> `talk_to_target`) makes the driver yield (existing rule); instant verbs (`eat` from the pack, `craft`, `store_item`, node verbs) apply in the runner's atomic apply and the walk continues.
* **Acceptance.** Flag on: rerun `model_server.tier1_acceptance` (rules and matrix): the runner audit shows Tier-1 entries, zero unexplained rejections (every `run:failed` code accounted for in the report), commission / needs / idle / budget checks as before; flag off: strict golden identical.
* **Open questions for c3.** (1) Whether the pack-eat threshold belongs to the rules scorer or stays with the Tier 0 needs loop (`needs.plan` already issues a ration when a site is missing). (2) `rest`: use the `sleep` task (inert-when-safe-entity-in-range finding in 10.5, only for anchor residents) or the `rest` verb's stamina effect.

## Tier 1 acceptance over one game day (`model_server/tier1_acceptance.py`, measured 2026-10-08)

Seed 1008, 2400 ticks (= `DEFAULT_DAY_LENGTH_TICKS`), seven agent-driven residents + the player-claimed customer (iven), roster `needs_scale` 1.0 (the shipped 0.015 gives hunger 1.8 / thirst 2.5 in a day and no trip, which proves nothing), real commission work time, period 10, prior 100. Command: `python -m model_server.tier1_acceptance --compare --ticks 2400`.

| | rules | matrix (+prior) |
|---|---|---|
| commission | accepted t=1, working t=23, ready t=2063, delivered t=2064, 1 sword | identical timeline |
| needs | max hunger 44.45, max thirst 55.58 (bound 60), min HP 100, 46 food/water trips, 0 timeouts, 0 blocked | identical |
| idle (not moved, no anchor, no trip, no task) | longest run 0 (7810 anchor ticks, 8983 moved) | identical |
| failures | Tier 1 errors 0, `run:failed` 0 | identical |
| decisions | 993 = 0.41 / tick, 23 interrupts | 993, same |
| decide call | mean 0.001 ms, max 0.01 | mean 2.58, p99 5.63, **max 18.81 ms** (bound 25), warm-up 33.5 ms paid once |
| driver step | mean 0.86 ms, max 16.4 | mean 1.91, p99 6.7, max 27.7 |
| tick | mean 12.3 ms, p99 28.0 | mean 13.5, p99 34.0 |

The matrix run reproduces the rules run: final positions of all eight residents are equal. The ready time is 2063 (not 923 as at the shipped need rate) because the smith makes its own food and water trips; it still finishes inside the day.

Slowest five matrix decide calls and their cause: tick 0, 7 rows, 18.8 ms (everyone is scored once at start); ticks 1200 and 1800, 6 rows, 12.2 / 10.7 ms (the schedule time block changes, which is a signature change for every resident); ticks 716 and 676, 1 row, 9.7 / 8.0 ms (the first row of a tick pays the per-tick affordance cache build: interaction boxes, entities). Cost is about 2 ms per re-scored row (`AffordanceEngine.mask`), so a batch of N costs about 2N ms. Before `warm()` the first call was 34.8 ms; `MatrixTier1.warm` / `AgentDriver.warm` (called at the first re-score, or by a server at start) moves that cost out of the decision figures.

Limits of this acceptance: Tier 1 walks goals through `AnchorMover`; it does not call `ActionRunner` (design below), so "no `run:failed` storm" is vacuous for Tier 1 today (the Tier 3 counter is 0 because no plan runs). The bound of 60 for needs is close to the measured 55.6: thirst peaks while the smith crosses the portal to the well. The matrix is bit-equal to rules by construction (prior 100 with placeholder weights); the plumbing that carries a different matrix choice is covered by `test_with_the_prior_at_zero_the_matrix_choice_changes_the_macro`.

## Matrix weights v2: imitation-trained from the rules prior (`model_server/train_matrix.py`, `systems/actions/weights.py`)

* **What it is.** No external model. The labels are the rules' own decisions: `--collect` runs the agent-mode village for several seeds (hunger/thirst U(0,85), hp U(60,100), agent-mode legality mask), records each resident's (X, P, legal mask, rules macro) every few ticks, and `fit` trains only `W` and `b` of `S = X@W + (X@U)*(P@V) + b` (the personality term `U`, `V` stays the prior's) by LBFGS on cross-entropy to the rules label plus `prior_weight` x KL to the prior's distribution plus an L2 pull to the prior's weights. On rows where the rules have no opinion ("silent" rows) the KL term keeps the new policy near the old one.
* **Deterministic and versioned.** Same data file and hyper-parameters give a byte-identical `weights_v2.npz` (hash `1be410e9...d21f7`); the file carries the schema version, menu and content hash, and `weights_v2.provenance.json` records data hash, hyper-parameters and the gate numbers. The data is reproducible by seed.
* **Gate.** The file is written only if held-out (whole seeds not used in training) agreement with the rules improves and the mean silent-row KL to the prior stays <= 0.15. Measured: held-out agreement 0.646 -> 0.851 (train 0.616 -> 0.810), silent KL 0.136, largest weight shift 1.04.
* **Use.** `EDEN_MATRIX_WEIGHTS=<version>` (unset or `1` = the rules prior, which is what ships by default). `weights.default_policy()` loads the named file; a missing, unrecognised or tampered file (hash mismatch) falls back to the prior and records why in `weights.STATUS`. The agent driver (`MatrixTier1`) and the Tier 3 escalation use it; with the variable unset nothing changes (s1 digests identical on a clean HEAD).
* **What it does not change.** `MatrixTier1` adds `prior_strength` (default 1) x the rules prior to the scores, so with the default the rules macro still wins whenever it is legal: tier1 acceptance (3000 ticks, seed 1008, needs 0.5) is bit-identical for v1 and v2 (1612 decisions, same needs, same trips). v2 matters where the rules macro is illegal, or with `prior_strength` < 1; the acceptance of a pure matrix (prior_strength 0) is the next measurement before it is made a default.
* **Real models.** Tier 2/3 learned models stay held until the user's APIs; the rules prior is the permanent fallback.

### Why the pure matrix (`EDEN_MATRIX_PRIOR_STRENGTH=0`) runs 2-5x slower (profile, commons seed 1008, 1200 ticks, `--tier1 matrix`, cProfile, 76 s)

* The Tier 1 / driver cost is small: `AgentDriver.step` 6.2 s cumulative of 70.6 s in `Engine.step`.
* Half of the time is path search in the **legacy task system**, not in the model plane: `social._handle_talk_to_target` -> `_approach_human_target` -> `contracts.move_toward` -> `roster/motion.move_task_actor` -> `anchor_mover._plan` -> `movement/pathing.plan_path`: 35.8 s cumulative, 771 `plan_path` calls (about 46 ms each, 8.7 M heuristic calls), 2651 `talk_to_target` steps in 1200 ticks.
* What this means (inference from the profile, not separately measured): with the prior off the matrix queues `talk`-family tasks much more often than the rules do, and each one searches a long path. The verb-side cap (`EDEN_REACH_MAX_DISTANCE`) does not touch it: it caps the affordance engine's own `Reach` searches, not the task system's mover.
* Options, none taken: (a) a request-size cap inside `plan_path` or a per-resident replan budget in the mover (movement files, 9d882a's); (b) a cheaper `social` task approach (walk straight when the segment is clear); (c) leave `prior_strength` at 1 or 0.5 (bit-identical to the rules) where wall time matters.

### Instinct features: cold, hot, wounded, fear_memory, tired, dark (`systems/decision/instinct_features.py`, `INSTINCT_SCHEMA_VERSION` 2)

* **Shape.** A separate versioned block `E` (N x 6; version 1 had the first four columns, version 2 appends `tired` and `dark` at the end, so the v1 indices do not move) with its own hand-weight table `EXT_SPEC` (E x K), added to the macro scores in `MatrixTier1.decide` (`scores + E @ W_ext`). The base matrix is untouched: `matrix.FEATURES` (F = 26), `FEATURE_SCHEMA_VERSION` 1, the shipped weights v1 (prior) and v2 (trained, hash `1be410e9...d21f7`) load as before (tested). Adding the columns to `FEATURES` would change F and invalidate both files; the versioned extension avoids that, and a v3 retrain that folds the block into `W` is a later, deliberate step (a `matrix.py` edit plus a `train_matrix.py` run on data from a world with the flags on).
* **Columns, each live only with its own flag** (off: 0 and the reader is never called): `cold`, `hot` = `temperature.cold_of / hot_of(engine, slot)` / 20 degrees (`EDEN_TEMPERATURE`); `wounded` = `wounds.bleed_of(engine, uid)` / 0.3 (`EDEN_WOUNDS`); `fear_memory` = `danger.danger_pressure(engine, uid, x, y)` (`EDEN_DANGER`); `tired` = `sleep.debt_of(engine, uid)` / 100 (`EDEN_SLEEP`); `dark` = `darkness.unease_of(engine, slot)` (`EDEN_DARKNESS`, 0..1; a fire lit by `light_fire` counts as light and relieves it).
* **Weights** (go_home +1.6 cold / +0.8 hot / +1.0 wounded / +0.8 fear; rest +1.5 wounded; ask_for_help +1.2 wounded; avoid +1.2 fear; sleep +2.4 tired, rest +1.6 tired, go_home +0.8 tired / +1.4 dark, work_at_station -1.2 tired, explore -1.0 tired / -1.5 dark; explore -1.0 cold, -1.5 wounded, -1.5 fear; work_at_station -1.5 wounded; others in `EXT_SPEC`). They are hand weights like the v1 prior, not trained.
* **Identity.** With all five flags off `instinct_features.scores` returns `None` and `decide` adds nothing: scores, macros and `last_detail` are the ones from before (tested; Tier 1 acceptance, weights, driver and Tier 2 tests unchanged).
* **What it does not do.** At `prior_strength` 1 (the default) the rules macro still wins whenever it is legal, so the block changes nothing there; it acts in the matrix-led modes (`EDEN_MATRIX_PRIOR_STRENGTH` < 1) and is recorded in `MatrixTier1.last_instinct` for the Tier 2 gate and acceptance. The reflexes themselves (seeking warmth, bleeding) are 9d882a's Tier 0 instincts.
