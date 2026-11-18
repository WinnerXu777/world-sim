# Refined Construction Implementation

This document covers the next construction layer after tool crafting is live.

The main goal is:

- make buildings feel as real as tools
- let residents build required structures because they need them
- keep construction ownership clean across `survival`, `occupation`,
  `planning`, `tasks`, `inventory`, and `construction`

## Core Rule

Construction should follow the same high-level split as crafting:

- producers decide *why* a building is needed
- `systems/tasks` later executes *how* it gets built
- `systems/construction` remains the owner of placed structures, build sites,
  and structure progress

So:

- `survival`
  - can emit basic shelter needs
- `occupation`
  - can emit work-related building needs
- `planning`
  - can emit optional or strategic building needs
- `tasks`
  - should later carry out gather / move / designate / build / repair chains
- `construction`
  - should own blueprints, need schemas, project records, site rules, and
    structure placement

## Building Categories

The first refined split is:

### 1. Basic Required Buildings

These are emitted by deterministic need producers.

Examples:

- `personal_shelter`
- `household_storage`
- `farm_plot`
- `village_well`
- `market_anchor`

These should be created because the sim determines they are needed.

Examples:

- if a resident or household lacks usable shelter, emit a shelter need
- if a farmer has no nearby farm anchor, emit a farm need
- if goods accumulate without storage, emit a storage need
- if a settlement has trade activity but no market anchor, emit a market need

### 2. Optional / Strategic Buildings

These are emitted by higher-level reasoning and plans.

Examples:

- `wall_segment`
- `watch_post`
- `hidden_cache`
- `fortified_gate`
- future workshops and specialized shops

These should not be built by default just because they exist. They should come
from goals, plans, or settlement-level strategy.

## Ownership Scopes

Building needs should carry a scope:

- `personal`
- `household`
- `occupation`
- `settlement`
- `strategic`

That scope matters because a resident should not always build a new structure
just because they personally do not own one.

## Build Decision Order

Before creating a new building need, the sim should prefer:

1. use an existing suitable structure
2. use a shared household / settlement structure
3. repair an existing damaged structure
4. only then create a new building need

This should make the world feel more realistic and less wasteful.

## New Construction Layer

The refined construction scaffold should add:

- `catalog.py`
  - declarative building blueprints
- `schema.py`
  - building-need and construction-project records
- `lifecycle.py`
  - construction state/profile normalization
- `needs.py`
  - deterministic building-need evaluation helpers
- `prompt_view.py`
  - reasoning-facing summaries for needs and projects

These should sit above the existing structure/site tools without replacing
them.

## Blueprint Requirements

Each building blueprint should describe:

- current support status
- category
- scope
- structure type
- material requirements
- producer hints
- place/site preference
- whether it is intended to be auto-emitted or plan-only

## Initial Building Set

The first scaffold should cover:

- `personal_shelter`
  - current structure type: `house`
- `household_storage`
  - current structure type: `storage_case`
- `farm_plot`
  - current structure type: `farm`
- `village_well`
  - current structure type: `well`
- `market_anchor`
  - current runtime placeholder: `village`
- `wall_segment`
  - current structure type: `wall`

`market_anchor` is a deliberate placeholder until a dedicated market/shop
structure exists in the map schema.

## Live Runtime Wiring

The first live construction pass now does this:

1. resident/runtime state normalizes:
   - `construction_profile`
   - `construction_state`
   - `construction_needs`
   - `construction_projects`
2. `map_test.py` emits deterministic resident needs for:
   - `personal_shelter`
   - `household_storage`
   - `farm_plot`
3. those needs become stable resident construction projects
4. `systems/tasks` routes:
   - `designate_build_site`
   - `build_project`
5. the engine bridge designates a real site, gathers abstract build material,
   and advances build progress on the real placed structure

## Next Runtime Wiring

The next expansion after this live slice is:

1. `planning` emits strategic/optional structures
2. settlement/public producers emit deduped shared needs like:
   - `village_well`
   - `market_anchor`
3. `tasks` grows repair / resume / builder-specialist construction chains
4. `construction` consumes real inventory-backed materials instead of abstract
   carrying only

## Current Boundaries

This pass should *not* try to:

- add every future structure class now
- solve all ownership and settlement management rules
- replace existing direct structure tools

The goal of this phase is to get a truthful first live slice working while
keeping settlement/public construction and inventory-backed materials for later
passes.
