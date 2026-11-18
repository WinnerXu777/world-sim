# Occupation Module Plan

## Purpose

`systems/occupation` should define what kinds of ordinary-life work and roles
residents tend to have in the sim world.

It answers:

- what kind of role this resident usually fills
- what ordinary routines are most natural for that role
- how that role is inherited, copied, or mutated across generations
- what ordinary baseline tools this role typically needs

Occupation should become the primary source for schedule candidate generation.


## Core Layering

Recommended hierarchy:

- `occupation` = main ordinary-life blueprint
- `schedule` = time-structured routine selector
- `personality` = bias and variation
- `goal / planning` = special overrides
- `survival / urgent` = hard overrides

This means occupation should say what kind of life a resident usually lives,
while schedule decides when that life rhythm happens.


## Scope

The first version should be declarative.

It should:

- define occupations
- define their preferred time-block routines
- define routine bias weights
- define preferred place / tool tags for future use
- define `occupation_required_tools`
- define `occupation_optional_tools`
- assign occupation at birth or resident creation

It should not yet:

- directly call many tool chains every tick
- fully execute profession behaviors
- own settlement economy or task assignment


## Medieval Starter Occupations

Recommended first list:

- `farmer`
- `fisherman`
- `hunter`
- `guard`
- `builder`
- `woodcutter`
- `gatherer`
- `trader`
- `healer`

These occupations should be written as blueprints for a medieval world and
should intentionally align with systems you already have or expect soon, such
as:

- `movement`
- `construction`
- `inventory`
- `talk`
- future `interaction`, `tasks`, and `economy`


## Occupation Data

Recommended resident field:

- `occupation`
  - `kind`
  - `schema_version`
  - `origin`
  - `parent_bias`
  - `skill`
  - `stability`
  - `mutation`
  - `notes`

This should stay compact and JSON-friendly.


## Assignment Rule

Occupation assignment should be probabilistic, not fully deterministic.

Recommended inputs:

- parent occupation or occupations
- personality affinity
- weighted random mutation

Recommended behavior:

- parent occupation gives strong bias
- personality gives moderate bias
- random mutation allows occasional variation

This is not meant to be fully hereditary and not meant to be fully random.


## Baseline Tools Versus Strategic Tools

Occupation should only own ordinary-life provisioning needs.

Recommended split:

- `occupation_required_tools`
  - core tools a resident normally needs for ordinary work
  - examples:
    - fisherman -> `fishing_rod`
    - woodcutter -> `axe`
    - builder -> `hammer`
- `occupation_optional_tools`
  - useful but nonessential upgrades
  - examples:
    - fisherman -> `simple_net`
    - guard -> `torch`
    - builder -> `rope`, `plank_bundle`

These baseline tools should later be handled through deterministic ordinary-life
logic once survival pressure is clear.

Strategic or situational tools should not come from occupation by default.
Those should be requested later through plans and reasoning, for example:

- craft a weapon for revenge
- craft torches for a night ambush
- prepare extra medical supplies for a dangerous expedition

That keeps occupation realistic without turning it into a full plotting system.


## Module Layout

Recommended files:

```text
at_the_beginning/
  systems/
    occupation/
      __init__.py
      catalog.py
      schema.py
      inheritance.py
      assign.py
      resolver.py
      prompt_view.py
      ops.py
      design.md
      future.md
```

Ownership:

- `catalog.py`
  - occupation blueprints
  - routine preferences
  - routine bias weights
  - preferred place/tool tags
  - baseline required and optional tools
- `schema.py`
  - occupation record builders
- `inheritance.py`
  - weighted parent + personality + mutation logic
- `assign.py`
  - stable occupation assignment for new residents
- `resolver.py`
  - schedule-facing occupation preferences and weights
- `prompt_view.py`
  - prompt-facing summaries
- `ops.py`
  - stable integration surface


## Schedule Integration

Occupation should become the primary source for schedule candidate generation.

Recommended schedule order:

1. get time block
2. ask occupation blueprint for preferred routines in this block
3. score those routines
4. let personality modify them
5. sample a probabilistic final choice

Fallback:

- if no occupation exists, schedule can still use its default block routines


## Procurement Order

When occupation eventually requests a baseline tool, residents should not jump
straight to crafting. The recommended procurement order is:

1. check equipped item
2. check personal inventory
3. check household or accessible storage
4. borrow, inherit, or loot if allowed later
5. craft only if still missing

This keeps the sim more believable than having every resident recreate their
trade tool from scratch.


## Future Expansion

Likely path after scaffold:

1. ensure occupation on resident creation and load
2. let schedule use occupation as its primary routine source
3. later connect occupation baseline tools to inventory and crafting
4. later connect occupation to task execution
5. later connect occupation to economy, territory, and inventory depth
