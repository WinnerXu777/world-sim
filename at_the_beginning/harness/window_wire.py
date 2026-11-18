"""1008 WS-D P5 (f): what the streaming window adds to the wire (client contract section 4). Everything here is empty or absent unless
``EDEN_WINDOW=1``, so a flag-off payload has exactly its old key set.

``stamp(engine)``: ``{"window_origin": [ox, oy], "window_epoch": n}`` for a payload whose positions are local to that origin; builders stamp at the time
they read the positions, so a payload never mixes epochs. ``world_block(engine)``: the keys ``/bootstrap`` ``world`` gains. ``stale_epoch(engine, body)``:
the 409 body when a request names an epoch the window has moved past, else None (a request without ``window_epoch`` counts as current).
"""
from __future__ import annotations

from .numerics import window_enabled

CHUNK_TILES = 32
UNITS_PER_TILE = 8


def stamp(engine) -> dict:
    """Pure coordinate stamp. Reading a frame never consumes a map update."""
    if not window_enabled():
        return {}
    manager = getattr(engine, "_window", None)
    if manager is None:
        return {"window_origin": [0, 0], "window_epoch": 0}
    return {"window_origin": [int(manager.frame.origin[0]), int(manager.frame.origin[1])], "window_epoch": int(manager.epoch)}


def integrated_block(engine) -> dict:
    """Current set snapshot, in numeric (cx, cy) order; contains no positions."""
    if not window_enabled():
        return {}
    manager = getattr(engine, "_window", None)
    coords = sorted(getattr(manager, "chunks", ()), key=lambda c: (c.x, c.y))
    return {"window": {"integrated": [f"{c.x}:{c.y}" for c in coords]}}


def exported_integrated_block(engine) -> dict:
    """Set snapshot captured with the last entity export, without consuming it."""
    if not window_enabled():
        return {}
    return getattr(engine, "_export_window", None) or integrated_block(engine)


def world_block(engine) -> dict:
    """The additive keys of ``/bootstrap`` ``world`` (the window origin and epoch are those the payload's positions use)."""
    if not window_enabled():
        return {}
    from systems.worldgen import GENERATOR_VERSION
    from . import window_manager
    return {"infinite": True, "chunk_tiles": CHUNK_TILES, "units_per_tile": UNITS_PER_TILE, "generator_version": GENERATOR_VERSION,
            "world_seed": str(window_manager.world_seed_of(engine)),
            **exported_integrated_block(engine),
            **(getattr(engine, "_export_stamp", None) or stamp(engine))}


def stale_epoch(engine, body) -> dict | None:
    if not window_enabled() or not isinstance(body, dict) or "window_epoch" not in body:
        return None
    current = stamp(engine)
    try:
        sent = int(body["window_epoch"])
    except (TypeError, ValueError):
        sent = None
    if sent == current["window_epoch"]:
        return None
    return {"ok": False, "reason": "stale_window_epoch", **current}


def chunk_service_factory():
    """The ``service_factory`` for the chunk routes: under ``EDEN_WINDOW=1`` the one ChunkService the window manager owns (one instance per
    process, one pump per tick), else the routes' own default."""
    if window_enabled():
        from . import window_manager
        return window_manager.shared_service
    from api.chunk_routes import default_service
    return default_service


def close_chunk_service() -> None:
    """Shutdown: stop the shared ChunkService's workers (a no-op unless the window ran)."""
    if window_enabled():
        from . import window_manager
        window_manager.close_service()
