# Humanizer Live Animation Issue

## Current Summary

The Humanizer integration is now far enough along that the live character can:

- spawn correctly in the gameplay scene
- use the existing incarnation animation controller
- play walk / run / bash / fall / get-up clips

The remaining blocker is the **arm chain on the Humanizer body**.

## Two Humanizer Paths We Tested

### 1. Previous live path: `mixamo` Humanizer rig

This version was closer to the animation assets structurally.

What was good:

- arms were much less crossed
- animations rendered more cleanly
- walk / run / one-shots were easier to bind

What was bad:

- the body no longer looked like the normal Humanizer character from the prototype scene
- the silhouette looked distorted in-game
- it felt like we were warping the Humanizer body to fit the animation path

Important conclusion:

- the distortion was **not mainly caused by body morph tuning**
- after backing out the aggressive body-shape edits, the distortion still pointed back to the `mixamo` live rig path itself

### 2. Current live path: `default-RETARGETED` Humanizer rig

This is the path currently enabled in:

- `godot_client/scripts/human_mode_3d.gd`
- `godot_client/scripts/incarnation_human.gd`

What is good:

- the body looks much closer to the normal Humanizer prototype scene
- proportions are more believable
- the character reads more like a real Humanizer-built person

What is bad:

- the arms cross inward or behind the body
- the rest of the animation can look mostly correct while the arm chain is clearly wrong

So the situation right now is:

- **previous path**: animation compatibility better, body shape worse
- **current path**: body shape better, arm animation worse

## Why The Arms Are Crossing

The strongest current diagnosis is:

- this is **not mainly a bad Mixamo asset problem**
- this is **not mainly a bad UAL asset problem**
- this is **not mainly a Humanizer body-shape problem**

It is most likely a **Humanizer default-rig arm-chain compatibility problem**.

Reason:

- both Mixamo one-shots and UAL locomotion showed the same arm failure pattern
- torso and legs can look mostly acceptable
- the body itself looks healthier on `default-RETARGETED`
- the failure stays concentrated in the shoulders / upper arms / forearms

That points to the **target rig basis**, especially the default Humanizer arm chain.

The likely structural mismatch is that the source clips behave more like a simpler humanoid arm chain, while the default Humanizer rig has extra stages in the arm:

- `clavicle.L`
- `LeftShoulder`
- `LeftUpperArm`
- `upperarm02.L`
- `LeftLowerArm`
- `lowerarm02.L`
- `LeftHand`

and the equivalent chain on the right side.

So the live controller is no longer failing to play animation. It is failing to distribute the source arm motion across the Humanizer arm chain in a clean way.

## What We Tried

### A. Body-shape tuning

We tried:

- making the whole character larger
- thinning arms / thighs / calves
- reducing weight / muscle values

Result:

- this changed appearance
- but it did **not** solve the root arm problem
- once reverted, the arm issue still remained

Conclusion:

- body morph tuning was a distraction, not the real fix

### B. Humanizer `mixamo` rig live path

We switched the live Humanizer rig to a `mixamo`-family path.

Result:

- arms improved
- body became distorted and no longer matched the normal Humanizer look

Conclusion:

- better animation compatibility, worse body fidelity

### C. Rest-pose correction on the generated Humanizer skeleton

We tried applying shoulder / arm corrections to the generated Humanizer rest pose.

Result:

- this could create bone / skin misalignment
- at one point the mesh looked exploded or badly offset

Conclusion:

- rewriting the live rest pose is risky on this path

### D. Per-frame arm pose correction

We tried code-side correction on:

- `clavicle.L` / `clavicle.R`
- `LeftUpperArm` / `RightUpperArm`

Result:

- sometimes slightly better
- sometimes arms spun rapidly because the correction compounded
- after stabilizing the cache, it was still not a true solution

Conclusion:

- useful as a probe
- not a reliable final fix

### E. Shoulder / clavicle remap experiments

We tried remapping source shoulder animation onto different Humanizer shoulder-chain bones.

Result:

- one version raised the arms unnaturally
- another folded them in a different wrong way

Conclusion:

- simple remap swaps were too crude

### F. Extra arm-segment duplication / weighted follow

We then tried a more structural fix in:

- `godot_client/scripts/incarnation_human.gd`
- `_duplicate_default_humanizer_arm_segment_tracks(...)`

The idea was:

- keep the normal named-bone mapping
- then feed the extra Humanizer arm bones (`upperarm02.*`, `lowerarm02.*`) from the source upper/lower arm tracks

Variants tried:

- full duplication
- reduced weighted follow
- different follow weights
- current direction: splitting source arm rotation more intentionally across both arm segments

Result:

- this is the most promising code-side direction so far
- but it is still not solved yet

## Current Best Understanding

The live Humanizer problem is now very specifically:

- `mixamo` rig path fixes animation better but distorts the body
- `default-RETARGETED` preserves the body but exposes the arm-chain mismatch

So the real unresolved issue is:

- **how to make the default Humanizer arm chain consume external humanoid animation correctly**

## Recommended Direction

### Short-term

Keep working on the `default-RETARGETED` Humanizer path, because it preserves the body shape better.

The best remaining code-side target is:

- structural arm-chain handling
- not more body morph tuning
- not more random per-frame shoulder hacks

### Medium-term

The best durable fix is still:

- retarget a small clean animation set specifically for the Humanizer default rig

That means at least:

- walk
- run
- bash
- fall
- get-up

So the animation assets match the Humanizer rig basis directly, instead of forcing runtime code to guess how to distribute arm motion.

## Current Bottom Line

We are no longer blocked by:

- body spawning
- animation playback
- axis problems
- scale problems

We are blocked by one narrower but stubborn problem:

- **the Humanizer default rig arm chain is still not consuming the source animations correctly**

That is why the current body looks better than before, but the arms still cross.
