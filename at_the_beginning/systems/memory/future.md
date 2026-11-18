# Memory Future

Current limitations:
- Retrieval quality still depends on how much meaningful resident memory has been accumulated
- Embedding and index rebuild cost still matter for larger late-game worlds
- Some event classes are still only lightly represented in the graph

Nuances:
- Memory retention and pruning already matter here, especially for dead residents and low-salience episodic events
- This module must stay derived from resident state instead of becoming an independent source of truth

Suggested next elaborations:
- Add richer event schemas for social conflict, trade, territory, and talk
- Improve batching and incremental indexing for long runs
- Add better archive and compaction strategies for old or dead residents
- Tighten integration with talk, planning, and future social systems
