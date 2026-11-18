# Talk Future

Current limitations:
- Tiny-model integration is not wired yet; current talk output is heuristic and template based
- TTS is designed but not yet implemented as a live asynchronous queue
- 3D direct-target selection is still basic

Nuances:
- Reflex remains higher priority than talk, and talk appraisal can escalate into urgent reactions or later reasoning
- Only player-audible local talk should be generated; this is intentionally not a whole-population dialogue simulator

Suggested next elaborations:
- Attach real `talk_reply` and `ambient_npc_talk` tiny-model modes
- Add asynchronous TTS with direct-talk guarantees and ambient voice budgets
- Improve direct-target acquisition in human mode, especially 3D
- Feed important speech into memory, goals, and reasoning with clearer structured follow-ups
