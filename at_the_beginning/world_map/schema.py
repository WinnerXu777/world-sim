"""Typed objects and constants for the authored 2D map file.

DRAFT contract (C-003; 0.2-draft adds actor_radius, interact_radius, map_kind). Conventions:

* All positions, wall boxes and bounds are in backend units. The file must
  declare ``units_per_tile``; there is no default.
* Origin is the top-left corner of the map, +x right, +y down, matching the
  ``[x, y]`` ground-plane coordinates ``systems/movement/spatial.py`` uses.
* The world bounds are ``[0, 0, width_tiles * units_per_tile,
  height_tiles * units_per_tile]``.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple, Union

FORMAT_VERSION = "0.2-draft"  # what new files should declare
ACCEPTED_FORMAT_VERSIONS = ("0.1-draft", "0.2-draft")
COORDINATE_SYSTEM = "top_left_x_right_y_down"
MAP_KINDS = ("exterior", "interior")
WALL_DEFAULT_HEIGHT = 2.4  # same literal spatial.wall_boxes emits
MAX_SIZE_TILES = 4096
LAYER_KINDS = ("terrain", "decoration", "footprint")
KNOWN_ANCHOR_KINDS = ("door", "work", "talk", "sleep", "spawn")
KNOWN_ANCHOR_ROLES = ("smith", "builder", "gatherer")  # backend occupations an anchor may be intended for
ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}"
GENERATED_ID_PATTERN = r"e_\d{6}"  # ids Engine._make_entity_id generates; map ids must not collide with them

Vec2 = Tuple[float, float]


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    path: str
    message: str

    def __str__(self):
        return f"{self.severity.upper()} {self.path}: {self.message}"


class MapValidationError(ValueError):
    def __init__(self, issues):
        self.issues = list(issues)
        errors = [i for i in self.issues if i.severity == "error"]
        super().__init__(f"{len(errors)} map error(s): " + "; ".join(str(i) for i in errors[:5]))


@dataclass(frozen=True)
class TileLayer:
    name: str
    kind: str
    palette: dict  # tile index (int, > 0) -> sprite reference (relative path)
    tiles: Tuple[Tuple[int, ...], ...]  # [row][col]; 0 means empty


@dataclass(frozen=True)
class Wall:
    id: str
    min: Vec2
    max: Vec2
    height: float = WALL_DEFAULT_HEIGHT
    owner_entity: Optional[str] = None  # entity id this wall belongs to; does not replace the min/max box


@dataclass(frozen=True)
class Anchor:
    id: str
    kind: str
    position: Vec2
    for_role: Optional[str] = None  # label only: the occupation this anchor is meant for; never a resident id


@dataclass(frozen=True)
class Entity:
    id: str
    kind: str
    interactive: bool
    position: Vec2
    sprite: Optional[str] = None
    interact_radius: Optional[float] = None  # backend units; None = backend default
    resource: Optional[dict] = field(default=None, compare=False)  # validated ``resource`` object (world_map/resources.py), if declared


@dataclass(frozen=True)
class Portal:
    id: str
    from_anchor: str
    to_map: str
    to_anchor: str


@dataclass(frozen=True)
class WorldMap:
    format_version: str
    map_id: str
    revision: Union[int, str]  # int for 0.2-draft; 0.1-draft files may carry a string
    tile_size_px: int
    units_per_tile: float
    size_tiles: Tuple[int, int]
    layers: Tuple[TileLayer, ...] = ()
    walls: Tuple[Wall, ...] = ()
    anchors: Tuple[Anchor, ...] = ()
    entities: Tuple[Entity, ...] = ()
    portals: Tuple[Portal, ...] = ()
    actor_radius: Optional[float] = None  # backend units; None = backend default (spatial.RADIUS)
    map_kind: str = "exterior"
    warnings: Tuple[Issue, ...] = field(default=(), compare=False)
    extras: dict = field(default_factory=dict, compare=False)  # validated chunk-document blocks: chunk, data, pinned_map

    @property
    def bounds(self):
        """[min_x, min_y, max_x, max_y] in backend units."""
        return [0.0, 0.0, self.size_tiles[0] * self.units_per_tile, self.size_tiles[1] * self.units_per_tile]

    def sprite_references(self):
        """Yield (json_path, reference) for every sprite the map names."""
        for li, layer in enumerate(self.layers):
            for key, ref in layer.palette.items():
                yield f"layers[{li}].palette.{key}", ref
        for ei, entity in enumerate(self.entities):
            if entity.sprite is not None:
                yield f"entities[{ei}].sprite", entity.sprite
