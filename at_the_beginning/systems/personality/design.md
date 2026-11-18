# Personality Design

Status: live as the stable resident bias layer.

This module owns archetype assignment, trait vectors, birth-time jitter, personality summaries, and pressure appraisal derived from resident state. It provides the long-lived who-this-resident-tends-to-be layer.

Primary files:
- `catalog.py` and `traits.py` for archetypes and trait helpers
- `assign.py` for deterministic assignment and compatibility
- `appraisal.py` for pressure computation
- `prompt_view.py` and `ops.py` for runtime-facing summaries

Main runtime wiring:
- `at_the_beginning/runtime/resident_store.py` ensures personality on resident creation/load
- `resident_store.py` also refreshes resident pressures
- `at_the_beginning/runtime/human_runtime.py`, `world_runtime.py`, and `talk_runtime.py` read personality summaries for prompts and heuristics

Owned data:
- Resident `personality`
- Trait vectors
- Pressure summaries

Personality is already a first-class resident-state layer. It biases decisions without directly executing them.
