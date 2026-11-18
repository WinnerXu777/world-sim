"""
genesis_config.py
=================
Single source of truth for all simulation constants.
Imported by every other module — never hardcode here.

Architecture overview
─────────────────────
h_tensor  (MAX_HUMANS,   32)  — human agents only
m_tensor  (MAX_ENTITIES, 32)  — entity registry: natural features, animals,
                                 structures.  Row = one named entity.
                                 Free slot = M_TYPE == 0.

Background tile grid (GRID_W × GRID_H)
  Exists only as a rendering / spatial-lookup concept.
  NOT stored in m_tensor.  map_geo.py precomputes a tile_mask per entity
  and a flat TILE_TO_ENTITY dict so per-tick "which entity is agent in?"
  is an O(1) dict lookup — no polygon math in the hot loop.

m_tensor column layout
  Shared cols 0–5 apply to ALL entity types.
  Cols 6–31 are typed by M_TYPE and documented in MAP_SCHEMA below.
  Always filter by M_TYPE before reading typed cols.

M_TYPE value ranges
  0       : free slot
  1–19    : natural features  (lake, forest, sea-region, mountain, beach, grass…)
  20–39   : structures        (house, village, farm, well…)
  40–79   : animals           (sheep, tiger, deer, wolf…)
  80–127  : world-agent types (assigned at runtime)
"""

# =============================================================================
# MAP / GRID DIMENSIONS  (background rendering grid — NOT m_tensor rows)
# =============================================================================
MAP_WIDTH  = 1200
MAP_HEIGHT = 900
TILE_SIZE  = 8                          # px per background tile
GRID_W     = MAP_WIDTH  // TILE_SIZE    # 150
GRID_H     = MAP_HEIGHT // TILE_SIZE    # 112
MAX_BG_TILES = GRID_W * GRID_H         # 16 800  — used only in map_geo.py masks

# =============================================================================
# ENTITY REGISTRY SIZE
# =============================================================================
MAX_ENTITIES = 1024   # m_tensor rows — natural features + animals + structures
MAX_HUMANS   = 100    # h_tensor rows
HUMAN_TENSOR_COLS = 32
MAP_TENSOR_COLS   = 32

# =============================================================================
# SIMULATION TIMING
# =============================================================================
TICKS_PER_YEAR     = 600
TICK_RATE_HZ       = 20
TICK_SLEEP         = 1.0 / TICK_RATE_HZ
AGENT_FRAME_EVERY  = 4
MAP_DELTA_EVERY    = 20
SNAPSHOT_EVERY     = AGENT_FRAME_EVERY
MAP_SNAPSHOT_EVERY = MAP_DELTA_EVERY
PROTOCOL_VERSION   = 1

# =============================================================================
# MOVEMENT
# =============================================================================
MOVE_STEP        = 1.0
ATTRACTION_FORCE = 5.0

# =============================================================================
# H_TENSOR — HUMAN TENSOR COLUMNS   shape = (MAX_HUMANS, 32)
# =============================================================================

# ── Shared 0–3 ───────────────────────────────────────────────────────────────
X    = 0
Y    = 1
TYPE = 2    # AGENT_TYPE_* constants below
HP   = 3

# ── Character 4–9 ────────────────────────────────────────────────────────────
H_STRENGTH   = 4
H_FERTILITY  = 5
H_AGGRESSION = 6
H_STAMINA    = 7
H_INFECTION  = 8
H_SHELTER    = 9

# ── Life 10–19 ───────────────────────────────────────────────────────────────
H_SEX                = 10
H_AGE                = 11
H_LIFE_EXP           = 12
H_COOLDOWN           = 13
HUNGER               = 14
THREAT               = 15
MOOD                 = 16
CRITICAL_HEALTH      = 17
ESCALATION_FLAG      = 18
ACQUIRED_INSTINCT_MASK = 19

# ── Social / carry 20–23 ─────────────────────────────────────────────────────
H_CARRYING         = 20
H_SKILL            = 21
H_TRIBE            = 22
H_PARENT_INSTINCTS = 23
THIRST             = 24
# Words 1 and 2 of the 64-bit acquired-instinct mask and of its parent copy (G-D0-2). float32 holds integers exactly only
# below 2**24, so the mask is split into 24-bit words: bits 0..23 in col 19 / 23 (above), bits 24..47 in 25 / 27, bits 48..63
# in 26 / 28. See harness/instinct_bits.py. Four of the seven reserved columns are used; 29 is H_SPACE, 30 is H_RESTRAINED (defend Phase 1) and only 31 is still free.
ACQUIRED_INSTINCT_MASK_1 = 25
ACQUIRED_INSTINCT_MASK_2 = 26
H_PARENT_INSTINCTS_1     = 27
H_PARENT_INSTINCTS_2     = 28
# D1 (spaces): the space a human is in; 0 = the overworld (every row written before spaces existed reads 0). See 1008_spaces_window_design.md.
H_SPACE = 29
# 1008 defend Phase 1: ticks a human stays restrained (pinned in place by harness/restraint.py, EDEN_RESTRAINT); 0 = free, which every earlier row reads.
H_RESTRAINED = 30
# 31 reserved

# Human TYPE value
AGENT_TYPE_EMPTY = 0
AGENT_TYPE_HUMAN = 1

# =============================================================================
# M_TENSOR — ENTITY TENSOR COLUMNS   shape = (MAX_ENTITIES, 32)
# =============================================================================

# ── Shared cols 0–5  (ALL entity types) ──────────────────────────────────────
CX       = 0   # centre x  (px)  — updated each tick for mobile entities
CY       = 1   # centre y  (px)
M_TYPE   = 2   # entity type integer  (0 = free slot)
M_HP     = 3   # health / integrity
SCALE    = 4   # visual radius (px) — drives MAP_GEO circle size
SPRITE_ID = 5  # rendering hint for future sprite atlas

# ── Natural feature state cols 6–9  (M_TYPE 1–19) ───────────────────────────
M_FERTILITY = 6   # soil fertility    [0–100]
M_ELEVATION = 7   # normalised height [0.0–1.0]
M_BURNING   = 8   # fire tick counter (0 = not burning)
M_FLOODED   = 9   # flood flag        [0/1]

# ── Animal life cols 6–12  (M_TYPE 40–79) ───────────────────────────────────
# (cols 6–12 reused under animal types — MAP_SCHEMA documents this)
A_AGE        = 6
A_LIFE_EXP   = 7
A_SEX        = 8   # 0=male 1=female
A_COOLDOWN   = 9
A_HUNGER     = 10
A_AGGRESSION = 11  # [0–1]  for predators
A_THIRST     = 12
# 17–29 reserved for species-specific attrs (13–16 are the resource-node columns below, 30–31 are M_GEN / M_SPACE)
# D1/D6: shared by every entity type. M_SPACE 0 = the overworld; M_GEN is a generation counter that survives a slot release (window slot reuse).
M_GEN   = 30
M_SPACE = 31

# ── Structure state cols 6–9  (M_TYPE 20–39) ────────────────────────────────
S_DURABILITY      = 6   # [0–100]
S_SHELTER_CAP     = 7   # max occupants
S_OCCUPANT_COUNT  = 8
S_BUILD_PROGRESS  = 9   # [0–100]  100 = complete

# ── Shared resource col 10 for natural features ───────────────────────────────
M_RESOURCE_FOOD  = 10   # food units (grass/forest/lake/beach)
M_LAVA_COOLING   = 10   # ticks until lava → barren  (overloads col 10 for M_LAVA)
M_RESOURCE_WATER = 11   # water units (lake/well/farm irrigation)
M_GROWTH_RATE    = 12   # typed growth / replenish rate

# =============================================================================
# KNOWN M_TYPE VALUES
# =============================================================================

# Natural features 1–19
M_LAKE     = 1
M_FOREST   = 2
M_SEA      = 3    # large sea region entity
M_MOUNTAIN = 4
M_BEACH    = 5
M_GRASS    = 6
M_LAVA     = 7
M_BARREN   = 8
# 9–19 available

# Structures 20–39
M_HOUSE   = 20
M_VILLAGE = 21
M_FARM    = 22
M_WELL    = 23
M_WALL    = 24
M_STORAGE_CASE = 25
M_MAP_OBJECT = 26   # inert interactive object instantiated from an authored map file (forge, anvil, door, ...)
# G-005: a resource node instantiated from an authored map (berry bush, ore pile, fish spot, ...); see systems/map/resources.py
M_RESOURCE_NODE = 27
M_NODE_KIND     = 13   # 1 berries 2 wood 3 stone 4 ore 5 fish 6 reeds 7 mushrooms
M_NODE_STOCK    = 14   # material stock units (non-edible nodes; edible nodes keep their stock in M_RESOURCE_FOOD)
M_NODE_CAP      = 15   # maximum stock
M_DEPLETED_TICK = 16   # tick the stock reached 0, -1 while stocked
# 28–39 available

# Animals 40–79
M_SHEEP = 40
M_DEER  = 41
M_TIGER = 42
M_WOLF  = 43
M_FISH  = 44   # lake fish — mobile within lake radius
# 45–79 available

# World-agent dynamic types 80+
# Assigned at runtime — add to MAP_SCHEMA when used.

# Convenience sets
NATURAL_TYPES   = set(range(1, 20))
STRUCTURE_TYPES = set(range(20, 40))
ANIMAL_TYPES    = set(range(40, 80))
IMPASSABLE      = {M_SEA, M_MOUNTAIN, M_LAVA}
HABITABLE       = {M_GRASS, M_FOREST, M_BEACH, M_LAKE}

# =============================================================================
# MAP_SCHEMA  — attribute documentation per M_TYPE
# Served via /get_schema.  Adding a new entity type = add one dict entry.
# Zero tensor changes required.
# =============================================================================
MAP_SCHEMA: dict[int, dict] = {
    M_LAKE: {
        "label": "lake", "mobile": False,
        "attrs": [
            {"col": M_FERTILITY,    "name": "fertility",   "dtype": "float"},
            {"col": M_ELEVATION,    "name": "elevation",   "dtype": "float"},
            {"col": M_BURNING,      "name": "burning",     "dtype": "int"},
            {"col": M_FLOODED,      "name": "flooded",     "dtype": "int"},
            {"col": M_RESOURCE_FOOD,"name": "fish_count",  "dtype": "float"},
            {"col": M_RESOURCE_WATER,"name": "water_stock","dtype": "float"},
            {"col": M_GROWTH_RATE,  "name": "replenish_rate","dtype": "float"},
        ],
    },
    M_FOREST: {
        "label": "forest", "mobile": False,
        "attrs": [
            {"col": M_FERTILITY,    "name": "fertility",    "dtype": "float"},
            {"col": M_ELEVATION,    "name": "elevation",    "dtype": "float"},
            {"col": M_BURNING,      "name": "fire_ticks",   "dtype": "int"},
            {"col": M_FLOODED,      "name": "flooded",      "dtype": "int"},
            {"col": M_RESOURCE_FOOD,"name": "tree_density", "dtype": "float"},
        ],
    },
    M_GRASS: {
        "label": "grassland", "mobile": False,
        "attrs": [
            {"col": M_FERTILITY,    "name": "fertility",  "dtype": "float"},
            {"col": M_RESOURCE_FOOD,"name": "food",       "dtype": "float"},
        ],
    },
    M_BEACH: {
        "label": "beach", "mobile": False,
        "attrs": [
            {"col": M_RESOURCE_FOOD,"name": "food",       "dtype": "float"},
        ],
    },
    M_MOUNTAIN: {
        "label": "mountain", "mobile": False,
        "attrs": [
            {"col": M_ELEVATION, "name": "elevation", "dtype": "float"},
            {"col": M_HP,        "name": "stability",  "dtype": "float"},
        ],
    },
    M_LAVA: {
        "label": "lava", "mobile": False,
        "attrs": [
            {"col": M_LAVA_COOLING, "name": "cooling_ticks", "dtype": "int"},
        ],
    },
    M_BARREN: {
        "label": "barren", "mobile": False,
        "attrs": [],
    },
    M_SEA: {
        "label": "sea", "mobile": False,
        "attrs": [
            {"col": M_FLOODED, "name": "flooded", "dtype": "int"},
        ],
    },
    M_HOUSE: {
        "label": "house", "mobile": False,
        "attrs": [
            {"col": S_DURABILITY,     "name": "durability",      "dtype": "float"},
            {"col": S_SHELTER_CAP,    "name": "shelter_capacity","dtype": "int"},
            {"col": S_OCCUPANT_COUNT, "name": "occupants",       "dtype": "int"},
            {"col": S_BUILD_PROGRESS, "name": "build_progress",  "dtype": "float"},
        ],
    },
    M_VILLAGE: {
        "label": "village", "mobile": False,
        "attrs": [
            {"col": S_DURABILITY,    "name": "durability",       "dtype": "float"},
            {"col": S_SHELTER_CAP,   "name": "shelter_capacity", "dtype": "int"},
            {"col": S_OCCUPANT_COUNT,"name": "occupants",        "dtype": "int"},
        ],
    },
    M_FARM: {
        "label": "farm", "mobile": False,
        "attrs": [
            {"col": S_DURABILITY,    "name": "durability",      "dtype": "float"},
            {"col": S_BUILD_PROGRESS,"name": "build_progress",  "dtype": "float"},
            {"col": M_RESOURCE_FOOD, "name": "food_stock",      "dtype": "float"},
            {"col": M_RESOURCE_WATER,"name": "water_stock",     "dtype": "float"},
            {"col": M_GROWTH_RATE,   "name": "growth_rate",     "dtype": "float"},
        ],
    },
    M_WELL: {
        "label": "well", "mobile": False,
        "attrs": [
            {"col": S_DURABILITY,    "name": "durability",      "dtype": "float"},
            {"col": S_BUILD_PROGRESS,"name": "build_progress",  "dtype": "float"},
            {"col": M_RESOURCE_WATER,"name": "water_stock",     "dtype": "float"},
            {"col": M_GROWTH_RATE,   "name": "replenish_rate",  "dtype": "float"},
        ],
    },
    M_WALL: {
        "label": "wall", "mobile": False,
        "attrs": [
            {"col": S_DURABILITY,    "name": "durability",      "dtype": "float"},
            {"col": S_BUILD_PROGRESS,"name": "build_progress",  "dtype": "float"},
        ],
    },
    M_STORAGE_CASE: {
        "label": "storage_case", "mobile": False,
        "attrs": [
            {"col": S_DURABILITY,     "name": "durability",      "dtype": "float"},
            {"col": S_SHELTER_CAP,    "name": "capacity_hint",   "dtype": "int"},
            {"col": S_BUILD_PROGRESS, "name": "build_progress",  "dtype": "float"},
        ],
    },
    M_MAP_OBJECT: {
        "label": "map_object", "mobile": False,
        "attrs": [
            {"col": S_DURABILITY,     "name": "durability",      "dtype": "float"},
            {"col": S_BUILD_PROGRESS, "name": "build_progress",  "dtype": "float"},
        ],
    },
    M_SHEEP: {
        "label": "sheep", "mobile": True,
        "attrs": [
            {"col": A_AGE,        "name": "age",        "dtype": "float"},
            {"col": A_LIFE_EXP,   "name": "life_exp",   "dtype": "float"},
            {"col": A_SEX,        "name": "sex",        "dtype": "int"},
            {"col": A_COOLDOWN,   "name": "cooldown",   "dtype": "float"},
            {"col": A_HUNGER,     "name": "hunger",     "dtype": "float"},
            {"col": A_AGGRESSION, "name": "aggression", "dtype": "float"},
            {"col": A_THIRST,     "name": "thirst",     "dtype": "float"},
        ],
    },
    M_DEER: {
        "label": "deer", "mobile": True,
        "attrs": [
            {"col": A_AGE,      "name": "age",      "dtype": "float"},
            {"col": A_LIFE_EXP, "name": "life_exp", "dtype": "float"},
            {"col": A_SEX,      "name": "sex",      "dtype": "int"},
            {"col": A_COOLDOWN, "name": "cooldown", "dtype": "float"},
            {"col": A_HUNGER,   "name": "hunger",   "dtype": "float"},
            {"col": A_THIRST,   "name": "thirst",   "dtype": "float"},
        ],
    },
    M_TIGER: {
        "label": "tiger", "mobile": True,
        "attrs": [
            {"col": A_AGE,        "name": "age",        "dtype": "float"},
            {"col": A_LIFE_EXP,   "name": "life_exp",   "dtype": "float"},
            {"col": A_SEX,        "name": "sex",        "dtype": "int"},
            {"col": A_COOLDOWN,   "name": "cooldown",   "dtype": "float"},
            {"col": A_HUNGER,     "name": "hunger",     "dtype": "float"},
            {"col": A_AGGRESSION, "name": "aggression", "dtype": "float"},
            {"col": A_THIRST,     "name": "thirst",     "dtype": "float"},
        ],
    },
    M_WOLF: {
        "label": "wolf", "mobile": True,
        "attrs": [
            {"col": A_AGE,        "name": "age",        "dtype": "float"},
            {"col": A_LIFE_EXP,   "name": "life_exp",   "dtype": "float"},
            {"col": A_SEX,        "name": "sex",        "dtype": "int"},
            {"col": A_COOLDOWN,   "name": "cooldown",   "dtype": "float"},
            {"col": A_HUNGER,     "name": "hunger",     "dtype": "float"},
            {"col": A_AGGRESSION, "name": "aggression", "dtype": "float"},
            {"col": A_THIRST,     "name": "thirst",     "dtype": "float"},
        ],
    },
    M_FISH: {
        "label": "fish", "mobile": True,
        "attrs": [
            {"col": A_AGE,        "name": "age",        "dtype": "float"},
            {"col": A_LIFE_EXP,   "name": "life_exp",   "dtype": "float"},
            {"col": A_SEX,        "name": "sex",        "dtype": "int"},
            {"col": A_COOLDOWN,   "name": "cooldown",   "dtype": "float"},
            {"col": A_HUNGER,     "name": "hunger",     "dtype": "float"},
            {"col": A_AGGRESSION, "name": "aggression", "dtype": "float"},
            {"col": A_THIRST,     "name": "thirst",     "dtype": "float"},
        ],
    },
}

# =============================================================================
# ANIMAL SPECIES PARAMETERS  (keyed by M_TYPE)
# =============================================================================
ANIMAL_LIFE_EXP: dict[int, tuple[float, float]] = {
    M_SHEEP: (6.0,  12.0),
    M_DEER:  (8.0,  16.0),
    M_TIGER: (10.0, 20.0),
    M_WOLF:  (8.0,  18.0),
    M_FISH:  (2.0,  6.0),
}
ANIMAL_SCALE: dict[int, float] = {   # visual radius in px
    M_SHEEP: 5.0,
    M_DEER:  6.0,
    M_TIGER: 7.0,
    M_WOLF:  6.0,
    M_FISH:  3.0,
}
ANIMAL_BASE_AGGRESSION: dict[int, float] = {
    M_SHEEP: 0.0,
    M_DEER:  0.0,
    M_TIGER: 0.9,
    M_WOLF:  0.7,
    M_FISH:  0.0,
}
ANIMAL_MOVE_STEP: dict[int, float] = {
    M_SHEEP: 2.0,
    M_DEER:  3.5,
    M_TIGER: 4.0,
    M_WOLF:  3.5,
    M_FISH:  1.5,
}
ANIMAL_PREY: dict[int, set] = {   # which M_TYPEs this animal hunts
    M_TIGER: {M_SHEEP, M_DEER, AGENT_TYPE_HUMAN},
    M_WOLF:  {M_SHEEP, M_DEER},
}
ANIMAL_PREDATOR_ATTACK_DAMAGE = 15.0
ANIMAL_PREDATOR_RANGE         = 20.0
ANIMAL_HUNGER_TICK_RATE       = 0.03
ANIMAL_THIRST_TICK_RATE       = 0.04
ANIMAL_MATE_RADIUS            = 12.0
ANIMAL_MATURE_TICKS           = 2.0   # years

# =============================================================================
# ENTITY SCALE DEFAULTS FOR NATURAL FEATURES  (radius in px)
# =============================================================================
NATURAL_SCALE: dict[int, tuple[float, float]] = {   # (min_r, max_r)
    M_LAKE:     (40,  100),
    M_FOREST:   (60,  150),
    M_MOUNTAIN: (50,  120),
    M_BEACH:    (40,   90),
    M_GRASS:    (50,  130),
    M_LAVA:     (20,   60),
    M_BARREN:   (30,   80),
}

# =============================================================================
# FIRE
# =============================================================================
FIRE_SPREAD_RADIUS = 80.0    # px — how close two forest entities must be to spread
FIRE_SPREAD_PROB   = 0.04
FIRE_HP_DAMAGE     = 4.0
FIRE_BURN_TICKS    = 80

# =============================================================================
# FLOOD
# =============================================================================
FLOOD_HP_DAMAGE   = 3.0
FLOOD_EXPAND_PROB = 0.25

# =============================================================================
# STORM
# =============================================================================
STORM_DISPLACEMENT = 50.0
STORM_HP_DAMAGE    = 8.0
STORM_MOOD_PENALTY = 25.0
STORM_THREAT_RAISE = 30.0

# =============================================================================
# EARTHQUAKE
# =============================================================================
QUAKE_ENTITY_DAMAGE = 60.0
QUAKE_AGENT_DAMAGE  = 30.0
QUAKE_RUBBLE_PROB   = 0.4

# =============================================================================
# VOLCANO
# =============================================================================
VOLCANO_INNER_RADIUS = 60.0
VOLCANO_OUTER_RADIUS = 160.0
VOLCANO_LAVA_COOLING = 300
LAVA_HP_DAMAGE       = 15.0

# =============================================================================
# HUMAN GAMEPLAY THRESHOLDS
# =============================================================================
MATURE_AGE               = 18.0
PROXIMITY_MATE_RADIUS    = 8.0
PROXIMITY_THREAT_RADIUS  = 15.0
COOLDOWN_DECAY_RATE      = 1.0 / TICKS_PER_YEAR
HUNGER_TICK_RATE         = 0.05
THIRST_TICK_RATE         = 0.07
THIRST_DAMAGE_RATE       = 2.5
# D-005: the legacy frontier expansion (instinct_frontier_expand, tool_expand_world_edge) is frozen: kept in the repo, not registered,
# not offered to the tool registry / NL parser, and refused by name with reason "legacy_frozen". Flip to False to re-enable.
FREEZE_LEGACY_FRONTIER   = True
FROZEN_FRONTIER_TOOLS    = ("instinct_frontier_expand", "tool_expand_world_edge")
CRITICAL_HEALTH_THRESHOLD = 20.0
ESCALATION_THRESHOLD     = 2.0

AGGRESSION_THRESHOLD   = 0.5
ATTACK_RANGE           = 14.0
ATTACK_DAMAGE          = 20.0
ATTACK_STAMINA_COST    = 8.0
HEAL_RATE              = 0.3
STAMINA_RECOVER_RATE   = 1.5
STAMINA_DRAIN_MOVE     = 0.2
SAFE_REPRO_HUNGER_MAX  = 55.0
SAFE_REPRO_THIRST_MAX  = 55.0
SAFE_REPRO_THREAT_MAX  = 45.0
SAFE_REPRO_HP_MIN      = 45.0
SAFE_REPRO_STAMINA_MIN = 25.0

SURVIVAL_SCAN_RADIUS   = 220.0
MIGRATION_SCAN_RADIUS  = 480.0
HAZARD_AVOID_RADIUS    = 120.0
PREDATOR_ALERT_RADIUS  = 90.0
FOOD_SEEK_THRESHOLD    = 50.0
WATER_SEEK_THRESHOLD   = 45.0
SHELTER_SEEK_THREAT    = 45.0
SURVIVAL_NAV_WEIGHT    = 7.0
HAZARD_FLEE_WEIGHT     = 10.0
SOCIAL_NAV_WEIGHT      = 2.5
TRIBE_COHESION_RADIUS  = 70.0
CROWDING_RADIUS        = 18.0
CROWDING_LIMIT         = 4
THREAT_DECAY_RATE      = 0.6
MOOD_RECOVERY_RATE     = 0.3

INFECTION_SPREAD_RADIUS  = 10.0
INFECTION_SPREAD_RATE    = 4.0
INFECTION_DAMAGE_RATE    = 1.0
INFECTION_THRESHOLD      = 60.0
INFECTION_NATURAL_DECAY  = 0.1
QUARANTINE_COOLDOWN_YRS  = 5.0

# =============================================================================
# EATING / RESOURCE
# =============================================================================
EAT_HUNGER_RESTORE   = 20.0
EAT_RESOURCE_COST    = 1.0
RESOURCE_REGROW_RATE = 0.015
MAX_ENTITY_FOOD      = 100.0
INITIAL_FOOD_GRASS   = 40.0
INITIAL_FOOD_FOREST  = 80.0
INITIAL_FOOD_BEACH   = 15.0
INITIAL_FOOD_LAKE    = 30.0

# =============================================================================
# WATER / FARM RESOURCE
# =============================================================================
DRINK_THIRST_RESTORE      = 35.0
DRINK_RESOURCE_COST       = 1.0
DRINK_PROXIMITY_RADIUS    = 24.0
MAX_ENTITY_WATER          = 100.0
LAKE_WATER_REPLENISH_RATE = 0.03
WELL_WATER_REPLENISH_RATE = 0.08
FARM_FOOD_GROWTH_RATE     = 0.10
FARM_WATER_USE_RATE       = 0.04
INITIAL_WATER_LAKE        = 100.0
INITIAL_WATER_WELL        = 80.0
INITIAL_WATER_FARM        = 30.0

# =============================================================================
# BUILD / CONSTRUCTION
# =============================================================================
BUILD_SITE_HP_FRACTION       = 0.15
BUILD_PROGRESS_PER_HUMAN     = 8.0
BUILD_STAMINA_COST           = 6.0
BUILD_SKILL_GAIN             = 0.5
BUILD_MOOD_GAIN              = 0.8
BUILD_RADIUS                 = 70.0
BUILD_MIN_STAMINA            = 8.0
BUILD_MATERIAL_USE           = 6.0
GATHER_MATERIAL_AMOUNT       = 18.0
GATHER_STAMINA_COST          = 4.0
MAX_CARRYING_MATERIAL        = 100.0
REPAIR_RATE_PER_HUMAN        = 12.0
DEMOLISH_RATE_PER_HUMAN      = 18.0
DEMOLISH_STAMINA_COST        = 5.0
SALVAGE_RETURN_FRACTION      = 0.35

# =============================================================================
# GENESIS PARAMETERS
# =============================================================================
ADAM_LIFE_EXP = 80.0
EVE_LIFE_EXP  = 85.0
GENESIS_AGE   = 20.0
LIFE_EXP_MIN  = 60.0
LIFE_EXP_MAX  = 90.0
