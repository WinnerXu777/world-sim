# 1008 Phase 2: the creature definition table, spawn, window store and the generalised predator loop ([GAP], harness plane, design only, 2026-10-09)

Author: 8d998a ("1008latenight"). For c3's approval before any code. Engine and data owner: harness. Model plane (latenight2) owns affordance, features, rules and verbs that READ this table (`fight`, `flee`, `hunt`, `hide`, loot grants). Nothing here changes behaviour with `EDEN_CREATURES` unset: no creature rows exist, no legacy function is touched except two one-line identity hooks (section 5).

## 1. What I read (the facts the design rests on)

* **Animal rows** are `m_tensor` rows with `M_TYPE` in `ANIMAL_TYPES = range(40, 80)`; used today: `M_SHEEP=40, M_DEER=41, M_TIGER=42, M_WOLF=43, M_FISH=44`. Columns `A_AGE=6 .. A_THIRST=12` (13-16 are resource-node columns, 17-29 are free for species attributes), `M_GEN=30`, `M_SPACE=31`. Per-species behaviour numbers live in five dicts in `genesis_config.py` (`ANIMAL_LIFE_EXP`, `ANIMAL_SCALE`, `ANIMAL_BASE_AGGRESSION`, `ANIMAL_MOVE_STEP`, `ANIMAL_PREY`) plus three global constants (`ANIMAL_PREDATOR_ATTACK_DAMAGE=15`, `ANIMAL_PREDATOR_RANGE=20`, mating radius). Every consumer uses `.get(species, default)`, so a new id costs nothing until it has a row.
* **The legacy loops** (`instincts_and_tools.py`): `animal_instinct_move` is a Python `for` over every animal with `random.random()` (global RNG, so not replayable from the world seed) and one `nearest_predator_target` call per predator per tick; `animal_instinct_predator_attack` is another Python loop with `pairwise_distances` per animal per prey type; damage is the global 15 at the global range 20 with no cooldown; HP at birth is a hard-coded 100 (`animal_born`). Hunger, thirst, age, death and reproduction are already vector or per-species generic and need no change.
* **Kills yield nothing but hunger.** `resolve_human_attack_intents` restores `hunt_hunger_restore` for a kill of a type in `HUNTABLE_ANIMAL_TYPES = {sheep, deer, fish}` (hard-coded in `systems/combat/hunting.py`). No meat, hide or bone item exists anywhere in the item catalog today.
* **The generator already decides where wildlife is.** `data.spawns` of every chunk (worldgen, `make_spawns`): up to 4 entries `{species, weight, max (1..4), sprite, slots[[x,y]...]}`, seeded from tile hashes, species `boar, deer, goat, rabbit, sheep, wolf` with habitat weights over the biomes. Nothing consumes it ("actual animals are created by the integration code", `./worldgen.md` section 9). That is the deterministic per-chunk spawn rule; Phase 2 is the integration code.
* **The window** owns rows through `WindowManager.integrate/unload` (generated entities are static, tracked in `ChunkState.slots/uids/baseline`; `SKIP_DELTA_COLUMNS` excludes position, so a chunk delta can never carry a wandering animal). Budget `WINDOW_ROW_BUDGET = 800` of `MAX_ENTITIES = 1024`; chunks are 256 units.
* **Dormancy for animals** is implemented (`_dormant_a`, rows frozen when outside every integrated chunk) but never triggered, because no animal row exists in window mode.
* **The client** gets animals as `{uid, x, y, type_id, ...}` from `_export_animal`; the hint kind comes from string matching on the type label (`_human_actor_projection`). There is no sprite or species name on the wire yet.
* **The bible** (`./expansion.md` section (b)) fixes names, sizes and pivots: wolf, boar, fox, sheep, dog, cat, goat 128x128 [64,112]; rabbit, songbird, crow, chicken 64x64 [32,56]; fish; deer, cow, horse 160x160 [80,144]; goblin, skeleton, giant spider 128x128 [64,112]; ten invented species. It says temperament and hostility are chosen by the simulation owners: the numbers below are proposals marked as such.

## 2. Shape of the change (one table, one kernel, one store)

```
systems/creatures/table.py    DATA: CREATURES (name -> row), ids, validation, lookups. Importable without torch.
systems/creatures/spawn.py    pure: spawn plan for a chunk from data.spawns + data.pois + the table (deterministic).
systems/creatures/kernel.py   the vectorised behaviour step (registered as ONE instinct when the flag is on).
harness/creature_store.py     like structure_store: stash/restore creatures by chunk (the Q3 record).
harness/creature_window.py    integrate/unload glue (spawn plan -> rows; quota; catch-up).
```

Flag `EDEN_CREATURES=1`, default off, **requires `EDEN_WINDOW=1`** (boot refuses otherwise, same `SpaceConfigError` pattern as the structure store). With the flag off: no import side effects, no registered instinct, goldens bit-identical by construction. Legacy god tools (`tool_spawn_animal_group`, `populate_*`) keep working for the five legacy species; with the flag on they may also name a new species by id.

## 3. The schema (data keyed by name, resolved to `M_TYPE`)

One row per species, plain dict, validated at import (unknown keys, ranges, prey names that do not exist, duplicate ids, id outside 40..79 are errors with the species name in the message). Units: world units, game ticks (20 per second), hp on the 0..100+ scale of `M_HP`. Time-of-day uses `harness.calendar.tick_to_time_block(tick)` (`dawn|day|dusk|night`), which answers under the legacy day and under `EDEN_CALENDAR` alike, so this table needs nothing from the blocked calendar items.

| field | meaning | engine use |
| --- | --- | --- |
| `id` | `M_TYPE` 40..79, **stable forever** (section 4) | column `M_TYPE` |
| `name`, `label` | snake_case key = asset name (`giant_spider`); display label | client, type registry |
| `sprite` | asset key `a4/...`, size and pivot as in the bible (or `None`) | frame payload, `data.spawns[].sprite` agrees |
| `footprint` | `[w, h]` movement box in units (collision and the client's draw box) | `SCALE` = max(w, h)/2, kernel collision radius |
| `hp` | birth and maximum hp (`animal_born` hard-codes 100 today) | `M_HP` |
| `speed` | `{walk, run}` units per tick (replaces `ANIMAL_MOVE_STEP`) | kernel |
| `damage`, `range`, `cooldown` | per-hit damage, reach in units, ticks between hits | kernel attack pass |
| `aggro` | 0..1 base aggression, and `aggro_range` (sense radius) | kernel perception, `A_AGGRESSION` |
| `flee_hp` | fraction of `hp` under which it flees whatever it is | kernel state change |
| `fear` | `{humans: bool, radius, species: [names]}`: what makes it bolt (prey animals) | kernel |
| `diet` | `{eats: ["grass"|"carrion"|"meat"|"fish"|"none"], prey: [names], humans: "never"|"hungry"|"always"}` replaces `ANIMAL_PREY` | kernel + `install()` fills the legacy dict |
| `activity` | `{dawn, day, dusk, night}` each 0..1: share of ticks it moves and hunts | kernel throttle (a deterministic hash of the tick, not `random`) |
| `group` | `{kind: solitary|herd|pack, size: [lo, hi], cohesion: radius, leader: bool}` | spawn size, kernel cohesion |
| `territory` | `{radius, leash}` around its home point (spawn slot); leaves only fleeing or chasing | kernel |
| `life_exp`, `mature` | years range (`ANIMAL_LIFE_EXP`) and reproduction age | `animal_born`, reproduce |
| `habitat` | rule used by the spawn plan: `{spawn_entry: "wolf"}` (the generator's), `{companion: "rabbit", p: 0.5}`, or `{poi: ["ruin"], per_poi: [1, 3]}` | spawn plan |
| `loot` | `[{item, min, max, p}]` for meat, hide, bone... (item ids to be added to the catalog) | granted by a kill, **model plane verb** reads it |
| `hostile` | `bool`: counts for the `can_defend`/threat predicates (`services.py:261` is hard-wired to tiger and wolf today) | table lookup replaces the hard-coded set |
| `variant_of` | for coat/design variants: `{of: "wolf", overrides: {...}, col 17 = variant index}` | not a new id (section 4) |
| `enabled` | bool: a row can exist in the table and not be spawned | spawn plan |

Species columns (all inside the free 17..29 range, all 0 for every existing row): `C_VARIANT=17`, `C_STATE=18` (0 idle, 1 wander, 2 flee, 3 chase, 4 rest, 5 return, 6 attack), `C_STATE_TICKS=19` (timer), `C_GROUP=20` (group id, 0 = none). Home is NOT a column: a generated creature's uid is `c{cx}_{cy}:fauna:{species}{n}` and its home point is the plan's slot, so the kernel reads it from the creature book (uid -> chunk, offset) which the store also serialises. That keeps home rebase-proof (no coordinate columns to shift).

Why a Python data module and not JSON: the asset side only needs names, ids and sprite keys, which are exported by `tools/export_creatures.py` to `docs`-visible JSON (`../contracts/client_contract.md` gets a "creatures" section); Python keeps the validation and the prey-name resolution in one place.

## 4. Ids and names (stable with the asset side)

Existing ids are untouched: 40 sheep, 41 deer, 42 tiger, 43 wolf, 44 fish. New ids are allocated once, in this order, and never reused or renumbered (tests pin them):

| id | name | id | name | id | name |
| --- | --- | --- | --- | --- | --- |
| 45 | boar | 52 | dog | 60 | brambleback |
| 46 | fox | 53 | cat | 61 | mire_lantern |
| 47 | goblin | 54 | cow | 62 | cinder_moth |
| 48 | skeleton | 55 | horse | 63 | cairn_keeper |
| 49 | giant_spider | 56 | chicken | 64 | thread_thief |
| 50 | goat | 57 | songbird | 65 | bellhorn |
| 51 | rabbit | 58 | crow | 66 | glassfin |
|  |  | 59 | (spare) | 67 | moonhart |
|  |  |  |  | 68 | rootling |
|  |  |  |  | 69 | hollow_rook |

70..79 are spare. The bible's 12 variant designs (winter wolf, pack leader, bristle boar, red/grey fox, goblin barterer/scrap raider, armoured skeleton, cave/orchard spider, moss/frost cairn keeper, autumn rootling) are **variants**: `variant_of` + `C_VARIANT` (1..n), not new ids, so a coat never costs an id. Names are the bible's, lowercase with underscores; the generator's species strings (`boar, deer, goat, rabbit, sheep, wolf`) are the same keys.

## 5. Generalising the predator loop

* **Legacy species keep running on the legacy code** until the kernel passes parity tests. `install()` (called once when the flag is on) mutates the five legacy dicts in place from the table (`ANIMAL_PREY`, `ANIMAL_MOVE_STEP`, `ANIMAL_SCALE`, `ANIMAL_BASE_AGGRESSION`, `ANIMAL_LIFE_EXP` are the same dict objects that `instincts_and_tools` imported by name), and adds the type-registry entries (label, attrs) for new ids. No legacy code is edited for that.
* **The kernel** (`creature_step`, one registered instinct, flag-gated) handles the rows whose table entry has `brain: "table"` (every new species; sheep, deer, wolf, tiger switch to it by changing one table field once the parity test passes). It is vectorised: no `for` over animals. Per tick: (1) a throttle mask from `activity[time block]` with a counter-based hash of `(world seed, tick, uid hash)` so replay from the same seed is exact, unlike `random`; (2) perception by masked distance matrices bucketed by chunk key (the same trick as `humans_within`: a cheap superset first, then the exact test), humans through `humans_within`; (3) the state machine as a few `torch.where` passes in priority order: flee (hp under `flee_hp`, or a feared kind within radius) > attack (prey in `range` and off cooldown, hunger/`humans` gate satisfied) > chase (prey or human in `aggro_range`, `aggro` roll) > return (beyond `territory.leash`) > cohere (herd/pack centroid by `scatter_add` on `C_GROUP`) > wander (hashed heading, persistent for `C_STATE_TICKS`); (4) movement by `speed`, then collision against the movement box and walls through the existing `apply_motion_limits` machinery for entities if it exists, else a plain clamp; (5) cancelled moves into chunks that are not integrated (the creature bounces; this is why dormant creatures never exist in practice).
* **Attack results go through the same damage functions as today** (`apply_human_damage`, `apply_entity_damage`), threat 100 on the victim as the legacy loop does. Human victims are NOT offered to `COMBAT_MODIFIER` in this phase (Phase 1 offered human-vs-human only); a later `target_kind` extension is a model-plane decision.
* **Two one-line legacy hooks** (this is the legacy edit I ask approval for): in `animal_instinct_move` and `animal_instinct_predator_attack`, `a_mask = _creatures.legacy_rows(ctx, a_mask)` as the first statement after the `a_mask` read. Returns the argument unchanged unless the flag is on and the kernel owns some rows, in which case it removes those rows. Everything else in the age/hunger/thirst/die/eat/drink/reproduce chain applies to all animal rows, creatures included, unchanged. Plus, from the model plane or me with approval, `HUNTABLE_ANIMAL_TYPES` becomes a table lookup (`huntable: true`) so boar and rabbit can be hunted, and `services.py:261`'s tiger/wolf pair becomes `hostile` rows.
* **Loot.** The engine emits a `creature_killed` event `{uid, species, slot, pos, killer_uid}` (an additive event on the existing queue) and reads `loot` from the table; the grant itself (inventory add to the killer, ground drop, corpse) is a model-plane verb effect, because items on the ground are not tensor rows. Item ids `meat`, `hide`, `bone`, `feather`, `egg`... must exist in the catalog first: [REQUEST] to latenight2.

## 6. The window: spawn, integrate, unload

* **Spawn plan** (`spawn.py`, pure, deterministic, no RNG state): for a chunk, `plan(chunk_document, table, world_seed)` returns an ordered list of `{uid, species, offset(x,y), group, variant}`. Sources, in order: (a) the generator's own `data.spawns` entries for the species the generator knows (wolf, boar, deer, goat, rabbit, sheep): the entry's `slots` ARE the positions, `max` the group size cap; the group size inside `[lo, hi]` of the table is a hash of `(seed, chunk, species)`; (b) `companion` species (fox follows rabbit and wolf habitat with probability `p`, thinned by a tile hash); (c) `poi` species (skeleton at ruin POIs, goblin at camp POIs, giant spider near boulders/forest POIs, the invented species at the entity kinds the bible suggests: reed_bed -> mire lantern, berry_patch -> thorn/brambleback, ...), one hash per POI. **No generator change and no chunk byte change** (the chunk sha256s, the worldgen goldens and the cache keys stay as they are). The alternative, widening `SPECIES` in `generate.py` (and `MAX_SPAWN_ENTRIES` 4 -> 6), changes every chunk's bytes (GENERATOR_VERSION bump, golden regeneration): I do not propose it for Phase 2; it is the migration path if the asset side wants the sprite key inside the chunk document.
* **Integrate.** After the chunk's static entities and after `structures.restore`, `creatures.restore(coord)` puts back the stored creatures standing in this chunk (catch-up below), then, only if this chunk has never been populated (a `populated` set, plus a per-species deficit rule after `RESPAWN_DAYS`), allocates the plan's missing creatures. Allocation uses the existing `allocator` (rows are owned by uid, released on unload) and `animal_born`-equivalent column writes with `hp` from the table. **Quota:** `CREATURE_ROW_BUDGET = 96` (env `EDEN_CREATURE_ROWS`) of the 1024 rows (800 window budget + up to 96 creatures + the rest for built structures and legacy); when full, plan entries are skipped in a fixed order (nearest to a controlled human first, then by uid), so which creatures exist depends only on where the humans are. `_advance`'s existing `_row_estimate` gains `+ creatures.estimate(coord)` like the structure store.
* **Unload.** `creature_store.stash(coord)` moves every creature **standing in this chunk** (by position, like structures; not by origin chunk) out of the tensors into a record keyed by `ChunkCoord`: uid, species, offset from the chunk corner, every `A_*`/`C_*` column, hp, group, home (chunk coordinate + offset), tick. The row is released through the same path as `release_slots` (a despawn event only if the client had been told about it). A creature that walked into another integrated chunk is stashed by that chunk's unload, not its birth chunk's.
* **Catch-up on restore** (closed form, no ticks replayed): age advances by the elapsed time through `calendar.age_step`; hunger and thirst advance but are clamped under the starvation threshold (90), so a creature is never killed while stored; a creature past `life_exp` is not restored (deterministic); position returns to its offset, then within `territory` of home. A restore never runs the kernel.
* **Dormancy.** Creatures in an integrated chunk are never dormant; creatures leaving all integrated chunks are blocked by the kernel (bounce) or stashed by the unload. `dormancy.refresh`'s animal mask therefore stays all false in practice and remains the safety net for rows from legacy god tools.
* **Re-base** needs nothing new: creature positions are ordinary `CX/CY`, shifted by the rebase like every row; home offsets are chunk-relative.
* **Saving.** Open question for the user (via c3), no text is written: stored creature records and the creature book are state that `snapshot` cannot put in today's format. Three options: (a) **regenerate** (the default I propose for the flagged stage): `snapshot` drops creature rows and records, `load` repopulates chunks from the plan; what is lost is individual wounds, kills, age and wandering, and it needs no new format and no user-facing text; (b) refuse to save while any record exists (always true after a walk, so useless); (c) include in format 4 with the structure store. I would ship (a) and say so in the flag's docstring and the client contract, and fold creatures into format 4 when the user approves that format.

## 7. Row budget and cost

Rows: the generator gives about 1..4 animals per entry and up to 4 entries per chunk; in practice 1..3 per chunk in meadow/forest chunks and 0 elsewhere, so the 25 integrated chunks hold roughly 30..60 creature rows, the 49 chunks of the keep ring 60..100. A quota of 96 is above that; structures keep their own estimate. Compute: the kernel is O(creatures x nearby) with chunk buckets, target at most 2 ms per tick at 96 creatures (budget measured by `tools/spatial_probe.py` extended with a creature mode; the legacy loop is O(creatures x humans) with Python overhead and is measured as the baseline). The ensure/resident and per-human costs from the scaling work are not affected.

## 8. First set, then the rest (data proposals; the simulation owners edit the numbers)

All values are proposals. `hp` 100 scale; speed in units per tick (a human walks about 2 per tick, `ANIMAL_MOVE_STEP` for deer is 3.5).

| species | hp | speed walk/run | dmg / range / cd | aggro, range | flee at hp | diet | activity d/dw/du/n | group | territory | notes |
| --- | ---: | --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| wolf (43) | 60 | 1.6 / 4.0 | 12 / 14 / 20 | 0.7, 120 | 0.25 | meat; prey deer, sheep, rabbit; humans when hungry | .5 .4 .9 1.0 | pack 3..6 | 300 / 450 | night/dusk hunter; matches current `ANIMAL_PREY` plus rabbit |
| boar (45) | 80 | 1.2 / 3.4 | 14 / 12 / 24 | 0.35, 60 | 0.15 | omnivore: forest food, carrion; humans only when cornered (aggro triggered by an attack) | .6 .8 .7 .3 | solitary or sow+young 1..4 | 200 / 320 | charges when hit; no hunting of prey |
| deer (41) | 50 | 1.8 / 5.0 | 0 | 0, - | 1.0 (flees always) | grass | .8 .6 .9 .4 | herd 3..8 | 350 / 500 | fear: humans radius 70, wolves 110; huntable |
| fox (46) | 30 | 1.8 / 4.2 | 5 / 8 / 16 | 0.3, 50 | 0.5 | meat: prey rabbit, chicken; scavenges | .4 .3 .9 1.0 | solitary / pair | 180 / 280 | flees humans; companion of rabbit habitat |
| sheep (40) | 40 | 1.0 / 3.0 | 0 | 0 | 1.0 | grass | .7 .8 .7 .1 | herd 4..10 | 250 / 400 | existing, switch to kernel later |
| goblin (47) | 50 | 1.6 / 3.2 | 8 / 10 / 22 | 0.6, 90 | 0.3 | humans "hungry"; carries loot; **barterer variant is peaceful** | .2 .3 .7 1.0 | band 2..5 | 220 / 360 | spawns at camp POIs |
| skeleton (48) | 70 | 1.2 / 2.4 | 14 / 12 / 26 | 0.9, 70 | 0 (never flees) | none (no hunger: `diet.eats = none` freezes the hunger rate) | 0 .2 .6 1.0 | solitary / 2..3 | 160 / 240 | spawns at ruin POIs; sun-averse variant optional |
| giant_spider (49) | 90 | 1.5 / 3.6 | 18 / 16 / 28 | 0.8, 100 | 0.1 | humans "always" in range | .3 .3 .6 1.0 | solitary | 140 / 220 | forest/boulder POIs |

The ten invented species and the other bible fauna (dog, cat, cow, horse, goat, rabbit, chicken, songbird, crow, glassfin, ...) go in with the same schema as `enabled: false` rows (id, name, sprite, footprint, loot, notes carried over from the bible); the simulation owners choose temperament and flip `enabled`. Birds use a `flight: true` flag (the kernel treats them as unblockable by footprint and never bouncing off walls) and fish stay on the legacy lake loop until a `swim` brain exists.

## 9. Test plan and gates

* `tests/test_creatures_table.py`: schema validation (every row, bad rows rejected with the name), ids pinned (40..69 as in section 4), prey names resolve, `install()` mutates the legacy dicts to the same values the legacy file holds for the five legacy species (parity), table exports JSON equal to the checked-in asset-side list.
* `tests/test_creatures_spawn.py`: the plan is a pure function (same input, same output; independent of call order and of the process); positions legal; no entry exceeds the generator's `max`; quota respected in the fixed order; the generator's chunk bytes unchanged (sha256 of three golden chunks).
* `tests/test_creatures_kernel.py`: state machine cases on hand-built worlds (flee, chase, cohere, territory return, cooldown, activity throttle by time block, never attacks a protected state, bounce at the unintegrated border); replay determinism (two runs, same seed, same rows bit for bit); a randomized comparison with the legacy predator loop restricted to sheep/deer/wolf (kills happen at comparable rates; this is a parity, not identity, test since the legacy uses `random`).
* `tests/test_harness_creature_store.py`: stash/restore round trip, attribution by position (a creature wandered into another chunk), catch-up clamps (never starves while stored, dies of age deterministically), quota, rebase, release/despawn events seen by the client only if announced, snapshot option (a).
* Real-window test: walk a controlled human 6 chunks east and back; creature population stays inside the quota, no duplicates after return, row count back to baseline, the same uids reappear.
* Gates unchanged: strict goldens x4 flag off, s1 digests (a2fcc8cbdd7143c8, f83fed5436dd08fe), window_walk/window_saves; plus `EDEN_CREATURES=1 EDEN_WINDOW=1` goldens (new golden `--creatures`) on an authored chunk set with a fixed seed.
* Size: M-L, in order: (1) table + validation + export (no engine), (2) spawn plan (pure), (3) store + window glue behind the flag with legacy species only (wolf/deer/sheep from the generator's spawns), (4) kernel + the two identity hooks, (5) new species data, (6) client payload keys (`species`, `sprite`, `state`, `footprint`) as additive fields with the flag on, documented in the client contract.

## 10. Decisions needed from c3

1. Approve the shape (table in `systems/creatures`, kernel as one flag-gated instinct, store like the structure store, spawn plan from the generator's `data.spawns` and POIs, no generator change).
2. Approve the legacy edits: the two identity hooks (`legacy_rows`) in `instincts_and_tools.py`; `map_test.py` `_build_frame_payload`/`_export_animal` additive keys (step 6, with the flag only); a short `genesis_config.py` registry addition for the new ids if `install()` cannot cover the type registry (I expect it can).
3. Ids and names in section 4 as the asset side's contract (c3 to pass on).
4. Saving: (a) regenerate, as proposed, pending the user's format 4 decision; no text is written either way.
5. Loot item ids: [REQUEST] to latenight2 to add `meat, hide, bone, feather, egg` to the catalog and to turn `HUNTABLE`/hostile sets into table lookups.
6. Whether the first run should use the numbers in section 8 or wait for the simulation owners' temperament choices (the bible says they decide; my default is to ship them as the starting data).

## 11. As built (approved by c3 on 2026-10-09; steps 1-3)

* **Decisions of c3**: shape approved; legacy edits approved (identity hook in the two animal loops, additive flag-on frame keys; both still to come with step 4 and 6); the id list is the asset contract (frozen in `tests/test_creatures_table.py` plus `tests/fixtures/creatures_contract.json`); saving = option (a); the section 8 numbers ship as starting data.
* **Balance note (c3)**: tune after seeing the creatures in a village scenario. Targets: a wolf pack against the family farm kills rarely but really (casualties per day rare but real), hunters can win, deer are not extinct after 10 game days. Not measured yet: it needs the kernel (step 4) and the hostile spawns.
* **Step 1 (cb87bfb)**: `systems/creatures/table.py` (29 rows, ids as section 4, `validate()` at import, `export()`), `tools/export_creatures.py`, `tests/test_creatures_table.py`. The legacy five match `genesis_config` exactly (life expectancy, scale, aggression, step, prey) so installing the table can never change them.
* **Step 2 (40d0f05)**: `systems/creatures/spawn.py`, a pure blake2b-hash plan over a chunk document (`data.spawns` for the generator's species, the companion rule for the fox, `data.pois` for the hostiles); `MAX_PER_CHUNK = 12`; `spawn_p` per species (wolf 0.08, deer 0.12, sheep 0.10, boar 0.15, fox 0.12, goblin 0.6, skeleton 0.7, giant spider 0.5). Seed 1008 around the origin: 23 creatures in the 5x5 ring, 53 in the 7x7. The generator and the chunk sha256s are unchanged (pinned in `tests/fixtures/creatures_chunk_hashes.json`).
* **Step 3**: `harness/creature_store.py` and four hooks in `window_manager.py` (`tick`, `integrate`, `unload`, `load`) plus the boot refusal in `engine_hooks.py` (`EDEN_CREATURES=1` without `EDEN_WINDOW=1`).
  * Populate: on integrate (and lazily from `tick` after a load) the plan's missing creatures are allocated, uid-deduplicated against live rows and stored records, up to the quota (`EDEN_CREATURE_ROWS`, default 96) and the free rows. Creature rows are removed from `allocator.owned`, so they are not part of the 800-row window budget. A populated chunk refills killed creatures only after `RESPAWN_DAYS = 2` game days without a visit.
  * Stash: `on_unload` stores every creature standing in the unloading chunk; `sweep` (every 20 ticks) stores creatures standing outside every integrated chunk under the chunk they stand in (so a wanderer is never frozen forever by dormancy). Records hold the row minus position, generation and space, plus the offset from the chunk corner (re-base proof) and the tick; at most 512 records are kept, oldest dropped.
  * Restore: closed-form catch-up (age by `calendar.age_step`, hunger and thirst up but capped at 60 so storage never starves anyone, cooldown decayed); a creature past its life expectancy does not return.
  * **Species**: only `brain: legacy` species (sheep, deer, wolf) are spawned until `systems.creatures.kernel_ready()` is true (step 4), so no table-brain creature wanders with the legacy brownian loop and starves.
  * **Saving, plainly**: nothing of the store (records, populated ledger) is saved and no refusal is raised. The creatures standing in the integrated chunks are ordinary rows and the world saves them with the tensors; after a load the integrated chunks are populated again from the plan without doubling the live ones. What is lost on save/continue: wounds, kills and the whereabouts of stored creatures. **A creature the player killed comes back after a reload** (the kill ledger is not saved). Revisit when real persistence of ecology is wanted.
  * Tests: `tests/test_harness_creature_store.py` (13: plan populates, quota, flag off inert, stash/restore bit for bit, catch-up, death of age, wanderer sweep, re-base proof offsets, respawn days, load without doubling, boot refusal).
* **Model-plane interface (latenight2, landed with step 3)**: table lookups `by_type`, `name_of`, `hostile_types`, `huntable_types` (legacy sets while the flag is off), `loot_of`, `threat_of`, `perceive_radius_of`, and the fields `tame`, `products`, `threat`, `perceive_radius`, `carcass`; loot item `fish` renamed `fish_catch`; a test checks every loot/product item against the inventory catalog.
* **Still to do**: step 4 (the kernel, the two identity hooks, `install()`, `creature_killed`, `kernel_ready()`), step 5 (table-brain species spawn; client keys), step 6 (frame keys). The balance scenario comes after step 4.

### Step 4 as built: the kernel

* `systems/creatures/kernel.py`: `step(engine)` is registered as the step hook `harness_creatures` (after `harness_window`, so a chunk is populated before its creatures act) when `EDEN_CREATURES=1` and `EDEN_WINDOW=1`; `install()` (called at the same time, `uninstall()` removes exactly what it added) writes the table into the five legacy dictionaries for every species except the legacy five and adds the `MAP_SCHEMA` entries (label, attrs including `variant` and `behaviour`) so births, ageing and the client's `type_label`/`state` know the new ids.
* Per tick, vectorised over the creature rows of the `brain: table` species (no loop over animals, no `random`): activity throttle by time block, perception (C x humans and C x animals distance matrices), the state machine in the order wander < cohere < return < chase < attack < flee, movement by walk/run speed clamped to the window frame, attacks through `apply_human_damage` / `apply_entity_damage` (human victims get THREAT 100), an attack cooldown in `C_STATE_TICKS`, `C_STATE` written for the client. `diet.eats == ["none"]` (skeleton) keeps hunger and thirst at 0. Chase decisions are per 20-tick epoch (probability `aggro`); wander headings stand 32 ticks. Rolls are `unit(tick, slot, generation, stream)`, a pure hash, so a replay is exact (tested: same slot and generation, same path).
* `creature_killed {id, slot, species, pos, killer_uid}` is queued once per dead creature row at the end of the tick (before the legacy `animal_instinct_die` zeroes it). `killer_uid` is the killing creature's uid for kernel kills and None for any other cause (a human's hit, starvation): the resolver's outcome rows carry the human killer, the model plane can join on `uid`. A kill feeds the killer (hunger -30).
* The two identity hooks (`_legacy_animal_rows` in `instincts_and_tools.py`, 21 lines): `animal_instinct_move` and `animal_instinct_predator_attack` skip the rows of the table-brain species when the flag is on; with the flag off the mask is returned as is (same object, tested). Strict goldens x4 and the s1 digests are unchanged.
* `kernel_ready()` is now true, so the store spawns the table-brain species (boar, fox, goblin, skeleton, giant spider) with the plan; the legacy-brain trio (sheep, deer, wolf) keeps the legacy loops until the parity/balance run.
* Known limits (v1): creatures ignore terrain and walls (as the legacy animals do); births from `animal_tool_reproduce` of new species get hp 100 and no group/variant (the legacy newborn), and reproduction is not capped by the creature quota; the kill ledger and wounds are not saved (see the saving note above).
* Tests: `tests/test_creatures_kernel.py` (21: flag off identity, legacy loops skip the table rows and still move a legacy row, boot hook order, install/uninstall exactness, hash properties, wander/replay/leash/cohesion/dormancy/frame clamp, fear, hunt, hunger gate, cooldown, cornered boar, skeleton, kill event once with killer, death without killer).

### Step 4b as built: collision (decision CREATURE-KERNEL) and step 5: the frame key

* `systems/creatures/collide.py`: `resolve(engine, start, desired, kind)` slides every kernel move through the boxes the humans' `slide()` uses (the window's chunk boxes - rock, ruin walls and water bodies come from the footprint layer -, the void boxes, the placed maps' boxes, the live `M_WALL` rows), vectorised over the creatures, float64, the same X-then-Y sweep and 1e-4 tolerances, no randomness (the box tensor is cached on the window revision; 96 creatures against 178 boxes cost about 1 ms inside a 4 ms kernel step). Differences from `slide`, each on purpose: a creature that starts in the margin of a wall is not frozen but can never enter the raw box; one inside a raw box (a wall built on it) may walk out.
* Three classes from the table flags: land (all boxes, plus a terrain-water test for shallows the footprint layer misses), `flight` (ignores the generated chunk boxes, not built or interior walls) and `swim` (ignores the generated boxes, may only stand on water tiles; glassfin, disabled today). Fish stay on the legacy loop and are not touched.
* `blocked_segments`: a blow needs a clear line; a wall box between attacker and victim cancels the attack (found while testing: a skeleton reached over a 4-unit wall).
* Space != 0: the kernel moves only space-0 rows and clamps to the window frame; pockets and interiors lie outside that frame and behind their slabs. Tested with a resident in a pocket (the skeleton stops at the frame limit) and a creature row inside a space (not moved).
* Not done: creatures do not path around obstacles (they slide along them and stop at a dead end), and a creature stuck against a wall while chasing gives up when the epoch changes.
* `systems/creatures/frame.py` + two lines in `map_test._export_animal` (flag on only): `animals[].creature = {species, sprite, footprint, state, variant}`; documented in `../contracts/client_contract.md` section 5b. Flag off: no key, no behaviour change.
* Tests: `tests/test_creatures_collide.py` (19: slide maths, closed room vs door control, blow gate, built wall, flyer/swimmer/land, lake, pocket), `tests/test_creatures_frame.py` (4).

### R0.3 as built: 10-day long-calendar balance (2026-11-18)

* Probe: `tools/creature_balance.py --days 10 --brain kernel --calendar user --seed 1` (`EDEN_CALENDAR=1`: 12,000-tick day, one life-year per day; sheep, deer and wolf on the table brain; 6 residents fed every tick so deaths measure creature pressure; residents do not fight back and a dead resident respawns in place). Each run took about 90 min in a `git archive` extract at a short path. Evidence: `.orchestration/wsim/reports/r03-*`.
* Baseline (fc69f3c, C:\e4, 12:47-14:20): start sheep 5, deer 6, boar 5, fox 1, no wolves.
  * Wolves 9 on day 1, 30 on day 10. Sheep 17 -> 9, deer 15 -> 9, boar 5 -> 1.
  * 551 resident deaths, all on day 9, all from one wolf. With `cooldown=1` it bit every 2 ticks for 15 HP and killed a resident in 14 ticks. Attribution is instrumented: 551 creature, 0 unattributed.
  * Duel estimate (closed form, not observed): wolf 0.3 s to kill a resident, hunter 5 s to kill a wolf.
* Causes:
  * (1) Wolf (and tiger) `cooldown=1` is the legacy value. The kernel reads it as ticks between bites (300 dps).
  * (2) `animal_tool_reproduce` gives a mature female one birth per life-year, which is one game day under the calendar. Packs grew daily, prey collapsed, and hungry wolves (`humans: "hungry"`) turned on residents.
* Changes (owner 1118: "thorough fix, do both"):
  * `table.py` data: wolf and tiger `cooldown` 1 -> 20 (15 dps: 6.7 s to kill a resident vs 5 s for a hunter).
    * Only the kernel reads `cooldown`. Both rows keep `brain="legacy"`, and `export()` has no behaviour numbers.
    * 24 was tried first and failed `test_creatures_parity` test_2 (the kernel pack killed 0 of 12 prey in 1,200 ticks). 16 and 20 pass.
  * `instincts_and_tools.animal_tool_reproduce`: the post-birth recovery is `year_ticks / life_year_ticks` life-years instead of `1.0`.
    * Legacy: 600/600 = 1.0, so flag-off is bit-identical.
    * Calendar: 8.0 = one calendar year (8 game days), so one birth per mature female per calendar year.
    * The decay is unchanged, so the creature store's decay stays consistent.
  * New `tests/test_animal_birth_calendar.py`: 2 F + 2 OK -> 4 OK.
* Counting run (fc69f3c + both changes, C:\e5, 14:44-16:08, exit 0):

| day | sheep | deer | wolf | boar | fox | kills | resident deaths |
|---|---|---|---|---|---|---|---|
| 1 | 17 | 11 | 9 | 5 | 1 | deer 1 | 0 |
| 3 | 17 | 17 | 7 | 5 | 1 | - | 0 |
| 5 | 13 | 17 | 7 | 5 | 1 | - | 0 |
| 7 | 12 | 14 | 6 | 5 | 0 | - | 0 |
| 9 | 5 | 24 | 11 | 3 | 1 | - | 0 |
| 10 | 7 | 20 | 11 | 1 | 0 | - | 0 |

* Verdict per target:
  * Wolves no longer explode (9 -> 11 over 10 days; baseline 30). Deer grow 11 -> 20.
  * **Sheep (17 -> 7) and boar (5 -> 1) decline with almost no recorded kills** (1 kill in 10 days). This is believed to be old age (boar life 8-15 life-years = days; sheep `life_exp` is pinned legacy) with births slowed to one per 8 days. Not verified: the probe attributes kills and resident deaths only, not animal deaths of age or hunger. Boar is near extinction by day 10. Open.
  * The fox count flickers between 1 and 0 (single animal, not explained; open).
  * Resident deaths: 0 (baseline 551). "Rare" holds; "possible" was not shown in 10 days.
  * Hunters can win: wolf 6.7 s vs hunter 5 s (estimate, not observed; a live hunter-vs-creature duel was not exercised).
  * No bug deaths: none in the counting run. The earlier partial-run cases (a wolf death at probe tick 52114, a resident death on day 7) did not recur in either run.
* Flag off: 4 strict goldens (default, `--resources`, `--spaces`, `--window-hook`) report no drift (11 checkpoints), on fc69f3c and again on 506f6c6 with the three files on top. Singles OK: creatures table 21 / parity 4 / kernel 21 / feed 11, harness_spaces_columns 18, harness_calendar x6.
* Not done: per-species birth rates or litter sizes, an age/hunger death breakdown in the probe, and a run longer than 10 days.

### F3 as built: breeding hold and litters (2026-11-19, `88b8c36`)

* Table key `litter` (int 1..8, default 1; sheep 2, boar 2). `animal_tool_reproduce` bears `litter` young per birth under a non-legacy calendar and one under the legacy calendar; recovery unchanged (one calendar year).
* Kernel breeding hold `hold_cooldown()` = `HOLD_COOLDOWN x LEGACY_YEAR_TICKS / life_year_ticks` (1.0 legacy, 0.05 under `EDEN_CALENDAR`: the same 600 ticks), used at both clamp sites (crowded pasture, hungry).
* Tests `tests/test_f3_litter.py` (6), `tests/test_f3_hold.py` (4), `tests/test_animal_birth_calendar.py` (flag-on cases expect the litter). Probe `tools/f3_animal_deaths.py` (death cause per uid, breeding female-ticks).
* Balance still open: single-seed 10-day counts are noisy (sheep 14 vs 3 between runs); thirst is the main sheep killer (F4); wolves breed again in calendar year 2 (F5). Evidence: `.orchestration/wsim/reports/f3_decline.md` (not in git).

### F4 as built (2026-11-23)

* Gate: these rules apply to the creature kernel under a non-legacy calendar (`long_calendar()`, with `EDEN_CALENDAR` enabled); legacy calendar behavior is unchanged.
* Thirst: species with no prey search for water up to `WATER_SEARCH_LONG = 1024` units, and their thirst walk beats the home leash. Predators retain the 240-unit search and the leash wins over thirst (flight and chase retain their existing priority).
* Wounds: a wounded creature flees a human or a harmful other species within `WOUND_RANGE = 120`; a harmful species can damage, prey on, or be feared by it. The nearer threat supplies the flee origin. Existing fear-driven flight remains in effect.
* Newborn home: a creature without a home adopts the home of the nearest same-species creature with one within `ADOPT_RADIUS = 16` units, else its birth chunk. The home is cached per uid and gives the newborn the usual leash; the cache is not persisted across save/load.
* Tests: `tests/test_f4_thirst.py` (7), `tests/test_f4_flee.py` (7), and `tests/test_f4_home.py` (10). The prior F4 implementation passed all four strict flag-off goldens with no drift. Seed evidence and limitations are in `.orchestration/wsim/reports/f4_seeds.md`.
* F4-2b: an in-progress follow-up redirects a homed thirsty predator that finds water beyond its leash toward the water nearest its home, if that water is within the leash. The diversion persists while thirsty to cross gaps in the ordinary search radius; the leash remains in force. `tests/test_f4_predator_water.py` exercises this behavior, legacy behavior, and the no-home-water case. Ten-day seed acceptance for wolf thirst and resident deaths remains pending; this follow-up is not yet accepted.
