# Humanizer Migration Notes

## Why move away from the current outfit-body path

Right now the live incarnation path is effectively using a full outfit/body scene as the character body. That helped us get something moving again, but it also makes a few problems more likely:

- awkward arm posture in walk/run
- weak face identity
- harder body customization later
- animation tuning depends too much on which outfit scene is acting as the body

The cleaner long-term path is:

- one canonical base body
- eyes / eyebrows / eyelashes / hair
- clothes layered onto that body
- one stable runtime character scene

That is what the Humanizer plugin in this repo is built for.

## What Humanizer already provides in this repo

The plugin already includes:

- a `Humanizer` resource builder
- `HumanConfig` for body, colors, and equipment
- a baked `CharacterBody3D` generation path
- default eyes / eyebrows / eyelashes / hair assets
- a built-in animation tree for retargeted humanoid rigs

Useful references:

- [authoring.tscn](/c:/Users/Rita/Desktop/world_simulator/godot_client/addons/humanizer/scenes/authoring.tscn)
- [CharacterBody3D.tscn](/c:/Users/Rita/Desktop/world_simulator/godot_client/addons/humanizer/scenes/tests/CharacterBody3D.tscn)
- [humanizer.gd](/c:/Users/Rita/Desktop/world_simulator/godot_client/addons/humanizer/scripts/core/humanizer.gd)
- [human_config.gd](/c:/Users/Rita/Desktop/world_simulator/godot_client/addons/humanizer/scripts/resources/human_config.gd)

## New prototype scene

A standalone sandbox scene was added for testing a proper Humanizer-built character:

- [HumanizerIncarnationPrototype.tscn](/c:/Users/Rita/Desktop/world_simulator/godot_client/scenes/characters/HumanizerIncarnationPrototype.tscn)
- [humanizer_incarnation_prototype.gd](/c:/Users/Rita/Desktop/world_simulator/godot_client/scripts/humanizer_incarnation_prototype.gd)

This scene is intentionally separate from the live incarnation controller. It lets us answer one question first:

`Does a Humanizer-built full body look healthier than the current outfit-body path before gameplay integration?`

## What to test in the prototype

Open the prototype scene and check:

- standing pose
- arm posture
- body proportions
- face / eyes / hair appearance
- whether the overall body feels more like a real character than the current outfit-body incarnation

The current prototype uses:

- `DefaultBody` with a configurable body profile
- low-poly eyes
- eyebrows
- eyelashes
- hair
- simple shirt / pants / shoes

## Recommended migration order

1. Validate the prototype body in isolation.
2. Pick one canonical player/incarnation body profile and outfit baseline.
3. Bake or stabilize that body as the new incarnation visual source.
4. Only then wire it into [IncarnationHuman.tscn](/c:/Users/Rita/Desktop/world_simulator/godot_client/scenes/characters/IncarnationHuman.tscn).
5. Keep the backend and memtensor interaction stack unchanged.

## Important boundary

This migration should change the `render/body pipeline`, not the backend simulation design.

Keep as-is:

- memtensor / backend authority
- manual control intent flow
- combat / threat / retaliation logic
- backend-to-render smoothing work

Change next:

- body construction
- face / hair / clothing composition
- the visual source used by the incarnation controller

## Immediate next recommendation

Use the prototype scene to pick:

- one body profile
- one hair option
- one simple outfit set

Once that looks better than the current outfit-body incarnation, migrate the live incarnation to a Humanizer-built body one step at a time.
