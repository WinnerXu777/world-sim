# Control Future

Current limitations:
- Godot still sends mostly legacy click actions like `attack`, `interact`,
  `select`, and `move`
- the client does not yet send explicit semantic contexts or view styles, so
  runtime state is inferred from current target/control state
- `switch_mode` and `switch_view` are normalized if sent, but not yet used as
  a full gameplay mode-routing contract
- click resolution is currently target-kind plus name-heuristic based rather
  than true map/entity tag driven

Important nuances:
- `pending_action` is intentionally still present because several runtime and
  UI paths still read it directly
- semantic control state is additive for now, not a hard cut-over
- `runtime/control_runtime.py` still owns claim/release/session authority;
  this module is not a second runtime

Suggested next elaborations:
- make Godot send explicit `context`, `view_style`, and future `modifier_mode`
  fields
- route `Q + left click` through true `work_on_target` / `attack_target`
  intent instead of legacy `attack` overloading
- replace name-heuristic target tagging with authoritative entity tags from the
  map/runtime export
- add richer player action payloads like `craft_request`, `build_request`,
  `pickup_target`, and `open_container`
- surface semantic action debugging in the client HUD once the control loop is
  stable
