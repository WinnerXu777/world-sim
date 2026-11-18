# Map Future

Current limitations:
- Chunk generation and streaming are still early and presentation-oriented
- Frontier generation is simpler than the long-term infinite-world target
- Human-mode chunk loading is functional but not yet fully optimized

Nuances:
- The backend should keep owning 2D truth, even as the client renders human mode in 3D
- Existing `infinite_map_design.md` remains the deeper planning document for this module

Suggested next elaborations:
- Improve persistence and regeneration rules for explored versus unexplored chunks
- Add stronger server-to-client chunk payload contracts for 3D human mode
- Expand terrain semantics, biome transitions, and structure-aware chunk exports
- Add LOD and preload strategies tuned for first-person and third-person play
