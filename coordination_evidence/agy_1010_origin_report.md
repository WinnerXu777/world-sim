# AGY 1010 Origin Report

## Actual Changed Files
- `at_the_beginning/api/chunk_routes.py` (fixed test compatibility with `getattr(service, 'pinned', None)` and updated `_descriptor` to attach origin metadata to all fully covered chunks mapped to the pinned area)
- `tests/test_harness_chunk_routes.py` (rewrote `PlacementOriginTests` to cover partial chunk semantics, correct multi-chunk area setup, large coordinates, and origin discoverability)

## Implementation Status
- Old test results failed and I have not rerun tests natively as requested (implementation and validation owed, rather than DONE). The exact validation command below is to be executed by the orchestrator/Codex.

## Exact Targeted Validation Commands
```bash
.venv/Scripts/python.exe -m unittest discover -s tests -p test_harness_chunk_routes.py
```

## Contract Fields and Units
- **New Field:** `placement_origin_absolute_units`
- **Data Type:** Array of two integers `[x, y]`
- **Units:** Absolute backend units (where `UNITS_PER_TILE = 8`).
- **Semantics:** Specifies the absolute world coordinates of the top-left placement origin of the authored map. Negative and large integer coordinates are preserved accurately as requested, without conversion to floats.
- **Discoverability & Deduplication:** The `placement_origin_absolute_units` field is attached to *all* fully pinned chunk descriptors covered by the `PinnedArea` to ensure it is discoverable from any window query around the player. It is the client's responsibility to deduplicate authored-map rendering using the stable map ID provided in the `pinned_map` field.
- **Partial Pinned Handling:** Chunks that only partially overlap a pinned area are generated procedurally as normal. They do not receive the `pinned_map` or `placement_origin_absolute_units` fields. Procedural and pending descriptors omit this metadata, preserving existing hash and document identity behaviors.

## Outstanding Gaps
- **GAP:** The map file itself (e.g., `starter_village.json`) does not specify its own internal `origin` field. The placement coordinates provided are derived strictly from the authoritative `PinnedArea` (`x0` and `y0`), representing placement bounds. Any internal layout registration origin remains unspecified in the map assets.

## Orchestrator verification

Codex executed the stated focused suite after repair with normal Windows subprocess access: **17 tests, 5.455 seconds, OK**. Under sandboxed subprocess access, only the unchanged real worker-pool case returned 503; the escalated run verifies that case without weakening its assertion. This establishes the backend descriptor change's targeted tests, not client consumption, full suite, or R5.1 visual acceptance.
