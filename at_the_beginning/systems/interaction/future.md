# Interaction Future

Current limitations:
- Fully scaffolded with no real resolver implementation yet
- Interaction logic is still distributed across other systems
- Human-mode interaction UX currently bypasses this module

Nuances:
- This module should become the semantic home for interaction verbs, not the storage layer for inventory, talk, or map entities
- It is a likely future dependency of inventory, talk, containers, and richer human-mode controls

Suggested next elaborations:
- Centralize pickup, loot, store, inspect, and open behaviors here
- Route manual clicks and future NPC interaction intents through shared verbs
- Add permission, reachability, and target-resolution logic
- Use this module to reduce ad hoc interaction code in runtimes and client endpoints
