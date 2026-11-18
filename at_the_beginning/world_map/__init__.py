"""Authored 2D map file: schema, loader, validator (DRAFT format 0.2-draft)."""
from .loader import check_map_bytes, check_map_file, load_map, load_map_bytes
from .parse import loads_strict, parse_map
from .schema import (FORMAT_VERSION, Anchor, Entity, Issue, MapValidationError, Portal, TileLayer, Wall, WorldMap)
from .spatial_bridge import to_anchor_list, to_movement_contract, to_wall_boxes
from .validate import check_portal_targets, effective_radius, validate_map

__all__ = ["FORMAT_VERSION", "Anchor", "Entity", "Issue", "MapValidationError", "Portal", "TileLayer", "Wall",
           "WorldMap", "check_map_bytes", "check_map_file", "load_map_bytes", "check_portal_targets", "effective_radius", "load_map", "loads_strict", "parse_map",
           "to_anchor_list", "to_movement_contract", "to_wall_boxes", "validate_map"]
