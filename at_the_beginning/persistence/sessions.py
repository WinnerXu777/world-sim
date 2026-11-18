"""Explicit New/Save/Continue operations; disk work runs outside the tick."""
from __future__ import annotations

import asyncio
import random
import uuid

import numpy as np
import torch

from . import codec, world_snapshot
from .checkpoints import CheckpointError, CheckpointStore


async def _finish_disk_job(function, *args):
    """Keep the session lock until a started disk operation actually finishes.

    Cancelling to_thread's await does not stop its worker. Drain it before
    propagating cancellation so another save cannot race its manifest commit.
    """
    job = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(job)
            break
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


class GameSessions:
    def __init__(self, engine, geometry, control_factory, root, create_world, seed, map_name="playable_village"):
        self.engine = engine
        self.geometry = geometry
        self.control_factory = control_factory
        self.store = CheckpointStore(root)
        self.create_world = create_world
        self.seed = seed
        self.map_name = map_name  # the launch map New Game creates (EDEN_MAP)
        self.active_id = None
        self.active_name = None
        self.active_epoch = None
        self.last_saved_tick = None
        self.last_error = None
        self.recovered_previous = False
        self._lock = asyncio.Lock()
        self.autosave_interval = 60.0

    def has_active_world(self):
        return bool(self.active_id and self.engine.world_loaded and self.active_epoch == self.engine.world_epoch)

    def status(self):
        return {"active_save_id": self.active_id, "name": self.active_name,
                "world_loaded": self.engine.world_loaded, "busy": self._lock.locked(),
                "last_saved_tick": self.last_saved_tick, "error": self.last_error,
                "autosave_interval_seconds": self.autosave_interval,
                "recovered_previous": self.recovered_previous, "world_epoch": self.engine.world_epoch}

    def _warm_up(self):
        """Pay the first-use costs of the new or restored world now, on this request, not on its first game ticks (never fails it)."""
        warm = getattr(self.engine, "warm_up_world", None)
        if callable(warm):
            try:
                warm()
            except Exception as exc:  # noqa: BLE001 - a derived index; the first tick would build it anyway
                import logging
                logging.getLogger("eden.sessions").warning("world warm-up failed: %s", exc)

    async def _save(self):
        if not self.has_active_world():
            raise CheckpointError("No selected gameplay world to save")
        tick = self.engine.tick
        snapshot = world_snapshot.capture(self.engine, self.geometry)
        queue_graph = getattr(self.engine, "queue_memory_graph_write", None)
        if callable(queue_graph):
            queue_graph()  # the derived memory graph is written by its own thread; the save does not wait for it
        entry = await _finish_disk_job(self.store.commit, self.active_id, self.active_name, tick, snapshot,
                                       world_snapshot.current_format())
        self.last_saved_tick = tick
        self.last_error = None
        return {"ok": True, "generation": entry, **self.status()}

    async def save(self):
        async with self._lock:
            try:
                return await self._save()
            except Exception as exc:
                self.last_error = str(exc)
                raise

    async def autosave_loop(self):
        while True:
            await asyncio.sleep(self.autosave_interval)
            async with self._lock:
                if not self.has_active_world() or self.engine.tick == self.last_saved_tick:
                    continue
                try:
                    await self._save()
                except Exception as exc:
                    # Keep the last complete generation; retry at the next interval.
                    self.last_error = str(exc)

    async def shutdown(self):
        """Called after stopping ticks and draining the autosave task."""
        async with self._lock:
            if not self.has_active_world():
                return
            try:
                await self._save()
            except Exception as exc:
                self.last_error = str(exc)
                raise

    async def new(self, name: str):
        name = name.strip()
        if not name or len(name) > 64:
            raise CheckpointError("World name must contain 1–64 characters")
        async with self._lock:
            # Preserve the active world before switching to a different save slot.
            if self.has_active_world():
                await self._save()
            self.engine.reset_world()
            random.seed(self.seed)
            np.random.seed(self.seed)
            torch.manual_seed(self.seed)
            await self.create_world(self.engine, map_name=self.map_name)
            self._warm_up()
            self.active_id = uuid.uuid4().hex
            self.active_name = name
            self.active_epoch = self.engine.world_epoch
            self.recovered_previous = False
            self.last_saved_tick = None
            try:
                return await self._save()
            except Exception as exc:
                self.last_error = str(exc)
                raise

    async def continue_world(self, save_id: str):
        async with self._lock:
            if self.active_id == save_id and self.has_active_world():
                return {"ok": True, "resumed_active": True, **self.status()}
            try:
                data, info = await _finish_disk_job(self.store.read, save_id)
                payload = codec.loads(data)
                world_snapshot.validate(payload, self.engine)
                if self.has_active_world():
                    await self._save()
                world_snapshot.restore(payload, self.engine, self.geometry, self.control_factory)
                self._warm_up()
                self.active_id = save_id
                self.active_epoch = self.engine.world_epoch
                self.active_name = info["name"]
                self.last_saved_tick = info["tick"]
                self.recovered_previous = info["recovered_previous"]
                self.last_error = None
                return {"ok": True, **self.status()}
            except Exception as exc:
                self.last_error = str(exc)
                raise
