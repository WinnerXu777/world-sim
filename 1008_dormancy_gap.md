# 1008 Interim dormancy (P6 step 1): residents and animals outside the integrated window ([GAP] and as-built, harness plane, 2026-10-09)

Author: 8d998a ("1008latenight"). Status: design, then code behind `EDEN_WINDOW_DORMANCY` (default off; requires `EDEN_WINDOW`). Reviewer: c3. Implements c3's order of 2026-10-09 "residents left outside the window keep running anchor movement through void (no walls) and needs".

## 1. What happens today (measured on the real server, `tools/live_smoke_window.py` phase_walk)

The window follows the player (`815daed`). Every resident left behind keeps its row, so it is still in `h_mask`: needs tick, escalations and the model plane keep acting, and an anchor-driven resident keeps moving through terrain that has no rows, no walls and no void boxes (void boxes sit only along the edges of integrated chunks). After a 1 200 unit walk, 5 of 5 space-0 residents were more than 5 chunks from the player; after 3 400 units, 7. In a long absence they would wander off the map, starve or die unseen.

## 2. Predicate (the one definition everybody uses)

A human row is **dormant** when: it is a live human, `H_SPACE == 0`, and the chunk containing its window-local position is **not in `WindowManager.chunks`** (not integrated). (Rows in interiors are never dormant: pockets are always loaded.) Animals: the same test on `M_TYPE in ANIMAL_TYPES`, `M_SPACE == 0` (no animal rows exist yet; the code is there so P5 step c2 inherits it).

* `engine._dormant_h`: `BoolTensor[MAX_HUMANS]`, `engine._dormant_a`: `BoolTensor[MAX_ENTITIES]`, refreshed once at the start of `step()` by `harness.dormancy.refresh(engine)` (vectorised: floor of the positions, a membership test against the integrated set; microseconds). All False with the flag off.
* `harness.dormancy.is_dormant(engine, slot)` for scalar callers.
* One-tick lag at the frontier is harmless: a resident cannot walk into a non-integrated chunk (void boxes), so a row is in a non-integrated chunk only because the window moved away from it or the row was placed there.
* **Hysteresis is the keep ring, not extra code**: a chunk is integrated from the 5x5 simulate ring and kept in the 7x7 ring, so a resident at the edge of the player's surroundings does not flicker.

## 3. Freeze: three layers, so no system has to know

1. **Masks.** `engine.step()` builds the registry context `ctx["h_mask"]` and `ctx["a_mask"]` without dormant rows, and ORs them back after the registry loop (the sync, id and death detection must keep seeing them as alive: `_prev_h_mask & ~h_mask` would otherwise report them dead). Needs, hunger and thirst, infection, mood, social, nature on humans, the instinct movement: all skip them.
2. **Sweeps.** `HumanRuntime.process_escalations` (and the talk sweep) excludes dormant slots, so no model call, no escalation and no decision is requested for them.
3. **Net.** At the start of `step()` the dormant rows are copied (a handful of rows), and at the very end they are written back: position, needs, hp, every column bit for bit. This catches whatever the model plane or another hook does to a dormant row (an anchor mover step, a god command) and gives a testable invariant: **a dormant row is bit-identical from tick to tick**. It does not undo records or the ledger; for those the model plane skips dormant residents (section 5).

## 4. Wake (the chunk is integrated again) and the catch-up rule

On the first tick a row is not dormant: `elapsed = tick - dormant_since`. Recommendation: **pause while away, closed-form on return, capped so nobody dies of the absence**:

* hunger: `min(hunger + HUNGER_TICK_RATE * rate("needs") * elapsed, 80)`; thirst: the same with a cap of 75. Both sit under the damage thresholds (90 / 100). A resident who was already at or over the threshold when frozen stays there and dies by the normal rule right after waking (the rule "really kills them").
* age: exact, `H_AGE += age_step() * elapsed` (a linear rate; old-age death is then the normal check).
* stamina set to its full value, threat and mood moved to their baselines (a rested resident), hp unchanged, infection unchanged.
* resident record: no change (memory stays, plans are dropped by the driver on resume, see 5).
* The rule is data in `harness/dormancy.py` (`CATCH_UP`), applied in one function, so tuning is one place. With `EDEN_CALENDAR` off the rates are the legacy ones, as everywhere.

## 5. For the model plane (latenight2): the exact predicate

`harness.dormancy.is_dormant(engine, slot)` (or `engine._dormant_h[slot]`). While true the driver must not: step the anchor mover, request a decision, start or advance a ladder errand, apply an action. On the tick it turns false the driver treats the resident as newly arrived: re-plan from its actual position (the stale plan is dropped, `rebase_model_plane` already shows which holders keep positions). `systems/actions/*` stays latenight2's; this document only gives the predicate and the wake event (`engine._dormancy_log`: `(tick, "sleep" | "wake", uid)`).

## 6. Cost and tests

Cost: one vectorised refresh per tick, a copy of the dormant rows, two mask ANDs. Measured with 5 to 7 dormant residents: reported with the code (expect below 0.1 ms; the saving is that dormant residents no longer run the movement and escalation work).

Tests: (1) a dormant row is bit-identical over 200 ticks with the registry running; (2) it is not reported dead or despawned in the frame/events; (3) wake applies the cap numbers exactly and never kills; (4) flag off: strict goldens unchanged, `_dormant_h` all False; (5) the window follow test, then walk away and back: the same residents, uids and slots, positions equal; (6) a save while residents are dormant restores them dormant (the predicate is derived from positions and the integrated set, nothing new is saved except `dormant_since`, which goes into the window section as `dormant_since: {uid: tick}`, additive to format 3); (7) live smoke: the residents left behind do not move (max 0.0 units) while the player is away.

## 7. Not in this step

Coarse background simulation of dormant residents (a village that lives on while the player is away): that is the full P6. Dormant structures: `1008_structure_store_gap.md` (next). A resident whose home or work anchor is a dormant structure: the anchor is a uid and a position; while dormant nothing reads it (test 7 of the store design covers the resume).

## 8. As built (ffeeced, b13eb77) and what the live runs changed

* Flag `EDEN_WINDOW_DORMANCY=1`; `engine_hooks.install` refuses to boot without `EDEN_WINDOW=1` (`SpaceConfigError` naming the flag).
* **Grace period** `GRACE_TICKS = 40`: a row must be outside the integrated chunks for 40 ticks before it goes dormant (a fresh world integrates one chunk per tick; without it the first ticks froze the player's own human).
* **A player's body is never dormant**: `WindowManager.controlled_slots()` = humans with a session plus the avatars a controller incarnated (`engine._incarnated_human_by_controller`). The window follows the same set, so a session that lapses after a few idle seconds does not send the window back to the village under a parked avatar (found live: origin snapped back, the avatar was left behind).
* **`thaw` follows a re-base**: the window hook re-bases in the middle of a step; writing the saved old-frame row back made the player look far from the new origin, the window re-based again every tick (runaway, found live, epoch +1 per tick). `freeze` records the origin and `thaw` shifts the saved rows by the difference.
* Catch-up applied as designed (hunger cap 80, thirst cap 75, age exact, stamina full, threat 0; mood and hp untouched).
* Model plane: `actions/dormancy_gate.py` (3543ada) skips dormant residents in the agent driver and the other sweeps; the legacy anchor driver skips them in `systems/roster/driver.anchor_driven_slots` (b13eb77).
* Measured live (tools/live_smoke_window.py, 47 checks): 7 residents outside the frame moved 0.000 units over 6 s while the player stood away; tick pace unchanged (112 to 119 ticks per 6 s at 20 Hz); `/status` work_ms p50 15.5 ms with the flag versus 16.9 ms without, p99 34.2 versus 33.9 (same walk, machine shared with other runs: no measurable cost).
* `dormant_since` is saved in the window section (key present only while something is dormant, so every other format 3 save is unchanged; the validator accepts it as optional). Not done: animals are masked and frozen by the same code but no animal rows exist in the window yet.
