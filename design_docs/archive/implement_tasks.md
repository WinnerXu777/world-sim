# Tasks Implementation

`systems/tasks` is the master activity execution layer for the simulation.
It should not replace reasoning, personality, or occupation. Instead, it turns
their outputs into concrete, interruptible work.

Core split:
- `occupation` says what kind of work a resident tends to do
- `schedule` says when ordinary work should happen
- `crafting` and `construction` define recipes and structures
- `goal` and `planning` define special long-horizon intent
- `tasks` turns all of that into executable step-by-step activity

Task ownership:
- resident `tasks` queue
- resident `task_state`
- task record schema
- queue helpers
- prompt/export summaries for the rest of the runtime
- later execution and interruption rules

Design rule:
- `tasks` is the master executor, not the master thinker
- many systems may create tasks
- task execution should still happen in one unified layer

Expected task producers:
- `occupation`
  baseline work tasks such as fishing, chopping wood, or patrol
- `schedule`
  ordinary time-of-day activation of routine tasks
- `crafting`
  procurement, gather, withdraw, craft, equip, and store sub-tasks
- `planning`
  strategic task chains such as ambush prep or revenge procurement
- `survival`
  emergency override tasks like fetch water, eat, flee, or seek shelter
- `talk` and `escalation`
  interrupt, suspend, or enqueue reactive tasks

Initial task families:
- movement
- gather
- inventory
- crafting
- occupation_work
- survival
- social
- combat

Example resident-side task chain:
1. `occupation = woodcutter`
2. `schedule = work_site`
3. `tasks` queue becomes:
   - `ensure_required_tool`
   - `gather_material`
   - `craft_item`
   - `move_to_place`
   - `chop_wood`
   - `store_item`

Example strategic override:
1. reasoning queue creates `plan = revenge`
2. planning emits:
   - `acquire_weapon`
   - `move_to_place`
   - `ambush_target`
3. `tasks` executes those instead of ordinary occupation work until resolved

Resident data model:
- top-level `tasks: []`
- top-level `task_state: {}`

Recommended first record shape:
```json
{
  "id": "task_000001",
  "task_kind": "craft_item",
  "status": "queued",
  "priority": 0.82,
  "source": "crafting_baseline",
  "summary": "craft fishing_rod",
  "target_kind": "item",
  "target_id": "fishing_rod",
  "target_place": {},
  "required_item": "knife",
  "requested_quantity": 1,
  "goal_id": null,
  "plan_id": null,
  "created_tick": 1200,
  "last_update_tick": 1200,
  "metadata": {}
}
```

First implementation phases:
1. Scaffold `systems/tasks`
2. Add resident `tasks` and `task_state`
3. Expose task summaries in human/world runtime payloads
4. Move baseline occupation provisioning into reusable task primitives
5. Make one occupation, likely `woodcutter`, use a fuller task chain
6. Expand into broader profession work

Near-term runtime wiring:
- ensure task state in `runtime/resident_store.py`
- expose task summaries in:
  - `runtime/human_runtime.py`
  - `runtime/world_runtime.py`
  - `map_test.py`

Later runtime wiring:
- `map_test.py` should stop hardcoding special profession steps directly
- task executor should become the shared place for movement, gather, withdraw,
  craft, store, and ordinary work loops

Current scope for this slice:
- scaffold module and docs
- resident state integration
- prompt/export integration
- not yet full task execution takeover
