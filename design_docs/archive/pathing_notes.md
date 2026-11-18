# NPC pathing module — notes and integration points (2026-10-06)

Module: `at_the_beginning/systems/movement/pathing.py`. Tests: `tests/test_pathing.py` (18 tests, real `spatial.slide`). Not wired into schedules, the engine, or any existing file.

## 1. What it does

`find_path(start, goal, contract, cell=None) -> list[(x, y)] | None` and `plan_path(...) -> PathResult(waypoints, reason, cell, margin, expansions)` (the same search, with a reason).

* `contract` is the movement-contract dict `spatial.slide` reads: `actor_radius`, `bounds`, `boxes` (`{"min": [x, y], "max": [x, y]}`), e.g. `world_map.to_movement_contract(...)` or `spatial.world_contract(engine)`.
* Waypoints **exclude `start`** and **end with `goal` exactly as given**. `[]` means start == goal. `None` means no path; `plan_path(...).reason` is `start_not_standable`, `goal_not_standable`, `no_path`, or `search_limit` (budget exhausted; a route may still exist). Bad input (non-finite, radius ≤ 0) raises `ValueError`.
* Model is `slide`'s: boxes inflated by `actor_radius` (square footprint), open interiors, bounds shrunk by the radius, same 1e-4 "embedded" tolerance. `is_standable(point, contract)` is exported for spawn/anchor checks.
* Method: reject non-standable endpoints, return `[goal]` when the straight segment is clear (no grid built), else 8-connected A* (no diagonal corner-cutting, octile heuristic, deterministic tie-breaks) on a lattice at `cell = max(r/2, longest_side/800)`, collinear removal, then greedy line-of-sight string pulling. Waypoints and segments keep a 0.15-unit margin from the exact inflated edge; the search retries with a 0.02 margin and then a half-size cell if nothing is found, so doors with a centre band down to about 0.6 u are found (the validator's `2r + 1 u` gap rule leaves 1.0 u).

### Measured (on this machine, not a guarantee)
* 1200×900, 40 random boxes: 0.00–0.15 s per cross-map path (most under 0.1 s). A map-wide wall with one door plus 30 boxes: 0.17 s (57k expansions). A wall that forces a ~1,100-unit detour: 0.56 s (215k expansions).
* Worst case is a sealed or unreachable goal on a big open map: it explores until `max_expansions` (250k, ≈ 2 s) and returns `search_limit`. Small sealed rooms return `no_path` quickly. Do not call it per tick for unreachable goals; cache failures.
* Fuzz cross-check (scratch script, not in the suite): 400 random fields, 800 walks with 1.0 and 1.5 steps, 0 failures; all 36 `no_path` results were confirmed unreachable by an independent fine-lattice BFS.

## 2. Integration points (not done)

1. **Where plans are consumed today:** `systems/schedule/navigation.py:build_schedule_navigation_bias` (line 103) returns `nav_schedule_bias`, a per-slot unit vector × `ROUTINE_WEIGHT` toward the nearest entity of a type within 220 u (`navigation.py:170-190`), or a time-bucketed random wander. It is wrapped by `instinct_schedule_navigation` (`instincts_and_tools.py:1195`) and added to the random-walk noise in `instinct_move` (`instincts_and_tools.py:1415-1490`, priority 38 in the registry at `:3276`). There is **no** destination, arrival, or path state today.
2. **Smallest hook:** inside `build_schedule_navigation_bias`, replace the "unit vector to nearest entity" step with "unit vector to the next waypoint" when a plan exists for the slot. Keep a per-slot plan cache (`{human_id: {goal, waypoints, index, contract_revision}}`) on the engine or in the resident's `schedule_state`. The goal comes from a map anchor (door, work, talk, sleep, spawn) chosen by the routine, instead of `nearest_geo_entity`.
3. **Contract source:** `world_contract(engine)` (the one `step()` uses, `map_test.py:4723`) so NPCs path against exactly what `slide` enforces. Re-plan when the contract `revision` changes (walls built/destroyed).
4. **Arrival:** advance the waypoint index when the NPC is within about one step of it (1.0–1.5 u); finish the plan within an anchor tolerance of about 2 u (12 px), as proposed in the scale audit. Re-plan when the position is not progressing (no gain in distance to the next waypoint for N ticks), when the goal anchor changes, or after a flee/survival override.
5. **Other users of the same API:** player click-to-move (`move_target` in `control_runtime`/`manual.py:resolve_target_step` currently steps in a straight line and will stall on walls), `_move_human_toward_point` (`map_test.py:3231`, used by the baseline gather/provision loops) and task families with `arrival_radius` (`systems/tasks/families/social.py`, `construction.py`). These would take the next waypoint instead of the final target.
6. **Portals:** a path stops at the portal's source anchor; the map change is a separate step (rebaseline §4), so plan on the current map only.

## 3. Risks and open points

* **Speed cap.** Waypoint steering only chooses a direction. Actual displacement still comes from `instinct_move`: random noise ±1.0 u/tick per axis plus the survival/hazard/social biases (up to 10–20 u/tick) and the gather step of 2.4 u/tick (see `../reports/scale_constants_audit.md` §2.1). Without the per-map displacement cap, an NPC will overshoot waypoints and slide along walls at 2–10× player speed. A cap (≈ 1.5 u/tick) and removing the noise for path-following residents are prerequisites for P3.
* **Jitter.** Noise added on top of a unit-vector bias makes NPCs weave; near corners the margin (0.15 u) is smaller than one step (1.0–1.5 u), so a noisy NPC will graze corners and slide. The module guarantees straight-segment walkability with `slide`, not robustness to noise. Prefer moving a path follower by an exact step toward the next waypoint (then `slide`), as the tests do.
* **Embedded actors never move** (`slide` freezes a start inside an inflated box; measured in the scale audit). Planning returns `start_not_standable` for them. The caller must handle it (depenetrate to the nearest standable point, or teleport to an anchor) or the NPC is stuck forever.
* **Anchors:** every anchor must pass `is_standable` with the map's radius and sit in the centre band of a doorway. The goal is not moved: a non-standable goal returns `None`. Anchors for interactions (forge, chest) whose footprint is a collision box need an approach point outside the inflated footprint; pathing to the object's own center will always be `goal_not_standable`.
* **Cost:** pathing is not free on big maps. Plan on state changes (new routine, new anchor), not per tick; cache by `(start cell, goal, revision)`; throttle re-plans per NPC; cache negative results. With ~10 residents and sub-100 ms typical plans this fits a 50 ms tick budget only if spread over ticks.
* **Dynamic obstacles:** only wall boxes are considered; NPCs, players, animals and runtime-built walls (until the contract revision changes) are not. Actors do not collide with each other, so crowding is a visual issue, not a pathing one.
* **Animals** are not slid against walls at all today; do not use this module for them until they are.
* **Small radius / huge maps:** with the legacy radius 0.35 on 1200×900 the lattice is coarsened by `MAX_CELLS` (1.5M), so narrow gaps may be missed. The module targets 2D maps with radius ~2.4 and sizes in the hundreds of units.
* **Optimality:** paths are near-optimal, not optimal (octile heuristic is slightly inadmissible; smoothing is greedy). Intentional.
* **Not verified:** behavior inside the engine tick, with noise, or with real `instinct_move` displacements; Godot-side interpolation of path-following NPCs.
