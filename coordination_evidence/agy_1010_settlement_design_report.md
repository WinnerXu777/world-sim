# Coordination Evidence: 1010 Settlement Design Report

**Date:** 2026-10-10
**Track:** Model Plane / Orchestrator

## Summary
The design for the R6.4 Settlement object and bounded growth has been drafted in `1010_settlement_gap.md`. This design aligns with the user's constraints: it focuses strictly on actionable technical architecture and introduces no production code edits at this stage.

## Key Technical Decisions
1. **Stable IDs & Registry:** Settlements will use `s_NNNNNN` IDs stored in a global `SettlementRegistry`. This ensures they survive chunk re-basing and unloading.
2. **Window Boundaries:** The settlement object itself is always loaded. Its physical buildings are managed by the `structure_store` (R3.10) when out of bounds. Growth mechanics for dormant settlements will rely on closed-form statistical catch-up upon integration, avoiding costly off-screen ticking.
3. **World Format 5:** Enabling the `EDEN_SETTLEMENT` flag and saving a world with settlements will bump the save format to 5. Strict schema validation and refusal texts are defined to prevent corruption on mismatched loads.
4. **Living Construction:** Blueprint entities will be used. Residents build them over time via `build_structure`. Terraform is handled deterministically by the `settle_site` verb clearing map objects locally.

## Handoff & Next Steps
This design is ready for review. Independent implementation can begin on the minimal slice (flag `EDEN_SETTLEMENT`, the registry, the `settle_site` action, and the save format bump) once approved. 

No commits have been pushed. No defaults have been changed. Strict goldens remain untouched.

*See `1010_settlement_gap.md` for full technical specifications.*
