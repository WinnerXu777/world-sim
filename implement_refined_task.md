# Refined Tasks Implementation

`systems/tasks` should now be treated as the execution orchestrator for resident
activity, while the previously built goal / planning / escalation stack remains
the reasoning orchestrator.

## Core Split

- `reasoning orchestrator`
  - `personality`
  - `goal`
  - `planning`
  - `escalation`
  - `talk`
  - `schedule`
  - `occupation`
- `execution orchestrator`
  - `systems/tasks`

- `reflex layer`
  - hardcoded instant scripts
  - hit reaction
  - immediate panic / hazard jolt
  - anything that should happen before task logic

The reasoning side decides what should happen.
The task side carries it out step by step.
The reflex layer stays outside tasks and handles only truly instant responses.

This means `systems/tasks` should become the shared execution coordinator for:

- ordinary occupation work
- baseline survival behavior
- future social / talk follow-through
- future combat and strategic plan execution

Only the truly instant body layer should remain outside tasks.

## Refined Task Shape

Instead of one growing `executor.py`, the task module should be split into:

- `contracts.py`
  - stable bridge between tasks and the live world/runtime
  - execution context
  - world callback surface
- `dispatcher.py`
  - chooses which task family handles the current task
  - owns the main `execute_active_task_step(...)` entry point
- `families/occupation.py`
  - baseline provisioning
  - ordinary work loops such as woodcutting, fishing, farming, patrol
- `families/survival.py`
  - food, water, sleep, shelter, and flee tasks
- `families/social.py`
  - talk, approach, socialize, and first mating / courtship tasks
- `families/combat.py`
  - future attack, flee, guard, chase tasks
- `families/strategic.py`
  - future plan-emitted tasks like ambush, theft, sabotage, revenge setup

The old `executor.py` can remain as a compatibility layer that re-exports the
current live pieces while the runtime migrates to the refined shape.

## Bridge Contract

The task layer should not directly depend on ad hoc engine internals.
Instead, runtime code should provide a stable world-action bridge.

Expected bridge surface:

- `resolve_place_target(place_tag, px, py, radius)`
- `resolve_resource_target(resource_kind, px, py, radius)`
- `resolve_safe_target(px, py, radius)`
- `move_toward_point(tx, ty, magnitude)`
- `commit_action(...)`
- `withdraw_tool(tool_kind, need)`
- `available_ingredient_quantity(item_kind, material_cache)`
- `progress_toward_item_kind(item_kind, required_quantity)`
- `craft_tool(tool_kind, need)`
- `nearest_storage_case(px, py, radius)`
- `consume_resource(resource_kind, entity_id, quantity)`

This keeps `systems/tasks` as the main executor while still allowing the engine
to stay authoritative over the actual world state.

## Immediate Wiring Goal

For this refinement pass, the runtime should:

1. build a `TaskWorldBridge`
2. build a `TaskExecutionContext`
3. call `dispatcher.execute_active_task_step(context)`

That means:

- `map_test.py` becomes a thin bridge
- task family modules own execution flow
- future systems can add their own families without expanding one huge file

## Occupation First, General Backbone Next

Right now the live task system is still occupation-facing.
That is fine as a first phase, but the refined structure should make expansion
easy for:

- `survival` tasks
- `talk` / `social` tasks
- `combat` tasks
- `plan-driven` strategic tasks

The target architecture is:

- many systems produce tasks
- one task dispatcher executes them
- family modules keep the implementation modular

For the first non-occupation expansion, `families/survival.py` should come
online through the same dispatcher path. Survival should produce and execute
basic tasks like:

- `fetch_water`
- `eat_food`
- `sleep`
- `seek_shelter`
- `flee_target`

Those are still task-driven multi-step actions, not reflexes. A resident being
hit or jolted by danger remains a reflex. A resident then fleeing, sourcing
food, going to shelter, or sleeping should flow through `systems/tasks`.

The migration should continue by gradually retiring overlapping behavior from
`instincts_and_tools.py`. The clean rule is:

- keep vital-sign ticks and true reflexes in the instinct layer
- move non-instant survival execution into `families/survival.py`
- eventually move nearby courtship / mating execution into `families/social.py`
- keep the task dispatcher as the shared executor once an activity is no longer
  a one-tick reflex

## Near-Term Next Steps After This Refinement

1. keep `occupation` live through `families/occupation.py`
2. add real `survival` task handling
   - `fetch_water`
   - `eat_food`
   - `sleep`
   - `seek_shelter`
   - `flee_target`
   - survival should preempt occupation work, but still sit below reflex
3. let `talk` and `escalation` emit social/combat tasks
4. start migrating courtship / mating into `families/social.py`
   - first task kinds:
     - `seek_mate`
     - `mate_with_target`
5. let `planning` emit strategic task chains
6. keep shrinking the bridge until the engine only exposes a clean world-action interface

## Current Live State

The refined task architecture is now the live non-reflex human execution path:

- `families/occupation.py`
  - baseline provisioning
  - woodcutter / fisherman / farmer / guard work loops
- `families/survival.py`
  - `fetch_water`
  - `eat_food`
  - `sleep`
  - `seek_shelter`
  - `flee_target`
- `families/social.py`
  - routine `socialize`
  - `seek_mate`
  - `mate_with_target`
- `families/combat.py`
  - baseline autonomous `attack_target`

The old human instinct loop is no longer the active owner of ordinary:

- eating / drinking execution
- courtship / reproduction execution
- schedule / social navigation
- human combat execution
- human autonomous movement

Manual player-controlled movement and attack are also no longer executed through
`instinct_move` / `instinct_attack`; they now run through the control/runtime
path directly, while the instinct layer stays focused on:

- ticking
- reflex
- state sync
