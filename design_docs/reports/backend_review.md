# Backend review (own code), 2026-10-07

Scope: the code written for the 2D build, read once as a reviewer: `systems/roster/` (load, validate, apply, driver, motion, needs, install), `systems/commission/`, `systems/god/`, `systems/decision/`, `simulation/` (dispatch, portal commands), `systems/movement/` (map_contract, anchor_mover, pathing), `persistence/` (map_guard, world_snapshot), and the memory graph writer. Method: an AST pass (unused imports, public names without docstrings, `print`, TODO/FIXME), a pass for public functions nothing references, and reading the modules. No behaviour was changed except the one bug below, which was approved first.

## Fixed

| Finding | Fix |
| --- | --- |
| **Bug: the god pause and the time scale survived `Engine.reset_world`.** A New Game or a Continue started while the god had paused time began frozen at tick 0 (verified: 2 steps advanced 0 ticks in the new world). | `reset_world` clears the pause and sets the scheduler to 1x (`map_test.py`, 3 lines). `tests/test_god_reset.py` (5 tests): new world, Continue of a save made while paused at 0.5x, reconnect without reset keeps the pause, `/status` of a new world, legacy golden contract. The four behaviour tests failed before the change. |
| 5 unused imports (`commission/engine.py` order_view and all_orders, `commission/dialogue.py` COMMISSION_CONFIG and commission_facts, `decision/contract.py` Optional, `roster/needs.py` math) | removed |
| `simulation/dispatch.py` said "Two ordered hook lists" and described three | corrected |
| `RosterRuntime` counters (`trips_done`, `rations`, `trip_timeouts`, `trip_blocked`, `portal_uses`) were created on first use through `getattr` | initialised in `__init__` |
| 54 public functions and classes without a docstring (roster, god, commission entry points, dispatch, map_contract, anchor mover, snapshot, map guard, decision) | one-line docstrings added; nothing else in those files changed |

Full suite after all changes: **544 tests OK** (539 before the reset fix and its 5 tests).

## Found, not fixed

Severity: **M** = could bite a player or an operator, **L** = tidiness.

| # | Finding | Sev | Note |
| --- | --- | --- | --- |
| 1 | **A god-set weather never expired on a roster map** (verified: rain with `duration_ticks` 10 was still rain at tick 400; only `advance_nature_cycle` ended weather and it is off on roster worlds). | M | **Fixed afterwards** (approved): `systems/god/expiry.py` post-step hook, end tick in the god ledger, `tests/test_god_weather_expiry.py` (8 tests). |
| 2 | Hidden runtime state lives in `engine.__dict__` (`_roster_runtime`, `_roster_world`, `_god_paused`, `_decision_service`, `_decision_log_root`) instead of being declared in `Engine.__init__`. Only what `reset_world` names is reset: `RosterRuntime` survives across worlds (trips and `final_positions` are guarded by the world epoch; `at_anchor`, `goal_key`, `moved` keep entries of old human ids until the driver overwrites them, which it does every tick; the diagnostic counters accumulate across worlds). The decision service also survives a reset (its stale-drop uses the epoch). | L | Works, is covered by tests, but is the pattern that produced the pause bug. |
| 3 | `map_id_at` exists twice with a different fallback: `systems/roster/driver.py` (falls back to the engine's map name) and `systems/god/state.py` (falls back to `"?"`). | L | Behaviour differs only for entries without map info. |
| 4 | Unreferenced or test-only public helpers: `commission/orders.is_terminal`, `movement/map_contract.copy_entities` and `copy_anchors` (never called), `commission/lines.known_codes`, `roster/apply.clear_roster_cache`, `movement/map_contract.clear_map_contracts` and `register_map_file` (tests only). | L | Harmless. |
| 5 | Public functions still without a docstring: most of `commission/orders.py`, `escrow.py`, `facts.py`, `lines.py`, `decide.py` builders, `lifecycle` (`refuse_order`, `accept_order`, `start_work`, `complete_work`), `dialogue.order_view`, `access.human_position`, `map_contract.copy_*`, `decision/providers.DecisionProvider`. | L | The module docstrings and `../contracts/commission_api.md` describe them. |
| 6 | `print` calls: `persistence/map_guard.py` prints the notice when a changed map is allowed through the override (intended, operator-visible); `state_memoryrag.write_graph_file` prints "Saved graph" once per write (from the worker thread; the engine log is noisy at about 20 lines per game minute from `[MemoryLightRAG] Retrieved ...` as well, legacy). | L | No debug prints or TODO/FIXME markers in the reviewed files. |
| 7 | The commission order store and the god event ledger are never pruned (`inventory_state["work_orders"]`, `["god"]["events"]`). 22 KB after 90 game minutes and 4 orders; fine for sessions of hours, not for years. | L | Documented in `BACKEND.md`. |
| 8 | One smith is assumed: `find_smith` takes the first resident whose roster role or occupation is smith (or the id asked for); the hold at the forge and the `smith_at_work` check use his roster `work` anchor. Two smiths would work per order but is untested. | L | Not documented elsewhere before this file. |
| 9 | ~~A possessed resident would starve in a long session.~~ **Withdrawn, my mistake:** `instinct_incarnation_stabilize` (priority 5) pins a controlled human's HP at 100 and hunger/thirst at 0 every tick and removes him from the survival instincts, so he cannot starve. Found while building the requested ration safety net (which could therefore never trigger and was removed again). | - | Covered by a guard test in `tests/test_roster_needs.py`. |
| 10 | `Engine.step` runs on the event loop; a long step blocks every route. The soak shows 99th percentile 24 ms and a maximum of 53 ms with 8 residents on 4 maps (budget 50 ms), so there is little headroom for more residents. | M | See `./performance_report.md`. |
| 11 | Line endings: `map_test.py` is now all LF (it was CRLF earlier today); `instincts_and_tools.py` is all CRLF. Not caused by this review. | L | Expect a whole-file diff on `map_test.py`. |

## Not found

The checks run found no debug prints (apart from item 6), TODO/FIXME/XXX/HACK markers or unused imports left in the reviewed files, and no hook that swallows an error silently (the dispatcher logs and records every hook failure). **Not reviewed:** the legacy routes of `map_test.py` (`/god_decree`, `/set_map`, `/testing/*`), the HTTP layer as a whole (the session-capability rule for every POST was not audited route by route), and the legacy systems under `at_the_beginning/systems/` that this work did not write.
