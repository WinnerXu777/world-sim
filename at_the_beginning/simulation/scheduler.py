"""Monotonic fixed-step scheduling with bounded catch-up and timing evidence."""
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable


class FixedStepScheduler:
    def __init__(self, hz: float = 20.0, *, max_catch_up: int = 2,
                 clock: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        if not math.isfinite(hz) or hz <= 0 or max_catch_up < 1:
            raise ValueError("A positive finite rate and catch-up limit are required")
        self.hz = hz
        self.max_catch_up = max_catch_up
        self.clock = clock
        self.sleep = sleep
        self._time_scale = 1.0
        self._revision = 0
        self.steps = 0
        self.overruns = 0
        self.dropped_deadlines = 0
        self.work_ms: deque[float] = deque(maxlen=1200)
        self.lateness_ms: deque[float] = deque(maxlen=1200)

    @property
    def time_scale(self) -> float:
        return self._time_scale

    def set_time_scale(self, scale: float) -> None:
        if scale not in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0):
            raise ValueError("Supported time scales: 0, 0.25, 0.5, 1, 2, 4")
        if scale != self._time_scale:
            self._time_scale = float(scale)
            self._revision += 1

    async def run(self, step: Callable[[], None], running: Callable[[], bool]) -> None:
        deadline = self.clock()
        revision = self._revision
        overdue_steps = 0
        while running():
            if revision != self._revision:
                # Resume/speed changes start a new wall-clock schedule, never a backlog.
                deadline = self.clock()
                overdue_steps = 0
                revision = self._revision
            if self.time_scale == 0:
                await self.sleep(1.0 / self.hz)
                continue
            period = 1.0 / (self.hz * self.time_scale)
            delay = deadline - self.clock()
            if delay > 0:
                await self.sleep(delay)
                continue
            started = self.clock()
            self.lateness_ms.append(max(0.0, started - deadline) * 1000.0)
            step()
            finished = self.clock()
            work = max(0.0, finished - started)
            self.work_ms.append(work * 1000.0)
            self.steps += 1
            self.overruns += int(work > period)
            deadline += period
            if deadline <= finished:
                overdue_steps += 1
                if overdue_steps >= self.max_catch_up:
                    missed = math.floor((finished - deadline) / period) + 1
                    self.dropped_deadlines += missed
                    deadline += missed * period
                    overdue_steps = 0
            else:
                overdue_steps = 0
            # Yield even under sustained overload so requests/cancellation get serviced.
            await self.sleep(0)

    def status(self) -> dict:
        def percentiles(samples: deque[float]) -> dict:
            ordered = sorted(samples)
            if not ordered:
                return {"p50": None, "p95": None, "p99": None, "max": None}
            return {**{f"p{p}": round(ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)], 3)
                       for p in (50, 95, 99)}, "max": round(ordered[-1], 3)}
        return {"target_hz": self.hz, "time_scale": self.time_scale,
                "steps": self.steps, "sample_count": len(self.work_ms),
                "overruns": self.overruns, "dropped_deadlines": self.dropped_deadlines,
                "work_ms": percentiles(self.work_ms), "lateness_ms": percentiles(self.lateness_ms)}
