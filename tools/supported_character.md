# Supported character assembly

The first assembled character is the female peasant. It combines the installed Quaternius female base with the peasant outfit, using one skeleton. The outfit contains four garment meshes and no head; it is not a complete body. The previous primitive head attachment is bypassed for this generated variant.

The builder checks all 65 imported bone names, parents, rest transforms and inverse skin bind poses before moving garment meshes to the base skeleton. It preserves mesh transforms and skin resources. It does not compensate for incompatible rigs with bone offsets. The imported female pair matches; the inspected male pair does not have identical rest transforms and remains outside this assembled variant.

Base body triangles under clothing are removed offline. A triangle is retained when its mean total influence from head, neck, forearm, hand and finger bones is at least 0.5. The original vertices, weights, normals and surface formats remain intact. Eyes and eyebrows are retained separately. This coverage policy is specific to the peasant outfit, not a general clothing system. The source base-body geometry otherwise protrudes through the peasant torso and trousers.

The generated scene, source hashes and coverage policy are under `godot_client/scenes/characters/generated/`. Source coordinates are metres with Y up after import; the source face points toward positive Z. The existing actor facing pivot rotates by PI. Skeleton rest/bind records are captured in `.tmp/implementation_0905/character_asset_audit.json`. No embedded animation player is retained; the current actor animation player still owns playback. Runtime animation import/correction paths are not replaced by this body assembly.

Rebuild from the repository root using the installed asset folders:

```powershell
godot --headless --path godot_client --log-file C:/Users/Rita/Desktop/world_simulator/.tmp/character_build.log --script res://tests/build_supported_character.gd
godot --headless --path godot_client --log-file C:/Users/Rita/Desktop/world_simulator/.tmp/character_validation.log --script res://tests/supported_character_validation.gd
```

The base kit's bundled `License_Standard.txt` identifies CC0 1.0 and Quaternius. Keep provenance for each required kit in the eventual clean-checkout asset manifest. Hair, wrist seams, male/ranger compatibility, cached animation normalization, AnimationTree ownership and recorded transition validation remain unfinished. The fresh normal gameplay capture validates visual improvement in the inspected poses, not all animations.

## Cached animations

The female peasant now loads baked `FemalePeasant_mixamo.res` and `FemalePeasant_locomotion.res` from the generated directory. These preserve the existing normalized clips: 22 Mixamo and 45 UAL1 clips. The runtime checks source selection, target skeleton path and a hash of bone names/parents/rest transforms before using a cache; unsupported variants retain the existing importer. Regenerate after changing source clips or normalization code. `use_cached_animation_resources=false` explicitly exercises the reference importer.

```powershell
godot --headless --path godot_client --log-file C:/Users/Rita/Desktop/world_simulator/.tmp/animation_bake.log --script res://tests/bake_supported_animations.gd
godot --headless --path godot_client --log-file C:/Users/Rita/Desktop/world_simulator/.tmp/animation_cache_validation.log --script res://tests/animation_cache_validation.gd
godot --headless --path godot_client --log-file C:/Users/Rita/Desktop/world_simulator/.tmp/animation_playback_validation.log --script res://tests/animation_playback_validation.gd
```

`animations.json` records clip names, lengths, loops and track counts. The bake rejects unresolved target nodes/bones. Parity checks compare clip metadata/bindings and 18,245 sampled position/rotation/scale values across 67 clips against the reference importer. This proves cache equivalence; it does not prove the existing retargeted clips are anatomically correct. Playback validation also checks that the looping idle advances and repeated idle/walk requests do not restart the clip. Idle no longer pauses at zero, and normal transitions no longer call stop before requesting a blend. A single AnimationTree, action priority tests, full recorded transition coverage, and speed matching remain required.

## Gameplay animation ownership

Normal gameplay now enables `use_animation_graph` for this supported rig. Its AnimationTree state machine is the sole pose writer; AnimationPlayer supplies cached resources. Unsupported rigs and explicit animation QA retain the reference playback path. `res://tests/animation_graph_validation.gd` verifies ownership and interruption/hold behavior. Initial action priority is talk, attack, pain, get-up, fall, then terminal death. A downed pose persists until explicit get-up, and death cannot enter get-up. Repeated requests for an already active action are ignored while locked.

This is an incremental replacement: legacy timer helpers still request states, combat phases and phase-sensitive hit interruption remain unfinished, and locomotion still needs a blend space driven by actual speed. Use fresh temporal recordings to validate those changes; a passing state test does not establish smooth or anatomically correct animation.
# Measured locomotion update

The supported gameplay rig now blends Idle/Walk/Sprint in a synchronized one-dimensional AnimationTree blend space. Blend coordinates are 0, 1 and 1.5, driven by measured horizontal speed divided by the shared contract's walk speed. Speeds below 0.15 use idle. Controlled actors use post-collision render velocity; NPCs use presentation displacement speed. Held keys, stale movement hints and direction holds no longer override stopped displacement on this path. Existing action locks still take precedence. Unsupported rigs and explicit animation QA retain their prior animation path.

This is velocity-based blend selection, not completed gait calibration: reference clip stride lengths, playback-rate matching, movement scale and full temporal recordings remain required. The current contract still uses the inherited 20-unit/s walking speed.
