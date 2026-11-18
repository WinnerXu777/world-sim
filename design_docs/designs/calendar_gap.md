# 1008 calendar module: day, night, seasons, ageing and rate scaling (GAP; design only, no code until the orchestrator's OK)

Author: 837dca (Harness plane). Origin: c3 [DECISION] of 2026-10-08 relaying the user: a game day is **12000 ticks** (10 real minutes at 20 ticks per second), a year is **8 days** (about 80 minutes), seasons about 2 days each; "a separate calendar module behind a flag (default off) with needs, ageing and crop rates rescaled behind the same flag; Stage 1 untouched by default". This note is the design that decision asks for, and it feeds `./expandtools_instincts.md` 2.B1, 2.B2, 2.A2, 2.B5.

## 0. What the tree does today (verified 2026-10-08, HEAD 85f3bf3)

Two unrelated clocks and a set of per-tick rates that were calibrated against the first.

| Clock | Value | Where | Used by |
|---|---|---|---|
| Year | `TICKS_PER_YEAR = 600` (30 s) | `genesis_config.py:54` | seasons (`season_for_tick`: quarters of 150 ticks), `COOLDOWN_DECAY_RATE = 1/600`, `instinct_age` (+1/600 per tick, `H_AGE` in years), animal ageing (`instincts_and_tools.py:1658`), resident memory ttl in years (`resident_store.py:190`), payload fields `ticks_per_year` and `year` (`map_test.py` 4623, 4653, 4691, 4785, 5527) |
| Day | `DEFAULT_DAY_LENGTH_TICKS = 2400` (2 min) | `systems/schedule/resolver.py:16` | `tick_to_time_block`: four equal blocks `dawn / day / dusk / night` of 600 ticks; schedule routines (`schedule/navigation.py`, `lifecycle.py`), `roster/driver.py`, `actions/recordops.py`, the Tier 1 `night` feature (`decision/features.py`: night 1.0, dusk 0.5) |

So today **one schedule day is four years** (2400 / 600) and the year, which sets the seasons, is exactly one schedule block. Nothing reads a light level or an hour. Both constants are imported **by name** (`from genesis_config import TICKS_PER_YEAR` in `instincts_and_tools.py`, `map_test.py`, `weather.py`), so a runtime flag cannot change them without an accessor.

Per-tick rates in `genesis_config.py` that implicitly assume the 600-tick year (a tick is 50 ms): `HUNGER_TICK_RATE 0.05` (0 to 100 in 2000 ticks = 100 s), `THIRST_TICK_RATE 0.07` (71 s), `THIRST_DAMAGE_RATE 2.5`, `HEAL_RATE 0.3`, `STAMINA_RECOVER_RATE 1.5`, `STAMINA_DRAIN_MOVE 0.2`, `MOOD_RECOVERY_RATE 0.3`, `THREAT_DECAY_RATE 0.6`, `INFECTION_*`, `ANIMAL_HUNGER_TICK_RATE 0.03`, `ANIMAL_THIRST_TICK_RATE 0.04`, `ANIMAL_MATURE_TICKS 2.0` (in years), `MATURE_AGE 18.0` years, `QUARANTINE_COOLDOWN_YRS 5.0`, `RESOURCE_REGROW_RATE 0.015`, `LAKE_WATER_REPLENISH_RATE 0.03`, `WELL_WATER_REPLENISH_RATE 0.08`, `FARM_FOOD_GROWTH_RATE 0.10`, `FARM_WATER_USE_RATE 0.04`; weather lasts `randint(60, 110)` ticks (3 to 5 s) in `weather.py` (lines 110, 163); `FIRE_BURN_TICKS`. Other tick constants that are **real-time** and should not move: action and task timeouts (`trip_timeout_ticks 2400`, `ready_hold_ticks 2400`), movement speed, cooldowns of verbs.

Under the user's calendar these numbers are wrong by one to two orders of magnitude if left alone: a resident would starve in 1/120 of a day and weather would change every 4 seconds.

## 1. Principle

**Body and nature time scale with the calendar; action and physics time stay in seconds.** A resident still walks, talks, builds and fights at the speed of ticks, but eats a few times per day, sleeps once, ages over days, crops grow over days, and weather lasts hours. One class table (section 4) assigns every constant to a class; a single set of multipliers does the rescale, only under the flag.

## 2. The module

New file `at_the_beginning/harness/calendar.py` (Harness plane; pure functions, no engine state, no torch). Flag `EDEN_CALENDAR=1`, read at call time (`calendar_enabled()`), default off. Two profiles, one interface:

```
Calendar(day_ticks, days_per_year, daylight)      # frozen dataclass
LEGACY = Calendar(day_ticks=2400, year_ticks=600)   # four equal day blocks, year in quarters: today's functions exactly
USER   = Calendar(day_ticks=12000, days_per_year=8)                               # year_ticks = 96000, season_ticks = 24000
active() -> Calendar            # USER if the flag is on, else LEGACY
now(tick) -> Moment             # day_index, tick_of_day, day_phase [0,1), block, season, season_phase, year, year_phase, light [0,1]
ticks_per_year() / season_for_tick(tick) / tick_to_time_block(tick) / year_of(tick)      # drop-in accessors
rate_scale(cls) -> float        # 1.0 with the flag off
```

* **Day.** `day_phase = (tick % 12000) / 12000`. Time 0 is dawn-start (sunrise at 0.00 + offset). Light is a smooth curve (`light = clamp(0.5 + 0.55 * sin(2 pi (day_phase - 0.25)) * k(season) + 0.05, 0, 1)` as a starting form; the exact curve is a tuning detail), with day length varying by season through `daylight(season)`: spring 0.50, summer 0.58, autumn 0.50, winter 0.42 of the day above the horizon. Blocks: `dawn` and `dusk` are fixed 1/24 of a day (500 ticks): the first and the last 500 ticks of the time the sun is above the horizon; `day` is what lies between them, `night` is the time below the horizon. The four block names stay (the schedule catalogue and `night` feature keep working); only their lengths change. From the daylight table (0.42 to 0.58 of 12000 = 5040 to 6960 ticks above the horizon): dawn 500, **day 4040 to 5960**, dusk 500, night 5040 to 6960 ticks (winter to summer; spring and autumn: 6000 above, day 5000, night 6000).
* **Year.** 8 game days, season boundaries at days 0, 2, 4, 6 (spring, summer, autumn, winter), so a season is 24000 ticks (20 real minutes). `season_phase` is the progress inside a season (used by 2.B2 crop windows and temperature curves).
* **Legacy profile.** Not an approximation: `LEGACY` must return exactly what `season_for_tick`, `tick_to_time_block` and `TICKS_PER_YEAR` do today, because the flag-off path calls through the same accessors. The strict golden is the proof.
* **No state, no RNG.** Everything is a function of `tick`, so it is origin-invariant, restart-safe and identical in shadow replay. The only saved fact is which profile the world was made under (section 6).
* **Daily slot (2.B1).** `day_index` change events: `calendar.day_changed(prev_tick, tick)` returns the list of day indices crossed, so a step hook can run `every_day` systems and a woken dormant chunk can ask for "days since `last_run_day`" in closed form.

## 3. Replacing the two clocks (flag-off-safe migration)

Step C1 changes no behaviour: every reader goes through the accessors, the `LEGACY` profile returns the old numbers, and the strict golden proves it.

| Site | Today | Change |
|---|---|---|
| `genesis_config.py:494` `COOLDOWN_DECAY_RATE = 1/TICKS_PER_YEAR` | import-time constant | keep the constant (flag off); the call sites that use it call `calendar.cooldown_decay_rate()` |
| `instincts_and_tools.py:1092` `instinct_age`, `:1658` animal age | `step = 1/TICKS_PER_YEAR` | `step = calendar.age_step()`; see section 5 for the flag-on value |
| `systems/nature/weather.py:90` `season_for_tick` | quarters of 600 | delegate to `calendar.season_for_tick` |
| `systems/nature/weather.py:110, 163` weather duration | `randint(60, 110)` | `randint(60, 110) * rate_scale("weather")` (the draw stays; counter-RNG is 2.E3 and is not part of this step) |
| `runtime/resident_store.py:190` memory ttl years | `years * TICKS_PER_YEAR` | `years * calendar.ticks_per_year()` |
| `map_test.py` 5 sites | `TICKS_PER_YEAR` in payloads | `calendar.ticks_per_year()` plus the additive `time` block (section 6) |
| `systems/schedule/resolver.py:16, 19` | `DEFAULT_DAY_LENGTH_TICKS`, equal quarters | `tick_to_time_block` delegates to the calendar; the default argument stays so existing callers and tests are unchanged |

Legacy files touched: `genesis_config.py`, `instincts_and_tools.py`, `weather.py`, `resident_store.py`, `map_test.py` (all legacy, need authorisation) and `systems/schedule/resolver.py` (a Model-plane area; 2f0fd3 to make or approve the edit). Each followed by a strict golden.

## 4. Rate classes (flag on only)

One multiplier per class, from `rate_scale(cls)`. Starting values are **proposals** derived from the target behaviour; the survival scenario in section 7 tunes them. Reference: legacy day 2400 ticks, new day 12000, factor 5; legacy year 600, new year 96000, factor 160.

| Class | Constants | Target behaviour under the new calendar | Proposed multiplier |
|---|---|---|---|
| physiology (hunger, thirst) | `HUNGER_TICK_RATE`, `THIRST_TICK_RATE`, animal equivalents | hunger from 0 to the seek threshold (50) in about 0.4 day (4800 ticks); thirst to 45 in about 0.25 day (3000 ticks); so a resident eats about 2 to 3 times and drinks 4 times a day | hunger 0.0104 / tick (x 0.21), thirst 0.015 / tick (x 0.21), i.e. one multiplier 0.21 for both |
| physiology (damage, recovery) | `THIRST_DAMAGE_RATE`, `HEAL_RATE`, `STAMINA_RECOVER_RATE`, `MOOD_RECOVERY_RATE`, `THREAT_DECAY_RATE`, `INFECTION_SPREAD/DAMAGE/NATURAL_DECAY` | starvation takes days, a wound heals in hours, a fever lasts a day; fights and fear stay seconds | damage and healing x 0.2; stamina and threat decay unchanged (they are action time); infection x 0.2 |
| ageing | `age_step`, `MATURE_AGE`, `ANIMAL_MATURE_TICKS`, `QUARANTINE_COOLDOWN_YRS`, memory ttl | see section 5 | decoupled from the calendar year |
| growth (nature) | `RESOURCE_REGROW_RATE`, `LAKE/WELL_WATER_REPLENISH_RATE`, `FARM_FOOD_GROWTH_RATE`, `FARM_WATER_USE_RATE`, node regrow | a gathered bush regrows in about 1 to 2 days, a farm crop ripens over a season (about 2 days), wells refill over hours | regrow x 0.2 (1 / the day factor), farm growth x 0.04 (a crop takes one season), water x 0.2 |
| weather | durations 60 to 110 | weather lasts 0.15 to 0.3 day | x 30 (1800 to 3300 ticks), extreme events drawn per season rather than per tick |
| action time | movement speed, verb cooldowns, task timeouts, `FIRE_BURN_TICKS`, attack ranges | unchanged | x 1.0 |

The multipliers are data in `calendar.py`, not edits to `genesis_config.py`: the constants keep their legacy values, and the code that reads them multiplies by `rate_scale(class)` (1.0 with the flag off). That keeps the golden bit-identical flag off, and keeps the table reviewable in one place. Sites to touch: the instinct functions that apply the rates (`instinct_hunger`, `instinct_thirst`, health recovery and infection, `apply_node_regrow`, `apply_resource_regrow`, `apply_water_cycle`, farm growth in `nature/ecology.py`), listed by the coverage map. A peer plane caveat: `systems/actions/verbs/survival.py`, `systems/roster` and Tier 1 features read thresholds, not rates, and are unaffected.

## 5. Ageing (needs a decision)

`H_AGE` is in years and `MATURE_AGE = 18`. With an 80-minute year, 18 years is 24 hours of play and a 60-year life is 80 hours: no run reaches adulthood, births never mature, and nobody dies of old age. So ageing must **not** follow the calendar year.

* **Proposal (A):** a life-year is a separate unit: `LIFE_YEAR_TICKS` (flag on) = **one game day of 12000 ticks per life-year**. Adulthood (18) then takes 3 hours of play, a 60-year life 10 hours; `age_step = 1/12000` per tick. The calendar year (seasons) and the life-year stay separate words in the code (`year_of(tick)` versus `age_years`).
* **Alternative (B):** a life-year is one game season (24000 ticks, 20 real minutes): adulthood in 6 hours, a 60-year life in 20 hours; rejected as too slow, no session would see a child grow up (A gives 3 hours).
* **Alternative (C):** a life-year equals a calendar year (24 hours to adulthood): no population turnover in any realistic session; rejected.
* The roster path already scales ageing per resident (`age_scale_vector` in `roster/driver.py`, `scales * step`); the multiplier slots into `step` and the vector is untouched.
* Anyone already in a save keeps their `H_AGE` number; only the rate changes.

## 6. Wire and save

* `/bootstrap` `world.calendar = {enabled, day_ticks, year_ticks, days_per_year, season_ticks, daylight, ticks_per_second}` and `/frame` gets an additive `time = {tick, day, day_phase, block, season, season_phase, year, light}` (flag on only). **PROPOSED for the client contract** (a new section; the client may ignore it). Existing `ticks_per_year` and `year` keep their meaning for the flag-off path and carry the new values when on.
* Save: a world made under the calendar flag cannot be continued without it (rates differ). Add `calendar: {profile, day_ticks, days_per_year}` to the world metadata that `world_snapshot` already writes for format 3 (a new key in `world_format`, same shape as `generator_version`); `validate` refuses a mismatch with a message in the style of the two approved texts. Draft for approval: "This save was made with the long calendar (a day is 12000 ticks, EDEN_CALENDAR=1), but this session runs without it, so it cannot be continued. Start the game with EDEN_CALENDAR=1 to continue it. The save file has not been changed." and the converse. No format-number bump is needed if the key is optional and absent means `LEGACY`.
* `time_control` (Stage 1 god power) stays; with a 10-minute day it is the user's way to skip to night or winter. `set_time_of_day` and `set_season` (2.C6) write a tick offset (`_nature_state["calendar_offset"]`, saved, used by `now(tick + offset)`).

## 7. Proof

1. **Flag off, bit-identical:** strict golden (dense default, `--resources`, `--spaces`) after each legacy-file commit; plus a table test that `calendar.LEGACY` equals the old `season_for_tick`, `tick_to_time_block` for ticks 0 to 5000 and 100 random larger ones.
2. **Calendar unit tests:** block and season boundaries at exact ticks; monotonic day index; `light` continuous and in [0, 1]; day lengths by season sum to a day; `day_changed` crosses each boundary once, including across a long jump; origin invariance is trivial (no state).
3. **Rescale scenario (flag on):** a resident with a food source survives 3 game days eating 2 to 3 times a day; with no food, death on day 3 to 4 (not minute 2); a farm planted in spring ripens before autumn; a node harvested to zero regrows within 2 days; a weather change lasts 0.15 to 0.3 day. Tuning uses this scenario; the multipliers are data and change in one place.
4. **Mixed flags:** calendar on with the window and spaces on (shadow-free). Window walk trace unaffected by the calendar (it is stateless).
5. **Budget:** `now(tick)` called once per tick is below 10 us; per-class `rate_scale` is a dict lookup, no new tensor passes (the existing passes multiply by a float).

## 8. Order and cost

C0 module and unit tests, nothing calls it (S). C1 accessors replace the readers, strict golden (S, five legacy files). C2 rate classes behind the flag plus the rescale scenario (M; this is where the tuning time goes). C3 consumers: light-driven perception radius (with `EDEN_PERCEPTION_BOUNDED`), the `night` feature in Tier 1 widened to `hour` and `light`, sleep pressure and darkness unease (2.A2), season-driven temperature, crop windows (2.B2, 2.B5) (M each, in the expansion plan's order). C4 wire and save refusal (S). Nothing in C0 to C2 changes the default behaviour.

## 9. Risks and decisions wanted

* **Ageing unit (section 5): DECIDED.** A, one life-year per game day (`CALENDAR_LIFE_YEARS_PER_DAY = 1`; 18 life-years = 18 game days = 3 hours of play). Accepted by the Orchestrator for the Harness calendar design in USER-DEC-4 (`../DECISIONS.md`, 2026-10-08).
* **Schedule file ownership: DECIDED.** `resolver.py` is Model-plane; 2f0fd3 approved the edit (signature and default unchanged, flag-off identical, flag-on only when the caller passes the default day length; committed alone with its tests; `tests/test_schedule*` and `test_actions_roster` run after).
* **Tuning is empirical:** the multipliers in section 4 are first estimates.
* **Long runs:** a game day of 10 minutes makes the unattended-run tests (hundreds of thousands of ticks) cover only a few days; the scenario tests therefore use `time_control` or a direct tick offset to jump, and need the lazy daily catch-up (2.E2) to be correct before they mean anything.
* **Existing saves** made without the flag keep working with the flag off; none can be moved across (refusal above).
* **Animals:** `ANIMAL_MATURE_TICKS` is in life-years like humans, rescaled the same way; predator and prey rates move with the physiology class so the food web keeps its ratio.
