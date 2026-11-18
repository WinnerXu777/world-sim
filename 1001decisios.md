# Decisions requiring the user

Created 2026-10-10 at the user's request. Source: `1009roadmap.md`, section 20. This register collects unresolved decisions; recording a recommendation is not approval. Codex assigns independent roadmap work when a task reaches an open decision. AGY may proceed with roadmap recommendations already marked RECOMMENDED, but may not decide OPEN items or change defaults on its own.

## Open decisions inherited from the roadmap

| ID | Decision needed | Existing recommendation | Affected tasks | Status |
| --- | --- | --- | --- | --- |
| DR-1 | Approve or revise third calendar save/session length refusal wording (exact draft in roadmap section 8). | Approve existing draft. | R0.4 | OPEN |
| DR-2 | Choose which feature flags become defaults, their order, and approve golden re-recording. | Calendar, bounded perception, spaces/window, creatures, then economy. | R7.1 | OPEN; preserve defaults meanwhile |
| DR-5 | Choose mixed-biome tile junction priority and whether visual seam masks are needed. | Priority table first; masks if visual acceptance shows seams. | R5.1, R5.7 | OPEN; retain existing precedence |
| DR-7 | Choose walking animation approach and budget. | Existing A3 residents; authored two-pose wolf and boar first. | R5.3, R9.5 | OPEN; existing static art may be integrated |
| DR-8 | Choose character kit priorities and first hair/garment presets. | Child/elder first; three hair presets and three garment sets. | R9.6 | OPEN |
| DR-9 | Confirm image generation licence terms before public distribution. | Check applicable Imagegen/Qwen terms before release. | R7.6, R9.10 | OPEN; no public release |
| DR-10 | Decide whether the player's body may be arrested or restrained. | Never in Phase 1; revisit when guards are playable. | R6.12 | OPEN; no new player restraint |
| DR-13 | Decide rules-prior policy and acceptance criteria for real Tier 1 weights. | Keep rules prior; decide with real-model data. | R8.4 | OPEN; held until real model inputs |
| DR-14 | State Gate F target machine and frame-rate target. | Client owner supplies target; record with acceptance evidence. | R5.7 | OPEN; automated tests do not substitute for visual acceptance |
| DR-15 | Authorize pushing branch to GitHub. | After R0 and clean full suite, only on user's word. | R7.5 | OPEN; local work only |
| DR-16 | Approve exact packaging cleanup deletion list. | List first, delete nothing without approval. | R7.4 | OPEN |
| DR-17 | Choose civic/church hall identity, materials/architecture, readability/grandeur, appearance storage/version fallback, and invented creature priorities; details in `1008expansion.md` open decisions. | Readability first; rank invented creatures by gameplay hook. | R9.6–R9.8 | OPEN |

## Standing authorizations and implemented decisions

- Checkpoint commit: `b555adc`, message `1010morning`.
- User authorized sending the relevant roadmap, implementation contracts and 2D client source to Google/Gemini via Antigravity and permitting assigned client edits.
- User subsequently authorized AGY for all relevant roadmap implementations today (2026-10-10), including necessary simulation/backend source and tests sent to Google/Gemini. This does not resolve OPEN design decisions or authorize sending secrets, pushing, public release, destructive cleanup, or changing defaults.
- User explicitly authorized messaging/assigning both standby Codex chats (`01a125a9-9cb8-7c91-9c7e-bd0ea43611b2`, “Stand by for implementation”; `01a125a9-12d2-7710-a186-cb2a2fa4f69c`, “Stand by for implementation work”) as fallbacks. Use AGY first; dispatch to standby chats only when AGY quota is exhausted or its permission problem cannot be resolved. Initial messaging attempts before this explicit reply were rejected; no assignments were delivered then.
- User authorized current and future asset briefs to Google/Gemini; asset generation/judgment permissions persist.
- Dispatch roadmap work to AGY; read native `/usage` between assignments. When a Gemini quota bucket is exhausted, Codex takes over remaining implementation. Unknown quota or a command failure is not proof of exhaustion.
- Roadmap DR-3 and DR-4 are RECOMMENDED: explicit authored origin metadata; decoration drawn by client, interactive entities owned by backend. Backend origin contract work is outside the current client assignment and must be reported if missing.
- DR-6, DR-11, DR-20 and DR-21 remain DECIDED as recorded in the roadmap. Do not reopen them merely to start a task.
- DR-12, DR-18 and DR-19 are RECOMMENDED measurement/tuning work, not new user blockers; preserve default flags pending DR-2.

## New decisions discovered during implementation

### DR-22 — Settlement save compatibility and refusal wording (OPEN draft)

AGY's R6.4 design proposes a settlement save section and format 5, including a refusal when loaded without EDEN_SETTLEMENT. Existing persistence supports formats 1–4; the need for a new format is under technical review in 1010_settlement_gap.md and is not yet established. If review proves a new refusal is necessary, approve or revise its exact wording before implementation. Recommendation: first reuse additive validated state where compatible, and preserve old saves; bring only the final necessary refusal text for review. Affects R6.4 persistence, not independent settlement design/store/construction work. No format bump or wording approved. Claim-radius data is a technical recommendation rather than a newly required user decision; player arrest remains the existing DR-10.

Source-grounded review confirms older readers can ignore unknown top-level/required-feature fields and silently discard settlement data on re-save. An optional extension alone does not prove safe downgrade. The final supported-reader policy and necessary refusal text remain OPEN; the independent bounded registry/coordinate foundation can proceed. The auxiliary-state draft also proposed silently ignoring saved wounds/drives; root rejected that as data loss, not a recommended user option. If the corrected R6.13 architecture introduces authoritative saved auxiliary state, the same preservation/reader/refusal review applies; derived caches may rebuild only when no authoritative state is lost. No new auxiliary gameplay formulas or save migration are approved.
