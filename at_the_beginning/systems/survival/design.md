# Survival Design

Status: live and central to basic human needs.

This module owns hunger, thirst, shelter-state updates, and survival-flavored navigation bias. It is the immediate bodily-needs layer that keeps humans alive in the sim.

Primary files:
- `hunger.py` for hunger ticking and eating
- `thirst.py` for thirst ticking and drinking
- `shelter.py` for shelter occupancy and flags
- `navigation.py` for survival-driven navigation bias

Main runtime wiring:
- Imported directly by `at_the_beginning/instincts_and_tools.py`
- Uses `systems.health` to apply damage from unmet needs
- Uses `systems.perception` to find nearby food, water, or safe movement cues

Owned data:
- Hunger and thirst deltas
- Shelter flags and occupancy sync
- Survival-navigation bias

Survival is still one of the main drivers of ordinary resident behavior. It sits below personality and goals and keeps routine need-management deterministic.
