# Inventory Design

Status: live as a separate event-driven store, with runtime wiring for starter
loadouts, house-backed resident storage, inventory-driven crafting, and a first
inventory-backed construction slice.

This module owns items, stack rules, owner inventories, container inventories, equipment slots, currency helpers, and transfer/drop/loot operations. Inventory is intentionally separate from `h_tensor`.

Primary files:
- `schema.py` for item and container definitions
- `store.py` for inventory state and identity helpers
- `ops.py` for add/remove/transfer/drop/loot
- `equipment.py` for equip state
- `currency.py` for money helpers
- `containers.py` and `queries.py` for storage and prompt/export helpers

Main runtime wiring:
- `at_the_beginning/map_test.py` owns the engine inventory store
- Genesis/runtime seeding gives humans starter inventories and storage cases
- Ordinary residents now use small carry-limited loadouts
- Completed `personal_shelter` projects now unlock `house_storage` as the
  resident's bulk storage anchor
- Occupation work, baseline crafting, and the first live construction slice now
  consume/produce real item stacks through this module
- Inventory endpoints and payload exports are already exposed through the API
- Godot inventory UI and quick actions are wired for basic equip/loot/store loops

Owned data:
- Inventory records for owners and containers
- Equipment state
- Currency balances and stack data

The current design deliberately keeps resident inventories simple:

- small personal carry
- house storage only if housed
- no free bulk storage for unhoused residents

That leaves room for the human-mode incarnation to grow into a richer
manual-control inventory loop later without forcing the same complexity onto
every NPC.
