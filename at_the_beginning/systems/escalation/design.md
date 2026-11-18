# Escalation Design

Status: live and wired into the human decision runtime.

This module owns pressure-driven routing from resident state into processing lanes. It extracts signals, scores candidates, creates queue decisions, and produces prompt-facing summaries for the human runtime.

Primary files:
- `signals.py` for signal extraction
- `scoring.py` for lane scoring
- `routing.py` for lane and batch decisions
- `queue_state.py` for escalation data containers
- `prompt_view.py` for prompt payloads and summaries
- `ops.py` for stable runtime entry points

Main runtime wiring:
- Imported directly by `at_the_beginning/runtime/human_runtime.py`
- Used to select urgent versus normal processing batches
- Feeds case metadata such as escalation summaries into the human-agent scheduler
- Interacts with `systems.goal` through review-due signals

Owned data:
- Escalation candidates
- Escalation decisions
- Lane scoring and queue summaries

This module currently bridges legacy escalation flags and newer pressure-driven routing. It is the policy layer between resident state and the tiny-model human scheduler.
