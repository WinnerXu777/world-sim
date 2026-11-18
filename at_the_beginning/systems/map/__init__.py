"""Map-domain creation and frontier-expansion helpers."""

from .chunking import (
    CameraChunkWindow,
    ChunkCoord,
    ChunkStreamDiff,
    chunk_coord_for_world_point,
    chunk_origin,
    chunk_rect_for_world_rect,
    chunk_window_payload,
    chunks_for_camera_window,
    diff_chunk_windows,
    parse_chunk_id,
    world_to_chunk_local,
)
from .chunk_generation import (
    CREATABLE_FRONTIER_TYPES,
    FrontierFeatureSpec,
    FrontierProfile,
    build_frontier_profile,
    generate_frontier_feature_plan,
)
from .create import (
    create_feature_near_feature,
    create_forest_patch_feature,
    create_lake_feature,
    create_mountain_chain_feature,
    create_natural_feature_at,
    create_settlement_area,
    create_wall_feature,
    transform_map_area,
)
from .expand import expand_world_edge, frontier_edges_for_humans, maybe_expand_frontier

__all__ = [
    "CameraChunkWindow",
    "CREATABLE_FRONTIER_TYPES",
    "ChunkCoord",
    "ChunkStreamDiff",
    "FrontierFeatureSpec",
    "FrontierProfile",
    "build_frontier_profile",
    "chunk_coord_for_world_point",
    "chunk_origin",
    "chunk_rect_for_world_rect",
    "chunk_window_payload",
    "chunks_for_camera_window",
    "create_feature_near_feature",
    "create_forest_patch_feature",
    "create_lake_feature",
    "create_mountain_chain_feature",
    "create_natural_feature_at",
    "create_settlement_area",
    "create_wall_feature",
    "diff_chunk_windows",
    "expand_world_edge",
    "frontier_edges_for_humans",
    "generate_frontier_feature_plan",
    "maybe_expand_frontier",
    "parse_chunk_id",
    "transform_map_area",
    "world_to_chunk_local",
]
