# 1008 Part 2.A instinct wiring without EDEN_CALENDAR ([GAP], harness plane, design only, 2026-10-09)

Author: 8d998a ("1008latenight"). For c3's approval before any code. Scope = `./expandtools_instincts.md` Part 2.A in its order, minus what needs the calendar flag (2.A2 sleep pressure, darkness unease: blocked on the user's wording). Every step is flag-gated, default off, retires nothing. Nothing in this file changes behaviour until a flag is set.

## 1. What I read (and what it changes about the plan)

* The registry (`default_registry_entries`, priorities 5..90) holds the tick entries (priorities 5..90); `Engine.register(fn, priority=..)` can add more at boot. **Everything below can be installed from `harness/engine_hooks.py` with `engine.register`, so no edit of `instincts_and_tools.py` is needed** (the functions that already exist there are imported and registered, new ones live in harness modules).
* **The roster world ignores the steering fields.** `instinct_move` computes `noise` plus the navigation biases, then `anchor_driven_rows` zeroes the row of every roster resident ("noise and biases are off for any roster resident, whoever moves it", `systems/roster/driver.py`). The 1008 village, the golden trace (8 residents) and the s1 scenarios are all roster worlds. So wiring `instinct_survival/social/schedule_navigation`, `instinct_search` and `instinct_reproduction_strategy` is **invisible there by construction** and only matters for non-roster humans (legacy maps, god-spawned crowds, a player's companions). That makes it safe and low value; I would not spend the golden budget on it before the winter set.
* `instinct_proximity` is already reached (infection passes it as `proximity_fn`); `instinct_pairwise_relations` is rebuilt on demand by `instinct_move` and the infection pass (`_get_human_pairwise` falls back to `_build_human_pairwise`), so wiring it is a shared-cache optimisation, not new behaviour. `instinct_flee` is a primitive that the god tools call (`flee_fn=instinct_flee`); what is missing is the *trigger* (A3).
* The weather already knows `season_for_tick` (works under both calendars), eight weather kinds and three growth multipliers; nothing consumes a temperature. The harness calendar answers `tick_to_time_block` under the legacy day and under `EDEN_CALENDAR`, so day/night offsets in a temperature model need no flag.
* Resident state that changes slowly belongs in the resident record on the decision cadence (the doc's own rule); `h_tensor` has exactly **one** free column (31). I do not spend it here.
* Daily and cadence systems already have a pattern: `AgentDriver.step` calls `market_day.step` and the bonds pass at fixed periods using `gameclock.DAY_TICKS`. A4 (drives) and A5 (grief, grudge decay, loyalty, jealousy) are resident-record systems on the relationship/personality stores, which the model plane owns; Part 1 already depends on `instinct_grudge_decay` there. I propose they stay with latenight2 (section 5).

## 2. The steps, in the order I would build them

Sizes S/M/L; each lands as its own commits, its own flag and its own focused tests; goldens must stay bit-identical flag off, and flag on where the step is invisible by design.

### Step 1: `EDEN_STEERING` (2.A1 wire) - S
* Registers, in this order, between `instinct_structure_occupancy` (37) and `instinct_move` (38): `instinct_pairwise_relations` (37.1, fills `ctx["pairwise_pre"]`), `instinct_search` (37.2), `instinct_reproduction_strategy` (37.3), `instinct_survival_navigation` (37.4), `instinct_social_navigation` (37.5), `instinct_schedule_navigation` (37.6). They return the dicts `instinct_move` already reads (`seek_mask`, `nav_*_bias`); the `TASK_OWNED_*` filters stay so a resident with an active task is never steered twice.
* Retired: none. `instinct_eat`, `instinct_drink` and the `*_with_humans` set stay as they are (the doc's "retire after parity" is a separate decision I am not taking).
* Tests: roster world flag on = every tensor bit-identical to flag off over 600 ticks (the proof it is invisible there); a legacy-style mini world (hand-built `h_tensor`, no roster) where a hungry human drifts toward food, a seeker toward a mate, and a scheduled human toward its anchor; masks respect dormancy (`ctx["h_mask"]`). Gate: strict goldens x4 unchanged flag off and flag on.
* Honest value: restores intended behaviour for non-roster humans. Cheap; I would do it last or on request.

### Step 2: `EDEN_TEMPERATURE` (2.A2 temperature comfort, the missing consumer of the season) - M
* One new instinct (`harness/temperature.py`), registered at 34 (after the vitals, before `instinct_heal`). Data table, no code in the rows: ambient = `SEASON_BASE[season] + WEATHER_OFFSET[kind] + BLOCK_OFFSET[time block]` (block from `calendar.tick_to_time_block`, season from `weather.season_for_tick`, weather kind from `_nature_state`), all numbers proposals (winter base about -4, summer about 22, night -5, day +3, comfort band 8..30).
* Per resident, vectorised, one pass over `ctx["h_mask"]`: `deficit = clamp(COMFORT_LOW - ambient_eff, 0)` where `ambient_eff` rises by a fraction when `H_SHELTER > 0` (the shelter flag the engine already maintains) and by a larger one near a lit fire or a built hearth (an entity-distance test against the few fire/hearth rows, not against everyone) and by clothing (a placeholder 0 until the item class exists). Effects: stamina drain and mood drop proportional to the deficit; HP damage only above a high deficit and without shelter or fire (the "cold kills the unprepared" rule); symmetric heat effects raise thirst. Rates scale with `calendar.rate_scale` so the same table works under either calendar.
* No new column: `body_temp` is derived each tick from the above (one scalar in a local tensor). The model plane gets the derived feature `cold` (request to latenight2: add `cold` to the Tier 1 features and `seek_shelter`/`light_fire` legality; the verbs exist).
* Balance gate (c3's rule: a winter that kills everyone is a bug): scenario run of the village over a winter at the legacy day and at the user's day; deaths from cold rare but real, none for residents who shelter and keep a fire; recorded numbers in the as-built section.
* Tests: pure ambient function for every season/weather/block; vectorised effects vs a scalar reference; shelter and fire reduce the deficit; no effect flag off (strict goldens); dormant rows untouched; cost below 0.1 ms per tick at 30 residents (`tools/spatial_probe.py` roster mode).

### Step 3: `EDEN_WOUNDS` (2.A2 wound recovery) - M
* Extends `systems/health`, does not replace it. State in the resident record (no column): `wound` = `{bleed, since}` set by an attack or a fall event, advanced **on the cadence (every 20 ticks) in closed form** for the elapsed window: bleeding costs HP at a rate that decays; infection chance rises with open wounds and low shelter/hygiene; healing rate depends on hunger, rest and shelter. Treatment (`treat_wound`) is a model-plane verb that clears `bleed`; the harness exposes `wounds.treat(engine, uid)`.
* Wakes correctly with dormancy: the closed-form advance runs for elapsed ticks (like `dormancy.wake`).
* Tests: closed-form equals tick-by-tick for the same window; untreated deep wound can kill, treated one heals; save round trip (the record is saved already); flag off inert.
* Needs the attack/wound event to exist as a ledger event (`human_hit` outcomes from `resolve_human_attack_intents` and `creature_killed`/creature hits from the kernel feed it). I can subscribe in the harness; the event shape is the resolver's outcome row (no new event).

### Step 4: `EDEN_DANGER` (2.A3, harness half: the danger ledger) - M
* `harness/danger.py`: the resident record gains `danger_memory`, a short list `{place (absolute position), kind, strength, tick}`; entries are created from attack/wound events (a creature of a kind hurt this resident here; a human attacked it), decay on the cadence (exponential, half-life in game days, `calendar`-scaled), merge when close, and are **shifted on a re-base** (it is an absolute position: `WindowManager.rebase` already shifts resident memory through `_shift_resident_memory`; I add the key to its list). A per-tick pass is one distance test of a resident against its own few places (not against everyone) and writes `THREAT` pressure when inside, with a dwell/hysteresis band so there is no flee-return oscillation. Creature kinds come from the table's `hostile` flag, so a wolf bite at the forest edge at dusk raises danger there.
* Flight itself is NOT an instinct in the roster world (anchor movers drive bodies): it is the existing `flee`/`hide` verbs and the `flee_target` task, chosen by the matrix with the `fear` feature. So the harness half stops at the ledger, the decay, the re-base shift and the features (`fear`, `near_danger`, `avoid_places`); latenight2 consumes them. For non-roster humans the ledger can call `instinct_flee` directly (flag `EDEN_DANGER_FLEE`, later).
* Tests: creation from a hit outcome, decay curve, merge, hysteresis, re-base shift equals the frame shift, window unload/restore keeps the record (it is in the resident record), flag off inert.

## 3. Cost, risks and files

Files: `harness/steering.py` (registration only), `harness/temperature.py`, `harness/wounds.py`, `harness/danger.py`, installs in `harness/engine_hooks.py` (CRLF file; one flag-gated block per step), a re-base key in `window_manager._shift_resident_memory`, tests `tests/test_harness_{steering,temperature,wounds,danger}.py`. No edit of `instincts_and_tools.py`, `map_test.py` or `genesis_config.py` (new constants live in the new modules). The only touches of existing harness code are mine.

Risks: temperature calibration (balance gate above); wounds depend on the attack events being complete (both resolver paths and the creature kernel); the danger ledger grows the resident record (cap the list, 8 entries). Per-tick budget for steps 2-4 together: below 0.3 ms at 30 residents (the doc's own bar), measured before merging.

## 4. Blocked, not touched

`instinct_fatigue_sleep_pressure` and `instinct_darkness_unease` need the day/night clock under `EDEN_CALENDAR`; the calendar C4 (`time` block, bootstrap `world.calendar`, save refusal texts) waits for the user's wording. `instinct_food_spoilage` needs per-item timestamps in the inventory record (model plane) and the day length (`gameclock.DAY_TICKS`, which is calendar-aware); I can supply the daily hook, latenight2 the item rule.

## 5. Proposed hand-offs (latenight2, resident-record systems)

2.A4 drives (curiosity, ambition, pride, thrift, territoriality) and 2.A5 (grief, jealousy, loyalty, gratitude, `grudge_decay`) are daily/cadence passes over the relationship and personality stores and feed goals and the matrix; the pattern (`market_day`, `bonds_day`, lazy decay with `last_decay_tick` applied on wake) already lives in `systems/actions`. They need nothing from the harness except the daily slot (`gameclock`), which exists. Boredom and loneliness (P2) go with them. If c3 would rather I build any of these, the plan is the same as step 3 (record fields, closed-form catch-up).

## 6. Decisions needed

1. Approve the order: 1 steering (S), 2 temperature, 3 wounds, 4 danger ledger; or put temperature first because it unlocks the winter scenario (my recommendation: 2, 3, 4, then 1).
2. Approve installing from `engine_hooks` with `engine.register` (no legacy-file edit) and the single `_shift_resident_memory` key.
3. Approve the hand-off of 2.A4/2.A5 and the `cold`/`fear`/`wounded` Tier 1 features to latenight2 (c3 to relay).
4. Balance numbers are proposals; the winter gate decides them.

## 7. As built (2026-10-09, HEAD 8abec74; harness plane, all flags default off, flag-off bit-identical)

Order approved by c3 and built: `EDEN_TEMPERATURE`, `EDEN_WOUNDS`, `EDEN_DANGER`, `EDEN_STEERING`. Installed from `harness/engine_hooks.py` with `engine.register` (genesis hooks for temperature and steering, a post-step `harness_wounds` when `EDEN_WOUNDS` or `EDEN_DANGER` is set); `instincts_and_tools.py` is untouched. Gate at 8abec74: strict goldens default/--resources/--spaces/window-hook no drift, s1 digests a2fcc8cbdd7143c8 and f83fed5436dd08fe, all test files below green.

| Flag | Module | What it does | Readers (all take `engine` first) | Tests |
|---|---|---|---|---|
| `EDEN_TEMPERATURE` | `harness/temperature.py` | Comfort instinct at priority 34: ambient = season base + weather offset + block-of-day offset; outside the comfort band 8..30 residents lose stamina, mood and thirst rates (0.02/0.02/0.015/0.02 per degree per tick) and, 10 degrees past the band, HP. Indoors (`H_SHELTER > 0` or `H_SPACE != 0`) +12; within 40 units of a lit fire or placed hearth/campfire +18. Totals on `engine._temperature_totals`. | `state_of(engine)`, `cold_of(engine, slot)`, `hot_of(engine, slot)`, `add_source(engine, x, y, *, radius, bonus, ticks)` for lit fires (shifted on re-base by `window_manager.rebase`; key `moved["warmth_sources"]`) | `test_harness_temperature.py` (17) |
| `EDEN_WOUNDS` | `harness/wounds.py` | A hit is an HP drop of 4 or more in one tick. Bleed `0.02 x hit HP` per tick, half-life 100 ticks (indoors twice as fast), infection `0.5 x hit HP`; closed-form catch-up per cadence of 20 ticks (max 48000), dormant rows skipped. State in `engine._wounds[uid]`, mirrored to `resident["wound"]`; event `human_wounded`. Callbacks `on_hit`/`off_hit` run even without the flag (the danger writer uses them). | `bleed_of(engine, uid)`, `wounded_of(engine, uid)`, `treat(engine, uid, strength)` | `test_harness_wounds.py` (15) |
| `EDEN_DANGER` | `harness/danger.py` | On a hit, writes `resident_store.remember_threat`: kind `predator` at the nearest hostile creature within 120 units, else `hazard` at the resident's own position. Re-base shifting is `rebase_model_plane` (latenight2), tested. | `places(engine, uid)`, `near_danger(engine, uid, x, y, radius)`, `danger_pressure(engine, uid, x, y, radius)` | `test_harness_danger.py` (9) |
| `EDEN_STEERING` | `harness/steering.py` | Registers once: `instinct_pairwise_relations` 37.1, `instinct_search` 37.2, `instinct_reproduction_strategy` 37.3, `instinct_survival_navigation` 37.4, `instinct_social_navigation` 37.5, `instinct_schedule_navigation` 37.6 (between occupancy 37 and move 38). | the keys they put in the tick context | `test_harness_steering.py` (4) |

Not invisible in a roster world: with `EDEN_STEERING=1` the default golden drifts (moods 100.0 vs 80.4 at tick 100) because the instincts bias movement; `EDEN_WOUNDS` and `EDEN_DANGER` alone do not drift, `EDEN_TEMPERATURE` drifts slightly (stamina, thirst, mood). Only the flag-off goldens are strict gates.

### Winter table (`tools/winter_probe.py`, the starter village, 8 residents, `EDEN_TEMPERATURE=1`, seed 1)

| Calendar | Spaces | Ticks | Deaths | HP lost to cold | Cold resident-ticks | Sheltered of those | Mean cold degrees | Fires lit |
|---|---|---|---|---|---|---|---|---|
| legacy | no | 2400 | 0 | 4.0 | 7738 | 0 | 3.5 | 0 |
| legacy | yes | 2400 | 0 | 1.9 | 5611 | 1596 | 2.2 | 0 |
| user | no | 24000 | 0 | 44.9 | 184605 | 0 | 14.3 | 0 |
| user | yes | 24000 | 0 | 12.6 | 175528 | 87826 | 8.3 | 0 |

Reading: winter on a roster village is mild because the roster needs scale is about 0.015 (the rates above are multiplied by it); with spaces on, residents spend half their cold ticks indoors and lose a quarter of the HP. Fuel use and clothing have no mechanism yet (the `light_fire` verb and the clothing item class are model-plane work; `temperature.add_source` is the hook), so "fires lit: 0" and "clothing: no mechanism yet" are the probe's honest readings, not a gate pass.

### Creature ecology found while building the balance scenario

The kernel brain exposed that the window world has no food or water for the legacy eat and drink loops (they need an entity under the animal). Fixed in the kernel (`systems/creatures/kernel.py`, `collide.py`): creatures that eat grass or forest graze on grass and sand tiles (`GRAZE_RATE` 0.06 per tick), share a forage cell of 8x8 tiles (`CELL_FOOD` 0.09: three grazers per cell), drinkers within a tile of water lose thirst (`DRINK_RATE` 0.4) and a thirsty creature (over 50) walks to water within 240 units. The legacy birth rule (`animal_tool_reproduce`) only looks at the cooldown, so the kernel pins the cooldown at 1.0 on a creature that is hungry (over 40) or on a full pasture (`CELL_CAPACITY` 3). Under the legacy calendar animals age four life-years a day (a life-year is 600 ticks, a day 2400), so a 10-day run there is not an ecology; `tools/creature_balance.py --calendar user` runs the 12000-tick day.

### Sleep pressure and darkness unease (USER-DEC-6 item 3; commit 7a81dee)

Two more flag-gated registry instincts, installed by genesis hooks in `engine_hooks.install()` before the runtime records the order, so the order is TEMPERATURE 34, SLEEP 34.2, DARKNESS 34.4, then `instinct_heal`, then STEERING. Flag off, nothing is registered and nothing is read.

| Flag | Module | Priority | Per tick | Readers for the model plane |
|---|---|---|---|---|
| `EDEN_SLEEP=1` | `harness/sleep.py` | 34.2 | debt (0-100) builds awake (100 after 0.75 of a game day) and clears asleep (0.30 of a day); above `TIRED` 50 it drags stamina and mood in proportion; a sleeper regains a little of both | `sleep.debt_of / tired_of / exhausted_of(engine, uid)` (tired above 50, exhausted from 85) |
| `EDEN_DARKNESS=1` | `harness/darkness.py` | 34.4 | unease = (1 - light) x outdoors x (0.2 within a fire's radius); mood falls, threat rises only up to `THREAT_CAP` 25 (below fleeing levels) | `darkness.unease_of(engine, slot)` (0..1, last tick) |

Notes. Rates are measured against `calendar.active().day_ticks`, so a 2400-tick and a 12000-tick day feel the same; they are also multiplied by `rate_scale("needs")` and the roster `needs_scale`. The debt updates on a 20-tick cadence in closed form; a dormant resident keeps its tick and the next update covers the time away. Asleep is the roster `sleep` anchor, else indoors during the night block. The debt is mirrored in `resident["sleep"]` (the records are in the save) and read back for a uid the engine has not seen. Darkness reads the fires of `harness.temperature` (hearths and `add_source`), so the lit-fire verb from the model plane relieves it. All numbers are proposals. Tests: `tests/test_harness_sleep.py` (17), `tests/test_harness_darkness.py` (14).
