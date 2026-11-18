# Construction Design

Status: live for world-side structure creation and repair, with a first
task-driven resident construction pass for personal shelter and farm support
projects, plus inventory-backed material delivery.

This module owns build-site selection, material gathering helpers, structure spawning, settlement construction tools, repair, demolition, and occupancy-related queries.

Primary files:
- `building.py` for structure creation and build tools
- `catalog.py` for refined building blueprints and construction categories
- `schema.py` for building-need and project records
- `lifecycle.py` for resident-facing construction state/profile helpers
- `needs.py` for deterministic building-need evaluation
- `prompt_view.py` for reasoning-facing summaries
- `sites.py` for site selection and blueprint resolution
- `materials.py` for nearby resource gathering helpers
- `repair.py` for repair and demolition flows
- `occupancy.py` for occupancy masks and structure usage helpers

Main runtime wiring:
- Imported by `at_the_beginning/instincts_and_tools.py`
- Used by tool-facing world operations and decree execution
- Resident state is normalized through `runtime/resident_store.py`
- Human/world reasoning payloads now include construction summaries
- `map_test.py` now evaluates resident construction needs, creates projects, and
  routes live build execution through `systems/tasks`
- Depends on `systems.perception` for nearby-site/resource checks
- Depends on `systems.health` for structure durability and repair state

Owned data:
- Buildable-site rules
- Construction blueprints
- Construction need records
- Construction project records
- Material-source filters
- Repair and demolition helpers

Construction is still primarily the authoritative structure/site module, but it
now also has a live resident-facing layer:

- deterministic building need emission
- resident construction state and project records
- prompt summaries for reasoning
- first task-driven project designation/build advancement

The current live slice is intentionally narrow. It covers:

- `personal_shelter`
- `farm_plot`

And it now does real resident-side material flow:

- residents gather/craft real item stacks
- carried materials are delivered into project metadata
- completed `personal_shelter` now doubles as the resident's house storage anchor

Settlement/public building needs like `village_well` and `market_anchor` are
still scaffolded rather than fully emitted/executed live.
