# Planning Future

Current limitations:
- `executor.py` intentionally does not yet mutate the sim for most plan ops
- Plan progress tracking is still shallow
- Plans are stored and compiled more than they are fully executed

Nuances:
- This module is the main safety boundary for resident reasoning output, so validation should stay strict
- Plan execution should remain deterministic and tool-like rather than free-form model behavior

Suggested next elaborations:
- Wire approved plan ops into actual inventory, movement, interaction, and social execution paths
- Add plan monitoring, interruption, and replanning support
- Expand plan catalogs as the reasoning queue becomes real
- Improve compiled-step status reporting for debugging and UX
