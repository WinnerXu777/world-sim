# 1006 New Design: Tier 1 Decision Model Between Deterministic Code and LLMs

Date: 2026-10-06
Status: design proposal. No code has been changed. Extends the model-tier plan in `implementation_0905.md` (I0-I5) and respects the delivery order in `ENGINEERING_REVIEW.md`.

## 1. Summary

Eden's current tier plan has deterministic execution at the bottom and generative LLMs (world, resident, fast interaction) above it. This document inserts a **Tier 1 decision tier** between them.

Tier 1 is a *typed decision model*: given a snapshot of one resident's state and a finite list of allowed options, it returns a probability for every option in a single forward pass. It does not generate text. Candidate models are Cloudflare's **Clef-Flash** (9B) and **Clef** (27B), with AutoTrust's **JEV/GEV** family as alternatives. All are described from a ChatGPT conversation (see section 12) and must be verified before we depend on them.

Tier 1 does three jobs:

1. Choose among a resident's allowed actions when deterministic rules are not enough.
2. Decide *whether to think harder*: `USE_BRAIN`, `REPLAN` and `PLOT` are ordinary options that route to the resident LLM (Tier 2).
3. Decide yes/no or accept/refuse on dialogue-driven requests (for example a commission) before any text is written.

The deterministic game remains authoritative. Tier 1 only ranks options that Python has already validated as legal.

## 2. Goals and non-goals

Goals:

- NPC behavior that reflects personality, memory and goals without calling a generative LLM for every decision.
- Bounded, observable latency, because there is no autoregressive decode.
- Outputs that are easy to validate: a choice from a closed set, not free-form text or code.
- A seam that works with no model at all, so the Stage 1 playable game (Gates A-H) is unaffected.
- Every decision logged so it can later become fine-tuning data.

Non-goals:

- Replacing the deterministic instinct, schedule, survival, combat or movement systems.
- Continuous or low-level control (movement vectors, combat inputs). The source material reports decision models do poorly here.
- Dialogue wording, plan generation or world reasoning. Those stay generative (Tier 2 and Tier 3).
- Kernel-level or serving-engine optimization. The target scale is 8-12 named residents (Milestone 3), not thousands.
- Training or fine-tuning in the first iteration.

## 3. Tier model

| Tier | Component | Invoked | Output | Authority |
| --- | --- | --- | --- | --- |
| 0 | Deterministic execution: instincts, schedules, survival, movement, combat, crafting, inventory | Every tick | World commands | Authoritative |
| 1 | **Decision model (new)** | On trigger events, per resident | Probability per allowed option | Proposes a choice only |
| 2 | Resident LLM | When Tier 1 chooses `USE_BRAIN`/`REPLAN`/`PLOT`, on low confidence, or on scheduled review | Goals, plans, negotiation outcomes (structured) | Proposes; validated by planning system |
| 3a | Fast interaction model | When a dialogue line is needed | Short speech or reaction text | Cannot accept obligations |
| 3b | World model | God decrees, significant world events, slow review | Validated world operations | Proposes; validated by execution agent |
| - | TTS | After a line is accepted | Audio | Presentation only |

Mapping onto the existing I0 roles: Tier 1 is new. Tier 2 is the existing "Agent/resident model". Tier 3a and 3b are the existing "Fast interaction" and "World" models. Tier 0 is the existing "Deterministic execution".

Rule of thumb for routing: if the answer can be computed by rules, Tier 0 does it. If it is a choice among known options, Tier 1. If it requires inventing something new (a plan, a goal, a sentence), Tier 2 or 3.

## 4. What Tier 1 sits on in the current repo

Based on the design docs, not a code audit:

- **Escalation system** (`systems/escalation`): extracts signals, scores lanes, routes residents to urgent or normal batches. Tier 1 becomes a consumer of these lanes. Today they feed the human-agent scheduler.
- **Tool and instinct registry plus LightRAG**: already retrieves a compact top-k of tools per query. This is the natural source of option lists.
- **Planning system** (`systems/planning`): validated, compiled plans with lifecycle and review state. Tier 2 writes here. Tier 1 reads the current plan step to build options.
- **Goal, schedule, personality, memory systems and resident sidecars**: supply the state snapshot.
- **Execution agent**: remains the only path that mutates the world.
- **I1 job boundary**: immutable jobs with deadline, priority, world/control epoch and cancellation. Tier 1 jobs use the same envelope.

## 5. The decision contract

A single provider interface, implemented first without any model.

```
DecisionRequest
  job_id, resident_id, world_epoch, state_revision, tick
  trigger            # event type + causal event id
  question_kind      # choice | yes_no   (score is a later addition)
  state              # structured snapshot (section 7)
  options[]          # id, one-line description, tags
  priority           # critical | active | background
  deadline_ms

DecisionResult
  job_id, resident_id, world_epoch, state_revision
  probabilities      # option id -> p
  top_option, top_p, margin
  provider_mode      # live | mock | rules | fallback
  latency_ms
```

Rules for the contract:

- `options` are produced by Python and already filtered for legality: range, ownership, materials, target liveness, current job freshness. The model never sees an option the resident could not execute.
- A result is applied only if `world_epoch` and `state_revision` still match at apply time. Stale results are dropped, consistent with the review's rule for stale proposals after death, possession changes or reload.
- `provider_mode` is always visible in status output, as the review requires (live, mock or fallback).

### Providers

1. **`RulesDecisionProvider` (build first)**: scores options from personality, needs, goals and relationships using deterministic weights. Used by Gate H scripted NPCs. Also serves as the permanent fallback.
2. **`RecordedDecisionProvider`**: replays logged decisions for tests.
3. **`ClefDecisionProvider`**: calls a hosted or local Clef-Flash endpoint.
4. Optional later: JEV/GEV providers behind the same interface.

## 6. Options: where they come from

An option list is built per request from four sources, merged and capped (target 4-12 options, hard cap well under the model's 256):

- **Plan options**: `continue_current_plan_step`, `abandon_plan`, from the planning system.
- **Situational actions**: retrieved from the registry (LightRAG top-k) and filtered by what the resident's occupation, inventory and surroundings allow.
- **Social options**: when a player or resident is present: greet, ask, accept request, refuse, haggle, report, avoid.
- **Cognitive options**: `USE_BRAIN`, `REPLAN`, `PLOT`, `INVESTIGATE`. Always present when the trigger is significant. Each option carries a one-line description, since descriptions improve accuracy in the source material.

Cognitive options are what make Tier 1 a "cognitive scheduler": it is how a resident gets escalated to Tier 2 without hard-coded thresholds alone.

## 7. State snapshot and prompt layout

Build the prompt from stable to volatile content. This is cheap to do now and pays off only if we self-host with prefix caching, so do not optimize beyond the ordering.

1. World and game rules (identical for everyone)
2. Occupation/archetype description (shared by role)
3. Location summary (shared by nearby residents)
4. Personality (stable per resident)
5. Long-term memory summary and relationship summary
6. Current goals and current plan with step
7. Recent perceived events (bounded)
8. Current observation / trigger
9. The question and the option list

Constraints:

- Budget 1K-8K tokens per request. Do not fill the model's maximum context; the source material notes long inputs destroy the latency advantage.
- Only facts the resident knows or perceives. Label rumors and uncertainty, per I2.
- Fields that change often (gold, hunger) go late so they do not invalidate shared prefixes.
- The snapshot is built from committed state and is immutable once enqueued.

## 8. Triggers and cadence (event-driven, not polling)

Tier 1 is called when something significant happens, not every tick. Initial trigger set, to be wired through the escalation signals:

- player enters interaction range or starts a conversation
- hostile or threatening entity perceived
- damage taken or ally harmed
- goal completed or plan step failed
- new consequential information learned (witnessed event, rumor)
- relationship change
- resource threshold crossed (for example needed material arrives or runs out)
- time-of-day schedule transition where the schedule offers a real choice
- god-power consequence perceived (for example iron appears for the smith)
- periodic low-frequency review while idle, as a safety net

Between triggers, residents follow Tier 0 behavior and their current plan step. No trigger means no model call.

Guards against runaway calls: per-resident cooldown, per-trigger dedupe by causal event ID, bounded escalation depth (Tier 1 -> Tier 2 -> Tier 1 cannot loop), and a global rate cap.

### Priority lanes

| Lane | Examples | Batch window | Deadline |
| --- | --- | --- | --- |
| critical | combat reaction, being attacked | very short | tight; fall back to Tier 0 on miss |
| active | player nearby or talking | short | about 1 s |
| background | routine residents, idle review | long | several seconds; may be dropped or deferred |

Player conversation outranks all else (consistent with I1). Numbers are placeholders until measured.

## 9. Interpreting the output

Do not blindly take the top option.

1. **Confidence gate**: if `top_p` is below a threshold, or the margin between the top two is small, treat the result as uncertain and escalate (add `USE_BRAIN` handling) to Tier 2 when the situation is significant. For minor situations, take the rules provider's choice instead.
2. **Sampling**: for non-critical choices, sample from the distribution with a temperature, optionally masked by personality, so residents vary without leaving their character. Critical and survival choices use argmax.
3. **Routing by option type**:
   - Physical/social option -> convert to a validated command and submit through the normal queue to the execution agent.
   - `continue_current_plan_step` -> no-op, Tier 0 continues.
   - `USE_BRAIN`/`REPLAN`/`PLOT` -> enqueue a Tier 2 job with the trigger and relevant context.
4. **Validation at apply time**: re-check legality against live state. If it fails, record the rejection, drop the result, and let Tier 0 act.

## 10. Interaction with Tier 2 and dialogue

### Tier 2 (resident LLM)

- Receives the trigger, the Tier 1 distribution (useful context), and grounded resident context.
- Outputs a structured plan or goal change that goes through the existing planning validator and compiler. Nothing here mutates the world directly.
- After a plan is stored, Tier 1 uses the plan's current step to build options. The big model is not needed again until a trigger demands it. This is the "plan once, execute cheaply for a long time" pattern.
- Tier 2 may also propose new goals or "possible pursuits". Tier 1 then scores them against personality and circumstances.

### Dialogue and promises (the smith example)

1. Player requests a sword.
2. Tier 0 and the task system compute feasibility facts: iron available, forge intact, capacity.
3. Tier 1 receives options such as `accept_commission`, `refuse_no_iron`, `haggle_price`, `defer`, `USE_BRAIN`.
4. If accepted, the deterministic task system reserves iron and schedules work. A promise is never made unless this step succeeds.
5. Tier 3a writes the reply wording from the *decided outcome*, so speech cannot contradict or invent the decision.

This matches the existing rule that the fast interaction model cannot independently accept obligations.

## 11. Staging relative to the existing plan

The review and `implementation_0905.md` say the deterministic game (Gates A-H) comes first and model integration is Stage 2 (I). This design does not change that.

### Stage 1 additions (small, safe, no model)

- Define `DecisionRequest`/`DecisionResult` and the provider interface.
- Implement `RulesDecisionProvider` and use it for scripted NPCs and the promise-to-action loop.
- Build option lists from the registry, plan and social context.
- Wire escalation triggers to produce decision requests.
- Add decision logging (section 14) and a status endpoint that shows provider mode.

Exit condition: scripted NPCs run entirely through the provider interface, with the game passing Gate H.

### Stage 2 (after Gate H)

- **S2.0 Evaluate**: stand up a Clef-Flash endpoint (hosted first) and measure latency, calibration and agreement with the rules provider on logged decisions.
- **S2.1 Shadow mode**: Clef runs on real triggers but its result is only logged next to the rules choice. No gameplay effect.
- **S2.2 Live for background lane**: apply Clef decisions for low-stakes residents and choices, with rules fallback.
- **S2.3 Live for active lane**: player-adjacent decisions and dialogue-intent choices.
- **S2.4 Escalation**: connect cognitive options and the confidence gate to Tier 2 (I0/I1 job boundary).
- **S2.5 Optional**: fine-tune on logged decisions; evaluate local serving.

Each step must keep Gate H behavior reproducible with providers disabled.

## 12. Model and deployment notes

Source: a ChatGPT conversation from the week of 2026-10-01 that discusses these models using web search results. These are second-hand claims, not verified by us. Verify before committing.

Claimed facts to verify:

- Clef-Flash: 9B, Qwen3.5 backbone, Apache-2.0, joint schema head, hosted on Workers AI as `@cf/cloudflare/clef-flash`, hosted context window 64K. Reported median latency about 39 ms in Cloudflare's own environment.
- Clef: 27B variant, higher quality, reported median latency about 209 ms.
- Models accept typed questions and options and return a probability per option; they are non-generative.
- Community quantizations (GGUF, GPTQ/W4A16, FP8, etc.) of Clef-Flash exist.

Deployment options:

| Option | Pros | Cons |
| --- | --- | --- |
| Hosted Workers AI endpoint (start here) | No local VRAM, no serving setup, fast to evaluate | Network latency, cost, offline play impossible, needs credentials handling |
| Local quantized Clef-Flash | Offline, no per-call cost | About 4.5 GB or more VRAM on an 8 GB card that also runs Godot rendering; Windows serving friction |
| Separate machine/WSL/Docker server | Isolates GPU load | More setup; vLLM is not installed on Windows in `requirements-models.txt` |

Technical cautions:

- Confirm that the chosen serving path actually runs the joint decision head. A standard chat-completions endpoint on vLLM or SGLang may not exercise it, and some quantizations may not preserve it.
- Local latency on an RTX 4060 is unknown; the hosted numbers do not transfer.
- Never put credentials in saves or logs (I1). Mark provider mode live, mock, rules or fallback.
- Serving-level optimization (shared-prefix attention kernels, radix scheduling) is out of scope at this population size.

## 13. Failure behavior

- Provider timeout, error or stale result: use `RulesDecisionProvider`, record `fallback`, keep the resident working.
- Provider unavailable for a sustained period: stay in rules mode and surface it in status.
- Malformed or missing probabilities: treat as failure.
- Option that fails live validation: drop and log; Tier 0 acts.
- Deadline missed in the critical lane: Tier 0 reaction already happened; late result is discarded.
- World reload, possession change or death: epoch change cancels pending jobs.

A slow or unavailable model must never starve player dialogue or deterministic execution.

## 14. Logging and training data

Each decision logs: job ID, resident ID, tick, trigger and causal event ID, state snapshot (or a reference to it), options, probabilities from each provider that ran, chosen option and how it was chosen (argmax, sampled, gate-escalated, fallback), validation result, and the later outcome if known (task succeeded, resident harmed, plan abandoned).

Uses:

- Shadow-mode comparison of Clef vs rules.
- Calibration of the confidence threshold.
- Regression tests via `RecordedDecisionProvider`.
- Labeled data for later fine-tuning. The existing `models/` SFT pipeline can be adapted for this, since the source material says Clef supports task-specific fine-tuning (verify the current tooling).

Keep raw prompt logging opt-in and bounded, as the review requires. Keep logs outside active user saves.

## 15. Metrics and tests

Metrics, per tier and lane: requests, latency p50/p95/p99, queue age, timeout/fallback rate, escalation rate to Tier 2, cache-friendly prefix length, rules-vs-model agreement, stale-drop count, validation-rejection count.

Tests:

- Contract tests for the provider interface with the rules and recorded providers (no network).
- A deterministic end-to-end test: trigger -> options -> decision -> validated command -> world change.
- Stale-result tests across epoch change, death and possession.
- Escalation-loop test showing bounded depth and cooldowns.
- Promise test: an accepted commission always reserves materials; a refused or failed one never creates an item.
- Failure tests: provider down, slow, malformed output.
- Shadow-mode report comparing providers on the same logged states.

## 16. Risks and open questions

Risks:

- **Temporal consistency**: the source material notes there is no evidence yet that decision models stay coherent across thousands of sequential decisions. Mitigation: keep personality, goals, plan and memory explicit in game state; use the model as a per-moment policy.
- **Option design dominates quality**: poor or overlong option lists will hurt more than model choice. Budget time for option and description design.
- **Calibration**: probability thresholds for escalation need empirical tuning; do not trust the defaults.
- **Overbuilding**: the batching and caching ideas in the source conversation target far larger populations. Resist adding them early.
- **Stage 1 scope creep**: only the interface, rules provider and logging belong in Stage 1.

Open questions:

1. Hosted first, or is offline/local play a hard requirement?
2. Does the user's GPU need to run Godot and a 9B model concurrently, or is a second machine available?
3. Should the decision log schema be shared with the existing resident decision history in sidecars, or kept separate?
4. How much of the existing human-agent escalation path (tiny-model scheduler) should Tier 1 replace versus wrap?
5. Which dialogue intents count as obligations requiring a Tier 1 decision before wording?

## 17. Immediate next steps

1. Review this document and settle the open questions in section 16.
2. Add the provider interface and `RulesDecisionProvider` to the Stage 1 plan as a small work item attached to the scripted-NPC milestone.
3. Write the option-list builder spec (sources, filters, caps) against the registry and planning catalog.
4. Define the trigger list against actual escalation signals.
5. After Gate H, run S2.0 to check the claims in section 12 against a real endpoint.
