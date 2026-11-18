# 1008 worldgen: deterministic chunk generator and streaming service (WS-D, R2-M1)

Owner: Model plane worker [2f0fd3]. Code: `at_the_beginning/systems/worldgen/`. Tests: `tests/test_worldgen_*.py`, `tests/golden/worldgen_*`. Benchmark: `tools/bench_chunks.py`. Pure and engine independent: nothing here imports the engine, `map_geo`, `genesis_config`, torch or the World facade (numpy only; `ProcessPoolExecutor` for the service).

Status of this document: section 1 (spec) was written before the code and is the contract; sections 2 onwards are filled in as the work lands. Numbers in section 7 are **measured** unless marked otherwise.

## 1. Chunk spec `chunk 0.1`

### 1.1 Geometry
| Constant | Value | Why |
| --- | --- | --- |
| `CHUNK_TILES` | 32 | D2 |
| `UNITS_PER_TILE` | 8 | `genesis_config.TILE_SIZE`, authored maps |
| `CHUNK_UNITS` | 256 | 32 x 8 |
| `TILE_PX` | 48 | `myassets/manifest.json` `tile_size`, so a chunk is 1536 px |
| Address | `(cx, cy)` Python `int` (int64 range), world tile of a chunk tile `(i, j)` is `(cx*32 + i, cy*32 + j)` | D2 |
| Axes | origin top-left of the chunk, +x right, +y down, row-major `tiles[row=j][col=i]` | `world_map/schema.py` |
| Positions | chunk-LOCAL, in backend units, `[0, 256)`, quantised to 1/16 unit (exact in float32 and in JSON) | revised D2 (window-relative) |
| Absolute position | `(cx*256 + x, cy*256 + y)` computed in int64 + float32 by the consumer; this package never makes a large absolute float | revised D2 |

### 1.2 Generation contract
`generate_chunk(world_seed, cx, cy, *, pinned=None, params=None) -> Chunk` is a pure function of `(world_seed, cx, cy, pinned fingerprint, generator_version)`. It does not look at neighbouring chunks, exploration order, wall-clock, the global RNG, `random`, `torch.rand` or `numpy.random`. All variation comes from an integer hash (`splitmix64` finaliser on `uint64` arrays) of `(seed, field id, octave, lattice x, lattice y)`.

Determinism rules (enforced by tests): float64 only, only `+ - * /` and `sqrt` (all IEEE-754 correctly rounded; no `sin`, `exp`, `pow`, no reductions over floats), every wavelength a power of two so lattice coordinates are exact, every field **quantised to a 12-bit integer** (`0..4095`) before any threshold, so tile ids are integer comparisons.

### 1.3 Document (what `Chunk.document` / the wire bytes contain)
The document is a `0.2-draft` authored-map document (it passes `world_map.parse_map` / `validate_map` with `base_dir=myassets`), so the Godot loader and validator stay one code path, plus a `chunk` block and a `data` block that older readers ignore (the validator warns about unknown top-level keys; accepted).

```
{
 "format_version": "0.2-draft", "map_id": "chunk_<cx>_<cy>", "revision": 0,
 "tile_size_px": 48, "units_per_tile": 8, "size_tiles": [32, 32], "actor_radius": 2.4,
 "coordinate_system": "top_left_x_right_y_down", "map_kind": "exterior",
 "layers": [ terrain, decoration, footprint ],          # int16 row-major, 0 = empty, palette id -> myassets-relative png
 "walls": [ {"id": "c<cx>_<cy>:w<n>", "min": [x, y], "max": [x, y], "height": 2.4} ... ],   # the shape spatial.py consumes
 "anchors": [], "portals": [],
 "entities": [ {"id", "kind", "interactive", "position": [x, y], "sprite"?, + extension keys} ... ],  # aggregated, capped
 "chunk":  {"spec": "0.1", "generator_version": "...", "world_seed": "<decimal string>", "cx": int, "cy": int,
            "pinned": "<fingerprint or ''>", "pinned_tiles": int},
 "data":   {"biome": 32x32 uint8, "edges": 32x32 uint8, "prop_palette": [paths], "props": [[palette_idx, x, y], ...],
            "spawns": [...], "pois": [...], "caps": {...}}
}
```
* `terrain` layer: fixed palette (section 3). Ids are stable per generator version, so clients cache by palette id.
* `decoration` layer: present, **empty in 0.1** (no tile-sized overlay art exists, section 3 `[GAP]`); dense visual scatter (trees, ferns, rocks) is in `data.props`, not in this layer, because the existing sprites are 80 to 240 px freestanding sprites with a foot pivot, not 48 px cells.
* `footprint` layer: tiles blocked by water / rock / ruin walls (1 water, 2 rock, 3 ruin); `walls` is the authoritative collision, the layer is a visual aid for minimap and tools.
* `walls`: the blocked mask decomposed into maximal rectangles (row runs merged vertically). Box edges lie on tile boundaries, in chunk-local units, clipped to the chunk: a lake crossing a seam is the union of the boxes of both chunks. Same keys and types as `spatial.wall_boxes` / `world_map.to_wall_boxes`.
* `entities` (cap `MAX_ENTITIES_PER_CHUNK = 16`): aggregated resource features (`kind` = `forest`, `ore_vein`, `stone_outcrop`, `berry_patch`, `fish_spot`, `reed_bed`, `mushroom_patch`) each with `resource`, `amount` (count of units it stands for), `radius` (units) and `tiles` (number of tiles it aggregates); and points of interest (`poi_ruin`, `poi_shrine`, `poi_camp`, `poi_cave`) as hooks for later lore. A chunk that would exceed the cap merges the nearest same-kind features (weighted centroid, summed amount) until it fits; POIs are never merged away, resources are. Ids are `c<cx>_<cy>:<kind><n>`, globally unique, and never `e_NNNNNN`.
* `data.spawns` (cap 4): wildlife spawn table entries `{species, weight, max, slots: [[x, y], ...]}`: seeded positions on legal land tiles so integration does not need to re-roll. Species with no sprite are still listed (hook), see `[GAP]`.
* `data.biome`: semantic biome id per tile; `data.edges`: 8-bit mask per tile, bit k set when neighbour k (N, NE, E, SE, S, SW, W, NW) has a different terrain id; computed from a one-tile apron, so a chunk's border tiles are correct before its neighbours exist. Autotile art does not exist yet (`[GAP]`); this mask is what a client or an artist's rule table keys on.
* Pinned tiles (section 5): terrain/decoration/footprint are `0`, no wall, entity or prop inside; `chunk.pinned_tiles` counts them. A chunk fully inside a pinned area is `{"pinned_map": "<id>"}` plus the empty layers (the engine loads the authored file instead).

### 1.4 Bytes, hash, version
Wire bytes = canonical JSON of the document: UTF-8, `sort_keys=True`, separators `(",", ":")`, ASCII-escaped, floats printed by `repr` (all values are multiples of 1/16, so the text is exact). `sha256` = SHA-256 of those bytes (this is the ETag; it is not inside the document). `generator_version` is a string (`0.1.0`) in the document and in every cache key; any change to a hash constant, calibration constant, palette or feature rule bumps it and regenerates the golden files. Save manifests record `world_seed`, `generator_version`, pinned fingerprint (D5).

### 1.5 Coordinate and layer shape example
A 32 x 32 terrain layer is 32 lists of 32 ints. A chunk at `(-1, 3)` has `map_id` `chunk_-1_3` and tile `(0, 0)` is world tile `(-32, 96)`.

## 2. Algorithm (what the code does)

Files: `spec.py` (constants), `noise.py` (integer-hash value noise, fBm, quantiser), `fields.py` (the global fields), `regions.py` (region grid), `pinned.py`, `classify.py` (fields to biome to terrain over any tile window, points of interest, pinned blend), `generate.py` (props, resources, spawns, walls, edge mask, document, bytes), `assets.py` (palette and gap list), `rings.py`, `service.py`, `golden.py`.

1. **Window.** A chunk is computed over a window of 34 x 34 tiles (the chunk plus a one-tile apron) at world tile `(cx*32 - 1, cy*32 - 1)`. `classify.compute_window` is a function of the window origin and size only; the tests prove the result for a tile does not depend on where the window starts.
2. **Fields** (value noise fBm, octave k has amplitude 2^-k, wavelengths in tiles, quantised to 0..4095 with a contrast stretch about the middle):

| Field | Wavelengths | Use |
| --- | --- | --- |
| elevation | 256, 128, 64, 32, 16 | water below `SEA = 800`, shore band to 940, highland above 3600, peak (blocking cliff) above 4060 |
| moisture | 256, 128, 64, 32 | meadow >= 2600, wetland >= 3400 on low ground, desert needs < 1000 |
| temperature | 512, 256, 128, 64 | desert needs >= 3200; pine on cold or high ground |
| river | 128, 64, 32 | the zero crossing of a smooth field; width is `abs(v - 0.5)` divided by the local gradient, so it does not blow up at saddles (a stream just ends there); half width 0.9 to 1.9 tiles from the `river_width` field; not above elevation 3300 |
| ford | 16, 8 | where above 3400 the river tile is a walkable ford (about one fifth of river area) |
| forest | 64, 32, 16 | combined with moisture, plus forest patches; forest where >= 2800 |

   All thresholds are integers on the 12-bit scale (constants at the top of `classify.py`). They were calibrated on 1,048,576 tiles with no pinned area. Seed 1008: water 11.9 %, shore 1.7 %, plains 35.4 %, forest 17.6 %, meadow 12.0 %, highland 9.9 %, peak 5.5 %, desert 3.3 %, wetland 0.8 %, river 1.5 %, ford 0.3 %. Seed 7 with the same constants: water 17.7 %, plains 41.6 %, forest 12.9 %, meadow 9.9 %, highland 5.9 %, peak 3.7 %.
3. **Region grid** (8 x 8 chunks = 256 x 256 tiles). Each region hashes, from `(seed, rx, ry, kind, slot)`: up to 2 lakes (45 % and 15 %; radii 8 to 24 by 6 to 20 tiles), up to 3 forest patches (60/40/25 %; radius 14 to 35), up to 2 point-of-interest candidates (90 % and 50 %; ruin 40, camp 25, shrine 20, cave 15 by weight). A lake is an elevation depression with a noisy rim (`depth = (1 - d2) * 1400`), a forest patch adds to the forest field (`(1 - d2) * strength`); both are terms in per-tile fields, so chunks agree by construction. No feature reaches further than `MAX_FEATURE_RADIUS = 40` tiles from its centre; a window consults every region within that distance (up to 2 x 2), so a feature crossing a region seam is emitted by the chunks on both sides from identical parameters (tested with a real lake found across the seam at tile 256).
4. **Points of interest.** A candidate is accepted only if every tile of its rectangle (plus a 2-tile margin) is ordinary land (a cave needs rock), it is not within the blend of a pinned area, and it is evaluated on the terrain without POIs, so there is no circularity. Ruins: paving floor, perimeter walls with 30 % hashed gaps and a guaranteed door gap in the middle of the south side; camp: cleared grass plus a campfire entity; shrine: 3 x 3 paving; cave: a rock patch, blocked except for a one-tile entrance. The entity (`poi_*`) is emitted only by the chunk that contains the anchor tile; the tiles and walls by every chunk the rectangle overlaps. POIs are rare by design (about one accepted candidate per two regions).
5. **Terrain, footprint, walls.** Biome to terrain id by a lookup table (section 3). Blocking tiles are water, river (not ford), peaks, ruin walls and cave rock. `boxes_from_mask` decomposes the blocked mask into disjoint tile-aligned rectangles (row runs merged vertically), so the walls exactly cover the footprint layer (tested).
6. **Edge mask.** Bit k of `data.edges` is set when neighbour k (N, NE, E, SE, S, SW, W, NW) has a different, non-empty terrain id, from the apron. It is the input an autotile rule table needs; the art does not exist yet.
7. **Props** (visual scatter, `data.props`, at most 640): per tile, one hash decides the kind by cumulative probability per biome (tree, berry bush, flower, reed, fern, boulder, mushroom, log) and the jitter inside the tile (positions are multiples of 1/16 unit). Forest tree probability rises from 10 % to 50 % with the forest field. Tree sprite: pine when cold or high or in 30 % of forest, apple tree on 1 in 16 warm wet trees, else oak. No props on blocked tiles, inside POI rectangles or within the cleared ring of a pinned area.
8. **Resources** (`entities`, cap 16): per 16 x 16 quadrant, props aggregate into `forest` (>= 4 trees), `stone_outcrop` (>= 2 boulders), `berry_patch` (>= 2 bushes), `mushroom_patch` (>= 2), `reed_bed` (>= 4), plus `fish_spot` (>= 6 water tiles with a land neighbour, position chosen by hash) and `ore_vein` (>= 24 rock tiles, 30 % hashed chance, position by hash). Each carries `resource`, `amount`, `tiles`, `radius`. Over the cap, the closest same-kind pair is merged (weighted centroid by amount, amounts summed) until it fits; POIs are never merged; ties break deterministically; merging preserves the total (tested). The cap is a parameter (`GenParams`) and part of the cache key when not the default.
9. **Wildlife spawn table** (`data.spawns`, at most 4): species weights from habitat tile counts (boar, deer, goat, rabbit, sheep, wolf); entries below weight 300 are dropped; each entry lists up to 4 hash-chosen slot positions on habitat tiles.
10. **Document and bytes.** See sections 1.3 and 1.4. A chunk fully inside a pinned area is a pointer (`pinned_map`) with empty layers.

Determinism notes: tile coordinates are int64 (addresses of 10^9 chunks work, tested); the lattice hash is splitmix64 over `uint64` arrays; float64 values come only from `+ - * /` of exact lattice fractions and are quantised before thresholding. Chunk generation never touches `random`, `numpy.random`, `torch`, the wall clock or unordered containers. Python hash randomisation is irrelevant (two `PYTHONHASHSEED` values in fresh processes give the same bytes, tested). Cross-machine identity is by construction (IEEE-754 operations only, no libm calls) and has been checked on this one machine only.

## 3. Palette from `myassets/` and gaps

Sources: `myassets/manifest.json`, `generated/manifest.json`, `generated/approved.json`, `a1/manifest.json`, `a4/static_manifest.json`. Every path below is checked to exist by `tests/test_worldgen_generate.py` (`test_palette_and_sprite_paths_all_exist_in_myassets`), and every generated chunk in the test sample is accepted by `world_map.check_map_bytes(payload, base_dir=myassets)` with no errors (sprite files included).

| Layer / palette id | Path (relative to `myassets/`) | Note |
| --- | --- | --- |
| terrain 1 grass | `terrain/grass.png` | 48 x 48 |
| terrain 2 sand | `generated/sand-local-v1.png` | 512 x 512 source, approved render size 48 x 48; used for shore, desert and ford |
| terrain 3 water | `generated/water-local-v2.png` | 512 x 512 source, approved render size 48 x 48; lakes and rivers |
| terrain 4 rock | `terrain/flagstone_slate.png` | STAND-IN for mountain ground |
| terrain 5 paving | `terrain/paving_stone.png` | ruin and shrine floor |
| footprint 1, 2, 3 | water tile, `flagstone_slate.png`, `buildings/wall_stone.png` | water / rock / ruin wall |
| decoration | none | empty layer in 0.1 |
| props | `a1/sprites/` oak, pine, boulders, berry bush, campfire; `a4/static/` apple tree, fern, green fern, mushrooms, reeds, wildflowers, fallen log | sizes and pivots in the comments of `assets.py` |
| spawn sprites | `a4/static/` deer, goat, sheep | wolf, boar, rabbit have none |

Note: the a1 and a4 sprites are marked "candidate only" / "visual review pending" in their manifests; the generator uses them because they are what exists.

**[GAP] list for the asset session.** Sizes and pivots follow the existing sets: ground tiles are 48 x 48 and periodic; freestanding sprites have the pivot at the foot (bottom centre, a few pixels above the bottom edge). Generated from `assets.GAPS`; nothing was invented.

| id | need (size / pivot) | where it plugs in | 0.1 stand-in |
| --- | --- | --- | --- |
| G-TERRAIN-TRANSITIONS | Biome transition / autotile edge tiles: grass<->sand, sand<->water, grass<->rock, grass<->forest floor, inner and outer corners. 47-tile blob set per pair, or a 16-tile edge-bitmask set; 48x48 each, periodic along the shared edge. | data.edges (8-bit neighbour-difference mask per tile) is already emitted | hard tile edges |
| G-WATER-SAND-48 | 48x48 exported copies of water and sand (the approved sources `generated/water-local-v2.png` and `generated/sand-local-v1.png` are 512x512 and the manifest has no `terrain/` entry for them), plus a SHALLOW water / ford tile and a deep-water tile; optional 4-frame ripple animation. | palette ids 2 and 3 | 512 px sources scaled by the client; fords drawn as sand |
| G-GROUND-TYPES | More ground tiles, 48x48 periodic: dirt / forest floor (leaf litter), mud / marsh, hot desert sand (distinct from shore sand), snow / tundra, mountain rock ground and a cliff-face edge tile, worn path. | biomes forest, wetland, desert, highland, peak | forest, wetland on grass; desert on shore sand; highland and peak on `terrain/flagstone_slate.png` |
| G-DECOR-TILES | Tile-sized (48x48) decoration overlays for the `decoration` layer: grass tufts, pebbles, shore foam, wet-sand edge, flower patches, footpath stones. | decoration layer (empty in 0.1) | none; scatter sprites in data.props |
| G-TREES | More tree species and states: birch, dead/bare tree, palm (desert), young sapling, cut stump (depleted), dense-thicket sprite. Same footprint as `a1/sprites/oak-a1-v1.png` (about 224x208 px, foot pivot [112,193]); stump 64x64 pivot [32,56]. | kind forest, data.props | oak, pine, apple tree |
| G-ORE-STONE | Ore and stone nodes with a depleted state: stone node, iron ore, copper ore, coal seam, clay bank. 96x96 each, foot pivot [48,86]. | kinds ore_vein, stone_outcrop | boulders for stone_outcrop; ore_vein has no sprite |
| G-CROPS | Crop growth stages (sprout, half, ripe, harvested) for wheat and one root crop, plus a tilled-plot tile; 48x48 tile aligned. Not used by the generator yet; listed because farming needs them. | none yet | none |
| G-ANIMALS | Wildlife sprites: wolf, boar, rabbit, fox, bird, fish (in-water silhouette). Match `a4/static` animals: 128x128, foot pivot [64,112] (rabbit and bird 64x64 pivot [32,56]); ideally 4-direction walk strips like `characters/`. | data.spawns species | deer, goat, sheep only; other species are table hooks with no sprite |
| G-POI-ART | Points of interest: ruined wall segments (96x96 and corner pieces), broken pillar 64x96, shrine 96x128 pivot [48,118], cave entrance 144x112 pivot [72,104], ruined-camp props (tent, bedroll). | kinds poi_ruin, poi_shrine, poi_cave | paving floor + `buildings/wall_stone.png` footprint for ruins; camp uses the campfire; shrine and cave have no sprite |
| G-RESOURCE-MARKERS | Fish-spot ripple marker 48x48; harvest-state variants for berry bush (bare), mushrooms (picked), reeds (cut). | kinds fish_spot, berry_patch, mushroom_patch, reed_bed | fish_spot has no sprite |
| G-BRIDGES | Not missing but unused: `a4/static/static-stone_bridge-a4-v1.png` (240x160) and `static-wood_pier-a4-v1.png` (192x160) fit river fords; placing them needs path-aware logic that belongs to a later generator version. | kind ford | ford tiles are walkable sand |

## 4. Streaming service

`rings.py` (pure) and `service.py` (workers, queue, LRU). The engine is not involved; the future World facade calls these from the tick thread.

**Rings (D11) as `RingConfig`**, in chunks of 256 units: simulation radius 2 (5 x 5), prefetch +2 (9 x 9), lead +2 in the direction of travel (the dominant axis advances two chunks; a diagonal heading leads on both axes), unload hysteresis +1 (a loaded chunk is unloaded only beyond radius 3), keep +1 (cache), render = camera rectangle plus 1 chunk via `chunking.chunks_for_camera_window`. No heading below 2 units/s. Chunk addresses and the camera-window math come from `systems/map/chunking.py` (loaded by file path so that importing the planner does not import the engine through `systems.map`).

**`plan_stream(actors, loaded, cached, in_flight, cfg, view)` -> `StreamPlan`** (pure, frozen result): `simulate` (must be integrated), `integrate` (simulate minus loaded, nearest first), `unload` (loaded beyond the hysteresis radius, farthest first), `prefetch` and `generate` (what to have generated, best first, excluding cached, in flight and loaded), `wanted`, `keep`, `drop` (cached outside `keep`), `render`, `priority`. Priority = 0 for the simulation ring and 1000 for the rest, plus distance in chunks from the nearest actor, discounted up to 35 % for chunks straight ahead. Two actors union their rings. `blocked_by_void(x, y, loaded)` is the predicate for the invisible wall at the edge of the integrated area.

**`ChunkService`**: `request(coord, priority)` (idempotent; a better priority re-queues), `cancel`, `set_wanted(priorities)` (queue = exactly these, stale queued requests are cancelled before they start, and not-yet-started in-flight ones are cancelled too), `apply_plan(plan)`, `pump()` (collects finished work, dispatches at most `max_in_flight` = 2 x workers tasks so that cancellation stays meaningful, never blocks), `get` / `peek` (LRU lookup; `get` counts hit or miss and refreshes recency), `get_blocking` (tools and tests only), `warm()` (start the workers), `stats()`. Workers are `ProcessPoolExecutor` processes running `generate.generate_payload`, which returns bytes only; the cache holds the payload bytes and the sha256, the JSON is parsed lazily on first `.document`. A worker exception or a dead pool is contained: the chunk is recorded in `failed` and can be requested again, a broken pool is restarted and its in-flight chunks re-queued, and nothing is raised out of `pump()`. `workers=0` generates inline inside `pump` (tests). The LRU key is `(world_seed, generator_version, pinned fingerprint, params fingerprint, cx, cy)`; capacity default 512.

**[DECISION] cache retention** (took the recommended default): the LRU decides what stays in memory (a revisited chunk is a cache hit); `apply_plan(plan, evict_dropped=True)` additionally frees everything outside the keep ring at once. D11 says both "bytes dropped from the cache beyond the keep ring" and "re-entering recently visited land costs a cache hit"; these conflict, and a chunk is about 16 KB, so retaining 512 of them costs about 8 MB.

**Integration contract for the later engine work** (not built here): per tick take at most one entry of `plan.integrate` whose bytes are in the cache, allocate its `m_tensor` rows from `entities`, register `walls` (already clipped to the chunk, same shape as `spatial.wall_boxes`) and tile-map cells; unload is the reverse; plan again when the actor changes chunk or heading, not necessarily every tick (the benchmark plans every tick, the worst case).

## 5. Pinned areas

`PinnedSet` of `PinnedArea(id, x0, y0, w, h)` tile rectangles plus `blend` (default 8 tiles). The default village area is `starter_village_area()` = 48 x 36 tiles at the world origin (read-only from `world_data/maps2d/starter_village.json` when a path is given). A chunk fully inside one area is a `pinned_map` pointer. For partially covered chunks the covered tiles are `0` in every layer and in `data.biome`, with no wall, entity or prop on them (tested for chunks (1,0), (0,1), (1,1)). Outside the rectangle: within `blend // 2` tiles everything is plain grass, no rivers, forests, props or walls; from there to `blend` tiles elevation is mixed toward ordinary land so that water and cliffs do not touch the border; within 64 tiles temperature, moisture and forest are pulled toward temperate values, so the start area is habitable whatever the seed. POIs are not placed within the blend. Beyond 64 tiles chunks are byte-for-byte what they would be without the area (only the `chunk.pinned` fingerprint in the document differs; layers, walls and entities are equal, tested). The pinned fingerprint is part of every cache key and of the document, so a save can refuse a changed set the way `persistence/map_guard.py` refuses a changed map.

Open point (not decided here): the authored village's own border tiles are grass, so the blend is plain grass; a later authored town with a different border needs its own blend description.

## 6. Tests

`tests/test_worldgen_generate.py` (36 tests), `tests/test_worldgen_service.py` (26 tests), data in `tests/golden/worldgen_hashes.json` (75 cases: 4 seeds including a negative and a 2^40 seed, 16 addresses including negatives, the region seam at chunks 7|8, 1000 x 1000, -123456 x 654321 and 10^6, plus 11 village-pinned chunks) and `tests/golden/worldgen_chunk_1008_2_0.json` (one full chunk, readable). Regenerate only with a `GENERATOR_VERSION` bump: `python at_the_beginning/systems/worldgen/golden.py --write`.

| Requirement | Tests |
| --- | --- |
| golden bytes | hashes of 75 cases and the full sample file |
| order independence | a 6 x 6 area (crossing the region seam) generated in three orders with fresh caches is byte-identical; the same area through a 2-process pool equals the single-process bytes; tile fields do not depend on the window origin |
| determinism across fresh processes | two subprocesses with different `PYTHONHASHSEED` print the same hashes as the parent; no dependence on `random`/`numpy.random` state |
| edge continuity | a double-width window equals two chunks side by side (terrain and biome, horizontal and vertical, at 5 addresses incl. the region seam and negatives); edge masks of neighbours equal a mask computed over both at once; wall boxes of neighbours exactly cover the blocked tiles of the joint window and at least one blocked feature crosses a tested seam; a real lake across the region seam is emitted by both sides |
| caps | entity count <= 16 and spawns <= 4 and props <= 640 over 900 chunks; a cap of 3 merges (not drops) and preserves amounts; the merge is order independent |
| pinned | pointer chunk, nothing written inside the rectangle, grass ring, far world unchanged, two areas and negative coordinates, key and fingerprint |
| format | every chunk passes the authored-map validator with real sprites; layers, quantisation, id uniqueness and prefix; walls disjoint and exact; canonical bytes round-trip; all biomes occur |
| service | rings and plans (9 x 9, lead, hysteresis, priority, purity, render ring), LRU, priority order, cancellation of stale requests, failure containment (inline and in a worker process), 2-process burst with cancellation |

## 7. Measurements (`tools/bench_chunks.py`, measured, not estimated)

Machine: Windows 11, Python 3.13.5, numpy 2.4.4, 16 logical CPUs; run 2026-10-08 02:36-02:45 in MEASURE mode (nothing else CPU-bound on the machine), 2 worker processes, seed 1008, village pinned, generator 0.1.0. Raw output: `.runtime/bench_chunks.json` (gitignored). Command: `python tools/bench_chunks.py --workers 2`.

### 7.1 Against the D11 targets

| D11 target or claim | Measured | Verdict |
| --- | --- | --- |
| generation about 50 ms per chunk (design target) | one process, 900 chunks, warm region cache: p50 4.46, p95 5.66, p99 7.85, max 14.09 ms; first chunk of a fresh process or region (cold cache, includes the point-of-interest probes): p50 8.90, p99 21.35, max 31.20 ms (300 chunks) | met with a 6x margin even cold |
| worker process, never block the tick | in the worker (inside the pool): p50 4.56, p99 8.98, max 13.97 ms; single request round trip (request to bytes in the cache, idle pool): p50 5.90, p95 14.14, p99 19.45 ms; throughput of 2 workers 397 chunks/s | met |
| a raw payload is "on the order of 6 KB" | raw canonical JSON: mean 15.7 KB, p50 15.1, p99 23.5, max 26.3, min 12.0 KB; zlib level 6: mean 2.0 KB, p99 4.3, max 5.0 KB; zlib level 1: mean 2.3 KB, max 5.9 KB; the three layers alone as raw int16 are 6.1 KB | plan estimate was low by 2.6x raw; compressed it is a third of the estimate [GAP] (small) |
| at least about 25 s between "chunk requested" and "chunk needed" while walking | real-time walk of 5000 units at 20 u/s (250.9 s, 5000 ticks): request to entering the simulation ring p50 51.5 s; chunk ready to entering the ring p50 51.4 s; the minimum is 2.7 s and is the first chunks beyond the ring after a cold start (about 99 chunks queued at once, the last ready after about 1 s). Run at 40 u/s: p50 25.8 s, minimum 1.4 s | met in steady state with 25 to 50x margin over the 1 s burst latency; the start-up minimum is 2.7x the worst burst latency |
| the player never waits / void barrier hits must be 0 at walking speed | 0 hits in the walk (5000 u at 20 u/s), the run (5000 u at 40 u/s, "run" = 2x walk is my assumption; the repo has no run speed) and the out-and-back walk (2 x 2500 u). Time-compressed stress of the same walk (world moves faster than real time; effective speed = 5000 u / wall time): 187 u/s (9x walk) 0 hits; 412 u/s (21x) 0 hits; 706 u/s (35x) 0 hits | met |
| cache hit instead of regeneration when re-entering recently visited land | LRU `get` hit 0.38 us, miss 0.30 us (200,000 calls); the out-and-back walk (5000 u of travel) generated 207 chunks against 279 for a straight 5000 u line, consistent with the return leg being served from the 512-entry LRU (not verified chunk by chunk); the service counts hits only for `get`, the bench uses `peek`, so no hit rate is reported | indicated, not proven (a per-chunk hit test is in the unit tests only for the LRU itself) |
| tick thread does only integration, under 2 ms | NOT the engine's integration. What the service side costs the main thread, planning every tick (worst case): `plan_stream` + `apply_plan` p50 1.02, p95 2.27, p99 3.13, max 8.66 ms (walk; 2500- and 5000-tick runs agree within 0.2 ms); `pump` p50 0.002, p99 0.10, max 0.57 ms; whole loop iteration p50 1.08, p99 3.27, max 8.73 ms. At most one chunk was integrated per tick (100 integration ticks of 5000). | planning every tick is more than 2 ms at p99; plan on change instead (see below) |
| memory per loaded chunk | cached chunk = payload bytes only: 14.8 KB average (512 entries is about 7.6 MB); if its document is parsed (`.document`) the chunk costs 84.7 KB including payload (200 chunks, tracemalloc); lazy parse costs 0.22 ms p50 / 0.34 ms p99 per chunk, `layer()` to numpy 0.02 ms | measured; entity rows in the tensors are not part of this |
| 5x5 cold start | pool already started: all 25 simulation-ring chunks ready in 0.07 s; starting the 2 worker processes and importing numpy in them: 0.16 s | measured |

**What this says about the plan.** The generator and the cache are far inside the targets. The one number above target is the planner cost if it is run every tick; the plan only changes when an actor crosses a chunk border or its heading changes, which at walking speed is once per 12.8 s, so the game should call `plan_stream` on change (and at most a few times per second) and only `pump` + one integration per tick. I did not build or measure that policy; `plan_stream` is pure, so a change test (actor chunk, heading octant) is a few lines at the call site.

### 7.2 Not measured

- Anything inside the engine: m_tensor slot allocation, wall-box registration, spatial hash, `world_contract` revision per chunk, tick p99 while streaming (Gate E "tick p99 within 2 ms of the no-streaming baseline"), integration cost per tick of the real thing.
- GIL and CPU contention between the tick and the pool-result handling in one process (the walk loop is a bare Python loop on the main thread, not the engine); more than 2 worker processes; several actors; teleporting (a cold 5 x 5 mid-game); a slow disk or any disk (nothing here touches disk).
- Save size and delta growth (D5 is not built), client cost, wire transfer (compression was computed with `zlib`, not sent), battery or thermal throttling, other machines or Python versions, memory of the whole process.
- Cross-machine identity of the bytes: checked across processes on this machine only (golden file, two `PYTHONHASHSEED` values, pool versus single process).
- Visual quality: the world was inspected as ASCII biome maps and statistics only, no rendered screenshot (no live Godot, and the transition art does not exist).
- Reachability: nothing guarantees that every land area is connected to the village; rivers and lakes are blocking with fords on about a fifth of river tiles, and peaks block.


## 8. Decisions taken, gaps found, what is not done

**Decisions taken (recommended default, provisional, each behind a constant or an interface):**
- **Chunk size** 32 x 32 tiles / 256 units kept as the plan says (`spec.CHUNK_TILES`). Generation cost per chunk is about 4.5 ms, so a smaller chunk would be cheap too; the reason to keep 32 is that it is the plan and fits the payload and the 25-chunk window budget.
- **Noise algorithm**: value-noise fBm on an integer hash, chosen because it needs only IEEE `+ - * /` (exact cross-machine) and is fast with numpy. Its weakness is slightly axis-aligned blobs; gradient or simplex noise would look more natural but needs care to stay exact. Revisit at generator 0.2 if the look matters.
- **Region size** 8 x 8 chunks (256 tiles), max feature radius 40 tiles.
- **Rivers** are the gradient-normalised zero crossing of a smooth field; about a fifth of river tiles are walkable fords (drawn as sand), the rest block. Lakes and rivers are blocking wall boxes. There is no shallow-water or bridge art; `static-stone_bridge` and `static-wood_pier` exist in `a4/static` but are unused.
- **Payload** = the authored-map JSON document (one loader path), canonical bytes, sha256 as ETag. A binary int16 form (6.1 KB for the three layers) would be smaller raw, but compressed JSON is 2.0 KB on average, so the wire does not need it.
- **Cache retention** is LRU (section 4).
- **Chunk-local positions** are multiples of 1/16 unit; `world_seed` is a decimal string in the document (JSON numbers above 2^53 lose precision in Godot).
- **Wildlife** is a spawn table with seeded slot positions; actual animals are created by the integration code, not here.

**[GAP] found (plan or repo claims that did not hold):**
- D11 estimated a raw payload of about 6 KB; measured 15.7 KB raw, 2.0 KB compressed (the document carries five 32 x 32 integer grids as JSON text).
- D11 says both that a chunk beyond the keep ring has its bytes dropped and that a revisit is a cache hit; resolved as in section 4.
- The plan's "forest patch is one entity with a tile mask and per-tile harvest": chunk 0.1 emits aggregated entities with a `tiles` count and a centroid, not a tile mask; the per-tile structure is in `data.props`. A tile mask can be added to the entity if per-tile harvest needs it.
- The orchestrator's palette list named `water-local-v2`, `sand-local-v1` and `nature_survival_atlas`: the first two exist only as 512 x 512 sources under `generated/` (approved to render at 48 x 48) and are not in `myassets/manifest.json`; the atlas crops are exported as `a1/sprites/*` (used). See the asset list in section 3.
- `world_map/parse.py` warns "unknown top-level key (ignored)" for `chunk` and `data` (and `pinned_map`), and there is no code that reads them yet: a chunk-aware loader or a validator whitelist is needed (owner: whoever owns `world_map/` and the Godot loader).
- `systems/map/__init__.py` imports the engine-side map code, so `systems/map/chunking.py` cannot be imported as `systems.map.chunking` from a pure module without that cost; `rings.py` loads the file by path instead. Moving `chunking.py` to a standalone module (or making `systems.map` lazy) would remove the workaround.
- No run speed exists in the repo (`MOVE_STEP = 1.0` per tick at 20 Hz is the only speed); the "run" benchmark uses 2x walk as an assumption.

**Not done in R2-M1 (by scope):** engine integration and anything in `map_test.py`/`instincts`; deltas and saves (D5); the `/chunks` and `/chunk/{cx}/{cy}` wire routes (D8, but `Chunk.payload` and `sha256` are exactly what they would serve); the Godot loader and autotile art (D9, section 3); dormant simulation (D7); windowed pathing (D10); spaces (D1); nature cycles; roads, villages or roaming structures beyond points of interest; connectivity or reachability guarantees; the replan-on-change policy for the planner; a per-chunk cache hit-rate counter in the bench (the walk uses `peek`).
