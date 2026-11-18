# Implementation and asset worker report — 2026-10-06

## Completed bounded work

Created `myassets` and an exploratory native Python/Arcade prototype in
`2D1006newstart` at the user's request. The shared Godot 2D addendum was delivered
after this prototype was built. It is preserved as exploratory work; it does not
replace the production Godot direction. No existing backend, Godot 3D, or web
files were changed by this worker. No commit, branch, tag, deletion, or major
restructure was performed. Snapshot existence has not been verified here.

The prototype has deterministic village/coast terrain, four-direction movement,
foot sorting, camera/zoom, water/building/resource collision, gathering and stocks,
inventory, dialogue, eating, well/crate interactions, a campfire task, pause/help,
minimap, screenshots, and isolated local saves. Resident behavior is static and
scripted. It is not Eden's full gameplay. A GET-only threaded Eden observer reads
bootstrap/frame; it does not possess residents, move them, or mutate the backend.

The interactive prototype was launched. Windows reports its child pythonw process
27536 as responding with a nonzero window handle. No errors were logged. GPU
captures are saved under `screenshots/`. The launcher wrapper PID was 2780.

## C-002 factual answers

1. **Sizes/pivots/directions:** Keep 48 x 48 terrain tiles and the reused 384 x 512
   character sheets, with 128 x 128 frames, four direction rows south/west/east/north,
   native pivot [64,124]. Idle column 1, walk columns [0,1,2,1]. No newly generated
   character sheets exist. Native image coordinates start at the top-left, x right,
   y down. Reused props use bottom-center pivots as recorded in the original
   manifest. Ground tiles use top-left [0,0]. See `../myassets/ART_BIBLE.md`.
2. **Backend scale:** No production backend-unit-to-pixel factor was selected.
   The local prototype measures its world directly in pixels: 48px tiles,
   145px/sec walk, 220px/sec run. Its observer normalizes positions using
   `2496 / bootstrap.world.width` for X and `1824 / bootstrap.world.height` for Y;
   this diagnostic normalization is not a shared unit contract. Source inspection
   confirms backend speed `MOVE_STEP * TICK_RATE_HZ = 1 * 20 = 20 units/sec` and
   radius 0.35 units. At 48px/unit the current walk speed would be 960px/sec, which
   is unsuitable for this presentation. **Proposal only:** 8 units/tile gives
   6px/unit and 120px/sec walking, but radius becomes only 2.1px and would require
   a footprint/radius review. Alternatively 1 unit/tile matches a 16.8px radius but
   requires an explicit backend walk-speed adjustment to approximately 3 units/sec
   for 144px/sec. Neither alternative is implemented or promoted to a decision.
3. **Map format/location:** No shared authored map exists. Current exploratory
   layout is procedural/hardcoded in `world.py` (52 x 38 tiles, 2496 x 1824px).
   Local Y points down; Arcade renders it with negated Y. Building collision is
   rectangular; resource collision is circular. This must not be copied into the
   production backend as an implicit map contract. **Proposed location only:**
   `world_data/maps2d/starter_village.json`, with a small custom JSON schema per
   C-003. Directory/file have not been created.
4. **Asset status:** see the category table below. Finished means prepared for
   prototype use, not verified as production/shipping-ready.

## Asset categories

| Category | Prepared | Missing / provisional |
| --- | --- | --- |
| Terrain | Grass, brick paving, stone paving; locally generated water and sand | Seamless biome/shore transition sets, autotile rules, interiors |
| Props/nature | 14 reused crops; generated oak/pine/boulders/berries/campfire/well | Forge/smith tools, material piles, inventory icons, animals; precise generated foot calibration |
| Buildings | 4 wall and 2 roof pieces; 2 houses assembled at runtime | Authored footprints/anchors, interiors, portal states, open/closed doors |
| Characters | 4 reused four-direction walk sheets; prototype uses elf and stalker | New licensed body templates/palette variants |
| Animations | Walk/idle layouts and six-frame sconce | Talk/attack/hit/down/death; campfire animation |
| Portraits | None prepared in myassets | Named NPC portraits; existing pack faces were not imported |

Generated nature atlas: 1536 x 1024; 3 x 2 cells, each 512 x 512. Cropped sizes and
native pivots are:

| Sprite | Cropped native size | Native bottom-center pivot | Prototype render height |
| --- | --- | --- | --- |
| Oak | 467 x 480 | [233.5,480] | 185px |
| Pine | 324 x 479 | [162,479] | 205px |
| Boulders | 384 x 260 | [192,260] | 73px |
| Berry bush | 397 x 450 | [198.5,450] | 66px |
| Campfire | 314 x 353 | [157,353] | 84px |
| Well | 365 x 441 | [182.5,441] | 145px |

Exact atlas regions, aspect-scaled widths, tool/source/prompt links, and license
status are recorded in `../myassets/generated/manifest.json`. These are measured
bounding pivots, not production ground-contact calibration. Berry top-edge alpha
remnants require a later isolated-sprite pass. Houses are assembled in memory at
240 x 336, pivot [120,336], then displayed at 288px high. They are not standalone
exported house PNGs. Reused prop dimensions/pivots are in `../myassets/manifest.json`.

## C-003 confirmation/amendment — proposal, not a user decision

Agree with the proposed custom JSON and split: this worker owns sprite references
and art-facing layers; Claude/backend owns Python schema validation and loading.
No schema or loader changes have been made by this worker.

Suggested precise amendments for agreement before implementation:

- Add `coordinate_system: "top_left_x_right_y_down"`. All `position`, wall `min/max`,
  and portal/anchor positions use backend units. Tile indices use col/row. Godot
  maps backend [x,y] to Vector2(x,y) times the derived pixel factor, without an
  independent Y inversion.
- Derive `pixels_per_unit = tile_size_px / units_per_tile`; do not also store an
  independently editable factor. Keep tile_size_px=48; units_per_tile remains open
  for the speed/radius/footprint decision described above.
- Add `sprite_id` to entity/decor records and stable tile IDs or a tileset mapping
  to terrain layers. Resolve IDs against both the reused and generated manifests.
- Specify row-major terrain arrays and the extent of each layer, validated against
  `size_tiles`. Decorations explicitly declare noninteractive/noncolliding status.
- Keep collision boxes in backend units with `id`, `min`, `max` as in wall_boxes.
  Preserve optional `height` for compatibility, ignored by Godot 2D. Backend loader
  exports these as the existing spatial contract's `boxes`. Author colliding
  footprint boxes directly; do not derive them from opaque sprite pixels.
- Validate unique IDs within each collection; link footprint boxes to stable
  entity IDs using an explicit owner field rather than conflating box and entity
  identity. Validate cross-references, anchors outside expanded collision boxes,
  reachability using the agreed actor radius, and portal targets/entry anchors.
- Use `from_anchor`, `to_map`, and `to_anchor` for portal references. Include the
  declared map revision in bootstrap and check it before accepting client display.

These are recommendations for the coordinator to relay; C-002/C-003 remain open
for the production unit contract and schema decision. This worker did not append
scratchpad entries, alter Claude entries, or modify coordinator-owned documents.

## Generation and license provenance

- One built-in imagegen nature atlas; exact full prompt in
  `../myassets/generated/generation.json`. No reference art was supplied to the
  generation request. Its alpha was checked: RGBA 1536 x 1024, range 0–253,
  933,853 fully transparent pixels. Generated-output terms have not been separately
  verified here; the generated manifest labels that status explicitly.
- User then requested local generation via `voiceimage`. Reused installed
  Qwen-Image 2.1 Q4_K_M, Qwen3VL text encoder, and VAE through stable-diffusion.cpp
  sd-cli.exe. No OpenAI image API call for these candidates. RTX 4060 CUDA; 512 x
  512, 32 Euler steps, CFG 6, seeds 1006/1007/1008. Each generation about 42–44sec
  according to its engine log, plus model loading.
- Water v1 rejected: decorative border caused visible repeated squares. Water v2
  and sand v1 accepted for prototype use; original files preserved. Exact prompts,
  settings, source, and status are in the adjacent PNG.json files. Approval record
  is `../myassets/generated/approved.json`. Actual coast screenshot inspected.
- `generate_local.ps1`, `generate_local_batch.ps1`, and `local_asset_jobs.json`
  provide reproducible sequential generation without editing voiceimage. Existing
  outputs are protected; batch skips them. New jobs need new versioned filenames.
- Hypnobius environment terms are included under `../myassets/licenses`, allow game
  use/modification and prohibit asset-pack redistribution. Original source copies
  were checked byte-for-byte. Reused Adventurer Pack character license is absent.
- Local GGUF/model license and generated-output terms were not independently
  verified. Existing deployment README identifies models but supplies no license.
  `Outside_C.png` was not imported because origin/terms were not supplied.

## Files changed by this worker

Only new files under `myassets/` and `2D1006newstart/`, and follow-up edits to those
new files. `myassets`: 5 copied sheets, 3 terrain crops, 14 prop crops, 6 building
pieces, 4 character sheets, original license/usage notes, catalog, build script,
README, reused manifest; generated atlas, 3 local candidates plus metadata,
approval record, generated manifest, and ART_BIBLE.

`2D1006newstart`: main.py, world.py, assets.py, backend.py, launch.ps1,
requirements.txt, .gitignore, README, this report, generate_local.ps1,
generate_local_batch.ps1, local_asset_jobs.json, verify_ui.py, 2 test files,
screenshots/opening.png, coast.png, dialogue.png, help.png. Ignored runtime logs,
bytecode, and isolated test scratch saves exist. No changes were made to global
requirements or to legacy/shared state. The initial repo already had substantial
uncommitted work belonging to other sessions, preserved untouched.

## Checks actually run

- Asset catalog script validated 33 reused asset entries: dimensions, crop bounds,
  copied-file SHA256 hashes, and character/sconce frame grids. Catalog inspected.
- Nine unittest checks passed: deterministic world/clear spawn, diagonal speed,
  water/house collision, complete task and no duplicate consumption, depletion and
  crate loot/eating, save/load roundtrip including stocks, invalid save position,
  GET-only observer with a local HTTP fixture, rejection of nonloopback URLs.
- Real Arcade callback smoke passed: movement, pause, F5/F9 save/load, Mira dialogue
  open/close, help, zoom, resize. Repeated after viewport/minimap changes. Test saves
  are separate from player saves and from Eden persistence.
- Real GPU screenshots inspected: opening, coast, dialogue, help. Captures use
  Arcade/OpenGL, not an HTML/mock image. Houses and generated nature visibly render.
- Minimap rendering bottleneck corrected by caching it as one texture. A local CPU
  draw-submission sample decreased from ~182.7ms to ~7.7ms; this is not an FPS or
  end-to-end benchmark. No release performance gate is claimed.
- All seven Python source/test files compiled. Sequential batch skip behavior
  verified against existing local candidates. No runtime errors logged at launch.
- No real Eden backend was running/responding at localhost:8002 during the probe;
  observer integration is fixture-tested, not production-server verified.

## Limitations and next bounded chunk

Snapshot confirmation and production scale/map decisions remain unresolved, so no
production migration or restructuring is started. Next asset-only chunk can
export separate atlas sprites with calibrated ground pivots, prepare forge/material
props, and generate named-resident portraits once names/style are provided. Prefer
local voiceimage candidates with manual review and full provenance. Once snapshot
and C-002/C-003 decisions are recorded, create the Godot 2D skeleton and consume one
shared authored map; do not port the prototype's local authoritative simulation or
normalized observer coordinates into the production client. No prediction/replay,
camera obstruction, NPC model integration, or post-Gate-H functionality was added.
