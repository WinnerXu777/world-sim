# Control Design

Status: live as the semantic action interpretation layer for incarnation
control, with `runtime/control_runtime.py` remaining the authoritative session
owner.

This module sits between raw client input and backend execution. Godot still
owns keybinds, mouse behavior, cursor capture, and camera feel. The control
module owns semantic action normalization, context-aware action coercion, and
click resolution.

Primary files:
- `schema.py` for semantic action, context, and view-style normalization
- `contexts.py` for allowed actions per control context
- `mode_manager.py` for stable context/view-style state
- `click_resolver.py` for target-aware click interpretation
- `router.py` for normalized control-event payloads and command-state updates
- `ops.py` for the public runtime-facing API

Main runtime wiring:
- `runtime/control_runtime.py` now delegates event normalization and command
  state mutation to this module
- manual movement/combat readers can now consume
  `pending_semantic_action` alongside the legacy `pending_action`
- status/control payloads now expose `control_context`, `view_style`, and
  semantic action fields without breaking the older payload shape

Owned concepts:
- semantic action vocabulary like `select_target`, `attack_target`,
  `interact_target`, `work_on_target`, and `talk_command`
- control contexts like `god_context`, `human_fps`, `human_tps`,
  `talk_context`, and `inventory_context`
- normalized view style
- tag-aware click resolution and default coercion rules

Current scope:
- keep the current Godot payloads working
- preserve legacy `pending_action` compatibility
- add semantic fields so newer systems can read a clearer action contract
- prepare the ground for future `switch_mode`, `switch_view`, and richer
  manual embodied action routing
