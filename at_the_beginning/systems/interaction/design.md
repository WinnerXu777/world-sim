# Interaction Design

Status: scaffold only.

This module is the reserved home for generalized interaction semantics such as `use`, `pickup`, `drop`, `loot`, `open`, `harvest`, `enter`, and `inspect`.

Primary files:
- `manual.py` scaffold
- `sim.py` scaffold
- `resolver.py` scaffold

Main runtime wiring:
- There is no meaningful runtime integration yet
- Current interaction behavior is still spread across control runtime, inventory endpoints, talk runtime, and ad hoc map/entity logic

Owned data:
- No stable owned state yet

The module exists to become the clean bridge between player/NPC intent and deterministic interaction execution, but it has intentionally not been centralized yet.
