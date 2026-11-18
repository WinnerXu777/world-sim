# Polish Backlog

This file is for non-blocking polish work that we want to defer until the core game loop and major systems are in place.

## Human Mode 3D

- Playtest the new 3D human-mode scene end-to-end in Godot and fix any runtime scene/script issues.
- Improve first-person camera feel:
  - head bob
  - better pitch/yaw limits
  - smoother follow and acceleration
  - optional crosshair
- Improve third-person camera feel:
  - collision-aware camera distance
  - shoulder offset / over-the-shoulder option
  - better follow smoothing
- Hide or adjust avatar/body rendering correctly in first-person view.
- Add better lighting, sky, atmosphere, and depth cues for human mode.
- Replace primitive placeholder meshes with better temporary art or reusable low-poly assets.
- Add simple terrain height variation on the client side while keeping backend truth 2D.

## God Mode / Human Mode Switching

- Make switching between god mode and human mode feel seamless.
- Preserve camera context more gracefully when switching back and forth.
- Add clearer UI indicators for current mode and available controls.
- Add an explicit on-screen hint for `F1` / `Tab` mode switching.
- Support switching into 3D human mode directly from a currently controlled target.

## Human-View Streaming

- Only resend changed chunks instead of full chunk upserts every human-view poll.
- Add chunk/actor interpolation and fade-in to reduce visible popping.
- Add client-side culling / LOD for distant props and actors.
- Bias chunk preloading more intelligently from camera direction and movement velocity.
- Add human-mode visibility rules later:
  - fog-of-war
  - occlusion-aware visibility
  - local knowledge instead of omniscient world knowledge

## Human Interaction Feel

- Add better first-person / third-person interaction targeting.
- Add raycast-based interact / attack selection in 3D mode.
- Improve feedback for:
  - attack hits
  - interactable targets
  - possession/control status
  - pending actions
- Add better local response presentation for urgent reactions:
  - flinch
  - aggro turn
  - flee start
  - ally alert cues

## Presentation / UX

- Improve HUD layout for human mode so it feels less like a debug panel.
- Add optional minimap or local compass for embodied play.
- Add audio hooks later for:
  - local action feedback
  - spatial events
  - future TTS / voice reactions
- Add accessibility settings for camera sensitivity, FOV, and motion intensity.

## Technical Cleanup

- Revisit the 3D human-mode scene after the full game loop is stable.
- Separate temporary prototype rendering code from long-term client rendering architecture.
- Add dedicated tests or debug tooling for human-view chunk streaming.
- Revisit the backend/client contract once first-person interaction and visibility systems are finalized.

## Inventory / Container Interaction

- Replace the current debug-style inventory text with a proper panel layout for player inventory, main-hand slot, money, and nearby container contents.
- Add explicit container focus and selection feedback in both 2D and 3D modes so players can tell which storage case or chest they are looting.
- Add 3D interaction targeting for storage cases and other future interactable props instead of relying on the current lightweight focus payload.
- Improve item presentation with icons, stack counts, weapon tags, rarity/value hints, and better readable labels.
- Add drag/drop or click-to-transfer flows later for player inventory management instead of only `Q`, `L`, `K`, and `P` debug-style shortcuts.
- Add quick-equip, quick-loot, and quick-store affordances for embodied play so inventory actions feel responsive in human mode.
- Surface money, equipped weapon, and simple resident loadout summaries more cleanly in the HUD and selection UI.
- Add audio/animation feedback for equip, loot, store, and container open/close actions.
- Add safer edge-case handling and UI feedback for failed transfers, full containers, missing items, and stale focus targets.
- Revisit the inventory contract once richer `systems/interaction` hooks and the incarnation-specific inventory flow are in place.
