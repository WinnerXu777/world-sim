# Occupation Design

Status: partially live.

This module owns medieval occupation blueprints, occupation assignment, inheritance-plus-mutation logic, and schedule-facing routine preferences. It is intended to become the main ordinary-life blueprint layer for residents.

Primary files:
- `catalog.py` for occupation blueprints
- `schema.py` for occupation records
- `inheritance.py` and `assign.py` for weighted assignment
- `resolver.py` for occupation-driven routine preferences
- `prompt_view.py` and `ops.py` for runtime-facing helpers

Main runtime wiring:
- Ensured on residents through `runtime/resident_store.py`
- Feeds `systems/schedule` as the primary routine source when an occupation is present
- Feeds baseline tool provisioning through `systems/crafting`
- `woodcutter`, `fisherman`, `farmer`, and `guard` now have the first task-driven
  ordinary work loops through `systems/tasks`
- Exposed in resident-facing prompt and export payloads

Owned data:
- resident `occupation`
- occupation assignment metadata
- occupation-driven schedule preferences
- baseline required tools and optional tool upgrades

The current module is intentionally declarative. It shapes ordinary-life
behavior without directly executing profession logic. Occupation is intended to
own baseline work identity and baseline tool needs, while strategic tool
requests should later come from goals and plans.
