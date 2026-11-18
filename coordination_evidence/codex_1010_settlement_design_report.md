# R6.4 settlement design repair handoff — 2026-10-10

Status: revised design for review, not accepted, implemented or production-ready. Edited only `1010_settlement_gap.md` and this report for this assignment. No source, canonical decisions, schema migration, defaults, tests or live/heavy runs changed.

The prior draft's new construction column, unconditional format 5, owner fields in strict StructureStore records, direct M_MAP_OBJECT clearing, and freeze-plus-closed-form-growth contradiction were removed. Actual source establishes existing S_BUILD_PROGRESS=9 in a 32-column entity tensor, 100 human/1024 entity live capacities, construction catalog item recipes, active construction helpers, exact StructureStore.RECORD_KEYS, and format-3/4 persistence selection.

The revised proposal now specifies:

- A separate bounded registry/project schema with exact keys, validated types/ranges, independent monotonic counters, caps and cross-field/reference rules; no slots as permanent identity and no settlement inventory owner disguised as a storage-case ID.
- Canonical integer chunk plus 1/256-unit subcoordinates, negative floor normalization, chunk-route coordinate range and integer-first local conversion across rebases. Existing dormant geometry floats remain honestly scoped.
- Bounded deterministic site candidates, active/dormant footprint checks, stamps/revision revalidation, protected authored objects/portals and explicit authority for any narrowly eligible natural-obstacle terraform. Default clear-site founding does not authorize arbitrary deletion.
- Existing personal_shelter recipe (6 wood_bundle, 3 fiber_bundle, 2 plank_bundle), once-only capped consumption from the consenting builder, paid labor gate, honest cancellation/destruction accounting, and no abstract H_CARRYING claim of discrete item conservation.
- A NEW staged commit/undo helper covering rows, geometry, inventories, registry and events. ActionRunner post-apply RecordOps and EffectApplier.atomic preflight are explicitly insufficient for that whole transaction. Adapter aliases reuse existing structure columns rather than adding one.
- One open project/review per eligible day, real stock/capacity/authority inputs, active work eligibility and dormant freeze without backlog. R6.5 catch-up requires a later conserved once-only bounded model.
- Optional settlement-state/required-feature design beside schema 3/4, with explicit old-reader silent-drop risk. A numeric future format is conditional on supported-reader compatibility analysis; no format number/refusal sentence is approved. DR-22 is genuinely open only for nonempty-state refusal/migration compatibility, canonical register unchanged. Claim radius is a routine proposed data recommendation; DR-10 arrest remains already open and is not reasked.

Substantive source inspected: `genesis_config.py`; `systems/construction/{schema,lifecycle,sites,ops,building,catalog,materials,repair}.py`; `systems/actions/{draft,runner}.py`, `verbs/{exploration,work}.py`; `harness/{structure_store,effects,world,adapter,engine_hooks}.py`; `persistence/world_snapshot.py`; actual UID allocation and resident movement/state sites in `map_test.py`; `api/chunk_routes.py`; R6.4 and DR-10 in `1009roadmap.md`. References and specific existing functions are recorded in the design's reuse table. No test execution is warranted for this documentation-only change; the document supplies future implementation and failure-injection acceptance cases.

Remaining engineering gaps: staging/undo implementation, dormant/protected footprint resolver, paid construction adapter, reader-range/required-feature compatibility policy, and R6.5 conserved catch-up. This handoff is substantive design, not an R6.4 completion claim. Long-walk probe/report ownership stays with this chat; backend void telemetry/importer files remain with their assigned workers.

## DR-22 wording candidates — review only, not approved

Nonempty authoritative settlement state with the feature disabled:

> This save contains settlements, but this session runs without settlement support, so it cannot be continued. Start the game with EDEN_SETTLEMENT=1 and the required streaming-world features to continue it. The save file has not been changed.

Unknown required feature or unsupported required-feature version:

> This save requires game features that this build cannot load, so it cannot be continued. Use a build that supports all of the save's required features. The save file has not been changed.

These are proposed text for a future pre-mutation refusal only. Include a separate diagnostic listing validated required-feature names/versions so users can identify the needed build; do not imply an unknown feature can be enabled through a guessed environment flag. Neither message names or approves a numeric world format. Neither solves downgrade safety in unmodified older readers that ignore the marker; the reader-range/schema contract still needs resolution. DR-22 remains OPEN and no canonical decision or production refusal was edited. An active new settlement may have zero buildings while the initial project is planned; dissolved records remain empty.
