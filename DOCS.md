# Documentation index

Written 2026-10-07 after the integrated 4-map build (8 residents). **Status words:** *current* = describes what the code does today; *plan* = a design or goal that guides work (parts may be done); *historical* = a record of how or why, no longer a description of the game; *stale parts* = mostly useful but contains lines that are no longer true (listed at the end).
Where two documents disagree, the order of authority is: the code and its tests, then the *current* contracts below, then `implementation_1006_2d_rebaseline.md`, then everything older (`1006_communication_scratchpad.md` rule 7).

## Start here

| Document | Status | What it is |
| --- | --- | --- |
| `README.md` | current (top) / historical (below "Legacy simulator notes") | What Eden 2D is, quick start (`play.ps1`), controls, first five minutes, architecture, tests. The legacy simulator README sits below it, unchanged. |
| `BACKEND.md` | current | Running the backend (env variables, four maps, roster, food/water loop), Save/Continue and the map guard, all routes, smoke and soak tools, known limits. |
| `godot_client_2d/README.md` | current, stale parts | The Godot 2D client: import, live tests, controls, the C1 to C6 additions. See "Stale lines" for what to ignore. |
| `play.ps1` | current | The one-command launcher (documented in `README.md`). |

## Contracts the client builds against (all current)

| Document | Status | What it is |
| --- | --- | --- |
| `1006_map_wire_contract.md` | current | `maps[]` in `/bootstrap`, `GET /map_file/{id}` (bytes, sha256, ETag), portals and `teleport_seq`, save manifest, **Continue with a changed map is refused** (section 6, implemented). |
| `1006_commission_api.md` | current | Commission routes, applied versus rejected results, order states, and the rule that the smith waits at the forge for a ready, uncollected sword (2 minutes). |
| `1006_god_mode_api.md` | current | God powers: envelope, possession state machine, heal, spawn, weather, time, witnesses and the event ledger. |
| `at_the_beginning/world_map/README.md` | current | The authored map file format (`0.2-draft`), validator and `tools/validate_map.py`. |

## Evidence (what was measured or run)

| Document | Status | What it is |
| --- | --- | --- |
| `1006_performance_report.md` | current from "Update after H6, H7, H8" on; the first sections are historical | 36000-tick and 90-game-minute soaks, the 5-minute HTTP soak, spike analysis, the roster-file incident. The numbers in the first half are for the earlier 5-resident, 2-map world. |
| `1006_live_smoke_report.md` | historical report plus current addenda | The first live smoke of the authored map (2026-10-06) and addenda for portals, the smith, god mode, and the four-map world with the ready-order hold. |
| `1006_gate_h_acceptance.md` | plan, stale parts | The coordinator's plan for the Gate H acceptance run. Verification plan, not a completion report. |
| `1006_backend_review.md` | current | The reviewer pass over the backend code written for the 2D build: what was fixed (including the pause-survives-reset bug) and the findings left open. |
| `godot_client_2d/C6_REPORT.md` | current | Recovery and presentation (reconnect, interrupted Continue, fault-injection tests). |
| `ASSET_LICENSE_AUDIT.md` | current as of 2026-10-07 | Provenance audit of the 33 assets the 2D client imports; re-run after any asset change. Not legal advice. |

## Plans and designs for the 2D game

| Document | Status | What it is |
| --- | --- | --- |
| `implementation_1006_2d_rebaseline.md` | plan (governing) | The October 6 decision to move to a 2D client and authored maps; overrides `implementation_0905.md` where they conflict. Order of work P0 to P7 and Gate H. |
| `1006_2d_first_version_goal.md` | plan (draft) | The proposed goal text for the first playable version ("Draft only"); the work it describes has been done in large part. |
| `1008implementation.md` | plan (draft) | Stage 2 plan: model plane and mock model server, T1a matrix policy, capability manifest and affordances, infinite map, world depth scenarios, asset needs, phasing and open questions. Nothing built yet. |
| `1008decisions.md` | current (living) | Orchestrator log for the Stage 2 work: ownership between the two worker sessions, rules of engagement, open decisions for the user, gap/verify inbox. |
| `1006newdesign.md` | plan | The Tier 1 decision model between rules and LLMs. Only the `DecisionProvider` seam with the rules provider, the decision log and the status field are built (`systems/decision`); no model is used in this build. |
| `1006_smith_loop_design.md` | historical (design, implemented) | Design of scheduled NPCs and the smith commission loop. The implementation differs in details (for example the ready-order hold, the food/water loop); `1006_commission_api.md` is the truth. |
| `1006_map_backend_integration.md` | historical (design, implemented) | How an authored map enters the backend (format `0.1-draft`, "design only"). Replaced by `1006_map_wire_contract.md` and `BACKEND.md`. |
| `1006_pathing_notes.md` | historical | Notes on the A* module. It says "not wired into schedules"; it is now used by the anchor mover (`systems/movement/anchor_mover.py`, `systems/roster/driver.py`). |

## Audits and reports from the start of the 2D work (historical)

| Document | Status | What it is |
| --- | --- | --- |
| `1006_godot2d_port_audit.md` | historical | Read-only audit of the existing Godot client and snapshot readiness (2026-10-06). |
| `1006_scale_constants_audit.md` | historical (values still agreed) | 48 px tiles, 8 units per tile, walk 20 u/s, actor radius 2.4. |
| `1006_snapshot_report.md` | historical | The local recovery snapshot taken before changing direction (S0). Not a description of the code. |

## Coordination records

| Document | Status | What it is |
| --- | --- | --- |
| `1006_communication_scratchpad.md` | current channel, stale parts | The shared channel between the Claude and Codex sessions (entries C-nnn, X-nnn). Its "Settled decisions" block still says Codex is generating assets. |
| `1006megathread.md` | historical | The coordinator's archive (about 200 KB): full reports and the archived channel. Search it, do not read it linearly; many statements in it (five residents, two maps, revision 1, 497 to 529 tests) were true when written. |

## Before the 2D re-baseline (historical; the 3D village and the legacy simulator)

| Document | Status | What it is |
| --- | --- | --- |
| `implementation_0905.md` | historical plan | The September 5 plan for a 3D Godot village and the model tiers (I0 to I5). Partly overridden by the re-baseline; the model-tier ideas are still the long-term plan. |
| `CODEX_IMPLEMENTATION_GOAL.md`, `ENGINEERING_REVIEW.md`, `IMPLEMENTATION_PROGRESS.md` | historical | The sibling documents of the 0905 plan: the 3D village goal, the 2026-09-05 engineering review (its delivery order is still cited), and the 2026-09-06 progress log. |
| `implement.md`, `implement_control.md`, `implement_crafting.md`, `implement_inventory_materials.md`, `implement_llm.md`, `implement_occupation.md`, `implement_orchestrator.md`, `implement_refine_constuction.md`, `implement_refined_task.md`, `implement_rendering.md`, `implement_richer_task.md`, `implement_tasks.md`, `implementation_all_actions.md`, `implment_schedule.md` | historical | April 2026 implementation notes of the legacy simulator (tasks, crafting, occupations, schedules, control, rendering, orchestrator, LLM). The systems exist in `at_the_beginning/systems/`; read the code first. |
| `backend_to_render.md`, `client_backend_boundary.md` | historical | April 2026 notes on the legacy 3D render/backend boundary. |
| `humanizer_issue.md`, `humanizer_migration.md`, `migration.md`, `polish.md` | historical | Legacy migration and polish notes. |
| `at_the_beginning/orchestrator/design.md`, `future.md`, `skills/*.md` | historical | Legacy orchestrator and tool-generation notes. |

## Not reviewed for this index

`myassets/*.md` (art bible, asset reports, the map contract reply), `tools/*.md`, `2D1006newstart/*.md`, `game_frontend/implement.md` and `godot_client/assets/README.md` belong to the art, tooling and legacy-client work; they are not described here.

## Stale lines to know about

These are the known statements that no longer match the game (the map wire contract title, the god-mode smoke count and the map-format README were corrected together with this index; the others belong to other authors and are left as written).
- **`1006_performance_report.md`**: sections "Commands", "(a)", "What the first run found", "(b)" and "Left as is" describe the earlier world (5 residents, 2 maps, `needs_scale` 0.02, env with only `smith_interior` origin). The `EDEN_MAP_FILES`/`EDEN_MAP_ORIGINS` there are incomplete for the current roster; use `BACKEND.md`.
- **`1006_live_smoke_report.md`**: the original run lists the old environment (one or two maps) and "five roster residents"; the current setup is in the docstring of `tools/smoke_common.py` and in the last addendum.
- **`1006_gate_h_acceptance.md`**: "529 tests" (now 539), "P6 roster currently has five residents" (it has eight), "both revision-2 authored maps" (four maps now; `starter_village` is revision 3).
- **`1006_communication_scratchpad.md`**: "The user has said Codex is currently generating assets" (settled decisions block).
- **`1006_pathing_notes.md`**: "Not wired into schedules, the engine, or any existing file".
- **`1006_map_backend_integration.md`**: written for format `0.1-draft` and a single map; the code accepts `0.2-draft` and several placed maps.
- **`godot_client_2d/README.md`**: "F1 toggles the collision overlay" in the P2 paragraph (the keys are now H or F1 for the controls card, F2 collision overlay, F3 debug line); the first paragraph says the project "does not connect to the backend" (C1 only; P2 onward does); "routes are specification only until the backend owner posts evidence" (they are implemented); the P2 paragraph says the live tests register only `starter_village.json` (the C2 note says all four maps).
- **Any document** that says NPCs cannot use portals, or shows the old run command with only the smith interior, predates the four-map world; the run command is in `BACKEND.md`.
