# Perception Design

Status: live and foundational across many systems.

This module owns spatial sensing helpers, nearby-entity queries, local perception contexts, and target ranking utilities. It is the shared sensing layer used by movement, survival, combat, construction, and other domain modules.

Primary files:
- `queries.py` for nearby and nearest-entity helpers
- `context.py` for local perception bundles
- `resolver.py` for ranking and best-target selection
- `ops.py` as the combined surface

Main runtime wiring:
- Imported directly by `at_the_beginning/instincts_and_tools.py`
- Used indirectly by `systems.combat`, `systems.survival`, `systems.construction`, and others
- Also used for local world-context generation in higher-level logic

Owned data:
- Local perception contexts
- Nearby-entity and nearest-target queries
- Target ranking helpers

Perception is a utility-heavy module that should remain fast, local, and deterministic. It supplies what is nearby rather than what should happen next.
