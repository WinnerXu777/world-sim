# Memory Design

Status: live as a separate resident-memory retrieval layer with runtime wiring.

This module owns `MemoryLightRAG`, resident-to-graph synchronization, retrieval bundles, and prompt-facing memory context. Resident JSON remains the canonical source of truth; the graph is a derived retrieval layer.

Primary files:
- `state_memoryrag.py` for graph storage and retrieval
- `graph_sync.py` for resident synchronization
- `retrieval.py` for prompt-facing bundles
- `ops.py` for stable runtime helpers
- `memory_design.md` for the deeper architecture write-up

Main runtime wiring:
- `at_the_beginning/map_test.py` owns the engine `memory_rag`
- `at_the_beginning/runtime/human_runtime.py` retrieves memory bundles for human cases
- `at_the_beginning/runtime/world_runtime.py` retrieves memory bundles for resident reasoning
- Resident updates and queue-driven syncs flow through the resident store and memory ops

Owned data:
- Memory graph nodes and edges
- Retrieval index state
- Memory bundles for prompts

This module is already a key bridge between resident-side state and the reasoning-facing prompt layer.
