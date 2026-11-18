# Tasks Design

Status: live as the main human activity execution spine.

This module is intended to become the master activity execution layer for the
simulation. It should unify ordinary work, procurement, movement, crafting,
and later strategic execution without replacing higher-level systems like
personality, goals, planning, or occupation.

Primary files:
- `catalog.py` for task kind definitions
- `schema.py` for task and task-state records
- `lifecycle.py` for resident queue/state normalization
- `resolver.py` for current-task and queue queries
- `prompt_view.py` and `ops.py` for runtime-facing helpers
- `contracts.py` for the stable task-world bridge and execution context
- `dispatcher.py` for family dispatch and live execution entry
- `families/occupation.py` for the current live occupation task family
- `families/survival.py` for the first live non-occupation task family
- `families/social.py` as the home for socialize, talk follow-through,
  courtship / mating, and richer support / gratitude / escort follow-through
- `families/combat.py` as the live attack / chase / retreat / guard task family
  plus the first hunt-finish / ally-protect extensions
- `families/strategic.py` as the live plan-execution family for the first
  structured plan steps
- `executor.py` now acts as a compatibility re-export layer while the refined
  structure takes over

Main runtime wiring:
- Ensured on residents through `runtime/resident_store.py`
- Exposed in resident-facing payloads through:
  - `runtime/human_runtime.py`
  - `runtime/world_runtime.py`
  - `map_test.py`
- `map_test.py` now uses task primitives for baseline occupation provisioning
  and the first set of task-driven occupation loops (`woodcutter`,
  `fisherman`, `farmer`, and `guard`)
- `map_test.py` now routes baseline survival tasks like `fetch_water`,
  `eat_food`, `seek_shelter`, `sleep`, and `flee_target` through the same
  dispatcher and task-world bridge
- `map_test.py` now routes first social courtship tasks through the same
  dispatcher path using `socialize`, `warn_target`, `call_for_help`,
  `help_target`, `deliver_item`, `escort_target`, `thank_helper`,
  `comfort_target`, `report_crime`, `seek_mate`, and `mate_with_target`
- `map_test.py` now routes baseline routine follow-through through task-owned
  routine movement instead of human schedule/navigation instincts
- `map_test.py` now routes autonomous human combat through task-owned
  `attack_target`, `chase_target`, `retreat_from_target`, `guard_area`,
  `protect_target`, `intercept_target`, and `finish_hunt` execution and
  resolves player-controlled human movement / attack outside the instinct
  registry
- `map_test.py` now routes the first plan-driven resident execution through
  task-owned strategic actions like `acquire_weapon`,
  `move_to_ambush_point`, `wait_in_hiding`, `recruit_ally`,
  `steal_from_container`, `escape_area`, `protect_home`, and
  `gather_food_buffer`
- `map_test.py` now builds a `TaskWorldBridge` and `TaskExecutionContext`,
  then calls the shared dispatcher entry point in `systems/tasks`

Owned data:
- resident `tasks`
- resident `task_state`
- task queue records
- active task summaries

Current scope:
- provide a clean home for task state and queue helpers
- make task context visible to the rest of the runtime
- begin migrating profession and crafting execution into one shared task layer
- begin migrating baseline survival execution into the same shared task layer
- own the live non-reflex human execution path that used to sit in
  `instincts_and_tools.py`
- drive baseline provisioning through reusable task primitives
- own the main live orchestration of active task execution while lower modules
  provide concrete world actions
- establish a stable module-level execution contract between the runtime and
  task families instead of passing raw callback dicts
- drive ordinary occupation loops through reusable task patterns like
  `move_to_place`, `chop_wood`, `fish_work`, `farm_work`, `gather_work`,
  `build_work`, `hunt_work`, `heal_work`, `trade_run`, `patrol_area`,
  and `store_item`
- support richer queue replacement with paused task storage and resumable work
- serve as the shared execution surface for both routine occupation work and
  the first live plan-driven strategic actions

The task layer now owns the live non-reflex human activity loop for baseline
occupation work, survival responses, social follow-through, routine
follow-through, autonomous combat, and the first live strategic plan steps.
Future work is now about broadening family depth rather than finishing the
basic ownership handoff.
