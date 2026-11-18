# 1008 Tier 3: model adapters, the confidence gate and escalation (round 2, P4)

Code: `at_the_beginning/systems/modelplane/tier3/` (`context.py`, `parsers.py`, `router.py`, `escalation.py`, `types.py`), `systems/actions/plan_adapter.py`, mock backend in `model_server/backends/heuristics.py`. Wire contract: `../contracts/model_api.md`. Everything is **off by default**: with the three Tier 3 slots at `off` no job, thread, socket or feature build exists (tested).

## 1. What is new on the wire

| Role | New mode | Case (typed, whitelisted) | Packet |
| --- | --- | --- | --- |
| `resident` | `plan_ops` | `resident_id, tick, reason, needs{hunger,thirst,stamina,hp,threat,mood}, scene{feature: 0..1}, goals, plan, options[{verb, params, distance?}], plan_ops[], limits` | `resident_id, confidence, steps[<=8 of {op, args}], summary?` |
| `world` | `director` | `query, reason, tick, residents, powers[{name, risk, args, example}], max_intents` | `thought, intents[<=6 of {power, args, reason?}]` |
| `dialogue` | (existing `talk_reply` / `ambient_npc_talk`) | `prompt_case` from a `DecidedOutcome` | `speech_text, speech_act, tone, physical_intent` |

A case is built from the Tier 1 feature builder and the affordance engine (only options legal *now*, at most 2 per verb, 12 in all). `assert_case` is a tripwire: unknown keys, forbidden keys (raw state, other residents' records, tensors, ids not in the whitelist) or a case over 6000 characters raise `ContextError` before anything is queued.

## 2. Parsers and the confidence gate (`parsers.py`)

A reply is untrusted. `parse_plan` / `parse_line` / `parse_intents` either return a typed proposal or raise `PacketError(code)`. Then the gate:

| Role | Gate | Reason codes (stable, counted as `gate:<code>` in `/model_status`, logged as `{"type":"tier3"}`) |
| --- | --- | --- |
| resident | non-empty, <= `max_steps`, `confidence >= min_confidence` (placeholder 0.6, tuned from shadow data), every op in `PLAN_OPS`, args schema-valid, and the ActionRunner's **dry run of step 0** is legal now | `empty_plan`, `too_many_steps`, `low_confidence`, `unknown_op:<op>`, `invalid_step:<i>:invalid_arguments`, `illegal_step:0:<runner code>`, `invalid_packet:<code>` |
| dialogue | wording only: `speech_text`, act, tone, one *allowed* `physical_intent`; obligations, items, trades and deltas are ignored | `invalid_packet:*` -> the rules line (`fallback_line`) |
| world | every intent is planned (never applied) by `harness.powers.plan`; destructive powers refused unless `allow_destructive_powers` | `unknown_power:*`, `risk_gated`, `invalid_arguments:*`, `no_intent`, `no_valid_intent` |

Failure of any kind (refused by admission control, timeout, breaker open, wrong epoch, switch toggled in flight, contract-breaking reply) leaves the resident on Tier 1 / the rules and records the reason; a line request always carries the rules' fallback line.

## 3. The router (`Tier3Router`)

Pull model, like the rest of the plane. `request_plan | request_line | request_intents` return a `Ticket` at once (`off` before any job exists; `pending`; `refused`). `ModelPlane.pump()` calls the job's `on_complete`, which parses, gates and stores a `Tier3Result`:

* **shadow**: stored and logged (`status="shadow"`, `would_apply` = the gate's verdict), never offered to a caller, world unchanged (tested by a before/after digest);
* **on**: offered once through `poll_plan | poll_line | poll_intents`: `accepted` (use it), `rejected` / `fallback` (use Tier 1 / the rules).

Nothing in the router executes a plan; the consumer runs an accepted plan through `run_plan(runner, actor, steps)`, and `apply_intents` applies accepted world intents through `harness.powers.apply` (atomic each).

## 4. Escalation wiring (`escalation.py`), no engine edit

`install(DISPATCH, plane)` (called from `api/model_routes.py::build_model_router`, which `map_test.py` already calls) registers one **builtin post-step hook** (`tier3_escalation`) that finds the engine's plane (`engine._model_plane`). While the resident slot is `off` it returns on its first statements. Otherwise, every `period` (1) tick it examines the next `batch` (1) resident, round robin over the roster (the first version examined 6 residents every 20 ticks at about 20 ms per sweep: the Gate A sweep cell measured +15.1 ms on p99 against a +2 ms budget, a real defect). Cost control, in order: (1) **prefilter** (`prefilter=True`): a pure tensor read decides whether the resident can trigger anything at all - hunger/thirst below `urgent_need`, threat not above `significant_threat` and low hp not above `significant_low_hp` means *calm* and nothing else runs (about 0.02 ms per tick, measured on the real engine); macro triggers (`USE_BRAIN`/`REPLAN`/`PLOT` chosen by the placeholder weights) of calm residents are therefore **not looked for**, on purpose; (2) a resident whose rounded inputs are unchanged since its last evaluation inside one cooldown window is skipped; (3) one world-judged mask per evaluation instead of two; (4) the affordance services cache the wall boxes once per tick (the mask asked for them hundreds of times); (5) `Escalator.warm()` at install pays the imports and the initial matrix. Measured on the real engine (400 ticks, 8 residents, 0/2/8 starved): mean 0.018 / 0.151 / 0.266 ms per tick, an evaluated tick costs about 4 ms (first one 12 ms), never more than 12.6 ms. That is not the "no tick above ~3 ms" target; the Gate A cell with the sweep has to be re-run before any claim about p99. For an evaluated resident the pipeline is:

features (Tier 1 feature builder) -> legality mask (affordance) -> `MatrixPolicy.decide` -> `classify`:

| Trigger | Meaning | Routes to |
| --- | --- | --- |
| `macro:USE_BRAIN`, `macro:REPLAN`, `macro:PLOT` | Tier 1 chose a cognitive macro | resident `plan_ops` |
| `tier1_uncertain` | `MatrixPolicy.gate`: uncertain AND (threat > 0.3 or low hp > 0.5) | resident `plan_ops` |
| `unmet_need` | hunger/thirst >= 0.8 with no legal eat/gather (drink) | resident `plan_ops` |
| `unresolved_threat` | threat > 0.3 and nothing legal among flee/hide/avoid/defend/ask_for_help | resident `plan_ops` |

At most 2 requests per sweep, a per-(resident, trigger) cooldown of 100 ticks, `parent_tier=1` on the job (the plane's depth cap and `causal_id` dedupe still apply). Shadow records only. In `on` mode the hook polls the router each tick and starts a `PlanCursor` for an accepted plan (`step_mode="cursor"`; `"oneshot"` = `run_plan`): the ActionRunner re-judges every step (schema, grounding, legality, rate/risk, audit), the next step starts when the previous step's task has ended, and the plan aborts on a refused step, a task timeout, a failed task or a changed world/model epoch. Outcomes are counted `run:ok` / `run:failed:<reason>` and logged as `tier3_run`. A rejection leaves the resident on Tier 1.

Dialogue and the world director are not swept: they are asked by their own call sites (`line_or_fallback(decided)` from a talk reply, `request_intents(query)` from a decree), which a game integration calls when the slot is not `off`.

## 5. Status and switch

`GET /model_status` has `switch.{tier2, tier3_resident, tier3_dialogue, tier3_world}`, the per-role metrics, and a `tier3` block (gate config, pending/ready, per-kind results, reasons, recent results, `escalation` counts and last sweep ms). `POST /control/models {"tier3_resident": "shadow"|"on"|"off", ...}` and `{"all_off": true}` flip modes (400 on a bad value, nothing changes); every effective change bumps the model epoch and drops cached answers.

## 6. Plan adapter (`systems/actions/plan_adapter.py`)

`systems/planning` is not edited. Its validator accepts only its 13 legacy ops, so Tier 3 plans stay in the S1 form `{op: <verb id>, args}`. `from_legacy` / `to_legacy` map the legacy ops that have an S1 verb (`rest_until_safe`, `recover_until_hp` -> `rest`; `move_to_target` -> `follow`; `move_to_place` -> `go_to_work`) and report the rest as `unmapped` with a reason (`no_s1_verb`, `needs_grounding`, `missing_target`, `unknown_legacy_op`). Nothing is guessed.

## 7. Mock server

`mock` answers all three roles from the case alone: `plan_ops` picks 1-3 steps from the *offered* options (need-weighted, seeded tie-break, confidence 0.5-0.95), `director` returns one reversible power with its catalog example args, dialogue uses the existing wording heuristics. `EDEN_MODEL_MOCK_SEED` changes the answers reproducibly.

## 8. Not done

* Tier 2 (`decide`) is not re-routed by the sweep: the existing `ClefDecisionProvider` path is unchanged; `tier1_uncertain` goes straight to the resident role. Wiring a `decide` request from the sweep (and Tier 2 -> Tier 3 on low confidence) needs a DecisionRequest builder for macro menus.
* `min_confidence`, `period`, `batch`, the thresholds are placeholders; no real model has been run against any of this (mock and scripted transports only).
* The talk-reply and decree call sites do not call the router yet (they are game code outside this slice).
* Later plan steps are schema-checked at the gate and judged by the runner when they run. In `on` mode a plan now runs through `PlanCursors` (one step at a time, the next waits for the previous task; `./actions.md` 10.9), so a step that depends on an earlier task no longer fails legality for that reason; a plan whose later step is illegal when its turn comes still aborts (reason logged, resident back on Tier 1).
* The 48 unregistered verbs are not added here.
