# Schedule Design

Status: partially live.

This module is the intended ordinary-life baseline for residents. It owns daily routine defaults, time-of-day block selection, current routine state, and probabilistic routine choice shaped first by occupation and then by personality.

Primary files:
- `catalog.py` for routine ontology and deterministic defaults
- `schema.py` for schedule profiles and routine records
- `lifecycle.py` for schedule state persistence
- `resolver.py` for time-block routing, weighted routine scoring, and probabilistic selection
- `navigation.py` for low-strength schedule fallback movement bias
- `prompt_view.py` and `ops.py` for runtime-facing summaries and helpers

Main runtime wiring:
- Ensured on residents through `runtime/resident_store.py`
- Exposed in resident-facing prompt and export payloads
- Provides a low-strength fallback navigation bias in the main sim loop
- Sits below survival, urgent reactions, and active plans
- Prefers `systems/occupation` block routines when a resident occupation is present

Owned data:
- `schedule_profile`
- `schedule_state`
- current routine records

The current integration is intentionally conservative. Candidate generation is deterministic in structure, final routine choice uses resident-specific stability and novelty bias, and the live movement effect is only a fallback bias rather than a full task executor.
