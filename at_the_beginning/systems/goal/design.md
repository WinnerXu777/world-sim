# Goal Design

Status: partially live as the resident long-term intent layer.

This module owns structured resident goals, goal review cadence, starter-goal generation, event-driven goal updates, and prompt-facing goal summaries.

Primary files:
- `schema.py` for goal records
- `catalog.py` for the goal ontology
- `lifecycle.py` for persistence, dedupe, and review cadence
- `generators.py` for starter and event-driven goal generation
- `review.py` for review entry points
- `ops.py` and `prompt_view.py` for runtime integration

Main runtime wiring:
- Imported by `at_the_beginning/runtime/resident_store.py` to ensure and refresh resident goals
- Used by `at_the_beginning/runtime/human_runtime.py` for prompt payloads
- Used by `at_the_beginning/runtime/world_runtime.py` for reasoning packets
- Used by `at_the_beginning/tools_execution/plot/executors.py` to apply structured goal updates

Owned data:
- Resident `goals`
- Goal review state
- Goal prompt payloads and primary-goal selection

Goals are currently the durable intent layer above memories and pressures. They are already persisted in resident JSON, but richer model-driven review is still evolving.
