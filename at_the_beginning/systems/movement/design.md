# Movement Design

Status: live and wired into both manual control and autonomous motion.

This module owns manual-control movement helpers, target-step resolution, world clamping, and autonomous navigation bias application.

Primary files:
- `manual.py` for player/manual-control motion
- `resolver.py` for step resolution and world clamping
- `sim.py` for autonomous navigation bias
- `ops.py` as the stable combined surface

Main runtime wiring:
- Imported directly by `at_the_beginning/instincts_and_tools.py`
- Manual movement flows through `apply_manual_control_movement()`
- Autonomous motion uses `apply_navigation_bias()` and step resolution
- Depends on survival/perception systems for directional bias inputs

Owned data:
- Manual movement context
- Step resolution helpers
- Navigation bias application

Movement is intentionally thin and deterministic. Other modules decide why an agent should move; this module decides how the move is applied within world bounds.
