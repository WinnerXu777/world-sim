# Rendering Implementation

This document defines the first concrete rendering architecture for the project.

The main goal is:

- make `human mode` feel embodied and readable in 3D
- make `god mode` feel strategic and fast to read in 2D / 2.5D
- reuse one coherent asset family instead of building separate art pipelines
- keep the rendering plan modular so it can grow with the backend systems


## Core Visual Direction

The project should use a single main low-poly fantasy / medieval asset family.

That family should feed both:

- `human mode`
  - fully 3D presentation
  - first-person and third-person camera support
- `god mode`
  - orthographic or high-angle 2.5D presentation
  - same world assets, different camera and readability rules

The most important design rule is:

- do not build two separate worlds
- build one 3D world and render it differently depending on mode

This keeps:

- asset production simpler
- style consistent
- backend-to-visual mapping much cleaner


## Chosen Asset Stack

The current recommended asset stack is:

### Environment / Exterior

- `Medieval Village MegaKit`

Role:

- houses
- roads
- roofs
- stairs
- doors
- windows
- walls
- village exteriors

Use:

- settlement shells
- houses and shelters
- village-level construction output
- god-mode settlement rendering

### Interior / Props / Furniture

- `Fantasy Props MegaKit`

Role:

- furniture
- clutter
- containers
- tables
- market props
- workshop props
- interior dressing
- some tools and weapons

Use:

- house interiors
- market/shop interiors
- storage visuals
- crafting/construction props

### Human Base Characters

- `Universal Base Characters`

Role:

- resident base meshes
- incarnation base mesh

This should be treated as the base humanoid visual layer.

### Human Variation

- `Modular Character Outfits - Fantasy`

Role:

- clothing variation
- profession variation
- social/status variation

Use:

- guard vs farmer vs trader vs builder silhouettes
- male/female resident variety
- incarnation customization later

### Human Animation

- `Universal Animation Library`

Role:

- locomotion
- combat
- hit / death
- emotes
- seated / idle

Use:

- human mode animation state machine
- resident task visualization

### Animals

- `Ultimate Animated Animal Pack`

Role:

- wolves
- tigers
- prey animals
- domestic animals later if covered

Use:

- wildlife
- hunting
- danger presentation

### Weapon Expansion

- `Medieval Weapons`

Role:

- crafted weapons
- combat readability
- held item visuals

Use:

- spear / axe / club / sword / polearm breadth
- crafting output visuals

### Construction-Phase Supplement

- `Kenney Retro Fantasy Kit`

Role:

- construction-stage visuals
- temporary build-state meshes
- simplified god-mode structure silhouettes

Use:

- planned sites
- foundations
- partial walls / early shells
- in-progress construction readability

Important rule:

- this should be treated as a supplemental kit
- it should not replace the main Quaternius building family for completed
  structures
- use it mainly for build-process states and simplified overview rendering


## Mode Split

## Human Mode

Human mode should be the high-fidelity embodiment layer.

Target feel:

- first-person or third-person
- animated residents and animals
- real 3D buildings and interiors
- held tool / weapon visuals
- close-range interaction readability

Human mode should visually emphasize:

- nearby people
- nearby tools / props
- doors / containers / work objects
- combat threat
- talk and local social life


## God Mode

God mode should be a readability-first overview layer.

Target feel:

- orthographic or near-orthographic high-angle camera
- 2D / 2.5D presentation built from the same 3D world
- faster map scanning
- simpler silhouettes
- lower animation priority

God mode should visually emphasize:

- settlement layout
- structures
- groups of residents
- animals
- high-level movement and events

Important rule:

- god mode should not need separate bespoke sprite art for everything in phase 1

Instead, phase 1 should use:

- the same 3D assets
- simpler materials
- distance culling
- optional billboards / icons for overlays
- orthographic camera framing


## God Mode Rendering Strategy

The simplest strong version is:

### Phase 1

- render the same 3D world in god mode
- use an orthographic or high-angle camera
- reduce visual noise with:
  - flatter lighting
  - reduced shadow complexity
  - lower animation emphasis
  - color-coded overlays for important sim state

### Phase 2

- add selective icon overlays for:
  - hunger
  - threat
  - talk
  - combat
  - construction
  - storage

### Phase 3

- add optional sprite / billboard replacements for far-away humans and animals

This avoids the need to paint a full second visual set up front.


## Godot Asset Layout

Recommended import layout:

```text
godot_client/
  assets/
    quaternius/
      environment/
        medieval_village_megakit/
      props/
        fantasy_props_megakit/
      characters/
        universal_base_characters/
        modular_character_outfits_fantasy/
      animals/
        ultimate_animated_animals/
      weapons/
        medieval_weapons/
      animations/
        universal_animation_library/
    generated/
      materials/
      icons/
      portraits/
```

Recommended supporting folders:

```text
godot_client/
  scenes/
    human_mode/
    god_mode/
    shared/
  scripts/
    rendering/
    animation/
    importers/
    registries/
```


## Render Registries

The backend already has many semantic concepts.
The rendering layer should not guess them ad hoc.

So we should add stable render registries later for:

- human occupation appearance
- structure-to-scene mapping
- item-to-prop mapping
- animal-type mapping
- animation-state mapping

Examples:

- `house` -> modular house scene
- `storage_case` -> chest / storage prop scene
- `woodcutter` -> base human + woodcutter outfit set
- `fisherman` -> base human + fisherman outfit + rod prop
- `wolf` -> wolf scene
- `axe` -> hand-held weapon prop


## Human Character Pipeline

Human characters should be assembled from:

1. base humanoid mesh
2. modular outfit parts
3. material color variation
4. equipped prop attachment
5. shared animation rig / library

This is important because the project has many residents.

We should not hand-author one scene per resident.

Instead:

- resident appearance should be generated from stable resident traits
- use resident id as part of deterministic variation
- occupation should be the strongest appearance driver
- personality / tribe / wealth / gender can add secondary variation


## Resident Visual Variation Rules

Recommended variation inputs:

- `occupation`
- `sex`
- `age band`
- `tribe / settlement color`
- `wealth / status` later
- deterministic `resident_id` seed

Examples:

- `guard`
  - more armor / heavier clothing
  - weapon visible
- `farmer`
  - simpler clothing
  - hoe / crop props
- `woodcutter`
  - axe
  - earth-tone outfit
- `trader`
  - more layered outfit
  - bag or belt prop later
- `healer`
  - utility belt / satchel later


## Incarnation Pipeline

The incarnation should use the same base character system as residents.

This is important because:

- backend identity stays unified
- equipment and crafting visuals stay compatible
- possession / incarnation logic stays simpler

But the incarnation can later add richer presentation:

- camera-specific hands / weapon presentation for first-person
- more detailed equipment switching
- richer bag / chest presentation
- optional player customization layer


## Human Animation Plan

The first animation state set should be:

- `idle`
- `walk`
- `run`
- `sit`
- `attack`
- `hit_react`
- `death`
- `talk_idle`
- `work_loop`

Occupation-specific first extensions:

- `chop_wood`
- `fish_work`
- `farm_work`
- `build_work`
- `patrol_ready`

Social / talk extensions:

- `wave`
- `point`
- `warn`
- `comfort`
- `call_help`


## Animal Rendering Plan

Animals should be simpler than humans.

The first goal is:

- correct silhouette
- locomotion
- attack / danger readability
- death / hit readability

First animal state set:

- `idle`
- `walk`
- `run`
- `attack`
- `death`

Animals should later map cleanly into:

- hunting tasks
- threat escalation
- food/resource flow


## Building / Interior Strategy

Buildings should render in two layers:

### Exterior shell

Driven by:

- `Medieval Village MegaKit`

Used for:

- village layout
- shelter / house structures
- walls
- village-level structures

### Interior dressing

Driven by:

- `Fantasy Props MegaKit`

Used for:

- beds
- tables
- storage
- work props
- market clutter
- shop interiors

Important phase 1 simplification:

- interiors do not need to be fully enterable and fully decorated for every building immediately

Good first pass:

- decorate only the buildings the incarnation can enter or that the camera can meaningfully inspect
- keep far-away houses as exterior shells only

## Construction-State Rendering

Construction should not appear as:

- nothing
- then instantly a finished building

Instead, each project should support staged rendering.

Recommended first render states:

1. `planned_site`
2. `foundation`
3. `partial_frame`
4. `near_complete`
5. `finished_structure`

Recommended asset ownership:

- `planned_site`
  - simple markers, stakes, dirt patch, material piles
- `foundation`
  - Kenney `Retro Fantasy Kit` or simple generated placeholder meshes
- `partial_frame`
  - Kenney `Retro Fantasy Kit` blocky shells or partial modular walls
- `near_complete`
  - hybrid state closer to final Quaternius structure
- `finished_structure`
  - final Quaternius building scene

This gives two benefits:

- the build process becomes visible and believable
- god mode can read build progress from far away much more clearly

Important style rule:

- use Kenney mainly for intermediate build states and overview readability
- use Quaternius for completed settlement identity
- do not mix both equally as the final settlement style unless we later choose
  a more stylized hybrid look


## Weapons / Tools Rendering

Tools and weapons should use one shared prop pipeline.

These visuals should be attached to:

- resident hands
- incarnation hands / sockets
- storage containers
- crafting outputs
- ground loot later

Phase 1 should support at least:

- `axe`
- `spear`
- `club`
- `hammer`
- `hoe`
- `fishing_rod`
- `torch`

This should align directly with:

- `systems/crafting`
- `systems/inventory`
- `systems/tasks`


## Backend To Rendering Mapping

The rendering layer should consume semantic state already present in the sim.

The first stable mappings should be:

- `human occupation` -> outfit preset
- `inventory equipped item` -> hand prop
- `task kind` -> animation state
- `structure type` -> scene prefab
- `animal type` -> animal scene prefab
- `talk active` -> face / head-look / speech bubble later
- `threat` -> god-mode overlay or alert icon later

This keeps rendering driven by sim truth instead of client-only hacks.


## First Rendering Phases

## Phase 1: Asset Intake

- download and organize chosen Quaternius packs
- import into `godot_client/assets/`
- verify formats and materials in Godot
- validate humanoid rig compatibility with the animation library

## Phase 2: Exterior World

- get village environment assets rendering in `HumanMode3D.tscn`
- get the same environment rendering in `Main.tscn` god-mode view
- choose god-mode camera and shadow simplification rules

## Phase 3: Humans

- import base characters
- import outfits
- import animation library
- build one resident assembler scene/script
- support deterministic outfit variation

## Phase 4: Animals

- import animal pack
- map wolves / tigers / prey animals to backend entity types
- add simple animation state switching

## Phase 5: Tools / Weapons / Props

- import first working tool set
- attach equipped props to residents/incarnation
- add first interior props and containers

## Phase 6: Readability

- add god-mode overlays
- add selection highlights
- add talk/combat/construction indicators
- add LOD / simplification rules


## Existing Godot Integration Points

The current Godot client already has two main scene entry points:

- `godot_client/scenes/Main.tscn`
- `godot_client/scenes/HumanMode3D.tscn`

And key scripts:

- `godot_client/scripts/main.gd`
- `godot_client/scripts/human_mode_3d.gd`
- `godot_client/scripts/map_entity_view.gd`
- `godot_client/scripts/agent_view.gd`

So the rendering plan should expand those, not replace them.


## Recommended First Concrete Build Slice

The best first visual slice is:

1. import `Medieval Village MegaKit`
2. render structures in `HumanMode3D.tscn`
3. render the same structures from a god-mode orthographic camera in `Main.tscn`
4. import `Universal Base Characters`
5. add one animated resident with `Universal Animation Library`
6. add `Modular Character Outfits - Fantasy` variation for occupations
7. attach one visible crafted tool like `axe`

After that, the next strong visual slice is:

1. import `Kenney Retro Fantasy Kit`
2. map construction projects to staged visual states
3. show at least:
   - `planned_site`
   - `foundation`
   - `partial_frame`
   - `finished_structure`
4. keep `finished_structure` on the Quaternius set
5. use the earlier Kenney stages for build-progress readability

That slice would prove:

- one asset family works in both modes
- resident visuals can be occupation-aware
- the backend is ready for tool/structure presentation


## Rendering Sandbox Map

There should be a dedicated tiny backend map for visual iteration:

- `render_test_village`

Current intended shape:

- fewer than 5 structures
- fewer than 5 villagers
- centered compact land footprint
- minimal surrounding noise

Purpose:

- quick Godot rendering tests
- camera tuning
- occupation / tool visual checks
- construction-state visual experiments

Recommended usage:

- boot the backend on `render_test_village`
- use the existing Godot clients against that small world first
- validate 2D god mode and 3D human mode there before scaling up to richer maps

Current testing convenience:

- backend helper endpoint:
  - `POST /testing/render_test_village`
- this helper:
  - resets the world
  - loads `render_test_village`
  - can auto-claim the first villager for `local_player`
- current Godot hotkey:
  - `F5` in both `Main.tscn` and `HumanMode3D.tscn`


## Non-Goals For First Pass

Do not try to solve all of this immediately:

- full custom shaders for every asset class
- final lighting model
- high-end facial animation
- fully enterable and fully decorated interiors for every structure
- separate bespoke sprite art for god mode
- perfect LOD system
- full first-person hand animation polish

The first pass should focus on:

- coherent asset intake
- one shared visual family
- one world rendered in two modes
- clear mapping from backend state to visuals
