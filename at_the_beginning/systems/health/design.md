# Health Design

Status: live and central to damage, healing, infection, and structure durability.

This module owns human and entity damage, healing, infection ticks, recovery ticks, critical-state updates, and structure durability changes.

Primary files:
- `damage.py` for core damage and heal helpers
- `infection.py` and `recovery.py` for ongoing status changes
- `status.py` for critical-state updates
- `durability.py` for structure durability
- `effects.py` for area and blessing/plague style effects

Main runtime wiring:
- Imported directly by `at_the_beginning/instincts_and_tools.py`
- Called by `systems.combat`, `systems.survival`, `systems.nature`, and `systems.construction`
- Used as the authoritative mutation layer for health-like state changes

Owned data:
- Health deltas
- Durability deltas
- Infection and recovery effects
- Critical-state classification

Health is currently a shared mutation module rather than a prompt-facing reasoning system. Other modules decide when harm or recovery should happen; this module applies it.
