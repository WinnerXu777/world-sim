"""Deterministic chunk generator and streaming service (see 1008_worldgen.md). Pure numpy; no engine imports.

The package `__init__` stays light on purpose: pool workers import `systems.worldgen.generate` and must not pay for the ring/service
modules. Import those explicitly: `from systems.worldgen.service import ChunkService`, `from systems.worldgen.rings import plan_stream`.
"""
from .generate import DEFAULT_PARAMS, Chunk, GenParams, chunk_key, generate_chunk
from .pinned import NO_PINS, PinnedArea, PinnedSet, starter_village_area
from .spec import CHUNK_SPEC, CHUNK_TILES, CHUNK_UNITS, GENERATOR_VERSION, TILE_PX, UNITS_PER_TILE

__all__ = ["Chunk", "GenParams", "DEFAULT_PARAMS", "generate_chunk", "chunk_key", "PinnedArea", "PinnedSet", "NO_PINS", "starter_village_area",
           "CHUNK_SPEC", "CHUNK_TILES", "CHUNK_UNITS", "GENERATOR_VERSION", "TILE_PX", "UNITS_PER_TILE"]
