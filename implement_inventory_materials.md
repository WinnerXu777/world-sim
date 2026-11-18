# Inventory Materials Implementation

This pass refines inventory so it becomes the material truth for:

- resident carry limits
- house-based bulk storage
- crafting inputs
- construction inputs
- ordinary work outputs such as hunting, gathering, farming, and woodcutting

## Core Rule

For normal residents:

- personal inventory is small and carry-limited
- if they have a completed house, that house becomes their bulk storage
- if they do not have a house, they are constrained by personal carry only

For the incarnation/player path:

- use the same backend item model
- but allow a richer carry tier and later better UI such as bags/chests

## Storage Model

Resident storage should be:

1. personal loadout
   - tools
   - small amounts of materials or food
   - limited by slots and weight

2. house storage
   - unlocked by a completed personal shelter / house
   - main bulk storage for that resident
   - stores work outputs, crafting materials, food, and tools

No-house residents should not get free bulk persistence.

## What This Should Drive

The same carry/storage model should govern:

- crafting
- construction
- hunting
- gathering
- woodcutting
- farming
- trader hauling

So the resident cannot keep producing resources forever if they cannot carry or
store them.

## Simplifying Rule

Do not force every resident to build a separate chest first.

For now:

- the completed house itself is the storage anchor
- optional standalone storage can remain for future expansion

## Implementation Direction

1. inventory schema
   - add weight capacity
   - add `house_storage`
   - keep resident carry small
   - keep incarnation carry larger

2. engine wiring
   - resolve a resident house inventory from completed `personal_shelter`
   - NPC tasks should prefer house storage instead of generic nearby shared storage

3. crafting
   - consume real item stacks from personal inventory or house storage
   - stop relying on `material_cache` for normal resident flows

4. construction
   - deliver real materials from personal carry to the build project
   - stop relying on abstract carrying as the material truth

5. occupation work
   - work outputs go into the real personal inventory first
   - if house storage exists, residents return home/store/resume
   - if no house exists, they remain carry-limited

## First Live Boundaries

The first live version does not need:

- nested bag inventories for ordinary residents
- full household ownership modeling
- full market/shop storage economics

It only needs:

- small resident carry
- house storage if housed
- real item consumption/production across work, crafting, and construction

## Current Live Status

This is now partially live in the runtime:

- resident loadouts use small slot/weight limits
- completed `personal_shelter` projects unlock `house_storage`
- occupation work outputs now land in real inventory instead of task-only cargo
- baseline crafting now consumes real inventory or house storage instead of
  relying on resident-side material caches
- live resident construction now delivers real carried materials into project
  progress instead of using abstract build carrying as the source of truth

Remaining gaps are mostly depth, not ownership:

- some legacy helper code still accepts `material_cache` as a compatibility
  parameter even though the main resident flow no longer depends on it
- player/incarnation inventory is not yet upgraded into the richer bag/chest UX
- settlement/public storage economics are still future work
