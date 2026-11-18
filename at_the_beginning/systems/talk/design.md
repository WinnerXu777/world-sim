# Talk Design

Status: partially live with full runtime plumbing and heuristic fallback output.

This module owns local spoken dialogue events, talk sessions, tiny-model prompt shaping, talk ticket routing, bark templates, follow-up effect bundles, and TTS payload generation. Talk is intentionally scoped to human mode and nearby audible interactions.

Primary files:
- `schema.py` for talk events, results, and TTS payloads
- `sessions.py` for local conversation state
- `prompt_view.py` for tiny-model prompt cases
- `routing.py` for talk ticket priorities and follow-ups
- `effects.py` for pressure, TTS, and effect bundles
- `ops.py` and `bark_templates.py` for runtime-facing helpers and fallback bark generation

Main runtime wiring:
- `at_the_beginning/runtime/control_runtime.py` captures `talk_command` events
- `at_the_beginning/runtime/talk_runtime.py` queues, resolves, and applies direct, ambient, and low-priority NPC chatter
- `at_the_beginning/map_test.py` ticks the talk runtime and exports talk feeds and TTS candidates
- Godot `Main` and `HumanMode3D` scenes and scripts expose `T`-to-talk input and nearby talk feed rendering

Owned data:
- Talk events and talk results
- Local session state
- TTS candidate payloads
- Tiny-model talk ticket metadata

The current runtime path is fully wired, but the model-facing part still uses heuristic and template fallback instead of a real tiny-model backend.
