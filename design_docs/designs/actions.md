# 1008 Actions: the resident verb vocabulary, the affordance engine and the Tier 1 features (R3-M1, WS-C first slice)

Status (updated 2026-10-08 by the model plane track): **BUILT.** Sections 1 to 8 are the original design text (kept; where it differs from what was built, section 10 is authoritative).
Section 10 records what was built and measured: affordance engine (10.2 to 10.3), features (10.4), the first 17 verbs (10.5 to 10.6), components (10.7), follow-ups (10.8), plan cursor (10.9), verb batches 1 and 2 (10.10, 10.14), agent driver (10.11), resource-node verbs (10.12), `EDEN_AGENT_ACTIONS` and re-base (10.13).
Current catalog counts: 65 rows, now 37 / glue 13 / new 15; 30 rows have a registered Action, plus `eat_from_node`, `gather_from_node`, `approach_node` on the resource registry. Sections 2.3 and 9 below were written before batch 2: `offer_trade`, `accept_trade`, `steal_when_safe`, `share_news` and `gossip` are implemented (10.14).
Originally written by the Model plane worker on branch `1008implementation`;
paths owned: `at_the_beginning/systems/affordance/`, `at_the_beginning/systems/actions/` (new), `at_the_beginning/systems/decision/features.py`,
`tests/test_affordance*.py`, `tests/test_actions*.py`, `tests/test_decision_features*.py`, this file.

What I read to write it (so you know what is verified): `./implementation.md` WS-B, WS-C, WS-H (H.2, H.3 items 2, 3, 5, 12), Appendix A;
the harness core `registry.py`, `effects.py`, `events.py`, `target_selectors.py`, `world.py`, `adapter.py`, `powers.py`, `schema.py`, `items.py`
(all read in full); `systems/tasks/catalog.py` (all 58 task kinds), the survival and social family headers, `tasks/contracts.py` (`TaskWorldBridge`),
`tasks/ops.py::queue_resident_task`, `systems/commission/{decide,facts,access,config,engine,lifecycle}.py`, `systems/planning/catalog.py`,
`systems/crafting/stations.py`, `systems/decision/matrix.py`, `systems/schedule/catalog.py`, `systems/goal/catalog.py`, the starter-village map entity kinds.
**Not read in detail:** the bodies of most task handlers (occupation, combat, strategic, most of social), `systems/construction`, `systems/memory`,
`systems/social/grouping.py`, `systems/personality` beyond the trait list. Where a status below says "now" for a verb whose handler I only know by its
task kind, step 4 tests are what prove it; a failing test will move the verb to "glue" or "new" and I will say so.

---

## 1. Model: what an Action is and how it runs

A resident **verb** is one entry of the vocabulary below. It exists in three forms that must not drift:

1. **Catalog row** (`systems/actions/catalog.py`, data): `id`, group, params, legality predicate id, duration, interruptible, risk, mapped task kind,
   perception needs, Tier 1 menu entry, Tier 3 plan op, `status`. This document's tables are the source for it; a test (`tests/test_actions_catalog.py`)
   fails if the doc, the catalog and Appendix A.2 disagree on the set of ids.
2. **Legality predicate** (`systems/affordance/predicates.py`, the single home; the actions package imports it): a pure, named function `(situation, actor, params) -> Verdict(ok, reason, detail)`.
   The affordance engine (section 5) and the action runner call the same predicate, so "can this happen" has exactly one answer.
3. **Registered Action** (`systems/actions/verbs/*.py`, only for verbs with status `now`/`glue`): a function on the harness registry,
   `@action("eat", risk=..., precondition="has_edible_or_source", interruptible=...) def eat(world, ctx, item: str = "", ...) -> ActionDraft`.
   The `ctx` parameter is in `schema_for_function`'s skip list, so the generated JSON Schema contains only the model-visible parameters and the actor is
   never a model-supplied value. The function is pure: it reads `world`, returns the draft, and mutates nothing.

`ActionDraft` (mine, mirrors the harness `powers.Draft`): `effects` (harness `Effect`s), `event` (`Emit` or None), `task` (optional `TaskRequest`, see
below), `preview` (dict for logs and for the model's repair message).

**Runner** (`systems/actions/runner.py`, `run_action(world, actor, name, args, proposer=...)`), one path for every tier and for rules:

```
 1 schema      registry.validate_call(name, args, "action")      unknown verb / wrong args / extra args          -> reject  code=invalid_arguments | unknown_action
 2 grounding   every id-typed arg must be an id the affordance engine offers this actor right now                 -> reject  code=ungrounded_target
 3 legality    predicate(situation, actor, args)                   dead, no item, unreachable, no room, ...      -> reject  code=illegal:<reason>
 4 rate/risk   per-actor cap, risk gate (destructive/irreversible need min confidence, may be forced to rules)   -> reject  code=rate_limited | risk_gated
 5 plan        draft = fn(world, ctx, **args)                      pure
 6 apply       world.apply(draft.effects + [event], atomic=True, cause="action:<name>")   revision bump, ledger event
 7 task        draft.task -> systems.tasks.ops.queue_resident_task(...) on the live resident record                (durative verbs)
 8 audit       one entry per call, accepted or rejected: tick, actor, verb, args, proposer/tier, probabilities if given, verdict, reason code, effect counts
```

Steps 1 to 4 are re-run at apply time if the world revision moved between a plan and its application (same rule as `powers.apply`): a target that
died, a bed that was taken or an item that was given away turns the call into a rejection, never into a wrong effect.
**Gate C rejection test** = for each implemented verb, a nonexistent verb name, wrong argument names, a wrong type, a stable id that does not exist, an
id that exists but is unreachable / not offered, and a dead actor are all rejected with a stable reason code and one audit entry. The audit log is an
in-memory ring plus an optional JSONL sink (`DecisionLog`-style, under the data root); it is not wired to the engine.

**Two kinds of verb, because the harness has two kinds of consequence:**

* **Atomic verbs** change state in one step and are expressible as harness `Effect`s: `eat` from the pack, `give_item`, `craft` at a station in reach.
* **Durative verbs** need walking, waiting or a work cycle, which today live in the task executors (`systems/tasks/families/*`, 58 task kinds, run by
  `Engine._execute_resident_task_step`). The Action's draft carries a `TaskRequest(task_kind, target_kind, target_id, target_place, required_item,
  requested_quantity, priority, metadata)` and the runner enqueues it with `queue_resident_task(resident, ...)`; the existing executor then does the how.
  The Action's job is validation, grounding, audit and the immediate effects (for example an event). No tensor is written by the verb itself for these.

**Parameter grounding rule (the Gate C core).** A model never writes coordinates, slot numbers or free-text place names. Ids are stable resident ids
(`h_000003`), entity ids (`village:house_smith`, `e_...`), map anchor ids (`village:use_well`), item kinds from the inventory catalog and recipe ids from the
crafting catalog. The affordance engine lists the concrete values that are legal for each verb for this actor *now* (nearest food id, the well anchor, the
recipe the station fits, the neighbour who is in range); the runner refuses any id outside that list, even if it exists in the world.

Risk classes follow the harness (`reversible`, `destructive`, `irreversible`). My classification: everything is `reversible` except those marked in the
tables. Open question D-3.

Status column: **now** = every system it needs exists and a task executor or atomic effect path exists (to be proven by the step 4 tests);
**glue** = the systems exist, a small piece of new code in my own paths is needed (a draft builder, a predicate, a decision topic);
**new** = needs a system that does not exist (market and prices, rumours, law, place memory, skill transfer, settlement), outside this slice.
`S1` = in the first slice I will implement in step 4.

---

## 2. Vocabulary (Appendix A.2, 65 verbs)

Columns: **params** (JSON Schema is generated from the Action signature; `T` = target id, `P` = place/anchor id, `I` = item kind, `n` = int, `R` = recipe id),
**legality** (predicate id, section 4), **effects / executor** (what changes, and which existing task kind or system does the work), **dur** (`i` = one tick,
`task` = multi-tick task, `intr` = interruptible per `TASK_KIND_DEFS`), **risk** (blank = reversible), **T1** (Tier 1 macro it belongs to),
**op** (Tier 3 plan op: existing `PLAN_OP_DEFS` name or *proposed* new name), **status**.

### 2.1 Survival

| id | params | legality | effects / executor | dur | risk | T1 | op | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `eat` | `item?:I, place?:P` | `can_eat` (edible in pack, else edible source in perception) | pack: `Transfer(item, 1, actor, None)` + `Delta hunger -20` (`EAT_HUNGER_RESTORE`) + `Emit ate`; else task `eat_food` (target resource `food`) walks to the source | i / task, intr | | `eat` | *eat* (new op) | now **S1** |
| `drink` | `place?:P` | `can_drink` (water site of the roster, or a tensor water source, reachable) | task `fetch_water` (target resource `water`); the executor applies `thirst -35` (`DRINK_THIRST_RESTORE`) and consumes the source unit | task, intr | | `drink` | *drink* | now **S1** |
| `rest` | `until?:{hp|stamina}` | `can_rest` (alive, hp or stamina below max) | task `sleep` with `metadata.mode="rest"`; stops at `RECOVERED_STAMINA_THRESHOLD`; no bed needed | task, intr | | `rest` | `rest_until_safe`, `recover_until_hp` | now **S1** |
| `sleep` | `place?:P` | `can_sleep` (home anchor or shelter reachable, threat below `SHELTER_SEEK_THREAT`) | task `seek_shelter` then `sleep` at the home anchor | task, intr | | `sleep` | *sleep* | now **S1** |
| `seek_shelter` | `place?:P` | `shelter_reachable` | task `seek_shelter` (resolves best safe target) | task, intr | | `go_home`, `hide` | *seek_shelter* | now |
| `light_fire` | `place:P, fuel?:I` | `can_light_fire` (fuel item, firepit/campfire entity in reach) | none today: a campfire is a static entity with no fuel or burn state | task | | `build` | *light_fire* | new (fire/fuel state) |
| `treat_wound` | `target?:T, item?:I` | `can_treat` (bandage/herb in pack; target in range or self) | for another resident: task `help_target` / `heal_target_action(bandage)`; self-treatment has no executor | task | | `help` | *heal_target* | glue (other) / new (self) |
| `flee_to` | `place?:P, from?:T` | `can_flee` (alive, a perceived threat or `from` given; a safe target exists) | task `flee_target` (priority 0.97, not interruptible), or `escape_area` | task, not intr | | `flee` | `escape_and_hide`, *flee_to* | now **S1** |
| `hide` | `place?:P` | `can_hide` (safe target in reach) | task `wait_in_hiding` after `move_to_place` | task, intr | | `hide` | `escape_and_hide` | now |

### 2.2 Work

| id | params | legality | effects / executor | dur | risk | T1 | op | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `go_to_work` | `place?:P` | `has_work_anchor` (roster work anchor or `work` map anchor) | task `move_to_place` to the anchor (schedule routine `work_site`) | task, intr | | `work_at_station` | `move_to_place` | now **S1** |
| `work_shift` | `ticks?:n` | `can_work` (occupation with a work task, at or near the anchor, tools per occupation) | the occupation's work task: `chop_wood`, `farm_work`, `fish_work`, `gather_work`, `build_work`, `hunt_work`, `heal_work`, `trade_run`, `patrol_area` | task, intr | | `work_at_station` | *work_shift* | now **S1** |
| `gather_resource` | `source:T (entity id), qty?:n` | `resource_reachable` (a gather node entity in perception radius: wood_pile, stone_pile, berry_bush, iron_pile) | task `gather_material` (`gather_radius` 24) | task, intr | | `gather` | `gather_food_buffer`, *gather_resource* | now **S1** |
| `hunt` | `target?:T` | `can_hunt` (huntable animal in perception, weapon or tool per occupation) | tasks `hunt_work`, `finish_hunt`, `loot_after_kill` | task, intr | | `gather` | *hunt* | now |
| `fish` | `source?:P` | `resource_reachable("fish")` | task `fish_work` | task, intr | | `gather` | *fish* | now |
| `farm_tend` | `plot?:P` | `can_farm` (plot entity in reach) | task `farm_work` (crop growth instinct is a separate NEW item, A.1) | task, intr | | `gather` | *farm_tend* | now |
| `craft` | `recipe:R, qty?:n` | `recipe_craftable` (ingredients in pack or reachable store, station kind in range, occupation tag, output room) | atomic part: `Transfer(ingredient, q, actor, None)` per ingredient + `Transfer(output, q, None, actor)` + `Emit crafted`, after the recipe `time_cost` via task `craft_item` (+ `ensure_required_tool`) | task, intr | | `work_at_station` | *craft* | now **S1** |
| `repair` | `target:T` | `can_repair` (damaged structure in reach, materials) | **no repair task exists** (`grep repair` in tasks: none); legacy `tool_repair_area_with_humans` is a god power | task | | `repair` | *repair* | new (construction repair task) |
| `build_structure` | `kind:I, site?:P` | `can_build` (materials, free site) | tasks `designate_build_site`, `build_project`, `build_work` | task, intr | | `build` | *build_structure* | glue (kind table) |
| `haul_items` | `item:I, qty:n, to:P` | `can_haul` (stock in a reachable store, destination reachable) | composite: `withdraw_item`, `move_to_place`, `store_item` | task, intr | | `gather` | *haul_items* | now (composite) |
| `store_item` | `item:I, qty?:n, container?:T` | `storage_reachable` (storage case in range, room) | task `store_item` | task, intr | | `work_at_station` | *store_item* | now **S1** |
| `fetch_item` | `item:I, qty?:n, container?:T` | `item_in_storage` (accessible store holds it, in range) | task `withdraw_item` | task, intr | | `work_at_station` | *fetch_item* | now **S1** |

### 2.3 Economy

Everything in `offer_trade`, `accept_trade`, `buy`, `sell`, `set_price`, `pay_debt` needs a market and ledger system that does not exist (prices exist
only as `COMMISSION_CONFIG["prices"]`, coin is an inventory item). They are catalogued so the manifest is complete and the mask has a stable column, but they
are *not* implementable now.

| id | params | legality | effects / executor | dur | risk | T1 | op | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `offer_trade` | `T, give:{I,n}, want:{I,n}` | `can_trade` (both in interaction range, offerer holds `give`) | needs an offer object with a lifecycle (like the work order) | i | | `trade` | *offer_trade* | glue (10.14) |
| `accept_trade` | `offer:id` | `offer_open` | the paired `Transfer`s, atomic | i | | `trade` | *accept_trade* | glue (10.14) |
| `request_item` | `T, item:I, qty?:n` | `can_request` (target alive, in interaction range; whether it holds the item is *its* business, not a legality condition, so the actor's options never leak the target's pack) | `queue_social_signal` to the target; the target decides (decision topic `request_item`, rules scorer built like `commission_scorer`: `give`, `refuse_no_item`, `refuse_distrust`, `refuse_busy`); on `give` -> `give_item` from the target | task | | `trade`, `ask_for_help` | *request_item* | glue **S1** |
| `give_item` | `T, item:I, qty?:n` | `can_give` (actor holds it, target alive and in interaction range with a clear line, target has room) | `Transfer(item, qty, actor, T)` + `Emit gave_item` + relationship `closeness` update through `resident_store.update_relationship`; far targets: task `deliver_item` | i / task | | `help`, `trade` | *give_item* | now **S1** |
| `buy` | `T, item:I, qty:n` | `can_buy` | price book and `Transfer` of coin | i | | `trade` | *buy* | new (market) |
| `sell` | `T, item:I, qty:n` | `can_sell` | as `buy` | i | | `trade` | *sell* | new (market) |
| `set_price` | `item:I, price:n` | `owns_shop` | price book per resident | i | | `trade` | *set_price* | new (market) |
| `commission_item` | `T, recipe:R` | `can_commission` (target is a resident whose occupation tag covers the recipe, in interaction range, customer alive) | `systems.commission.decide.submit_request(...)` through the engine's `execute_commission` path: creates the order, the smith decides with the Stage 1 rules provider, escrow, work, `ready`, collect | task (order lifecycle) | | `trade` | *commission_item* | now **S1** (resident customer path) |
| `pay_debt` | `T, n` | `has_debt` | needs debts | i | | `trade` | *pay_debt* | new (ledger) |

### 2.4 Social

| id | params | legality | effects / executor | dur | risk | T1 | op | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `greet` | `T` | `can_talk` (target alive, in interaction range or approachable) | task `talk_to_target` with `speech_act=greeting`; relationship `closeness` +small; `Emit greeted` | task, intr | | `socialise` | *greet* | now **S1** |
| `chat` | `T?, topic?:str` | `can_talk` | tasks `approach_target`, `socialize`, `talk_to_target`; the `talk` system produces text, not this layer | task, intr | | `socialise` | *chat* | now **S1** |
| `ask_for_help` | `T?` | `can_call_help` (anyone alive in perception) | task `call_for_help` (priority 0.72) | task, intr | | `ask_for_help` | `recruit_allies` | now |
| `comfort` | `T` | `can_comfort` (target alive, in range, mood low) | task `comfort_target` | task, intr | | `help` | *comfort* | now |
| `teach` | `T, skill:str` | `can_teach` | `H_SKILL` is a single scalar column, there is no skill list to transfer | task | | `socialise` | *teach* | new (skills) |
| `share_news` | `T, event:id` | `knows_event` | needs per-resident knowledge of events and a rumour decay model (A.1 `instinct_rumor_spread`) | task | | `socialise` | *share_news* | glue (10.14) |
| `gossip` | `T, about:T` | `knows_event` | as `share_news` | task | | `socialise` | *gossip* | glue (10.14) |
| `court` | `T` | `can_court` (adult, opposite/any per sex rules, target in range) | tasks `seek_mate`, `mate_with_target` only reach mating; courtship without mating has no state | task | | `socialise` | *court* | glue (closeness steps) |
| `befriend` | `T` | `can_talk` | repeated `chat`/`give_item` raises `closeness` (a relationship update); no new system | task | | `socialise` | *befriend* | glue |
| `apologise` | `T, event?:id` | `has_harmed(T)` | needs a recorded harm event between the two; relationship update | task | | `socialise` | *apologise* | glue |
| `forgive` | `T` | `has_grudge(T)` | relationship update and goal clear (`retaliate`) | i | | `socialise` | *forgive* | glue |
| `follow` | `T` | `target_reachable` | task `follow_target` (`FOLLOW_RADIUS` 10) | task, intr | | `socialise` | `move_to_target`, *follow* | now **S1** |
| `invite` | `T, place:P` | `can_talk` | needs an invitation object and acceptance | task | | `socialise` | *invite* | new |
| `ask_directions` | `T, place:str` | `can_talk` | needs place knowledge per resident | task | | `socialise` | *ask_directions* | new (place memory) |

### 2.5 Conflict and law

| id | params | legality | effects / executor | dur | risk | T1 | op | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `warn` | `T` | `can_talk` | task `warn_target` (priority 0.58) | task, intr | | `avoid`, `defend` | *warn* | now |
| `threaten` | `T` | `can_talk` | `warn_target` with a fear effect on the target; no fear mechanic is wired to it | task | | `defend` | *threaten* | glue |
| `defend` | `T?, place?:P` | `can_defend` (kin/ally or home in perception) | tasks `protect_target`, `guard_target`, `protect_home`, `guard_area` | task, intr | | `defend` | `guard_place` | now |
| `attack` | `T` | `can_attack` (target alive, not self, not an ally by rules, in perception) | task `attack_target` (priority 0.95, not interruptible); damage resolves in the combat system | task, not intr | destructive | `attack` | `attack_target_when_close` | now |
| `arrest_or_restrain` | `T` | `holds_authority` | no law or restraint system | task | destructive | `defend` | *arrest* | new (law) |
| `steal_when_safe` | `T or container:T` | `can_steal` (container/resident in reach, nobody witnessing is a *plan* condition, not a legality one) | task `steal_from_container` (`steal_from_container_action`) | task | destructive | `attack` | `steal_from_target_when_safe` | now |
| `report_crime` | `T, about:T` | `witnessed_crime` | task `report_crime` (priority 0.63) | task, intr | | `ask_for_help` | *report_crime* | now |
| `avoid` | `T` | `target_in_perception` | task `retreat_from_target` / goal `avoid_target` | task, not intr | | `avoid` | `avoid_target` | now |
| `retaliate` | `T` | `can_attack` and goal `retaliate` or a recorded harm event | `attack_target` with a justification record | task, not intr | destructive | `attack` | *retaliate* | now |

### 2.6 Exploration and knowledge

| id | params | legality | effects / executor | dur | risk | T1 | op | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `explore_toward` | `heading?:{N,NE,...}` or `P` | `can_move` | task `move_to_place` / `scout_area`; today only inside the finite map | task, intr | | `explore` | `move_to_place` | now |
| `scout_region` | `P?` | `can_move` | task `scout_area` (plan kind `scout_region`) | task, intr | | `explore` | `observe_target`, *scout_region* | now |
| `mark_place` | `name:str` | `can_move` | needs per-resident place memory | i | | `explore` | *mark_place* | new (place memory) |
| `remember_place` | `P` | `perceives(P)` | as `mark_place` | i | | `explore` | *remember_place* | new (place memory) |
| `lead_group_to` | `P, members:[T]` | `leads_group` | `social/grouping.py` exists; the lead/follow protocol around `escort_target` + `return_to_group` is untested | task | | `explore` | *lead_group_to* | glue |
| `migrate_group` | `P` | `leads_group` | needs settlement and chunk travel | task | | `explore` | *migrate_group* | new |
| `settle_site` | `P` | `can_build` | needs a settlement object | task | | `build` | *settle_site* | new |

### 2.7 Cognitive control

These do not act on the world; they change which tier decides next. They are resident-record writes (plan store, reasoning-review flag), so they carry no tensor
`Effect`; the runner records them in the audit and `Emit`s `decision_escalated`.

| id | params | legality | effects / executor | dur | risk | T1 | op | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `USE_BRAIN` | `reason?:str` | `can_think` (alive, brain budget not exhausted) | `queue_reasoning_review(resident, tick, reason)` | i | | `USE_BRAIN` | - | now |
| `REPLAN` | `reason?:str` | `plan_exists` | `queue_reasoning_review` + `plan_step_failed` flag | i | | `REPLAN` | - | now |
| `PLOT` | `target?:T` | `has_plot_motive` (goal `retaliate`/`steal_when_safe`/rival tag) | stores a plan request of kind `ambush`/`revenge`/`theft` for the reasoning lane | i | destructive | `PLOT` | plan kinds `ambush`, `revenge`, `theft` | now |
| `reflect` | - | `can_think` | memory consolidation by Tier 2/3; there is no consolidation system | task | | `USE_BRAIN` | *reflect* | new |
| `continue_plan_step` | - | `plan_active` and next step valid | `execute_compiled_plan_step` (planning executor) | i | | `continue_plan_step` | - | now |

**Counts** (counted by script from the tables above; `tests/test_actions_catalog.py` will keep them honest): 65 verbs; `now` 37, `glue` 13, `new` 15.
The 17 `S1` verbs (first slice): `eat`, `drink`, `rest`, `sleep`, `flee_to`, `go_to_work`, `work_shift`, `gather_resource`, `craft`, `store_item`, `fetch_item`,
`request_item` (glue), `give_item`, `commission_item`, `greet`, `chat`, `follow`.

---

## 3. Tier 1 menu <-> verbs (the 24 macros of `decision/matrix.py`)

The macro is *what kind of thing*; `resolve(macro, actor)` in the affordance engine picks the concrete verb and parameters (nearest legal by distance, ties by
id). The matrix never sees parameters.

| macro | resolves to (in order of preference) | mask M[i, macro] is true when |
| --- | --- | --- |
| `eat` | `eat` | `can_eat` |
| `drink` | `drink` | `can_drink` |
| `rest` | `rest` | `can_rest` |
| `sleep` | `sleep` | `can_sleep` |
| `work_at_station` | `craft` (open commission or occupation recipe) > `work_shift` > `go_to_work` > `fetch_item`/`store_item` | `has_work_anchor` and `can_work` or `has_work_anchor` (go there) |
| `gather` | `gather_resource` > `fish` > `farm_tend` > `hunt` | any `resource_reachable` |
| `go_home` | `seek_shelter` (home anchor) | `home_anchor` |
| `socialise` | `chat` > `greet` > `follow` | another live resident in perception |
| `trade` | `commission_item` > `request_item` > `give_item` (market verbs absent) | neighbour in range and (actor holds coin or item, or a recipe fits their occupation) |
| `help` | `give_item` > `comfort` > `treat_wound` | a perceived resident in need (hunger, hp, mood, threat over a threshold) and a way to help |
| `avoid` | `avoid` | a perceived non-self target |
| `flee` | `flee_to` | alive and not immobilised (a threat does not have to exist: legality is not advice) |
| `defend` | `defend` > `warn` | kin/ally or home in perception |
| `attack` | `attack` | `can_attack` |
| `explore` | `explore_toward` > `scout_region` | `can_move` |
| `build` | `build_structure` | `can_build` |
| `repair` | `repair` | `can_repair` (always false until the repair task exists) |
| `ask_for_help` | `ask_for_help` | anyone in perception |
| `hide` | `hide` | `can_hide` |
| `idle` | task `idle` | alive |
| `continue_plan_step` | `continue_plan_step` | `plan_active` |
| `USE_BRAIN`, `REPLAN`, `PLOT` | same-named cognitive verbs | `can_think`, `plan_exists`, `has_plot_motive` |
| 6 commission outcomes | `commission.legal_options(facts)` computed from the affordance engine's own facts | an `offered` order addresses this resident (parity-tested against `systems/commission/decide.legal_options`) |

A dead resident has an all-false row (the matrix already reports `no_legal`). `repair` and part of `build` are false in this slice, which is the truth, not a
placeholder.

---

## 4. Legality predicates (names used above)

All pure, read-only, perception-bounded (they query `world.within` with the resident's perception radius, never the whole table). Reason codes are stable
strings so the audit and the model's repair message can use them: `dead`, `no_item`, `no_edible`, `no_source`, `unreachable`, `out_of_range`, `blocked`,
`no_room`, `no_station`, `no_recipe`, `missing_ingredients`, `wrong_occupation`, `no_target`, `target_dead`, `self_target`, `not_offered`, `rate_limited`.

`alive`, `can_eat`, `can_drink`, `can_rest`, `can_sleep`, `shelter_reachable`, `home_anchor`, `has_work_anchor`, `can_work`, `resource_reachable(kind)`,
`recipe_craftable(recipe)`, `storage_reachable`, `item_in_storage`, `can_give`, `can_request`, `can_commission`, `can_talk`, `can_comfort`, `can_treat`,
`can_call_help`, `can_defend`, `can_attack`, `can_steal`, `can_hide`, `can_flee`, `can_move`, `plan_active`, `plan_exists`, `can_think`, `has_plot_motive`,
`target_reachable`, `target_in_perception`; the not-yet-buildable ones (`can_trade`, `offer_open`, `holds_authority`, `knows_event`, ...) exist as predicates that
return `Verdict(False, "system_missing")` so the manifest stays total.

Reachability (D-4, changed in review): an immediate interaction (`give_item`, `request_item`, `craft` at a station, `store_item`) uses
`systems.commission.access.interaction_ok` (range plus clear line, wall boxes). Anything the resident must walk to (`eat`/`drink` at a site, `sleep`, `go_to_work`,
`chat`, `follow`, `gather_resource`, `explore_toward`) uses the pluggable `Reach` (section 5): straight line first, then `movement.pathing.plan_path` with an expansion cap,
a cache keyed by (contract revision, start cell, goal cell, goal entity), one portal hop per call (up to 3), and a reverse search from the goal when the forward
search runs out of budget. A capped answer falls back to the straight-line result and is marked `reachability="approx"`; every other answer is `"exact"`.

---

## 5. Affordance engine (step 2) - BUILT

Files: `verdicts.py` (Verdict, Option, ActionCall, reason codes), `config.py` (radii and thresholds, all placeholders), `services.py` (`Services`, `EngineServices`
read-only over the engine, `StaticServices` for synthetic worlds), `observation.py` (`observe()`: the perception-bounded input), `reach.py`, `predicates.py`
(one `@verb` per verb: predicate + candidate generator), `commission.py` (the six outcomes from the engine's own facts), `engine.py` (`AffordanceEngine`, `MACRO_VERBS`),
`testing.py` (`WalledServices`), `bench.py`. Predicates exist for all the `S1` verbs plus the ones the 24 macros need (`repair` is a predicate that answers `system_missing`).
Tests: `tests/test_affordance_unit.py` (synthetic worlds) and `tests/test_affordance_engine.py` (real booted engine). Results in section 10.

Original plan: `systems/affordance/`: `AffordanceEngine(world, services)`; `options(actor) -> list[Option]` where `Option = (verb, params, legal, reason, distance, target_ids)`;
`legal(actor, verb, params) -> Verdict` (same predicate the runner uses); `mask(actors) -> bool[N x K]` over `decision.matrix.MENU`;
`commission_options(smith, order)`; `resolve(macro, actor) -> ActionCall | None`. It needs three things beyond the harness `World`: the resident record store,
the inventory store (already behind `world.items`) and the map facts (anchors, entity kinds). The engine adapter exposes `world.residents`; anchors and entity kinds come
from `systems.movement.map_contract` and `systems.roster.driver.anchor_positions` (read-only). Parity target and the cases required by the assignment:
smith commission (accept / `refuse_no_materials` / `refuse_no_forge` / `refuse_cannot_afford` / `refuse_busy` / `refuse_distrust`), no iron, dead resident,
`no_room` (recipient pack full), unreachable target.

## 6. Tier 1 features (step 3) - BUILT (design text below kept; what differs from it is listed in 10.4)

`systems/decision/features.py`: `FEATURE_SCHEMA_VERSION = 2` (the matrix module's synthetic schema is version 1 and stays untouched), `build_features(world, services, residents)
-> (X[N x F], P[N x 16], meta)` from `h_tensor` columns (hunger, thirst, stamina, hp, threat, mood), the resident record (personality traits and pressures, schedule block,
goal urgency, plan flags, relationships to the nearest K), perception-bounded scene counts via `world.within`, time of day, and inventory flags via `world.items`.
Vectorised for the numeric part; the per-resident record reads are Python (8 now, measured, not promised for 100). Same 26 feature names and meaning as v1 where one exists so the
trained or placeholder `W` still applies; new columns are appended and bump the version. Shadow helper `features.shadow_compare(...)` is a test-harness function that runs a
seeded headless engine for N ticks and reports matrix-vs-rules agreement on the commission topic and macro-menu agreement on `eat`/`drink`/`sleep`/`flee` situations; it is
not called by the engine and has no default-on flag.

---

## 7. Tier 3 plan ops

Existing `PLAN_OP_DEFS` (13 ops) map onto verbs: `move_to_place` -> `go_to_work`/`explore_toward`; `move_to_target` -> `follow`; `observe_target` -> `scout_region`;
`avoid_target` -> `avoid`; `recruit_allies` -> `ask_for_help`; `attack_target_when_close` -> `attack`; `guard_place` -> `defend`; `steal_from_target_when_safe` ->
`steal_when_safe`; `return_home` -> `seek_shelter`; `rest_until_safe`/`recover_until_hp` -> `rest`; `gather_food_buffer` -> `gather_resource`; `wait_until_tick` is not a verb
(control flow). Proposed new ops (in `systems/actions/plan_ops.py` until the orchestrator approves edits to `systems/planning/catalog.py`, which is not in my paths):
`eat`, `drink`, `sleep`, `craft`, `give_item`, `request_item`, `commission_item`, `greet`, `chat`, `work_shift`, `gather_resource`, `flee_to`, `store_item`, `fetch_item`.
A **mock Tier 3 plan** for Gate C is a list of such steps with args; `run_plan` calls `run_action` for each and stops at the first rejection, returning the audit entries.

---

## 8. Open choices ([DECISION]) and the default I proceed with

* **D-1 Consumption and creation of items.** `EffectApplier` refuses `Transfer` with `src=None` or `dst=None` unless the whole applier has `allow_item_creation`.
  `eat` (consume) and `craft` (consume ingredients, create output) need exactly that. **Default:** the action runner enables the flag only for a call whose action declares
  `consumes`/`produces` and only for `Transfer`s that match the declaration (checked by me), via the public attribute; no harness file is edited. Preferred outcome: the harness grows a
  separate declared `consume`/`produce` permission (a [GAP] to Harness).
* **D-2 Durative verbs enqueue legacy tasks, not effects.** The harness has no task-request effect. **Default:** `ActionDraft.task` + `queue_resident_task` in the runner as in section 1.
  Alternative: a `Task` effect type in the harness so an atomic plan can carry it.
* **D-3 Risk classes.** Default: `attack`, `retaliate`, `steal_when_safe`, `arrest_or_restrain`, `PLOT` are `destructive`; nothing is `irreversible` in this slice (a resident death by
  `attack` is combat resolution, and I do not classify the verb by its worst outcome). Destructive verbs get the stricter gate in the runner (min confidence config, forced to rules when a
  model proposes it with `top_p` below it).
* **D-4 Reachability** - CHANGED BY REVIEW (R3-M1a-D): pluggable `Reach`, `plan_path` with a small expansion cap (`REACH_MAX_EXPANSIONS` = 6000), cache on (contract revision,
  start cell, goal cell), fall back to the straight line and mark `approx` when the cap is hit. Built; the detour case is tested on synthetic and on the real map. Cost in section 10.3.
* **D-5 Who edits `PLAN_OP_DEFS`.** Default: ops live in `systems/actions/plan_ops.py`; `systems/planning/catalog.py` is untouched.
* **D-6 First-slice list.** Default: the 17 `S1` verbs above (the assignment asked for about 12; `store_item`, `fetch_item`, `follow`, `greet`, `work_shift` are cheap given the others).
  `repair` is dropped from the slice because no repair executor exists.
* **D-7 Where the mask lives.** Default: `AffordanceEngine.mask` returns a plain `torch.bool` N x K tensor in `MENU` order and nothing in the engine calls it.

## 9. What is not done / not claimed

* Sections 5, 6 and 10.1-10.7 are built. Step 4 is built for the 17 S1 verbs plus the batches of 10.10 (batch 1: 8 verbs); the other catalog rows have no registered Action (`not_implemented`).
* The runner is not called by the engine, and `ActionRunner` needs an explicit `record_ops` (`EngineRecordOps(engine)`) to do anything besides item/tensor effects.
* Statuses `now` are inferred from task kinds and handler names, not from running them; step 4 tests decide (see finding F-1).
* The new plan ops (section 7) live in `systems/actions/plan_ops.py`. `systems/planning/validator.py` accepts only the ops in `PLAN_OP_DEFS`, so a plan that uses them will **not**
  run in the planning system until a later integration that touches `systems/planning` (needs the orchestrator's OK). Until then they run only through `actions.run_plan`.
* `Reach` quantises start and goal to 2-unit cells for caching, so a start within about 1 unit of a wall edge can inherit the answer of a neighbouring cell.
* Walls broken within a tick show up in `Reach` on the next tick (the contract is cached per tick); entity liveness (forge hit points) is read fresh on every call.

---

## 10. Step 2 results

### 10.1 Findings from reading and probing the real engine (they change what some statuses mean)

* **F-1. All 8 Stage 1 residents are anchor-driven, not task-driven.** `systems/roster/driver.py` moves every non-controlled resident that has a roster binding
  (the schedule picks an anchor, an `AnchorMover` walks there, "nothing else moves them"); task movement is suppressed (`Engine._move_human_toward_point`). Only the smith has
  `work_mode: occupation`, the other seven are `anchor_only`. So a verb that I mapped to a movement task (`go_to_work` -> `move_to_place`, `sleep` -> `seek_shelter`, `flee_to`,
  `follow`) may not move a roster resident at all through `queue_resident_task`. The levers that do work for them are the schedule routine (`schedule.lifecycle.set_current_routine`
  -> anchor key) and roster needs trips. Step 4 will test each S1 verb against a roster resident and report which ones need the routine route or are demoted to `glue`.
* **F-2. Food and water have no task-level source in the authored village.** `Engine._resolve_task_resource_target("food"|"water")` and `_resolve_task_safe_target` returned `None` for
  residents of the starter village: authored map objects (well, berry patch, campfire, beds) are `M_MAP_OBJECT` rows with zero food and water columns. Roster residents eat and
  drink through `systems/roster/needs.py` (a trip to the roster's water/food anchor, `ticks` standing there, or a free ration), which is not a task. The affordance engine mirrors the
  executors: the sources it offers are the roster need sites plus tensor entities that really carry a food/water resource, so `drink` for iven is "village:use_well" and for the smith's `eat`
  it is "village:use_campfire" (across the smith-house portal: about 110 units by the exact path).
* **F-3. Legality is deliberately not advice.** `flee_to` is legal for any living resident that knows a shelter, `rest` only when stamina or hp is below max (`not_needed` otherwise),
  `eat`/`drink` only from hunger/thirst 1.0 (`not_needed`), so the mask is sparse at tick 0 (nobody can eat or drink): intended, not a bug.
* **F-4. `Verdict` must not define `__bool__`.** An early version did and every `if dead:` / `bad or ok` idiom on error verdicts silently inverted; removed, and a test now asserts that
  `legal()` on a dead resident returns the reason `dead` for every registered verb.

### 10.2 Parity and cases (all green)

`tests/test_affordance_engine.py::CommissionParityTests` creates a real `offered` order on the booted engine and compares `AffordanceEngine.commission_options` with
`legal_options(commission_facts(...))` of Stage 1 for 12 states: baseline (`accept_commission`), no iron, one iron (needs two), no wood, customer cannot afford, forge wrecked (hp 0),
forge entity gone (type 0), busy (two other open orders), distrust (closeness -0.6), rival tag, smith dead (`refuse_busy`, Stage 1's fallback) and four reasons at once
(`refuse_no_forge, refuse_no_materials, refuse_cannot_afford, refuse_distrust`, same order). Each case asserts equality with Stage 1 and, separately, the expected list (so a change on
either side fails). Real-engine cases also cover: the mask for 8 residents, dead resident (empty options, all-false row, `target_dead` for others), hungry resident with a pack ration vs
the smith with only a site, drink at the well, gather nodes, `give_item` range, a target behind a wall (detour found, `reachability="exact"`; the capped planner mislabels it blocked),
a sealed target (`unreachable`, `exact` thanks to the reverse search), perception radius, and that no read changes the tensors or the inventory state (digest). Synthetic cases cover
`no_room` (recipient pack full), `no_item`, `self_target`, malformed arguments, out of range, wall in range, station, tool, output room, portal routes, the approximate fallback and the cache.

### 10.3 Cost (measured, MEASURE mode, `python at_the_beginning/systems/affordance/bench.py`, 8 residents, tick 200, 100 runs; raw `.runtime/bench_affordance.json`)

| call | p50 | p95 | p99 | max (ms) |
| --- | --- | --- | --- | --- |
| `observe` (one resident) | 0.52 | 0.90 | 1.33 | 1.33 |
| `options` (all verbs, one resident), warm reach cache | 2.13 | 3.09 | 5.54 | 5.54 |
| `options`, cold reach cache | 26.2 | 36.5 | 76.2 | 76.2 |
| `mask` for the 8 residents, warm | 10.1 | 15.4 | 18.5 | 18.5 |
| `mask` for the 8 residents, cold | 56.8 | 65.2 | 79.0 | 79.0 |
| `commission_options` | 0.36 | 0.43 | 0.51 | 0.51 |
| one detour search (`plan_path`, cold) | 6.8 | 11.7 | 11.7 | 11.7 |
| a search that exhausts its budget (forward + reverse, both capped) | 30.8 | 37.4 | 37.4 | 37.4 |

The cold cases are dominated by `plan_path` calls (about 4.6 ms each on this 1056 x 480 map, most of them to reach a door portal because house walls block straight lines). Scaled
linearly, a cold mask for 100 residents would be about 0.7 s, so this layer must run on decision events and not every tick; nothing in the engine calls it. The early exit (`first_only`
in the mask path) took the cold 8-resident mask from 161.6 to 56.8 ms. Not done, and the obvious next step if the mask has to be cheaper: label connected components of the movement
contract once per revision (flood fill on a coarse grid) so "reachable?" becomes a table lookup and `plan_path` runs only for the option that is chosen. Done in step 5, see 10.7.

### 10.4 Step 3 results: the Tier 1 feature builder (`systems/decision/features.py`)

**What it is.** `build_features(world, services, residents) -> FeatureBatch(ids, X float64 N x 26, P N x 16, alive, tick, schema, timing_ms)`. Columns are the matrix menu's `FEATURES`
in the same order (so the placeholder weights apply unchanged); `FEATURE_SCHEMA_VERSION = 2` versions the *definitions* in `FEATURE_DEFS` (version 1 was the synthetic
`matrix.population_features`); `COLUMNS_SCHEMA = 1` is the matrix weights file key and is asserted equal. Differences from the section 6 plan: it returns a `FeatureBatch`, not a tuple;
`services.hostile_count` (new, read-only) supplies `near_danger`; relationships are read from the record of the resident itself.

**Vectorised vs Python.** Needs, positions and "who is near whom" come from one read of the humans table and one batched distance matrix (N x all humans); the record-based columns (pressures,
goals, plans, relationships, pack, anchors, sites) are a Python loop per resident. Measured scaling below says the Python part dominates: it is the first thing to restructure
if X has to be built for ~100 residents every decision cycle.

**Perception bound (tested).** A row uses: the resident's own tensor row, own record, own pack, own roster anchors/sites, other residents within 96 units (counts, nearest one's closeness
and rival tag, taken from the *resident's own* relationships), predators within 120 units. A test moves a second resident out of range, changes its needs, record, pack and relationship
to the first, and asserts the first resident's row is bit-identical; moving it into range changes the row. Dead or unknown residents get an all-zero row except `one` (and the tensor needs of a
dead one).

**Tests** (`tests/test_decision_features.py`, 18, real booted engine): finite and in range for the 8 residents, `closeness` in [-1, 1] and negative closeness survives, reproducible in one
process and across two seeded boots (bit-equal), needs columns follow the tensor, pack/place/station/time-block columns, dead/unknown rows, read-only (tensors, inventory and records
unchanged), the matrix accepts the batch with the affordance mask, shadow helper deterministic and serialisable.

**Cost** (MEASURE lock, `python at_the_beginning/systems/affordance/bench_features.py`, tick 200, 200 calls; raw `.runtime/bench_features.json`):

| call | p50 | p95 | p99 | max (ms) |
| --- | --- | --- | --- | --- |
| `build_features`, 8 residents | 2.37 | 3.21 | 4.98 | 5.47 |
| the same 8 residents repeated x12 (96 rows; scaling probe only, not 96 distinct residents) | 31.9 | 36.0 | 39.9 | 40.6 |

That is about 0.3 ms per resident and linear, so ~30 ms for 100 residents per call: fine per decision cycle, not per tick. Matrix `decide` for 8 rows: 0.5 ms; mask for 8 residents inside the
shadow loop: 17.9 ms mean. I make no claim about a target.

**Shadow report** (`features.shadow_compare(engine, ticks, sample_every, perturb_seed)`; test-harness only, not called by the engine tick, no flag). Compares the matrix choice (placeholder
weights, hash `67c16468...`, masked by the affordance engine) with the Stage 1 survival rules (`survival_task_specs` mapped to eat/drink/sleep/go_home/flee):

* **Unperturbed seeded run, 600 ticks, 16 samples x 8 residents:** the rules never speak (no resident reaches a need threshold in 600 ticks), so there is nothing to agree with. The matrix
  chose `work_at_station` 106, `socialise` 12, `idle` 10 times; 0 rows would escalate through the gate.
* **Stress states** (50 seeded draws x 8 residents = 400 states with hunger/thirst/stamina/hp/threat drawn from a seeded generator): the rules spoke in 310; the matrix agreed with the rules
  in **51.6%** of those. Disagreements are not errors of either side yet - the placeholder `W` is hand-set - but they are the evidence for what the weights must learn: `drink->eat` 69
  (thirst first in the rules, hunger first in the matrix), `drink->rest` 18, `flee->defend/eat/drink` 28 of 50, `go_home->eat/defend/drink` 27 of 30, `sleep->rest` 17 of 17.
  `rules_choice_illegal` was 0 in the single-seed run.
* Rules decide by fixed priority (threat/flee first); the placeholder matrix mixes drives linearly, so a threatened resident that is also hungry is a place it diverges. Nothing here says the matrix is wrong.

**Not done in step 3:** no engine hook (default OFF, as asked); no trained weights; no feature for `plan_step_failed` beyond `planning_state.review_needed`; `near_food`/`near_water` use the
roster sites and tensor resources only (the authored village has none, see G-005); `is_night` is dusk 0.5 / night 1, not a per-resident circadian value.

### 10.5 Step 4 results: the 17 S1 verbs on the 8 roster residents of the real engine (evidence for D-008)

Measured with `tests/test_actions_roster.py` (real booted `starter_village`, seeded) and two scratch exploration runs; every row below is also an assertion, so a change in the accepted
Stage 1 build shows up as a failing test. **works** = the verb does what its name says for a roster resident; **routine** = it works only through the schedule-routine route
(`schedule.lifecycle.set_current_routine`, walked by the anchor driver) and the routine is replaced at the next schedule refresh (`DEFAULT_REFRESH_TICKS` = 120 ticks, 6 s) or time block;
**demoted** = the Action refuses with `refused:roster_driven` because the legacy task it would queue stays `active` forever and blocks the queue; **partial** = only a part works.

| verb | roster resident | what was measured |
| --- | --- | --- |
| `eat` (item in the pack) | **works** | atomic: ration destroyed (declared consumption), hunger 80 -> 60 the same tick, mood/stamina bumps as the legacy handler |
| `eat` (at a site) | **demoted** | the roster needs loop walks the resident to the campfire by itself once hunger passes the threshold (hunger 60 -> under 10 within 360 ticks, no task involved); the `eat_food` task it would queue stays `active`, `blocked_reason: food_not_found` (G-005), and queued tasks behind it never start |
| `drink` | **demoted** | same as eat at a site (`fetch_water`; the loop waters the resident); no tensor water source exists in the village |
| `rest` | **partial** | queues a `sleep` task. `_handle_sleep` walks to a safe entity within 220 units if `resolve_safe` finds one; task movement is suppressed for roster residents, so the task stays `active` and nothing beyond the roster loop's ~1.3 stamina/tick is gained. With no safe entity in range it rests in place (+12 stamina once) and completes. **Which of the two happens varied between processes because the tests did not seed the global RNGs** (`random`, `torch`; the server seeds them in its lifespan): a safe entity appears at tick 1 at a different distance each process (20 to 195 units in 8 runs, none in 2 of 8, which then completed). With `random.seed(1008); torch.manual_seed(1008)` 5 of 5 processes agree (entity at 129 units: stays active), so `RosterCase` seeds them and the test asserts the active outcome. Hash seed and clock were not isolated separately; the fix is the seeding, which makes the outcome identical in every process tried |
| `sleep` | **routine** | `set_routine("sleep")`: the gatherer walked from 140 to 42 units of its bed in 100 ticks; at the next refresh the schedule put it back to `gather` and it walked to work again |
| `flee_to` | **routine** | `set_routine("return_home")` walks it toward its sleep anchor. The legacy `flee_target` task is inert for a roster resident (rhea: still `active`, no movement in most runs, completed once; its threat decays by the instincts alone). In the village there is no safe-place resolver result either (G-005) |
| `go_to_work` | **routine** | `set_routine("work_site")`: the builder reached its work anchor (under 5 units) within 100 ticks; replaced at the next refresh |
| `work_shift` | **demoted** | builder: `build_work` stays `active`, `blocked_reason: worksite_not_found`, no movement, no output; smith: no work task of its own (works through the commission loop), refused `no_work_task` |
| `gather_resource` | **demoted** | `gather_material` stays `active`; the driver returns the gatherer to its anchor and no item is gained in 200 ticks even when standing at the node |
| `craft` | **works** | smith at the forge: 2 iron + 1 wood destroyed, 1 sword created in the same atomic apply, conservation holds (the recipe's `time_cost` is not modelled) |
| `store_item` / `fetch_item` | **works** | atomic Transfers between the pack and `village:supply_crate` (range 16 + clear line) |
| `give_item` | **works** | atomic Transfer + `gave_item` event + closeness 0.03 (giver) / 0.06 (receiver), existing relation kind kept |
| `request_item` | **works** | the asked resident's rules answer (`give` / `refuse_no_item` / `refuse_distrust` / `refuse_busy`); on `give` the asked resident gives through the same runner (two audit entries) |
| `commission_item` | **works** | `submit_request` through the record op: order created (`reserved`), the smith's rules provider accepted |
| `greet`, `chat` | **partial** | event + closeness (+0.02 / +0.03) work; the `talk_to_target` task would stay `active` (task movement suppressed, the target is walked elsewhere), so no task is queued for a roster resident |
| `follow` | **demoted** | `follow_target` stays `active` with no movement; refused |

Summary: 7 verbs fully usable (eat from the pack, craft, store, fetch, give, request, commission), 3 only through the routine route (sleep, flee_to, go_to_work), 3 partial (rest, greet, chat),
5 demoted (eat at a site, drink, work_shift, gather_resource, follow). For D-008: everything that needs a *worksite*, a *source in the world* or *the resident's own movement* is demoted
today; everything that is an item or relationship exchange works. The affordance mask still lists the demoted verbs (their predicates answer "the world allows it", not "the driver will do it"),
so a Tier 1 policy on roster residents over-offers `eat`, `drink`, `gather`, `follow` and `work_at_station` via `work_shift`; I did not change the predicates because D-008 decides what "can" means for a roster resident.
Another observation: the engine itself queues survival tasks (e.g. `fetch_water` for a thirsty roster resident) that also stay `active` doing nothing; that is Stage 1 behaviour I did not touch.

### 10.6 Step 4 results: the package

* `systems/actions/`: `catalog.py` (65 `VerbRow`s, generated from the section 2 tables; counts at step 4: 37 now / 9 glue / 19 new, 5 destructive; after batch 2: 37 / 13 / 15), `draft.py` (`ActionDraft`, `RecordOp`, `ActionRefused`),
  `runner.py` (`ActionRunner.run/plan/apply`, `ActionContext`, `ActionResult`, `RateConfig`, `RiskConfig`), `audit.py` (`AuditLog`: ring + optional JSONL), `recordops.py`
  (`EngineRecordOps`, `StaticRecordOps`, `NullRecordOps`), `plan_ops.py` (`PLAN_OPS` = the 17 S1 ids, `run_plan` mock Tier 3), `verbs/{survival,work,economy,social}.py` (17 `@action`s on their own
  `Registry`, not `DEFAULT`, so the legacy manifest tests are untouched).
* Pipeline (8 stages, section 1): schema -> grounding -> legality (the affordance predicate, one answer) -> rate/risk -> plan (pure) -> apply (atomic, `cause="action:<verb>"`) -> record ops -> audit.
  Reason codes: `unknown_action`, `not_implemented`, `invalid_arguments`, `unknown_actor`, `ungrounded_target|place|recipe|item`, `illegal:<predicate reason>`, `rate_limited`, `risk_gated`,
  `refused:<reason>` (`roster_driven`, `no_work_task`), `undeclared_item_creation`, `apply_failed`.
* D-1 as built: `World.effects.allow_item_creation` is switched on only for the duration of one apply and only when the draft declares `consumes`/`produces` that match every `src=None`/`dst=None` Transfer
  (`craft`, `eat`); restored in a `finally`. Verified by tests, including a failed apply (conservation) and a mis-declared draft.
* D-2 as built: `RecordOp("queue_task")` -> `queue_resident_task` after a successful apply; failures are reported in the audit and never roll the effects back (effects and record ops are not one transaction).
* Not done: 48 verbs have no registered Action; `from_target` of `flee_to` and `until` of `rest` are not implemented; `craft` ignores the recipe `time_cost`; no engine hook; `PLAN_OPS` are not known to `systems/planning`;
  `relationship` closeness deltas (0.02/0.03/0.03/0.06) are placeholders; `rate_limited` default (8 calls per 20 ticks per actor) and `risk_gated` default (0.6) are placeholders; the runner is not thread-safe.
* Tests: `tests/test_actions_catalog.py` (6, drift between A.2, the doc tables and the catalog, registry vs rows), `tests/test_actions_runner.py` (36, synthetic worlds incl. the Gate C table for all 17 verbs),
  `tests/test_actions_roster.py` (13, real engine).

### 10.7 Step 5 results: connected components (`systems/affordance/components.py`)

Built as the last paragraph of 10.3 asked, with one deliberate restriction. `Components(contract)` rasterises the lattice `systems.movement.pathing` plans on (cell = actor_radius/2, wall boxes inflated
by the actor radius plus the planner's tight margin), labels row runs with union-find (4-connected, the same components as the planner's no-corner-cutting 8-connected lattice) and answers `label(point)`
and `connected(a, b)`. `Reach` builds it once per contract revision (`components_for`) and uses it **only as a positive shortcut and only when the caller does not need a length**
(`check(..., need_length=False)`, which the mask uses; `options` and `resolve` still use exact lengths). Same label -> reachable, `mode="component"`, length = straight-line lower bound. A different label
or no label is **not trusted**: the search runs (the planner retries with a finer lattice and finds doors this lattice can miss, so a negative from labels alone could be a false "unreachable").
Quick answers are cached under a separate key; an exact answer serves both kinds of question. It imports the private pathing helpers `_contract`, `_inflate`, `_segment_hits`; if they change, the
import fails and `Reach` silently keeps searching.

Measured with `bench.py` (MEASURE mode, 8 residents, tick 200, 100 runs; raw `.runtime/bench_affordance_step5.json`; the step 2 numbers are in 10.3):

| call | before (exact lengths) p50 / p95 / p99 | after (components) p50 / p95 / p99 |
| --- | --- | --- |
| `mask`, 8 residents, cold reach cache | 55.4 / 66.7 / 75.6 ms | 13.8 / 20.1 / 23.4 ms |
| `mask`, 8 residents, warm | 9.8 / 14.0 / 18.0 ms | 9.9 / 13.5 / 18.0 ms |
| one detour question, cold | 6.8 / 11.9 ms (search) | 0.16 / 0.19 ms (component) |
| a search that exhausts its budget (sealed pocket in a big map) | 29.9 / 32.1 ms | unchanged: a negative is still decided by search |

First build of the labels: 2.5 ms on the 1056 x 480 starter village (4 components). `mask(exact=False)` equals `mask(exact=True)` on the real engine for the 8 residents (bench) and for 6 scattered placements
(test). The warm mask is unchanged because the remaining ~10 ms is predicate work, not reachability. Scaled linearly, a cold mask for 100 residents is now about 0.17 s instead of 0.7 s.
Not done: negative answers from labels (they would need the planner's finer-lattice retry); the exhausted-budget case is not faster; `options` does not use the shortcut (it needs lengths for `distance`).
Tests: `tests/test_affordance_components.py` (15: synthetic door / sealed pocket / narrow gap / closed door, quick vs exact on 1600 random pairs, quick/exact cache separation, one build per revision,
fallback without the planner internals, portal legs, real-map mask equality).

### 10.8 Follow-ups after acceptance (H-Q1 permit, D-008 driver table)

* **H-Q1 adopted.** The runner no longer toggles `World.effects.allow_item_creation`. It builds `ItemPermit(consume={item: sum}, produce={item: sum})` from the draft's `consumes`/`produces` (quantities summed per item)
  and calls `world.apply(effects, atomic=True, cause="action:<verb>", items=permit)`; no permit when the draft declares nothing. Plan time still checks every creating/destroying Transfer against the declaration (stable code
  `undeclared_item_creation`); the harness now adds the sum cap (`consume_over_cap`, reported as `apply_failed` with the skip reasons; tested with two Transfers that each match but together exceed the declaration). `eat` is registered
  with `consumes=EDIBLE_ITEMS`; `craft` is not (its items depend on the recipe, so the manifest cannot list them statically).
* **D-008 mask honesty (data only).** `systems/affordance/driver.py` + `config.DRIVER_MODE = "roster"`: while the mode is `roster`, a resident with `record["roster"]` gets `roster_driven` instead of ok for `drink`, `work_shift`,
  `gather_resource`, `follow`, and for `eat` when the food is at a site or a resource (`detail["source"]` is `site`/`entity`; eating from the pack stays legal). It is applied by the engine after the predicate answers (no predicate
  edits, no engine hook) in `options`, `legal`, `resolve` and `mask`, so the runner and Tier 1 get the same answer. `AffordanceEngine(driver_mode="agent")` or `config.DRIVER_MODE = "agent"` turns it off. Consequences:
  the runner now answers `illegal:roster_driven` for those verbs (the verbs' own `refused:roster_driven` gate stays as defence and is tested with an agent-mode engine); `work_shift` of the smith is also `illegal:roster_driven`
  (`no_work_task` is only seen in agent mode); for roster residents the `gather` and `drink` macros offer nothing, `eat` offers only pack food, and `socialise` falls back to `chat`/`greet`.
  Default stays `roster` until the user decides D-008. Tests: `tests/test_affordance_driver.py` (6) plus the three real-engine tests in `test_affordance_engine.py` which now assert both modes.


### 10.9 Per-step scheduling of a Tier 3 plan (`systems/actions/plan_cursor.py`)

`run_plan` sends every step through the runner at once. That is correct for instant steps and wrong when a step queues a legacy task (the next step is judged before the task has done anything). `PlanCursors` is the on-mode path of the Tier 3 escalation (`./tier3.md` section 4): one cursor per resident, the next step starts only when the previous step's task has left the resident's queue.

* A step runs through `ActionRunner.run` (schema, grounding, legality, rate/risk, audit), `proposer="tier3"`.
* Waiting: the record-op result of `queue_task` carries `task_id`; the cursor watches `record["tasks"]` and reads `task_state.last_completed_task` for the outcome (`completed` -> next step; any other outcome -> abort `task_<outcome>`; id gone without a record -> go on, the runner judges the next step anyway). `set_routine` steps (roster residents) have no task to watch and wait `routine_wait_ticks` (60, placeholder). Instant steps chain in one `advance` (at most 8).
* Aborts with a stable reason, event returned from `advance` and counted `run:failed:<reason>` / logged `tier3_run`: `step_<i>:<runner code>`, `timeout` (`task_timeout_ticks`, 400), `task_<outcome>`, `stale_epoch` (world epoch or model epoch changed: world reset, switch toggled), `superseded`, `runner_replaced`, cancel.
* `StaticRecordOps` now gives queued tasks an `id` and has `finish_task(actor, id, outcome)` (the engine's shape) for synthetic worlds. Tests: `tests/test_actions_plan_cursor.py` (9).
* Not done: a plan whose later step needs a different resident (trade, give) is judged by the runner when it comes up and aborts if illegal; there is no re-planning from the abort (the resident returns to Tier 1 and may be escalated again after the 100-tick cooldown). `routine_wait_ticks` is not measured. Real roster-engine behaviour of waiting on task ids was exercised only through the escalation smoke, not a dedicated test.


### 10.10 Verb batches beyond the first slice (WS-E, item 3 of R3-NEXT)

The 48 catalog rows without an Action are registered in batches of about 10, S-1..S-5 first. A batch is one commit: the Actions, the `s1=True` flip of their catalog rows, a Gate C table entry for each verb in `tests/test_actions_runner.py`, roster-engine tests in `tests/test_actions_roster.py`, and a line here. A verb whose power needs an engine edit is not registered; it is listed as [GAP] below.

Batch 1 verbs: `seek_shelter`, `hide`, `attack`, `avoid`, `warn`, `ask_for_help`, `comfort`, `explore_toward`

Batch 2 verbs: `offer_trade`, `accept_trade`, `steal_when_safe`, `share_news`, `gossip`

| verb | file | what it does | roster resident | notes |
|---|---|---|---|---|
| `seek_shelter` | `verbs/survival.py` | roster: `set_routine("return_home")`; others: legacy `seek_shelter` task | routine | |
| `hide` | `verbs/survival.py` | `wait_in_hiding` task, `hold_ticks` 8 (placeholder = legacy default) | task | |
| `attack` | `verbs/conflict.py` | `attack_target` task; **destructive** (risk gate, never offered to a model unless `GateConfig.allow_destructive_ops`) | `illegal:roster_driven` | added to the driver `ALWAYS` table |
| `avoid` | `verbs/conflict.py` | `retreat_from_target` task | `illegal:roster_driven` | added to `ALWAYS` |
| `warn` | `verbs/conflict.py` | event; non-roster also a `warn_target` task | event only | new predicate binding `can_talk` |
| `ask_for_help` | `verbs/social.py` | `call_for_help` task (completes by itself) | task | |
| `comfort` | `verbs/social.py` | `comfort_target` task (non-roster) + closeness +0.05 | event + closeness | like `greet` |
| `explore_toward` | `verbs/exploration.py` | `move_to_place` task | `illegal:roster_driven` | added to `ALWAYS` |

* Walking verbs (`attack`, `avoid`, `explore_toward`) are demoted to `roster_driven` for roster residents because the roster driver owns their movement (D-008, section 10.8). Measured (`test_actions_roster.py`, 80 ticks): a `move_to_place` task to a point 20 away stays active and the resident ends far from the goal; `attack_target` stays active; `retreat_from_target` completes in ~20 ticks but on the same path the driver walks (to the resident's own anchor), so it proves no avoidance. This changes the Tier 1 mask of roster residents: those macros are now illegal for them while `driver_mode="roster"`. Agent mode is unaffected.
* D-005: `FROZEN_LEGACY` (`instinct_frontier_expand`, `tool_expand_world_edge`) is not in the catalog; the runner, `plan_adapter` (both directions) and `gate_plan` answer `legacy_frozen` if a tier names one (`tests/test_actions_frozen.py`, 5).
* Skipped: `defend` (`guard_area` is open-ended; the cursor waits for the task to leave the queue, so a plan step could never finish) - [GAP] until a bounded guard task exists or the cursor learns a hold time.
* Not done: the remaining verbs of the 48 (economy/trade S-1, craft S-3, traveller S-2, instincts S-5); durations and priorities above are placeholders copied from the legacy task defaults.

## 10.11 Agent-driven residents: measured behaviour and open sites (agent twin, `tests/test_actions_roster_agent.py`, `tests/test_roster_agent_counts.py`)

Same eight residents, every binding `driver == "agent"`. Differences from the anchor residents of 10.5/10.10 (measured):

* No `roster_driven` demotion: `drink`, `work_shift`, `gather_resource`, `follow`, `attack`, `avoid`, `explore_toward` are judged by the world alone (the affordance driver table keys on `is_anchor_driven`).
* `eat` / `drink` at a site return a `site_trip` RecordOp: the roster needs loop's own trip is started now (no task). `sleep`, `flee_to`, `seek_shelter`, `go_to_work` use the `set_routine` route (`ctx.has_anchors`); the agent driver's Tier 1 reads the routine and walks (100 ticks to home / work in the tests).
* `greet`, `chat`, `comfort`, `warn` queue their task (`ctx.is_roster` is "anchor-driven", so an agent resident takes the task branch, and the agent driver yields while a task is queued or active). These four sites intentionally stay on `is_roster`; the routine route is not meaningful for them.
* **Fixed (authorised by c3, S5):** `_handle_move_to_place` used to resolve `place_tag` / `target_id` only and never read `target_place` {x, y}, so `explore_toward` (a `move_to_place` task with `target_kind == "point"`) roamed instead of walking to its heading. It now walks to an explicit point (`_point_target`: `target_kind == "point"` with numeric x/y; no existing caller creates such a task, every other `move_to_place` resolves as before), finishes within `POINT_ARRIVE_RADIUS` 2.0. (A first version also ended the task after 8 stalled ticks; it was removed because it changed the anchor-resident behaviour pinned by `test_the_walking_task_behind_them_is_inert_for_a_roster_resident`, where the task must stay active.) Test: `test_explore_toward_walks_an_agent_resident_to_its_point` (stands within 6 of the point after the task completes) and `test_move_to_place_without_a_point_target_is_unchanged`.
* Interrupts (`agent_driver.py`): signature `(routine, commission override, (threat >= 30, HP dropped >= 10 since the last tick))`; a change re-scores that resident on the same tick, otherwise every `EDEN_AGENT_DECIDE_PERIOD` (10) ticks staggered by slot. `status()` reports `prior` (100.0), `prior_strength`, `decided`, `interrupts`. "A hostile enters perception" has no separate signal: it shows as THREAT.
* Roster counts under the agent driver: `anchor_driven_slots == 0`, `roster_slots(engine, "agent") == 8`.

### Slot holders (pre-list for the P5 uid / AbsPos change)

Nothing in the Model plane stores a tensor slot across ticks. Everything below looks the slot up per call from the uid:
`agent_driver.py` (`roster_slots` per tick; `Row.slot` is transient; caches keyed by human uid: `cache`, `last_goal`, `last_hp`), `plan_cursor.py` (keyed by uid / plan id), `affordance/services.py` (`_entity_uid_by_slot` read per call, `interaction_boxes` cached per tick), `decision/features.py` (`table.slot_of(uid)` per batch), `tier3/escalation.py` (`_human_slot_for_id` per resident per sweep; digests keyed by uid), `runner.py` (`table.slot_of(actor)` per run). One fallback that invents an id from a slot: `affordance/services.py:238` uses `f"slot:{s}"` for an entity without a uid; it is a display id, never stored. The decision cache of `MatrixTier1` is keyed `(id(engine), world_epoch)`, not by slot. The `slot` words in `model_server` / `modelplane/switch` are model-tier slots, not tensor slots.

## 10.12 Resource-node verbs (G-005, behind `EDEN_MAP_RESOURCES=1`)

Two Actions wrap the Harness effect builders of `harness/resources.py` (`systems/actions/resource_verbs.py`):

| Verb | Predicate | Wrapper |
|---|---|---|
| `eat_from_node(node)` | `can_eat_from_node` | `ActionDraft(d.effects, d.event, [], d.preview)`; creates and destroys nothing (hunger -20 floored at 0 while hunger > 20, node food -min(food, 1)) |
| `gather_from_node(node, qty=1)` | `can_gather` | `ActionDraft(d.effects, d.event, [], d.preview, produces=d.produces)`; the runner builds `ItemPermit(produce={item: qty})` from `produces`; stock removed == items created |

* Not part of the 65-verb vocabulary (`tests/test_actions_catalog.py` pins that set and `REGISTRY.actions == S1`): they sit on their own `RESOURCE_REGISTRY`. A runner built without an explicit registry reads `default_registry()` **per call**: the S1 registry while the flag is off, S1 + these two while it is on. A runner given a registry uses it as is (tests assign `runner.registry`).
* Legality: the predicates call the builders, so they cannot disagree with the effect: a node is a resource-node row (type 27); the actor must stand within the node's radius + 1.0 (`harness.resources.REACH`); refusal reasons map to the affordance vocabulary (`not_a_node`/`empty` -> `no_source`, `not_edible` -> `no_edible`, `too_far` -> `out_of_range`, `not_hungry` -> `not_needed`, `bad_qty` -> `invalid_params`, `no_room` -> `no_room`) with the builder's reason in `detail.node_reason`. With the flag off both answer `not_wired` and enumerate no candidates, so the default mask and the golden are unchanged.
* Tier 1: `MACRO_VERBS["eat"]` gains `eat_from_node` after `eat`, `MACRO_VERBS["gather"]` gains `gather_from_node` after `gather_resource`. A node is a candidate only in reach.
* `ID_PARAMS["node"] = "target"`: a hallucinated node id is `ungrounded_target`.
* NOT done: walking to a node (legal only in reach, like `craft` at the forge; the `move_to_place` point task now exists, so an "approach" step can be added), `fish` / `farm_tend` as separate verbs, a plan-op mapping for the two verbs (`PLAN_OPS` is the 17+batches S1 set), selling or storing the gathered items.

## 10.13 `EDEN_AGENT_ACTIONS` (default off) and the window re-base callback

**Actions through the runner** (`systems/actions/agent_driver.py`, commit 96ccc7a). With the flag on, Tier 1 macros that are not plain routine or site goals are resolved with `AffordanceEngine.resolve` and run through `ActionRunner` (`proposer = tier1:<provider>`); routine and site goals stay on `AnchorMover`. Rules action layer: eat from the pack at the trip threshold when edible food is carried, `rest` (the sleep task) when stamina <= 40 and no threat, greet/chat at the `talk` anchor on a socialising routine (300-tick cooldown). A refused or unresolved macro is counted (`none:<macro>` / `<verb>:<code>`) and cooled down for 20 ticks. Flag off: the driver is untouched (strict golden, default and `--resources`: no drift, 11 checkpoints).
Measured, `model_server.tier1_acceptance --compare --actions --ticks 2400`: 9 audit entries (chat 5, eat 4), 0 rejections, identical for rules and matrix (final positions equal); commission ready 2063 / delivered 2064, the same as flag-off; max thirst 55.58 (bound 60), max hunger 44.45; idle 0; decisions 0.43/tick. `none:eat` 18 (no edible food in the pack, the trip happens) and `none:socialise` 10 (nobody in reach). `rest` did not fire in the day (stamina stayed above 40).

**Re-base callback** (`systems/actions/rebase.py`, `rebase_model_plane(engine, dx, dy) -> {holder: count}`). `dx`/`dy` are added to window-local coordinates; only `H_SPACE == 0` residents move; `dx = dy = 0` is a no-op. Called by the window manager after the tensors and the map contract are shifted, before the next step hook. Holders: `roster_final_positions`, `roster_checkpoint` (tensor rows), `mover_plans` (goal and waypoints; keys `uid` and `("task", uid)`), `mover_no_path` (goal), `record_positions` (`target_place` / `ambush_anchor` dicts under tasks, task_state, goals, schedule records, and `memory.last_threats` x,y), `driver_goals` (`AgentDriver.last_goal`). Held no positions (checked): needs trips, plan cursors, Tier 3 digests, the decision cache. Not shifted: event / memory history, audit-log params; resource memory is the window manager's. Test: `tests/test_rebase_model_plane.py`.


## 10.14 Approach-the-node and S-1 batch 2 (R4-ASSIGN item 1)

**`approach_node`** (not a catalog verb; on `RESOURCE_REGISTRY`, flag `EDEN_MAP_RESOURCES=1`). Params `node`. Legal (`can_approach_node`) when the node row has stock (food + node_stock > 0), is not burning, is within `RADIUS["resource"]` and **outside** its reach (`scale + REACH`); in reach it answers `in_reach` (use the gather / eat verb), with the flag off `not_wired`. Effect: a `move_to_place` point task to the node centre (`metadata.node`); on arrival the node verbs are legal (tested on the real engine: walk, then `gather_from_node`). Offered by the `gather` macro after `gather_resource` / `gather_from_node`; in `driver.ALWAYS` (a roster-driven resident is refused `roster_driven`: its movement is the anchor driver's); in `ROUTABLE_VERBS`.

The five verbs of batch 2 (listed at 10.10): `offer_trade`, `accept_trade`, `steal_when_safe`, `share_news`, `gossip` (rows flipped to `s1`; `offer_trade`, `accept_trade`, `share_news`, `gossip` go `new` -> `glue`, counts 37 / 13 / 15). None reads another resident's pack or memory in a predicate (Observation's rule); the other side's facts are judged by its own rules at op time or by the Action (`refused:<reason>`).

| verb | file | what it does | roster resident | notes |
|---|---|---|---|---|
| `offer_trade` | `verbs/economy.py` | opens an offer in the services' `OfferBook` (60-tick life); the asked resident answers by `respond_to_trade`: `accept`, `refuse_distrust`, `refuse_busy`, `refuse_no_item`, `refuse_needs` (hungry >= 50 keeps an edible against a non-edible), `refuse_unfair` (value received < 0.9 x value given up, `item_kind_def.value`); on accept the swap runs as `accept_trade` by the asked resident (`proposer rules:trade_response`) | works (instant) | params `target, give, want, give_qty?, want_qty?`; `give` / `want` are grounded as items |
| `accept_trade` | `verbs/economy.py` | `offer_open`: the offer exists, is addressed to the actor, not lapsed, giver in interaction range, both packs and rooms re-checked; two `Transfer`s in one atomic apply, closeness +0.03 both ways, offer closed | works | an addressed resident (Tier 2/3) may also call it directly |
| `steal_when_safe` | `verbs/conflict.py` | `can_steal`: exactly one of `target` / `container`, in interaction range, **no other living resident within help range (72)** (`illegal:watched`); the Action refuses `refused:no_item` when the owner lacks it (a resident's pack is not visible to the predicate; a container's is); one `Transfer`, a `theft` ledger event seen only by thief and owner (`private`: the owner does not learn who) | works (instant, no movement) | **destructive** (D-3): `risk_gated` for any proposer but `rules*` unless confidence >= 0.6; not in `MACRO_VERBS` (the `attack` macro is unchanged) |
| `share_news` | `verbs/social.py` | `knows_event`: the actor witnessed the ledger event, the listener (in social range, reachable) did not; the listener becomes a witness of the **same** event id (an idempotent `Emit(event_id=...)`), a `heard_news` memory entry, closeness +0.02 both ways, a private `shared_news` event | event + memory + closeness (like `greet`) | new id kind `event` (`ungrounded_event`) |
| `gossip` | `verbs/social.py` | the latest event the actor witnessed that involves `about` and the listener did not see; as `share_news` plus the listener's closeness to `about` moves by half the teller's, capped 0.05 per telling | same | `about` grounded as a resident |

* `MACRO_VERBS` only appended (`trade` + `offer_trade`, `accept_trade`; `socialise` + `share_news`, `gossip`), so the resolution order of the existing verbs and the Tier 1 mask columns do not change. The Tier 1 rules do not choose these yet.
* Tests: `tests/test_actions_s1_batch2.py` (15, synthetic Scene), `Batch2Roster` in `test_actions_roster.py` (3, real engine), the five Gate C rows in `test_actions_runner.py` (the Scene now carries ledger event `ev_000001`), `ApproachNode` in `test_actions_resource_verbs.py` (4), counts in `test_actions_catalog.py`.
* NOT done: `buy` / `sell` / `set_price` / `pay_debt` (no market), a Tier 1 rule that offers a trade or begs, a reputation consequence of a witnessed theft, a `refuse_busy` test (the synthetic table has no `threat` column), a plan-op mapping for the node verbs, `defend`.

## 10.16 Bonds and place memory (`EDEN_BONDS`, `EDEN_PLACES`; both default off, need `EDEN_AGENT_ACTIONS`)

Seven more catalog verbs, on their own flag-gated registries (`bonds_verbs.BONDS_REGISTRY`, `places_verbs.PLACES_REGISTRY`, added by `resource_verbs.default_registry()` like market/credit/labour/justice), with predicates in `affordance/bonds_predicates.py` and `places_predicates.py` (flag off: `not_wired`, no candidates, not registered; the S1 `REGISTRY` and the catalog pin are untouched).

| verb | predicate | effect | notes |
|---|---|---|---|
| `befriend(target)` | `can_befriend` (in talking range, neither side below -0.2, the weaker closeness under 0.6) | both closeness +0.05 | stops at the cap: `not_needed` |
| `court(target)` | `can_court` (both >= 0.1, not kin, both under 0.85) | both closeness +0.04 | courtship without mating; the mating tasks are untouched |
| `apologise(target, event?)` | `has_harmed` (the target holds a grudge, closeness <= -0.05, in range) | the listener's closeness moves toward 0 by `0.12 x (0.5 + mercy)`, halved for a grave grudge (< -0.5) and halved again against a `thief` tag; never past 0 | never makes a friend; the thief tag stays until restitution or time (reputation pass) |
| `forgive(target)` | `has_grudge` (the actor's own closeness <= -0.05; no proximity needed) | the actor's closeness moves toward 0 by 0.15, never past it | the reputation pass drops a `thief` tag when closeness reaches 0 |
| `mark_place(name)` | `can_move` (non-empty name; the mask lists no candidates) | the actor's position under that name in `record["known_places"]` | at most 16 places per resident, the oldest is forgotten |
| `remember_place(place)` | `perceives` (an anchor, site or entity in view; the runner grounds the id) | the perceived place's position under its id | the mask offers up to 6 unknown perceived places |
| `ask_directions(target, name)` | `can_talk` (in range, the name not already known) | the **asked** resident answers by rules at op time (`places.answer_directions`: it must know the place and not hold the asker below -0.2); a yes copies the place (`source: told`) and moves both closeness values +0.02 | a refusal is an op result (`refuse_unknown` / `refuse_distrust`), the call itself is ok |

* **Where the state lives.** Bonds only change the two relationship records (the state reputation, credit and labour already read). A known place is `record["known_places"][name] = {"target_place": {"x", "y"}, "space", "tick", "source"}`; `rebase.RECORD_FIELDS` gained `known_places`, so the existing re-base walk (key `target_place`) shifts remembered places with the window (test: `test_places.Rebase`, `test_bonds_day.Places`). Nothing reads the memory for movement yet.
* **Who uses them.** `actions/bonds_day.py` (called from `AgentDriver.step` every 60 ticks, no-op with the flag off) lets residents who already stand within talking distance, calm (hunger/thirst < 60, threat < 30), awake and not on an errand: forgive (mercy >= 0.5; a thief only at >= 0.7), apologise (conscience > 0.1), befriend (sociability > 0.5) or court (both fond, the more sociable of the pair), in that order, one verb per resident per pass, each pair-verb on a 600-tick cooldown whatever the outcome. No errands: people bond when they meet. Places have no rules consumer yet (Tier 2/3 and the explore macro, later).
* **Tests.** `test_bonds.py` (rules, verbs on the synthetic Scene, flag off), `test_places.py` (names, cap, directions, verbs, re-base, flag off), `test_bonds_day.py` (real engine: the pass, cooldown, hunger/range/off-period, dormancy, record ops, re-base of a mark, asking between two residents).
* **Not done (listed honestly).** `teach` (`H_SKILL` is one scalar; needs a skill list), `invite` (needs an invitation object and acceptance, like the offer book), `reflect` (memory consolidation is a Tier 2/3 job; there is no consolidation system), `light_fire` and `repair` (need fire / damage state in the engine), `settle_site` and `migrate_group` (need a settlement object), `arrest_or_restrain` and `defend` (see `./defend_design.md`; `arrest` can now use the Phase 1 restraint flag).

### 10.17 Which remaining catalog verbs can wrap a legacy task today (probe, agent residents, starter village, 120-400 ticks; `scratchpad/probe_tasks.py` queues the task for an agent resident and steps the engine)

| task | result | consequence for the verb |
|---|---|---|
| `scout_area` | completes in 7 ticks, no item or position change | `scout_region` is a trivial wrapper with no world effect; not registered until a consumer exists (place memory could take the perceived places) |
| `fish_work` | active, blocked `missing_fishing_rod`; with a rod: `water_not_found` in the village (no water entity of the kind it wants) | `fish` = `gather_from_node` on a fish node (`EDEN_MAP_RESOURCES`, item `fish_catch`) already exists; a separate task wrapper would need the rod + a water entity predicate that mirrors the task's own search |
| `hunt_work` | active, blocked `missing_spear` | `hunt` waits for the creature table (`huntable`, `loot`, `creature_killed`): then it is a verb over the table, not over this task |
| `farm_work` / `build_work` | active, blocked `worksite_not_found` | worksites come from the map (`work` anchors); `work_shift` already starts the occupation's task. `farm_tend` / `build_structure` need a plot / site predicate that mirrors the task |
| `help_target`, `warn_target`, `escort_target`, `challenge_target`, `report_crime` | active (walking toward the target in the task system; none ends without the target reacting) | `treat_wound` waits for 9d882a's wound fields (a direct bandage-for-HP effect is simpler than the task); `report_crime` is covered by `report_theft` (justice); `threaten` has no fear mechanic |

So the rest of the catalog needs an engine-side fact first (tool or worksite predicates, creature table, wounds, fire/damage state, settlements, skills); none of them is blocked by the model plane. They are listed with their blockers in 10.16 and are taken up as those facts land (creature table, wounds).

### 10.18 Guard posts: `defend` (`EDEN_DEFEND`, default off, needs `EDEN_AGENT_ACTIONS`; Phase 0 of `./defend_design.md`, on top of 9d882a's Phase 1 hook)

* **The verb.** `defend(target)` (a person in talking range) or `defend(place)` (an anchor, site or entity the actor perceives; exactly one) on `guard_verbs.GUARD_REGISTRY` (added by `default_registry()`; S1 `REGISTRY` and the catalog pin untouched). Predicate `can_defend` (`predicates.defend`, which delegates to `affordance/guard_predicates.py` with the flag on; flag off it keeps its S1 verdict and the `[{}]` candidate, and a call with a parameter answers `not_wired`). Illegal: dead, hp < 30 (`too_hurt`), already guarding (`already_guarding`), self (`self_target`), both or neither parameter (`invalid_params`), unperceived place (`not_perceived`). Reversible. The op `post_open` is run by the `ActionRunner` on the services' guard book (`systems/guard`); the person guarded holds the guard 0.03 dearer.
* **The post.** One per guard, `GUARD_TICKS = 600` (a quarter game day). Runtime state only: the book lives on `services.__dict__`, a post stores resident ids and place ids, never coordinates (a place post's position is read from the services every tick, so the re-base cannot stale it). Closed with a reason: `expired`, `guard_down`, `dormant` (a dormant guard loses the post, it is not frozen), `needs` (hunger or thirst >= 60: a guard on an errand is not served by the ladder, so it is released before it can starve), `charge_gone`, `lost` (place no longer resolvable).
* **The shield.** `guard_day._install` sets `systems.combat.modifiers.COMBAT_MODIFIER` once (never over another model's hook; `driver.routed["guard.hook_taken"]` counts that case). `systems/guard/modifier.py`: for an attack on a human, the first open post (by id) over that person, or over a place within 40 of them, whose guard is alive, awake, not restrained, hp >= 30, within 40 of the person and not the attacker takes the blow instead at 0.6 of the damage; the threat still lands on the original target; the blow is recorded in the book. Deterministic, no randomness, no tensor writes.
* **The pass** (`actions/guard_day.py`, from `AgentDriver.step` every tick, a no-op flag off): tend posts; every 10 ticks answer fresh blows and let the rules open posts. Rules: a free, calm, healthy resident (not on an errand, hp >= 30, hunger/thirst < 60, own threat < 30) who is an authority (`law.is_authority`) or protective (>= 0.6) stands guard over the nearest resident under threat (>= 30): an authority over anyone it does not distrust (closeness >= -0.2), a protective resident only over someone it holds at >= 0.5; at most 4 new posts per pass; a failed attempt cools down 300 ticks per (guard, charge). The guard walks (ladder purposes `guard` / `guard_place`, both in `rebase.FOLLOWING_PURPOSES`: the position is recomputed from the person every tick) and, in reach, calls `defend`; `ladder.arrive` then holds the errand for the watch. A post opened by the verb alone (Tier 2/3) gets a holding errand from the pass (`ladder.hold_guard`).
* **The answer.** A blow the guard took is answered once per (guard, attacker) pair per 200 ticks, within 40 ticks of the blow, unless the attacker is down (hp < 30): an authority or a fierce guard (aggression >= 0.6) calls `attack` (destructive; the `rules:` proposer passes the risk gate), anyone else `warn`s and attacks if the same attacker strikes again after the warning.
* **Not done.** The rules open only person posts (place posts are a verb choice for Tier 2/3, tested on the engine); no `rob` rung yet (it needs a victim that `can_defend` and the retaliation to be measured on the village first); `arrest_or_restrain` (9d882a's restraint flag is available); a guard hit by a creature is not mitigated (creature attacks are not offered to the hook); threat from any source (a tiger too) can start a watch, which is acceptable: the guard walks to the threatened person.
* **Tests.** `test_guard.py` (book, the hook on tensors and through the real resolver, the verb on the synthetic Scene, flag off), `test_guard_day.py` (real engine: who opens a post, installation, expiry, needs, dormancy, place posts, the answer).

### 10.19 Verb-side cap on the path-search request (`EDEN_REACH_MAX_DISTANCE`, unset = today)

`plan_path` sizes its search area from the request (30 to 500 ms for long requests, `../archive/harness_handover.md`). `Reach._compute` now skips the search when the straight-line distance to the goal is above `EDEN_REACH_MAX_DISTANCE` world units (read at call time; unset, empty, 0 or junk: no cap) and answers `ReachResult(False, "approx", "unreachable")`, the same shape a search that ran out of budget already gives; `reach.stats["too_far"]` counts it. A clear straight line, a portal hop and a connected component answer are never capped (they are computed before the search). Tests: `tests/test_reach_cap.py`. A default value is a measurement for c3 (the legal-option mask only surfaces goals inside the perception radius, so a cap of a few hundred units should change nothing for the mask and only trim long `plan_path` calls from verbs given far explicit targets).

### 10.20 Robbery and arrest (`EDEN_ROB`, default off; needs `EDEN_AGENT_ACTIONS`, `EDEN_AGENT_LADDER`, `EDEN_REPUTATION`, `EDEN_JUSTICE`, `EDEN_DEFEND`; the arrest also needs the harness's `EDEN_RESTRAINT`)

* **The rung.** `rob` is the top of the ladder (`ORDER` already ended with it; `Ladder.built()` adds it with the flag). `thresholds` gives it the highest bar (base 0.85, moved by conscience like `steal`), and `Ladder._rob` adds its own gates: conscience at or below 0.0 (`rob.ROB_MAX_CONSCIENCE`; an average resident sits near +0.03 and never robs), hp >= 50, and a victim who is awake, not a player's body (`rob.controlled`), carries edible food, is not held dear (closeness < 0.3), is within 400, has no open guard post over them and has no awake authority within 80 of them (`rob.WITNESS_RADIUS`). It goes to the nearest such resident (a following errand, purpose `rob`) and calls `rob` once; win or loss, the pair cools down 400 ticks.
* **The verb.** `rob(target, item?, qty?)` (destructive, so only the rules proposer passes the risk gate; `can_rob` lists no mask candidates): in reach, robber hp >= 50, the victim carries edible food. A contest decides it: `p = clamp(0.5 + 0.5 x (power(robber) - power(victim)), 0.1, 0.9)`, `power = hp/100 x (0.4 + 0.6 x aggression) (+ 0.35 for the victim when a guard with an open post stands in reach)`, one deterministic draw `world.rng("rob", "robber>victim")`. A win: the food moves victim -> robber (declared Transfer), the victim loses 12 hp (a victim already low can die; the engine handles death), the culprit is known at once (`reputation.record_theft(..., violent=True)`: noticed immediately, opinion drop doubled), the victim's closeness to the robber drops another 0.12; event `robbery`. A loss: the robber loses 8 hp, the victim keeps its food and holds the attempt against the robber; event `robbery_failed`. Both are `local` events within 80, so neighbours witness them.
* **The consequences are the existing pipeline.** The victim's knowers gossip and confront (`reputation`), the justice pass reports the robbery to an authority (`justice_day`), a case opens, the authority walks to the robber and levies damages (`levy_damages`).
* **The arrest.** `arrest_or_restrain(target)` (catalog verb, predicate `holds_authority`, destructive): an authority in reach of a resident the reputation book holds as a robber with a known culprit (`rob.robber_on_record`) holds them for `ARREST_TICKS = 300` through `harness/restraint.restrain` (op `restrain`, runner `_restrain`, needs the engine behind the record ops). The ladder calls it right after a successful `levy_damages` (`Ladder._arrest`, from the enforce errand's arrival and from `start_enforce` in reach), so a convicted robber pays and is held; the harness counter releases them by itself. Refused: flag off, restraint flag off (`not_wired`), not an authority, not convicted, target dormant or a player's body, already restrained. A thief who only stole is never held.
* **A stress knob.** `EDEN_LADDER_RUNGS=forage,rob` restricts the rungs tried (unset = all); `s1_commons --rob [--rungs forage,rob]` turns the whole family on (`EDEN_DEFEND`, `EDEN_ROB`, `EDEN_RESTRAINT`). In the default commons scenario the lower rungs always find something, so `rob` never fires (digests `2fbbeae222e2dbd0` / `506087d6cd7c03b7` unchanged with `--rob`).
* **Measured (commons, `--rob --rungs forage,rob --stall-rations 0 --keeper-rations 6 --family-hunger 95`, 4000 ticks, seeds 1008 / 1 / 2).** Each run: one robbery won (seed 2 also one fought off), one case opened, damages levied, the robber arrested; nobody dies, no silent starvation, no stuck errand, actions in the second half, coin and every item conserved, no errors (`verdict.pass` true).
* **Not done.** A robbery of a dormant resident is not possible by construction; a dormant robber does nothing (the ladder does not run for it). Creature attacks and guards: see 10.18. The arrest has no early release or trial; a pardon needs a judge model.
* **Tests.** `test_rob.py` (rules, verb on the Scene, risk gate, flag off), `test_rob_day.py` (engine: the rung, deterrents, errand, reporting, levy and arrest, refusals, flag off).

### 10.21 Care verbs and clothing (`light_fire` with `EDEN_TEMPERATURE`, `treat_wound` with `EDEN_WOUNDS`; both default off, need `EDEN_AGENT_ACTIONS`)

* **Verbs.** `CARE_REGISTRY` (`actions/care_verbs.py`, added by `default_registry()` while either flag is on; each predicate answers `not_wired` for its own flag off, and a services object without an engine, the synthetic Scene, answers `no_engine`). Both are reversible and declare the one item they destroy (`ActionDraft.consumes`). `light_fire(place?, fuel?)` (predicate `can_light_fire`): burns one `wood_bundle`, at the actor's spot or a perceived place within reach, when no warmth source (a map hearth or a lit fire) lies within 20; op `fire_light` calls 9d882a's `temperature.add_source(engine, x, y, ticks=1200)`. `treat_wound(target?, item?)` (predicate `can_treat`): dresses the actor's own wound or that of a neighbour in interact range (`wounds.wounded_of`) with a `bandage` (strength 1.0, stops the bleed) or a `herb_bundle` (0.6, stops 60 % of it); op `wound_treat` calls `wounds.treat(engine, uid, strength)`; a neighbour's closeness to the carer rises 0.04.
* **Clothing class.** `systems/clothing/__init__.py`: `INSULATION = {cloak: 4.0, fur_coat: 9.0}` degrees, `insulation_of(items)` (the best garment held, 0.0 for none); `cloak` and `fur_coat` are declared items (tag `clothing`, not stackable) in `inventory/schema.py`. The harness's `temperature.CLOTHING_BONUS` is still the constant scalar placeholder; the per-resident bonus is for 9d882a to read from `insulation_of` (the item class is ready; no behaviour changes until `effective_temperature` uses it).
* **The pass.** `actions/care_day.py` (from `AgentDriver.step` every 10 ticks, a no-op with both flags off; at most 6 acts a pass): a free resident dresses its own wound, else a wounded neighbour in reach it holds at >= 0.3 (any one, for an authority); a resident that is >= 6 degrees under the comfort band and carries wood lights a fire when none burns near. Both go through the ordinary verbs (legality, risk gate and audit as for a model's call).
* **Tests.** `test_care.py` (real engine: the fire and its expiry, refusals, candidates, flag off, own and neighbour treatment, herbs, reach, the day pass, clothing items).

### 10.22 Emotions and slow drives (`EDEN_EMOTION`, default off; needs `EDEN_AGENT_ACTIONS`) and the calendar day (`gameclock.day_ticks()`)

* **Where the state lives.** `record["emotion"]` in the resident's own record (saved with it; no format change, no tensor column): `last_decay_tick`, `grudges`, `grief {level, subject, since, relief}`, `mourned`, `tension {rival: 0..1}`, `drives {curiosity, thrift}`, `places`. Pure rules: `systems/emotion/rules.py`; readers `systems/emotion/__init__.py`. One cadence pass, `actions/emotion_day.py`, from `AgentDriver.step` every 60 ticks (a no-op flag off), over awake residents only.
* **Grudge decay (2.A5, P1).** Lazy and daily: when a game day (`gameclock.day_ticks()`) has passed since `last_decay_tick`, the elapsed days (at most 30) are applied at once, so a resident that was dormant catches up on waking. A negative closeness rises 0.04 a day toward 0 unless it got worse since the last pass (a new offence refreshes it for that day); a grave one (<= -0.7, tagged `grave`) rises only to -0.35 ("a betrayal never fully fades", feuds possible but not eternal); `thief`-tagged relations stay with the reputation pass (its own faster, mercy-scaled decay and the tag removal at 0). Positive closeness is never touched.
* **Grief.** A relation at closeness >= 0.5 to someone whose record says dead (`status.alive` false, set by `mark_dead`) starts a grief: level `0.4 + 0.6 x closeness`, linear fade over 3 game days, mood lowered once (20 x level, through the effects layer, bounded), a `grief` memory event. A heavier loss replaces a lighter running grief. **Comfort:** a free, calm neighbour in reach who holds the griever at >= 0.3 (the loyalty-moved threshold) calls the existing `comfort` verb (it needs the griever's mood low, so a grieving resident with an unshaken mood is not comforted); each success lifts the level by 0.12; a pair rests 600 ticks.
* **Jealousy.** A resident whose partner (mutual closeness >= 0.6, the court range) stands in reach of a third resident the partner holds at >= 0.3 builds tension against the rival (+0.1 a pass x (0.5 + possessiveness = mean of pride and vengefulness traits)); tension fades 0.25 a day; above 0.6 the resident holds the rival 0.03 less dear every pass and, in reach and calm, `warn`s (600-tick cooldown per pair). Retaliation (`retaliate`, not implemented in the catalog) is not wired.
* **Loyalty** is derived, not stored: `rules.threshold(base, loyalty_trait)` moves the closeness a resident asks before it helps or defends by +-0.15 (guard kin threshold 0.5, the care pass's 0.3, the comfort threshold). **Gratitude** is the closeness steps the verbs already give (0.03 for being guarded, 0.04 for being treated); **resentment** is the grudge.
* **Drives (2.A4, two first as the spec advises).** `curiosity`: starts at half the trait, builds `0.12 x (0.5 + trait)` a day, discharged 0.4 per newly learned place (`known_places` count). `thrift` (hoarding 1.0 to giving 0.0): pulled 0.25 a day toward `0.2 + 0.6 greed + 0.2 caution - 0.2 sociability`, and +0.1 a day while the resident carries fewer than 2 food items. Ambition, pride and territoriality are not built (the spec's own caution against knobs that make noise, not character); their hooks are `drives{}` and the instinct block.
* **Tier 1.** The instinct block is schema v3: `grief`, `tension`, `curious`, `thrifty` appended (flag `EDEN_EMOTION`); e.g. grief: rest +1.0, socialise +0.6, work -0.8, explore -1.0; curious: explore +1.6, go_home -0.6; thrifty: trade +0.6, help -0.8; tension: avoid +0.8, help -0.4, socialise -0.5. Hand weights; the base matrix and weights v1/v2 are untouched (the block is additive, `MatrixTier1.decide` adds `E @ W_ext`; a v3 weight retrain stays a deliberate later step). It acts in matrix-led modes (prior strength < 1).
* **Calendar day.** `gameclock.day_ticks()` replaces the `DAY_TICKS` constant for the market day, loans (grace), justice cases, the reputation forgiveness step (a quarter of the day) and the passes above: legacy 2400, `EDEN_CALENDAR=1` 12000; a scenario that sets `gameclock.DAY_TICKS` itself (the s1 commons and market runs use 600) keeps its value under both. Under `EDEN_CALENDAR=1` the full set of day-dependent tests passes except the market scenario subprocess run (it runs the whole world under the calendar's slower needs; tuned for the legacy day).
* **Tests.** `test_emotion.py` (pure rules; engine: lazy decay, refresh, grave floor, dormant catch-up, the calendar day, flag off, grief and comfort, jealousy, drives, loyalty, the feature columns), `test_gameclock.py`.
