# Movement Future

Current limitations:
- No full pathfinding layer yet
- Terrain-aware locomotion costs are still simple
- Human mode and sim mode still share a mostly top-down movement model

Nuances:
- Movement should stay a low-level execution layer, not absorb survival or combat decision logic
- Future vehicle or mount systems should build on this module rather than bypass it

Suggested next elaborations:
- Add pathfinding and waypoint support
- Add terrain, structure, and crowding costs
- Separate locomotion styles such as sprint, sneak, and mounted travel
- Improve embodied human-mode feel without breaking sim-side determinism
