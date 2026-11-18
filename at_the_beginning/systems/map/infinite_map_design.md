# Infinite Map Chunking Design

## Goal

Turn the current finite map into a chunked world where:

- the backend owns a conceptually unbounded world
- Godot only loads the camera-visible region plus a safety margin
- new explored areas are generated or loaded as chunk upserts
- far-away chunks can be unloaded from the client

This belongs in `systems/map/` because it is a map-domain concern, not a rendering-only trick.

## Design Logic

Follow the same reusable pattern used elsewhere in the repo:

- semantic tools express intent
- generic chunk/window math stays reusable and engine-agnostic
- camera/client adapters translate local engine details into world-space requests
- map generation and streaming remain backend-authoritative

Do **not** hardcode a one-off Godot-only infinite map path.

## Terrain Continuity Rule

New chunks should not be generated as isolated random biome bags.

- sample the neighboring frontier terrain first
- bias new terrain toward compatible nearby biomes
- let lakes transition toward beach/grass
- let forests transition toward grass
- let mountains transition toward barren/grass
- allow variation, but avoid abrupt edge seams caused by pure random choice

The reusable place for that logic is `chunk_generation.py`, so both:

- current bounded edge expansion
- future true chunk generation

can share the same terrain-smoothing rules.

## Important Distinction

The current frontier-expansion system is only a bounded-canvas approximation.

- `tool_expand_world_edge` and `instinct_frontier_expand` make the current map feel larger
- they do **not** create true unbounded coordinates
- true infinite world requires chunk streaming and chunk-aware spatial indexing

## Recommended World Model

Represent the world as a grid of chunks:

- each chunk has integer coordinates `(chunk_x, chunk_y)`
- each chunk has fixed world size like `1200 x 900` pixels
- entities live in world space but can also be exported as:
  - `chunk_x`, `chunk_y`
  - `local_x`, `local_y`

This lets the backend and client reason about huge worlds without one giant monolithic map payload.

## Protocol Direction

Do **not** keep one endlessly growing global map JSON.

Instead:

- backend persists generated chunks
- client requests only the current visible window
- backend returns:
  - chunk upserts
  - chunk removals
  - actor positions

Example shape:

```json
{
  "protocol": 2,
  "world": {
    "infinite": true,
    "chunk_px_w": 1200,
    "chunk_px_h": 900,
    "tile_size": 8
  },
  "window": {
    "center_world": [2400.0, -1200.0],
    "view_world": [1280.0, 720.0],
    "margin_chunks": 1
  },
  "chunk_upserts": [
    {"chunk_id": "2:-2", "entities": [...]},
    {"chunk_id": "3:-2", "entities": [...]}
  ],
  "chunk_removed": [
    "0:-2"
  ]
}
```

## Godot Integration

Godot can support this cleanly.

The camera side should:

- compute the visible world-space rectangle
- expand it by a preload margin
- request matching chunks from the backend
- unload far-away chunks when the window changes

Zooming in/out is compatible with chunk streaming as long as the client sends a world-space view size, not just raw engine-specific zoom state.

### Trigger Priority

For smooth world growth, use this trigger order:

1. reported camera/view window enters preload margin
2. controlled target enters preload margin
3. only then fall back to legacy human-near-border behavior

That lets the backend prepare terrain before the player actually reaches the hard edge.

## Backend Requirements

True infinite map will need more than a protocol change.

### Current blockers

- fixed `MAP_WIDTH` and `MAP_HEIGHT`
- fixed `GRID_W` and `GRID_H`
- fixed `TILE_TO_ENTITY`
- many movement and placement clamps to current map bounds

### Required upgrades

- chunk-aware world coordinates
- chunk-aware geometry lookup
- chunk-aware map generation
- chunk streaming endpoints
- optional floating origin for rendering precision

## Reusable Components

The Python helper module `chunking.py` is the reusable base.

It should stay responsible for:

- chunk coordinate math
- world-to-chunk/local conversion
- camera window to chunk window conversion
- diffing current vs desired chunk sets

It should **not** own:

- Godot-specific camera APIs
- actual chunk persistence
- procedural content generation rules

Procedural terrain continuity belongs in `chunk_generation.py`, not in `chunking.py`.

## Implementation Order

1. Keep current bounded sim working.
2. Add protocol-v2 chunk window requests/responses.
3. Add chunk persistence and lazy generation.
4. Replace fixed map geometry lookup with chunk-aware lookup.
5. Move movement/placement off global clamps.
6. Add Godot chunk load/unload logic.
7. Only then call the map truly infinite.

## Rule For Future Work

When adding infinite-map features:

- prefer reusable chunk/window abstractions
- keep backend authoritative
- avoid client-only fake world growth
- avoid storing the whole explored universe in one active JSON payload
