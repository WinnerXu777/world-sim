# Nature Design

Status: live and wired into environmental simulation.

This module owns ecology rebalance, resource regrowth, water cycling, weather state, season tracking, environmental hazards, and discrete disasters such as floods or earthquakes.

Primary files:
- `weather.py` for nature-cycle state and modifiers
- `ecology.py` for regrowth and animal-population helpers
- `hazards.py` for fire and lava damage ticks
- `disasters.py` for larger world events
- `ops.py` as the stable surface

Main runtime wiring:
- Imported directly by `at_the_beginning/instincts_and_tools.py`
- Uses `systems.health` to apply environmental damage
- Feeds world-level state changes that influence survival and map behavior

Owned data:
- Nature-cycle state
- Disaster helpers
- Ecology/regrowth helpers

Nature is currently the environmental mutation layer for the world sim. It changes what the world is doing around agents rather than deciding agent intent directly.
