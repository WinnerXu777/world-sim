"""
initial_map_design.py
=====================
Registry of map generators for the Eden simulation.

Design contract
───────────────
Each generator places DISCRETE ENTITIES into m_tensor (one row per entity)
and registers their geometry into MAP_GEO via map_geo.register_entity().

There is NO tile-grid filling.  m_tensor is an entity registry, not a tile
array.  16,800 tile rows no longer exist — there might be 40–80 entities
on a typical map.

Generator signature:
    def map_<name>(m_tensor, entity_count_ref, device) -> None

Generators call:
    entity_born(m_tensor, entity_count_ref, cx, cy, m_type, ...,
                register_geo=True, device=device)
    ... which writes one m_tensor row AND calls map_geo.register_entity().

The background tile grid (GRID_H × GRID_W) is rendered by the viewer using
map_geo.background_tile_types() — it asks "for each tile, which entity covers
it?" and colours accordingly.  Tiles not covered by any entity render as sea.

Adding a new map
────────────────
1. Write map_<name>() placing entities via entity_born().
2. Add it to MAP_REGISTRY.
3. Done — genesis.py, instincts_and_tools.py unchanged.

Adding a new entity type to an existing map
────────────────────────────────────────────
Write one entity_born() call in the appropriate map function.
Add the M_TYPE constant to genesis_config if it's new.
"""

import random
import math
import torch

import map_geo
from genesis_config import (
    MAP_WIDTH, MAP_HEIGHT, TILE_SIZE,
    MAX_ENTITIES,
    CX, CY, M_TYPE, M_HP, SCALE, M_FERTILITY, M_ELEVATION, M_RESOURCE_FOOD,
    M_LAKE, M_FOREST, M_SEA, M_MOUNTAIN, M_BEACH, M_GRASS,
    M_LAVA, M_BARREN, M_HOUSE, M_VILLAGE, M_WELL, M_STORAGE_CASE,
    M_FARM, M_WALL,
    M_SHEEP, M_DEER, M_TIGER, M_WOLF,
    M_LAVA_COOLING, VOLCANO_LAVA_COOLING,
    NATURAL_SCALE,
    INITIAL_FOOD_GRASS, INITIAL_FOOD_FOREST, INITIAL_FOOD_BEACH, INITIAL_FOOD_LAKE,
    ANIMAL_LIFE_EXP,
)
from instincts_and_tools import entity_born, animal_born


# =============================================================================
# SHARED PLACEMENT HELPERS
# =============================================================================

def _place(m_tensor, entity_count_ref, device,
           cx, cy, m_type,
           scale=None, hp=100.0,
           food=0.0, fertility=0.0, elevation=0.0,
           extra_cols: dict[int, float] | None = None) -> int:
    """
    Convenience wrapper: place one natural-feature entity, seed its resource
    cols, and register geometry in MAP_GEO.
    Returns entity_id.
    """
    if scale is None:
        lo, hi = NATURAL_SCALE.get(m_type, (40, 80))
        scale  = random.uniform(lo, hi)

    food_defaults = {
        M_GRASS:  INITIAL_FOOD_GRASS,
        M_FOREST: INITIAL_FOOD_FOREST,
        M_BEACH:  INITIAL_FOOD_BEACH,
        M_LAKE:   INITIAL_FOOD_LAKE,
    }
    fert_defaults = {
        M_GRASS:  60.0, M_FOREST: 90.0, M_BEACH: 25.0, M_LAKE: 50.0,
    }
    food      = food      or food_defaults.get(m_type, 0.0)
    fertility = fertility or fert_defaults.get(m_type, 0.0)
    if extra_cols is None:
        extra_cols = {}

    return entity_born(
        m_tensor, entity_count_ref,
        cx=cx, cy=cy, m_type=m_type, hp=hp, scale=scale,
        register_geo=True, device=device,
        col_vals={
            M_RESOURCE_FOOD: food,
            M_FERTILITY:     fertility,
            M_ELEVATION:     elevation,
            **extra_cols,
        },
    )


def _scatter_entities(m_tensor, entity_count_ref, device,
                       m_type, count,
                       cx_range, cy_range,
                       min_sep=60.0,
                       scale_range=None) -> list[int]:
    """
    Place `count` entities of m_type randomly within (cx_range, cy_range),
    enforcing minimum separation min_sep px between centres.
    Returns list of entity_ids.
    """
    placed  = []
    centres = []
    attempts = 0
    while len(placed) < count and attempts < count * 30:
        attempts += 1
        x = random.uniform(*cx_range)
        y = random.uniform(*cy_range)
        # Minimum separation check
        too_close = any(
            math.hypot(x - ox, y - oy) < min_sep
            for ox, oy in centres
        )
        if too_close:
            continue
        sc = None
        if scale_range:
            sc = random.uniform(*scale_range)
        eid = _place(m_tensor, entity_count_ref, device, x, y, m_type, scale=sc)
        placed.append(eid)
        centres.append((x, y))
    return placed


# =============================================================================
# MAP 1 — Eden Island  (lush single island)
# =============================================================================

def map_eden_island(m_tensor: torch.Tensor, entity_count_ref: list,
                     device: str) -> None:
    """
    Classic single island.
    Entities placed:
      1 large sea region (background ocean)
      4–6 grass patches (central)
      3–5 forest patches (inner ring)
      1–2 lakes
      2–3 beaches (coastal)
      1–2 mountains (high ground)
    Adam & Eve are spawned by genesis.py at MAP centre after this call.
    """
    W, H = MAP_WIDTH, MAP_HEIGHT
    cx, cy = W / 2, H / 2

    # Sea background — large enough to cover whole map
    _place(m_tensor, entity_count_ref, device,
           cx, cy, M_SEA, scale=max(W, H))

    # Beaches — coastal ring
    for angle in [0, 72, 144, 216, 288]:
        rad  = math.radians(angle)
        dist = random.uniform(H * 0.32, H * 0.42)
        bx   = cx + math.cos(rad) * dist
        by   = cy + math.sin(rad) * dist
        _place(m_tensor, entity_count_ref, device,
               bx, by, M_BEACH, scale=random.uniform(45, 90))

    # Grass — mid island
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_GRASS, count=5,
                      cx_range=(W*0.35, W*0.65),
                      cy_range=(H*0.35, H*0.65),
                      min_sep=70)

    # Forest — inner ring
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_FOREST, count=4,
                      cx_range=(W*0.3, W*0.7),
                      cy_range=(H*0.3, H*0.7),
                      min_sep=80, scale_range=(60, 140))

    # Lakes
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_LAKE, count=2,
                      cx_range=(W*0.38, W*0.62),
                      cy_range=(H*0.38, H*0.62),
                      min_sep=100, scale_range=(40, 80))

    # Mountains — outer high ground
    for angle in [30, 180]:
        rad  = math.radians(angle)
        dist = random.uniform(H * 0.22, H * 0.30)
        mx   = cx + math.cos(rad) * dist
        my   = cy + math.sin(rad) * dist
        _place(m_tensor, entity_count_ref, device,
               mx, my, M_MOUNTAIN, scale=random.uniform(50, 100),
               elevation=0.8)


# =============================================================================
# MAP 2 — Archipelago  (scattered island chain)
# =============================================================================

def map_archipelago(m_tensor: torch.Tensor, entity_count_ref: list,
                     device: str) -> None:
    """
    3–5 small islands.  Each island is a cluster of grass/forest/beach
    entities around a central point.  No dominant land mass.
    """
    W, H = MAP_WIDTH, MAP_HEIGHT

    # Global sea background
    _place(m_tensor, entity_count_ref, device,
           W/2, H/2, M_SEA, scale=max(W, H))

    n_islands = random.randint(3, 5)
    # Place island centres with separation
    island_centres = []
    for _ in range(n_islands):
        for _attempt in range(50):
            ix = random.uniform(W * 0.12, W * 0.88)
            iy = random.uniform(H * 0.12, H * 0.88)
            if all(math.hypot(ix - ox, iy - oy) > 180 for ox, oy in island_centres):
                island_centres.append((ix, iy))
                break

    for icx, icy in island_centres:
        R = random.uniform(70, 130)   # island "radius"
        # Beach ring
        for angle in range(0, 360, 90):
            rad = math.radians(angle + random.uniform(-20, 20))
            bx  = icx + math.cos(rad) * R * 0.75
            by  = icy + math.sin(rad) * R * 0.75
            _place(m_tensor, entity_count_ref, device,
                   bx, by, M_BEACH, scale=random.uniform(35, 65))
        # Grass core
        _place(m_tensor, entity_count_ref, device,
               icx, icy, M_GRASS, scale=random.uniform(50, 90))
        # Maybe a small forest
        if random.random() < 0.7:
            fx = icx + random.uniform(-30, 30)
            fy = icy + random.uniform(-30, 30)
            _place(m_tensor, entity_count_ref, device,
                   fx, fy, M_FOREST, scale=random.uniform(40, 80))
        # Maybe a lake
        if random.random() < 0.5:
            lx = icx + random.uniform(-20, 20)
            ly = icy + random.uniform(-20, 20)
            _place(m_tensor, entity_count_ref, device,
                   lx, ly, M_LAKE, scale=random.uniform(30, 55))


# =============================================================================
# MAP 3 — Pangaea  (large continent)
# =============================================================================

def map_pangaea(m_tensor: torch.Tensor, entity_count_ref: list,
                 device: str) -> None:
    """
    Dense continental landmass.  Rich resources — good for population growth.
    """
    W, H = MAP_WIDTH, MAP_HEIGHT
    _place(m_tensor, entity_count_ref, device,
           W/2, H/2, M_SEA, scale=max(W, H))

    # Dense grass coverage
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_GRASS, count=12,
                      cx_range=(W*0.12, W*0.88),
                      cy_range=(H*0.12, H*0.88),
                      min_sep=60, scale_range=(60, 140))

    # Forests
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_FOREST, count=8,
                      cx_range=(W*0.15, W*0.85),
                      cy_range=(H*0.15, H*0.85),
                      min_sep=70, scale_range=(70, 150))

    # Lakes
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_LAKE, count=4,
                      cx_range=(W*0.2, W*0.8),
                      cy_range=(H*0.2, H*0.8),
                      min_sep=120, scale_range=(45, 90))

    # Mountain range across the top third
    for i in range(4):
        mx = W * (0.2 + i * 0.2)
        my = H * random.uniform(0.12, 0.28)
        _place(m_tensor, entity_count_ref, device,
               mx, my, M_MOUNTAIN, scale=random.uniform(60, 110), elevation=0.85)

    # Coastal beaches
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_BEACH, count=5,
                      cx_range=(W*0.05, W*0.95),
                      cy_range=(H*0.05, H*0.95),
                      min_sep=100, scale_range=(40, 80))


# =============================================================================
# MAP 4 — Volcanic Eden  (island + active volcano)
# =============================================================================

def map_volcanic_eden(m_tensor: torch.Tensor, entity_count_ref: list,
                       device: str) -> None:
    """
    Single island with a pre-placed active lava entity in the north.
    Creates immediate pressure + rich southern resources.
    """
    W, H = MAP_WIDTH, MAP_HEIGHT
    cx, cy = W / 2, H / 2
    _place(m_tensor, entity_count_ref, device,
           cx, cy, M_SEA, scale=max(W, H))

    # Standard island entities (southern half)
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_GRASS, count=4,
                      cx_range=(W*0.35, W*0.65),
                      cy_range=(H*0.50, H*0.75),
                      min_sep=70)
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_FOREST, count=3,
                      cx_range=(W*0.3, W*0.7),
                      cy_range=(H*0.48, H*0.70),
                      min_sep=80)
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_LAKE, count=2,
                      cx_range=(W*0.38, W*0.62),
                      cy_range=(H*0.52, H*0.72),
                      min_sep=90)
    _scatter_entities(m_tensor, entity_count_ref, device,
                      M_BEACH, count=4,
                      cx_range=(W*0.28, W*0.72),
                      cy_range=(H*0.70, H*0.85),
                      min_sep=70)

    # Active volcano — north centre
    vcx, vcy = cx, H * 0.22
    lava_eid = _place(m_tensor, entity_count_ref, device,
                      vcx, vcy, M_LAVA,
                      scale=random.uniform(45, 65),
                      extra_cols={M_LAVA_COOLING: float(VOLCANO_LAVA_COOLING)})

    # Barren ring around lava
    for angle in range(0, 360, 72):
        rad = math.radians(angle)
        bx  = vcx + math.cos(rad) * 80
        by  = vcy + math.sin(rad) * 80
        _place(m_tensor, entity_count_ref, device,
               bx, by, M_BARREN, scale=random.uniform(30, 55))

    # Mountain near volcano
    _place(m_tensor, entity_count_ref, device,
           vcx + 60, vcy + 40, M_MOUNTAIN,
           scale=random.uniform(50, 80), elevation=0.9)


# =============================================================================
# MAP 5 — Divided Eden  (two landmasses separated by a sea channel)
# =============================================================================

def map_divided_eden(m_tensor: torch.Tensor, entity_count_ref: list,
                      device: str) -> None:
    """
    West and east landmasses separated by a central sea channel.
    Natural barrier encourages tribal divergence.
    """
    W, H = MAP_WIDTH, MAP_HEIGHT
    _place(m_tensor, entity_count_ref, device,
           W/2, H/2, M_SEA, scale=max(W, H))

    for side_cx in [W * 0.27, W * 0.73]:
        _scatter_entities(m_tensor, entity_count_ref, device,
                          M_GRASS, count=4,
                          cx_range=(side_cx - W*0.12, side_cx + W*0.12),
                          cy_range=(H*0.25, H*0.75),
                          min_sep=65)
        _scatter_entities(m_tensor, entity_count_ref, device,
                          M_FOREST, count=3,
                          cx_range=(side_cx - W*0.10, side_cx + W*0.10),
                          cy_range=(H*0.25, H*0.75),
                          min_sep=70)
        _scatter_entities(m_tensor, entity_count_ref, device,
                          M_LAKE, count=1,
                          cx_range=(side_cx - W*0.08, side_cx + W*0.08),
                          cy_range=(H*0.3, H*0.7),
                          min_sep=80)
        _scatter_entities(m_tensor, entity_count_ref, device,
                          M_BEACH, count=3,
                          cx_range=(side_cx - W*0.14, side_cx + W*0.14),
                          cy_range=(H*0.20, H*0.80),
                          min_sep=70)
        _place(m_tensor, entity_count_ref, device,
               side_cx + random.uniform(-30, 30),
               H * random.uniform(0.2, 0.35),
               M_MOUNTAIN, scale=random.uniform(55, 90), elevation=0.82)


# =============================================================================
# MAP 6 — Render Test Village  (small centered sample settlement)
# =============================================================================

def map_render_test_village(m_tensor: torch.Tensor, entity_count_ref: list,
                            device: str) -> None:
    """
    Very small centered sample map for rendering iteration.

    Goals:
    - compact walkable footprint near map center
    - intentional "courtyard / keep" read instead of a random blob
    - minimal extra world noise
    - enough shape variety for both 2D and 3D frontend tests
    """
    W, H = MAP_WIDTH, MAP_HEIGHT
    cx, cy = W / 2, H / 2

    # Large sea background so unused map area stays visually quiet.
    _place(m_tensor, entity_count_ref, device, cx, cy, M_SEA, scale=max(W, H))

    # Compact land footprint with a central approach and a little off-axis
    # natural variety so the scene doesn't feel perfectly symmetrical.
    _place(m_tensor, entity_count_ref, device, cx, cy, M_GRASS, scale=220.0)
    _place(m_tensor, entity_count_ref, device, cx - 84.0, cy + 64.0, M_FOREST, scale=54.0)
    _place(m_tensor, entity_count_ref, device, cx + 96.0, cy - 58.0, M_BEACH, scale=46.0)

    # Compact castle-yard structure layout sized for the current test
    # assets: one central castle landmark, a light front yard, and only
    # a few supporting utility props so the scene stays readable.
    entity_born(
        m_tensor, entity_count_ref,
        cx=cx, cy=cy - 6.0, m_type=M_VILLAGE, hp=100.0, scale=24.0,
        register_geo=True, device=device,
    )
    entity_born(
        m_tensor, entity_count_ref,
        cx=cx - 38.0, cy=cy + 42.0, m_type=M_WALL, hp=100.0, scale=11.5,
        register_geo=True, device=device,
    )
    entity_born(
        m_tensor, entity_count_ref,
        cx=cx + 38.0, cy=cy + 42.0, m_type=M_WALL, hp=100.0, scale=11.5,
        register_geo=True, device=device,
    )
    entity_born(
        m_tensor, entity_count_ref,
        cx=cx - 20.0, cy=cy + 26.0, m_type=M_STORAGE_CASE, hp=100.0, scale=8.5,
        register_geo=True, device=device,
    )
    entity_born(
        m_tensor, entity_count_ref,
        cx=cx + 18.0, cy=cy + 30.0, m_type=M_WELL, hp=100.0, scale=8.5,
        register_geo=True, device=device,
    )
    entity_born(
        m_tensor, entity_count_ref,
        cx=cx + 66.0, cy=cy + 54.0, m_type=M_FARM, hp=100.0, scale=10.5,
        register_geo=True, device=device,
    )


# =============================================================================
# MAP REGISTRY
# =============================================================================

def map_playable_village(m_tensor: torch.Tensor, entity_count_ref: list, device: str) -> None:
    """Fixed inland baseline. Sea backgrounds are not overlapping simulation entities."""
    cx, cy = MAP_WIDTH / 2, MAP_HEIGHT / 2
    _place(m_tensor, entity_count_ref, device, cx, cy, M_GRASS,
           scale=180.0, food=500.0, fertility=75.0)
    _place(m_tensor, entity_count_ref, device, cx - 95, cy - 60, M_FOREST,
           scale=28.0, food=180.0, fertility=65.0)
    for x, y, kind, radius in [
        (-22, -22, M_HOUSE, 6), (0, -26, M_HOUSE, 6), (24, -20, M_HOUSE, 6),
        (-18, 22, M_WALL, 4), (18, 22, M_WALL, 4),
        (-10, 5, M_STORAGE_CASE, 2), (12, 7, M_WELL, 3), (45, 28, M_FARM, 9),
    ]:
        entity_born(m_tensor, entity_count_ref, cx=cx+x, cy=cy+y, m_type=kind,
                    hp=100.0, scale=radius, register_geo=True, device=device)


MAP_REGISTRY: dict[str, callable] = {
    "playable_village": map_playable_village,
    "eden_island":   map_eden_island,
    "archipelago":   map_archipelago,
    "pangaea":       map_pangaea,
    "volcanic_eden": map_volcanic_eden,
    "divided_eden":  map_divided_eden,
    "render_test_village": map_render_test_village,
}


def pick_map(name: str | None = None) -> tuple[str, callable]:
    if name is None:
        name = random.choice(list(MAP_REGISTRY.keys()))
    if name not in MAP_REGISTRY:
        raise ValueError(f"Unknown map: {name!r}. Available: {list(MAP_REGISTRY)}")
    return name, MAP_REGISTRY[name]
