# Map Design

Status: live for 2D world truth, frontier expansion, and chunk streaming support.

This module owns map creation, frontier expansion, chunk coordinate math, chunk streaming diffs, and natural feature creation. It is the authoritative spatial domain for the backend simulation.

Primary files:
- `create.py` for feature and settlement creation
- `expand.py` for frontier growth
- `chunking.py` for chunk windows and diffs
- `chunk_generation.py` for frontier feature planning
- `infinite_map_design.md` for the larger map direction

Main runtime wiring:
- Imported directly by `at_the_beginning/instincts_and_tools.py`
- Used by `at_the_beginning/map_test.py` for chunk streaming and human-view window generation
- Feeds the Godot client with chunk-window-based world slices

Owned data:
- Chunk math and payloads
- Frontier expansion plans
- World feature creation helpers

The map module keeps the backend authoritative in 2D while enabling client-side 3D projection and selective chunk loading in human mode.
