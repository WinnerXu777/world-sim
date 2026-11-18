# Crafting Design

Status: partially live with baseline execution.

This module owns recipe blueprints for tools, components, and simple usable
items. It is intended to become the shared truth layer between `inventory`,
`occupation`, future manual incarnation crafting, and future resident
procurement/work loops.

Primary files:
- `catalog.py` for declarative recipes
- `schema.py` for crafting job records
- `lifecycle.py` for resident crafting state and baseline provisioning review
- `resolver.py` for recipe queries
- `stations.py` for future station requirements
- `prompt_view.py` and `ops.py` for runtime-facing helpers

Planned runtime wiring:
- Occupation uses baseline tool needs to drive ordinary provisioning checks
- Inventory and nearby storage are checked before crafting is requested
- Manual incarnation crafting should use the same recipes as residents
- Construction should later consume crafted outputs rather than inventing them
- Baseline occupation provisioning and strategic plan-driven crafting should stay distinct

Main runtime wiring:
- Residents now always carry a `crafting_state` through `runtime/resident_store.py`
- `at_the_beginning/map_test.py` now reviews baseline occupation provisioning against real owner inventory plus nearby storage
- `at_the_beginning/map_test.py` now executes conservative baseline provisioning steps:
  withdraw nearby tools, gather raw materials, craft simple intermediate components, and finish core occupation tools
- Those baseline provisioning steps are now also surfaced as reusable task
  primitives through `systems/tasks`
- Human and world reasoning prompt payloads now include crafting summaries

Owned data:
- Recipe definitions
- Ingredient requirements
- Required tool and station metadata
- Crafting job schema

The current module is still intentionally narrow. Baseline occupation
provisioning now executes in a conservative way, but there is still no player
crafting UI, no station use, and no broader resident job/task chain. The
current procurement order is equipped item -> personal inventory -> accessible
storage -> cached gathered materials -> craft.
