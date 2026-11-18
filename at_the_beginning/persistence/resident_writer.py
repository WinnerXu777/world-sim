"""One bounded resident export writer, serialized with session replacement."""
import asyncio

from runtime.resident_store import write_resident_batch
from .sessions import _finish_disk_job


class ResidentWriter:
    def __init__(self, sessions):
        self.sessions = sessions

    async def flush_once(self):
        # New/Continue hold this same lock, so an old export finishes before reset.
        async with self.sessions._lock:
            engine = self.sessions.engine
            store = engine.resident_store
            # The worker's wall-clock interval also retries while simulation is paused.
            jobs = store.capture_dirty(engine.tick, force=True, limit=16)
            if jobs:
                results = await _finish_disk_job(write_resident_batch, jobs)
                store.acknowledge_writes(results)

    async def run(self):
        while True:
            try:
                await self.flush_once()
                self.sessions.engine.resident_store.save_errors.pop("__writer__", None)
            except Exception as exc:
                self.sessions.engine.resident_store.save_errors["__writer__"] = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(1.0)
