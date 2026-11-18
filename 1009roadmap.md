# 1009 roadmap: from the 1008 stage to a playable, intelligent, endless village

Owner: orchestrator session `1008orchestrator` (does not implement; assigns, verifies, records).
Written: 2026-10-09 (branch `1008implementation`, local only, HEAD at writing `56876b4`).
Plan of record it extends: `1008implementation.md` (workstreams WS-A to WS-H, gates A to H, phases P0 to P7).
Ledger it is traced against: `1008decisions.md` (every row id quoted below, e.g. `GATEE-FINAL`, is a row in it).

This file is the single place to see what is done, what is next, what is held, and where the evidence is. It does not replace the design docs; it points at them.

## 0. How to read and trace this roadmap

- **Item ids** look like `R2.4`. Phase `R2`, item 4. Ids never change and are never reused.
- **Status** is one of: `DONE` (built, tested, flag-off identical, evidence cited), `DONE*` (built and tested, but a named gate or run is still owed), `IN FLIGHT`, `NEXT`, `QUEUED`, `HELD` (waiting for the user), `BLOCKED` (waiting for another item).
- **Evidence** is a commit hash (`git show <hash>`), a ledger row (`grep -n "^| ROWID" 1008decisions.md`), or a design doc section. If an item has no evidence it is not `DONE`.
- **Flag** is the environment variable that turns the feature on. Every new feature is default off (user decision D-002 and the Stage 1 compatibility rule); flag off must stay bit-identical to Stage 1 (proved by the strict goldens).
- **Owner** is a track, not a person: `Harness/engine` (session 9d882a, `1008latenight`), `Model plane` (session c0853f, `1008latenight2`), `Assets` (Codex agents via the orchestrator), `Client` (Codex, `godot_client_2d/`), `User`.
- **Update protocol.** When an item changes status, the orchestrator edits this file in the same pathspec commit as the ledger row that records it. A status change without a ledger row is a bug in the process.

### 0.1 Rules of engagement that every item inherits

1. Pathspec commits only (never `git add -A`, reset, stash, checkout, clean). One shared working tree, strict path ownership.
2. No push of `1008implementation` unless the user says so (D-004).
3. Godot and `myassets/` (images, video, large files) are never committed; `godot_client*/` and `game_frontend/dist/` edits in the tree are not ours.
4. Heavy runs hold `.runtime/fullsuite.lock` (NORMAL or MEASURE) with a real ETA; a failed lock take aborts the whole script; delete only your own lock; MEASURE means nothing else runs.
5. Clean verification runs use a `git archive` extract at a short path with `myassets/` and `tests/fixtures/maps/sprites/` copied in. Test command: `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'`. Strict goldens: `tools/golden_trace.py --check --strict` (default, `--resources`, `--spaces`, `--window-hook`).
6. Real models, hosting, training are out of scope until the user supplies APIs (P7 held; Clef details held).
7. Tags between sessions: `[ACK] [GAP] [DECISION] [VERIFY] [BLOCKED] [DONE] [STOP]`. Workers forward gaps and design choices; the orchestrator decides inside user direction and brings the rest to the user one at a time.

## 1. Where we are (snapshot, 2026-10-09)

| Measure | Value | Evidence |
| --- | --- | --- |
| Code HEAD (docs on top) | `4690536` code, `56876b4` ledger | `git log --oneline` |
| Last clean full suite | 2002 tests OK (26 min) at `330d4a7`; goldens no drift | `FULLSUITE-2002` |
| Tests added after that | emotion and calendar C5 (`afc80a2`, `4690536`); gate on `4690536` was running when the user said stop and did not finish | `EMOTION-C5` |
| Tick cost, 30 roster residents, window flags on | mean about 38 ms (budget 50), p99 about 54 | `PERF-ENSURE` |
| Tick cost, 50 / 100 residents | about 69 / 131 ms (not met, stretch) | `PERF-ENSURE` |
| Commits on the branch | 400 | `git log --oneline \| wc -l` |
| New-feature flags | about 35 `EDEN_*`, all default off (inventory in section 7) | `grep EDEN_` |
| Last user stop | 2026-10-09, both worker sessions stopped cleanly, no locks held, no uncommitted worker files | session log |
| Pushed to GitHub | no (local only) | D-004 |

### 1.1 Interrupted by the stop (restart these first)

| Id | What | Owner |
| --- | --- | --- |
| R0.1 | Clean-archive gate on `4690536` (strict goldens, then full suite, about 33 min) | Model plane |
| R0.2 | Flag-off golden on the final head (covers sleep, darkness, clothing commits) | Harness/engine |
| R0.3 | 10-day user-calendar balance run, killed at day 4 with one wolf death at probe tick 52114; table, duels and the day-7 death cause still owed | Harness/engine |
| R0.4 | Third calendar refusal text (save and session both long calendar but different lengths); draft is in the ledger discussion and in this file, section 8 | User |

## 2. Phase map

| Phase | Name | Status | Exit condition |
| --- | --- | --- | --- |
| R0 | Close the current batch | NEXT | R0.1 to R0.4 closed, one clean full suite at HEAD |
| R1 | Foundations (model plane, harness, Tier 0 to 3 contracts) | DONE | Gate A, harness gates |
| R2 | Resident intelligence and social economy | DONE* | Gate B/C evidence plus commons scenarios |
| R3 | Endless map: chunks, spaces, window, dormancy | DONE* | Gate D evidence, Gate E closed |
| R4 | Living world: calendar, climate, creatures | DONE* | balance table under the long calendar (R0.3) |
| R5 | Client integration and assets in the game | NEXT (largest gap) | Gate F: windowed Godot acceptance |
| R6 | Remaining world depth | QUEUED | verbs, market M2, settlements, offscreen village, tools |
| R7 | Defaults, hardening, packaging | QUEUED | flags decided, full suite with the chosen flags, cleanup, push on the user's word |
| R8 | Real models (Tiers 1 weights, 2, 3) | HELD | user supplies APIs |
| R9 | Art and content expansion | IN FLIGHT | production kit, animation path, more content |

R5, R6 and R9 can run in parallel with R0 once the machine is free (different files); R7 needs R0 to R6 decisions; R8 needs the user.

## 3. R1 Foundations (DONE)

| Id | Item | Status | Flag | Evidence |
| --- | --- | --- | --- | --- |
| R1.1 | LLM switch: every tier off/shadow/on, default off (D-002) | DONE | `EDEN_TIER1/2/3_*`, `/control/models` | `1008_model_api.md`, `1008_tier3.md` |
| R1.2 | Model plane: wire contract, mock FastAPI server, breakers, budgets, stale guard | DONE | `EDEN_MODEL_*` | `1008_model_api.md` |
| R1.3 | Gate A: 30 min against the mock with injected faults, tick p99 unchanged | DONE | none | `SWEEP-FIX` (sweep stress pair p99 +0.70 ms vs +2 ms limit) |
| R1.4 | Harness: World facade, SpaceFrame, Effects/ItemPermit, EventLedger, powers, scheduler hooks, golden traces | DONE | `EDEN_HARNESS` | `1008_scheduler_design.md`, `tests/golden/*`, `FRONTIER-GOLDEN` |
| R1.5 | Frozen old frontier tools and legacy 3D/web paths kept in the repo, not used (D-005) | DONE | none | `1008_frontier_freeze_diff.md` |
| R1.6 | Exact 64-bit acquired-instinct masks (three 24-bit float words) | DONE | none | `G-D0-2-DEC`, `1008_g_d0_2_plan.md` |
| R1.7 | Bounded perception, cdist and clamp fixes kept (D-006, D-007) | DONE | `EDEN_PERCEPTION_BOUNDED` | `PERCEPTION-DONE` |

## 4. R2 Resident intelligence and social economy (DONE*)

Principle (D-008, user): every resident is decision-driven; Tier 1 matrix by default without any LLM, then Tier 2 Clef, then Tier 3 LLM on escalation. The roster driver stays as the rules baseline.

| Id | Item | Status | Flag | Evidence |
| --- | --- | --- | --- | --- |
| R2.1 | Affordance engine and action layer (37 catalog verbs, runner pipeline, rate/risk gate) | DONE | `EDEN_AGENT_ACTIONS` | `AGENT-ACTIONS-DONE`, `1008_actions.md` |
| R2.2 | Agent driver equals anchor driver tick-by-tick; Tier 1 acceptance 5/5 | DONE | `EDEN_ROSTER_DRIVER=agent`, `EDEN_AGENT_TIER1` | `TIER1-ACCEPT`, `1008_agent_driver_design.md` |
| R2.3 | Matrix weights v2 (imitation, deterministic, versioned, rules prior fallback); pure matrix (prior 0) fails acceptance and is slower, so rules prior stays default | DONE | `EDEN_MATRIX_WEIGHTS`, `EDEN_MATRIX_PRIOR_STRENGTH` | `WEIGHTS-V2` (`c0b35d9`), `PURE-MATRIX-SWEEP` |
| R2.4 | Tier 2 DecisionRequest builder, off/shadow/on, mock only | DONE | `EDEN_AGENT_TIER2` | `TIER2-BUILDER` (`ec53205`) |
| R2.5 | Tier 3 adapters with confidence gate and typed context; escalation sweep amortised | DONE | `EDEN_TIER3_*` | `1008_tier3.md`, `SWEEP-FIX` |
| R2.6 | Escalation ladder (forage, trade, beg, steal) and reputation with gossip | DONE | `EDEN_AGENT_LADDER`, `EDEN_REPUTATION` | `R5B-ACCEPT` (`f7fa833`, `9e61f82`) |
| R2.7 | Market M1: stalls, buy/sell/price from supply and demand, coin conservation | DONE | `EDEN_MARKET` | `D5-M1` (`96c7cef`), `1008_market_justice_design.md` |
| R2.8 | Credit (borrow, lend, debts, default) and labour (work_for, wages) | DONE | `EDEN_CREDIT`, `EDEN_LABOUR` | `CREDIT-LABOUR` (`c07995f`) |
| R2.9 | Justice: authority, cases, fines at 1.5 times stolen value | DONE | `EDEN_JUSTICE` | `JUSTICE-C3` (`ddaf7b1`) |
| R2.10 | Guards (defend phase 0), combat hook and restraint (phase 1), robbery and arrest | DONE | `EDEN_DEFEND`, `EDEN_RESTRAINT`, `EDEN_ROB` | `DEFEND-DESIGN`, `DEFEND-P1-DONE` (`fd8c110`, `febf786`), `REACH-ROB-ARREST` (`75c809f`) |
| R2.11 | Bonds (court, befriend, apologise, forgive) and place memory | DONE | `EDEN_BONDS`, `EDEN_PLACES` | `BONDS-PLACES` (`bf42b80`) |
| R2.12 | Care (light_fire, treat_wound), clothing, Tier 1 features cold/fear/wounded/tired/dark | DONE | `EDEN_TEMPERATURE`, `EDEN_WOUNDS` | `CARE-FEATURES` (`bf59c5c`, `59d9796`, `a3f7bd3`) |
| R2.13 | Emotions: grief, comfort, jealousy, loyalty, grudge decay, curiosity and thrift drives | DONE* | `EDEN_EMOTION` | `EMOTION-C5` (`4690536`); gate R0.1 owed |
| R2.14 | Combined scenario `commons` (market, credit, labour, justice, reputation): no deaths, coin conserved, deterministic | DONE | all of the above | `COMMONS-DORMANT-LN2` (`5fdad04`) |
| R2.15 | Verb-side path-search cap | DONE (default unset) | `EDEN_REACH_MAX_DISTANCE` | `REACH-ROB-ARREST` (`ae268e1`) |

Known balance issues carried forward: the commons village lives at the ration floor and cannot pay wages (`COMMONS-DORMANT-LN2`); the pure matrix is 2 to 5 times slower because it chooses socialise often (`PURE-MATRIX-SWEEP`). Both are R6 tuning items.

## 5. R3 Endless map (DONE*)

Principle (user): render and simulate near the player, generate ahead of approach, efficient (D11). Interiors are separate spaces (D-001).

| Id | Item | Status | Flag | Evidence |
| --- | --- | --- | --- | --- |
| R3.1 | Chunks 32x32 tiles, routes `/chunks`, `/chunk/{cx}/{cy}` (ETag, 503 pending), deterministic worldgen | DONE | `EDEN_CHUNK_ROUTES` | `1008_worldgen.md`, `P1-DONE`, `P2-DONE` |
| R3.2 | Spaces (Option L): first-class space identity, 32 interior pockets, masks guarantee isolation | DONE | `EDEN_SPACES` | `SPACES-DESIGN`, `P3-DONE` |
| R3.3 | Window with re-base at 2 chunks, row budget 800, origin invariance, save formats 1/2/3 with approved refusal texts | DONE | `EDEN_WINDOW` | `P4P5AB-DONE`, `1008_spaces_p4_p5_gap.md` section 11 |
| R3.4 | Map resources in authored maps (G-005), `family_farm` map and interiors | DONE | `EDEN_MAP_RESOURCES` | `G005-DONE`, `FAMILY-FARM` (`5857662`) |
| R3.5 | Client contract: chunk loader and interior-space fields (C1, C2) | DONE (client side only) | `EDEN_CLIENT_CHUNKS` | `CLIENT-C1`, `CLIENT-C2`, `godot_client_2d/C1_CHUNK_LOADER_REPORT.md`, `C2_SPACES_REPORT.md` |
| R3.6 | Gate E: window tick within 5 ms of base (mean), 1 percent of ticks over 50 ms, no spike over 250 ms after tick 50 | DONE | none | `GATEE-CAUSE`, `GATEE-FIX`, `GATEE-FINAL`, `GATEE-CLOSED` (`a4185fa`, `1782ddb`, `ee6307a`, `1d11655`) |
| R3.7 | Real-server window smoke (47 checks) and a real walk: 3,400 units, epochs 0 to 4, 0 rejected inputs | DONE | window flags | `WINDOW-SMOKE`, `WALK-FIXED` (`431006e`, `e544adb`, `815daed`) |
| R3.8 | Re-base follows the controlled player; clamps replaced by `world_limits()` | DONE | window flags | `WINDOW-WALK-BUGS`, `WALK-FIXED` |
| R3.9 | Interim dormancy for residents and animals outside the frame (frozen, closed-form catch-up capped at hunger 80, thirst 75) | DONE | `EDEN_WINDOW_DORMANCY` | `DORMANCY-LN` (`ffeeced`, `b13eb77`, `c680bd7`) |
| R3.10 | Dormant structure store, save format 4 only when non-empty, approved refusal text | DONE | `EDEN_STRUCTURE_STORE` | `STRUCTURE-STORE` (`540f384`), `USER-DEC-6`, `CALENDAR-C4` (`b5cbf56`) |
| R3.11 | Quadratic-scan rewrites (mate, help, support, attack target, masks); `EDEN_ENSURE_ONCE` | DONE | `EDEN_ENSURE_ONCE` | `SPATIAL-DONE`, `PERF-ENSURE` |
| R3.12 | Gate D (determinism, 5,000-unit walk, edits survive unload) | DONE* | none | window-walk golden, finite-window golden `ddf042f`; a 5,000-unit run is not recorded (live walk reached 3,400); to be added in R0 |

## 6. R4 Living world (DONE*)

| Id | Item | Status | Flag | Evidence |
| --- | --- | --- | --- | --- |
| R4.1 | Calendar: 12000-tick day, 8-day year, season 2 days, one life-year per game day, rate classes as config data (needs 0.21, damage 0.2, regrow 0.2, farm 0.04, weather 30, action 1.0, starvation 0.0015) | DONE | `EDEN_CALENDAR` | `1008_calendar_gap.md`, `PART2-DEC`, `CALENDAR-C4` (`0c64f1f`, `e373dc5`), `EMOTION-C5` (`afc80a2`) |
| R4.2 | Calendar save refusals #1 and #2 (user approved as written) | DONE | `EDEN_CALENDAR` | `USER-DEC-6` (`b5cbf56`) |
| R4.3 | Perception scale by light; sleep pressure; darkness unease | DONE | `EDEN_SLEEP`, `EDEN_DARKNESS` | `CALENDAR-C4` (`2eade37`, `7a81dee`) |
| R4.4 | Temperature, wounds, danger memory, steering (steering changes the roster golden when on) | DONE | `EDEN_TEMPERATURE`, `EDEN_WOUNDS`, `EDEN_DANGER`, `EDEN_STEERING` | `BALANCE-WINTER`, `1008_instincts_wiring_gap.md` |
| R4.5 | Creature table (29 species, ids frozen, asset contract file), spawn plan, vectorised kernel, collision with walls and terrain, client frame keys | DONE | `EDEN_CREATURES` | `CREATURES-GAP`, `CREATURES-STEPS-INSTINCTS`, `CREATURE-KERNEL`, `CREATURE-COLLIDE-DEFEND0` (`cb87bfb`, `40d0f05`, `04d1300`, `2a5993c`, `1fc76e6`), `tests/fixtures/creatures_contract.json` |
| R4.6 | Creature graze, drink and finite pasture | DONE | `EDEN_CREATURES` | `BALANCE-WINTER` (`398d5fd`, `8abec74`, `fd00f09`) |
| R4.7 | Ecology balance under the long calendar (wolf pack vs `family_farm`, hunters can win, deer not extinct, causes of resident death) | IN FLIGHT (interrupted at day 4) | `EDEN_CREATURES`, `EDEN_CALENDAR` | R0.3; finding: under the legacy calendar animals age 4 years per day so legacy-calendar ecology is meaningless (`BALANCE-WINTER`) |
| R4.8 | Parity of legacy-brain wolf, deer, sheep versus the kernel before any species moves | DONE (4 tests) | `EDEN_CREATURES` | `tests/test_creatures_parity.py`; extension to all species is optional |

## 7. Flag inventory (all default off)

Models: `EDEN_TIER1`, `EDEN_TIER2`, `EDEN_TIER3_*`, `EDEN_MODEL_*`. Decision layer: `EDEN_ROSTER_DRIVER=agent`, `EDEN_AGENT_ACTIONS`, `EDEN_AGENT_TIER1=matrix`, `EDEN_AGENT_TIER2`, `EDEN_MATRIX_WEIGHTS`, `EDEN_MATRIX_PRIOR_STRENGTH`, `EDEN_AGENT_DECIDE_PERIOD`. Social: `EDEN_AGENT_LADDER`, `EDEN_LADDER_RUNGS`, `EDEN_LADDER_STARVE`, `EDEN_REPUTATION`, `EDEN_MARKET`, `EDEN_CREDIT`, `EDEN_LABOUR`, `EDEN_JUSTICE`, `EDEN_DEFEND`, `EDEN_RESTRAINT`, `EDEN_ROB`, `EDEN_BONDS`, `EDEN_PLACES`, `EDEN_EMOTION`, `EDEN_REACH_MAX_DISTANCE`. Body and world: `EDEN_TEMPERATURE`, `EDEN_WOUNDS`, `EDEN_DANGER`, `EDEN_STEERING`, `EDEN_SLEEP`, `EDEN_DARKNESS`, `EDEN_CALENDAR`, `EDEN_CREATURES`, `EDEN_CREATURE_ROWS`. Map: `EDEN_PERCEPTION_BOUNDED` then `EDEN_SPACES` then `EDEN_WINDOW` (plus `EDEN_MAP_RESOURCES`, `EDEN_CHUNK_ROUTES`), `EDEN_WINDOW_DORMANCY`, `EDEN_STRUCTURE_STORE`, `EDEN_ENSURE_ONCE`. Harness: `EDEN_HARNESS`, `EDEN_HARNESS_NEEDS`, `EDEN_HARNESS_RESOURCES`.
Dependencies: `EDEN_AGENT_LADDER`, `EDEN_REPUTATION`, `EDEN_MARKET`, `EDEN_CREDIT`, `EDEN_LABOUR`, `EDEN_JUSTICE`, `EDEN_DEFEND`, `EDEN_ROB` all need `EDEN_AGENT_ACTIONS`; justice needs reputation; rob needs ladder, reputation, justice, defend; arrest needs `EDEN_RESTRAINT`; dormancy, structure store and creatures need `EDEN_WINDOW`; Tier 2 builder needs `EDEN_AGENT_TIER1=matrix`.

## 8. R0 Close the current batch (NEXT)

| Id | Task | Owner | Done when |
| --- | --- | --- | --- |
| R0.1 | Clean-archive gate on current HEAD: strict goldens (default, `--resources`, `--spaces`, `--window-hook`), s1 digests (`a2fcc8cbdd7143c8` steal+reputation, `f83fed5436dd08fe` trade), commons digests (`2fbbeae222e2dbd0`, `506087d6cd7c03b7`), full suite | Model plane | suite green, counts logged in `1008decisions.md` |
| R0.2 | Flag-off golden for the sleep, darkness and clothing commits | Harness/engine | logged |
| R0.3 | Restart the 10-day long-calendar balance run (60 to 90 min, single process); report population table, duels (hunter vs creature, creature vs resident), cause of the day-7 resident death; tune section 8 of `1008_creatures_gap.md` data if needed | Harness/engine | table in `1008_instincts_wiring_gap.md` or `1008_creatures_gap.md`, ledger row |
| R0.4 | Third calendar refusal. Draft: "This save was made with a long calendar whose game day is {saved_day} ticks and whose year is {saved_year} ticks, but this session's long calendar has a game day of {now_day} ticks and a year of {now_year} ticks, so hunger, growth, weather and ageing would run at different rates and the save cannot be continued. Use the build the save was made with, or start a new world. The save file has not been changed." | User approves, then Harness/engine | text approved, code raises `SaveFormatError` |
| R0.5 | Record a 5,000-unit straight walk in the live smoke (Gate D wording) | Harness/engine | logged |
| R0.6 | Re-run emotion, care and calendar tests under `EDEN_CALENDAR=1` (market-scenario test is flag-sensitive) | Model plane | known exception resolved or documented |

## 9. R5 Client integration and assets in the game (NEXT, the largest gap)

Nothing from the 1008 stage is yet visible in the Godot client except the chunk-ground debug scene and the interior-space fields. Owner: Codex client sessions, with the orchestrator relaying contracts. Gate F (plan of record): a generated 3x3 chunk area renders with no seams, correct depth sorting, walls matching sprites, chunk load/unload at walking speed without frame drops.

| Id | Task | Depends on | Notes |
| --- | --- | --- | --- |
| R5.1 | Wire the chunk loader into the real game scene behind a flag; place authored maps (pinned-map placement handoff is undecided in C1); props and spawns from chunks | R3.1, R3.5 | `C1_CHUNK_LOADER_REPORT.md` open decisions |
| R5.2 | Window re-base in the client: origin shift, stamps (`window_epoch`, `window_shift`), 409 stale-window handling | R3.3 | contract section 4 |
| R5.3 | Render creatures from `animals[].creature` (`species`, `sprite`, `footprint`, `state`, `variant`); direction selection plus light bob; dead pose | R4.5, R9.3 | contract section 5b, `myassets/h008_creatures/ANIMATION_OPTIONS.md` |
| R5.4 | Calendar in the client: day/night lighting from `time` block, season tint | R4.1 | contract section 5c |
| R5.5 | Import accepted art into Godot (tiles h001, buildings h007, creatures h008, character kit h005) with nearest filtering; display scale: character master at 0.40 on the 48 px grid, buildings display copy at scale 1 | R9.1 to R9.3 | assets are never committed |
| R5.6 | Place buildings in authored maps and in generated settlements; footprints and doors become collision and anchors | R5.5, R6.4 | footprints are proposals |
| R5.7 | Windowed visual acceptance run (Gate F) with evidence screenshots | R5.1 to R5.5 | none exists yet |
| R5.8 | Place the spaces-aware portal regression test into the client tests directory | R3.5 | `evidence/stage2_parity/` copy |
| R5.9 | Chunk seam masks and mixed-biome junction priority decision | R5.1 | user-visible decision |

## 10. R6 Remaining world depth (QUEUED)

| Id | Task | Owner | Depends on / notes |
| --- | --- | --- | --- |
| R6.1 | Remaining catalog verbs: teach (needs a skill list), invite (invitation object), reflect (needs Tier 2/3 consolidation), repair (damage state), settle_site and migrate_group (settlement object), retaliate | Model plane | `1008_actions.md` 10.16 |
| R6.2 | Market M2: price formation, travelling merchants, spoilage (per-stack age, inventory schema), taxes and fines, saved market object | Model plane with Harness/engine (persistence) | `1008_market_justice_design.md` section 8 |
| R6.3 | Economy balance: opt-in implementation verified on four 4,000-tick commons seeds; current integration/full-suite gate and broader long-calendar sustainability still owed | Model plane | `ECONOMY-BALANCE-1010`; `coordination_evidence/codex_1010_r63_report.md` |
| R6.4 | Settlement object and settlement growth (construction as a living process, terraform) | Harness/engine | needs structure store (R3.10); `1008expandtools_instincts.md` 2.C3, 2.D1, 2.D3 |
| R6.5 | Full offscreen village simulation (coarse simulation for dormant villages) replacing interim freeze (P6) | Harness/engine | `1008_dormancy_gap.md` |
| R6.6 | Animals c2 and `window.integrated` | Harness/engine | `1008_client_contract.md` |
| R6.7 | Wire the remaining uncalled instincts (21), ambition/pride/territory drives; retire none | Harness/engine and Model plane | `1008_instincts_wiring_gap.md` |
| R6.8 | Port the 64 unported god tools (21 P1 first), add 15 new god tools, roads overlay | Harness/engine | `1008expandtools_instincts.md` Part 2.C |
| R6.9 | Creature extensions: reproduction cap by quota, newborn variants, creature attacks through the combat hook, killer identity for human kills, creature pathing around obstacles, more species enabled | Harness/engine | `CREATURE-KERNEL` limits |
| R6.10 | Scaled S3 opt-in correctness verified; task-bridge step 2, performance and combined integration gates remain pending | Harness/engine | `S3-SCALED-1010`; `1008_s3_s5_taskbridge_design.md`; `coordination_evidence/s3_scaled_gate_result.json` |
| R6.11 | Spatial index (chunk-keyed tile map) only if rows approach 400; stagger construction sync and escalation signals if 50 residents becomes a real scenario | Harness/engine | `1008_spatial_index_gap.md` |
| R6.12 | Arrest or restrain the player body: user game-design decision before anything is built | User | `DEFEND-P1-DONE` |
| R6.13 | Aux tensor for hot per-resident state (only human column 31 is free) | Harness/engine | design needed before any new per-resident column |

## 11. R7 Defaults, hardening, packaging (QUEUED)

| Id | Task | Notes |
| --- | --- | --- |
| R7.1 | Decide which flags become defaults and in which order (proposal: `EDEN_CALENDAR`, then window family, then creatures, then economy flags); each flip needs a golden re-record with the user's approval | Stage 1 compatibility is the default today |
| R7.2 | Full suite and goldens with the chosen flags exported; soak run (30 game minutes with the mock, then long) | Gate A style run for the final build |
| R7.3 | Suite isolation: shared `tests/engine_isolation.restore_after` for every test that installs handlers; known flag-sensitive tests | `FULLSUITE-2002` |
| R7.4 | Packaging cleanup after Gate D (D-003): dead code, frozen frontier tools stay but unused (D-005), docs index | user schedule |
| R7.5 | Push `1008implementation` to GitHub | only on the user's word (D-004) |
| R7.6 | Licence review for assets before any public release (imagegen output terms, Qwen commercial licence) | User |

## 12. R8 Real models (HELD, user supplies APIs)

No work until the user provides endpoints. Everything is built behind the mock so that this phase is configuration.

| Id | Task | Notes |
| --- | --- | --- |
| R8.1 | Point the adapters at real endpoints and run `tools/model_conformance.py` | P7 of the plan |
| R8.2 | Tier 2 Clef: real request and response mapping; shadow first, then on | details held by the user |
| R8.3 | Tier 3 roles resident, dialogue, world: shadow, then on per role | adapters and gates exist |
| R8.4 | Real Tier 1 weights from logged data or models (the v2 weights are imitation of the rules) | pure matrix fails acceptance today; needs the commission check discussion (`PURE-MATRIX-SWEEP`) |
| R8.5 | Feature schema v3 retrain if the Tier 1 feature set changes | additive instinct block already avoids it so far |

## 13. R9 Art and content expansion (IN FLIGHT)

All art stays git-ignored in `myassets/`; imports into Godot are R5.5. Generator: Codex with its own imagegen tool (Qwen local workflow replaced). Style direction accepted by the orchestrator on the user's behalf (`USER-DEC-5`): earth-tone pixel art, dark outlines, production grade not perfection, high resolution, 2x masters with exact 1x derivatives.

| Id | Item | Status | Evidence |
| --- | --- | --- | --- |
| R9.1 | Tile set h001 (202 tiles, 48x48) | DONE, user preview review still open | `H001-CODEX` |
| R9.2 | Character kit: modular paperdoll spec, 256 px masters (adult about 160 px, pivot [128,224]), boots, 4 tunic palettes, gripping hand | DONE static | `MODULAR-PILOT`, `H005-RESULT`, `1008expansion.md` |
| R9.3 | Buildings h007: shelter, peasant hut, farmhouse with barn, smithy, market shop, inn, manor, grand hall plus 4 variants | DONE | `H007-RESULT` (`97f81ec`) |
| R9.4 | Creatures h008: 10 creatures, 33 static poses, ids from the frozen contract | DONE static | `H008-RESULT` (`8561dc0`) |
| R9.5 | Walking animation. Imagegen frames failed (h005), automatic cut-out failed (h006). Options: separately authored limb parts, hand-pixeled frames, two-pose walk for wolf and boar | NEXT decision | `H006-RESULT`, `ANIMATION_OPTIONS.md` |
| R9.6 | Characters: children, elders, women, slim and sturdy builds, hair, headgear, boots variants, tools, armour; separate underwear impossible with imagegen (briefs stay baked) | QUEUED | `1008expansion.md` |
| R9.7 | Remaining creatures: dead poses for fox, sheep, goblin, skeleton, spider; 8 more invented species; north views | QUEUED | `H008-RESULT` |
| R9.8 | More buildings: dwellings between hut and manor, workshops, civic, walls, gates, ruins, fantasy structures, seasonal variants that are real art not tints | QUEUED | `H007-RESULT` |
| R9.9 | Props, flora, resource nodes, items and inventory icons for new items (meat, hide, bone, feather, egg, cloak, fur coat) | QUEUED | creature items request to Model plane |
| R9.10 | Imagegen licence check by the user before public distribution | HELD | every art report |

## 14. Gates, in one table

| Gate | Meaning | Status | Evidence |
| --- | --- | --- | --- |
| A | Model plane survives faults, tick p99 unchanged | PASSED | `SWEEP-FIX` |
| B | Tier 1 reproduces rules, cheap, shadow logs | PASSED for rules-prior; pure matrix not default | `TIER1-ACCEPT`, `PURE-MATRIX-SWEEP` |
| C | Affordance parity, 12 verbs end to end with mock Tier 3 | PASSED in substance (37 verbs plus registries); no single re-run check recorded | `AGENT-ACTIONS-DONE`, `D5-M1` |
| D | Determinism, long walk, save and edits | PASSED* (3,400-unit live walk, window-walk golden; add 5,000-unit run, R0.5) | `WALK-FIXED`, `GATEE-FINAL` |
| E (added) | Window tick cost | PASSED | `GATEE-CLOSED` |
| F | Client renders the generated area without seams | NOT STARTED (R5.7) | none |
| H | Golden traces, manifest | PASSED for golden traces; manifest drift test see `1008_coverage_map.md` | `tests/golden/*` |
| Stage target (added) | 30 residents, mean tick under 50 ms with the window on | PASSED (38 ms); 50 residents is stretch (69 ms) | `PERF-ENSURE` |

## 15. Decisions that govern this roadmap

User decisions (verbatim substance in `1008decisions.md`): D-001 interiors are separate spaces; D-002 every tier defaults off; D-003 packaging cleanup after Gate D; D-004 push only on the user's word; D-005 old frontier tools and legacy 3D/web paths stay frozen, not deleted, not used; D-006/D-007 keep the cdist and clamp fixes; D-008 all residents decision-driven; G-005 resources allowed in authored maps; `USER-DEC-3` theft and market as real and complicated as possible; `PART2-DEC` day = 12000 ticks, year = 8 days; `USER-DEC-4` paperdoll characters and creatures including fantasy hostiles; `USER-DEC-5` art review delegated, production grade, high resolution; `USER-DEC-6` calendar refusals #1 and #2 and save format 4 text approved; stop instruction on 2026-10-09 (all work halted cleanly).

Orchestrator decisions within that direction: ladder defaults (`R5B-DEC`), Gate E redefinition (`GATEE-FIX`), stage tick target (`SPATIAL-DONE`), re-base follows the player and dormancy priority (`WALK-FIXED`), structure store behind a flag with floor decay (`STRUCTURE-STORE`), creature save option (a): creature rows are regenerated on load, wounds and kills are not saved (`CREATURES-GAP`), rob and arrest approved (`CREATURE-COLLIDE-DEFEND0`), art direction after h006 (`H006-RESULT`).

## 16. Risks and watch list

| Risk | Why it matters | Mitigation or owner |
| --- | --- | --- |
| Client lags the backend by a large margin | Players see none of R3 and R4 until R5 lands | start R5 now; keep contract sections 4, 5b, 5c current |
| Tick cost at 50 to 100 residents | 69 and 131 ms are over budget | R6.11, stagger work behind a flag when the scenario is real |
| Ecology under the legacy calendar is meaningless | Animals age 4 years per day | long calendar must be the default before creatures are shown (R7.1) |
| Only one free human column | wounds and future per-resident state | aux tensor (R6.13) before more columns |
| Saves: new formats and refusals | silent loss is unacceptable | refuse over migrate; format 4 only when the store is non-empty; creature state intentionally not saved |
| Lock and shared-tree discipline | stale locks cost about 20 to 30 minutes twice; one lock deleted by mistake | abort on failed take, own-lock-only deletion, real ETAs |
| Test isolation | handler leaks produced 91 failures once | `tests/engine_isolation.restore_after` (R7.3) |
| Imagegen limits | no canvas or coordinate lock, no animation, safety blocks on underwear | static art only, offline normalisation, authored animation path (R9.5) |
| Art licensing | public release blocked until terms are checked | R7.6, R9.10 |
| Flag combinations grow | about 35 flags; untested combinations | R7.2 runs the chosen combination; add a flag-matrix smoke |

## 17. Suggested order of work from here

1. **R0** (one to two hours of machine time, serial because of the lock): R0.1 and R0.2 together, then R0.3, with R0.4 decided by the user in parallel.
2. **R5.1, R5.2, R5.4** (Client) in parallel with **R6.5, R6.6** (Harness/engine) and **R6.1, R6.2** (Model plane).
3. **R5.5, R5.6, R5.7** once R9.2 to R9.4 art is imported: first windowed acceptance of the endless map with buildings and creatures.
4. **R9.5 decision** (animation path) and **R9.6 to R9.9** content in parallel throughout.
5. **R6.3, R6.4, R6.7 to R6.10**, then **R7** (defaults, soak, cleanup, push on the user's word).
6. **R8** whenever the user supplies APIs; nothing above waits for it.

## 18. Cold start: how a new agent (Codex or Claude Code) takes over

The orchestrator session that wrote this roadmap and the two worker sessions (`1008latenight` = Harness/engine, `1008latenight2` = Model plane) are stopped. A new agent works from this file alone plus the files it points to. The old "orchestrator does not implement" rule belonged to that session layout; a single agent may implement directly, but every other rule in section 0.1 stays.

### 18.1 Reading order (about 30 minutes)

1. This file, sections 0 to 2 and 18 to 22.
2. `1008decisions.md`: read the last 40 rows (from `FULLSUITE-LN2` down) and the section 2 decision table; `grep -n "^| ROWID" 1008decisions.md` finds any row quoted in this roadmap.
3. `1008implementation.md` sections 0, 1, 3, 6 (principles, tier map, phases, user decisions).
4. The design doc named in the item you are about to do (every item in sections 3 to 13 names its evidence).
5. `1008_harness_handover.md` section 0 and 5 (traps), `1008_actions.md` sections 10.x (what each verb flag does).
6. `README.md` and `BACKEND.md` for running the game and the environment variables.

### 18.2 Repository map

| Path | What it is |
| --- | --- |
| `at_the_beginning/` | the engine: `map_test.py` (the tensor world, `Engine.step`), `instincts_and_tools.py` (legacy instincts and tools), `genesis_config.py` (columns and constants), `map_geo.py`, `runtime/`, `simulation/`, `persistence/` (save formats), `api/` (HTTP routes, `chunk_routes.py`, `model_routes.py`) |
| `at_the_beginning/harness/` | Harness plane: `engine_hooks.py` (flag installs), `window*.py`, `spaces.py`, `restraint.py`, `calendar.py`, `limits.py`, `structure_store.py`, `powers.py`, `human_query.py` |
| `at_the_beginning/systems/` | `actions/` (verbs, runner, drivers, ladder, reputation, market, credit, labour, justice, defend, bonds, places, care, emotion), `affordance/` (legal-option predicates), `decision/` (Tier 1 features, matrix, weights), `modelplane/` (Tier 2/3 client, escalation), `creatures/`, `worldgen/` (chunks), `movement/` (pathing, anchor mover, collision), `combat/`, `schedule/`, `roster/`, `escalation/`, `nature/`, `social/`, `clothing/`, `bonds/`, `places/` |
| `model_server/` | mock FastAPI model server, `gate_a.py`, `tier1_acceptance.py`, `train_matrix.py`, scenarios `s1_family_farm.py`, `s1_commons.py`, `s1_acceptance.py` |
| `tools/` | `golden_trace.py`, `live_smoke_*.py`, `profile_tick.py`, `spatial_probe.py`, `creature_balance.py`, `winter_probe.py`, `model_conformance.py`, `soak_*.py`, `validate_map.py` |
| `tests/` | unit and integration tests; `tests/golden/` golden traces; `tests/fixtures/` incl. `creatures_contract.json`; `tests/engine_isolation.py` |
| `world_data/maps2d/` | authored maps (`family_farm.json`, starter village and interiors) |
| `godot_client_2d/` | the 2D Godot 4.6 client (Codex-owned); `scripts/net/` (`chunk_loader.gd`, `map_sync.gd`, `frame_ingest.gd`, `space_view.gd`, `world_client.gd`), `scripts/game/game.gd`, `scripts/map_view.gd`, `data/resident_sprites.json`, `tests/`, `c2_checks/` |
| `myassets/` | all art (git-ignored): `h001` tiles, `h005_production` kit, `h007_buildings`, `h008_creatures`, pilots `h002` to `h004`, `h006_cutout` |
| `godot_client/`, `game_frontend/` | legacy 3D client and web frontend: frozen, not used, edits in the tree are not ours |
| `.runtime/` | locks, data roots, scratch (git-ignored) |

### 18.3 Environment and commands (Windows, Git Bash or PowerShell)

Python: `.venv/Scripts/python.exe` (there is no `python3`). Godot 4.6.2 for the client. From the repository root:

| Purpose | Command |
| --- | --- |
| Run the game | `powershell -ExecutionPolicy Bypass -File .\play.ps1` (options in `README.md`) |
| One test module | `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_<name>.py'` |
| Full suite (about 26 min, 2002 tests at `330d4a7`) | `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'` on a clean extract |
| Strict goldens | `.venv/Scripts/python.exe tools/golden_trace.py --check --strict` and again with `--resources`, `--spaces`, `--window-hook` |
| Model plane Gate A | `model_server/gate_a.py` (`--stress`, `--sweep`); Tier 1: `model_server/tier1_acceptance.py` |
| Family farm scenario | `python -m model_server.s1_family_farm --variant forage\|trade\|beg\|steal [--reputation] --ticks N --json out.json` (fresh process each time) |
| Commons scenario | `python -m model_server.s1_commons --seeds 1008,1,2 --repeat` (4000 ticks); stress: `--rob --rungs forage,rob --stall-rations 0 --keeper-rations 6 --family-hunger 95` |
| Window smoke over real HTTP | `.venv/Scripts/python.exe tools/live_smoke_window.py [--port 8021] [--keep]` (47 checks incl. a real walk) |
| Tick profile and scale probes | `tools/profile_tick.py`; `tools/spatial_probe.py N TICKS roster anchor\|agent`; `tools/spike_probe.py` |
| Creature balance (60 to 90 min, single process) | `tools/creature_balance.py --days 10 --brain kernel --calendar user` |
| Winter probe | `tools/winter_probe.py` |
| Client tests (headless Godot) | `godot_client_2d/tests/run_chunk_loader_test.py`, `godot_client_2d/c2_checks/run_spaces.py` (the Windows message `Failed to read the root certificate store.` is a known harmless diagnostic) |

Digest anchors from the last verified runs (valid only for the default command line of each script; if a digest differs, first confirm the command line, then bisect from `330d4a7`): s1 steal+reputation `a2fcc8cbdd7143c8`, trade `f83fed5436dd08fe`, commons seed 1008 `2fbbeae222e2dbd0`, seed 1 `506087d6cd7c03b7`.

### 18.4 Definition of done for any item

1. Behind its own `EDEN_*` flag, default off; flag-off identical to Stage 1: strict goldens (default, `--resources`, `--spaces`, `--window-hook`) show no drift and the s1 and commons digests match.
2. Unit tests, plus an oracle test when it replaces an existing computation (keep the old implementation inside the test), plus a scenario or live check when it touches the running world.
3. A clean-archive run: `git archive HEAD` extracted to a SHORT path (for example `C:\e1`), then copy `myassets/` and `tests/fixtures/maps/sprites/` into it (git-ignored directories), then run there. Never run heavy checks in the working tree.
4. Pathspec commit(s): `git add -- <new files>` then `git commit -m "..." -- <paths>`; legacy files committed alone with their tests.
5. An as-built section in the design doc, a ledger row in `1008decisions.md` (format `| ID | date | from | tag | what and evidence | decision or next |`), and this roadmap updated in the same commit.

### 18.5 Traps (learned the hard way)

- Locks: `.runtime/fullsuite.lock`. Take with `set -o noclobber; echo "<NORMAL|MEASURE> <who> <time> <what> eta=<real> " > .runtime/fullsuite.lock`, check the take succeeded, abort the whole script if not, delete only your own file, always remove it in a cleanup that actually ran (a stale lock cost 20 to 30 minutes twice, one script deleted another session's lock). MEASURE means nothing else may run; timing numbers on a shared machine are upper bounds.
- Shell: Bash heredocs with quotes or backticks break; write files with a file-writing tool or small scripts. Files are CRLF in places. Measurement scripts need an `if __name__ == "__main__":` guard (Windows multiprocessing spawns chunk workers).
- Tests: unseeded tests that boot the real engine have variance (seed global RNGs); `map_test` owns a module-level engine, so scenarios run in a fresh process; tests that install model-plane handlers on the shared backend engine must call `tests/engine_isolation.restore_after`; register `map_geo.reset_window` with `addCleanup` first; tests using pockets need `map_geo.configure_pockets(POCKET_ORIGINS)`; `validate_placement` reads the process environment.
- Windows: a plain `terminate()` of the backend orphans the chunk pool workers; use the process-group stop in `live_smoke_window.py`. Path length: extract at short paths. `pythonw` PID 27536 (`2D1006newstart/main.py`) is not ours, leave it.
- Engine: roster residents get zero movement noise and navigation bias, so steering changes are invisible for them; only human columns 30 (restraint) is used and 31 is the last free one; resource node centres are not standable (use `Ladder.stand_point`); queued roster action tasks can starve a resident (watchdog at 400 ticks or need 75); `update_relationship` overwrites the relation kind; residents more than about 10 chunks apart cannot both be integrated.
- Sandbox: an earlier Codex run could not run live server parity because its shell failed with `CreateFileMapping` error 5. Heavy and live runs may need an unrestricted shell; if blocked, say so and do not mark the item done.
- Process: do not widen scope silently; do not reinterpret silence as approval; never mark an item `DONE` without evidence in the ledger.

## 19. Task cards for the next items

Each card is self-contained. Acceptance is what a reviewer checks; "evidence" is what goes into the ledger row.

### R0.1 Clean-archive gate on current HEAD
- Do: take a NORMAL lock; `git archive HEAD` to a short path; copy `myassets/` and `tests/fixtures/maps/sprites/`; run the four strict goldens, then the full suite; release the lock.
- Accept: no golden drift; full suite green (previous: 2002 OK at `330d4a7`; expect about 2030 after emotion and calendar C5 tests). A red test is first checked for handler leakage (`tests/engine_isolation.py`) and flag sensitivity (`EDEN_CALENDAR=1` market scenario test is a known exception, R0.6).
- Evidence: ledger row with counts, HEAD hash, archive path, run time.

### R0.2 Flag-off golden for sleep, darkness, clothing commits
- Covered by R0.1 if run on a HEAD that contains `7a81dee`, `2ca80d9`, `59d9796`; log that explicitly.

### R0.3 Long-calendar ecology balance
- Do: `tools/creature_balance.py --days 10 --brain kernel --calendar user` (single process, outside the lock but not alongside a MEASURE run). Record population per day (sheep, deer, wolf, boar, fox), hunger and thirst means, deaths with cause, duel numbers (hunter vs creature, creature vs resident time to kill), and the cause of any resident death (the earlier partial run had a wolf death at probe tick 52114 and a resident death at day 7).
- Accept (targets, adjust with evidence): no species extinct or exploding (sheep must not go 40 to 460 in 4 days, nor collapse to 3), resident casualties rare but possible, hunters can win a duel, nobody dies of a bug (void walking, stuck task, starvation by a rules gap).
- Then: tune the data rows in `systems/creatures/table.py` (section 8 of `1008_creatures_gap.md` lists the starting numbers); parity test `tests/test_creatures_parity.py` stays green.
- Evidence: table in `1008_creatures_gap.md` as-built, ledger row.

### R0.4 Third calendar refusal text
- Needs the user's approval of the draft in section 8 (`R0.4`), then 9d882a's code path `_check_calendar` in `persistence/world_snapshot.py` raises `SaveFormatError` with it; add a round-trip test (calendar A save, calendar B session).

### R0.5 5,000-unit straight walk (Gate D wording)
- Do: extend `tools/live_smoke_window.py` phase_walk (or add a flag) to walk 5,000 units east and then back; log re-base epochs, memory, rejected inputs (must be 0), void hits (0), residents left behind keep absolute positions and slots, and memory growth bounded.
- Accept: exit code 0 with the new check; ledger row; Gate D line in section 14 becomes PASSED.

### R0.6 `EDEN_CALENDAR=1` test sweep
- Do: run the day-dependent test modules with `EDEN_CALENDAR=1`; the market-scenario subprocess test is known to fail because the world runs on slower needs tuned for the legacy day.
- Accept: either fix the scenario to be calendar-independent or mark the exception in a test skip with a reason pointing at this item.

### R5.1 Wire the chunk loader into the real game scene (Client)
- Files: `godot_client_2d/scripts/net/chunk_loader.gd`, `scripts/chunk_debug.gd`, `scenes/ChunkDebug.tscn`, `scripts/game/game.gd`, `scripts/map_view.gd`.
- Do: instantiate the loader in the game scene behind `--enable-chunks` or `EDEN_CLIENT_CHUNKS=1`; feed it the controlled actor's position (`set_chunk_center(cx, cy)` for exact addresses); draw chunk ground with the h001 tiles through a tile atlas (48 px cells); keep Stage 1 behaviour when the flag is off.
- Needs a decision: DR-3 (pinned authored-map placement) and DR-4 (props vs entity ownership).
- Accept: headless tests green (`run_chunk_loader_test.py`, `run_spaces.py`, existing client tests) and a windowed run on a real backend with the four window flags shows the ground following the player across at least 3 re-bases with no gaps; evidence = screenshots stored in `godot_client_2d/evidence/` (not committed if large).

### R5.2 Window re-base in the client
- Do: read `window_origin`, `window_epoch`, `window_shift` from `/bootstrap` and `/frame`; shift all client-side positions on epoch change without visible jumps; send `window_epoch` on window views and handle 409 `stale_window_epoch` by refetching; see `1008_client_contract.md` section 4.
- Accept: a scripted 3,400-unit walk shows no teleport or flicker; the 409 path is unit-tested with a mock.

### R5.3 Creatures in the client
- Do: read `animals[].creature = {species, sprite, footprint, state, variant}` (contract section 5b); load sprites by the frozen id contract (`tests/fixtures/creatures_contract.json`, art in `myassets/h008_creatures`, display copies at scale 1); pick south or east by heading (west mirrors east); light bob while moving (option from `ANIMATION_OPTIONS.md`); dead pose swap for wolf, boar, deer; Y-sort by pivot.
- Accept: creatures render in the right place, face the heading, die visibly, no collision or depth glitch beside buildings; species with no art show a labelled placeholder.

### R5.4 Day and night in the client
- Do: `time` block from `/frame` under `EDEN_CALENDAR=1` (contract section 5c); tint and darkness by `light`; season tint; no change when the block is absent.
- Accept: a 10-minute real-time day visibly cycles; flag off unchanged.

### R5.5 and R5.6 Import art and place buildings (Client + Assets)
- Do: copy accepted art into the client resource tree (never commit); characters master at scale 0.40 or derivative at 0.80 with nearest filtering; buildings display copy at scale 1; set footprints, doors and collision from `myassets/h007_buildings/manifest.json`; add buildings to authored maps and to generated settlements through map content (Codex), keeping door anchors valid for pathing.
- Accept: residents can path to a door; a building footprint blocks movement; scale beside a resident looks right (door 80 to 90 px beside a 64 px adult).

### R5.7 Windowed acceptance (Gate F)
- Do: run a real backend with window, calendar and creature flags, play 15 minutes with a person at the keyboard; capture evidence; record the target machine's frame rate (the client owner states the target, it is not assumed).
- Accept: Gate F text in `1008implementation.md` WS-F: no seams, correct depth, walls match sprites, chunk load and unload at walking speed without frame drops.

### R6.1 to R6.4 (gameplay depth) first steps
- R6.1 verbs: for each missing verb add a catalog row, predicate, verb, tests, flag; `teach` needs a skill list first (design it), `invite` needs an invitation object, `repair` needs a damage state on structures, `settle_site` and `migrate_group` need the settlement object (R6.4). Doc: `1008_actions.md` section 10.x.
- R6.2 market M2: price memory and elasticity, travelling merchants (needs a second settlement or off-window arrivals), spoilage (per-stack age in inventory schema; legacy edit; ties to the food_spoilage instinct), taxes via justice, saved market object (persistence edit, may need a format key; refusal wording goes to the user).
- R6.3 economy balance: commons runs show peak hunger at the ration floor on every seed and wages refused 22 to 31 times per run; tune production, prices and the Tier 0 ration (`EDEN_LADDER_STARVE` exists for scarcity scenarios); re-run commons seeds 1008, 1, 2, 3 after every change; accept when nobody is permanently at the floor and some residents can afford wages.
- R6.4 settlements: design first (`[GAP]` doc): settlement object (members, claim radius, buildings, roles), construction as a living process (2.D1), terraform (2.C3), growth rules; it needs the structure store (done) and the calendar (done).

### R7.1 Flag defaults
- Do: propose and measure; flipping a default changes goldens, so re-record under the user's approval. Proposed order: `EDEN_CALENDAR` first (ecology and ageing are wrong without it), then `EDEN_PERCEPTION_BOUNDED`, `EDEN_SPACES`, `EDEN_WINDOW` family, then creatures, then the economy chain in dependency order. Each flip: full suite, soak 30 game minutes, a live smoke, a ledger row, user approval.

### R9.5 Walking animation path (needs DR-7)
- Options with costs are in `myassets/h006_cutout/PILOT_REPORT.md` and `myassets/h008_creatures/ANIMATION_OPTIONS.md`. Recommended first spend: artist-authored two-pose east and south walk for wolf and boar (planted feet checked), subtle breathing for the rest. For characters keep the existing A3 baked walk sheets for walking residents; use the h005 kit for idle, portraits and equipment tiers.

## 20. Decision register (open decisions, with a recommendation)

Status `OPEN` needs the user; `RECOMMENDED` means the agent may proceed on the recommendation and report; `DECIDED` is listed so it is not asked twice. Add new decisions here with the next free number.

| Id | Decision | Options | Recommendation | Blocks | Status |
| --- | --- | --- | --- | --- | --- |
| DR-1 | Third calendar refusal wording (R0.4) | approve draft text in section 8 / change it | approve | R0.4 | OPEN (user) |
| DR-2 | Which flags become defaults, in what order, and when to re-record goldens | see R7.1 | calendar first, then window family, then creatures, then economy chain | R7.1 | OPEN (user at R7) |
| DR-3 | Pinned authored-map placement in the chunk loader (descriptors carry no authored-map origin; maps spanning several chunks) | descriptor carries origin / client reads origin from `/bootstrap` maps / generator pins maps at chunk-aligned origins | descriptor carries `origin`; backend change in `chunk_routes.py` | R5.1 | RECOMMENDED |
| DR-4 | Chunk props: client-drawn from chunk data or entities from the backend `map_delta` | props as visuals only / props as entities with ids | visuals for decorative props, entities for anything interactive (resources, structures), as the window already does | R5.1 | RECOMMENDED |
| DR-5 | Mixed-biome junction priority and chunk-seam visual masks | per-tile priority order / blend masks | priority order table in `world_data`, masks only if seams show in R5.7 | R5.1, R5.7 | OPEN (visual call) |
| DR-6 | Far-resident limit: residents beyond about 10 chunks cannot both be integrated; dormant village freezes until full offscreen simulation | accept until R6.5 / build R6.5 earlier | accept (user did not object) | R6.5 | DECIDED (revisit at R6.5) |
| DR-7 | Animation path for walking (R9.5) | hand-pixel two-pose / separately authored limb parts then rig / commission / keep baked A3 for walking | keep A3 for residents, two-pose for wolf and boar first | R5.3, R9.5 | OPEN (user budget) |
| DR-8 | Character kit priorities: adult average first, then child and elder mini-kits, or slim and sturdy variants first; first garment and hair presets | child/elder first / variants first | child and elder first (village needs them), 3 hair presets and 3 garment sets | R9.6 | OPEN |
| DR-9 | Imagegen and Qwen output licence before any public distribution | user checks terms | required before release | R7.6, R9.10 | OPEN (user) |
| DR-10 | Can a player's body be arrested or restrained | never / only by explicit game rule / yes | never in Phase 1 (current); revisit when guards exist in play | R6.12 | OPEN (game design) |
| DR-11 | Creature persistence on save | option (a) regenerate, kills and wounds lost / (b) refuse / (c) new format | (a) shipped; revisit when ecology persistence matters | R4.5 | DECIDED (revisit) |
| DR-12 | Which creature species are enabled by default and their balance numbers | data in `systems/creatures/table.py` | decide from the R0.3 table | R0.3, R7.1 | RECOMMENDED |
| DR-13 | Real Tier 1 weights: replace rules prior or keep it as default, and the commission acceptance check that fails when the pure matrix crafts its own sword | loosen the check (swords may exceed 1) / keep strict and constrain craft | keep the rules prior default; decide with real data in R8 | R8.4 | OPEN (R8) |
| DR-14 | Gate F target machine and frame-rate target | client owner states it | state it in the R5.7 evidence | R5.7 | OPEN (client) |
| DR-15 | Push `1008implementation` to GitHub | now / after R7 / never | after R0 and a clean full suite, only on the user's word | R7.5 | OPEN (user) |
| DR-16 | What the packaging cleanup removes (D-003) | dead code, frozen frontier tools (kept per D-005), duplicate docs, `tmp_*` test dirs at the repo root | list first, delete nothing without approval | R7.4 | OPEN |
| DR-17 | Expansion doc choices (`1008expansion.md` section "Open decisions"): civic or church identity of the hall, material and architecture priorities, scenario readability versus grandeur, appearance storage and version fallback, rank of the invented creatures for the next art pilot | see doc | rank invented creatures by gameplay hook (brambleback, bellhorn done); scenario readability first | R9.6 to R9.8 | OPEN |
| DR-18 | `EDEN_ENSURE_ONCE` and `EDEN_REACH_MAX_DISTANCE` defaults | measure then set | ensure-once on after R0.1 on a clean suite; reach cap value from a measurement of path-search cost | R7.1 | RECOMMENDED |
| DR-19 | Ladder thresholds and weights are placeholders; whether restitution should ever be mandatory; whether `rules:ladder` proposer should go through model confidence | tune by scenario | tune in R6.3, restitution only through justice, proposer stays rules | R6.3 | RECOMMENDED |
| DR-20 | Stagger construction sync and escalation signals to reach 50 residents under 50 ms | flagged behaviour change / do nothing | do nothing until a 50-resident scenario exists | R6.11 | DECIDED (revisit) |
| DR-21 | Spatial index (chunk-keyed tile map) | build / defer | defer until rows near 400 | R6.11 | DECIDED (revisit) |

## 21. Who does what (tracks) when sessions exist

If several agents work at once, keep these ownerships (they avoid merge conflicts in the one shared tree); a single agent may hold all tracks.

| Track | Owns | Typical items |
| --- | --- | --- |
| Harness/engine | `harness/`, `window*`, `spaces`, `persistence` formats, movement and combat edits, creatures, calendar, goldens and profiling tools | R0.2, R0.3, R0.5, R3, R4, R6.4 to R6.11, R6.13 |
| Model plane | `systems/actions`, `affordance`, `decision`, `modelplane`, `model_server`, `systems/clothing`, `bonds`, `places` | R0.1, R0.6, R2, R6.1 to R6.3, R8 |
| Client | `godot_client_2d/` | R5 |
| Assets | `myassets/` (generate, normalise, validate, document) | R9 |
| Orchestration | this roadmap, `1008decisions.md`, user questions, verification of other tracks | decisions, gates, ledger |

Cross-track edits go through a `[GAP]` note in the ledger or a message, never a silent edit of another track's file; legacy files outside any track (for example `map_test.py`, `instincts_and_tools.py`) may be edited only as pure-equivalence or flag-gated changes under the golden gates, committed alone.

## 22. Glossary

- **Tier 0**: deterministic code at 20 Hz. **Tier 1**: matrix policy over 24 macro actions with a masked softmax and a rules prior. **Tier 2**: Clef decision model (held, built against a mock). **Tier 3**: LLM roles resident, dialogue, world, on escalation. No Tier 4.
- **Roster resident**: a resident defined in a map roster with real anchors (work, talk, home, sleep), driven by the anchor driver or the agent driver.
- **Window**: the streamed square of integrated chunks around the player (5x5 simulated, 7x7 kept); positions are window-relative and re-based at 2 chunks; `window_epoch` counts re-bases.
- **Space**: an isolated region id (0 is the overworld; interiors live in pockets outside the window range); masks keep spaces from seeing each other.
- **Dormant**: a human or animal row outside the integrated frame for 40 ticks: frozen, caught up in closed form when it returns.
- **Structure store**: built structures leave the tensors with their chunk and come back with it (save format 4 only when non-empty).
- **Golden**: a recorded trace of the engine used to prove flag-off identity (`tests/golden/`, `tools/golden_trace.py`).
- **Digest**: a hash of a scenario outcome (`s1_*` scripts) used to prove determinism and flag-off identity.
- **Ledger**: `1008decisions.md`, the append-only record of who decided or delivered what and with what evidence.
- **Flag**: an `EDEN_*` environment variable; default off.
- **A3 / A4 art**: the existing resident and animal sprite sets (A3 residents 128 px frames at actor scale 0.72; A4 static animals); **h001 to h008**: new asset rounds (tiles, pilots, kit, buildings, creatures).
- **Master and display**: 2x author sprite and its exact half-size derivative used at scale 1; characters are displayed at 0.40 (master) on the 48 px tile grid.

## 23. Change log of this file

- 2026-10-09: first version, written from `1008decisions.md` rows up to `EMOTION-C5` (HEAD `56876b4`).
- 2026-10-09: handover version: added sections 18 (cold start), 19 (task cards), 20 (decision register), 21 (tracks), 22 (glossary) so that Codex or Claude Code can continue from this file alone.

### 2026-10-10 verified implementation update

R6.3 opt-in balance implementation passed four4,000tick seeds+repeat,78focusedtests, historical flag-off digests and all four strict goldens in immutable scoped archives. Source hashes match live owned files. Full clean current-HEAD integration suite remains a separate gate; long-calendar market exception is reproduced and documented under R0.6, not silently fixed by rate/default changes. See ECONOMY-BALANCE-1010 and coordination_evidence/codex_1010_r63_report.md. Other roadmap tasks and OPEN user decisions retain their prior status.
