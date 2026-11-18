# Combat Design

Status: live and wired into the core simulation loop.

This module owns short-horizon violence and hunting behavior for humans. It provides manual attack intent collection, autonomous attack and hunt intent collection, target range checks, and the final resolution that turns intents into damage.

Primary files:
- `manual.py` for player-controlled attack intents
- `sim.py` for autonomous attack and hunt intents
- `resolver.py` for target checks and damage application
- `hunting.py` and `queries.py` for huntable target selection

Main runtime wiring:
- Imported directly by `at_the_beginning/instincts_and_tools.py`
- Manual control flows through `collect_manual_attack_intents()`
- Autonomous combat and hunting flow through `collect_sim_attack_intents()` and `collect_sim_hunt_intents()`
- Final damage is applied through `resolve_human_attack_intents()`, which delegates into `systems.health`

Owned data:
- Combat intents
- Huntable-target rules
- Range and target resolution helpers

This module currently assumes close-range, sim-driven combat and acts as the authoritative bridge between intent gathering and health damage.
