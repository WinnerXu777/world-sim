# P3 scheduled NPCs and P4 smith loop with a rules-only DecisionProvider — design

Date: 2026-10-06. Author: session 1006implementation2. **Design only: no existing file was edited, nothing was run for this document, no git operations.**
Reads: `1006newdesign.md` (Tier 1 / DecisionProvider), `implementation_0905.md` section F, `1006_map_backend_integration.md`, `1006_map_wire_contract.md`, `1006_pathing_notes.md`, `1006_scale_constants_audit.md`, `1006_communication_scratchpad.md` (C-018, P3/P4 constraint), and the systems/runtime code cited below.

Marks: **[V]** = verified by reading the code named. **[U]** = unverified inference, guess, or depends on work not yet landed. Line numbers are from reads made while session 1006implementation was editing `map_test.py`/`spatial.py`, so they drift: names are authoritative.

## 0. Findings that shape the design

1. **None of the smith loop exists.** No sword, iron, ingot, smith occupation, forge entity type, work order, reservation, or dialogue-choice API. Crafting has recipes only; the forge station is defined but unused (`systems/crafting/stations.py`, `CRAFTING_STATION_DEFS["forge"]`: "Reserved for later metalworking recipes") [V]. `required_tool_tags` and `station_kind` on recipes are never enforced anywhere, only shown in prompt views [V: grep]. The `interaction` package is an empty scaffold (`systems/interaction/*.py`, `EXTRACTION_STATUS = "scaffold"`) [V].
2. **Tasks are not durable work orders.** The resident task queue is a derived artifact: `_sync_managed_resident_tasks` (`map_test.py` ~1275) rebuilds `desired_specs` every sync and calls `replace_resident_tasks`; task ids come from a process-global counter (`systems/tasks/ops.py:_next_task_id`, `itertools.count`) and crafting job ids from another (`systems/crafting/ops.py:_JOB_COUNTER`) [V]. Both restart at 1 after a process restart, so ids are not safe as durable keys. A work order must be its own persisted record, with tasks derived from it.
3. **There is no reservation concept in inventory.** `systems/inventory/ops.py` has `add_item`, `remove_item`, `transfer_item` (can move partially, rolls back only add-failures), `drop_item`; items carry no `reserved` flag; "reserve" appears nowhere in the package [V: grep]. Reservation must be built, and the cleanest durable form is **escrow by physical transfer** into a per-order inventory record (section 1.3).
4. **Snapshot schema is strict, so where new state lives matters.** `persistence/world_snapshot.py::validate` requires `set(payload["engine"]) == set(ENGINE_FIELDS)` and `set(attributes) == allowed` for each of `RUNTIMES` [V]. Any new Engine attribute listed in `ENGINE_FIELDS`, or new attribute on `world_agent/human_agent/talk_agent/orchestrator/tiny_model_runtime`, makes every existing save fail. **Schema-free homes that already persist:** `engine.inventory_state` (an `ENGINE_FIELDS` member; a plain dict of dicts) and per-resident records (`residents` in the payload) [V]. The design uses `inventory_state["work_orders"]` plus `inventory_state["inventories"]["work_order:<id>"]`.
5. **NPC movement from tasks bypasses walls.** In `Engine.step`, the end-of-tick slide loop (`spatial_slide(start, desired, spatial)`, `map_test.py` ~4778-4786) runs **before** `_sync_slot_ids_and_events`, which calls `_sync_occupation_provisioning` → `_execute_resident_task_step` → `bridge.move_toward` → `_move_human_toward_point` (`map_test.py` ~3236), and that function writes `h_tensor[slot, X/Y]` directly with `+ unit*magnitude` and a global clamp [V: read order]. `movement_starts` is captured at the start of the next step, so task displacement is never slid. Anchor movement must therefore slide its own step (as the pathing tests do), or the loop must be reordered. This also means a task move can embed an NPC inside an inflated wall, after which `slide` freezes it (verified in the scale audit).
6. **Survival pacing will fight a scheduled day.** `HUNGER_TICK_RATE = 0.05`, `THIRST_TICK_RATE = 0.07` per tick (`genesis_config.py:469-470`), applied each tick (`systems/survival/hunger.py:33`, `thirst.py:46`) = +1.0 hunger per second at 20 Hz; `FOOD_SEEK_THRESHOLD = 50` (survival tasks preempt everything below combat in `_sync_managed_resident_tasks`) and starvation damage of 2 HP per tick at hunger ≥ 90 (`hunger.py:35-36`) [V]. A resident goes to seek food after about 50 s and takes lethal damage after about 90 s without eating. A 20-30 minute run needs a food/water loop or a per-map needs scale (risk R1). [U: not run.]
7. **Memory expires in seconds.** `EVENT_POLICY` in `runtime/resident_store.py` lists a handful of kinds; unknown kinds get `ttl_years: (1, 2)`, and `TICKS_PER_YEAR = 600` (30 s), so an unlisted event lives 30-60 s; `RECENT_EVENT_LIMIT = 14` keeps the 14 most salient [V]. `RELATION_POLICY` makes only `parent/child/family/mate` permanent; `friend` lasts 2-6 "years" (1-3 min) [V]. "Remembered after reload" needs explicit policy entries (section 3.6).
8. **Two decision seams already exist, neither is the DecisionProvider.** `HumanAgentRuntime` builds a case (`_build_case`), decides by rules (`_decide`, `_fallback_tiny_decision_packet`) and can call a tiny-model handler (`_decide_batch`, `runtime/tiny_runtime.py:TinyModelRuntime.run_mode_batch`, handler lookup `_tiny_model_handler`); `TalkAgentRuntime._generate_direct_result` answers free text by keyword rules ("money/coin/pay/trade" → "What are you offering?") [V]. The new DecisionProvider is a typed option → probability contract (`1006newdesign.md` §5). Stage 1 should add it for the commission decision only and not refactor `HumanAgentRuntime` (risk R8).
9. **The smith lives in the interior map, and multi-map does not exist yet.** The registry applies one authored map per world; G5-G7 (placement, containment, instantiation, portals) are queued with session 1006implementation (scratchpad C-017/C-018). NPC portal use is deferred to P6. So P3/P4 start with the smith, forge, counter and player all in one map (section 4, phase B).

## 1. What exists today for the smith request loop

### 1.1 Table: exists / partial / missing

| Need | Today | Missing |
| --- | --- | --- |
| Recipe `sword` | `CRAFTING_RECIPE_DEFS` in `systems/crafting/catalog.py`: 14 recipes (stone_blade, rope, plank_bundle, club, axe, spear, hoe, hammer, basket, pack, fishing_rod, simple_net, bandage, torch) [V]. Format: `ingredient_requirements`, `required_tool_tags`, `station_kind`, `occupation_tags`, `time_cost`, `difficulty` | `sword` recipe; `station_kind="forge"`; `occupation_tags=("smith",)` |
| Materials | `ITEM_KIND_DEFS` in `systems/inventory/schema.py` (wood, fiber, stone, herb, fish, crops, coin, club, knife, spear, axe, hammer, hoe, basket, pack, fishing_rod, simple_net, stone_blade, rope, plank_bundle, rations, bandage, torch) [V] | `iron_ingot` (and maybe `iron_ore`), `sword` item defs (weapon tag, `main_hand` slot) |
| Station | `crafting_station_def("forge")`; `M_FORGE` type is proposed by session 1006implementation (`1006_map_backend_integration.md` 1.4) but not present: types 20-25 only [V] | forge entity instantiation, "is the station usable" query (alive HP, id present) |
| Occupation | 9 blueprints: farmer, fisherman, hunter, guard, builder, woodcutter, gatherer, trader, healer (`systems/occupation/catalog.py`) [V] | `smith` blueprint (block_routines, place_tags, `required_tools=("hammer",)`) |
| Inventory | owner inventories (`ensure_owner_inventory`), containers (`ensure_container_inventory`, `storage_case`, `stockpile`), currency helpers (`inventory_balance`, `spend_currency`, `grant_currency`), `transfer_item`; per-record deterministic item ids (`next_item_id`, persisted `next_item_uid`) [V] | reservation/escrow, all-or-nothing multi-item transfer |
| Task lifecycle | `queued → active → paused/completed/...` (`systems/tasks/ops.py`: `start_next_resident_task`, `complete_current_task`, `interrupt_current_task`); families in `systems/tasks/families/` dispatched by `systems/tasks/dispatcher.py:TASK_FAMILY_MODULES`; `deliver_item` task (`social.py:_handle_deliver_item`) → bridge `try_deliver_item` → `map_test.py:_attempt_task_delivery` (a plain `transfer_item` by kind, partial allowed) [V] | any commission/work-order task; delivery by order id, not by item kind |
| Crafting execution | baseline provisioning only: `map_test.py:_craft_baseline_tool` / `_craft_cached_component` consume ingredients and `add_item` the output **instantly**, no station, no duration, no reservation [V] | station-gated, time-based crafting |
| Work orders | none | the whole lifecycle |
| Persistence of residents | `ResidentAgentStore` JSON sidecars + snapshot payload `residents`; atomic writes (`_atomic_write_json`); dirty/revision tracking; `record_event`, `update_relationship` [V] | commission event kinds and relation tag policies |
| Memory graph | `systems/memory/ops.py:update_relationship_and_sync`, `graph_sync.py`; retrieval bundle `build_human_memory_bundle` [V] | none for Stage 1 beyond calling the existing helpers |
| Commands | `simulation/commands.py:CommandInbox` (UUID `command_id`, fingerprint idempotency, bounded queue, receipts, `world_epoch`/`possession_epoch` authorization, `applied`/`rejected` result via `GET /commands/{id}`); executor `simulation/inventory_commands.py:execute` handles only `transfer`/`equip` [V]. Receipts are **in memory only**: `Engine.reset_world` and restore create a fresh `CommandInbox` [V] | commission command executor; generalised dispatcher |
| Talk | free-text `talk_command` events → `TalkAgentRuntime` direct/ambient/NPC queues → keyword rules or tiny-model handler; results feed `recent_lines` and `/talk/state`; relationship deltas via `_apply_relationship_delta` [V] | scripted choice → typed command path; outcome-driven line selection |
| Interaction range | inventory reach 30 u, no wall test (`inventory_commands.py:44`); interact/work range 70 u (`map_test.py` `_attempt_manual_interact`/`_attempt_manual_work`); attack is the only wall-aware check (`resolver.py`) [V]; `Entity.interact_radius` exists in the map schema, nothing in the engine reads it [V: grep] | wall-aware interaction helper (scale audit §7) |
| Decision interface | none; `HumanAgentRuntime._decide` and tiny-model hooks only (finding 8) | `systems/decision/` |

### 1.2 Lifecycle: which function implements each step (names new unless marked existing)

State machine (`offered → accepted → awaiting_materials → reserved → working → ready → delivered`, branches `refused`, `canceled`, `failed`). All transitions live in one new module, `systems/commission/lifecycle.py`; every transition is a function that checks the **current state** and applies **all** side effects in the same synchronous call (no yield, single simulation thread), so check-and-set is atomic [V: `Engine.step` is a plain method; async work only wraps whole ticks].

| Step | Function | Existing pieces it calls | Notes |
| --- | --- | --- | --- |
| request → `offered` | `create_order(engine, customer_id, smith_id, recipe_id, command_id)` | `crafting_recipe_def`, `ensure_owner_inventory` | Idempotent on `(customer_id, smith_id, recipe_id)` while an order is open: returns the existing `order_id` with `duplicate_open_order`. Order id from a counter **stored in the order store** (`next_order_uid`), never a process-global. |
| feasibility facts | `commission_facts(engine, order)` | `crafting_missing_ingredients` (`crafting/ops.py`), inventory queries (`total_quantity`, `inventory_balance`), forge liveness (`station_available`), `interaction_ok` | Pure read; feeds option legality. |
| decision | `decide_commission(engine, order)` | `DecisionService.decide` (section 3.3) | Produces `accepted` or `refused(reason)`. |
| `accepted → reserved` | `reserve_inputs(engine, order)` | `transfer_item`, `ensure_container_inventory` | All-or-nothing: pre-check totals, transfer materials from the smith's stock container to `work_order:<id>`, move the price from the customer to escrow, roll back on any shortfall, then set `state="reserved"` and `reserved_tick` in the same call. |
| `accepted → awaiting_materials` | same function, shortfall branch | | Only when the policy allows waiting (customer-supplied or en-route material); otherwise the decision would have been a refusal. Re-checked every `ORDER_REVIEW_TICKS` by `review_orders(engine)`; `deadline_tick` → `failed(no_materials)`. |
| `reserved → working` | `start_work(engine, order)` | station check, `smith at work anchor` | Triggered by the smith's commission task arriving at the work anchor (3.2/4). |
| work progress | `advance_work(engine, order)` | `station_available`, smith alive, smith within anchor tolerance | `progress_ticks += 1` per call, **simulation ticks only**, persisted in the order. If the forge or smith is unavailable: set `blocked_reason` once (guarded flag), emit the committed reason; after `FORGE_WAIT_TICKS` → `failed(forge_unavailable)`. |
| `working → ready` | `complete_work(engine, order)` | `remove_item` (consume ingredients from escrow), `add_item` (output into escrow) | One call; precondition `state == "working"` and `progress_ticks >= work_ticks`; if `add_item` cannot place the output, roll back and stay `working` (blocked: `capacity`). Sets `consumed=True` in the same call. |
| `ready → delivered` | `deliver_order(engine, order, collector_id)` | `transfer_item` (output escrow → customer; price escrow → smith) | Precondition `state == "ready"`, customer alive, `interaction_ok`; capacity check before moving; sets `delivered_tick`, `settled=True` in the same call. A second call finds `delivered` and returns the stored receipt with no side effect. |
| cancel | `cancel_order(engine, order, by, reason)` | `release_escrow` | Allowed in `offered/accepted/awaiting_materials/reserved`; policy for `working` (decision D6). `release_escrow` returns every item and coin to its source once, guarded by `settled`. |
| fail | `fail_order(engine, order, reason)` | `release_escrow` | Forge destroyed too long, smith dead, deadline missed, customer gone. |
| consequences | `commit_consequences(engine, order, new_state)` | `resident_store.record_event`, `update_relationship_and_sync`, `engine._queue_event` (`map_test.py:_queue_event`), `engine._force_frame_refresh` | Called inside each transition; guarded by `order["committed"][<state>]` so a repeat never re-commits (3.6). |

### 1.3 Where exactly-once is enforced (three layers)

1. **State machine CAS.** Every transition function begins with `if order["state"] != expected: return {"ok": False, "reason": "invalid_transition", "state": order["state"]}` and finishes by setting the new state and incrementing `order["revision"]` before returning. Duplicate accept/deliver/cancel calls hit this and have no effect.
2. **Escrow by physical transfer.** Reserved materials and price live in `inventory_state["inventories"]["work_order:<id>"]` (owner_kind `"work_order"`), not in the smith's or customer's inventories. Other consumers (`_available_ingredient_quantity`, baseline provisioning, `/inventory/transfer`) cannot spend them because they are not accessible. Consumption removes from escrow; delivery moves the output from escrow. After `settled`, the escrow is empty, so even a buggy second call has nothing to move.
3. **Persistence in the same object graph as the world snapshot.** `inventory_state` is in `ENGINE_FIELDS`, so order records and escrow are captured together at a tick boundary (`world_snapshot.capture` runs between steps) and restored together [V]. Receipts in `CommandInbox` are lost on restore, so a retried `command_id` after Continue gets `stale_world_epoch`; the client must re-read order state (`GET /commission/state`) rather than blindly resend, and the state machine guarantees a replayed request with a new id cannot duplicate an open order.

## 2. P3: three scheduled NPCs (smith, builder, gatherer)

### 2.1 Anchors → schedule targets

Authored data: anchors have `kind` in `door|work|talk|sleep|spawn` and optional `for_role` (`world_map/schema.py:KNOWN_ANCHOR_KINDS`, `KNOWN_ANCHOR_ROLES = ("smith", "builder", "gatherer")`; `for_role` is a label, never a resident id; several residents of one role need explicit backend assignment: C-018) [V].

**Binding lives in backend config, not map data.** New data file per map, e.g. `world_data/rosters/<map_id>.json` (backend-owned; not under `world_data/maps2d/`, which Codex owns):

```
{"map_id": "starter_village", "residents": [
  {"key": "smith", "name": "Brann", "sex": 0, "age": 38, "role": "smith",
   "archetype": "disciplined", "traits": {"greed": 0.5},
   "anchors": {"spawn": "…:smith_spawn", "work": "…:smith_work", "talk": "…:smith_counter", "sleep": "…:smith_bed"},
   "stock": {"iron_ingot": 4, "wood_bundle": 4}, "personal": {"hammer": 1, "coin": 20}},
  {"key": "builder", …}, {"key": "gatherer", …}]}
```
Loader: new package `systems/roster/` (`load_roster(path)`, `apply_roster(engine, roster, anchors)`), validated against the loaded `WorldMap` (anchor ids exist, kinds match, `for_role` equals `role` when present, no anchor shared by two residents unless allowed).
Stable identity: the generated resident id (`h_000001...`, `Engine._make_human_id`) is not stable across worlds, so the resident record gets `resident["roster_key"] = "smith"` (persisted in the resident JSON and snapshot; schema-free). A lookup `roster_resident_id(engine, key)` scans residents (3-12 of them) and caches in a non-saved attribute rebuilt after restore. No change to `ENGINE_FIELDS` or `RUNTIMES`.

Where residents are created and bound: `map_test.py:create_genesis` spawns four hard-coded villagers around the global map center for `playable_village`/`render_test_village` (`Mara/Iven/Toma/Elsa`, `cx_px ± 6-18`) [V]. For an authored map the roster replaces that list: `apply_roster` calls `engine.spawn(...)` at each resident's `spawn` anchor (standable, via `spatial.standable_spawn_point`, which session 1006implementation added [V]), then sets occupation and `roster_key`. Occupation override: `ensure_resident_occupation` assigns only when the record has none and `ensure_resident` runs it immediately with no `preferred_kind` hook [V], so `apply_roster` overwrites `resident["occupation"]` with `assign_occupation(human_id, preferred_kind=role)` (supported: `inheritance.sample_occupation_kind(preferred_kind=…)` requires `role in OCCUPATION_NAMES`, hence the `smith` blueprint) and clears `schedule_profile/schedule_state` so `ensure_resident_schedule` rebuilds them. **Conflict:** `create_genesis` belongs to session 1006implementation right now (section 6).

Routine → anchor kind (`systems/schedule/catalog.py` routines: sleep, stay_home, return_home, wander_local, gather, work_site, patrol, guard, socialize, rest, visit_water):

| Routine | Anchor kind (resident's explicit anchor first, else nearest of kind matching `for_role`) |
| --- | --- |
| sleep, stay_home, return_home, rest | `sleep` (fallback `door`) |
| work_site, guard, patrol, gather | `work` |
| socialize | `talk` |
| visit_water | nearest well/lake entity (unchanged type lookup) |
| wander_local | no anchor: current behavior, or a random standable point within 12 u of the talk anchor (decision D7) |

Two code paths consume routines today, and both must be changed [V]:
* **Bias path:** `systems/schedule/navigation.py:build_schedule_navigation_bias` (`nearest_geo_entity(..., radius=220.0)` + `entity_unit_vector`, lines ~170-190) adds a unit×`ROUTINE_WEIGHT` vector into `instinct_move`'s noise.
* **Task path:** `systems/tasks/families/occupation.py:routine_task_specs` emits `move_to_place` with a `place_tag`; `_handle_move_to_place` resolves it with `bridge.resolve_place` (`map_test.py:_resolve_task_place_target`, a type-set lookup) and walks with `bridge.move_toward` → `_move_human_toward_point`, with arrival radius `bridge.gather_radius` = 24 u (3 tiles) [V].

### 2.2 Path module and an anchor mover

`systems/movement/pathing.py` (exists, unwired) plus a new `systems/movement/anchor_mover.py`:

* `AnchorMover.step(engine, slot, goal_xy, step_len) -> arrived: bool`. Keeps a per-slot plan `{goal, waypoints, index, contract_revision}` in a **non-saved** dict on the engine (rebuilt after restore; a lost plan just re-plans). Re-plan when the contract `revision` changes, the goal changes, the actor has not closed distance to the next waypoint for N ticks, or a negative result expires (cache `no_path` for several seconds).
* Each call moves **exactly** `min(step_len, distance)` toward the next waypoint and then calls `spatial.slide(start, desired, contract)` itself (finding 5), so the actor never ends embedded and never crosses a wall. Arrival: within `ANCHOR_TOLERANCE = 2.0` u (12 px) of the goal anchor.
* `plan_path` failure reasons map to behavior: `start_not_standable` → re-snap with `spatial.snap_to_standable` [V exists]; `goal_not_standable` → configuration error logged once; `no_path`/`search_limit` → the resident idles at its current anchor and the task records `blocked_reason`.

Plug-in points: (a) `_resolve_task_place_target` (`map_test.py` ~1873) returns `{"x","y","anchor_id", "arrival": 2.0}` for the roster resident's anchor-backed place tags (`home/hearth` → sleep, `worksite/market/settlement` → work/talk) before the type-set fallback; (b) `_handle_move_to_place` (`occupation.py:802`) uses `target["arrival"]` instead of `gather_radius` when present; (c) `bridge.move_toward_point` (lambda in `_execute_resident_task_step`, `map_test.py` ~3679) calls `AnchorMover.step` for roster residents instead of `_move_human_toward_point`; (d) `build_schedule_navigation_bias` returns **zero** for roster residents, because their movement comes from the task path, so the bias path cannot also push them.

### 2.3 NPC speed cap and noise removal: exact call sites

Goal: a roster resident moves at ≤ 1.0 u/tick (walk) toward its anchor, with no jitter. Sources of displacement, all [V]:

| Source | Call site | Change for roster residents on a map that sets `npc_mode = "anchor"` |
| --- | --- | --- |
| Random walk noise ±1.0 u per axis | `instincts_and_tools.py:instinct_move`, `noise = (torch.rand((n, 2), device=device) - 0.5) * (MOVE_STEP * 2)` (~1439) | zero the rows of roster residents (mask by slot; the loop already has `h_indices`) |
| Mate attraction | `instinct_move` (~1471, 1484) `ATTRACTION_FORCE` 5.0 | skip those rows |
| Navigation biases summed in `apply_navigation_bias` (`systems/movement/sim.py`) | schedule: `navigation.py` (~170-190); survival: `systems/survival/navigation.py:131-155` (`SURVIVAL_NAV_WEIGHT` 7.0 ×, hazard 10 ×, predator); social: `systems/social/grouping.py:88,95` | zero for roster residents (survival keeps working through tasks, below) |
| Flee repulsion `MOVE_STEP*3.0` | `instincts_and_tools.py:instinct_flee` (~931) | cap through the choke point below |
| Task movement (gather, provisioning, anchor) | `map_test.py:_move_human_toward_point` (~3236), `BASELINE_GATHER_MOVE_STEP = 2.4` (`map_test.py:350`, used at ~1747, 1769, 1804, 3592 and as `move_step` in `_execute_resident_task_step`, ~3691) | roster path uses `AnchorMover`; `move_step` becomes a per-map value (1.0) |
| Decision-driven magnitudes | `runtime/human_runtime.py:649-728` (`MOVE_STEP × 1.8-3.0`), `runtime/talk_runtime.py:636` (`_apply_listener_reaction`, flee 2.4×) | cap through the choke point |
| Final clamp | `instinct_move` (~1494-1495) `.clamp(0, MAP_WIDTH/HEIGHT)` | no change; `slide` bounds are per-map already |

**Single choke point (recommended first):** a per-tick displacement cap applied to every non-controlled human just after all movement is done. Today the slide loop in `Engine.step` (~4778) runs before the task phase, so put the cap and a second `slide` for the task phase in one new function `apply_npc_motion_limits(engine, movement_starts)` called after `_sync_slot_ids_and_events` (or move the reconcile loop to after it). That guarantees "no teleport, no wall crossing" for every source without enumerating them, and the noise removal then only addresses jitter. The cap value comes from the map contract override (`max_step_per_tick`, default absent = legacy unchanged) [U: needs a field in `map_contract`, owned by session 1006implementation].

Survival interaction (risk R1): with noise and biases off, hunger/thirst tasks still preempt work (`_sync_managed_resident_tasks`), driving the resident to a well/food source through the same mover. The map needs a well (maps to `M_WELL`, 1.4 in the integration note) and food (rations in the smith's house storage), or the needs rates need a per-map scale: `instinct_hunger`/`instinct_thirst` (`instincts_and_tools.py:1077-1082`) call `apply_hunger_tick(ctx["h_mask"], h_tensor)` without the engine; a per-map multiplier needs `ctx["engine"]`, which is available in `ctx` [V: `ctx = {"h_mask","a_mask","engine"}` in `Engine.step`].

### 2.4 The three NPCs

* **Smith**: new `smith` occupation (`systems/occupation/catalog.py`: day → `work_site`, dusk → `socialize`, night → `sleep`; `place_tags` ("smithy", "worksite"); `required_tools ("hammer",)`; `optional_tools ()`); starts in the smith interior with work (at the forge), talk (counter) and sleep anchors. Takes commission orders (P4).
* **Builder**: existing `builder` occupation, hammer. For P3 the "work" is presence at a work anchor (a build-site anchor), not real construction projects: `construction_task_specs` and `should_activate_builder_work` would otherwise engage the construction system, which needs sites on the map [U]. Provide a roster flag `work_mode = "anchor_only"` that skips the occupation-work branches in `_sync_managed_resident_tasks` and leaves `routine_task_specs` only.
* **Gatherer**: existing `gatherer` (basket). Same `anchor_only` for P3; real gathering (`gather_work` consuming forest/grass entities from the tensor) needs resource entities instantiated from the map and belongs to P5/P6 (the god "spawn resource" power).
* All three: deterministic personalities via `archetype`/`traits` in the roster (`systems/personality/catalog.py:ARCHETYPE_PRESETS`, 16 traits) [V], so that "several different responses to the same request" (F2) is reproducible.

Day length is `DEFAULT_DAY_LENGTH_TICKS = 2400` (`systems/schedule/resolver.py`): 120 s per day, four 30 s blocks [V]. A 20-30 minute run is 10-15 days.

## 3. P4: the smith loop

### 3.1 Player interaction and range

Entities and distances (example fixture `tests/fixtures/maps/example_smith.json`): forge entity at (24, 16) with a blocking wall footprint (16,8)-(32,16) owned by it; work anchor (24, 21); talk anchor (24, 29); spawn (8, 32) [V].

* **Interaction predicate**: new `systems/commission/access.py:interaction_ok(engine, actor_slot, target, radius)`: `hypot ≤ radius` **and** `not segment_blocked(actor_xy, target_xy, boxes)` using the same boxes as movement (`spatial.map_wall_boxes(engine)` / contract boxes; `segment_blocked` already exists and treats contact as blocked [V]). The target's **own** footprint must be ignored (`Wall.owner_entity` links a wall to its entity [V schema]); the registry in `systems/movement/map_contract.py` currently stores only wall `id`, `min`, `max`, `height` [V], so ownership has to be added there or looked up from the loaded `WorldMap` (needs session 1006implementation, dependency D1).
* Radii: talk to the smith 16 u (2 tiles; the scale audit proposal), collect at the counter 16 u from the smith, forge not interacted with directly by the player in Stage 1. Per-entity `interact_radius` from the map is read through a helper `entity_interact_radius(engine, entity_id, default)` once entities are instantiated [U].
* Client path today: `/control/event` carries `select`/`talk` events with `target_kind: "human"` and `target_id`; `_attempt_manual_interact` merely sets `current_intent = "interact_human"` after a type check, with no distance or wall check [V]. The commission commands add the real checks.

### 3.2 Scripted dialogue choices → typed commands

Existing plumbing is free text only (3.1/finding 8). Add a typed path beside it:

* **Read model**: `GET /commission/state?controller_id=` returns `{"npc": {id, name, role}, "choices": [{id, label, enabled, reason}], "orders": [{order_id, state, recipe, price, blocked_reason, progress}], "line": {...last line}}`. Choices are computed from facts (e.g. "Commission a sword (30 coin)" disabled with reason `out_of_range` or `no_funds` when applicable).
* **Commands** (same envelope as `/inventory/transfer`: `protocol_version`, `world_epoch`, `possession_epoch`, `controller_id`, `command_id` UUID; response 202 `received`; outcome via `GET /commands/{id}`): `POST /commission/request {smith_id, recipe_id}`, `/commission/cancel {order_id}`, `/commission/collect {order_id}`. No separate "accept" command: **the smith decides**; the player's price is shown before the request, so the request itself is the agreement to the quoted price (no extra state beyond 0905's lifecycle).
* **Executor**: new `simulation/commission_commands.py:execute(engine, action, payload)`; `CommandInbox.drain(self, execute_inventory_command)` (`map_test.py` ~4731) passes one function, so a small dispatcher (`simulation/dispatch.py`, registry `{action: executor}`) is needed. Session 1006implementation plans a portal executor at the same drain call (`1006_map_wire_contract.md` §4; integration note S8), so the dispatcher should be written once as a registry (dependency D2, section 6).
* **Wording**: lines come from the **decided outcome**, never the other way round (`1006newdesign.md` §10): `systems/commission/lines.py` maps `(role, outcome_code)` to 2-4 variants, chosen by `sha256(resident_id|order_id) % n`; delivered through the existing talk feed by building a result dict shaped like `_generate_direct_result` output and calling `TalkAgentRuntime._apply_result`/`_record_runtime_line` so `/talk/state` and `frame.talk` show it [V: shapes read]. Free-text `talk_command` stays for chatter; while a commission dialogue is open the keyword rules must not answer the same request (D9).

### 3.3 DecisionProvider interface and the RulesDecisionProvider

New package `systems/decision/` (no existing file touched):

* `contract.py`: `DecisionOption(id, description, tags)`, `DecisionRequest(job_id, resident_id, world_epoch, state_revision, tick, trigger, question_kind, state, options, priority, deadline_ms)`, `DecisionResult(job_id, resident_id, world_epoch, state_revision, probabilities, top_option, top_p, margin, provider_mode, latency_ms)`, exactly as `1006newdesign.md` §5. `provider_mode ∈ {rules, mock, recorded, fallback, live}`.
* `providers.py`: `RulesDecisionProvider` (deterministic), `RecordedDecisionProvider` (replays a log by `(resident_id, trigger id)`), and a `ClefDecisionProvider` stub that raises `NotImplementedError` (Stage 2).
* `service.py`: `DecisionService.decide(request) -> DecisionResult`: calls the active provider, validates probabilities (finite, cover exactly the offered option ids, sum ≈ 1, else treat as failure and use `fallback` = the rules provider), logs, and exposes `status()` with provider mode. Held on the engine as a **non-saved** attribute `engine.decision_service` (outside `ENGINE_FIELDS`/`RUNTIMES`), surfaced in `/status` (`map_test.py:status`).
* `log.py`: append-only JSONL under `<data_root>/decisions/` (outside saves, per `1006newdesign.md` §14; `*.jsonl` is already gitignored), with state snapshot, options, probabilities, chosen option, how chosen, validation outcome; later outcome (order delivered/failed) appended by id.
* **Staleness**: a result is applied only if `world_epoch` equals `engine.world_epoch` and `state_revision` equals `order["revision"]` at apply time; otherwise dropped and logged. With the synchronous rules provider the check is trivially true, but the code path is the one a live provider needs.

**Option legality is computed before the provider runs, from facts** (`1006newdesign.md` §5: options are legal by construction), so a refusal can never state a false reason:

| Option id | Legal when |
| --- | --- |
| `accept_commission` | recipe in the smith's occupation set; forge available; materials fully reservable; customer can pay; open orders < capacity; smith alive |
| `refuse_no_materials` | the material shortfall is non-empty |
| `refuse_no_forge` | forge missing/destroyed/unavailable |
| `refuse_cannot_afford` | customer coin < price |
| `refuse_busy` | open orders ≥ capacity |
| `refuse_distrust` | relationship closeness ≤ −0.2, or a `rival` tag, or (traits) high `vengefulness` with a recent hostile event |
| `defer_check_back` | optional, Stage 1 off |

`RulesDecisionProvider` scores each legal option, then softmax (temperature 0.35) for probabilities; the selected option is the argmax (Stage 1 is deterministic; seeded sampling by `hash(order_id)` is a later switch). Inputs: resident record fields only (`personality.traits`, `pressures` such as greed/loyalty/security from `systems/personality/appraisal.py`, `relationships[customer].closeness`, `occupation.skill`, current backlog, price margin). Example: `accept` ≈ 1.0 + 1.2·closeness + 0.6·(greed − 0.5) + 0.4·(discipline − 0.5) − 0.3·security_pressure; `refuse_distrust` ≈ 0.4 + 1.0·vengeance_pressure − 0.8·closeness. Weights are placeholders to tune with logged runs. Output when exactly one option is legal: that option with p = 1.0.

**Where accept/refuse is decided:** `systems/commission/decide.py:decide_commission(engine, order)`, called from the executor of `commission_request` in the same tick the command is drained (`CommandInbox.drain`, beginning of `Engine.step`), so the player sees the decision on the next frame. It builds the request, calls `engine.decision_service.decide`, validates freshness, maps the chosen option to a lifecycle transition (`accepted` + `reserve_inputs`, or `refused(reason)`), and picks the line.

The existing `HumanAgentRuntime._decide`/tiny-model path is untouched in Stage 1. A later step can re-express it through `DecisionService` (risk R8).

### 3.4 Where events and memory are committed

`commit_consequences(engine, order, state)` (inside each transition, guarded by `order["committed"][state]`):

* Resident memory: `resident_store.record_event(human_id, tick, kind, note=..., other_human_id=..., extra={"order_id", "recipe", "price"})` for the smith and the customer, with kinds `commission_requested`, `commission_accepted`, `commission_refused`, `commission_ready`, `commission_delivered`, `commission_failed`, `commission_canceled`. **Required edit:** list them in `EVENT_POLICY` (`runtime/resident_store.py`), `permanent: True` for accepted/refused/delivered/failed so they outlive the 30-60 s default TTL and the 14-event cap prefers permanent entries (`_retained_entries`) [V].
* Relationships: `update_relationship_and_sync(memory_rag, resident_store, human_id=smith, other_id=customer, relation_kind=..., closeness_delta=..., tick=...)` (`systems/memory/ops.py`) [V]. Add `RELATION_POLICY["customer"] = {"permanent": True, "salience": 0.7}` (and use `friend`/`rival` deltas for good/bad outcomes) so the follow-up survives; today's `friend`/`known` entries expire within minutes.
* World feed/UI: `engine._queue_event("commission_delivered", order_id, slot, ...)` (`map_test.py:_queue_event`) so `/frame.events` carries it; `engine._force_frame_refresh = True`.
* Goal/plan review: `record_event` already triggers `refresh_goals_for_event` and may queue reasoning reviews for specific kinds; commission kinds do **not** need to queue reasoning reviews in Stage 1 (models disabled).
* **Remembered follow-up** (Gate F): the smith's `socialize`/greeting line for a customer with a `delivered` order in the ledger uses an "ask how the sword treats you" variant. The authoritative source is the order ledger (persisted, never expires) with the memory event as a secondary signal.

### 3.5 Save/reload exactly-once guarantees

* Order records and escrow inventories are inside `engine.inventory_state` → captured by `world_snapshot.capture` and restored by `restore` with all other engine fields; `progress_ticks`, `state`, `committed`, `consumed`, `settled` are plain data [V: `ENGINE_FIELDS` includes `inventory_state`; `restore` setattr-loops every captured field].
* Restore bumps `world_epoch` and clears `CommandInbox` and possession; the smith's task plan, `AnchorMover` plans and `decision_service` caches are derived and rebuilt. After restore `advance_work` simply continues from `progress_ticks`.
* **Test matrix** (new `tests/test_smith_loop.py`): capture/restore at each state (`offered` no longer exists after the same-tick decision, so at `accepted/reserved`, mid-`working`, `ready`, `delivered`) and assert: one sword total in the world, ingredients consumed once, coin conserved (customer + smith + escrow = initial), `committed` flags unchanged, no second memory event, `delivered` order cannot be collected again.
* Counter safety: `order_id` comes from a persisted `next_order_uid`; the process-global `_TASK_COUNTER`/`_JOB_COUNTER` ids are never used as durable keys.
* Async hazard: resident sidecar writes can lag (`background_writes`), but a checkpoint reads `_cache`/`residents` in the payload, not the sidecar files [V: `capture`], so the snapshot is tick-consistent.

### 3.6 Failure branches

| Case | Behavior | Test |
| --- | --- | --- |
| Insufficient iron at request | option set excludes `accept_commission`; `refuse_no_materials` chosen; no order escrow, no state change except a `refused` record + memory event + line "no iron" (truthful) | stock = 0 → request → `refused(no_materials)`, inventories unchanged |
| Iron removed between accept and reserve | accept and reserve happen in one call, so impossible in Stage 1; if the policy allows waiting, `awaiting_materials` with `deadline_tick`; shortfall → `failed(no_materials)` and release | remove stock after accept in a controlled test using the waiting policy |
| Forge destroyed before request | `refuse_no_forge` | set forge `M_HP = 0` (or free its slot), request |
| Forge destroyed while working | `blocked_reason = "forge_unavailable"` set once; progress paused; after `FORGE_WAIT_TICKS` `failed(forge_unavailable)`; escrow returned once; customer and smith both get a committed `commission_failed` event; smith line explains "forge is wrecked" | destroy mid-work, step, assert refund and a single event |
| Smith dies / leaves | `fail_order(smith_unavailable)`; refund | kill smith in test |
| Duplicate request while open | `duplicate_open_order` with the existing id; no second escrow | request twice with different command ids |
| Duplicate command id | `CommandInbox` returns the stored receipt (same epoch) | extend the `/inventory/transfer` retry test pattern (`tests/test_inventory_commands.py`) |
| Duplicate collect | second call: `already_delivered` with the stored receipt | collect twice |
| Cancel after ready | not allowed (`invalid_transition`); cancel in `reserved` refunds everything | |
| Customer inventory full at delivery | stays `ready`, `blocked_reason = "customer_inventory_full"`, line says so | fill pack, collect |
| Customer far away or wall between | `interaction_ok` false → `rejected(out_of_range|blocked)` | actor behind the forge wall |
| Stale epochs | `CommandInbox.authorize` rejects (`stale_world_epoch`, `stale_possession_epoch`) [V] | existing pattern |
| Save/reload mid-craft | section 3.5 | |

### 3.7 Required data additions (small, mostly new-file)

* `systems/inventory/schema.py`: `iron_ingot` (material, stackable), `sword` (weapon, `main_hand`, not stackable).
* `systems/crafting/catalog.py`: `"sword"` recipe: `ingredient_requirements=(("iron_ingot", 2), ("wood_bundle", 1))`, `station_kind="forge"`, `required_tool_tags=("hammer",)` (not enforced by the engine; the commission facts check the smith's hammer), `occupation_tags=("smith",)`, `time_cost=1.5` (work ticks = `ceil(time_cost × WORK_TICKS_PER_UNIT)`, suggested 600 → 900 ticks, 45 s). Numbers are placeholders (decision D2).
* `systems/occupation/catalog.py`: `smith` blueprint.
* `genesis_config.py`: `M_FORGE` and `MAP_SCHEMA` entry, **owned by session 1006implementation** (integration note 1.4); P4 depends on it (D1).
* `runtime/resident_store.py`: `EVENT_POLICY` and `RELATION_POLICY` entries.

## 4. Step plan

Each step is independently shippable and keeps legacy behavior byte-identical (golden contract test stays green). "Extends" = existing test file; "adds" = new test. Phase A touches **no existing file except where marked**, so it can run in parallel with session 1006implementation.

### Phase A: pure/new-file work (no conflict)

| Step | Work | Files (new unless marked) | Extends / adds |
| --- | --- | --- | --- |
| P4.1 | Decision contract, `RulesDecisionProvider`, `RecordedDecisionProvider`, service with fallback and staleness, JSONL log | `systems/decision/{__init__,contract,providers,service,log}.py` | adds `tests/test_decision.py`: provider contract, normalization, malformed output → fallback, stale epoch/revision dropped, recorded replay, deterministic argmax, personality changes probabilities |
| P4.2 | Items, recipe, occupation data | edit `systems/inventory/schema.py`, `systems/crafting/catalog.py`, `systems/occupation/catalog.py` | adds `tests/test_commission_data.py` (recipe present, `crafting_missing_ingredients` for sword, smith occupation assignable via `preferred_kind`); existing tests unaffected |
| P4.3 | Work-order store and lifecycle on plain dicts: create, facts, reserve (all-or-nothing + rollback), advance, complete, deliver, cancel, fail, escrow release, committed-flag guard, revision CAS | `systems/commission/{__init__,orders,escrow,lifecycle,facts}.py` | adds `tests/test_commission_orders.py` (no engine; fake `inventory_state`): every transition table entry, duplicate calls, partial stock rollback, coin conservation invariant, order id counter persistence round trip |
| P4.4 | Outcome-driven lines and the dialogue read model | `systems/commission/{lines,dialogue}.py` | adds `tests/test_commission_dialogue.py`: choice enablement, line chosen by outcome code, deterministic variant |
| P3.1 | Roster loader and validator (against `WorldMap`, read-only import) | `systems/roster/{__init__,load,validate}.py`, `world_data/rosters/*.json` sample | adds `tests/test_roster.py`: fixture roster loads, rejects unknown anchor ids/kinds/duplicate anchors, `for_role` mismatch |
| P3.2 | `AnchorMover` (plan cache, exact step + `slide`, arrival tolerance, re-plan rules, negative cache) using `pathing.py` | `systems/movement/anchor_mover.py` | adds `tests/test_anchor_mover.py` (real `slide`): reaches anchors through 8 and 10 u doors without a teleport (per-tick displacement ≤ step), never embedded, re-plans on contract revision change, caches `no_path` |
| P3.3 | Interaction helper with owned-footprint exclusion (works with a plain contract + owner map) | `systems/commission/access.py` | adds `tests/test_interaction_access.py`: in range + clear, blocked by a wall, own footprint ignored, boundary cases |

### Phase B: engine integration (touches shared files; start only after session 1006implementation lands G5-G7 or agrees the extension points in section 6)

| Step | Work | Existing files edited (function level) | Extends / adds |
| --- | --- | --- | --- |
| P3.4 | Roster apply at world creation; occupation override; `roster_key` | `map_test.py:create_genesis` (1-3 line call into `apply_roster`) | extends `tests/test_map_contract.py` pattern; adds `tests/test_roster_apply.py`: residents appear on spawn anchors, standable, correct occupations |
| P3.5 | Anchor-aware schedule: place-tag → anchor resolution; arrival tolerance; bias zeroed for roster residents | `systems/schedule/navigation.py:build_schedule_navigation_bias`, `systems/tasks/families/occupation.py:_handle_move_to_place`, `map_test.py:_resolve_task_place_target`, `_execute_resident_task_step` (bridge lambda) | adds `tests/test_npc_schedule.py` (see P3.7); unit-level resolution checks go in `tests/test_roster_apply.py` |
| P3.6 | NPC motion limits: per-map step cap + second slide for the task phase; noise/bias masking for roster residents; optional per-map needs scale | `map_test.py:step` (one call after `_sync_slot_ids_and_events`), `instincts_and_tools.py:instinct_move`, `:instinct_hunger/instinct_thirst`, `systems/movement/map_contract.py` (new optional fields, owner: session 1006implementation) | extends `tests/test_map_contract.py` golden legacy contract (must stay equal); adds `tests/test_npc_motion.py`: legacy maps unchanged, roster resident displacement ≤ cap each tick, no jitter at an anchor over 200 ticks |
| P3.7 | Three-NPC day run: smith, builder, gatherer through dawn/day/dusk/night blocks | none (test only; starts the clock at block boundaries to keep it fast) | adds `tests/test_npc_schedule.py`: each NPC at its anchor kind at the expected block (within tolerance), per-tick displacement ≤ cap, no embedded state, survival does not starve them within the test window (needs per-map needs scale) |
| P4.5 | Commission tick hook + task family + station availability + persistence wiring | `map_test.py:_sync_managed_resident_tasks` (new branch after combat), `:_sync_slot_ids_and_events`/provisioning call site (`review_orders`/`advance_work` hook), `systems/tasks/{dispatcher,contracts}.py` (+ bridge callback), new `systems/tasks/families/commission.py`, `runtime/resident_store.py` (`EVENT_POLICY`, `RELATION_POLICY`) | adds `tests/test_commission_engine.py`: request → accept → reserve → work (progress only at the work anchor) → ready → deliver on a real `Engine.step` loop |
| P4.6 | Commands, routes, dispatcher registry | new `simulation/{dispatch,commission_commands}.py`; `map_test.py` (drain call, `/commission/*` routes, `/status` decision block) | extends `tests/test_inventory_commands.py` pattern: idempotent retry, stale/possession epochs, release-before-tick; adds `tests/test_commission_commands.py` |
| P4.7 | Save/reload and failure matrix, Gate F script | none beyond P4.5/6 | adds `tests/test_smith_loop.py`: section 3.5/3.6 matrix with `world_snapshot.capture/restore` (pattern from `tests/test_map_contract.py`) |
| P4.8 | Status/log/doc wiring and client contract note | `/status`, `tools/*.md` | adds log schema test in `tests/test_decision.py` |

Exit test (rebaseline P4): request → accept/refuse by real state → reserve → work → deliver once → remembered after reload, models disabled, in `tests/test_smith_loop.py` plus one real-process run against the actual client later.

## 5. Risks and open decisions

### Risks
* **R1 Survival pacing** (finding 6): +1 hunger/s and 40 HP/s starvation; residents will leave work to eat every ~50 s and die ~40 s later without food/water access. Must be settled before P3.7 can pass: per-map needs scale (recommended), or a guaranteed food/water loop.
* **R2 Task phase bypasses walls** (finding 5): NPCs can already end inside inflated walls and freeze. Fixed only if the mover slides or the reconcile order changes; touching `step` order changes legacy NPC behavior (gate per map).
* **R3 Order state vs derived tasks:** if anyone derives order progress from the task queue instead of the order record, replans (`replace_resident_tasks` every sync) will reset work. The order's `progress_ticks` is the only truth.
* **R4 Memory expiry** (finding 7): without the `EVENT_POLICY`/`RELATION_POLICY` edits the "remembered follow-up" fails in under a minute. Also `RECENT_EVENT_LIMIT = 14` can evict commission events if too many permanent entries accumulate.
* **R5 Dependency on unbuilt map work:** forge/chest instantiation (G5/G6), interior reachability and portals (G7), entity ownership of footprints, `interact_radius`. The loop can be developed against a single registered map in tests, but the real game needs the smith interior.
* **R6 Snapshot strictness:** the design avoids new `ENGINE_FIELDS`/`RUNTIMES` attributes; any later shortcut that adds one breaks all existing saves.
* **R7 `CommandInbox` receipts are not persisted:** retries after Continue always fail `stale_world_epoch`; the client must resync (`/commission/state`) after reconnect, which the wire contract's reconnect rules already imply.
* **R8 Two decision seams:** leaving `HumanAgentRuntime`'s tiny-model path in place beside `DecisionService` is intentional for Stage 1 but risks drift; schedule a convergence step after Gate H.
* **R9 Dialogue collision:** the keyword talk rules (`_generate_direct_result`) would also answer messages sent while a commission dialogue is open.
* **R10 Performance:** `world_contract` is rebuilt every tick and per call; adding a per-tick `AnchorMover` per NPC and orders is small (3 NPCs) but pathing must be cached (see `1006_pathing_notes.md`).
* **R11 Time-scale and pause:** work progress counts simulation ticks, so god-mode pause/time scale (G3) must pause it consistently; wall-clock deadlines (`input_timeout` 0.75 s, possession 5 s) do not.
* **R12 Hidden writers to inventory:** `/inventory/spend` and `/inventory/spawn_storage_case` mutate directly (rebaseline §8, not queue-routed [V route list]); a player could spend coin that is about to be escrowed in the same tick. Escrow happens at the decision, in-tick, so the window is one tick wide, but routing those through the queue closes it.

### Open decisions for the user (recommendations in bold)
* **D1** Deliver the stages in two phases (Phase A now, Phase B after G5-G7), or build P3/P4 against a single combined test map first? **Phase A now.**
* **D2** Economy numbers: sword = 2 iron + 1 wood, 30 coin, 45 s work? Who supplies iron (smith's stock, **customer-supplied option later**, god "spawn resource" in P5)? Does a failed order refund 100%? **Smith stock for Stage 1, full refund.**
* **D3** Where do orders live: `inventory_state["work_orders"]` (**recommended**, no schema change, escrow and ledger travel together) vs the smith's resident record.
* **D4** Memory permanence: make commission events and the `customer` relationship permanent (**yes**) or accept that they fade.
* **D5** Delivery mode: **player collects at the counter** in Stage 1 vs the smith carrying the item to the player (needs smith-to-player pathing and, cross-map, NPC portals which are P6).
* **D6** Cancel policy while `working`: **allow with forfeiture of the work-in-progress share (e.g. refund 50%)** vs disallow.
* **D7** `wander_local` for anchor residents: stay, or wander to a random standable point near the talk anchor.
* **D8** Needs pacing: **per-map needs scale** (e.g. ×0.05) vs a real food/water economy now.
* **D9** Dialogue: while a commission is open, suppress keyword talk replies for that resident (**yes**).
* **D10** Does session 1006implementation provide the extension points in section 6 (command registry, tick hook, post-genesis hook)? **Yes, ask now.**

## 5a. Decisions recorded (orchestrator, 2026-10-06)

* D1 Phase A (new files) is approved but sequenced after the Godot 2D client P2 task.
* D2 Economy numbers live in one data constant, tunable later; the smith holds a small iron stock; the player can supply iron through the god-power resource spawn; full refund on cancel before work.
* D3 Orders live in `inventory_state["work_orders"]` plus escrow inventories.
* D4 Permanent commission events and a customer relation.
* D5 Collect at the counter (smith-carries is P6).
* D6 Cancel allowed until state `working`; once working it cannot be cancelled in v1.
* D7 No wander for anchor-driven residents in P3.
* D8 Per-map needs scale lives in the roster file (`world_data/rosters/<map_id>.json`), not in the map schema.
* D9 Suppress keyword talk during an open commission dialogue.
* D10 Session 1006implementation builds the three extension points (command-executor registry `simulation/dispatch.py`, per-tick hook list, post-genesis hook list) as part of G7 and stores wall owner ids in the registry; this work then consumes them. No `map_test.py` edits until the orchestrator says so.

## 6. Conflicts with session 1006implementation and how to avoid them

Their current/queued ownership (scratchpad C-016-C-018, integration note S3-S8, wire contract): `world_map/`, `systems/movement/{spatial,map_contract}.py`, `genesis_config.py` (`M_FORGE`, footprint columns), `persistence/world_snapshot.py` (map manifest), and in `map_test.py`: `create_genesis`, `prime_protocol_state`, the `/bootstrap` route and new `/map_file` routes, the portal drain dispatcher, spawn/standability, the teleport handling in `Engine.step`; `instincts_and_tools.py` is also modified in the working tree [V: git status at read time].

My phases overlap them only at these **function-level** hot spots; none needs to be edited concurrently if sequenced:

| Hot spot | Who | Plan |
| --- | --- | --- |
| `map_test.py:create_genesis` (roster apply) | both | They add the authored-map branch; I add a 1-3 line `apply_roster(...)` call **after** their branch is merged, or they add a generic `engine.post_genesis_hooks` list I register into from a new module |
| `CommandInbox.drain(self, execute_inventory_command)` in `Engine.step` | both (portal vs commission) | Ask them to make it a registry (`simulation/dispatch.py: {action: executor}`); I register `commission_*` from `simulation/commission_commands.py` with no further `map_test.py` edit |
| `Engine.step` movement block (slide loop, teleport reset) | both | My motion-limit call is one line **after** `_sync_slot_ids_and_events`; schedule it after their portal step, in a short window announced on the scratchpad |
| `_sync_slot_ids_and_events` / provisioning call site (tick hook) | me | One line `for hook in self.tick_hooks: hook(self)` (or a direct call); offer them the same list for portal hooks |
| `genesis_config.py` `M_FORGE` | them | I wait for it; my data steps (P4.2) do not touch the file |
| `systems/movement/map_contract.py` new optional fields (`max_step_per_tick`, `needs_scale`, wall owner ids) | them | Request the fields; I do not edit the file |
| `world_snapshot.py` | them | I add no engine fields, so no overlap |
| `runtime/resident_store.py` | me | New dict entries only (`EVENT_POLICY`, `RELATION_POLICY`); small, low conflict |
| `instincts_and_tools.py` (`instinct_move`, hunger/thirst) | possibly both | Tell them before editing; masks are 3-line changes |

Concretely: do **Phase A first (P4.1-P4.4, P3.1-P3.3)**, which adds only new files and three data edits (`inventory/schema.py`, `crafting/catalog.py`, `occupation/catalog.py`) that nobody else is editing; post the section-6 extension-point request on the scratchpad; start Phase B only on their "G5-G7 implemented and tested" post.

## 7. Not verified

* Nothing in this document was executed. All behavior claims (step order, task movement bypassing slide, hunger pacing, memory TTLs, snapshot strictness) come from reading source and could be wrong where code changed while I read.
* Hunger/starvation timing (finding 6) is arithmetic from constants; the actual loop (eating from entities, rations, wells) could soften it.
* Whether `ensure_resident` can be bypassed cleanly for occupation overrides, and whether schedule re-derivation after clearing `schedule_state` is stable, was read but not exercised.
* The interaction of `replace_resident_tasks` with a new commission family (preemption, `current_source` matching in `_sync_managed_resident_tasks`) needs an experiment.
* `world_contract` fields for `max_step_per_tick`/`needs_scale`/wall owners do not exist; the registry API is session 1006implementation's to decide.
* No Godot/client behavior was considered beyond the HTTP contract sketched in 3.2.
