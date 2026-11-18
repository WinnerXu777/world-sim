# Orchestrator Implementation

Status: first live seam.

This document defines the new `at_the_beginning/orchestrator/` layer.

The orchestrator is not a second logic engine.

It should be:

- a thin reusable coordinator
- a normalized packet pipeline
- a stage router
- a handoff layer between already-existing system modules

It should not become the place where combat, talk, planning, escalation,
inventory, crafting, or task logic gets rewritten.

## Main Design Choice

The orchestrator should work like a reusable event pipeline:

- many possible inputs
- one normalized orchestration packet
- a slim ordered set of phases
- outputs handed off to the correct existing modules

So the architecture is:

- `systems/*`
  - own domain logic
- `runtime/*`
  - own live simulation/runtime state
- `orchestrator/*`
  - coordinate end-to-end chains between them

## Goal

The goal is not:

- one dedicated chain file per situation

The goal is:

- one generic orchestration pipeline
- where a concrete case like `manual attack on resident` is only a worked
  example of the reusable flow

So later these should all fit the same orchestrator shape:

- manual attack
- manual talk
- manual interact
- spontaneous danger
- witnessed death
- theft
- social insult
- public panic
- plan outcome

## Input / Output Style

The orchestrator should stay packet-based.

### Inputs

Inputs can come from many sources:

- manual control actions
- task outcomes
- combat outcomes
- talk outcomes
- world events
- spontaneous perception/escalation triggers
- reasoning outputs

### Middle pipeline

The middle should stay slim and reusable:

- normalize trigger
- apply immediate effects if needed
- hand off reflex if needed
- emit urgent ticket if needed
- emit consequence/reasoning ticket if needed
- materialize tasks if needed
- finalize result

### Outputs

Outputs can be varied:

- direct world effect already applied
- reflex requested
- urgent reaction ticket
- consequence ticket
- reasoning ticket
- strategic plan packet
- task emissions
- memory/event records

## Main Principle

The orchestrator answers:

- what stages should this trigger pass through?
- in what order?
- which modules should be called?
- what outputs should be forwarded?

It should not answer:

- how combat works
- how talk works
- how escalation scoring works
- how planning works
- how task execution works

Those remain in their current modules.

## First Worked Example

The first concrete example should be:

- manual incarnation attack on a resident

This is only a worked example, not a dedicated one-off chain architecture.

It is useful because it exercises:

- control
- combat
- reflex
- escalation
- reasoning
- planning
- tasks

The intended reusable flow is:

1. intake receives a manual action packet
2. packet is normalized
3. immediate effect phase confirms the attack outcome
4. reflex handoff can be requested
5. urgent reaction ticket can be requested
6. consequence/reasoning ticket can be requested
7. later planning output can materialize strategic tasks
8. finalize stores packet history

Current live state:

- manual `attack_target` combat outcomes now create a normalized orchestration
  packet
- successful manual `interact_target` and `work_on_target` actions now also
  emit normalized manual-action packets
- talk-runtime outputs now emit normalized world-event packets and can hand off
  same-tick urgent/consequence follow-through through the same escalation seam
- generic completed resident tasks now emit normalized `task_outcome` packets
- `reasoning_output` is now live through the same packet pipeline with a mock
  world-model output shape, so the orchestrator can exercise full
  `reasoning_output -> task_materialization -> plot_execution` flow before a
  real LLM is attached
- the orchestrator reuses `HumanAgentRuntime` escalation routing instead of
  duplicating combat or escalation logic
- the target resident can process an urgent same-tick reaction through the
  existing human runtime
- deferred consequence / reasoning follow-up is delegated to the existing
  human-escalation-to-world-reasoning path
- the orchestrator still stays thin: it coordinates, it does not own combat,
  reasoning, or task logic

## Module Shape

Recommended scaffold:

- `orchestrator/schema.py`
  - packet and result builders
- `orchestrator/intake.py`
  - convert raw triggers into orchestration packets
- `orchestrator/phases.py`
  - reusable phase names and default handlers
- `orchestrator/router.py`
  - choose phase order from normalized packet facts
- `orchestrator/runtime.py`
  - live orchestration runtime / queue / history
- `orchestrator/ops.py`
  - public helper API

## Packet Design

Packets should be neutral and reusable.

Example shape:

```json
{
  "packet_id": "orch_000014",
  "tick": 4201,
  "trigger_kind": "manual_action",
  "actor_kind": "human",
  "actor_id": "h_000031",
  "target_kind": "human",
  "target_id": "h_000044",
  "semantic_action": "attack_target",
  "action_family": "embodied_interaction",
  "world_refs": {},
  "facts": {
    "immediate_effect_applied": true,
    "requires_reflex": true,
    "emit_urgent_ticket": true,
    "emit_reasoning_ticket": true,
    "emit_task_materialization": false
  },
  "payload": {},
  "metadata": {}
}
```

The key idea is:

- the orchestrator works on normalized facts
- not on raw UI state
- not on bespoke scenario classes

## Reusable Phases

The orchestrator should define reusable phases such as:

- `normalize`
- `immediate_effects`
- `reflex_handoff`
- `urgent_signal`
- `consequence_signal`
- `reasoning_ticket`
- `task_materialization`
- `finalize`

Not every packet runs every phase.

The router should choose phases from packet facts instead of situation names.

## Relationship To Existing Systems

The intended module ownership should stay:

- `systems/combat`
  - combat rules and resolution
- `systems/talk`
  - talk and speech outcomes
- `systems/escalation`
  - scoring / ticket decisions
- `systems/planning`
  - plan logic
- `systems/tasks`
  - execution
- `runtime/control_runtime.py`
  - manual control sessions and events

The orchestrator should simply call those modules in the correct order.

## First Scaffold Scope

The first scaffold should do these things:

- create the packet schema
- create trigger intake helpers
- create reusable phase names and no-op/default phase handlers
- create a routing layer based on packet facts
- create a live runtime object with queue/history
- support the first worked example packet shape for manual attack

The first scaffold does not need to fully replace existing runtime flow yet.

## Recommended Next Implementation Order

1. scaffold `at_the_beginning/orchestrator/`
2. build normalized packet helpers
3. build reusable phase routing
4. connect one worked example input:
   - manual `attack_target`
5. verify the packet can carry:
   - immediate effect truth
   - urgent/reasoning handoff decisions
   - later task materialization intent
6. later fold more runtime seams into the orchestrator

## Boundary

This orchestrator should stay slim.

If a file starts accumulating domain rules like:

- damage formulas
- relationship logic
- memory retrieval
- task execution

that is a design smell.

The orchestrator should remain the coordinator, like a CEO or dispatcher:

- receive
- normalize
- route
- hand off
- finalize

The system modules remain the domain leads.
