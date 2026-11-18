"""Admission control: per-role in-flight cap and requests per game minute, per-resident cooldown, dedupe by causal event id,
bounded escalation depth. Pure bookkeeping; no I/O. ``clock`` returns game seconds (default: monotonic wall seconds)."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque


class Admission:
    def __init__(self, limits: dict, cooldown_s: float = 2.0, max_depth: int = 1, dedupe_size: int = 4096, dedupe_ttl_s: float = 120.0,
                 clock=time.monotonic):
        """``limits``: {role: {"max_in_flight": int, "per_minute": int}}."""
        self.limits = limits
        self.cooldown_s = float(cooldown_s)
        self.max_depth = int(max_depth)
        self.clock = clock
        self._lock = threading.Lock()
        self._in_flight = {role: 0 for role in limits}
        self._starts = {role: deque() for role in limits}
        self._cooldown: dict = {}
        self._seen: OrderedDict = OrderedDict()
        self._dedupe_size = dedupe_size
        self.dedupe_ttl_s = float(dedupe_ttl_s)

    def admit(self, role: str, resident_id: str = "", causal_id: str = "", depth: int = 0, parent_tier: int = 0, tier: int = 0):
        """(True, "") and reserves a slot, or (False, reason). Reasons: escalation_depth, escalation_loop, duplicate, cooldown,
        budget_in_flight, budget_rate."""
        now = self.clock()
        limit = self.limits[role]
        with self._lock:
            if depth > self.max_depth:
                return False, "escalation_depth"
            if parent_tier and tier <= parent_tier:
                return False, "escalation_loop"   # a job spawned by tier t may only target a higher tier
            if causal_id and now - self._seen.get((role, causal_id), -1e18) < self.dedupe_ttl_s:
                return False, "duplicate"
            if resident_id and self.cooldown_s > 0:
                until = self._cooldown.get((role, resident_id), 0.0)
                if now < until:
                    return False, "cooldown"
            if self._in_flight[role] >= limit["max_in_flight"]:
                return False, "budget_in_flight"
            starts = self._starts[role]
            while starts and now - starts[0] >= 60.0:
                starts.popleft()
            if len(starts) >= limit["per_minute"]:
                return False, "budget_rate"
            starts.append(now)
            self._in_flight[role] += 1
            if causal_id:
                self._seen[(role, causal_id)] = now
                while len(self._seen) > self._dedupe_size:
                    self._seen.popitem(last=False)
            if resident_id and self.cooldown_s > 0:
                self._cooldown[(role, resident_id)] = now + self.cooldown_s
                if len(self._cooldown) > 4096:
                    self._cooldown = {k: v for k, v in self._cooldown.items() if v > now}
            return True, ""

    def release(self, role: str) -> None:
        with self._lock:
            self._in_flight[role] = max(0, self._in_flight[role] - 1)

    def forget(self, role: str, causal_id: str) -> None:
        """Allow a causal id to be asked again (used after a toggle drops its job)."""
        with self._lock:
            self._seen.pop((role, causal_id), None)

    def snapshot(self) -> dict:
        with self._lock:
            return {"in_flight": dict(self._in_flight), "started_last_minute": {r: len(s) for r, s in self._starts.items()}}
