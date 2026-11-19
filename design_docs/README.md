> Renamed 2026-11-18 from DOCS.md (date prefix dropped); old names are mapped in design_docs/README.md.

Current to commit: 0c14bd2 (doc pass 2026-11-18 by 1118wsimimplementation: 22301b7, 222ba3c, 506f6c6, b1a02dd, 63e675e, 0c14bd2; earlier pass to 7c9df1e)

# Documentation index

Written 2026-10-07 after the integrated 4-map build (8 residents). **Status words:** *current* = describes what the code does today; *plan* = a design or goal that guides work (parts may be done); *historical* = a record of how or why, no longer a description of the game; *stale parts* = mostly useful but contains lines that are no longer true (listed at the end).
Where two documents disagree, the order of authority is: the code and its tests, then the *current* contracts below, then `designs/implementation_1006_2d_rebaseline.md`, then everything older (`archive/communication_scratchpad.md` rule 7).

## Start here

| Document | Status | What it is |
| --- | --- | --- |
| `../README.md` | current (top) / historical (below "Legacy simulator notes") | What Eden 2D is, quick start (`../play.ps1`), controls, first five minutes, architecture, tests. The legacy simulator README sits below it, unchanged. |
| `../BACKEND.md` | current | Running the backend (env variables, four maps, roster, food/water loop), Save/Continue and the map guard, all routes, smoke and soak tools, known limits. |
| `../godot_client_2d/README.md` | current, stale parts | The Godot 2D client: import, live tests, controls, the C1 to C6 additions. See "Stale lines" for what to ignore. |
| `../play.ps1` | current | The one-command launcher (documented in `../README.md`). |

## Contracts the client builds against (all current)

| Document | Status | What it is |
| --- | --- | --- |
| `contracts/map_wire_contract.md` | current | `maps[]` in `/bootstrap`, `GET /map_file/{id}` (bytes, sha256, ETag), portals and `teleport_seq`, save manifest, **Continue with a changed map is refused** (section 6, implemented). |
| `contracts/commission_api.md` | current | Commission routes, applied versus rejected results, order states, and the rule that the smith waits at the forge for a ready, uncollected sword (2 minutes). |
| `contracts/god_mode_api.md` | current | God powers: envelope, possession state machine, heal, spawn, weather, time, witnesses and the event ledger. |
| `../at_the_beginning/world_map/README.md` | current | The authored map file format (`0.2-draft`), validator and `tools/validate_map.py`. |

## Evidence (what was measured or run)

| Document | Status | What it is |
| --- | --- | --- |
| `reports/performance_report.md` | current from "Update after H6, H7, H8" on; the first sections are historical | 36000-tick and 90-game-minute soaks, the 5-minute HTTP soak, spike analysis, the roster-file incident. The numbers in the first half are for the earlier 5-resident, 2-map world. |
| `reports/live_smoke_report.md` | historical report plus current addenda | The first live smoke of the authored map (2026-10-06) and addenda for portals, the smith, god mode, and the four-map world with the ready-order hold. |
| `reports/gate_h_acceptance.md` | plan, stale parts | The coordinator's plan for the Gate H acceptance run. Verification plan, not a completion report. |
| `reports/backend_review.md` | current | The reviewer pass over the backend code written for the 2D build: what was fixed (including the pause-survives-reset bug) and the findings left open. |
| `../godot_client_2d/C6_REPORT.md` | current | Recovery and presentation (reconnect, interrupted Continue, fault-injection tests). |
| `../ASSET_LICENSE_AUDIT.md` | current as of 2026-10-07 | Provenance audit of the 33 assets the 2D client imports; re-run after any asset change. Not legal advice. |

## Plans and designs for the 2D game

| Document | Status | What it is |
| --- | --- | --- |
| `designs/implementation_1006_2d_rebaseline.md` | plan (governing) | The October 6 decision to move to a 2D client and authored maps; overrides `archive/implementation_0905.md` where they conflict. Order of work P0 to P7 and Gate H. |
| `designs/2d_first_version_goal.md` | plan (draft) | The proposed goal text for the first playable version ("Draft only"); the work it describes has been done in large part. |
| `designs/implementation.md` | plan (draft) | Stage 2 plan: model plane and mock model server, T1a matrix policy, capability manifest and affordances, infinite map, world depth scenarios, asset needs, phasing and open questions. Nothing built yet. |
| `./DECISIONS.md` | current (living) | Orchestrator log for the Stage 2 work: ownership between the two worker sessions, rules of engagement, open decisions for the user, gap/verify inbox. |
| `designs/newdesign.md` | plan | The Tier 1 decision model between rules and LLMs. Only the `DecisionProvider` seam with the rules provider, the decision log and the status field are built (`systems/decision`); no model is used in this build. |
| `archive/smith_loop_design.md` | historical (design, implemented) | Design of scheduled NPCs and the smith commission loop. The implementation differs in details (for example the ready-order hold, the food/water loop); `contracts/commission_api.md` is the truth. |
| `archive/map_backend_integration.md` | historical (design, implemented) | How an authored map enters the backend (format `0.1-draft`, "design only"). Replaced by `contracts/map_wire_contract.md` and `../BACKEND.md`. |
| `archive/pathing_notes.md` | historical | Notes on the A* module. It says "not wired into schedules"; it is now used by the anchor mover (`systems/movement/anchor_mover.py`, `systems/roster/driver.py`). |

## Audits and reports from the start of the 2D work (historical)

| Document | Status | What it is |
| --- | --- | --- |
| `reports/godot2d_port_audit.md` | historical | Read-only audit of the existing Godot client and snapshot readiness (2026-10-06). |
| `reports/scale_constants_audit.md` | historical (values still agreed) | 48 px tiles, 8 units per tile, walk 20 u/s, actor radius 2.4. |
| `reports/snapshot_report.md` | historical | The local recovery snapshot taken before changing direction (S0). Not a description of the code. |

## Coordination records

| Document | Status | What it is |
| --- | --- | --- |
| `archive/communication_scratchpad.md` | current channel, stale parts | The shared channel between the Claude and Codex sessions (entries C-nnn, X-nnn). Its "Settled decisions" block still says Codex is generating assets. |
| `archive/megathread.md` | historical | The coordinator's archive (about 200 KB): full reports and the archived channel. Search it, do not read it linearly; many statements in it (five residents, two maps, revision 1, 497 to 529 tests) were true when written. |

## Before the 2D re-baseline (historical; the 3D village and the legacy simulator)

| Document | Status | What it is |
| --- | --- | --- |
| `archive/implementation_0905.md` | historical plan | The September 5 plan for a 3D Godot village and the model tiers (I0 to I5). Partly overridden by the re-baseline; the model-tier ideas are still the long-term plan. |
| `archive/CODEX_IMPLEMENTATION_GOAL.md`, `archive/ENGINEERING_REVIEW.md`, `archive/IMPLEMENTATION_PROGRESS.md` | historical | The sibling documents of the 0905 plan: the 3D village goal, the 2026-09-05 engineering review (its delivery order is still cited), and the 2026-09-06 progress log. |
| `archive/implement.md`, `archive/implement_control.md`, `archive/implement_crafting.md`, `archive/implement_inventory_materials.md`, `archive/implement_llm.md`, `archive/implement_occupation.md`, `archive/implement_orchestrator.md`, `archive/implement_refine_construction.md`, `archive/implement_refined_task.md`, `archive/implement_rendering.md`, `archive/implement_richer_task.md`, `archive/implement_tasks.md`, `archive/implementation_all_actions.md`, `archive/implement_schedule.md` | historical | April 2026 implementation notes of the legacy simulator (tasks, crafting, occupations, schedules, control, rendering, orchestrator, LLM). The systems exist in `at_the_beginning/systems/`; read the code first. |
| `contracts/backend_to_render.md`, `contracts/client_backend_boundary.md` | historical | April 2026 notes on the legacy 3D render/backend boundary. |
| `archive/humanizer_issue.md`, `archive/humanizer_migration.md`, `archive/migration.md`, `archive/polish.md` | historical | Legacy migration and polish notes. |
| `../at_the_beginning/orchestrator/design.md`, `../at_the_beginning/orchestrator/future.md`, `../skills/*.md` | historical | Legacy orchestrator and tool-generation notes. |

## Not reviewed for this index

`../myassets/*.md` (art bible, asset reports, the map contract reply), `../tools/*.md`, `../2D1006newstart/*.md`, `../game_frontend/implement.md` and `../godot_client/assets/README.md` belong to the art, tooling and legacy-client work; they are not described here.

Art status (2026-11-18): art rounds h009-h022 are assembled into git-ignored `../myassets/h0nn_*/` folders as reviewed candidates, each with its own `PILOT_REPORT.md`, manifest and `--validate` check. Nothing is committed or imported into the game yet (R5.5).

## Stale lines to know about

These are the known statements that no longer match the game (the map wire contract title, the god-mode smoke count and the map-format README were corrected together with this index; the others belong to other authors and are left as written).
- **`reports/performance_report.md`**: sections "Commands", "(a)", "What the first run found", "(b)" and "Left as is" describe the earlier world (5 residents, 2 maps, `needs_scale` 0.02, env with only `smith_interior` origin). The `EDEN_MAP_FILES`/`EDEN_MAP_ORIGINS` there are incomplete for the current roster; use `../BACKEND.md`.
- **`reports/live_smoke_report.md`**: the original run lists the old environment (one or two maps) and "five roster residents"; the current setup is in the docstring of `tools/smoke_common.py` and in the last addendum.
- **`reports/gate_h_acceptance.md`**: "529 tests" (now 539), "P6 roster currently has five residents" (it has eight), "both revision-2 authored maps" (four maps now; `starter_village` is revision 3).
- **`archive/communication_scratchpad.md`**: "The user has said Codex is currently generating assets" (settled decisions block).
- **`archive/pathing_notes.md`**: "Not wired into schedules, the engine, or any existing file".
- **`archive/map_backend_integration.md`**: written for format `0.1-draft` and a single map; the code accepts `0.2-draft` and several placed maps.
- **`../godot_client_2d/README.md`**: "F1 toggles the collision overlay" in the P2 paragraph (the keys are now H or F1 for the controls card, F2 collision overlay, F3 debug line); the first paragraph says the project "does not connect to the backend" (C1 only; P2 onward does); "routes are specification only until the backend owner posts evidence" (they are implemented); the P2 paragraph says the live tests register only `starter_village.json` (the C2 note says all four maps).
- **Any document** that says NPCs cannot use portals, or shows the old run command with only the smith interior, predates the four-map world; the run command is in `../BACKEND.md`.

## Old name -> new path

| Old name | New path |
| --- | --- |
| `1001decisios.md` | [design_docs/archive/decisions_legacy.md](archive/decisions_legacy.md) |
| `1006megathread.md` | [design_docs/archive/megathread.md](archive/megathread.md) |
| `1006newdesign.md` | [design_docs/designs/newdesign.md](designs/newdesign.md) |
| `1006_2d_first_version_goal.md` | [design_docs/designs/2d_first_version_goal.md](designs/2d_first_version_goal.md) |
| `1006_backend_review.md` | [design_docs/reports/backend_review.md](reports/backend_review.md) |
| `1006_commission_api.md` | [design_docs/contracts/commission_api.md](contracts/commission_api.md) |
| `1006_communication_scratchpad.md` | [design_docs/archive/communication_scratchpad.md](archive/communication_scratchpad.md) |
| `1006_gate_h_acceptance.md` | [design_docs/reports/gate_h_acceptance.md](reports/gate_h_acceptance.md) |
| `1006_gate_h_completion_audit.md` | [design_docs/reports/gate_h_completion_audit.md](reports/gate_h_completion_audit.md) |
| `1006_godot2d_port_audit.md` | [design_docs/reports/godot2d_port_audit.md](reports/godot2d_port_audit.md) |
| `1006_god_mode_api.md` | [design_docs/contracts/god_mode_api.md](contracts/god_mode_api.md) |
| `1006_live_smoke_report.md` | [design_docs/reports/live_smoke_report.md](reports/live_smoke_report.md) |
| `1006_map_backend_integration.md` | [design_docs/archive/map_backend_integration.md](archive/map_backend_integration.md) |
| `1006_map_wire_contract.md` | [design_docs/contracts/map_wire_contract.md](contracts/map_wire_contract.md) |
| `1006_pathing_notes.md` | [design_docs/archive/pathing_notes.md](archive/pathing_notes.md) |
| `1006_performance_report.md` | [design_docs/reports/performance_report.md](reports/performance_report.md) |
| `1006_scale_constants_audit.md` | [design_docs/reports/scale_constants_audit.md](reports/scale_constants_audit.md) |
| `1006_smith_loop_design.md` | [design_docs/archive/smith_loop_design.md](archive/smith_loop_design.md) |
| `1006_snapshot_report.md` | [design_docs/reports/snapshot_report.md](reports/snapshot_report.md) |
| `1006_STAGE1_LOCAL_DELIVERY.md` | [design_docs/reports/STAGE1_LOCAL_DELIVERY.md](reports/STAGE1_LOCAL_DELIVERY.md) |
| `1008decisions.md` | [design_docs/DECISIONS.md](DECISIONS.md) |
| `1008expandtools_instincts.md` | [design_docs/designs/expandtools_instincts.md](designs/expandtools_instincts.md) |
| `1008expansion.md` | [design_docs/designs/expansion.md](designs/expansion.md) |
| `1008implementation.md` | [design_docs/designs/implementation.md](designs/implementation.md) |
| `1008_actions.md` | [design_docs/designs/actions.md](designs/actions.md) |
| `1008_agent_driver_design.md` | [design_docs/designs/agent_driver_design.md](designs/agent_driver_design.md) |
| `1008_calendar_gap.md` | [design_docs/designs/calendar_gap.md](designs/calendar_gap.md) |
| `1008_clamp_audit.md` | [design_docs/reports/clamp_audit.md](reports/clamp_audit.md) |
| `1008_client_contract.md` | [design_docs/contracts/client_contract.md](contracts/client_contract.md) |
| `1008_coverage_map.md` | [design_docs/reports/coverage_map.md](reports/coverage_map.md) |
| `1008_creatures_gap.md` | [design_docs/designs/creatures_gap.md](designs/creatures_gap.md) |
| `1008_d0_audit.md` | [design_docs/reports/d0_audit.md](reports/d0_audit.md) |
| `1008_defend_design.md` | [design_docs/designs/defend_design.md](designs/defend_design.md) |
| `1008_defend_phase1_gap.md` | [design_docs/designs/defend_phase1_gap.md](designs/defend_phase1_gap.md) |
| `1008_dormancy_gap.md` | [design_docs/designs/dormancy_gap.md](designs/dormancy_gap.md) |
| `1008_family_farm_report.md` | [design_docs/reports/family_farm_report.md](reports/family_farm_report.md) |
| `1008_frontier_freeze_diff.md` | [design_docs/reports/frontier_freeze_diff.md](reports/frontier_freeze_diff.md) |
| `1008_g_d0_2_plan.md` | [design_docs/designs/g_d0_2_plan.md](designs/g_d0_2_plan.md) |
| `1008_harness_handover.md` | [design_docs/archive/harness_handover.md](archive/harness_handover.md) |
| `1008_instincts_wiring_gap.md` | [design_docs/designs/instincts_wiring_gap.md](designs/instincts_wiring_gap.md) |
| `1008_map_resources_design.md` | [design_docs/designs/map_resources_design.md](designs/map_resources_design.md) |
| `1008_market_justice_design.md` | [design_docs/designs/market_justice_design.md](designs/market_justice_design.md) |
| `1008_model_api.md` | [design_docs/contracts/model_api.md](contracts/model_api.md) |
| `1008_s3_s5_taskbridge_design.md` | [design_docs/designs/s3_s5_taskbridge_design.md](designs/s3_s5_taskbridge_design.md) |
| `1008_scheduler_design.md` | [design_docs/designs/scheduler_design.md](designs/scheduler_design.md) |
| `1008_spaces_p3_gap.md` | [design_docs/designs/spaces_p3_gap.md](designs/spaces_p3_gap.md) |
| `1008_spaces_p4_p5_gap.md` | [design_docs/designs/spaces_p4_p5_gap.md](designs/spaces_p4_p5_gap.md) |
| `1008_spaces_window_design.md` | [design_docs/designs/spaces_window_design.md](designs/spaces_window_design.md) |
| `1008_spatial_index_gap.md` | [design_docs/designs/spatial_index_gap.md](designs/spatial_index_gap.md) |
| `1008_structure_store_gap.md` | [design_docs/designs/structure_store_gap.md](designs/structure_store_gap.md) |
| `1008_tick_profile.md` | [design_docs/reports/tick_profile.md](reports/tick_profile.md) |
| `1008_tier3.md` | [design_docs/designs/tier3.md](designs/tier3.md) |
| `1008_wire_notes.md` | [design_docs/contracts/wire_notes.md](contracts/wire_notes.md) |
| `1008_worldgen.md` | [design_docs/designs/worldgen.md](designs/worldgen.md) |
| `1009roadmap.md` | [design_docs/ROADMAP.md](ROADMAP.md) |
| `1010_aux_state_gap.md` | [design_docs/designs/aux_state_gap.md](designs/aux_state_gap.md) |
| `1010_settlement_gap.md` | [design_docs/designs/settlement_gap.md](designs/settlement_gap.md) |
| `backend_to_render.md` | [design_docs/contracts/backend_to_render.md](contracts/backend_to_render.md) |
| `client_backend_boundary.md` | [design_docs/contracts/client_backend_boundary.md](contracts/client_backend_boundary.md) |
| `CODEX_IMPLEMENTATION_GOAL.md` | [design_docs/archive/CODEX_IMPLEMENTATION_GOAL.md](archive/CODEX_IMPLEMENTATION_GOAL.md) |
| `DOCS.md` | [design_docs/README.md](README.md) |
| `ENGINEERING_REVIEW.md` | [design_docs/archive/ENGINEERING_REVIEW.md](archive/ENGINEERING_REVIEW.md) |
| `humanizer_issue.md` | [design_docs/archive/humanizer_issue.md](archive/humanizer_issue.md) |
| `humanizer_migration.md` | [design_docs/archive/humanizer_migration.md](archive/humanizer_migration.md) |
| `implement.md` | [design_docs/archive/implement.md](archive/implement.md) |
| `implementation_0905.md` | [design_docs/archive/implementation_0905.md](archive/implementation_0905.md) |
| `implementation_1006_2d_rebaseline.md` | [design_docs/designs/implementation_1006_2d_rebaseline.md](designs/implementation_1006_2d_rebaseline.md) |
| `implementation_all_actions.md` | [design_docs/archive/implementation_all_actions.md](archive/implementation_all_actions.md) |
| `IMPLEMENTATION_PROGRESS.md` | [design_docs/archive/IMPLEMENTATION_PROGRESS.md](archive/IMPLEMENTATION_PROGRESS.md) |
| `implement_control.md` | [design_docs/archive/implement_control.md](archive/implement_control.md) |
| `implement_crafting.md` | [design_docs/archive/implement_crafting.md](archive/implement_crafting.md) |
| `implement_inventory_materials.md` | [design_docs/archive/implement_inventory_materials.md](archive/implement_inventory_materials.md) |
| `implement_llm.md` | [design_docs/archive/implement_llm.md](archive/implement_llm.md) |
| `implement_occupation.md` | [design_docs/archive/implement_occupation.md](archive/implement_occupation.md) |
| `implement_orchestrator.md` | [design_docs/archive/implement_orchestrator.md](archive/implement_orchestrator.md) |
| `implement_refined_task.md` | [design_docs/archive/implement_refined_task.md](archive/implement_refined_task.md) |
| `implement_refine_constuction.md` | [design_docs/archive/implement_refine_construction.md](archive/implement_refine_construction.md) |
| `implement_rendering.md` | [design_docs/archive/implement_rendering.md](archive/implement_rendering.md) |
| `implement_richer_task.md` | [design_docs/archive/implement_richer_task.md](archive/implement_richer_task.md) |
| `implement_tasks.md` | [design_docs/archive/implement_tasks.md](archive/implement_tasks.md) |
| `implment_schedule.md` | [design_docs/archive/implement_schedule.md](archive/implement_schedule.md) |
| `migration.md` | [design_docs/archive/migration.md](archive/migration.md) |
| `polish.md` | [design_docs/archive/polish.md](archive/polish.md) |
