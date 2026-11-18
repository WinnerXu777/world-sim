"""ChunkService: generation in worker processes, a priority queue with cancellation of stale requests, and an in-memory LRU.

Pull-based and engine-free: the caller (the tick thread, later) only calls `set_wanted` / `request`, `pump` and `get`, all of which
return immediately. `pump()` hands finished work back, at most what the caller asks for (`max_ready`), so integration can be spread
across ticks. Workers are started lazily; `workers=0` generates inline inside `pump` (tests, tools).
"""
from __future__ import annotations

import collections
import heapq
import itertools
import time
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Callable, Iterable, Optional

from . import generate as gen
from .generate import DEFAULT_PARAMS, Chunk, GenParams, chunk_key
from .pinned import as_pinned
from .rings import ChunkCoord, StreamPlan
from .spec import GENERATOR_VERSION


class ChunkCache:
    """LRU keyed by (world_seed, generator_version, pinned fingerprint, params fingerprint, cx, cy)."""

    def __init__(self, capacity: int = 512):
        self.capacity = max(1, int(capacity))
        self._items: "collections.OrderedDict[tuple, Chunk]" = collections.OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key) -> bool:
        return key in self._items

    def get(self, key) -> Optional[Chunk]:
        item = self._items.get(key)
        if item is None:
            self.misses += 1
            return None
        self._items.move_to_end(key)
        self.hits += 1
        return item

    def peek(self, key) -> Optional[Chunk]:
        return self._items.get(key)

    def put(self, key, chunk: Chunk) -> None:
        self._items[key] = chunk
        self._items.move_to_end(key)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)
            self.evictions += 1

    def evict(self, key) -> bool:
        return self._items.pop(key, None) is not None

    def keys(self) -> list:
        return list(self._items)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"size": len(self._items), "capacity": self.capacity, "hits": self.hits, "misses": self.misses,
                "hit_rate": (self.hits / total) if total else 0.0, "evictions": self.evictions}


def _percentile(values, p):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, min(len(ordered) - 1, int(-(-len(ordered) * p // 100)) - 1))]


class ChunkService:
    def __init__(self, world_seed: int, pinned=None, params: GenParams = DEFAULT_PARAMS, workers: int = 2, lru_capacity: int = 512,
                 max_in_flight: Optional[int] = None, inline_budget: int = 1, generate: Callable = gen.generate_payload,
                 cache: Optional[ChunkCache] = None, clock: Callable[[], float] = time.perf_counter):
        self.world_seed = int(world_seed)
        self.pinned = as_pinned(pinned)
        self.params = params
        self.workers = int(workers)
        self.max_in_flight = int(max_in_flight if max_in_flight is not None else max(1, self.workers) * 2)
        self.inline_budget = int(inline_budget)
        self.cache = cache or ChunkCache(lru_capacity)
        self._generate = generate
        self._clock = clock
        self._executor: Optional[ProcessPoolExecutor] = None
        self._heap: list = []
        self._queued: dict = {}                    # coord -> (priority, seq, enqueue time)
        self._queued_time: dict = {}               # coord -> enqueue time, for chunks popped but not yet finished
        self._seq = itertools.count()
        self._in_flight: dict = {}                 # coord -> (future, dispatch time, enqueue time)
        self._done: "collections.deque" = collections.deque()
        self.failed: dict = {}                     # coord -> error text of the last failure
        self.counters = collections.Counter()
        self.latency_ms: collections.deque = collections.deque(maxlen=4096)       # request -> ready (queue wait + generation + IPC)
        self.generation_ms: collections.deque = collections.deque(maxlen=4096)    # time inside the worker

    # ------------------------------------------------------------------ keys
    def key(self, coord) -> tuple:
        return chunk_key(self.world_seed, coord.x, coord.y, self.pinned, self.params)

    # -------------------------------------------------------------- requests
    def request(self, coord: ChunkCoord, priority: float = 0.0) -> str:
        """Queue a chunk (idempotent). Returns 'cached', 'in_flight', 'queued' or 'updated'."""
        if self.key(coord) in self.cache:
            return "cached"
        if coord in self._in_flight:
            return "in_flight"
        known = self._queued.get(coord)
        if known is not None and known[0] <= priority:
            return "queued"
        seq = next(self._seq)
        self._queued[coord] = (priority, seq, known[2] if known else self._clock())
        heapq.heappush(self._heap, (priority, seq, coord.x, coord.y))
        self.counters["requested" if known is None else "reprioritised"] += 1
        return "queued" if known is None else "updated"

    def cancel(self, coords: Iterable[ChunkCoord]) -> int:
        """Drop queued requests; try to cancel not-yet-started in-flight ones. Returns how many were cancelled."""
        n = 0
        for coord in coords:
            if self._queued.pop(coord, None) is not None:
                n += 1
                self.counters["cancelled_queued"] += 1
            flight = self._in_flight.get(coord)
            if flight is not None and flight[0].cancel():
                del self._in_flight[coord]
                n += 1
                self.counters["cancelled_in_flight"] += 1
        return n

    def set_wanted(self, priorities: dict) -> dict:
        """Make the queue match `priorities` (coord -> priority, lower = sooner): request new/changed, cancel stale. Cached chunks are skipped."""
        stale = [c for c in self._queued if c not in priorities]
        cancelled = self.cancel(stale)
        stale_flight = [c for c in self._in_flight if c not in priorities]
        cancelled += self.cancel(stale_flight)
        for coord, pri in priorities.items():
            self.request(coord, pri)
        return {"cancelled": cancelled, "queued": len(self._queued), "in_flight": len(self._in_flight)}

    def apply_plan(self, plan: StreamPlan, evict_dropped: bool = False) -> dict:
        """Align the queue with what the plan wants (cached chunks cost nothing). The LRU normally decides what stays in memory, so a
        revisited chunk is a cache hit; `evict_dropped=True` additionally frees everything outside the keep ring at once."""
        if evict_dropped:
            for coord in plan.drop:
                self.cache.evict(self.key(coord))
        return self.set_wanted({c: p for c, p in plan.priority.items() if self.key(c) not in self.cache})

    # ------------------------------------------------------------------ pump
    def pump(self) -> list:
        """Collect finished chunks and dispatch queued ones. Never blocks. Returns newly ready Chunks (completion order)."""
        ready: list = []
        self._collect(ready)
        self._dispatch(ready)
        return ready

    def _ensure_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=self.workers)
        return self._executor

    def _dispatch(self, ready: list) -> None:
        if self.workers <= 0:
            for _ in range(self.inline_budget):
                coord = self._pop_next()
                if coord is None:
                    return
                self._run_inline(coord, ready)
            return
        while len(self._in_flight) < self.max_in_flight:
            coord = self._pop_next()
            if coord is None:
                return
            enq = self._queued_time.pop(coord, self._clock())
            args = (self.world_seed, coord.x, coord.y, self.pinned, self.params)
            try:
                future = self._ensure_executor().submit(self._generate, args)
            except BrokenProcessPool:
                self._restart_pool()
                future = self._ensure_executor().submit(self._generate, args)
            self._in_flight[coord] = (future, self._clock(), enq)
            future.add_done_callback(lambda f, c=coord: self._done.append((c, f)))
            self.counters["dispatched"] += 1

    def _pop_next(self) -> Optional[ChunkCoord]:
        while self._heap:
            priority, seq, x, y = heapq.heappop(self._heap)
            coord = ChunkCoord(x, y)
            current = self._queued.get(coord)
            if current is None or current[1] != seq:
                continue                                     # stale heap entry (cancelled or reprioritised)
            del self._queued[coord]
            self._queued_time[coord] = current[2]
            if self.key(coord) in self.cache:
                self._queued_time.pop(coord, None)
                continue
            return coord
        return None

    def _run_inline(self, coord: ChunkCoord, ready: list) -> None:
        enq = self._queued_time.pop(coord, self._clock())
        start = self._clock()
        try:
            _, _, payload, sha, ms = self._generate((self.world_seed, coord.x, coord.y, self.pinned, self.params))
        except Exception as exc:                             # noqa: BLE001 - a failed chunk must never reach the caller's tick
            self.failed[coord] = repr(exc)
            self.counters["failed"] += 1
            return
        self._finish(coord, payload, sha, ms, enq, ready)

    def _collect(self, ready: list) -> None:
        while self._done:
            coord, future = self._done.popleft()
            flight = self._in_flight.pop(coord, None)
            if flight is None or future.cancelled():
                continue
            try:
                _, _, payload, sha, ms = future.result()
            except BrokenProcessPool as exc:
                self.failed[coord] = repr(exc)
                self.counters["failed"] += 1
                self._restart_pool()
                continue
            except Exception as exc:                         # noqa: BLE001
                self.failed[coord] = repr(exc)
                self.counters["failed"] += 1
                continue
            self._finish(coord, payload, sha, ms, flight[2], ready)

    def _finish(self, coord: ChunkCoord, payload: bytes, sha: str, ms: float, enqueued: float, ready: list) -> None:
        chunk = Chunk(coord.x, coord.y, self.world_seed, GENERATOR_VERSION, payload, sha)
        self.cache.put(self.key(coord), chunk)
        self.failed.pop(coord, None)
        self.latency_ms.append((self._clock() - enqueued) * 1000.0)
        self.generation_ms.append(ms)
        self.counters["completed"] += 1
        ready.append(chunk)

    def _restart_pool(self) -> None:
        old, self._executor = self._executor, None
        if old is not None:
            old.shutdown(wait=False, cancel_futures=True)
        for coord, (future, _, enq) in list(self._in_flight.items()):
            self._in_flight.pop(coord, None)
            self.request(coord, 0.0)                         # requeue what the dead pool was holding
        self.counters["pool_restarts"] += 1

    # ------------------------------------------------------------------ reads
    def get(self, coord: ChunkCoord) -> Optional[Chunk]:
        """Cache lookup; counts a hit or a miss and refreshes recency. Never generates."""
        return self.cache.get(self.key(coord))

    def peek(self, coord: ChunkCoord) -> Optional[Chunk]:
        return self.cache.peek(self.key(coord))

    def is_pending(self, coord: ChunkCoord) -> bool:
        return coord in self._queued or coord in self._in_flight

    def pending_count(self) -> int:
        """Chunks requested and not yet finished (queued + in flight): what a pump loop needs to know whether to keep pumping."""
        return len(self._queued) + len(self._in_flight)

    def busy(self) -> bool:
        return self.pending_count() > 0

    def get_blocking(self, coord: ChunkCoord, timeout: float = 30.0) -> Chunk:
        """For tools and tests only: request at top priority and pump until the chunk is ready."""
        hit = self.get(coord)
        if hit is not None:
            return hit
        self.request(coord, -1.0)
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            self.pump()
            hit = self.cache.peek(self.key(coord))
            if hit is not None:
                return hit
            if coord in self.failed and not self.is_pending(coord):
                raise RuntimeError(f"chunk {coord.x}:{coord.y} failed: {self.failed[coord]}")
            time.sleep(0.0005)
        raise TimeoutError(f"chunk {coord.x}:{coord.y} not ready after {timeout}s")

    def warm(self) -> None:
        """Start the worker processes now (they import numpy lazily) so the first real request does not pay for it."""
        if self.workers > 0:
            ex = self._ensure_executor()
            futures = [ex.submit(_noop) for _ in range(self.workers)]
            for f in futures:
                f.result(timeout=60)

    # ------------------------------------------------------------------ misc
    def stats(self) -> dict:
        lat = list(self.latency_ms)
        gms = list(self.generation_ms)
        return {"generator_version": GENERATOR_VERSION, "workers": self.workers, "queued": len(self._queued), "in_flight": len(self._in_flight),
                "failed": len(self.failed), "counters": dict(self.counters), "cache": self.cache.stats(),
                "latency_ms": {"p50": _percentile(lat, 50), "p99": _percentile(lat, 99), "n": len(lat)},
                "generation_ms": {"p50": _percentile(gms, 50), "p99": _percentile(gms, 99), "n": len(gms)}}

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        self._heap.clear()
        self._queued.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _noop() -> int:
    return 0
