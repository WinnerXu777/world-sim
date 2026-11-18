# Social Design

Status: live for grouping, mating, and simple social-state helpers.

This module owns pairwise relation building, social navigation bias, reproduction logic, reproduction cooldowns, and simple emotional recovery helpers. It also re-exports infection ticking for compatibility.

Primary files:
- `grouping.py` for relation and navigation helpers
- `mating.py` for reproduction and seek restrictions
- `ops.py` for the stable surface
- `infection.py` as a compatibility re-export

Main runtime wiring:
- Imported directly by `at_the_beginning/instincts_and_tools.py`
- Influences navigation bias and reproduction in the main sim loop
- Reproduction outcomes also feed resident-memory updates through higher-level runtime hooks

Owned data:
- Pairwise relation helpers
- Reproduction logic and cooldown decay
- Social navigation bias

Social is currently a lightweight low-level domain module, not yet the full relationship or tribe system. It provides immediate social mechanics rather than long-horizon social strategy.
