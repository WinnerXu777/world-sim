# Crafting Future

Current limitations:
- Baseline execution is conservative and only covers occupation provisioning, not full resident profession work
- Intermediate components are crafted through a lightweight cache rather than a full material-in-inventory workflow
- There is no player crafting UI yet
- Station usage is declarative only
- Multi-step production chains, repair, and recycling are not implemented
- There is no live concept of `plan_requested_recipes` yet

Nuances:
- Crafting should stay the shared recipe truth layer, not become a giant world executor
- `construction` should keep ownership of placed structures while `crafting` owns tools and components
- Occupation should express crafting affinity and tool need, but actual procurement and execution should later flow through schedule, goals, planning, inventory, and interaction
- Not every resident should start from zero every time; inheritance, storage access, and borrowing should remain valid ways to satisfy tool requirements
- Baseline occupation tools should be cheap, deterministic provisioning work once survival pressure is clear
- Strategic recipes such as revenge weapons or ambush supplies should come from plans rather than automatic occupation logic
- The current baseline loop gathers one unit at a time and is intentionally simple so it does not overpower survival, urgent response, or later task systems

Suggested next elaborations:
- Add player-side manual crafting actions and UI
- Replace the temporary `material_cache` with fuller inventory/container-aware material handling when resident loadouts become richer
- Add plan-emitted strategic recipe requests and route them into crafting jobs
- Add station reservation, repair, recycling, and later capital equipment such as boats and carts
- Expand baseline execution into fuller profession workflows once tasks, ownership, and economy are deeper
