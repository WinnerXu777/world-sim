# Orchestrator Design

Status: first live seam.

This module is the reusable cross-module coordinator for end-to-end event
chains. It is intentionally thin. It should normalize many kinds of triggers,
route them through reusable phases, and hand outputs off to existing systems.

Primary files:
- `schema.py` for packet and result helpers
- `intake.py` for trigger-to-packet normalization
- `phases.py` for reusable phase handlers
- `router.py` for phase-order selection
- `runtime.py` for queue/history and packet execution
- `ops.py` for lightweight helpers

Owned concepts:
- orchestration packet shape
- reusable phase ordering
- queue/history of orchestrated packets

Not owned here:
- combat rules
- talk rules
- escalation scoring rules
- planning logic
- task execution logic

Those remain in their existing system modules. The orchestrator should only
coordinate them.

Current live seam:
- manual `attack_target` combat outcomes are packetized through this module
- successful manual `interact_target` / `work_on_target` actions are also
  packetized here
- talk-runtime outputs are packetized here as generic `world_event` inputs
- completed resident tasks are packetized here as generic `task_outcome`
  inputs
- mock `reasoning_output` packets are now materialized here through the same
  `task_materialization` phase and delegated into the existing plot executor
- `phases.py` now delegates target-human escalation handoff to
  `HumanAgentRuntime.ingest_external_trigger(...)`
- immediate urgent reaction and deferred consequence registration now happen
  through existing escalation/runtime logic, not duplicated orchestrator logic
