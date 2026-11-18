# `instincts_and_tools.py` Migration Plan

## Goal

Shrink [instincts_and_tools.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/instincts_and_tools.py) down to:

- ticking
- reflex
- state sync

Everything else should migrate into system modules, with `systems/tasks` acting as
the main execution coordinator for resident activity.

## End State

### What stays in `instincts_and_tools.py`

Only low-level, always-on, simulation-foundation behavior should remain:

- vital ticking
  - `instinct_age`
  - `instinct_hunger`
  - `instinct_thirst`
  - `instinct_stamina_tick`
  - `instinct_emotional_recovery`
  - `instinct_infection_tick`
- death / cleanup
  - `instinct_die`
  - `instinct_hp_death`
- state sync
  - `instinct_shelter_check`
  - `instinct_structure_occupancy`
  - minimal control-state sync like `instinct_player_control_override`
- true reflex / immediate body scripts
  - panic jolt
  - hit reaction
  - immediate hazard recoil
  - minimal hardcoded flee primitive if needed as a low-level helper, not as a main behavior path
- world/environment ticking
  - `instinct_nature_cycle`
  - `instinct_fire_tick`
  - `instinct_lava_tick`
  - `instinct_resource_regrow`
  - `instinct_water_cycle`
  - `instinct_frontier_expand`

### What leaves `instincts_and_tools.py`

All non-instant resident execution behavior should move out:

- survival execution
  - `instinct_eat`
  - `instinct_drink`
  - `instinct_survival_navigation`
- social / courtship execution
  - `instinct_search`
  - `instinct_reproduction_strategy`
  - `tool_reproduce`
  - eventually most mating-related pairwise execution
- routine movement and life follow-through
  - `instinct_social_navigation`
  - `instinct_schedule_navigation`
  - `instinct_move`
- combat execution
  - `instinct_attack`
  - related human combat-followthrough logic
- occupation / work execution
  - already moving into `systems/tasks`

The rule is:

- instinct layer = body/state/time
- task layer = action execution
- reasoning layer = intent / planning

## Current Migration Status

### Active human loop ownership

The live human loop has now been migrated off the old instinct-side execution
path:

- baseline survival execution is task-owned
- routine movement / routine follow-through is task-owned
- courtship / mating execution is task-owned
- autonomous human combat execution is task-owned
- manual player-controlled human movement / attack execution is runtime-owned
  outside the instinct registry

That means the active human registry no longer owns ordinary:

- eat / drink execution
- reproduction execution
- navigation / movement execution
- combat execution

### Already moved or partially moved

- occupation execution is live through `systems/tasks`
  - woodcutter
  - fisherman
  - farmer
  - guard
- baseline survival execution is live through `systems/tasks/families/survival.py`
  - `fetch_water`
  - `eat_food`
  - `sleep`
  - `seek_shelter`
  - `flee_target`
- social execution is live through `systems/tasks/families/social.py`
  - `socialize`
  - `seek_mate`
  - `mate_with_target`
- combat execution is live through `systems/tasks/families/combat.py`
  - `attack_target`

### Legacy overlap status

The earlier gating work served its purpose, but the main overlapping human
registry entries have now been removed from the active registry path instead of
just being masked.

## Ownership Map

### `systems/survival`

Should end up owning:

- hunger / thirst ticking
- shelter flags and occupancy sync
- survival policy thresholds

Should **not** remain the main execution home for:

- going to food
- going to water
- sleeping
- fleeing to safety

Those now belong in `systems/tasks/families/survival.py`.

### `systems/social`

Should end up owning:

- reproduction eligibility rules
- cooldown policy
- social-state helpers
- pairwise-policy helpers if still useful

Should **not** remain the main execution home for:

- moving toward a mate
- resolving mating as a resident activity loop
- talk-followthrough
- escort / approach / socialize execution

Those should live in `systems/tasks/families/social.py`.

### `systems/combat`

Should own:

- intent gathering
- targeting rules
- damage resolution
- huntability / range checks

`systems/tasks/families/combat.py` should become the execution coordinator for:

- attack target
- chase target
- flee target if combat-driven
- guard target

### `systems/tasks`

This should become the single execution spine for resident activities:

- occupation work
- survival execution
- social execution
- combat execution
- strategic / plan-driven execution

## Migration Principles

### 1. No dual ownership

Once a behavior has a real task-family path, the instinct path must:

- gate itself off when task-owned
- then be removed after the task path is stable

### 2. Keep ticking separate from action

Needs should still rise in the instinct layer:

- hunger goes up
- thirst goes up
- stamina changes over time
- infection ticks

But the *response* should be task-driven.

### 3. Reflex stays below tasks

If something must happen instantly this tick, keep it outside tasks.

Examples:

- got hit
- touched lava
- immediate panic spike
- immediate hazard bounce

Everything else should become a task if it is a multi-step activity.

### 4. Migrate by family, not by giant rewrite

The safest order is:

1. gate old behavior
2. add live task-family replacement
3. verify parity
4. remove registry entry / old executor
5. keep only tiny compatibility wrappers if still needed

## Ordered Migration Waves

### Wave 1: Finish Survival Migration

Status: complete in the active registry path.

Objective:

- remove remaining non-reflex survival execution from the instinct loop

Already done:

- task-driven survival family is live
- instinct-side gating is in place

Next removals:

- remove `instinct_eat` from active execution once task path is fully trusted
- remove `instinct_drink`
- remove `instinct_survival_navigation`

What remains afterward:

- `instinct_hunger`
- `instinct_thirst`
- `instinct_stamina_tick`
- `instinct_shelter_check`
- `instinct_structure_occupancy`

### Wave 2: Finish Courtship / Mating Migration

Status: complete in the active registry path.

Objective:

- move reproduction execution fully into `systems/tasks/families/social.py`

Already done:

- `seek_mate`
- `mate_with_target`
- engine bridge for human-target resolution and mating action
- instinct-side seek/reproduction gating

Next removals:

- remove `tool_reproduce` from the live human registry path
- retire courtship execution dependence on `seek_mask` for humans
- reduce pairwise reproduction coupling inside `instinct_move`

What remains in `systems/social`:

- safety / eligibility policy
- cooldown policy
- relationship / grouping helpers

### Wave 3: Migrate Human Movement Ownership

Status: complete for ordinary autonomous human movement.

Objective:

- stop using `instinct_move` as the main human execution path

Target split:

- tasks move humans toward goals
- reflex handles immediate impulse motion
- `instinct_move` should shrink or disappear for humans

Actions:

- route more task families through bridge movement
- remove dependence on `nav_survival_bias`, `nav_social_bias`, and `nav_schedule_bias`
  for humans once equivalent task producers exist

Likely destination:

- `systems/tasks/families/survival.py`
- `systems/tasks/families/social.py`
- `systems/tasks/families/occupation.py`
- future `systems/tasks/families/combat.py`

### Wave 4: Bring Combat Family Online

Status: baseline attack flow complete.

Objective:

- make combat execution task-owned except for true instant reflex pieces

Move toward:

- `attack_target`
- `chase_target`
- `combat_flee`
- `guard_target`

Keep outside tasks:

- immediate hit reaction
- raw damage application
- one-tick panic jolt

Likely file targets:

- `systems/tasks/families/combat.py`
- `systems/combat/*` remains the rules / resolution backend

Then retire or shrink:

- `instinct_attack`
- combat-driven movement pieces inside `instinct_move`

### Wave 5: Retire Human Pairwise Navigation From Instinct Loop

Status: complete in the active registry path. Pairwise helpers can remain as
pure utilities, but the pairwise navigation registry stages are no longer part
of the live human loop.

Objective:

- stop relying on pairwise-navigation bias for ordinary human execution

Move out of the registry path:

- `instinct_pairwise_relations`
- `instinct_social_navigation`
- most human pairwise-movement coupling

Keep only if still needed as a reusable helper:

- pairwise builder as a pure utility in `systems/social/grouping.py`

### Wave 6: Final Human Registry Cleanup

Status: active registry cleanup complete for the ordinary human loop.

Target human registry shape:

- age tick
- hunger tick
- thirst tick
- stamina tick
- emotional recovery tick
- death checks
- heal / infection tick
- shelter / occupancy sync
- player-control sync
- true reflex hooks

Everything else should be task or system owned.

## Registry Target

### Registry entries removed from the active human activity loop

- `instinct_search`
- `instinct_reproduction_strategy`
- `instinct_pairwise_relations`
- `instinct_survival_navigation`
- `instinct_social_navigation`
- `instinct_schedule_navigation`
- `instinct_eat`
- `instinct_drink`
- `instinct_attack`
- `instinct_move`
- `tool_reproduce`

### Registry entries that now remain in the active human loop

- `instinct_age`
- `instinct_hunger`
- `instinct_thirst`
- `instinct_stamina_tick`
- `instinct_emotional_recovery`
- `instinct_die`
- `instinct_hp_death`
- `instinct_heal`
- `instinct_shelter_check`
- `instinct_structure_occupancy`
- `instinct_infection_tick`
- `instinct_player_control_override`
- world/environment tick entries

## Suggested Engine Refactor

To make the migration clean, the engine should eventually formalize three layers:

### 1. Tick / Reflex Layer

Runs through the lightweight registry:

- ticks
- state sync
- reflex

### 2. Task Producer Layer

Decides what task queue should exist right now:

- survival producer
- social producer
- occupation producer
- plan / reasoning producer
- escalation producer

This can live in engine-side sync helpers first, then become cleaner over time.

### 3. Task Execution Layer

Always goes through:

- `TaskWorldBridge`
- `TaskExecutionContext`
- `dispatcher.execute_active_task_step(...)`

## Concrete Next Steps After This Doc

1. Remove live dependence on `tool_reproduce` in the human loop once the social
   task slice is stable across more scenarios.
2. Start reducing `seek_mask` dependence in human movement now that courtship is
   task-driven.
3. Bring `families/combat.py` online so `instinct_attack` can start shrinking.
4. Move more human movement ownership out of `instinct_move`.
5. After each family stabilizes:
   - gate old instinct path
   - verify
   - remove old path

## Success Condition

The active-loop migration is complete when:

- `instincts_and_tools.py` no longer owns ordinary human action execution
- resident survival, social, combat, occupation, and routine activity all run
  through task/runtime orchestration instead of the old instinct registry path
- the instinct layer handles:
  - ticking
  - reflex
  - state sync

That active-loop condition is now met. Future work is about deepening task
families and shrinking leftover utility code, not restoring instinct-side
ownership.
