# Inventory Future

Current limitations:
- Resident inventories are intentionally shallow
- Item variety is still small
- Player/incarnation inventory is not yet in the richer bag/chest/manual UX
- Ownership, theft, corpse loot, and long-term world persistence are still basic

Nuances:
- Inventory should stay event-driven and separate from high-frequency tensor state
- Only small derived flags should flow back into fast sim state if needed later
- Residents now use a deliberate split:
  small personal carry plus house storage only if they have completed shelter

Suggested next elaborations:
- Add corpse loot, theft, trading, and storage ownership rules
- Deepen player-facing equipment, consumables, and hotbar flows
- Expand real material-stack use across more occupation chains and public/shared construction
- Add tighter hooks into `systems/interaction` once that module becomes real
