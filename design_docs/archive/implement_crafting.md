# Crafting Module Plan

## Purpose

`systems/crafting` should define how tools, components, and simple usable items
are made from materials.

It answers:

- what materials are required to make an item
- what tools or stations are required
- what occupations naturally care about that item
- how future residents and the incarnation can turn materials into useful gear
- how ordinary baseline crafting differs from strategic plan-driven crafting

This module should become the bridge between `inventory`, `occupation`, and
`construction`.


## Core Layering

Recommended ownership split:

- `inventory` = what an actor or container currently has
- `crafting` = how items and components are made
- `construction` = how placed world structures are built
- `occupation` = what tools and work outputs are typically needed
- `schedule` = when ordinary procurement and crafting happens
- `goal / planning` = special projects and long-horizon crafting intent

This keeps `construction` focused on structures rather than turning it into a
giant everything-menu.


## Scope

The first version should be declarative and recipe-oriented.

It should:

- define crafting recipes
- define ingredient requirements
- define required tool tags and station kinds
- define occupation tags for recipe affinity
- define `plan_requested_recipes` as a future reasoning-facing concept
- expose prompt/runtime helpers for future integration

It should not yet:

- fully execute profession crafting end to end
- reserve stations or containers in the live runtime
- auto-run resident procurement chains
- support complex vehicle or boat production


## First Recipe Slice

Recommended early craftables:

- `stone_blade`
- `rope`
- `plank_bundle`
- `club`
- `spear`
- `hammer`
- `fishing_rod`
- `simple_net`
- `bandage`
- `torch`

These are intentionally simple and useful for:

- occupation realism
- manual incarnation crafting
- future construction inputs
- future repair and survival loops


## Baseline Versus Strategic Crafting

Recommended split:

- `baseline occupational crafting`
  - deterministic ordinary-life behavior
  - only for core occupation tools
  - examples:
    - fisherman makes or acquires `fishing_rod`
    - woodcutter makes or acquires `axe`
    - builder makes or acquires `hammer`
- `strategic crafting`
  - triggered by `goal / planning`
  - created through future `plan_requested_recipes`
  - examples:
    - make a weapon for revenge
    - prepare torches for a night ambush
    - craft medical stock before a risky trip

This keeps everyday provisioning cheap and believable while preserving richer
goal-driven crafting for special events.


## Occupation Integration

Occupation should declare what tools or crafted outputs matter for ordinary
life.

Examples:

- `fisherman`
  - `fishing_rod`
  - later `simple_net`
  - much later `small_boat`
- `builder`
  - `hammer`
  - `rope`
  - `plank_bundle`
- `guard`
  - `spear`
  - `torch`
- `healer`
  - `bandage`

Recommended rule:

- occupations should express tool and output affinity
- crafting should define how those items are made
- inventory/storage should decide whether crafting is even necessary

This means residents do not need tools to pop into existence. They can inherit,
borrow, loot, or craft them when missing.


## Procurement Order

Residents should not jump directly to crafting a missing item.

Recommended procurement order:

1. check equipped item
2. check personal inventory
3. check household or accessible storage
4. borrow, inherit, or loot if allowed later
5. craft only if still missing

This same order should later apply to ordinary occupation tools and strategic
plan-driven recipes.


## Manual Incarnation Integration

The incarnation should eventually use the same recipe system as residents, but
through direct manual control.

Recommended gameplay loop:

1. player wants an item
2. crafting checks recipe and missing materials
3. inventory and nearby storage are queried
4. if materials exist, craft directly or at a required station
5. crafted output is added to inventory or nearby container

This should later support a proper crafting UI without needing a separate item
logic system for the player.


## Module Layout

Recommended files:

```text
at_the_beginning/
  systems/
    crafting/
      __init__.py
      catalog.py
      schema.py
      resolver.py
      stations.py
      prompt_view.py
      ops.py
      design.md
      future.md
```

Ownership:

- `catalog.py`
  - recipe blueprints
  - ingredient lists
  - tool/station requirements
  - occupation affinity tags
  - future support for baseline versus strategic recipe usage
- `schema.py`
  - crafting job records and schema helpers
- `resolver.py`
  - recipe queries and lightweight requirement lookup
- `stations.py`
  - station definitions and station-facing helpers
- `prompt_view.py`
  - prompt/runtime summaries for recipes and jobs
- `ops.py`
  - stable integration surface


## Runtime Wiring Plan

Recommended wiring path:

1. scaffold recipe catalog and helpers
2. connect occupation blueprints to preferred recipe kinds
3. connect inventory to recipe satisfiability and missing-ingredient checks
4. connect occupation baseline tool needs to recipe lookup
5. add player-side manual crafting flow
6. later allow resident occupation logic to create procurement/crafting needs
7. later allow planning to emit `plan_requested_recipes`
8. later connect crafted outputs into `construction`

This module should begin as a shared truth layer before any major live runtime
execution is added.


## Future Expansion

Likely path after scaffold:

1. add inventory item definitions for crafting materials and outputs
2. add player crafting UI and manual build actions
3. add resident procurement and simple crafting execution
4. add station usage and reservation rules
5. add multi-step chains, repair, recycling, and quality
6. add advanced occupation equipment such as boats, carts, and workshops
