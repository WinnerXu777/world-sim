from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True, order=True)
class ChunkCoord:
    """Stable integer chunk address in an unbounded 2D world."""

    x: int
    y: int

    @property
    def chunk_id(self) -> str:
        return f"{self.x}:{self.y}"


@dataclass(frozen=True)
class CameraChunkWindow:
    """
    Camera-derived world-space query.

    `view_world_w` and `view_world_h` are already expressed in world units, so
    the backend does not need to know engine-specific zoom semantics.
    """

    center_x: float
    center_y: float
    view_world_w: float
    view_world_h: float
    margin_chunks: int = 1


@dataclass(frozen=True)
class ChunkStreamDiff:
    """How the client/server chunk window should change this step."""

    load: tuple[ChunkCoord, ...]
    keep: tuple[ChunkCoord, ...]
    unload: tuple[ChunkCoord, ...]


def _require_positive(value: float, label: str) -> float:
    numeric = float(value)
    if numeric <= 0.0:
        raise ValueError(f"{label} must be > 0")
    return numeric


def chunk_coord_for_world_point(
    world_x: float,
    world_y: float,
    *,
    chunk_px_w: float,
    chunk_px_h: float,
) -> ChunkCoord:
    """Return the chunk containing a world-space point."""
    width = _require_positive(chunk_px_w, "chunk_px_w")
    height = _require_positive(chunk_px_h, "chunk_px_h")
    return ChunkCoord(
        x=int(math.floor(float(world_x) / width)),
        y=int(math.floor(float(world_y) / height)),
    )


def chunk_origin(
    coord: ChunkCoord,
    *,
    chunk_px_w: float,
    chunk_px_h: float,
) -> tuple[float, float]:
    """Top-left world-space origin of a chunk."""
    width = _require_positive(chunk_px_w, "chunk_px_w")
    height = _require_positive(chunk_px_h, "chunk_px_h")
    return float(coord.x) * width, float(coord.y) * height


def world_to_chunk_local(
    world_x: float,
    world_y: float,
    *,
    chunk_px_w: float,
    chunk_px_h: float,
) -> tuple[ChunkCoord, float, float]:
    """Convert a world-space point to `(chunk_coord, local_x, local_y)`."""
    coord = chunk_coord_for_world_point(
        world_x,
        world_y,
        chunk_px_w=chunk_px_w,
        chunk_px_h=chunk_px_h,
    )
    origin_x, origin_y = chunk_origin(coord, chunk_px_w=chunk_px_w, chunk_px_h=chunk_px_h)
    return coord, float(world_x) - origin_x, float(world_y) - origin_y


def chunk_rect_for_world_rect(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    *,
    chunk_px_w: float,
    chunk_px_h: float,
    margin_chunks: int = 0,
) -> tuple[int, int, int, int]:
    """Return inclusive chunk bounds intersecting a world-space rectangle."""
    width = _require_positive(chunk_px_w, "chunk_px_w")
    height = _require_positive(chunk_px_h, "chunk_px_h")
    if max_x < min_x or max_y < min_y:
        raise ValueError("world rect max must be >= min")
    min_chunk_x = int(math.floor(float(min_x) / width)) - int(margin_chunks)
    max_chunk_x = int(math.floor(float(max_x) / width)) + int(margin_chunks)
    min_chunk_y = int(math.floor(float(min_y) / height)) - int(margin_chunks)
    max_chunk_y = int(math.floor(float(max_y) / height)) + int(margin_chunks)
    return min_chunk_x, min_chunk_y, max_chunk_x, max_chunk_y


def chunks_for_camera_window(
    window: CameraChunkWindow,
    *,
    chunk_px_w: float,
    chunk_px_h: float,
) -> tuple[ChunkCoord, ...]:
    """Enumerate the chunk window required for a camera-visible region."""
    view_w = _require_positive(window.view_world_w, "view_world_w")
    view_h = _require_positive(window.view_world_h, "view_world_h")
    half_w = view_w / 2.0
    half_h = view_h / 2.0
    bounds = chunk_rect_for_world_rect(
        window.center_x - half_w,
        window.center_y - half_h,
        window.center_x + half_w,
        window.center_y + half_h,
        chunk_px_w=chunk_px_w,
        chunk_px_h=chunk_px_h,
        margin_chunks=window.margin_chunks,
    )
    min_x, min_y, max_x, max_y = bounds
    coords: list[ChunkCoord] = []
    for chunk_y in range(min_y, max_y + 1):
        for chunk_x in range(min_x, max_x + 1):
            coords.append(ChunkCoord(chunk_x, chunk_y))
    return tuple(coords)


def chunk_window_payload(
    window: CameraChunkWindow,
    *,
    chunk_px_w: float,
    chunk_px_h: float,
) -> dict:
    """Serializable helper for a future protocol-v2 chunk request."""
    chunks = chunks_for_camera_window(window, chunk_px_w=chunk_px_w, chunk_px_h=chunk_px_h)
    return {
        "center_world": [round(float(window.center_x), 2), round(float(window.center_y), 2)],
        "view_world": [round(float(window.view_world_w), 2), round(float(window.view_world_h), 2)],
        "margin_chunks": int(window.margin_chunks),
        "chunk_size": [float(chunk_px_w), float(chunk_px_h)],
        "chunk_ids": [coord.chunk_id for coord in chunks],
    }


def parse_chunk_id(value: str) -> ChunkCoord:
    """Parse `x:y` chunk ids back into structured coordinates."""
    raw = str(value).strip()
    left, sep, right = raw.partition(":")
    if not sep:
        raise ValueError(f"invalid chunk id: {value!r}")
    return ChunkCoord(int(left), int(right))


def normalize_chunk_set(values: Iterable[ChunkCoord | str]) -> set[ChunkCoord]:
    """Normalize strings and structured coords into a chunk set."""
    result: set[ChunkCoord] = set()
    for value in values:
        if isinstance(value, ChunkCoord):
            result.add(value)
        else:
            result.add(parse_chunk_id(str(value)))
    return result


def diff_chunk_windows(
    current: Iterable[ChunkCoord | str],
    desired: Iterable[ChunkCoord | str],
) -> ChunkStreamDiff:
    """Return which chunks to load, keep, and unload when the camera window changes."""
    current_set = normalize_chunk_set(current)
    desired_set = normalize_chunk_set(desired)
    load = tuple(sorted(desired_set - current_set))
    keep = tuple(sorted(desired_set & current_set))
    unload = tuple(sorted(current_set - desired_set))
    return ChunkStreamDiff(load=load, keep=keep, unload=unload)
