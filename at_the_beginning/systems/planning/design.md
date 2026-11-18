# Planning Design

Status: partially live as the structured plan layer for reasoning output.

This module owns structured plan records, plan validation, compilation into approved operations, plan persistence, and prompt-facing plan catalogs and summaries.

Primary files:
- `schema.py` and `catalog.py` for plan ontology
- `validator.py` for schema validation
- `compiler.py` for compiling validated plans into runtime-safe ops
- `lifecycle.py` for plan persistence and review state
- `executor.py` for conservative execution-facing hooks
- `ops.py` and `prompt_view.py` for runtime-facing payloads

Main runtime wiring:
- `at_the_beginning/runtime/resident_store.py` ensures resident plan state
- `at_the_beginning/runtime/human_runtime.py` and `world_runtime.py` expose plan payloads in prompts
- `at_the_beginning/tools_execution/plot/executors.py` stores and applies plan outputs

Owned data:
- Resident `plans`
- `planning_state`
- Plan catalogs, prompt payloads, and compiled-step bundles

Planning currently provides the contract between world-model reasoning output and deterministic Python execution. The schema and validation are real; full in-sim execution is still conservative.
