# Orchestrator Future

Current limitations:
- only the first broader live wave is wired: manual combat/actions,
  talk-runtime results, and generic completed-task packets
- `reasoning_output` is currently exercised through a deterministic mock
  builder, not a real world-model response yet
- decrees, richer world events, and post-reasoning materialization are still
  mostly scaffold-only here
- phase handlers now delegate to existing runtimes, but packet correlation
  across multi-tick chains is still future work

Important nuances:
- the orchestrator should not become a second domain-logic layer
- the packet router should stay fact-driven, not situation-file driven
- a concrete case like manual attack is only a worked example of the generic
  pipeline, not a dedicated custom chain architecture

Suggested next elaborations:
- let control-intake `talk_command` and other semantic actions optionally queue
  pre-outcome packets when useful, while keeping outcome packetization the
  authoritative seam
- replace ad hoc handoffs between combat/talk/escalation/reasoning with
  orchestrator packet handoff where it adds clarity
- add richer `task_outcome` consequence semantics for more task kinds without
  turning the orchestrator into a task-logic layer
- replace the mock reasoning builder with a real world-model output while
  keeping the packet shape and `task_materialization` contract stable
- connect decree/world-event packets to the same runtime history and phase
  delegation
- add packet correlation ids for longer-lived chains that span immediate
  reaction, reasoning, and later task materialization
