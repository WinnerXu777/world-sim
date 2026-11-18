# 1008 Dormant structure store: design for review ([GAP], harness plane, 2026-10-09)

Author: 8d998a ("1008latenight"). Status: **design, nothing built.** Prerequisite of 2.C3 (terraform), 2.D1 (construction as a living process) and 2.D3 (settlement growth) in `./expandtools_instincts.md` Part 2 (2.E6). Reviewer: c3.

## 1. The problem, as measured in the tree

* `WindowManager.integrate` creates rows only for generated chunk features (ids `c<cx>_<cy>:...`); `unload` stores a **delta** against the generated state and releases those rows. A row the game creates at run time (`systems/construction.spawn_structure_entity` through `create_object`, ids `e_NNNNNN`, types `STRUCTURE_TYPES = 20..39`: house, well, farm, wall, storage case, village ...) is **owned by no chunk**. It lives in `m_tensor` for good, counts against `WINDOW_ROW_BUDGET = 800`, keeps its `map_geo` shape and its movement box, and is saved with the tensors.
* Consequence 1 (budget): a settlement of 150 buildings holds 19 % of the window's rows forever, and every chunk the player visits and builds in adds to it.
* Consequence 2 (the live walk, 2026-10-09): once the window follows a player 10 chunks away (`815daed`), a structure left behind sits at a window-local coordinate outside the fixed `map_geo` frame (clipped geometry, boxes without a chunk) and nothing ever frees it.
* Consequence 3 (save size): all of it goes in every save, wherever it is.

## 2. Design

**A `StructureStore` inside the `WindowManager`: `dict[ChunkCoord] -> list[StructureRecord]`**, next to `deltas`.

* **Which rows move.** At `unload(coord)`: rows with `M_SPACE == 0`, `M_TYPE in STRUCTURE_TYPES` (plus the other runtime types listed in section 6), a uid that is not one of the chunk's generated uids, and an absolute chunk (from the row's centre) equal to `coord`. Found with one vectorised mask over the tensor (about 0.1 ms; runs once per unload, never per tick).
* **Record** = `{uid, cols: all columns except CX, CY, M_GEN, M_SPACE, offset: [x, y] chunk-local, geo: {shape, scale, points}, last_tick}`. The uid is kept (`e_NNNNNN` is the identity everything else refers to: ownership, resident homes, anchors, inventories). Inventory contents are already keyed by uid in `inventory_state` and `release_slots` leaves them alone (documented there).
* **Release** through the existing `release_slots` (it already clears geometry, uid maps, caches and events). The store holds the only copy.
* **At `integrate(coord)`**, after the generated rows and the chunk delta: for each record allocate a slot (`SlotAllocator.allocate` with the stored uid), write the columns, `CX = chunk origin + offset`, `register_entity` the geometry, give back the movement box. Order: generated rows first, structures second, so a structure that stood on a removed feature stays valid.
* **Origin invariance.** Offsets are chunk-local, so a re-base needs no work on the store.
* **Budget.** `_row_estimate(chunk)` adds `len(store[coord])`; a settled chunk can therefore be `deferred_budget`, which is the correct behaviour (it is the player's own world; the only knob is the 800).
* **Dormant simulation.** Stored structures do nothing while unloaded. On integrate, apply the elapsed time in closed form (`n = (tick - last_tick) // day_ticks` days of decay: `S_DURABILITY` loss, build progress of an abandoned site frozen). This is the first user of the `Daily` + `last_run_tick` pattern in 2.E2; it needs the calendar (C4 wires the day length).
* **Save.** `snapshot()` gains `"structures": [[[cx, cy], [record...]], ...]`. Loading a format 3 save without the key gives an empty store (nothing lost: those worlds never unloaded a structure into it). A save with a non-empty store cannot be read by a build without this feature; **proposal: format 4 only when the store is non-empty**, with a refusal text pair in the format 3 pattern (wording for the user; I would not code it before approval, as for the calendar).
* **Interiors.** Rows with `M_SPACE != 0` (pocket interiors) never move into the store; there are at most 32 pockets, they are bounded.

## 3. What this does not do (and the dependent decisions)

* Residents and animals are not structures; far residents stay as they are (see `../contracts/client_contract.md` section 4, "left behind").
* A structure far from every resident is not drawn and does not serve its function (a well far away is not a water source for anyone; correct, nobody is there).
* The chunk **delta** remains for generated features (a harvested berry patch); the store is only for rows with no generator origin.

## 4. Tests that gate it

1. Round trip: build, walk away (unload), walk back (integrate): every column, uid, geometry shape, box and inventory equal bit for bit; slot may differ.
2. Budget: 200 structures in a chunk do not count while unloaded; integrate is deferred, not dropped, when the headroom is short.
3. Re-base invariance: the same world integrated at two origins gives equal absolute positions.
4. Save round trip with a non-empty store; format 3 save without the key loads.
5. Flag off (no `EDEN_WINDOW`): nothing is reachable; strict goldens unchanged.
6. Window-walk golden is untouched (no structures in it); add one walk that builds before leaving.

## 5. Cost

M (about 250 lines in `window_manager.py`, a few in the snapshot/load pair, tests). No legacy file changes. Risk: places that look up a structure by **slot** across an unload (the construction ledger, `instinct_structure_occupancy`, resident anchors). They key on uid today (checked for the ledger; to be verified for the other two at implementation time by the position-holder scan test pattern from the re-base work).

## 6. Open questions for c3 / the user

1. **Format 4 wording** (section 2, Save) when the first structure goes dormant. Needs the user's approved text.
2. **Other runtime row types** to treat the same way: dropped items and corpses (are they rows? I believe they live in `inventory_state` and events, not tensors; to verify), fire (`M_BURNING` is a column of a structure/forest row, so it travels with it), regrown forest (a generated-uid row: stays in the delta).
3. **Animals** (P5 step c2) will want the same store (a herd that was near a village when the player left). Separate record kind; same file.
4. **Decay while dormant**: the closed-form catch-up is a rule choice (a village left for a game week has rotted). Alternative: freeze (no decay while no player/resident is near). Recommend catch-up with a floor (never below 10 % durability) so a return is never a ruin by default.

## 7. As built (flag `EDEN_STRUCTURE_STORE`, default off; needs `EDEN_WINDOW`, boot refuses otherwise)

* `harness/structure_store.py`; hooks in `WindowManager`: `unload` calls `structures.stash(coord, generated_uids)` before releasing the generated rows, `integrate` calls `structures.restore(coord)` after them, `_advance` adds `structures.estimate(coord)` to the row estimate, `snapshot` calls `check_saveable()`.
* A built structure = a row with `M_TYPE` in `STRUCTURE_TYPES`, `M_SPACE == 0`, centre inside the chunk's local square, uid not one of the chunk's generated uids. The record keeps every column except position/generation/space, the position as an offset from the chunk corner (a re-base while away needs no work: tested), the geometry (shape, radius, points as offsets) and which inventory-seeding markers the uid had.
* Container inventories live in `inventory_state` keyed by uid and are not touched by a release: they stay put and the restored row (same uid) finds them again (tested).
* Restored rows are not added to `allocator.owned` (a built structure was never the window's generated row), so `owned`, the budget and the save section stay what they were.
* **Q2 answered**: dropped items and corpses are not tensor rows (no such concept in the tree outside `inventory_state`); nothing to store. Fire (`M_BURNING`) is a column and travels with the row.
* **Q4 (decay)**: `DECAY_PER_DAY` is data and is `0.0` because no structure decay rule exists in the tree yet (D1 adds one); the closed form `max(durability - rate * days_away, 0.10 * durability_when_it_left)` is in place and tested with a patched rate. With rate 0 a returning village is exactly as it was left.
* **Q1 (format 4)**: not written. `snapshot()` raises `StructureStoreSaveError` (a `ValueError`) while the store holds any structure, so a save (manual or autosave) keeps the previous generation and reports `last_error`; the provisional wording is `structure_store.SAVE_REFUSAL`, to be replaced by the approved text. Walking back so the chunk integrates empties the store and saves work again.
* **Animals (Q3)** later, same file.
* Anchors: a resident whose home is a stored structure resolves to "no home" (`_resident_home_structure_record` returns None) while it is away and to the structure again after restore; no crash (test 7). Tests: `tests/test_harness_structure_store.py` (13).
