# Queue And Planning Architecture

## Purpose

This document defines the next-step runtime design for resident intelligence.

The architecture should now be:

- `reflex layer`
- `urgent queue`
- `normal queue`
- `reasoning queue`
- `god decree queue`

The key design decision is:

- keep `urgent` and `normal` on the tiny resident model
- reuse the stronger `world model` for both:
  - `god decrees`
  - `resident reasoning`
- always give god decrees higher priority than resident reasoning


## Core Rule

Keep top-level routing simple:

- `urgent = react`
- `normal = live`
- `reasoning = strategize`

Do not overfit routing with too many fragile scoring rules.

Use:

- `pressures` to shape and prioritize behavior
- `goals` to express what the resident wants
- `plans` to express how the resident intends to pursue it

But do not let pressures alone become the full top-level router.


## Model Split

### Tiny Resident Model

Used for:

- `urgent queue`
- `talk reply / appraisal`
- `normal queue`

Why:

- high frequency
- low latency
- short outputs
- many routine cases

The tiny resident model should support three resident-facing modes:

- `urgent_react`
- `talk_reply`
- `normal_live`

### World Model

Used for:

- `god decree queue`
- `reasoning queue`

Why:

- decrees are sparse
- reasoning cases are sparse
- both benefit from stronger reasoning
- both can reuse ToolRAG
- this avoids hosting a third separate reasoning-only model


## Priority Policy

The world model should be scheduled like this:

1. process `god decree queue` first
2. if no decree is pending, process `reasoning queue`
3. otherwise idle

This means:

- decrees always stay top priority
- resident reasoning uses the strong model only during decree-idle time
- reasoning latency is acceptable because it is for long-horizon strategy


## Tiny-Model Priority Policy

Inside the tiny resident model service, keep the priority order:

1. `reflex` (hardcoded, not an LLM call)
2. `urgent_react`
3. `direct_talk`
4. `ambient_talk`
5. `normal_live`
6. `ambient_npc_talk`

Important:

- true danger still wins over dialogue
- direct talk should feel immediate
- ambient talk should feel responsive, but not block combat or panic reactions
- nearby NPC-to-NPC chatter should be the first talk lane dropped under load
- routine life decisions should be the first thing dropped under load


## Queue Meanings

### 1. Reflex Layer

Hardcoded and immediate.

Used for:

- flinch
- face attacker
- aggro
- flee start
- ally alert
- threat spike

This gives immediate visible response before any model finishes.

### 2. Urgent Queue

Tiny model, highest resident priority.

Used for:

- fast manual-interaction response
- immediate combat/social reaction
- lethal danger response
- short-horizon reaction after reflex

Examples:

- `counterattack`
- `flee`
- `call_help`
- `guard`
- `surrender`

Important:

- attacks, hazards, and direct danger go straight here after reflex
- talk does not start here by default
- talk may escalate into this queue after appraisal

### 3. Normal Queue

Tiny model, lower priority than urgent.

Used for:

- routine life decisions
- simple non-critical follow-through
- everyday survival/social choices

Examples:

- `seek_food`
- `seek_water`
- `rest`
- `regroup`
- `go_home`
- `avoid_target`

Important:

- ordinary speech does not belong here
- only post-talk ordinary follow-through belongs here

### 4. Reasoning Queue

World model, low frequency, high value.

Used for:

- goal updates
- plotting
- revenge planning
- ambush planning
- ally recruitment planning
- theft / wealth / status strategy
- periodic or event-triggered strategic review

This queue should be selective, not high volume.

### 5. God Decree Queue

World model, highest global priority.

Used for:

- interpreting user decrees
- selecting world actions
- choosing tools / instincts / new actions


## Systems Ownership

### `systems/personality`

Owns:

- archetypes
- trait vectors
- birth jitter
- stable bias

Does not own:

- queue routing
- plan execution

### `systems/goal`

Owns:

- structured goal schema
- goal lifecycle
- review state

Does not own:

- plan execution
- queue scheduling

### `systems/planning`

Owns:

- structured plan schema
- plan validation
- plan compilation
- plan execution state

Does not own:

- god decree logic
- low-level tensor mutation policy

### `systems/talk`

Owns:

- direct talk vs ambient talk session logic
- player-to-resident utterance capture and packaging
- speech appraisal output handling
- short verbal reply schema
- talk-driven escalation triggers
- witness-hearing policy

Does not own:

- hardcoded reflexes
- long-term goal mutation policy
- free-form plot execution

### `systems/inventory`

Owns:

- item schema
- owner/container inventory store
- currency, weapon, and container state
- equip / unequip rules
- transfer / drop / loot / deposit / withdraw ops

Does not own:

- high-frequency human tensor state
- queue scheduling
- world-camera / human-camera logic

### `tools_execution/`

New recommended execution folder.

Owns:

- hardcoded Python execution scripts for decree-mode outputs
- hardcoded Python execution scripts for plot/reasoning-mode outputs
- schema-to-runtime translation
- deterministic validation and dispatch

Does not own:

- LLM prompting
- resident memory state
- personality / goal generation

### `systems/escalation`

Owns:

- semantic routing
- reaction vs consequence vs reasoning tickets
- deferred queue eligibility
- resident-side scheduling signals

This should decide:

- ignore
- reflex only
- urgent
- normal
- reasoning
- combinations like `urgent + reasoning`

For talk events, `systems/escalation` should also be able to decide:

- `direct_talk`
- `ambient_talk`
- `direct_talk + urgent`
- `direct_talk + reasoning`
- `ambient_talk + reasoning`


## Inventory Design

`systems/inventory` should be fully separate from `h_tensor`.

That separation is important because:

- `h_tensor` is for high-frequency simulation state
- inventory is mostly event-driven
- inventory changes when a meaningful action happens:
  - pickup
  - spend
  - equip
  - loot
  - steal
  - store
  - consume

So the design rule should be:

- `inventory store` = source of truth
- `h_tensor` = no full inventory contents

If we ever need a fast hint later, we can mirror only tiny summaries back into
fast state, for example:

- `armed_flag`
- `equipped_weapon_class`
- `encumbrance_hint`
- `wealth_hint`

But those should be optional derived summaries, not the main inventory storage.


## Inventory Scope Tiers

Keep inventory depth different for different actor classes.

### Normal Residents

Keep resident inventory intentionally simple.

Recommended first scope:

- money
- one main-hand weapon
- maybe one small carried item or loot pouch

This keeps normal residents believable without overbuilding NPC micromanagement.

### Human-Mode Incarnation

Give the player incarnation a richer inventory because it is fully manual and
interaction-heavy.

Recommended first scope:

- money
- weapon slots
- carried items
- storage interactions
- looting
- equip / unequip

This is where the more elaborate inventory UX should live first.


## Inventory Module Shape

Recommended layout:

```text
systems/
  inventory/
    schema.py
    store.py
    ops.py
    equipment.py
    containers.py
    currency.py
    queries.py
    resolver.py
```

Suggested ownership:

- `schema.py`
  - item kinds
  - stack rules
  - item tags
  - slot rules
- `store.py`
  - owner/container -> item records
  - save/load hooks
  - stable ids
- `ops.py`
  - add/remove/transfer/drop/loot
- `equipment.py`
  - equip / unequip
  - active weapon
  - slot validation
- `containers.py`
  - storage case
  - chest
  - stockpile
  - corpse loot later
- `currency.py`
  - spend / grant / afford checks
- `queries.py`
  - what is carried
  - what is equipped
  - nearby accessible container
  - total wealth
- `resolver.py`
  - capacity rules
  - ownership / access rules
  - stack merge rules


## Inventory Interaction Boundary

Keep boundaries clean:

- `inventory` owns items and containers
- `interaction` owns `pickup`, `drop`, `open`, `loot`, `store`, `steal`
- `combat` reads equipped weapon state from inventory
- `construction` later consumes materials from inventory/containers
- `goal` and `personality` can generate intents like:
  - `accumulate_wealth`
  - `arm_self`
  - `steal_when_safe`
  - `stash_resources`

Map entities such as storage cases should exist in `map`, but their contents
should live in `systems/inventory`.


## First Inventory Slice

Recommended implementation order:

1. item catalog + inventory store
2. add / remove / transfer / drop ops
3. one currency item path
4. one main-hand weapon slot
5. one storage container entity
6. interaction hooks for pickup / store / loot

This gives a robust first version without forcing complex resident inventory too
early.


## Goal And Plan Separation

Keep these separate:

- `goal` = what the resident wants
- `plan` = how the resident intends to do it

Examples:

- goal: `retaliate`
- plan: recover, recruit ally, wait near lake, attack later

- goal: `accumulate_wealth`
- plan: gather valuables, steal when target isolated, avoid detection

This is much better than letting the model invent one large free-form desire blob.


## Talk Design

`systems/talk` should support free-form player speech in human mode, while still
keeping the runtime structured and safe for a tiny model.

Core rule:

- `reflex` is always first
- if the event is `talk`, do talk appraisal first
- if the event is `attack / hazard / direct danger`, go straight to `urgent_react`

This means:

- speech can create danger
- but speech does not outrank already-existing lethal danger
- the tiny model handles immediate social surface
- the world model only handles long-term conversational consequences later


## Talk Scope

Keep spoken dialogue local and embodied.

For now:

- spoken talk only exists in `human mode`
- spoken talk only exists within the incarnation's local hearing distance
- spoken talk does not run for the full population
- spoken talk does not run globally in `god mode`

Within that local hearing bubble, support:

- `player <-> resident` talk
- `resident <-> resident` audible talk near the player

This keeps the world feeling alive without trying to simulate every
conversation in the entire population.


## Talk Interaction Modes

### Direct Talk

Triggered by:

- hold `T`
- click a specific resident
- enter a line of dialogue

Behavior:

- clicked resident gets priority reply
- processed above ambient talk
- uses one tiny-model `talk_reply` call
- may escalate into `urgent_react`
- may schedule later reasoning

Use this for:

- threats
- apologies
- demands
- trade offers
- intimidation
- direct role-play conversation

### Ambient Talk

Triggered by:

- hold `T`
- speak without clicking a specific resident

Behavior:

- nearby residents can hear
- lower priority than direct talk
- should not fan out to every listener equally
- choose one or a few likely responders
- other listeners can receive deterministic heard-event updates

Use this for:

- shouting
- calling for help
- public threats
- public persuasion
- general role-play speech near a crowd

### Nearby Resident Chatter

Triggered by:

- two or more residents are within the incarnation's hearing bubble
- local context suggests simple speech is appropriate
- the tiny-model service has spare budget after higher-priority lanes

Behavior:

- only exists near the player in `human mode`
- not meant to simulate whole-world conversation
- usually realized as one-line barks
- occasionally allowed to become a tiny two-turn exchange
- should be the lowest-priority talk lane on the tiny model

Use this for:

- greetings
- warnings
- fear reactions
- comfort
- conflict barks
- gossip-like flavor
- trade or work chatter


## Talk Routing Rule

Do not treat speech as only text generation.

Treat it as an event that can produce:

- verbal reply
- immediate physical intent
- pressure deltas
- escalation flags
- reasoning follow-up

Recommended flow:

1. player speech event arrives
2. if a true danger reflex is already active, reflex remains first
3. `systems/talk` packages the case for tiny-model `talk_reply`
4. tiny model returns one structured reply + appraisal object
5. Python applies:
   - short verbal response
   - immediate movement/combat/social reaction
   - memory / relationship effects
   - optional urgent escalation
   - optional reasoning follow-up

This keeps talk grounded in the same action architecture as the rest of the sim.


## Resident-to-Resident Talk Rule

Do not try to run full LLM conversation for all residents.

Instead, use a layered local-only design:

1. hardcoded trigger logic decides whether nearby residents should speak
2. hardcoded semantic framing decides:
   - `speaker`
   - `listener`
   - `speech_act`
   - `topic`
   - `tone`
   - `urgency`
3. tiny-model `ambient_npc_talk` optionally turns that frame into a short line
4. if the tiny model is busy, fall back to a template line

This means:

- the simulation does not need full-population dialogue
- nearby NPC chatter still feels varied
- higher-priority combat and direct talk always win

Recommended runtime policy:

- allow only a small local conversation budget
- prefer one-line bark style output
- keep two-turn exchanges rare
- skip entirely when urgent / direct talk load is high


## Talk Escalation Rule

Speech can trigger real danger.

Examples:

- “hello” -> talk reply only
- “leave me alone” -> talk reply + maybe avoid / back away
- “give me your money” -> talk reply + normal or reasoning follow-up
- “I am going to kill you” -> talk reply + urgent reaction + reasoning follow-up

So the talk pipeline should support:

- `talk only`
- `talk + urgent`
- `talk + reasoning`
- `talk + urgent + reasoning`

The key rule is:

- appraise speech first
- then route based on appraisal output


## Tiny Talk Output Shape

The tiny model should not generate long monologues.

Keep it to:

- one short reply
- one short physical intent
- compact appraisal flags

Recommended fields:

- `speech_text`
- `speech_act`
- `tone`
- `physical_intent`
- `danger_upgrade`
- `reasoning_followup`
- `witness_policy`
- `relationship_delta`
- `pressure_deltas`
- `memory_salience`

Keep reply length short, for example:

- 1 sentence
- roughly 8-20 words

For nearby resident chatter, keep it even smaller:

- usually 3-12 words
- often one-line bark style


## Example Talk Outputs

### Direct Threat Example

Player says to one resident:

- “I am going to kill you.”

Structured output:

```json
{
  "mode": "direct_talk",
  "target_id": "h_000045",
  "speech_text": "Stay away from me!",
  "speech_act": "threat_response",
  "tone": "fearful_angry",
  "physical_intent": "flee",
  "danger_upgrade": true,
  "reasoning_followup": true,
  "witness_policy": "nearby_hear",
  "relationship_delta": "hostile",
  "pressure_deltas": {
    "fear": 0.72,
    "hostility": 0.44
  },
  "memory_salience": 0.89
}
```

Expected runtime behavior:

- resident verbally responds
- resident begins fleeing immediately
- urgent reaction ticket can be created if needed
- nearby witnesses may receive a heard-threat memory
- later reasoning may create `avoid_target`, `retaliate`, or `recruit_allies`

### Direct Apology Example

Player says to one resident:

- “I’m sorry. I won’t hurt you.”

Structured output:

```json
{
  "mode": "direct_talk",
  "target_id": "h_000045",
  "speech_text": "Then leave me alone.",
  "speech_act": "apology_response",
  "tone": "guarded",
  "physical_intent": "back_away",
  "danger_upgrade": false,
  "reasoning_followup": false,
  "witness_policy": "none",
  "relationship_delta": "guarded",
  "pressure_deltas": {
    "fear": -0.08,
    "trust": 0.05
  },
  "memory_salience": 0.41
}
```

### Ambient Shout Example

Player says near several residents:

- “Help me! Wolves are coming!”

Structured output:

```json
{
  "mode": "ambient_talk",
  "primary_listener_id": "h_000012",
  "speech_text": "Where are they?",
  "speech_act": "alarm_response",
  "tone": "alert",
  "physical_intent": "scan_and_prepare",
  "danger_upgrade": false,
  "reasoning_followup": true,
  "witness_policy": "crowd_hears",
  "relationship_delta": "neutral",
  "pressure_deltas": {
    "fear": 0.21,
    "loyalty": 0.09
  },
  "memory_salience": 0.63
}
```

### Nearby Resident Chatter Example

Resident near the player warns another resident:

- local semantic frame: `warn` about nearby danger

Structured output:

```json
{
  "mode": "ambient_npc_talk",
  "speaker_id": "h_000012",
  "listener_id": "h_000018",
  "speech_text": "Stay close. Something's wrong.",
  "speech_act": "warn",
  "topic": "danger",
  "tone": "tense",
  "physical_intent": "stay_alert",
  "danger_upgrade": false,
  "reasoning_followup": false,
  "witness_policy": "audible_local_only",
  "relationship_delta": "supportive",
  "pressure_deltas": {
    "fear": 0.12,
    "loyalty": 0.07
  },
  "memory_salience": 0.29
}
```


## TTS Design

Treat TTS as a presentation layer, not as part of the decision-critical path.

Core rule:

- text and reaction happen first
- TTS runs asynchronously afterward
- TTS must never block:
  - `reflex`
  - `talk appraisal`
  - `urgent_react`
  - movement / combat / memory effects

Recommended flow:

1. tiny model generates `speech_text`
2. text bubble / subtitle can appear immediately
3. physical and social effects are applied immediately
4. an async TTS queue decides whether to synthesize audio
5. if the audio arrives in time, play it
6. if it is late or over budget, keep the line text-only


## TTS Priority Classes

Use a small number of TTS priority bands:

- `direct_talk_voice`
  - highest priority
  - resident lines directed to the player
  - should almost always be synthesized

- `ambient_talk_voice`
  - medium priority
  - player-audible crowd or nearby contextual speech
  - synthesize if within current TTS budget

- `ambient_npc_voice`
  - lowest priority
  - nearby resident-to-resident chatter
  - only synthesize the top few lines after higher-priority work is satisfied

Important:

- resident lines are not always low priority
- resident lines directed at the player are high priority
- ordinary resident-to-resident chatter is the lowest priority by default


## TTS Distance Rule

Distance to the incarnation should shape both synthesis choice and playback mix.

Use distance in two ways:

1. synthesis gating
   - if a line is too far away, do not synthesize it
   - keep it as subtitle / text bubble only

2. playback presentation
   - closer lines are louder and clearer
   - farther lines are quieter
   - later we can add panning / muffling / low-pass effects

This gives the desired feel:

- direct talk is loudest and clearest
- ambient talk follows a closer = louder rule
- distant low-value chatter can remain text-only


## TTS Budget Rule

Do not try to voice every ambient line.

Use a voice budget:

- direct-talk lines are guaranteed or near-guaranteed
- ambient talk lines are synthesized only if they fit the current budget
- ambient NPC chatter is synthesized only for the top few audible lines

Recommended policy:

- keep a short rolling TTS queue
- cap simultaneous or near-simultaneous ambient voice lines
- drop stale lines quickly
- prefer subtitle fallback over delayed playback


## TTS Ranking Rule

Inside the async TTS queue, rank non-direct lines by:

- `tts_priority`
- `distance_to_player`
- `memory_salience`
- `speech_act`
- `age / staleness`

A simple rule is:

- direct talk first
- then closer, more salient ambient lines
- then low-value NPC chatter last

So the system should behave like:

- `direct_talk_voice` -> almost always voice
- `ambient_talk_voice` -> voice if close enough and within budget
- `ambient_npc_voice` -> voice only top few nearby lines


## TTS Salience Source

Do not spend an extra LLM call just to decide voice priority.

Instead, reuse the structured talk output that already exists.

Useful fields already returned by the tiny talk call:

- `mode`
- `speech_act`
- `tone`
- `danger_upgrade`
- `reasoning_followup`
- `memory_salience`

Hardcoded TTS policy can derive priority from those fields.

Example:

- `danger_upgrade == true` -> high voice importance
- `speech_act in ["warn", "alarm_response", "threat_response", "plea"]` -> bump up
- `mode == "direct_talk"` -> very high
- `mode == "ambient_npc_talk"` with no special flags -> low

This avoids a second model pass while still keeping TTS selection meaningful.


## Example TTS Payload

```json
{
  "speaker_id": "h_000012",
  "speech_text": "Stay close. Something's wrong.",
  "tts_priority": "ambient_npc_voice",
  "distance_to_player": 9.4,
  "memory_salience": 0.29,
  "voice_profile": "male_tense_01",
  "expires_tick": 4120
}
```

Expected playback policy:

- if within budget and still fresh, synthesize and play
- if not, keep the subtitle / text bubble only
- if another higher-priority line arrives, this one can be dropped


## Structured Goal Design

Goals remain bounded and reusable.

Example goal kinds:

- `retaliate`
- `avoid_target`
- `protect_kin`
- `recruit_allies`
- `accumulate_wealth`
- `steal_when_safe`
- `gain_status`
- `guard_home`
- `hoard_food`
- `explore_region`
- `seek_mate`

Recommended fields:

- `kind`
- `target_id`
- `target_place`
- `priority`
- `status`
- `origin`
- `plan_hint`
- `confidence`
- `created_tick`
- `last_review_tick`
- `expires_tick`


## Structured Plan Design

Plans should also be structured and validated.

The world model should not directly execute arbitrary resident actions.

Preferred pipeline:

1. retrieve relevant context from ToolRAG and MemoryRAG
2. produce a structured plan object
3. validate the plan against approved plan ops
4. compile the plan into runtime-approved steps
5. execute through hardcoded Python logic

Example plan shape:

```json
{
  "goal_id": "g_0012",
  "plan_kind": "ambush",
  "priority": 0.81,
  "steps": [
    {"op": "recover_until_hp", "threshold": 70},
    {"op": "recruit_allies", "count": 1},
    {"op": "move_to_place", "place_hint": "near_lake"},
    {"op": "attack_target_when_close", "target_id": "h_player"}
  ],
  "confidence": 0.74,
  "expires_tick": 12000
}
```


## ToolRAG And MemoryRAG Roles

### `ToolLightRAG`

Used by the world model in:

- decree mode
- resident reasoning mode

For resident reasoning, it should provide:

- available domain ops
- valid plan ops
- known module capabilities
- reusable action patterns

Important:

- ToolRAG should guide plan generation
- it should not turn resident reasoning into unrestricted direct tool execution

### `MemoryLightRAG`

Used by the world model in resident reasoning mode to understand:

- who attacked the resident
- who matters socially
- what important events happened
- where conflicts, dangers, and opportunities are located

This is what enables long-term smart behavior like revenge, ambush, grief,
alliance, and theft to feel personal.


## World Model Modes

Even though decree handling and reasoning handling share the same world model,
they must use different task modes.

### `decree mode`

Used for:

- world directives
- tool selection
- world-level interventions

Output:

- decree interpretation
- tool/action requests

Execution boundary:

- decree-mode outputs should be passed into dedicated hardcoded executors under
  `tools_execution/`
- the model should not directly perform arbitrary runtime mutation

### `resident reasoning mode`

Used for:

- goal updates
- plan generation
- long-term resident strategy

Output:

- structured goal updates
- structured plan objects

Important:

- resident reasoning mode should not act like god mode
- it should not emit arbitrary world-authority tool execution
- it should stay resident-scoped and schema-validated

Execution boundary:

- plot / reasoning outputs should also be passed into dedicated hardcoded
  executors under `tools_execution/`
- reasoning outputs should compile into approved plot/runtime actions, not raw
  free-form code


## Escalation Output

`systems/escalation` should output tickets, not a single boolean result.

Example:

```json
{
  "human_id": "h_000023",
  "requires_reflex": true,
  "reaction_ticket": {
    "queue": "urgent",
    "reason": "manual_attack",
    "priority": 0.96
  },
  "consequence_ticket": {
    "queue": "normal",
    "reason": "manual_attack_followup",
    "due_tick": 1040,
    "priority": 0.73
  },
  "reasoning_ticket": {
    "queue": "reasoning",
    "reason": "revenge_goal_review",
    "due_tick": 1180,
    "priority": 0.88
  }
}
```

Important:

- one event may produce more than one ticket
- `urgent`, `normal`, and `reasoning` are not mutually exclusive


## Manual Interaction Policy

Do not route all manual interactions to the same lane.

Instead:

- immediate visible response -> reflex
- fast local reaction -> urgent
- simple follow-up -> normal
- long-term meaning / plotting -> reasoning

Examples:

- player attacks resident
  - reflex + urgent + deferred normal + maybe reasoning

- player interacts socially with resident
  - maybe no urgent
  - normal follow-up
  - sometimes reasoning if socially important

- player steals from resident
  - maybe urgent if confrontation is immediate
  - normal for short consequence
  - reasoning for revenge / theft-back / scheme


## Reasoning Queue Triggers

Do not send every review to the world model.

Use reasoning for:

- periodic goal review
- event-triggered strategic review
- repeated conflict with same target
- revenge candidate formation
- major kin/family loss
- betrayal
- high-value greed/status opportunities
- ambush / recruit / scheme style long-term planning

Do not use reasoning for:

- ordinary hunger decisions
- routine shelter seeking
- low-salience regrouping
- simple near-term reactions


## Suggested Module Layout

```text
at_the_beginning/
  systems/
    escalation/
      signals.py
      scoring.py
      routing.py
      queue_state.py
      prompt_view.py
      ops.py
    planning/
      __init__.py
      catalog.py
      schema.py
      lifecycle.py
      validator.py
      compiler.py
      executor.py
      prompt_view.py
      ops.py
    talk/
      __init__.py
      schema.py
      sessions.py
      prompt_view.py
      bark_templates.py
      effects.py
      routing.py
      ops.py
  tools_execution/
    decree/
      __init__.py
      schema.py
      dispatcher.py
      executors.py
    plot/
      __init__.py
      schema.py
      dispatcher.py
      executors.py
```

The exact filenames can evolve, but the design rule should stay:

- decree execution and plot execution live in the same top-level
  `tools_execution/` folder
- both are hardcoded Python execution layers
- both translate structured model outputs into deterministic engine behavior


## Prompt Design

### Urgent Queue Prompt

Tiny and tightly bounded.

Input:

- immediate danger / attacker / target
- top memory snippets
- top goal
- allowed urgent actions

Output:

- one short-horizon intent

### Talk Reply Prompt

Tiny and tightly bounded.

Input:

- player utterance
- talk mode (`direct_talk` or `ambient_talk`)
- target resident summary
- top relevant memories
- top relationship hint
- personality summary
- allowed physical intents

Output:

- one short reply
- one physical intent
- escalation flags
- compact pressure / relationship deltas

### Ambient NPC Talk Prompt

Tiny and lowest-priority.

Input:

- hardcoded local semantic frame
- speaker personality summary
- listener relationship hint
- short local context
- allowed bark length / tone constraints

Output:

- one short bark line
- optional lightweight physical intent
- compact pressure / relationship deltas

### Normal Queue Prompt

Still small.

Input:

- resident summary
- pressures
- top goals
- small memory bundle
- allowed normal actions

Output:

- one ordinary next-step intent

### Resident Reasoning Prompt

World model, resident-scoped.

Input:

- personality summary
- goal summary
- plan summary
- structured memory bundle
- relationship bundle
- reasoning trigger reason
- ToolRAG capability bundle
- valid goal kinds
- valid plan kinds
- valid plan ops

Output:

- structured goal updates
- structured plan objects

### Decree Prompt

World model, world-authority scoped.

Input:

- decree text
- world state summary
- ToolRAG world-action bundle

Output:

- world-level action selection


## Execution Rule

The world model in resident reasoning mode must not directly mutate tensors or
execute arbitrary tools.

Preferred rule:

- world model returns structured resident reasoning output
- Python validates it
- planning/compiler converts it into approved plan objects
- `tools_execution/plot/` executes approved plot actions later

The same principle applies to decree mode:

- world model returns structured decree output
- Python validates it
- `tools_execution/decree/` executes approved decree actions

This keeps both execution paths parallel in design:

- `decree mode -> tools_execution/decree`
- `resident reasoning mode -> tools_execution/plot`

Both should stay deterministic and hardcoded, even if the output schemas evolve.


## Migration Path

### Phase 1

Keep current reflex + urgent + normal working.

### Phase 2

Keep urgent and normal on the tiny model.

### Phase 3

Wire a `reasoning queue` scheduler that feeds the world model only when the
decree queue is empty.

### Phase 4

Use the world model in resident reasoning mode to:

- update goals
- generate validated plans

### Phase 5

Create `tools_execution/` and split execution into:

- `tools_execution/decree/`
- `tools_execution/plot/`

### Phase 6

Compile and execute plan steps incrementally through `systems/planning` and
`tools_execution/plot/`.


## Anti-Patterns To Avoid

Do not:

- send all normal cases to the world model
- let resident reasoning emit arbitrary world/god tool calls
- merge decree prompts and resident reasoning prompts into one schema
- let plans execute without validation
- overcomplicate the top-level routing logic


## Recommendation

Yes, move to:

- hardcoded reflexes
- tiny-model urgent queue
- tiny-model normal queue
- shared world model for:
  - god decrees
  - resident reasoning
- decree-first scheduling priority
- structured goals
- structured validated plans

This gives you:

- simpler deployment
- fewer models to host
- better use of the strongest model
- strong long-term resident intelligence
- clean reuse of ToolRAG and MemoryRAG
