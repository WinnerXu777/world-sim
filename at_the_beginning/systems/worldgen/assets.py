"""The visual palette the generator may use, taken from what really exists in `myassets/`, and the list of everything missing.

Nothing here invents an asset. `verify_palette(myassets_root)` checks every path against the directory; the tests run it. Sizes and
pivots of sprites come from the manifests (`myassets/manifest.json`, `a1/manifest.json`, `a4/static_manifest.json`).
"""
from __future__ import annotations

from pathlib import Path

from .spec import (FOOT_ROCK, FOOT_RUIN, FOOT_WATER, TERRAIN_GRASS, TERRAIN_PAVING, TERRAIN_ROCK, TERRAIN_SAND, TERRAIN_WATER)

# layers[].palette: positive integer string -> path relative to myassets/
TERRAIN_PALETTE = {
    str(TERRAIN_GRASS): "terrain/grass.png",                      # 48x48, medieval_village pack
    str(TERRAIN_SAND): "generated/sand-local-v1.png",             # 512x512 source, approved.json render_size 48x48
    str(TERRAIN_WATER): "generated/water-local-v2.png",           # 512x512 source, approved.json render_size 48x48
    str(TERRAIN_ROCK): "terrain/flagstone_slate.png",             # STAND-IN for rock / mountain ground (48x48 procedural)
    str(TERRAIN_PAVING): "terrain/paving_stone.png",              # 48x48 ruin / shrine floor
}
FOOTPRINT_PALETTE = {
    str(FOOT_WATER): "generated/water-local-v2.png",
    str(FOOT_ROCK): "terrain/flagstone_slate.png",
    str(FOOT_RUIN): "buildings/wall_stone.png",                   # 96x96 stone wall tile from the village pack
}
DECORATION_PALETTE: dict = {}                                     # empty in chunk 0.1: no 48x48 overlay art exists (see GAPS)

# data.prop_palette: index -> sprite path (80 to 240 px freestanding sprites with a foot pivot)
PROP_SPRITES = (
    "a1/sprites/oak-a1-v1.png",                                   # 0  224x208 pivot [112,193]
    "a1/sprites/pine-a1-v1.png",                                  # 1  176x240 pivot [88,227]
    "a4/static/static-apple_tree-a4-v1.png",                      # 2  192x224 pivot [96,208]
    "a1/sprites/boulders-a1-v1.png",                              # 3  128x96  pivot [64,86]
    "a1/sprites/berry-bush-local-a1-v1.png",                      # 4  80x96   pivot [40,87]
    "a4/static/static-fern-a4-v1.png",                            # 5  80x80   pivot [40,68]
    "a4/static/static-green_fern-a4-v1.png",                      # 6  80x80   pivot [40,68]
    "a4/static/static-mushrooms-a4-v1.png",                       # 7  64x64   pivot [32,56]
    "a4/static/static-reeds-a4-v1.png",                           # 8  80x112  pivot [40,100]
    "a4/static/static-wildflowers-a4-v1.png",                     # 9  80x80   pivot [40,68]
    "a4/static/static-fallen_log-a4-v1.png",                      # 10 160x96  pivot [80,80]
    "a1/sprites/campfire-a1-v1.png",                              # 11 96x96   pivot [48,86]
)
P_OAK, P_PINE, P_APPLE, P_BOULDERS, P_BERRY, P_FERN, P_GREEN_FERN, P_MUSHROOMS, P_REEDS, P_FLOWERS, P_LOG, P_CAMPFIRE = range(12)

# Entities that name a sprite directly (authored shape `entities[].sprite`)
ENTITY_SPRITES = {
    "forest": PROP_SPRITES[P_OAK],
    "stone_outcrop": PROP_SPRITES[P_BOULDERS],
    "berry_patch": PROP_SPRITES[P_BERRY],
    "reed_bed": PROP_SPRITES[P_REEDS],
    "mushroom_patch": PROP_SPRITES[P_MUSHROOMS],
    "poi_camp": PROP_SPRITES[P_CAMPFIRE],
}
# wildlife species that have art in myassets/a4/static (others are table hooks without a sprite)
SPECIES_SPRITES = {
    "deer": "a4/static/static-deer-a4-v1.png",                    # 160x160 pivot [80,144]
    "goat": "a4/static/static-goat-a4-v1.png",                    # 128x128 pivot [64,112]
    "sheep": "a4/static/static-sheep-a4-v1.png",                  # 128x128 pivot [64,112]
}


def all_palette_paths() -> list[str]:
    paths = set(TERRAIN_PALETTE.values()) | set(FOOTPRINT_PALETTE.values()) | set(PROP_SPRITES)
    paths |= set(ENTITY_SPRITES.values()) | set(SPECIES_SPRITES.values())
    return sorted(paths)


def verify_palette(myassets_root) -> list[str]:
    """Paths the generator uses that are not files under `myassets_root` (empty list = all present)."""
    root = Path(myassets_root)
    return [p for p in all_palette_paths() if not (root / p).is_file()]


# Everything the generator wants and cannot draw today. `standin` says what 0.1 uses instead (may be "none").
# Sprite size / pivot follow the existing sets: trees and bushes are freestanding sprites with the pivot at the foot
# (bottom centre, a few px above the bottom edge), ground is 48x48 and periodic (no baked edges).
GAPS = [
    {"id": "G-TERRAIN-TRANSITIONS", "need": "Biome transition / autotile edge tiles: grass<->sand, sand<->water, grass<->rock, grass<->forest floor, "
     "inner and outer corners. 47-tile blob set per pair, or a 16-tile edge-bitmask set; 48x48 each, periodic along the shared edge.",
     "key": "data.edges (8-bit neighbour-difference mask per tile) is already emitted", "standin": "hard tile edges"},
    {"id": "G-WATER-SAND-48", "need": "48x48 exported copies of water and sand (the approved sources `generated/water-local-v2.png` and "
     "`generated/sand-local-v1.png` are 512x512 and the manifest has no `terrain/` entry for them), plus a SHALLOW water / ford tile and a deep-water tile; "
     "optional 4-frame ripple animation.", "key": "palette ids 2 and 3", "standin": "512 px sources scaled by the client; fords drawn as sand"},
    {"id": "G-GROUND-TYPES", "need": "More ground tiles, 48x48 periodic: dirt / forest floor (leaf litter), mud / marsh, hot desert sand (distinct from shore sand), "
     "snow / tundra, mountain rock ground and a cliff-face edge tile, worn path.", "key": "biomes forest, wetland, desert, highland, peak",
     "standin": "forest, wetland on grass; desert on shore sand; highland and peak on `terrain/flagstone_slate.png`"},
    {"id": "G-DECOR-TILES", "need": "Tile-sized (48x48) decoration overlays for the `decoration` layer: grass tufts, pebbles, shore foam, wet-sand edge, "
     "flower patches, footpath stones.", "key": "decoration layer (empty in 0.1)", "standin": "none; scatter sprites in data.props"},
    {"id": "G-TREES", "need": "More tree species and states: birch, dead/bare tree, palm (desert), young sapling, cut stump (depleted), dense-thicket sprite. "
     "Same footprint as `a1/sprites/oak-a1-v1.png` (about 224x208 px, foot pivot [112,193]); stump 64x64 pivot [32,56].",
     "key": "kind forest, data.props", "standin": "oak, pine, apple tree"},
    {"id": "G-ORE-STONE", "need": "Ore and stone nodes with a depleted state: stone node, iron ore, copper ore, coal seam, clay bank. 96x96 each, foot pivot [48,86].",
     "key": "kinds ore_vein, stone_outcrop", "standin": "boulders for stone_outcrop; ore_vein has no sprite"},
    {"id": "G-CROPS", "need": "Crop growth stages (sprout, half, ripe, harvested) for wheat and one root crop, plus a tilled-plot tile; 48x48 tile aligned. "
     "Not used by the generator yet; listed because farming needs them.", "key": "none yet", "standin": "none"},
    {"id": "G-ANIMALS", "need": "Wildlife sprites: wolf, boar, rabbit, fox, bird, fish (in-water silhouette). Match `a4/static` animals: 128x128, foot pivot [64,112] "
     "(rabbit and bird 64x64 pivot [32,56]); ideally 4-direction walk strips like `characters/`.", "key": "data.spawns species",
     "standin": "deer, goat, sheep only; other species are table hooks with no sprite"},
    {"id": "G-POI-ART", "need": "Points of interest: ruined wall segments (96x96 and corner pieces), broken pillar 64x96, shrine 96x128 pivot [48,118], "
     "cave entrance 144x112 pivot [72,104], ruined-camp props (tent, bedroll).", "key": "kinds poi_ruin, poi_shrine, poi_cave",
     "standin": "paving floor + `buildings/wall_stone.png` footprint for ruins; camp uses the campfire; shrine and cave have no sprite"},
    {"id": "G-RESOURCE-MARKERS", "need": "Fish-spot ripple marker 48x48; harvest-state variants for berry bush (bare), mushrooms (picked), reeds (cut).",
     "key": "kinds fish_spot, berry_patch, mushroom_patch, reed_bed", "standin": "fish_spot has no sprite"},
    {"id": "G-BRIDGES", "need": "Not missing but unused: `a4/static/static-stone_bridge-a4-v1.png` (240x160) and `static-wood_pier-a4-v1.png` (192x160) fit river fords; "
     "placing them needs path-aware logic that belongs to a later generator version.", "key": "kind ford", "standin": "ford tiles are walkable sand"},
]


def gaps_markdown() -> str:
    rows = ["| id | need (size / pivot) | where it plugs in | 0.1 stand-in |", "| --- | --- | --- | --- |"]
    for g in GAPS:
        rows.append(f"| {g['id']} | {g['need']} | {g['key']} | {g['standin']} |")
    return "\n".join(rows)
