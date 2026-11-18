"""Chunk routes (1008 WS-D, D8): ``GET /chunks`` (window query) and ``GET /chunk/{cx}/{cy}`` (exact bytes, ETag = sha256).

Hook (the only change needed in map_test.py, next to the model router; the flag decides whether the routes exist at all):

    from api.chunk_routes import build_chunk_router, enabled as chunk_routes_enabled      # with the other api imports
    if chunk_routes_enabled():
        app.include_router(build_chunk_router(lambda: engine))

Engine independent: the routes serve whatever a ``systems.worldgen.service.ChunkService`` produces, so they work before the
window exists. ``ChunkService`` is pull-based and not thread-safe; every access here happens on the event loop thread, and a small
pump task calls ``pump()`` while any requested chunk is still pending. Nothing generates inline in a request handler (with the
default two worker processes); a chunk that is not ready within ``READY_TIMEOUT`` answers 503 ``chunk_pending`` + ``Retry-After``.

Flag ``EDEN_CHUNK_ROUTES=1`` (default off: the routes do not exist). World seed: ``EDEN_WORLD_SEED`` (integer, development default
1008 until saves carry the seed); workers: ``EDEN_CHUNK_WORKERS`` (default 2). Chunk coordinates are limited to ``abs <= 2**40``.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from systems.worldgen import CHUNK_TILES, GENERATOR_VERSION, UNITS_PER_TILE, PinnedSet, starter_village_area
from systems.worldgen.rings import ChunkCoord
from systems.worldgen.service import ChunkService

FLAG = "EDEN_CHUNK_ROUTES"
SEED_ENV = "EDEN_WORLD_SEED"
WORKERS_ENV = "EDEN_CHUNK_WORKERS"
DEFAULT_SEED = 1008
MAX_WINDOW = 15            # chunks per side of a /chunks query
MAX_ABS_COORD = 2 ** 40
READY_TIMEOUT = 2.0        # seconds a /chunk request waits for generation
PUMP_INTERVAL = 0.005


def enabled(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    return environ.get(FLAG, "") == "1"


def default_service() -> ChunkService:
    """Service for the running world: seed and worker count from the environment, the starter village pinned."""
    seed = int(os.environ.get(SEED_ENV, DEFAULT_SEED))
    workers = int(os.environ.get(WORKERS_ENV, "2"))
    return ChunkService(seed, pinned=PinnedSet([starter_village_area()]), workers=workers)


def _etag_matches(header: Optional[str], sha256: str) -> bool:
    if not header:
        return False
    tags = [part.strip() for part in header.split(",")]
    return "*" in tags or any(tag.removeprefix("W/").strip('"') == sha256 for tag in tags)


def _reject(reason: str, status: int = 400, **extra):
    return JSONResponse({"ok": False, "reason": reason, **extra}, status_code=status)


class ChunkRoutes:
    """The two handlers plus the pump task; ``service`` is created on first use."""

    def __init__(self, service_factory: Callable[[], ChunkService] = default_service):
        self._factory = service_factory
        self._service: Optional[ChunkService] = None
        self._wanted: set = set()
        self._pump_task: Optional[asyncio.Task] = None

    @property
    def service(self) -> ChunkService:
        if self._service is None:
            self._service = self._factory()
        return self._service

    def close(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
            self._pump_task = None
        if self._service is not None:
            self._service.close()
            self._service = None
        self._wanted.clear()

    # pump ----------------------------------------------------------------------------------------------------------------
    def want(self, coord: ChunkCoord, priority: float) -> None:
        self.service.request(coord, priority)
        self._wanted.add(coord)
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = asyncio.get_running_loop().create_task(self._pump())

    async def _pump(self) -> None:
        service = self.service
        while self._wanted:
            service.pump()
            self._wanted = {c for c in self._wanted if service.is_pending(c)}
            await asyncio.sleep(PUMP_INTERVAL)

    # handlers ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _descriptor(coord: ChunkCoord, chunk, pinned_set: Optional[PinnedSet] = None) -> dict:
        item = {"chunk_id": coord.chunk_id, "revision": 0, "url": f"/chunk/{coord.x}/{coord.y}"}
        if chunk is None:
            return {**item, "sha256": None, "state": "pending"}
        pinned = chunk.pinned_map
        result = {**item, "sha256": chunk.sha256, "state": "pinned_map" if pinned else "ready"}
        if pinned:
            result["pinned_map"] = pinned
            if pinned_set is not None:
                area = pinned_set.fully_pinned_by(coord.x, coord.y)
                if area is not None and area.id == pinned:
                    from systems.worldgen import UNITS_PER_TILE
                    result["placement_origin_absolute_units"] = [area.x0 * UNITS_PER_TILE, area.y0 * UNITS_PER_TILE]
        return result

    async def window(self, cx0: int, cy0: int, cx1: int, cy1: int):
        if cx1 < cx0 or cy1 < cy0:
            return _reject("invalid_window")
        if cx1 - cx0 + 1 > MAX_WINDOW or cy1 - cy0 + 1 > MAX_WINDOW:
            return _reject("window_too_large", max_chunks_per_side=MAX_WINDOW)
        if max(abs(cx0), abs(cy0), abs(cx1), abs(cy1)) > MAX_ABS_COORD:
            return _reject("coordinate_out_of_range")
        service = self.service
        centre = ((cx0 + cx1) / 2.0, (cy0 + cy1) / 2.0)
        chunks = []
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                coord = ChunkCoord(cx, cy)
                chunk = service.peek(coord)
                if chunk is None:
                    self.want(coord, abs(cx - centre[0]) + abs(cy - centre[1]))      # nearest the window centre first
                chunks.append(self._descriptor(coord, chunk, getattr(service, 'pinned', None)))
        return JSONResponse({"ok": True, "world_seed": str(service.world_seed), "generator_version": GENERATOR_VERSION,
                             "chunk_tiles": CHUNK_TILES, "units_per_tile": UNITS_PER_TILE, "chunks": chunks})

    async def chunk(self, cx: int, cy: int, request: Request):
        if max(abs(cx), abs(cy)) > MAX_ABS_COORD:
            return _reject("coordinate_out_of_range")
        coord = ChunkCoord(cx, cy)
        service = self.service
        found = service.get(coord)
        if found is None:
            self.want(coord, -1.0)                                                    # a direct request beats every prefetch
            deadline = asyncio.get_running_loop().time() + READY_TIMEOUT
            while found is None and asyncio.get_running_loop().time() < deadline:
                if coord in service.failed and not service.is_pending(coord):
                    return _reject("chunk_failed", 500)
                await asyncio.sleep(PUMP_INTERVAL)
                found = service.peek(coord)
        if found is None:
            response = _reject("chunk_pending", 503)
            response.headers["Retry-After"] = "1"
            return response
        headers = {"ETag": f'"{found.sha256}"', "Cache-Control": "no-cache"}
        if _etag_matches(request.headers.get("if-none-match"), found.sha256):
            return Response(status_code=304, headers=headers)
        return Response(content=found.payload, media_type="application/json", headers=headers)


def build_chunk_router(get_engine=None, service_factory: Callable[[], ChunkService] = default_service) -> APIRouter:
    """Router with ``GET /chunks`` and ``GET /chunk/{cx}/{cy}``. ``get_engine`` is accepted for symmetry with the model router
    and unused until the window exists (the routes do not read the engine)."""
    routes = ChunkRoutes(service_factory)
    router = APIRouter()
    router.chunk_routes = routes                                       # tests and shutdown hooks reach the service through this

    @router.get("/chunks")
    async def chunks(cx0: int, cy0: int, cx1: int, cy1: int):
        return await routes.window(cx0, cy0, cx1, cy1)

    @router.get("/chunk/{cx}/{cy}")
    async def chunk(cx: int, cy: int, request: Request):
        return await routes.chunk(cx, cy, request)

    return router
