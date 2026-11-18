# Scheduler integration: calling the harness from the Engine (DESIGN ONLY, no code, no Engine.step edit)

Author: harness worker (837dca). Status: proposal for the orchestrator. Decision needed in section 7 before any edit to `map_test.py`.

## 1. Goal and constraints
Run the harness (`World`/`EngineWorld`, `Registry.schedule`, `EffectApplier`, `EventLedger`, powers, tasks) inside the live tick, **behind a default-off flag**, with the golden trace as the guard: flag off = byte-identical to today (trivial), flag on = identical hashes for every stage that is declared "no behaviour change", and an explained, regenerated golden for the stage that is allowed to change behaviour. No edit to `Engine.step` until stage S5.

## 2. What exists today (read from `map_test.py`, `simulation/dispatch.py`)
`Engine.step` (map_test.py 4851-4962) runs, in order: pause check; movement snapshot; `world_contract`; `player_control` maintenance; **`command_inbox.drain(self, DISPATCH.execute)`** (all god and inventory commands arrive here); `world_agent.process_queues` (decree/plot execution); the **legacy registry loop** (`for entry in self._registry: entry["fn"](ctx, **kwargs)`, order fixed at construction); talk and human agents; manual control; the movement reconcile; **`DISPATCH.run_step_hooks`**; `_sync_slot_ids_and_events`; **`DISPATCH.run_post_step_hooks`**; frame/map payloads; `self.tick += 1`.

Three seams already exist and need no change to `Engine.step`:
* `DISPATCH.register_step_hook(name, fn(engine))`, runs after the reconcile; `register_post_step_hook`, runs after the id/event sync; `register_genesis_hook(name, fn(engine, map_name))`, runs at the end of `create_genesis`.
* `DISPATCH.register_executor(action, fn(engine, action, payload))`, the route for commands drained from the inbox (used today for `god_heal`, `god_weather`, `commission_*`, `portal`).
* Hooks are exception-isolated: a raising hook is logged and recorded in `DISPATCH.errors`, and the tick continues. (Good for safety; it also means a broken harness hook is invisible unless a test checks `DISPATCH.errors`.)
`systems/roster/install.py` is the existing pattern: `install_smith_loop(DISPATCH)` is called once at import (map_test.py:393), registering builtin hooks.

## 3. Proposal: install through the existing seams, in five independently landable stages
All stages are guarded by one environment flag `EDEN_HARNESS` (default unset = off). `harness/engine_hooks.py` (new, mine) provides `install(dispatch)`; the only edit outside my files is the call site (section 7, decision A): three lines in `map_test.py` next to `install_smith_loop(DISPATCH)`:
```
if os.environ.get("EDEN_HARNESS") == "1":
    harness_hooks.install(DISPATCH)
```

| stage | what runs | hook / seam | behaviour change | golden expectation | guard |
|---|---|---|---|---|---|
| S0 | one shared `EngineWorld` per engine, built lazily and rebuilt when `engine.world_epoch` changes; `engine.harness` accessor returns it | genesis hook | none | identical | test: world exists, tick/revision track the engine, a reset replaces it |
| S1 | event bridge: legacy event sources (god events in `systems/god/events.py`, death/birth detected in `_sync_slot_ids_and_events`) are mirrored into the `EventLedger` once per tick | post-step hook | none (read-only mirror) | identical | test: every legacy god event appears once in the ledger with the same witnesses |
| S2 | schedule check: the legacy registry entries are declared as harness "legacy systems" (reads/writes from `1008_coverage_map.md`); `Registry.schedule()` order is compared with `engine._registry` order and a mismatch is recorded in `engine.harness.errors` | genesis hook | none (declaration + comparison only; the legacy loop still executes) | identical | test: schedule order == registry order on every shipped map; a deliberately reordered registry is caught |
| S3 | new-style `@system` functions (effects as data) run in phase order from a step hook, applied through one `EffectApplier` run per tick; none exist yet, so this stage is empty until the first reimplemented system (the first candidate is the hunger/thirst drain, the cheapest and best covered) | step hook | only for systems that are switched on | identical while no system is registered; regenerated, explained golden when the first system is switched on | each switched-on system needs an equivalence test against its legacy twin |
| S4 | powers over the command inbox: executor `harness_power` calls `harness.powers.call(engine.harness, name, args)`; god API route maps to it; the 9 ported powers become reachable | executor | none until a client sends the new command | identical | test: command applied at the inbox seam, event in the ledger, dry run changes nothing |
| S5 | replace the legacy registry loop by the scheduler (the only stage that edits `Engine.step`, at most about 6 lines at the `for entry in self._registry` loop, behind the flag) | `Engine.step` | none if S2 held (same order), then intentional once systems are migrated | identical when only legacy systems are scheduled | separate [DECISION] with the exact diff before touching it; D-005 (legacy frontier/expand frozen until Gate D) unchanged |

S0-S2 and S4 are pure additions through hooks that already exist. S3 and S5 are where behaviour can change, and each is gated by its own equivalence tests and a regenerated golden.

## 4. Revision and tick bookkeeping
* `World.revision` (harness, bumped by every non-empty `EffectApplier` run) is separate from the legacy stale-result revisions (world epoch, map state version). They answer different questions; I propose to keep them separate and expose both in `engine.harness.versions()`, rather than unifying (unifying would change what legacy stale-result checks see).
* `world.tick` reads `engine.tick` (already so in `EngineWorld`). Hooks run before `self.tick += 1`, so a hook sees the tick being computed, which is what events should be stamped with.
* The legacy population counter is resynced after any apply that spawns or removes humans (done in `EngineWorld.apply`, this change set); a power that kills residents no longer leaves `engine.pop_count` stale.

## 5. Hazards and mitigations
1. Bare vs package imports produce two module objects (`map_test` vs `at_the_beginning.map_test`). Hook functions receive the engine as an argument and import nothing global from the engine module. Test: install once, run through both import paths.
2. `DISPATCH.clear()` (tests) removes non-builtin hooks. Install with `builtin=True` like the roster hooks, so test isolation does not silently switch the harness off.
3. Exception isolation hides errors: `engine.harness.errors` collects them and a test asserts it is empty after N ticks on each shipped map.
4. GC freeze (`gcpolicy.freeze_after_load`) runs after the genesis hooks; the harness world built in the genesis hook is frozen with the world and thawed with it. Test extension of `test_harness_gcpolicy`: object count stays flat across reset cycles with the flag on.
5. Cost: S0-S2 must add less than 0.5 ms per tick (budget p99 24.7 of 50 ms today). Measured in MEASURE mode before the flag is ever enabled in the server; S1's mirror is the only per-tick work.
6. Determinism: counter-based RNG keyed by (seed, tick, system, entity) is unaffected by hook order; legacy global RNG (python/numpy/torch) is not touched by S0-S2, so goldens stay identical.
7. The Model plane's `systems/actions` runner needs the same `EngineWorld` instance (shared revision, one item store). `engine.harness` is the one accessor; I do not edit `systems/actions/`.

## 6. Test plan (all new tests in `tests/test_harness_engine_hooks.py`)
S0: world builds on genesis, replaced on reset, tick tracks engine. S1: god event mirrored once with the legacy witnesses. S2: order equality on all shipped maps plus a negative case. S4: inbox command applies a power atomically; dry run changes nothing; unknown power refused with a stable reason. Cross-cutting: flag off leaves `DISPATCH.step_hooks` unchanged; flag on, 300 ticks, `DISPATCH.errors` empty, strict golden identical (`golden_trace.py --check --strict` with `EDEN_HARNESS=1`).

## 7. Decisions requested
A. OK to add the three-line flag call in `map_test.py` beside `install_smith_loop(DISPATCH)` (this edit needs your OK per the standing rule on `map_test.py`)?
B. Event bridge sources for S1: only `systems/god/events.py` (recommended first, it already has witnesses), or also births and deaths from `_sync_slot_ids_and_events`?
C. S3 first system: hunger/thirst drain (recommended), or another?
D. S5 (editing `Engine.step`) stays a separate [DECISION] with the exact diff; confirm that is how you want it handled.

## 8. Not covered here
No adapter bridge from the harness `Task` store to the legacy `resident["tasks"]` queue (the actions package keeps its RecordOps for that); the harness `Transfer` path writes inventory through `LegacyItemStore` only; D-001 interiors-as-spaces is not implemented.
