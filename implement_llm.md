# LLM Integration Architecture

## Purpose

This document defines how to integrate the actual LLM backends into the
runtime that now exists.

The goal is:

- keep the simulation responsive
- keep deployment simple
- keep model responsibilities clean
- make later SGLang batching straightforward


## Current Live Seams

The live backend now has both model seams present:

- `reasoning llm seam`
- `tiny llm seam`

Current implementation state:

- the `reasoning llm seam` is already live through the world-model runtime and
  currently uses mock `reasoning_output` packets when a real handler is not
  attached
- the `tiny llm seam` is now live through the tiny-model runtime and currently
  uses structured mock outputs for urgent, normal, and talk modes when a real
  handler is not attached

Important rule:

- the mock outputs are not separate ad hoc logic paths
- they are the same structured contracts the future real handlers must return


## Model Topology

Use two model tiers:

- `tiny resident model`
- `world model`

### Tiny Resident Model

Used for:

- `urgent queue`
- `normal queue`
- `talk reply`
- `ambient npc talk`

Why:

- many calls
- low latency matters
- outputs should stay small and structured
- most resident decisions are simple

Suggested size:

- sub-`3B`
- quantized
- SGLang batched

### World Model

Used for:

- `god decree queue`
- `reasoning queue`

Why:

- low-frequency
- higher reasoning load
- can benefit from ToolRAG
- can generate richer structured goal/plan outputs

Suggested size:

- larger than the tiny resident model
- quantized if needed
- single shared world-model runtime


## Runtime Ownership

### World Model Runtime

Current shared seam already exists in:

- [world_runtime.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/world_runtime.py)
- [map_test.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/map_test.py)

Current hook:

- `engine.set_world_model_handler(handler)`
- `engine.run_world_model_mode_batch(mode=..., cases=..., engine=...)`

The world model must support two modes:

- `decree`
- `resident_reasoning`

### Tiny Resident Runtime

The current tiny-model seam now lives in:

- [tiny_runtime.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/tiny_runtime.py)
- [human_runtime.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/human_runtime.py)
- [talk_runtime.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/talk_runtime.py)

Current hooks:

```python
engine.set_tiny_model_handler(handler)
engine.set_resident_model_handler(handler)
```

Current runtime entry:

```python
handler(mode="urgent_react", cases=[...], engine=engine)
handler(mode="normal_live", cases=[...], engine=engine)
handler(mode="talk_reply", cases=[...], engine=engine)
handler(mode="ambient_npc_talk", cases=[...], engine=engine)
```

The tiny resident model should support four modes:

- `urgent_react`
- `normal_live`
- `talk_reply`
- `ambient_npc_talk`


## Queue To Model Mapping

### Reflex Layer

No LLM.

Handled by hardcoded Python.

### Urgent Queue

Model:

- tiny resident model

Task:

- immediate short-horizon reaction

Examples:

- `counterattack`
- `flee`
- `call_help`
- `guard`

### Normal Queue

Model:

- tiny resident model

Task:

- routine living decisions

Examples:

- `seek_food`
- `seek_water`
- `rest`
- `go_home`
- `regroup`

### Talk Reply Queue

Model:

- tiny resident model

Task:

- short direct or ambient spoken replies
- immediate social stance
- immediate physical intent hints for talk follow-through

Examples:

- `threat_response`
- `alarm_response`
- `trade_response`
- `apology_response`

### Ambient NPC Talk Queue

Model:

- tiny resident model

Task:

- low-priority nearby bark realization for human mode

Examples:

- `warn`
- `greet`
- `comfort`
- `gossip`

### Reasoning Queue

Model:

- world model

Task:

- strategic review
- goal updates
- plotting
- long-term social behavior

Examples:

- revenge
- ambush
- ally recruitment
- theft planning
- status planning

### God Decree Queue

Model:

- world model

Task:

- interpret and structure god decrees


## Priority Policy

### World Model Scheduler

The world model should always process:

1. `god decree queue`
2. `reasoning queue`
3. idle

This is already reflected in the current runtime behavior.

### Tiny Resident Scheduler

The tiny resident model should process:

1. `urgent_react`
2. `talk_reply`
3. `normal_live`
4. `ambient_npc_talk`

Urgent should preempt everything else.

Direct talk should feel immediate, but still stay behind true danger.


## Input Assembly

## World Model: Decree Mode

Each decree case should include:

- raw decree text
- optional sub-queries
- ToolRAG bundle
- execution limits / validation context

Recommended case shape:

```python
{
    "world_model_mode": "decree",
    "query": "...",
    "sub_queries": [...],
    "tool_bundle": {...},
    "execution_limits": {...},
    "raw_payload": {...},
}
```

## World Model: Resident Reasoning Mode

Each reasoning case should include:

- resident id
- reason for review
- personality summary
- goal summary
- current plans
- plan catalog
- memory bundle
- ToolRAG bundle

Recommended case shape:

```python
{
    "world_model_mode": "resident_reasoning",
    "resident_id": "h_000123",
    "reason": "attack_event",
    "resident_context": {
        "personality": {...},
        "personality_summary": "...",
        "goals": [...],
        "goal_summary": "...",
        "plans": [...],
        "plan_summary": "...",
        "plan_catalog": {...},
        "memory_bundle": {...},
        "tool_bundle": {...},
    },
    "review_requested": True,
    "auto_plan": True,
}
```

## Tiny Model: Urgent Mode

Urgent cases should stay very small.

Each case should include:

- local state
- immediate threat
- short summary of attacker / target
- active primary goal
- escalation metadata

Do not dump full resident JSON.

Recommended case shape:

```python
{
    "resident_model_mode": "urgent_react",
    "human_id": "h_000123",
    "local_state": {
        "distress": 0.74,
        "threat": 82.0,
        "hp": 54.0,
        "stamina": 33.0,
    },
    "nearby": {
        "predator": {...},
        "hazard": {...},
        "ally": {...},
        "shelter": {...},
    },
    "primary_goal": {...},
    "personality_summary": "...",
    "escalation": {...},
}
```

## Tiny Model: Normal Mode

Normal cases can be slightly richer than urgent, but still compact.

Each case should include:

- resident summary
- nearby context
- personality summary
- primary goal
- active plan summary

Recommended case shape:

```python
{
    "resident_model_mode": "normal_live",
    "human_id": "h_000123",
    "local_state": {
        "hunger": 71.0,
        "thirst": 42.0,
        "mood": 58.0,
        "stamina": 61.0,
    },
    "nearby": {
        "food": {...},
        "water": {...},
        "shelter": {...},
        "ally": {...},
    },
    "personality_summary": "...",
    "goal_summary": "...",
    "plan_summary": "...",
    "escalation": {...},
}
```

## Tiny Model: Talk Reply Mode

Talk reply cases should stay compact and grounded.

Each case should include:

- utterance
- talk mode
- speaker and listener ids
- listener personality summary
- relationship summary
- local context
- allowed physical intents

Recommended case shape:

```python
{
    "resident_model_mode": "talk_reply",
    "talk_mode": "direct_talk",
    "speaker_id": "h_player",
    "listener_id": "h_000123",
    "prompt_case": {
        "utterance": "I am going to kill you",
        "personality_summary": "guarded (caution=0.84, aggression=0.31)",
        "relationship_summary": "neighbor",
        "local_context": {
            "tick": 812,
            "distance_to_player": 2.4,
        },
        "allowed_physical_intents": [
            "flee",
            "back_away",
            "scan_and_prepare",
            "counterattack",
            "call_help",
        ],
    },
}
```

## Tiny Model: Ambient NPC Talk Mode

Ambient NPC talk cases should be even smaller.

Recommended case shape:

```python
{
    "resident_model_mode": "ambient_npc_talk",
    "speaker_id": "h_000111",
    "listener_id": "h_000147",
    "prompt_case": {
        "speech_act": "warn",
        "topic": "danger",
        "tone": "tense",
        "urgency": "high",
    },
}
```


## Output Contracts

## World Model: Decree Mode Output

The world model should return the same structured decree packet shape the runtime
already executes through:

- [tools_execution/decree/](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/tools_execution/decree)

Recommended output:

```python
{
    "packet": {
        "thought": "...",
        "map_actions": [...],
        "human_actions": [...],
        "new_entities": [...],
        "new_instincts": [...],
    }
}
```

## World Model: Resident Reasoning Mode Output

The world model should return structured resident reasoning output that is
executed through:

- [tools_execution/plot/](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/tools_execution/plot)

Recommended output:

```python
{
    "packet": {
        "resident_id": "h_000123",
        "reasoning_mode": "resident_reasoning",
        "reason": "attack_event",
        "goal_review": {
            "requested": True,
            "reason": "attack_event",
            "force": True,
        },
        "goal_updates": [...],
        "plans": [...],
        "auto_plan": False,
    }
}
```

Important rule:

- world model should not directly execute tools
- world model should not directly mutate tensors
- world model only returns structured resident reasoning packets

## Tiny Model: Urgent Output

Urgent output should be minimal.

Recommended shape:

```python
{
    "packet": {
        "resident_model_mode": "urgent_react",
        "human_id": "h_000123",
        "lane": "urgent",
        "intent": "flee_predator",
        "reason": "predator pressure overrides all other needs",
        "action": {
            "type": "move_away",
            "target_eid": 47,
            "magnitude": 4.3,
        },
        "confidence": 0.91,
        "followup": {
            "goal_review_requested": False,
            "reaction_ticket_requested": True,
            "consequence_ticket_requested": True,
        },
    }
}
```

## Tiny Model: Normal Output

Normal output should also stay compact.

Recommended shape:

```python
{
    "packet": {
        "resident_model_mode": "normal_live",
        "human_id": "h_000123",
        "lane": "normal_candidate",
        "intent": "seek_food",
        "reason": "hunger is outranking other needs this tick",
        "action": {
            "type": "move_toward",
            "target_eid": 81,
            "magnitude": 3.15,
        },
        "confidence": 0.74,
        "followup": {
            "goal_review_requested": False,
            "reaction_ticket_requested": False,
            "consequence_ticket_requested": False,
        },
    }
}
```

## Tiny Model: Talk Reply Output

Talk output must carry both speech and immediate embodied follow-through.

Recommended shape:

```python
{
    "packet": {
        "resident_model_mode": "talk_reply",
        "mode": "direct_talk",
        "speaker_id": "h_000123",
        "listener_id": "h_player",
        "target_id": "h_000123",
        "speech_text": "Stay away from me!",
        "speech_act": "threat_response",
        "tone": "fearful_angry",
        "physical_intent": "flee",
        "danger_upgrade": True,
        "reasoning_followup": True,
        "witness_policy": "nearby_hear",
        "relationship_delta": "hostile",
        "pressure_deltas": {
            "fear": 0.72,
            "hostility": 0.44,
        },
        "memory_salience": 0.89,
    }
}
```

## Tiny Model: Ambient NPC Talk Output

Ambient NPC bark output should still be structured.

Recommended shape:

```python
{
    "packet": {
        "resident_model_mode": "ambient_npc_talk",
        "mode": "ambient_npc_talk",
        "speaker_id": "h_000111",
        "listener_id": "h_000147",
        "speech_text": "Wolves, run!",
        "speech_act": "warn",
        "topic": "danger",
        "tone": "tense",
        "physical_intent": "",
        "danger_upgrade": False,
        "reasoning_followup": False,
        "witness_policy": "audible_local_only",
        "relationship_delta": "neutral",
        "pressure_deltas": {},
        "memory_salience": 0.15,
    }
}
```


## Mock Policy

Current mock flags:

- `engine.mock_tiny_model_enabled`
- `engine.mock_reasoning_enabled`

Current behavior:

- when `mock_tiny_model_enabled` is `True`, the tiny runtime still runs, but it
  returns structured packets synthesized from the existing deterministic urgent,
  normal, and talk heuristics
- when `mock_reasoning_enabled` is `True`, the orchestrator still runs, but it
  synthesizes a structured `reasoning_output` packet and hands it into the same
  plot-materialization path

This means:

- both LLM seams are live now
- both currently have mock outputs
- both can later swap to real handlers without changing the downstream
  execution contracts


## Prompting Rules

### Tiny Resident Model

Keep prompts:

- short
- schema-driven
- fixed action vocabulary
- no free-form long reasoning

Urgent and normal should use different system instructions, even if they share
the same small model.

### World Model

Use different prompt modes:

- `decree mode`
- `resident reasoning mode`

Even though they share one model, do not share one prompt template.

Resident reasoning mode should be explicitly forbidden from acting like god
mode.


## SGLang Batching Design

### Tiny Resident Model

Batch:

- `urgent_react` cases together
- `talk_reply` cases together
- `normal_live` cases together
- `ambient_npc_talk` cases together

Do not mix these modes in one prompt template unless backend simplicity later
forces it.

### World Model

Batch:

- decree cases together
- reasoning cases together

Do not mix decree-mode and resident-reasoning-mode cases in the same inference
batch.


## Retrieval Policy

### ToolRAG

Used by:

- decree mode
- resident reasoning mode

But:

- only when available
- should degrade gracefully if not loaded

### MemoryLightRAG

Used by:

- resident reasoning mode
- optionally `normal_live` and `talk_reply` later

Not needed for:

- decree mode
- `urgent_react`
- `ambient_npc_talk`


## Execution Boundary

### Decree Execution

Output goes through:

- [tools_execution/decree/](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/tools_execution/decree)

### Plot Execution

Output goes through:

- [tools_execution/plot/](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/tools_execution/plot)

### Resident Intent Execution

Urgent and normal tiny-model outputs should continue to be applied by the
resident runtime, not by the decree or plot executors.

Talk tiny-model outputs should continue to be applied by the talk runtime, not
by the decree or plot executors.


## Proposed File Changes

### World Model Integration

Primary files:

- [world_runtime.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/world_runtime.py)
- [map_test.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/map_test.py)

Later additions:

- `systems/llm/world_prompt.py`
- `systems/llm/world_client.py`
- `systems/llm/world_schema.py`

### Tiny Model Integration

Primary files:

- [tiny_runtime.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/tiny_runtime.py)
- [human_runtime.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/human_runtime.py)
- [talk_runtime.py](c:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/talk_runtime.py)

Later additions:

- `systems/llm/resident_prompt.py`
- `systems/llm/resident_client.py`
- `systems/llm/resident_schema.py`


## Suggested Handler Interfaces

### World Model Handler

```python
def world_model_handler(*, mode: str, cases: list[dict], engine) -> list[dict]:
    ...
```

Supported modes:

- `decree`
- `resident_reasoning`

### Tiny Resident Handler

```python
def resident_model_handler(*, mode: str, cases: list[dict], engine) -> list[dict]:
    ...
```

Supported modes:

- `urgent_react`
- `normal_live`
- `talk_reply`
- `ambient_npc_talk`


## Rollout Phases

### Phase 1

Integrate the actual world model backend.

Tasks:

- attach a real handler through `set_world_model_handler(...)`
- keep current fallback path intact
- validate decree mode first
- validate reasoning mode second

### Phase 2

Add the tiny resident model handler.

Tasks:

- create `set_tiny_model_handler(...)`
- keep `set_resident_model_handler(...)` as an alias
- route urgent, normal, and talk through the tiny model runtime
- keep current heuristic resident decisions and talk generation as structured
  mock fallback

### Phase 3

Tighten schemas and prompts.

Tasks:

- stabilize decree prompt
- stabilize resident reasoning prompt
- stabilize urgent prompt
- stabilize normal prompt

### Phase 4

SGLang productionization.

Tasks:

- enable prompt sharing
- batch by queue type
- add metrics
- add retry / timeout rules


## Testing Plan

### World Model Tests

- decree handler returns a valid decree packet
- reasoning handler returns a valid resident reasoning packet
- decree queue preempts reasoning queue
- fallback still works when no handler is configured

### Tiny Model Tests

- urgent handler returns a valid structured urgent packet
- normal handler returns a valid structured routine packet
- talk handler returns a valid structured talk packet
- ambient npc handler returns a valid bark packet
- urgent preempts talk and normal
- fallback still works when no tiny model handler is configured

### Integration Tests

- player attack triggers:
  - reflex immediately
  - urgent tiny-model response
  - deferred reasoning review later

- direct talk triggers:
  - tiny talk reply
  - talk runtime applies physical intent
  - orchestrator can emit consequence and reasoning follow-up if needed

- world decree during queued reasoning:
  - decree executes first
  - reasoning waits


## Non-Goals For First Pass

Do not try to implement all of these immediately:

- dynamic code generation inside the resident reasoning lane
- direct free-form tool execution from resident reasoning
- mixed decree and reasoning prompts in one batch
- full automatic prompt optimization

First pass should focus on:

- real handler wiring
- stable schemas
- safe fallback
- clean batching
- structured mock output parity for tiny and reasoning seams


## Final Rule

Keep the LLM integration layered like the rest of the repo:

- runtime builds compact semantic cases
- model returns structured outputs
- hardcoded Python validates and executes

Do not let either model bypass the structured execution pipeline.
