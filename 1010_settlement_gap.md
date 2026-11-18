# Settlement R6.4 / growth R6.5: revised design gap — 2026-10-10

Status: **design proposal, not implemented or accepted**. This replaces the initial format-5/new-column/closed-form-growth draft. Symbols marked NEW are proposals. Existing function names refer to inspected source. No production edit, migration, gameplay default, refusal wording or user decision is approved here.

## 1. First slice and actual reuse points

The first opt-in slice registers settlements, links existing residents and built structures, designates a material-funded shelter, advances construction while participants are active, and proposes bounded local growth. Fully dormant settlements freeze. R6.5 catch-up is separate work with conserved resources; no statistical stock, work or population is invented on integration.

| Actual source / API | Reuse and limitation |
| --- | --- |
| genesis_config.py: MAX_HUMANS=100, MAX_ENTITIES=1024, MAP_TENSOR_COLS=32; S_BUILD_PROGRESS=9 | Existing structure progress. M_GEN=30 and M_SPACE=31 are occupied. No M_CONSTRUCTION_PROGRESS column or tensor-width change is needed. |
| systems/construction/sites.py: structure_blueprint, resolve_build_site, find_buildable_site | Actual footprint/defaults and nearby-land search; active rows only, without settlement ownership/dormant overlap validation. |
| systems/construction/ops.py: designate_site, spawn_structure, advance_build; building.py: designate_construction_site, spawn_structure_entity, build_with_humans | Existing live construction. Creation needs create_object_fn and returns a slot. Worker progress uses abstract H_CARRYING and can advance without carried material; it does not enforce discrete catalog recipes. |
| systems/construction/catalog.py: construction_blueprint, building_material_requirements | personal_shelter maps to M_HOUSE and requires wood_bundle=6, fiber_bundle=3, plank_bundle=2. Initial paid construction uses this kind only. |
| systems/construction/schema.py: build_construction_need, build_construction_project; lifecycle.py: ensure_construction_behavior_state | Existing resident need/project views: settlement_id on needs, site/metadata/progress on projects. Normalizing builders are not strict saved-settlement validators. |
| systems/actions/draft.py: ActionDraft, RecordOp, queue_task; runner.py: ActionRunner.plan/apply | Revision-aware planning, effect apply then record ops. Post-apply ops do not roll effects back. verbs/exploration.py has explore_toward; settle_site and migrate_group would be NEW. |
| harness/effects.py: Transfer, ItemPermit, Set, Spawn, Despawn, Emit, EffectApplier.validate/apply | Item conservation and preflight. atomic=True is validation before apply, not general rollback over geometry/dictionaries/record ops. Spawn does not register map_geo. |
| harness/adapter.py: EngineWorld, LegacyItemStore | Shared engine UID lists and real human/storage-case inventory records. An s_* string is not a supported inventory owner. ENTITY_COLUMNS lacks structure-progress/durability aliases. |
| map_test.py: _make_entity_id, _entity_uid_by_slot, _human_uid_by_slot, _sync_slot_ids_and_events | Actual runtime e_* UID allocation and identity mapping. Slots are transient, not saved building identity. |
| harness/structure_store.py: StructureStore.stash/restore/export/load/validate | Dormant runtime structures retain UID/columns/chunk-relative geometry. RECORD_KEYS is exactly {uid,type,cols,offset,tick,geo,seeded}; adding owner/settlement fields currently fails. DECAY_PER_DAY=0. |
| persistence/world_snapshot.py: capture/validate/restore | Formats 1/2/3/4, strict engine/runtime/window keys. Format 4 is chosen when window.structures is present. Calendar is optional but does not prove old readers preserve new authoritative state. |

NEW EDEN_SETTLEMENT=1 stays default off and requires window/spaces, structure-store and a consistent calendar profile. Flag off means no registry allocation, new hook/verb/wire/save section or RNG draw. Prerequisite failure is before world mutation. Existing save compatibility checks remain.

## 2. Exact bounded state proposal

NEW SettlementRegistry is an engine service, not an m_tensor row or StructureStore field. Its envelope has exactly {schema_version,next_id,next_project_id,records,projects}. schema_version=1; both counters are integers 1..100000000, monotonic, greater than every allocated suffix, never reused. Refuse exhaustion. All integer validation rejects bool, float and string coercion. Unknown keys, duplicate links, NaN and infinity fail validation.

Proposed NEW caps (data choices, not existing engine guarantees): 32 settlements, 64 retained projects total, 1024 building links total, at most cfg.MAX_HUMANS distinct current members globally. Saturation refuses new operations without evicting authoritative records.

Settlement record has exactly:

| Key | Type and range |
| --- | --- |
| uid | NEW s_ plus eight decimal digits 00000001..99999999. |
| name | Nonempty string, <=80 Unicode characters, no control characters. |
| anchor | Exact chunk/sub coordinate record below; overworld only. |
| claim_radius_q | Integer 1..131072, with Q=256; NEW initial fixed recommendation 51200 (200 units). Saved data, no population-driven changes. |
| members | Sorted unique strings, length 1..128, resolved against authoritative resident records; a living member belongs to at most one settlement. No invented human-ID pattern or slot-based identity. |
| buildings | Sorted unique runtime structure UIDs, length 1..128, resolving to an active structure or dormant StructureStore record; generated chunk features excluded. |
| roles | Dictionary: keys subset of members, values builder/keeper/watch only. watch confers no arrest/restraint ability. |
| founded_tick, last_review_tick | Integers 0..2^63-1 with founded_tick <= last_review_tick <= saved engine.tick. |
| status | active/dissolved; active founding may have zero buildings while the first project is planned. Dissolved records have empty members/buildings/roles. Explicit dissolution clears links before retention cleanup. |

NEW project record has exactly {id,settlement_id,builder_id,building_kind,anchor,structure_uid,status,created_tick,last_work_tick,recipe,paid}. id=sp_ plus eight decimal digits under next_project_id. References use the same string bounds and resolve globally. building_kind initially personal_shelter; status is planned/funded/building/complete/cancelled/destroyed. structure_uid is null only while planned, cancelled before placement, or destroyed after an audited loss. Ticks obey the preceding bounds. recipe/paid are dictionaries with exactly the selected catalog recipe keys; recipe matches supported catalog/profile, paid has integer quantities 0..recipe[item]. At most one open project per settlement. Existing resident construction project records are derived views, not a second material account.

Cross-field validation: planned has null structure_uid and all paid quantities zero; funded/building/complete have a resolving structure_uid and paid==recipe. Cancelled-before-placement has null UID/zero payment, whereas cancelled-after-funding retains the structure link and full payment. Destroyed has null structure_uid and paid==recipe; its transition removes the building link and emits the old UID/material-loss audit in the same commit. Complete requires S_BUILD_PROGRESS=100 in the active row or dormant cols; other live work states require progress below 100. Project anchors must lie inside the owning claim and match the linked structure's designated anchor within the declared quantization tolerance. Retained terminal projects can be pruned only after their audit is persisted, without deleting live unfinished structures or refunding material. A dead builder's existing authoritative resident record remains a valid historical project reference; reassigning live work requires a new explicitly validated builder.

Before restore mutates state, members must exist in payload.residents; a building UID must occur exactly once across active IDs/dormant structure records, have STRUCTURE_TYPES type and overworld space, and have at most one settlement association. Dormant is valid, not missing. Death removes current membership/roles but may retain historical resident records. Explicit destruction removes building links/cancels work; unload retains links. At runtime an unresolved UID pauses work and emits an audit entry; confirmed destruction resolves it. Malformed missing references on load fail rather than creating replacements. Restoration rebinds the same UID to a new slot; never cache a slot across ticks.

Association is organizational, not a new property/crime rule. Do not expand fetch_item/theft/container permissions or infer public stock from proximity. Future ownership needs a separate validated UID table with explicit authority; do not change StructureStore.RECORD_KEYS. Household ownership semantics are deferred.

## 3. Exact coordinates and site validation

NEW Q=256 subunits per unit; chunk=256 units=65536 subunits. anchor is exactly {chunk:[cx,cy],sub:[sx,sy]}. Chunk components are integers in [-2^40,2^40], matching current chunk_routes.MAX_ABS_COORD; sub components are integers 0..65535. Negative coordinates use floor division/divmod. Designation snaps the local request once to this lattice with documented nearest-grid/tie behavior. Do not re-quantize after every rebase.

Live local x is ((cx-origin_cx)*65536+sx)/256, y likewise: subtract integers first. Claims, overlap and offsets use integer differences/squared distances against claim_radius_q, not float(cx*256)+local. Live designation is restricted to integrated nearby chunks, bounding local float magnitude. Registry anchors never rebase. Existing StructureStore offsets/geometry floats are retained; this does not claim all legacy geometry is fixed-point.

NEW plan_settlement_site is pure candidate data:

1. Resolve living actor UID, overworld, founding/designation authority, world/window stamp, registry/project capacity, consenting builder and actual materials. Verify reach/work eligibility through real legality/movement routes. Roster residents need the existing routine path, not a task their anchor driver suppresses.
2. Reuse sites.find_buildable_site with catalog footprint, then check claim overlap, reserved projects, active movement/wall/void geometry, pinned authored maps/portals and dormant structure footprints. Use a finite NEW lattice/ring search capped at 64 candidates, ordered by integer squared distance then cx,cy,sx,sy. No unordered-set tie or random fallback.
3. Reject pending/unloaded chunks and protected obstacles. M_MAP_OBJECT includes authored forge/door/anvil, not a reliable tree/rock class. Claims do not authorize demolition. First slice accepts a clear site by default.
4. Optional NEW terraform request separately names sorted obstacle UIDs and allowed operation. Require explicit authority for confirmed eligible generated/unowned natural obstacles inside the work footprint. Refuse authored/pinned objects, portals, buildings, inventory-bearing entities, occupied geometry/living actors, unknown protection/ownership or whole natural terrain-region deletion. Inspect actual generator/authored/resource metadata; do not classify from M_TYPE alone. Preview exact deletions/resource effects. Broader terrain edits remain deferred.
5. Revalidate all UIDs, footprint, stamps, inventory, revision and destination capacity immediately before commit. Finish every check before any deletion/consumption. A full destination row cannot leave cleared ground and lost materials.

## 4. Paid construction and transaction boundary

Initially personal_shelter consumes its full catalog recipe from the consenting builder's human inventory, once when funding the site. Communal storage access is deferred. Use actual Transfer(item,qty,builder_uid,None) with exactly capped ItemPermit.consume. NEW paid is accounting for consumed items invested in the structure, not an invented ItemStore balance. No src=None creation. Labor requires paid==recipe and active, reachable, living builder with enough stamina. Use S_BUILD_PROGRESS, HP and the existing structure blueprint; cap progress at 100. Adapt worker calculations to the paid gate; calling legacy abstract gather_materials/build_with_humans is not proof of discrete conservation. Do not additionally bill H_CARRYING as duplicate material.

Planned/unfunded cancellation consumes nothing. After funding, cancellation leaves an unfinished structure and stops work: invested material remains consumed, automatic refunds/salvage are zero. Destruction audits that loss once. Future salvage needs capped produce permits and anti-double-refund state. Repair needs a NEW explicit item recipe/labor gate; current repair_with_humans only uses abstract carrying/stamina. Active age/weather decay is deferred and dormant zero decay remains.

NEW commit_settlement_project owns the whole commit. Do not consume in ActionDraft.effects and put registry/geometry creation in an ordinary post-apply RecordOp: runner.apply does not roll those effects back. atomic=True preflight is not arbitrary exception rollback and needs additional aggregate row/field/capacity validation.

Preflight column names/aliases, whole-batch item totals, geometry permission and row reservations; stage registry/project data. Retain undo data for affected tensor rows, UID counters/lists, counts/masks, map_geo/tile ownership/version, inventory/seeding records, pending events/despawns, harness index/revision, resident records and dirty markers. Execute synchronously on the engine tick, no await/worker handoff. Reuse create_object and _make_entity_id for runtime structures, register geometry once, consume once, publish registry links/event only after success. Any exception/skipped effect restores every captured component; emit only a separate failure audit. Narrow staging/undo is NEW and needs fault injection. Existing world.apply is reused within it, not claimed to provide this guarantee.

If harness Set handles structures, NEW ENTITY_COLUMNS aliases build_progress/durability/shelter_cap/occupant_count must map to existing constants; those names are absent today. No new column. Resident need/project views derive after commit and can be rebuilt. Request/project IDs make a lost-response retry return the prior result, never pay/spawn twice.

## 5. Growth and dormancy

NEW daily review uses harness/calendar.active().day_ticks plus saved last_review_tick. Review settlements in UID order once per eligible day. Housing capacity comes from linked complete/intact active or dormant buildings; blueprints are not beds. First slice adds no population. If members lack capacity, no project is open, a builder is active with exact recipe, and a valid site exists, queue at most one construction need/proposal. A configured food-reserve test must count authorized real quantities minus a declared per-member reserve, never virtual surplus or newly inferred public stock. Failure leaves a paused need, no stock creation/task spam. Bound search and registry counts as above.

Work requires integrated project site and active nearby assigned member. Other linked chunks may be dormant. Current residents remain rows under dormancy; they do not enter StructureStore. Building restore can change slots, not UIDs. All-dormant first slice freezes. Wake advances review watermark to current day boundary without backlog growth, labor, births or decay. Rebase changes only live coordinate conversion.

R6.5 is later: separately versioned catch-up, elapsed-day cap, deterministic ordering and persisted last-applied tick. Production requires saved source stock and destination capacity; consumption/work/deaths/building loss debit conserved accounts. Missing stock/labor/capacity means freeze/refuse catch-up. No statistical material, completed construction or residents. Save/reload must match uninterrupted bounded catch-up and never apply elapsed days twice. Existing zero-rate structure decay cannot imply settlement growth.

## 6. Persistence compatibility analysis

Do not add settlement/owner keys to StructureStore records, payload.engine or window: exact RECORD_KEYS, ENGINE_FIELDS and _validate_window prevent this. NEW top-level settlement_state is separately versioned/validated, with NEW world_format.required_features indicating its version. This may coexist with schema 3 (no dormant structures) or schema 4 (structures present); settlements must not pretend to be dormant structures or cause an unconditional format 4/5 bump. Persist both UID counters, anchors, paid recipes and review watermarks. Validate the entire payload/references before reset_world, restore/bind after validation, and clear registry on new world. Old otherwise compatible saves without extension initialize empty registry.

However, current older readers ignore unknown top-level/world_format keys. They could load a schema-3/4 settlement save, then silently lose settlement state on re-save. Optional fields alone are therefore not a safe downgrade contract. If every supported reader is updated to reject unknown required_features before mutation, the optional extension is viable without a numeric bump. If unmodified older readers remain supported, a future recognized schema is needed for settlement-bearing saves to force refusal. Its number/migration follows that compatibility analysis/tests, not an assumed format 5. Existing format-4 refusal concerns dormant buildings and cannot explain lost settlement state.

New readers with settlement disabled must refuse nonempty authoritative settlement state before reset_world, never silently ignore it. Empty/absent state can load after validation; existing format/map/registry/calendar checks still apply. Genuine missing contract: supported reader range and nonempty-extension refusal/migration wording. **DR-22 is OPEN only for this actual new wording/compatibility issue if that policy is adopted**. No refusal sentence is approved here; canonical decisions are untouched. Settlement-on is not permission to migrate incompatible format-1/2 worlds.

## 7. Required implementation verification

No tests ran for this documentation change. Future acceptance requires:

- Flag off: current strict goldens and old save bytes/key sets unchanged; no added hooks/RNG/APIs. Absent-extension saves load only when otherwise compatible.
- Exact keys/types/caps: bool-as-int, duplicate IDs/links, unknown references/roles/items, malformed recipes, NaN/future ticks and counter exhaustion fail before mutation.
- Negative/large chunk normalization near +/-2^40, multiple rebases, deterministic site ties and unchanged claims/anchors after save/reload.
- Protected authored portal/door/forge, dormant overlaps, unknown authority, pending chunk, unreachable/occupied footprint: no deletion, item debit or geometry change.
- Actual 6 wood/3 fiber/2 plank payment once, no unfunded/offscreen progress, rollback fault injection at every stage, lost-response idempotency, no cancel/destroy refund creation.
- Unload/reintegrate retains UID/paid/progress with changed slot; death/destruction clears correct links; duplicate active/dormant UID fails before restore reset.
- One open project/review per day, finite candidate search, cap saturation without authoritative eviction; no repeated tasks/virtual stock.
- Long dormancy freezes; waking advances watermark without catch-up. Later R6.5 conserved, bounded, once-only catch-up/save equivalence.
- Schema 3+extension, schema 4+structures+extension, empty state, flag-disabled refusal, unknown required feature, unmodified-reader downgrade behavior; refused save bytes unchanged.

Claim radius is a routine proposed default-off data choice, not a new user blocker. Arrest/restraint is already DR-10 OPEN in 1009roadmap.md; it is not reasked or enabled. Remaining technical gaps are the full commit/undo boundary, exact dormant/protected footprint resolver, paid-build adapter, supported-reader compatibility contract and R6.5 conservation model. This is substantive design for review, not R6.4 completion or production readiness.
