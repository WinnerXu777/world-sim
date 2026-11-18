# 1008 implementation plan: Stage 2 (model tiers, tool/instinct expansion, infinite map, real world depth)

Written 2026-10-08 by the Claude backend session. Status: **plan (draft, user decisions recorded in section 6)**. Nothing here is built unless a section says so.

**User decisions, 2026-10-08 (these override anything below that disagrees):** (1) there is no tier 4; the model tiers are Tier 1 matrix, Tier 2 Clef, Tier 3 LLM, so section 1 is renumbered to that and the self-extension tier is dropped. (2) The map is rendered and simulated only near the player and **generated live as the player approaches**; the design must also be efficient, see WS-D. (4) We build only code and an API-first model boundary; the user will provide and work on the models later, and no model hosting or training is in scope. (5) Stage 2 delivers the fully intelligent game with a **switch to turn the LLM tiers on and off**, all tools and instincts ready (the list may be expanded, see Appendix A), Clef details held open until the real model API is supplied. Full record in section 6. Governing context: Stage 1 is accepted for local evaluation (`1006_STAGE1_LOCAL_DELIVERY.md`); the tier design is `1006newdesign.md`; the long-term roles are `implementation_0905.md` I0 to I5. Where this plan and those disagree, this plan is a proposal, not a decision.

## 0. Goal and principle

Stage 1 proved a closed loop: a few scripted residents, one commission (go to the smith, order a sword), rules-based decisions, four hand-authored maps. Stage 2 turns that into a **scaffold for real intelligence**: any resident can face any situation, choose among many legal actions, plan over days, talk, remember, and live in a world that does not end.

One principle runs through everything, taken from Stage 1: **Python decides what is legal and applies it; models only choose among, or propose, validated things.** No model ever mutates a tensor. Every model call has a rules fallback, a deadline, and a stale-result guard. We write all the code first against a mock model server; the real models arrive later as a FastAPI service behind the same contract and change no game code.

## 1. Tier map (user's numbering, 2026-10-08)

The user's numbering is used from here on: **Tier 1 = matrix, Tier 2 = Clef, Tier 3 = LLM**, with deterministic code beneath them as Tier 0. There is no Tier 4. Note that `1006newdesign.md` calls the Clef decision model "Tier 1" and splits the LLMs into its own Tier 2/3a/3b; that document is not rewritten, so read its "Tier 1" as this plan's Tier 2, its "Tier 2" as this plan's Tier 3 `resident` role, and its "Tier 3a/3b" as this plan's Tier 3 `dialogue` and `world` roles.

| Tier | What | Cost per call | Runs | Status today |
| --- | --- | --- | --- | --- |
| **Tier 0** | Deterministic execution: instincts (tensor ops over `h_tensor`/`m_tensor`: `torch.cdist` proximity, masks, needs, death, fire), tasks, schedule, movement, combat, crafting, inventory | microseconds, batched | every tick (20 Hz) | built (`instincts_and_tools.py`, `systems/*`) |
| **Tier 1** | **Matrix policy (new)**: per-resident feature vector times weight matrices, masked softmax over a fixed macro-action menu, one batched `torch` matmul for all residents | tens of microseconds for 100 residents | on triggers and on a slow background cadence | not built; `RulesDecisionProvider` is its hand-written ancestor |
| **Tier 2** | **Clef decision model**: typed options in, a probability per option out, no text | 40 to 200 ms hosted (reported, unverified; details still being decided by the user) | only when Tier 1 is unsure and the situation matters | seam built (`systems/decision`), provider is a stub |
| **Tier 3** | **LLM**, three roles behind one switch: `resident` (goals, plans, negotiation, replanning, reflection), `dialogue` (wording from an already-decided outcome), `world` (god decrees, regional events, world operations through tools with ToolRAG) | 0.1 to several seconds | `USE_BRAIN`/`REPLAN`/`PLOT`, low confidence, scheduled review, a line of speech, a decree | hooks exist (`resident_model_handler`, `talk_runtime.py`, `world_runtime.py`), mock and templates only |

Routing rule (extends 1006newdesign section 3): if rules can compute it, Tier 0. If it is a choice among known legal options, Tier 1, escalating to Tier 2 when unsure. If it needs a plan, goal or negotiation, Tier 3 `resident`. If it needs words, Tier 3 `dialogue`. If it changes the world, Tier 3 `world`. Self-extension (models proposing new code) is out of scope: the `propose_new_instinct`/`propose_new_tool` registry entries stay unused.

### 1.1 The LLM switch (a first-class requirement)

The game must be fully playable and fully "intelligent" with every model off, and become smarter, not different in kind, when models are on. One configuration, per tier and role, three modes:

| Mode | Behaviour |
| --- | --- |
| `off` | Tier 3 roles use the built-in deterministic stand-ins (template dialogue, heuristic plans from `world_runtime._heuristic_plan` and the planning scaffold, rules-based decisions). Tier 2 is skipped; Tier 1 matrix (or rules) decides. No network calls. This is the Stage 1 behaviour, extended to all new content. |
| `shadow` | The model is called on real triggers and its answer is logged next to the stand-in's choice; the stand-in's choice is applied. Used to evaluate a model before trusting it. |
| `on` | The model's validated answer is applied; any failure, timeout, stale result or illegal output falls back to the stand-in for that call. |

Settings: environment variables (`EDEN_TIER1=rules|matrix`, `EDEN_TIER2=off|shadow|on`, `EDEN_TIER3_RESIDENT`, `EDEN_TIER3_DIALOGUE`, `EDEN_TIER3_WORLD` = `off|shadow|on`, plus endpoint URL, key variable name and model id per role) and a runtime route (`POST /control/models`) so the switch can be flipped in a running game from the client or a script. Rules: toggling bumps the world's model epoch so in-flight jobs from the old setting are dropped by the existing stale guard; the mode is written to the decision log and shown in `/model_status`, but it is **not** part of the saved world, so a save made with models on loads and plays with them off. The same switch is the master kill switch if a model misbehaves.

## 2. Workstreams, in build order

Each workstream has its own gate. Ownership follows Stage 1: **Claude** owns backend, tests, tools, model server; **Codex** owns `godot_client_2d/` and `myassets/` (handoffs through the scratchpad).

### WS-A. Model plane (contract, serving, safety): build first, needs no model

1. **Wire contract v1** (`model_server/contract.py` shared by game and server): one envelope for every role: `job_id`, `role` (`decide`, `resident`, `dialogue`, `world`), `world_epoch`, `state_revision`, `priority`, `deadline_ms`, `cancel_token`, `schema_version`, `payload`. Responses carry `provider_mode` (`rules|mock|recorded|live|fallback`), `latency_ms`, `model_id`, and a typed result. JSON Schema is generated from the dataclasses, so a bad model output is rejected before it touches the game.
2. **Model server** (`model_server/`, FastAPI): `POST /v1/decide`, `/v1/resident`, `/v1/dialogue`, `/v1/world`, `GET /health`, `/ready`, `/v1/models`. Pluggable backends per role from environment config: `mock` (deterministic), `rules` (calls the same scorers), `openai_compat` (vLLM/SGLang/Ollama), `clef` (hosted Workers AI or local), `recorded` (replay). The game never imports a model library; it only speaks HTTP. Batching and prefix caching live in the server.
3. **Game-side client** (`systems/modelplane/`): async job queue on a worker thread so the 20 Hz tick never blocks; per-role budgets (in-flight cap, requests per game minute); per-resident cooldown; dedupe by causal event id; bounded escalation depth (a Tier 1 or 2 escalation to Tier 3 never loops back); circuit breaker per endpoint (open after N timeouts, half-open probe). Reuses `DecisionService.apply_if_fresh` for the epoch/revision stale guard.
4. **`ClefDecisionProvider`**: becomes a thin client of `/v1/decide`. Falls back to rules on any error (already how `DecisionService` behaves).
5. **Unify the legacy hooks**: `resident_model_handler`, the tiny modes (`urgent_react`, `normal_live`, `talk_reply`, `ambient_npc_talk`) and the world handler (`decree`, `resident_reasoning`) become adapters over the same client, with their existing structured output contracts kept (`implement_llm.md`). No second NPC stack.
6. **Observability**: per role and lane: requests, p50/p95/p99, queue age, timeout and fallback rate, escalation rate, stale drops, validation rejects, rules-vs-model agreement. Surfaces in the existing `decision` status field and a `/model_status` route.
7. **The LLM switch** from section 1.1: `modelplane` reads the per-tier modes (`off|shadow|on`), applies them per call, and exposes `POST /control/models`. `off` is the default and must never touch the network.
8. **Hook-up kit for the real models (user supplies these later).** (a) A published API spec: the contract exported as OpenAPI/JSON Schema with worked request and response examples per role, so whoever serves a model knows exactly what to accept and return. (b) A conformance script `tools/model_conformance.py URL --role decide|resident|dialogue|world` that sends canned requests, checks schema, probability sums, option-set equality, deadline behaviour and error handling, and prints pass/fail; any endpoint that passes can be switched on. (c) Config only: the user gives a base URL, an API-key environment variable name, a model id and (for Clef) whatever request mapping the final Clef API needs; an adapter file `modelplane/adapters/clef.py` holds the mapping and is the only code that changes when the Clef details are decided. Until then the Clef adapter is a documented stub that raises, and the system runs Tier 1 only.

Gate A: the whole game runs 30 game minutes against the mock server with injected timeouts, garbage, slow and stale replies; zero crashes, tick p99 unchanged from the Stage 1 baseline (28 ms), every fault recorded as a fallback, not a failure. Pulling the server out mid-run degrades to rules.

### WS-B. Tier 1 and Tier 2 decision layers (matrix policy and Clef)

**Tier 1, the matrix policy.** This is the answer to "how do 100 residents decide cheaply at 20 Hz". Design:

- **State matrix `X` (N x F)**: one row per resident, built by vectorised reads from `h_tensor` and the resident sidecars: needs (hunger, thirst, stamina, HP, threat, mood), personality traits (`systems/personality`), active goal weights (`systems/goal`), schedule slot (`systems/schedule`), relationship summaries to the nearest K others, local scene summary (counts of food/water/danger/kin within radius from `systems/perception`), inventory flags, time of day and weather. Features are normalised to [0,1] or [-1,1] and versioned (`FEATURE_SCHEMA_VERSION`).
- **Menu `K`**: a fixed macro-action vocabulary (about 24 to start): `eat`, `drink`, `rest`, `sleep`, `work_at_station`, `gather`, `go_home`, `socialise`, `trade`, `help`, `avoid`, `flee`, `defend`, `attack`, `explore`, `build`, `repair`, `ask_for_help`, plus `USE_BRAIN`, `REPLAN`, `PLOT`, `continue_plan_step`. Each macro-action maps to existing tasks (`systems/tasks/families/*`) and schedule/plan ops (`systems/planning/catalog.py`), so Tier 1 chooses *what kind* of thing; the task system does the *how*.
- **Legality mask `M` (N x K)**: computed by Python from facts (the affordance engine, WS-C). An illegal option has probability exactly 0 and can never be chosen by any tier.
- **Scores**: `S = X @ W + (X @ U) * (P @ V) + b`, masked, then `softmax(S / temperature)` row-wise. `W` (F x K) is the main matrix; the bilinear term lets personality `P` modulate the same state differently per resident. One `torch.matmul` for the whole population. Hysteresis (a bonus for the currently running macro-action, from `goal` stickiness) prevents flapping.
- **Rules are a special case**: initialise `W` from the existing hand-written rules scorers, so `RulesDecisionProvider` and Tier 1 produce the same decisions on day one. That gives a free regression oracle and a permanent fallback.
- **Learning path**: the decision log (JSONL under the data root, already written by `DecisionLog`) records request, probabilities, chosen option and outcome. Train `W`/`U`/`V` offline by distilling Clef (and later outcome-weighted data) into the matrix; load a new `weights_vN.npz` with a version and hash recorded in saves. Training code lives under `models/`, never in the tick loop.
- **Gate to Tier 2**: if `top_p` is below a threshold or the margin to the runner-up is small, and the situation is significant (danger, obligation, dialogue, high-stakes inventory), the row is sent to Clef. Otherwise the matrix result is final. Thresholds are config, tuned from shadow data.

**Tier 2, Clef.** Same `DecisionRequest`/`DecisionResult` contract already built. Stage order (from 1006newdesign section 13): S2.0 evaluate latency/calibration/agreement; S2.1 shadow mode (logged next to the Tier 1 choice, no effect); S2.2 live for the background lane with rules fallback; S2.3 critical lane with tight deadlines and Tier 0 reaction first; S2.4 escalation to Tier 3. Clef facts (sizes, license, latency) came from a ChatGPT conversation and **must be verified** before we depend on them; that is why Tier 1 exists and why the provider is swappable.

Gate B: Tier 1 reproduces the rules provider on 10,000 logged states (agreement 100 percent at initialisation); a 100-resident batch costs under 1 ms; shadow-mode logs of Tier 1 vs rules vs mock-Clef are produced; a trained `W` beats rules on at least one scripted scenario metric without any Tier 0 safety regression (no deaths from starvation in the 90-minute soak).

### WS-C. Tools, instincts and capabilities for a real AI game

Today there are 46 `instinct_*` and 74 `tool_*` functions in `instincts_and_tools.py` (mostly god/world-agent powers: disasters, spawn, terraform), and `models/tools_and_instincts_registry.py` (57 documented entries in tiers A/B/C) used to train the world agent (LoRA-A). Stage 1's playable behaviour goes through a different, newer path (`systems/commission`, `tasks`, `planning`). Stage 2 needs these to become **one capability system with three audiences**, built on the redesigned harness evaluated in WS-H below (declared systems, one action vocabulary, powers with dry-run, effects and events as data), not on the original calling conventions:

1. **Capability manifest (single source of truth).** Every callable gets a machine-readable entry, generated and then checked against the code by a test: `id`, `audience` (`system` = per-tick instinct, `resident` = something a person can do, `god` = world power), `args` (JSON Schema), `preconditions` (a named legality predicate), `effects` (what state it may change), `cost`/`cooldown`, `perception_required`, `authority` (who may invoke it), `risk` (reversible, destructive, irreversible), and `retrieval_text` for ToolRAG. The existing registry becomes a view of this, so the world-agent training data and the runtime cannot drift apart. A CI test fails if a `tool_*` has no manifest entry or the signature differs.
2. **Affordance engine** (`systems/affordance/`): given a resident and the world, returns the list of legal options with parameters (nearest food, a reachable bed, a station that fits a recipe, a neighbour who could trade). This is what builds the Tier 1 option list and the legality mask, and it is the only place "can this happen" is answered. Reuses `perception`, `movement/pathing`, `inventory`, `crafting/stations`, `occupation`.
3. **Resident verbs.** A curated subset of macro-actions with typed parameters is what Tier 3 `resident` plans over. Plan step ops grow beyond the current set (`move_to_place`, `observe_target`, `attack_target_when_close`, ...) to include `trade_with`, `request_item`, `offer_item`, `craft`, `work_shift`, `gather_resource`, `build_structure`, `teach`, `heal_target`, `report_to`, `follow`, `lead_group_to`. Each op has a validator and an executor in `systems/planning` and `systems/tasks`; a model can only emit ops from the catalog.
4. **God/world tools stay god-only.** Tier 3 `world` gets them through ToolRAG (retrieve top-k manifest entries for the decree, then a validated plan, as `world_runtime.py` already structures). Residents never receive `tool_smite`-class powers. Acquired instincts (`ACQUIRED_INSTINCT_MASK`) remain a god/world mechanism with explicit grants.
5. **Expanded catalog.** The user asked for the tool/instinct list to be expanded as far as is useful; Appendix A proposes the additions (new per-tick instincts, resident verbs, god tools), each of which gets a manifest entry, a legality predicate, a rules implementation and a test before any model may use it. No model-written code is ever loaded.
6. **Safety envelope for every model-originated action**: schema validation, catalog membership, live legality re-check at apply time, rate caps, `risk`-based approval (destructive or irreversible resident actions require a higher confidence and can be forced to a rules decision), and a full audit entry (who proposed it, tier, probabilities, validation result).

Gate C: manifest coverage test green; the affordance engine returns the same legal options as the Stage 1 commission code for the smith scenario (parity), and at least 12 resident verbs are executable end to end with a mock Tier 3 plan; an illegal model output (nonexistent tool, wrong args, unreachable target) is rejected and logged on every verb.

### WS-H. Harness redesign: evaluating the original tools and instincts

The user pointed out that the tools and instincts were designed long ago and asked for an honest evaluation and a better harness. This section is that evaluation. It is based on reading `instincts_and_tools.py` (3,331 lines, 46 `instinct_*`, 74 `tool_*`), the engine loop in `map_test.py` (`Engine.step`, `default_registry_entries`), `runtime/execution_*.py` (the string-mask DSL and packet validation) and the tests. **Not verified:** I did not profile the tick, did not read every function (about 10 were read closely, the rest were classified from names and signatures), and the triage in H.3 is a proposal to be confirmed by a read-only audit in P0.

#### H.1 What the original design got right (keep it)

- **Vectorised tensor simulation.** One `h_tensor`/`m_tensor` pass per instinct is fast and simple; a shared dense pairwise pass (`_build_human_pairwise`, one `cdist` reused by mating, attack and infection) is a good pattern. It is the right substrate for Tier 0 and for the Tier 1 matrix policy.
- **Additive steering.** `instinct_move` sums survival, social and schedule bias vectors into one step. That "sum of force fields" idea is exactly what a unified mover needs (H.2, item 7).
- **The `systems/` extraction pattern.** Each domain has `design.md`, `future.md`, `ops.py` and often `prompt_view.py` (a text/feature view for models). This is the right shape for Tier 1 features and Tier 3 prompts.
- **The Stage 1 additions**: idempotent command layer (`simulation/commands.py`), god-power ledger with witnesses, decision seam with stale guards, save guards. These already point toward the harness below.

#### H.2 Findings: where the original design will not scale to a real intelligent game

1. **Two disjoint action systems.** Per-tick instincts and `tool_*` powers mutate tensors directly; resident behaviour in Stage 1 goes through a different newer path (`systems/tasks`, `commission`, `planning`). A model choosing "what should this person do" has no single action vocabulary. (Verified from the code layout.)
2. **Hidden data dependencies and float priorities.** `Engine.step` runs a priority-sorted list (`default_registry_entries`, priorities like `37.75`) over a shared mutable `ctx` dict; instincts communicate through undeclared keys (`pairwise_pre`, `nav_survival_bias`, `seek_mask`). Order matters and nothing states why; adding a system means guessing a priority. (Verified.)
3. **Inconsistent tool contracts.** Signatures vary (`(ctx, h_tensor, mask, ...)`, `(ctx, m_tensor, entity_mask, ...)`), `**_` swallows unknown arguments, one-element lists (`pop_count_ref`, `entity_count_ref`) act as out-parameters, and return values are `None`, `{}`, `{"map_dirty": True}` or `{"h_mask": ...}`. Validation of model output works by `inspect.signature` plus a hand-written registry. Typos in argument names are silently ignored. (Verified.)
4. **Registry drift.** `models/tools_and_instincts_registry.py` documents 57 entries while the module defines 74 tools and 46 instincts; the registry is written by hand and also trains the world agent. (Counts verified.)
5. **Fragile targeting.** Powers take a boolean tensor `mask` over tensor slots; a model produces it by writing a string expression in a custom DSL (`execution_selectors.py`, 755 lines, with a documented list of unsupported features). Slots are reused when residents die (the code already keeps `_human_uid_by_slot` to cope). A model-written string mask is the most likely failure point and cannot be validated against a schema. (Verified.)
6. **Effects are invisible.** A tool changes tensors and returns a dirty flag. Nothing records "what happened, to whom, who saw it", so memory, gossip, goals and Tier 1 triggers cannot hook the effect. Only the Stage 1 god ledger does this, for god powers. (Verified.)
7. **Two movement systems.** `instinct_move` is a biased random walk (noise plus bias vectors); Stage 1 added `anchor_mover` and `pathing` for task movement. Intelligent agents need one pipeline: intent, path, local steering, collision. (Verified.)
8. **Global randomness.** 16 `random.*` and 33 more in `systems/` plus `torch.rand` use the process-global RNGs, seeded once (`map_test.py`, `persistence/sessions.py`). Results depend on call order and on how many residents exist, which breaks replay, shadow-mode comparison and order-independent chunk generation. Snapshots save the global RNG state as a workaround. (Counts verified; consequence is reasoning.)
9. **Service-locator and module globals.** Instincts reach the engine through `ctx["engine"]` (for example `instinct_hunger` calls `needs_scale_vector(ctx.get("engine"), ...)`) and spatial lookup uses module-level `map_geo` globals. Systems cannot be unit-tested on a tiny synthetic world, two worlds cannot run in one process, and chunk-aware lookup cannot be swapped in cleanly. (Verified.)
10. **Packaging debt.** `instincts_and_tools.py` repeats its whole import block twice (`try: from systems...` / `except ImportError: from at_the_beginning.systems...`), the engine lives in a file called `map_test.py` (6,106 lines), and `instinct_*` and `tool_*` for the same job coexist (`instinct_find_buildable_site`/`tool_find_buildable_site`, `instinct_gather_materials`/`tool_gather_building_materials`, `instinct_repair_with_humans`/`tool_repair_area_with_humans`, and `tool_build_*`/`tool_construct_*` which are thin wrappers of two shared helpers). (Verified.)
11. **Almost untested legacy layer.** Of 46 test files only 2 reference `instincts_and_tools` directly; the Stage 1 suite (557 tests) covers the new systems, not the 120 legacy functions. Refactoring them blind is unsafe. (Verified by search; indirect coverage through `Engine` is possible but unmeasured.)
12. **No preconditions, costs or reversibility** on powers: `tool_smite` or `tool_cull` act immediately with no dry run, no rate limit and no undo. Acceptable for a human god; unsafe as a model-callable surface. (Verified.)
13. **Overloaded word "tier".** The registry's `tier` A/B/C means prompt exposure priority, not a model tier. It should be renamed (`exposure`) to avoid confusion with Tier 0 to 3.
14. **Hard limits**: acquired instincts use a 64-bit mask (`instinct_bit_range [0, 63]`), dense N x N distances per tick, and pixel-scale constants. All fine at Stage 1 size, all need a plan at 100+ residents and chunked space.

#### H.3 Proposed harness (the better design)

Principle: **commands in, effects out, events recorded, everything declared.** Build it as new packages beside the legacy code (a strangler migration, not a rewrite), with adapters so every old function keeps working while it is migrated.

1. **Declared systems with a computed schedule.** A `@system(name, phase, reads=[...], writes=[...], every=n)` decorator replaces float priorities. The scheduler orders systems per phase (sense, needs, decide, act, resolve, world, record) and by declared column reads/writes (a conflict is a build-time error, not a bug at runtime). It records per-system time every tick, which also gives the profile we currently lack.
2. **One action vocabulary.** Resident verbs (Appendix A.2) are `Action`s: typed parameters, `preconditions` (legality predicate shared with the affordance engine), `duration`, `interruptible`, `effects`. They run as state machines in the existing task system (`systems/tasks`). Per-tick instincts stay as Tier 0 systems; they stop being "things a model can call".
3. **Powers with dry-run.** God/world tools become `Power`s with `plan(params, world) -> EffectSet` (pure, no mutation; usable for preview and for validating a Tier 3 `world` proposal) and `apply(effect_set)`. The model gets structured validation errors from `plan()` and one bounded repair attempt.
4. **Effects as data.** Systems, actions and powers return typed `Effect`s (`Delta(entity, field, amount)`, `Set`, `Spawn`, `Despawn`, `Transfer(item)`, `Emit(event)`); one `EffectApplier` applies them in vectorised batches, enforces clamps and conservation (items cannot appear from nowhere), bumps the state revision (which the stale-result guard already uses) and writes the audit entry. Hot paths such as hunger decay may still write columns directly through a small `bulk` API with the same bounds enforcement. The Stage 1 command layer is extended, not replaced.
5. **Event ledger as the backbone of intelligence.** Every effect that matters emits an event (`id, tick, type, actors, place, visibility`); perception decides witnesses; subscribers are memory, gossip, goal generators, the Tier 1 trigger detector, the client log. This is what turns "a sword was made" or "someone stole bread" into memories and decisions. The god ledger is generalised into this.
6. **Typed selectors instead of string masks.** A JSON selector (`{"of":"residents","where":[{"field":"hunger","op":">","value":60}],"near":{"anchor":"well","radius":30},"order_by":"hunger","limit":3}`) validated by schema, compiled to masks by Python, resolved to **stable ids** at plan time and re-resolved at apply time. Every feature of the old DSL (`rank`, `dist`, bit tests) has a field in the new one; the old DSL stays as a legacy parser until nothing emits it.
7. **One movement stack.** Action or schedule produces an intent (target point or flow field), pathing produces waypoints, local steering sums the existing bias fields (survival, social, schedule) plus small wander noise, `spatial.slide` resolves collisions. `instinct_move`'s random walk becomes the wander term. Chunk-level flow fields serve long journeys.
8. **A narrow `World` facade.** Systems receive `World` (tensors, chunk-aware spatial index, clock, event ledger, effect applier, RNG streams, resident records) instead of `ctx["engine"]` and `map_geo` globals. Consequences: synthetic tiny worlds for unit tests, several worlds in one process for evaluation, and the infinite map swaps in a chunked spatial index behind the same facade.
9. **Counter-based RNG streams.** `rng(world_seed, tick, system, entity_id)` (Philox or an integer hash) replaces the global generators: results no longer depend on call order or population size, replay and shadow comparison become exact, and the chunk generator uses the same primitive.
10. **Manifest generated from decorators.** `@system`, `@action` and `@power` register themselves; the capability manifest (WS-C), JSON Schemas, OpenAPI fragments, ToolRAG index text, the training registry and the docs are generated from them, and a CI test fails on any undeclared callable. This replaces the hand-written registry (finding 4) and the `**_` signatures (finding 3).
11. **The simulation as an environment.** Add a headless `EdenEnv` (`reset(seed, scenario)`, `step(n)`, `observe(resident)`, `events()`), faster than real time and deterministic given the seed. It is used for scenario tests, soak runs, offline evaluation of Tier 3 plans, and training the Tier 1 matrix weights without the HTTP server.
12. **Perception-bounded observations.** Tier 1 features and Tier 3 prompts are built only from `observation(resident)` (what the resident perceives plus what it remembers), never from raw tensors, using the existing `prompt_view.py` pattern. This makes "no omniscient leakage" a structural property.
13. **Model-facing tool use.** Tier 3 uses JSON-schema function calling over plan ops and manifest entries retrieved per situation (ToolRAG), with a static cache-friendly prompt prefix, a dry-run feasibility check (reachability, materials, legality) returned as structured errors, and a budget per resident per game day. The model can only emit catalog items; Python validates and applies.
14. **Spatial scaling.** Keep dense pairwise `cdist` while loaded residents stay under roughly 300 (to be measured); beyond that, a chunk-keyed cell list gives neighbour candidates and the same masks apply. Profile first (item 1) before optimising anything.
15. **Packaging cleanup, test-guarded.** Make `at_the_beginning` a proper installable package (one import path, no `try/except ImportError` duplication), split the engine out of `map_test.py` into `engine/` modules **only after** characterization tests exist, and rename `registry tier` to `exposure`.

Proposed triage of the existing callables (confirm in P0; names are from the module, the merges marked "verified" were read in code):

| Group | Today | Proposal |
| --- | --- | --- |
| Vital-sign instincts | `instinct_age`, `hunger`, `thirst`, `stamina_tick`, `emotional_recovery`, `cooldown`, `die`, `hp_death`, `heal`, `shelter_check`, `structure_occupancy`, `infection_tick` | Keep as Tier 0 systems; add declared reads/writes; add the new needs (Appendix A.1) |
| Movement and steering | `instinct_move`, `search`, `survival_navigation`, `social_navigation`, `schedule_navigation`, `player_control_override`, `incarnation_stabilize` | Fold into the unified mover (item 7); possession logic moves to the control system |
| Decision logic inside the tick loop | `check_escalation`, `tool_inherit_instinct` (both registered as per-tick entries) | Move to the decision layer; they are not physics |
| Nature | `nature_cycle`, `fire_tick`, `lava_tick`, `resource_regrow`, `water_cycle` | Keep; make chunk-aware and lazy for unloaded chunks |
| Structures (14 callables) | `tool_build_house/village/farm/well` and `tool_construct_*` (verified wrappers), `designate_structure_site`, `find_buildable_site`, `gather_building_materials`, `build/repair/demolish_*_with_humans`, plus instinct twins | Merge to `build_structure(kind, mode=instant|with_humans)` as one Power and one Action family; delete the instinct twins |
| Hazards | `wildfire`, `earthquake`, `storm`, `volcanic_eruption`, `drought`, `flood`, `plague`, `area_attack`, `epidemic` | One data-driven `hazard(kind, center, radius, intensity, duration)` Power with a profile table; effects and events emitted uniformly |
| Animals (12) | `spawn_animal_group`, `populate_*`, `fill_land_*`, `restock_lakes_with_fish`, `herd/scatter/draw/stampede`, `feed/heal/make_animals_flee` | One `animals(op, ...)` Power plus species data; spawning moves to the chunk generator |
| Status setters | `set_mood`, `set_threat`, `calm_area`, `panic_area`, `bless`, `set_aggression`, `enlighten`, `reset_cooldown`, `age_shift`, `life_exp_modify` | One `modify_attribute(selector, field, op, value, bounds, duration)` Power plus named presets |
| Terraform | `create_lake`, `create_forest_patch`, `create_mountain_chain`, `create_feature_near_feature`, `transform_area`, `create_wall`, `settle_area` | Keep as chunk-aware map-edit Powers writing deltas (WS-D); retire `expand_world_edge` and `instinct_frontier_expand` |
| Acquired instincts | `grant/revoke/inherit_instinct`, 64-bit mask | Keep the mask as a cache; store grants as a set of ids; remove the 64 limit |
| Population | `born`, `reproduce`, `cull`, `smite`, `migration`, `quarantine` | Keep as Powers with preconditions and dry-run; `cull`/`smite` flagged `risk: destructive` |

**Migration order** (each step keeps the game and all 557 tests green): (1) characterization tests and a per-system profile of the current tick (golden traces from a seeded run); (2) `World` facade and counter-based RNG behind adapters; (3) decorators plus generated manifest and CI drift test; (4) Effects/EventLedger with legacy tools wrapped to emit events; (5) typed selectors; (6) unified mover; (7) merge the duplicated groups in the table; (8) package cleanup. Stage 2 features (WS-A, B, C, D) are written against the new interfaces from the start, so the new work is never built on the old contracts.

Gate H: golden-trace test shows identical outcomes (within a stated tolerance) before and after each migration step; manifest generated from decorators covers 100 percent of callables and the drift test is green; a hazard, an animal op and a status change run through `plan()` then `apply()` with events in the ledger and no direct tensor writes in the Power code; a seeded 30-game-minute run is bit-reproducible on two machines; per-system timing is published in `/model_status`-style status.

### WS-D. Infinite map

Facts that shape the design (verified in the repo): the engine world is fixed at `MAP_WIDTH x MAP_HEIGHT = 1200 x 900` units with 8 units per tile (`genesis_config.py`); entities live in a 1024-row `m_tensor` and humans in a 100-row `h_tensor`; spatial lookup uses `map_geo.TILE_TO_ENTITY`; the four authored 2D maps are placed inside that frame at origins `village[0,0]`, `smith[620,0]`, `lodge[620,400]`, `west[960,160]` with a 220-unit separation rule. `systems/map/chunking.py` (window math) and `chunk_generation.py` (terrain continuity) exist but nothing uses them. `h_tensor` columns 25 to 31 and `m_tensor` columns 13 to 31 are reserved.

Design (backend-authoritative; the world is sparse, the tensors hold only the active window):

- **D0 Audit (read-only, first).** Enumerate every use of `MAP_WIDTH/HEIGHT`, `GRID_W/H`, `TILE_TO_ENTITY`, clamps in movement/placement/spawn, and each tensor index assumption. Output: a table of call sites with the change needed. This sizes everything below and may change the plan.
- **D1 Spaces, not one frame.** Add a `space` concept: the open overworld is one space; every interior is its own space. Store the space id in a reserved column (`H_SPACE`, `M_SPACE`); perception, collision and proximity filter on equal space. This removes the shared-frame placement hack and the 220-unit isolation rule, and lets interiors be any size. Portals already exist (`POST /control/portal`); they change `space` plus position.
- **D2 Chunk coordinates.** **Revised 2026-10-08 after the D0 audit (`1008_d0_audit.md`, G-D0-1/G-D0-2): the earlier claim "float32 is fine to +/-100k units" was wrong for the collision code as written** (`EMBED_TOL = 1e-4` is below one float32 ulp for |x| >= 1024, the snap margin 0.001 below one ulp for |x| >= 16384, and `torch.cdist` is inexact above 25 rows: about 0.78 units of error at coordinates near 1000). Therefore: positions are stored **window-relative** (float32 offsets from an int64 chunk origin, a `SpaceFrame` owned by the World facade), so tensors never hold large absolute coordinates; absolute positions are `(int64 origin, float32 local)` pairs at the persistence and wire boundary; all distance code uses an exact helper, not bare `cdist`. Chunk = 32 x 32 tiles = 256 units = 1536 px at 48 px tiles (tile-based, so it lines up with authored maps and the Godot tile grid; the old design's 1200 x 900 px chunks are dropped). Persistent id is the integer pair `(cx, cy)`.
- **D3 Authored areas are pinned.** `starter_village` (and any later authored town) is a set of pinned chunks: it always loads from its map file, is never regenerated, and generation avoids it and blends into its border.
- **D4 Deterministic generator.** `generate_chunk(world_seed, cx, cy)` is a **pure function of the seed and the chunk coordinates only, not of neighbouring chunks or exploration order** (this corrects my earlier sketch; the existing `chunk_generation.py` samples the frontier neighbours, which would make the world depend on the path the player took, so it is a reference for biome-compatibility rules, not the algorithm). Continuity across chunk edges comes from sampling global coherent noise fields (elevation, moisture, temperature, river flow) that are defined everywhere, so adjacent chunks agree by construction. Tile-edge transitions (autotiling) read the 8 neighbouring tiles by sampling the same noise fields, so a chunk can be built before its neighbours exist. Features larger than a chunk (lakes, rivers, forests, ruins) are placed from a coarse region grid (for example 8 x 8 chunks) with hash-seeded cells and emitted by every chunk they overlap. The generator produces: biome from layered noise, resource nodes (trees, ore, berries, fish spots) and wildlife spawn tables with seeded placement, and rare points of interest (ruined camp, cave, shrine) as hooks for later lore. Output reuses the authored layer format (`terrain`/`decoration`/`footprint` layers with a palette of sprite paths relative to `myassets/`) so the Godot loader and validator stay one code path. Blocking tiles produce wall boxes in the same shape `systems/movement/spatial.py` already consumes.
- **D5 Sparse state with deltas.** Only changes are saved: placed/removed structures, depleted or regrown resources, killed animals, items on the ground, discovered flags, per-chunk generation version. A pristine chunk is regenerated from the seed. Save manifest records `world_seed`, `generator_version`, and a hash; Continue refuses a generator-version mismatch the way it already refuses a changed map (`persistence/map_guard.py`).
- **D6 Activation window.** Load chunks within R_load of any possessed actor or active resident, unload beyond R_unload (hysteresis). On load, entities get slots in `m_tensor` with stable ids (`e_NNNNNN` allocation moves to a persistent counter); on unload they are written back to the delta store. Budget: `MAX_ENTITIES` limits the window, so tune chunk contents (for example tree density as aggregate "forest" entities with per-tile harvest, as the design already prefers) rather than raising the cap blindly.
- **D7 Simulation level of detail.** Residents in loaded chunks run full Tier 0. Residents outside any window go **dormant**: no per-tick movement; their schedule and needs advance in coarse steps (once per game minute) using the same rules; they are materialised at the right place when a window reaches them. Animals and nature cycles do the same. This is what keeps cost proportional to what is near, not what has been explored.
- **D8 Wire protocol.** New `GET /chunks?cx0&cy0&cx1&cy1` (window query) returning chunk descriptors `{chunk_id, revision, sha256, url}`, `GET /chunk/{cx}/{cy}` returning exact bytes with ETag (same scheme as `/map_file`), and removals in the frame stream. The client sends a world-space view rectangle, not engine zoom. `/bootstrap` advertises `world.infinite: true`, `chunk_tiles`, `units_per_tile`, `generator_version`. Legacy finite worlds keep working unchanged.
- **D9 Client (Codex).** Godot 2D chunk loader: one `TileMapLayer` set per chunk, load/unload by distance, camera-driven requests, cached by sha256. Interiors render as their own space.
- **D10 Pathing.** Within a chunk window use the existing grid pathing; cross-chunk travel by coarse waypoints (chunk centre graph) then local pathing; long journeys by dormant fast-forward.

#### D11. Efficiency design: how live generation stays cheap

The user's requirement: only a window around the player exists, new land is generated as the player approaches, and it must be efficient. All numbers below are **design targets or arithmetic from repo constants, not measurements**; P3 produces `tools/bench_chunks.py` to replace them with measured values.

**Four concentric rings around each active actor** (distances in chunks of 256 units; the player walks at 20 u/s, so one chunk takes about 12.8 s to cross, and running is faster but still seconds per chunk):

| Ring | Radius (initial) | What exists inside it |
| --- | --- | --- |
| Render ring | camera rectangle plus 1 chunk | client tiles loaded and drawn (client cost only) |
| Simulation ring | about 2 chunks (5 x 5) | chunk entities hold `m_tensor` slots; residents and animals run full Tier 0; collision and pathing active |
| Generation (prefetch) ring | simulation ring plus 2 chunks, biased 2 more in the direction of travel | chunks are generated and cached ahead of need; no entities in tensor yet |
| Keep ring | prefetch ring plus 1 chunk (hysteresis) | beyond it a chunk is unloaded (deltas written, bytes dropped from the cache) |

With a 2-chunk prefetch lead, a walking player has at least about 25 s between "chunk requested" and "chunk needed". The generator budget is therefore generous (design target 50 ms per chunk), and the system must never make the player wait.

**Where the work runs** (the tick is 50 ms and must not be touched):
- Generation runs in a worker process (`ProcessPoolExecutor`, so the GIL is not shared with the tick), vectorised in `numpy` (noise fields as arrays over the 32 x 32 tile grid and a one-tile apron), returning a compact byte payload (tile ids as `int16` layers, entity list). No Python per-tile loops on the hot path.
- The tick thread only does **integration**: take at most one ready chunk per tick (design target below 2 ms), allocate its `m_tensor` slots, register its wall boxes and spatial-hash cells. Unloading is the same cost in reverse. Work is spread across ticks, never batched into one.
- A priority queue orders requests by distance and travel direction; stale requests (the player turned around) are cancelled before they start.
- Results are cached in an in-memory LRU of chunk payloads (a few hundred entries; one raw payload is on the order of 6 KB before compression, to be measured) keyed by `(world_seed, generator_version, cx, cy)`. Re-entering recently visited land costs a cache hit, not a generation. Only deltas touch disk.

**Memory and tensors**: chunk contents are aggregated on purpose (a forest patch is one entity with a tile mask and per-tile harvest, not hundreds of tree rows), with a per-chunk entity cap. With the simulation ring at 25 chunks and a cap of around 16 entities per chunk, the window needs about 400 rows of the 1024 in `m_tensor`, leaving room for animals, structures and authored areas; the cap is enforced and tested, and a chunk that would exceed it merges features instead.

**Spatial index**: replace the single global `TILE_TO_ENTITY` dict with per-chunk tile maps keyed by `(cx, cy)`, so a lookup is two integer divisions and a dict hit, and an unload drops one chunk's map. Proximity (`torch.cdist` over at most 100 humans) stays as is; entity queries first gather candidates from the actor's chunk and its 8 neighbours, then run the tensor math.

**Dormant residents and animals**: cost is O(number of dormant residents) per game minute, vectorised, not per tick. Their position is stored in chunk coordinates; on re-entry of a window they are placed along their schedule's expected route.

**Never walk into the void**: if a needed chunk is not integrated yet (slow disk, a stall), the boundary of the loaded area acts as an invisible wall in the authoritative movement code (the client can show fog). The player cannot outrun the world, and a late chunk is a delay, never a glitch or a crash.

**Client side**: the backend sends chunk descriptors for the requested window; the client fetches `GET /chunk/{cx}/{cy}` only if its cache lacks that `sha256`, and builds tile layers incrementally (a few chunks per frame). Payloads are small and cacheable by hash. The client keeps the render ring, the backend keeps the simulation ring; the two are independent.

**Determinism and test strategy**: integer-hash noise (no Python `random` state, no global RNG), fixed float64 pipelines with quantised thresholds so tile ids are integers on every machine, a golden-file test for a set of seeds and coordinates, and an order-independence test (generate the same area in two different orders, bytes must match).

**Metrics and gates (E = efficiency)**: generation ms per chunk (p50/p99), integration ms per tick, tick p99 while walking 5,000 units and while running, cache hit rate, number of times the void barrier triggered (must be 0 at walking speed), resident memory per loaded chunk, and save size after exploring 500 chunks without changes (must be near zero, because pristine chunks regenerate). Gate E: tick p99 within 2 ms of the no-streaming baseline during walking; zero void-barrier hits at walking speed; save size growth proportional to edits, not to distance travelled.

Gate D: determinism test (same seed gives byte-identical chunks across runs and machines); a resident can walk 5,000 units in a straight line with bounded memory; save, quit, Continue reproduces identical deltas; a chunk edit survives unload and reload; the 30/90 game-minute soaks with 8 residents stay at p99 <= 30 ms; a stress test with 100 residents spread over 200 chunks stays under the tick budget thanks to dormancy.

Fallback (D0 is done, 2026-10-08): the audit (`1008_d0_audit.md`) found the engine invasive but not a rewrite and recommends **not** taking the larger-fixed-frame fallback; the plan proceeds with chunked space behind the World facade.

### WS-E. World depth: from "go to the smith" to a living village

The model tiers are only useful if there is something to decide. Targets, each a scenario with a measurable pass condition rather than a feature list:

1. **Economy**: items, prices, barter and coin (`inventory/currency.py` exists), shops/stalls as stations, stock, scarcity. Scenario: drought raises food prices, a farmer rations, a gatherer sells.
2. **Occupations beyond the smith**: farmer, hunter, builder, healer, merchant, guard, using `OCCUPATION_DEFS` and `crafting/stations`. Each has stations, work anchors, tools and a daily routine; jobs can be taken, lost, inherited (`occupation/inheritance.py`).
3. **Social fabric**: relationships, reputation, gossip (witnessed events propagate as memories with decay), kinship, grudges/loyalty feeding the `goal` generators (`retaliate`, `protect_kin`, `recruit_allies`), simple norms (theft is noticed, help is remembered).
4. **Needs and emotions** beyond hunger/thirst: fear, loneliness, pride; affect mood and the feature vector.
5. **Memory**: `systems/memory` (MemoryRAG/LightRAG) feeds Tier 3 prompts with retrieved relevant memories; add reflection (Tier 3 summarises a day into durable beliefs).
6. **Events and stakes**: weather and seasons with consequences, predators, illness (`social/infection.py`), raids, travellers arriving from unexplored chunks. These are the situations that trigger Tiers 1 to 3.
7. **Player verbs**: the possessed player uses the same resident verbs and the same affordance engine, so no special cases.

Acceptance scenarios (each becomes a scripted regression test with the mock model first, then a shadow run with a real model):
- S-1 *Hungry family*: food runs out, a resident chooses between foraging far, trading, begging, theft; consequences propagate to reputation.
- S-2 *The stranger*: a traveller from a newly generated chunk arrives, is evaluated, trade or hostility emerges.
- S-3 *Commission, generalised*: Stage 1's sword order works for any recipe and any capable crafter, including refusal for lack of materials and referral to another smith.
- S-4 *God decree*: "bless the harvest" (Tier 3 `world`) changes crop yield; residents notice and talk about it; no omniscient leakage.
- S-5 *A winter*: seasonal scarcity over 10 game days with no scripted outcome; no starvation deaths from system bugs, only from genuine scarcity.

### WS-F. Assets and rendering (using `myassets/`)

What exists: a 48 px tile contract, `myassets/manifest.json` (69 root entries; packs: Medieval Village tilesheets `Ground`, `Walls`, `Roofs`, `Props_Decor`, `Sconce_Spritesheet`; Eden procedural periodic terrain `grass`, `cobble_tileable`, `flagstone_slate`, `paving_*`, `plank_floor`; locally generated `water-local-v2`, `sand-local-v1`, `nature_survival_atlas`; buildings, props, four body families, portraits); A4 animation work in progress (`myassets/a4`: run, door use, entry/exit frames with fixed pivots, still pilots). Public distribution of the generated art is **not cleared** (`ASSET_LICENSE_AUDIT.md`); this plan keeps the local-evaluation stance.

Needed for an unbounded overworld (to be confirmed by Codex against the real files; I have not checked every sheet):

1. **Biome palette**: terrain tiles for grass, forest floor, sand/beach, shallow and deep water, dirt, rock/mountain, snow, and **transition/autotile edges** between neighbouring biomes. If only periodic fill tiles exist, the generator needs either autotile sets or a shader-free blend rule; this is the main asset gap.
2. **Resource and wildlife sprites**: trees (several species/ages), bushes/berries, ore and stone nodes, fish spots, crops by growth stage, and top-down animals (sheep, deer, wolf, tiger already exist as entity types).
3. **Structures for emergent building**: house variants, fences, wells, workbenches, storage, farm plots, tents/camps; the Medieval Village sheets cover much of this.
4. **Day/night and weather presentation** (client-side tint, rain, snow) driven by backend time/weather already sent.
5. **A4 integration**: run, door and enter/exit clips follow authoritative state only (never decide traversal), as already agreed in X-063.
6. **Provenance**: every new asset keeps source/tool/model/seed/hash records in `ASSET_NOTICES.md`; prefer the user's local generator.

A tile-id contract keeps rendering and backend decoupled: the generator emits palette indices to sprite paths; the backend never reads pixels; collisions come from the generated wall boxes, not from art.

Gate F: a procedurally generated 3 x 3 chunk area renders in Godot with no visible seams, correct depth sorting, and walls matching the sprites; chunk load/unload at walking speed without frame drops on the target machine (target stated by Codex, not assumed here).

### WS-G. Evaluation, data flywheel and process

- **Replay and regression**: `RecordedDecisionProvider` extended to all roles; golden-trace tests so a change that alters decisions is visible.
- **Shadow first, always**: any new model or weight set runs in shadow for a soak before it may act.
- **Metrics that matter for "intelligence"** (beyond latency): goal completion rate, plan success rate, illegal-proposal rate, repeated-loop rate (flapping), dialogue consistency with decided outcomes, memory recall accuracy, deaths by cause, economic stability.
- **Data**: decision logs, plan records and dialogue logs are the training corpus (`models/` has the SFT/dataset scaffolding: `generate_sft_ds.py`, `sft.sh`, `tools_and_instincts_registry.py`). Dataset builders read the manifest, not hand-copied lists.
- **Performance budget**: tick 50 ms at 20 Hz; Stage 1 p99 was 28 ms for 8 residents; target 100 residents at p99 <= 40 ms with Tier 1 on and the mock server on; model calls never on the tick thread.
- **Hardware assumption**: the dev machine has one 8 GB GPU that also runs Godot; the model server defaults to hosted endpoints, with a local quantized path as an option (1006newdesign section 12). Nothing in the game assumes a GPU.
- **Git and ownership**: work on branches off `1006implementation`; no public publishing; scratchpad entries for any change to the wire protocol or client.

## 3. Phasing

| Phase | Content | Depends on | Exit |
| --- | --- | --- | --- |
| P0 | D0 audit (read-only); WS-H characterization tests, golden traces and per-system tick profile; capability manifest generator; baseline soak numbers re-recorded | nothing | audit table; profile; manifest covers all `tool_*`/`instinct_*` |
| P0.5 | WS-H harness core: `World` facade, counter-based RNG, `@system/@action/@power` decorators with generated manifest, Effects and EventLedger (legacy wrapped by adapters) | P0 | Gate H (part); all existing tests green |
| P1 | WS-A model plane + mock server; `ClefDecisionProvider` over HTTP | P0 | Gate A |
| P2 | Tier 1 matrix policy initialised from rules; affordance engine; option/mask for the smith scenario | P1 | Gate B (part), Gate C (part) |
| P3 | D1 spaces; D2/D3/D4 generator; D5 deltas; D6 window; protocol D8 (backend side) | P0 | determinism + persistence tests |
| P4 | Resident verbs, plan ops, Tier 3 adapters and prompts, escalation wiring and confidence gate | P1, P2 | Gate C; shadow mode live |
| P5 | D7 dormancy, D10 pathing; client chunk loader (Codex); asset gaps closed (Codex) | P3 | Gate D, Gate F |
| P6 | World depth scenarios S-1 to S-5 with mock models | P2, P4 | scenarios pass |
| P7 | **Held until the user supplies the model APIs.** Config only: point the adapters at the endpoints, run `tools/model_conformance.py`, then shadow, then `on` per role (Clef shadow first, then Tier 3 `resident` on one resident, then widened) | P1, P4 and the user's APIs | S2.0 to S2.4 metrics |

P1 to P3 can run in parallel (different files). Nothing in P0 to P6 needs a real model, and the LLM switch is built in P1, so every later phase is tested with models both off and mocked on.

## 4. Risks

- **Tensor engine rigidity** (biggest): fixed shapes and global clamps may make D1/D6/D7 expensive. Mitigation: D0 first; fallback is a larger fixed frame with streaming.
- **Model claims unverified**: Clef specs and latency are second-hand. Mitigation: the Tier 1 matrix policy, rules fallback, S2.0 evaluation before any dependency.
- **Complexity creep in capabilities**: three audiences could blur. Mitigation: the manifest `audience` field is enforced by tests; residents cannot call god tools.
- **Save compatibility**: every new state (spaces, chunks, weights) must go through the manifest/guard, or old saves silently break. Mitigation: versioned manifest sections and refusal over silent migration, as in Stage 1.
- **Asset licensing** blocks any public release; unchanged from Stage 1.
- **Scope**: this is large. The phase table is ordered so each phase is independently useful and testable.

## 5. Still open

- **Q3 (explained, awaiting a yes or no).** Today the four maps (village, smith, lodge, west cottage) all sit inside one 1200 x 900 coordinate frame, with interiors parked beside the village at fixed origins and kept more than 220 units apart so residents inside a house cannot "see" the village. That does not scale to an endless world (where would the next interior go?). D1 changes it: every interior becomes its own separate space with its own coordinates, and a door moves an actor between spaces. Effects: interiors can be any size; the 220-unit rule and `EDEN_MAP_ORIGINS` disappear; the save format gains a space id, so **saves from the Stage 1 build will be refused by Continue** (a deliberate rule, not silent corruption). Nothing visible changes to the player. Recommendation: yes. If no, the infinite overworld would still have to reserve a far-away "interior zone" in the same frame, which is more fragile.
- **Clef request/response mapping**: held by decision until the real API is supplied.
- **Hosted vs local models**: moot for now; the model server is API-only.

## 6. Decisions recorded (2026-10-08, from the user)

1. Tiers are Tier 1 matrix, Tier 2 Clef, Tier 3 LLM; there is no Tier 4 (section 1).
2. The map is rendered and simulated only around the player and generated live ahead of the player's approach; the design must be efficient (WS-D, D11). "Infinite" in practice means seed-deterministic and limited only by float precision; no separate guarantee is required.
3. Interiors as separate spaces: explained under Q3, decision pending.
4. We write only code and an API-first boundary; the user works on the models later and supplies the APIs. No model hosting, training or fine-tuning is in this plan's scope.
5. Stage 2 delivers the full intelligent game with an on/off switch for the LLM tiers, with all tools and instincts (expanded per Appendix A) ready, and Clef details held until the real API arrives.
6. The original tools and instincts are old and must be evaluated and redesigned where better, not just extended: WS-H records the evaluation (14 findings, with what was and was not verified) and proposes the replacement harness and a test-guarded strangler migration.

## Appendix A. Proposed expansion of instincts, verbs and tools

Today: 46 `instinct_*` and 74 `tool_*` functions in `instincts_and_tools.py` (disasters, spawning, terraforming, animals, construction, grants) plus the task families `survival`, `social`, `combat`, `occupation`, `construction`, `strategic`. The gap for a real AI game is **resident-level verbs and richer needs**, not more disasters. Every entry below needs a manifest row, a legality predicate, a rules implementation (so it works with models off), and a test. Names are proposals.

**A.1 New Tier 0 instincts (per tick, vectorised, no model):**
- `instinct_fear_response` (threat drives flee, freeze or hide by personality), `instinct_fatigue_sleep_pressure` (sleep debt, nap), `instinct_temperature_comfort` (cold, heat, clothing, fire, shelter), `instinct_wound_recovery` (bleeding, infection risk, healing rate), `instinct_loneliness` and `instinct_boredom` (feed mood and the social/explore goals), `instinct_grief` (kin death affects mood and goals), `instinct_darkness_unease` (night fear), `instinct_territory_guard` (defend home), `instinct_curiosity` (drives exploration into new chunks), `instinct_food_spoilage`, `instinct_crop_growth`, `instinct_resource_depletion_regrowth` (per chunk, lazy), `instinct_herd_follow` and `instinct_predator_stalk` (animals), `instinct_rumor_spread` (witnessed events become gossip with decay), `instinct_reputation_update`.

**A.2 Resident verbs (the Tier 1 menu and Tier 3 plan ops).** Grouped; each is a typed op with parameters:
- Survival: `eat`, `drink`, `rest`, `sleep`, `seek_shelter`, `light_fire`, `treat_wound`, `flee_to`, `hide`.
- Work: `go_to_work`, `work_shift`, `gather_resource`, `hunt`, `fish`, `farm_tend`, `craft`, `repair`, `build_structure`, `haul_items`, `store_item`, `fetch_item`.
- Economy: `offer_trade`, `accept_trade`, `request_item`, `give_item`, `buy`, `sell`, `set_price`, `commission_item` (generalised Stage 1 loop), `pay_debt`.
- Social: `greet`, `chat`, `ask_for_help`, `comfort`, `teach`, `share_news`, `gossip`, `court`, `befriend`, `apologise`, `forgive`, `follow`, `invite`, `ask_directions`.
- Conflict and law: `warn`, `threaten`, `defend`, `attack`, `arrest_or_restrain`, `steal_when_safe`, `report_crime`, `avoid`, `retaliate`.
- Exploration and knowledge: `explore_toward`, `scout_region`, `mark_place`, `remember_place`, `lead_group_to`, `migrate_group`, `settle_site`.
- Cognitive control (route to higher tiers): `USE_BRAIN`, `REPLAN`, `PLOT`, `reflect`, `continue_plan_step`.

**A.3 God and world tools to add** (Tier 3 `world` and the god panel, never resident-callable): `tool_set_season`, `tool_spawn_traveller` (with a seeded backstory hook), `tool_seed_rumor`, `tool_grant_item`, `tool_set_relationship`, `tool_trigger_event` (festival, market day, raid, famine), `tool_reveal_resource_node`, `tool_found_settlement_site`, `tool_set_prices`, `tool_teleport_actor`, `tool_pin_chunk` (keep a region loaded), `tool_regenerate_chunk` (explicit, destructive, confirmed).

**A.4 Ordering.** Implement in the order the acceptance scenarios need them: S-3 (generalised commission) needs the economy and craft verbs; S-1 (hungry family) needs survival, work, social and conflict verbs plus gossip and reputation; S-2 (the stranger) needs `tool_spawn_traveller` and chunk generation; S-4 (decree) needs the manifest-driven ToolRAG path; S-5 (winter) needs temperature, spoilage and crop instincts.
