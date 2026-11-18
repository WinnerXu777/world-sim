# world_map: authored 2D map file (format `0.2-draft`)

Wired into the Engine: the backend registers map files through `EDEN_MAP_FILES` (`systems/movement/map_contract.py`), places several maps with `EDEN_MAP_ORIGINS`, and serves the exact file bytes at `GET /map_file/{map_id}` (see `BACKEND.md` and `1006_map_wire_contract.md`). This package parses, validates and converts walls to the shape `systems/movement/spatial.py` consumes.
`0.1-draft` files are still accepted (with a warning). Check a file: `.venv/Scripts/python.exe tools/validate_map.py MAP.json [MORE.json] [--base-dir DIR] [--actor-radius R]` (exit 1 on any error; several maps also cross-check portals).

## Conventions
- Backend units everywhere (positions, walls, bounds, radii). Origin top-left, +x right, +y down, positions are foot points. Bounds are `[0, 0, w * units_per_tile, h * units_per_tile]`.
- `units_per_tile` has no default and must come from the file. Pixels per unit is derived (`tile_size_px / units_per_tile`) and must not be stored: a stored `pixels_per_unit` that equals the derived value gives a warning (ignored), a different value is an error.
- Sprite references are paths relative to `--base-dir` (planned: `myassets/`), no `..`, not absolute. Existence is checked only when a base directory is given.

## Fields
Top level: `format_version`, `map_id`, `revision` (non-negative integer; `bool`, floats and strings are errors in `0.2-draft`, and `0.1-draft` files may still use a non-empty string, with a warning), `tile_size_px`, `units_per_tile`, `size_tiles [w, h]`, `layers`, `walls`, `anchors`, `entities`, `portals`.
Optional: `actor_radius` (positive finite; recommended, warning when absent), `map_kind` (`exterior` default, or `interior`), `coordinate_system` (must be `top_left_x_right_y_down`), the chunk-document blocks `chunk`, `data`, `pinned_map` (below), unknown keys warn.

| Collection | Item fields |
| --- | --- |
| `layers` | `name`, `kind` (`terrain` / `decoration` / `footprint`), `palette` (`"<positive int>"` -> sprite path), `tiles` (row-major ints, `0` = empty) |
| `walls` | `id`, `min [x,y]`, `max [x,y]`, optional `height` (default 2.4), optional `owner_entity` (an entity id; does not replace the box) |
| `anchors` | `id`, `kind` (known: `door work talk sleep spawn`; others warn), `position`, optional `for_role` (non-empty occupation label, known: `smith builder gatherer`, others warn; an `e_NNNNNN` value is an error; it labels intended use only, resident assignment stays backend-owned) |
| `entities` | `id`, `kind`, `interactive` (explicit bool), `position`, optional `sprite`, optional `interact_radius` (positive finite), optional resource keys (below) |
| `portals` | `id`, `from_anchor`, `to_map`, `to_anchor` |

## Resource keys on entities (G-005, data only for now)
An interactive entity may declare what it yields, with flat optional keys (the same ones the chunk generator writes): `resource` (`water` on `well`; `crops` on `farm_plot`/`farm`; `berries` on `berry_bush`/`berry_patch`/`bush`; `wood` on `tree`/`forest`/`wood_pile`; `stone` on `stone_pile`/`stone_outcrop`; `ore` on `iron_pile`/`ore_vein`/`ore_node`; `fish` on `fish_spot`; `reeds` on `reed_bed`; `mushrooms` on `mushroom_patch`), `amount` (units, 0..1e6), `cap` (> 0, at least `amount`), `regrow` (0..10 per tick), `radius` (0..256 backend units), `tiles` (non-negative integer), `item` (lower-case item name), `water` (0..100, crops only); `stock` (`{item: 1..10000}`, kinds `storage chest storage_case crate`); `capacity` (1..32, kinds `bed shelter hearth`). `amount`, `cap`, `regrow`, `radius`, `tiles`, `item`, `water` need `resource`. Errors: unknown resource name, resource not fitting the kind, bad ranges, keys on a non-interactive entity. The parsed, normalised declaration is `Entity.resource` (`{"name": ..., ...}`, `None` when nothing is declared) and is carried into the registered map entities. Nothing in the engine reads it yet; the four shipped maps declare none. Adding the keys to a shipped file changes its bytes, so its `revision` must be bumped (Continue checks revision and sha256). Design: `1008_map_resources_design.md`.

## Chunk documents
Generated chunks (`1008_worldgen.md`) are `0.2-draft` plus three top-level blocks, now accepted without a warning and exposed as `WorldMap.extras`: `chunk` (object with integer `cx`, `cy`), `data` (object, opaque to the validator), `pinned_map` (an id string). A document with `pinned_map` is a pointer to an authored map: it must have no walls, anchors, entities or portals and only empty (`0`) tiles. Any other unknown top-level key still warns.

## Validation
Errors: structure and types; non-finite or out-of-bounds coordinates; degenerate walls; ids distinct across walls, entities, anchors and portals (layer names are a separate namespace); ids matching `^e_\d{6}$` (the backend's generated entity ids); `owner_entity` not an existing entity; anchor not standable (inside a wall inflated by the actor radius, or closer than the radius to the map edge); anchor unreachable (exact free-space flood fill from the first `spawn` anchor: the actor centre may move in `[r, size - r]` minus every wall inflated by `r`, compressed to wall edges, so a gap of g is passable iff g > 2r; a gap of exactly 2r counts as blocked although `spatial.slide` lets an actor pass dead centre); missing/unsafe sprite files; portal from an unknown anchor; same-map portal to an unknown anchor; cross-map portal to a missing anchor (`check_portal_targets`).
Warnings: an anchor (including portal exits) within `r + 1` of a wall but still standable (an actor starting embedded in an inflated wall never moves); a route that passes a gap with `2r < g <= 2r + 1` (marginal, almost no lateral tolerance; blocked gaps stay an error); unknown anchor kind or top-level key; no anchors / no `spawn`; no `actor_radius`; older format version; no base directory for sprite checks; portal from a non-`door` anchor; `map_kind: "interior"` whose walkable space is open to the map bounds (no wall ring); an interactive entity whose wall has `owner_entity` but no `work`/`talk` anchor outside that wall inflated by the actor radius (and within the entity's `interact_radius` when it declares one).

Actor radius precedence (validator, `to_movement_contract`): explicit argument or CLI flag, then the file's `actor_radius`, then `systems.movement.spatial.RADIUS`.

## API
`load_map(path, base_dir=None, actor_radius=None)` raises `MapValidationError` on any error. `check_map_file(...)` returns `(WorldMap | None, issues)` without raising. `parse_map(dict)`, `validate_map(map, base_dir, actor_radius)`, `check_portal_targets(maps)`, `effective_radius(map, override)`, `to_wall_boxes(map)` (same keys, order and types as `spatial.wall_boxes`), `to_anchor_list(map)` (plain dicts, includes `for_role` when set), `to_movement_contract(map, actor_radius=None)` (input for `spatial.slide`).
Tests: `tests/test_world_map.py`, `tests/test_world_map_v02.py`; fixtures in `tests/fixtures/maps/` carry arbitrary values (`example_smith.json` mirrors the example in `myassets/MAP_CONTRACT_REPLY.md`).
